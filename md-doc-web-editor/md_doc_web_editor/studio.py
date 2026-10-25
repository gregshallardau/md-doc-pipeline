"""Document studio APIs: bounded output jobs, snapshot inspection and file tools."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import secrets
import shutil
import sys
import time
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from jinja2 import TemplateError

from .snapshots import make_snapshot, project_files, revision, safe_path, atomic_write
from md_doc.config import _find_repo_root


class SnapshotRequest(BaseModel):
    path: str
    buffers: dict[str, str] = Field(default_factory=dict)
    format: str = "pdf"
    revision: int = 0
    purpose: Literal["preview", "export"] = "preview"
    client: str = Field(default="default", min_length=1, max_length=128)
    visible_page: int = Field(default=1, ge=1, le=10000)


class FileAction(BaseModel):
    action: str
    path: str
    destination: str = ""
    content: str = ""


class ImportRequest(BaseModel):
    name: str
    data: str = Field(max_length=40 * 1024 * 1024)
    images: bool = False


class AssetRequest(BaseModel):
    path: str
    data: str = Field(max_length=15 * 1024 * 1024)


def inspect_snapshot(path: Path, workspace: Path) -> dict[str, Any]:
    from .server import _config_layers, _resolve_css, _find_includes
    from md_doc.config import load_merge_fields

    # Reject invalid YAML rather than rendering with silently dropped settings.
    from md_doc.config import _find_repo_root

    root = _find_repo_root(path.parent)
    current = path.parent
    while current.is_relative_to(root):
        meta = current / "_meta.yml"
        if meta.exists():
            values = yaml.safe_load(meta.read_text())
            if values is not None and not isinstance(values, dict):
                raise ValueError(f"{meta.name} must contain a YAML mapping")
        if current == root:
            break
        current = current.parent
    from .server import _FRONTMATTER_RE

    raw = path.read_text()
    match = _FRONTMATTER_RE.match(raw)
    if match:
        frontmatter = yaml.safe_load(match.group(1))
        if frontmatter is not None and not isinstance(frontmatter, dict):
            raise ValueError("Document frontmatter must contain a YAML mapping")
    elif raw.startswith("---\n"):
        raise ValueError("Frontmatter has no closing --- delimiter")
    result = _config_layers(path, workspace)
    result["theme"] = _resolve_css(path, workspace)
    result["fields"] = load_merge_fields(path)
    result["includes"] = _find_includes(raw, path, workspace)
    result["provenance"] = {
        key: layer["file"] for layer in result["layers"] for key in layer["values"]
    }
    return jsonable_encoder(result)


class PreviewSession:
    """A bounded persistent process, retaining one document's layout cache."""

    def __init__(self, directory):
        self.directory = directory
        self.process = None
        self.lock = asyncio.Lock()
        self.close_lock = asyncio.Lock()
        self.owner = None
        self.log = ""
        self.drain = None
        self.used = time.monotonic()

    async def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "md_doc_web_editor.worker",
            "--persistent",
            str(self.directory),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=2 * 1024 * 1024,
        )
        self.drain = asyncio.create_task(self._drain())

    async def _drain(self):
        process = self.process
        while chunk := await process.stderr.read(4096):
            self.log = (self.log + chunk.decode(errors="replace"))[-12000:]

    async def close(self, owner=None):
        async with self.close_lock:
            # An obsolete job must never kill a newer job sharing the session.
            if owner is not None and self.owner not in (None, owner):
                return
            process, drain = self.process, self.drain
            if process and process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            if drain:
                await drain
            self.process = self.drain = None
            shutil.rmtree(self.directory, ignore_errors=True)
            try:
                self.directory.parent.rmdir()
            except OSError:
                pass

    async def render(self, request, event):
        async with self.lock:
            self.owner = request["job_id"]
            try:
                async with self.close_lock:
                    if not self.process or self.process.returncode is not None:
                        await self.start()
                    process = self.process
                self.used = time.monotonic()
                self.log = ""
                process.stdin.write((json.dumps(request) + "\n").encode())
                await process.stdin.drain()
                while line := await process.stdout.readline():
                    message = json.loads(line)
                    if message["type"] == "error":
                        raise ValueError(message["error"])
                    if message["type"] == "result":
                        self.used = time.monotonic()
                        return message, self.log
                    event(message)
                raise ValueError("Preview worker exited before completing its output")
            finally:
                self.owner = None


class Studio:
    def __init__(self, workspace, build_root, builds):
        self.workspace = workspace
        self.root = build_root
        self.builds = builds
        self.token = secrets.token_urlsafe(32)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.slots = asyncio.Semaphore(2)
        self.sessions: dict[str, PreviewSession] = {}
        self.session_lock = asyncio.Lock()
        self.job_sessions: dict[str, PreviewSession] = {}

    async def preview_session(self, client):
        async with self.session_lock:
            session = self.sessions.get(client)
            if session:
                return session
            if len(self.sessions) >= 2:
                idle = [
                    (key, value) for key, value in self.sessions.items() if not value.lock.locked()
                ]
                if not idle:
                    return None
                key, old = min(idle, key=lambda item: item[1].used)
                self.sessions.pop(key)
                await old.close()
            session = PreviewSession(self.root / ".sessions" / secrets.token_urlsafe(24))
            self.sessions[client] = session
            return session

    async def prune_sessions(self):
        async with self.session_lock:
            for key, session in list(self.sessions.items()):
                if not session.lock.locked() and session.used < time.monotonic() - 1800:
                    self.sessions.pop(key)
                    await session.close()

    async def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            return
        if job["state"] in {"queued", "running"}:
            job["state"] = "cancelled"
            session = self.job_sessions.get(job_id)
            if session:
                await session.close(job_id)
            process = self.processes.get(job_id)
            if process and process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except asyncio.TimeoutError:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
            task = self.tasks.get(job_id)
            if task and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            # Let the runner reap its process and clean its directory.

    async def close(self):
        for job_id in list(self.jobs):
            await self.cancel(job_id)
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        for session in self.sessions.values():
            await session.close()
        self.sessions.clear()

    def page_event(self, job_id, directory, event):
        job = self.jobs[job_id]
        if job["state"] == "cancelled":
            return
        if event["type"] == "reset":
            job["preview_pages"] = []
            job["preview_reset"] = True
        elif event["type"] == "page":
            partial = Path(event["path"]).resolve()
            if not partial.is_relative_to(directory / "output") or not partial.is_file():
                raise ValueError("Invalid progressive preview artifact")
            if partial.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("Preview page exceeds 128 MiB")
            identifier = secrets.token_urlsafe(24)
            self.builds[identifier] = {
                "path": str(partial),
                "filename": partial.name,
                "format": "pdf",
                "expires_at": time.time() + 1800,
            }
            job.setdefault("preview_pages", []).append(
                {
                    "page": event["page"],
                    "url": f"/api/artifacts/{identifier}",
                    "revision": job["revision"],
                    "provisional": True,
                }
            )

    async def run(self, job_id, req, directory, snapshot_workspace):
        job = self.jobs[job_id]
        session = None
        failure: Exception | None = None
        try:
            async with self.slots:
                if job["state"] == "cancelled":
                    return
                job["state"] = "running"
                output = directory / "output"
                output.mkdir()
                session = (
                    await self.preview_session(req.client)
                    if req.format == "pdf" and req.purpose == "preview"
                    else None
                )
                if session:
                    self.job_sessions[job_id] = session
                    try:
                        message, log = await asyncio.wait_for(
                            session.render(
                                {
                                    "job_id": job_id,
                                    "project": str(directory / "project"),
                                    "document": str(
                                        (snapshot_workspace / req.path).relative_to(
                                            directory / "project"
                                        )
                                    ),
                                    "output": str(output),
                                    "visible_page": req.visible_page,
                                },
                                lambda event: self.page_event(job_id, directory, event),
                            ),
                            180,
                        )
                    except asyncio.TimeoutError:
                        await session.close(job_id)
                        raise ValueError(
                            "Rendering exceeded 180 seconds; simplify the document and retry"
                        ) from None
                    except Exception:
                        await session.close(job_id)
                        raise
                    job["render_stats"] = message["stats"]
                    if message["code"]:
                        raise ValueError(
                            next(
                                text
                                for level, text in message["result"]["events"]
                                if level == "error"
                            )
                        )
                    if job["state"] == "cancelled":
                        return
                    self.complete(job_id, directory, output, req.format, log)
                    return
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "md_doc_web_editor.worker",
                    str(snapshot_workspace / req.path),
                    str(directory / "project"),
                    str(output),
                    req.format,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                self.processes[job_id] = process
                if job["state"] == "cancelled" and process.returncode is None:
                    process.terminate()
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), 180)
                except asyncio.TimeoutError:
                    if process.returncode is None:
                        process.kill()
                    await process.communicate()
                    raise ValueError(
                        "Rendering exceeded 180 seconds; simplify the document and retry"
                    )
                if job["state"] == "cancelled":
                    return
                log = (stderr.decode(errors="replace") + "\n" + stdout.decode(errors="replace"))[
                    -12000:
                ]
                job["log"] = log.replace(str(directory / "project"), "[project]")
                if process.returncode:
                    message = "Rendering failed"
                    try:
                        result = json.loads(stdout.decode().strip().splitlines()[-1])
                        message = next(text for level, text in result["events"] if level == "error")
                    except (ValueError, KeyError, IndexError, StopIteration):
                        message = stderr.decode(errors="replace")[-2000:] or message
                    raise ValueError(message.replace(str(directory / "project"), "[project]"))
                self.complete(job_id, directory, output, req.format, log)
        except Exception as exc:
            failure = exc
        finally:
            self.processes.pop(job_id, None)
            self.job_sessions.pop(job_id, None)
            if job["state"] != "succeeded":
                if session:
                    await session.close(job_id)
                shutil.rmtree(directory, ignore_errors=True)
            else:
                # Output is immutable; discard potentially large source snapshots.
                shutil.rmtree(directory / "project", ignore_errors=True)
            # Publish the failure only once the job's files are gone: a client that
            # sees "failed" must never find the job directory still on disk.
            if failure is not None and job["state"] != "cancelled":
                job.update(state="failed", error=str(failure), finished=time.time())

    def complete(self, job_id, directory, output, format_name, log):
        job = self.jobs[job_id]
        job["log"] = log.replace(str(directory / "project"), "[project]")
        artifacts = [
            p
            for p in output.rglob(f"*.{format_name}")
            if not p.name.startswith(".md-doc-preview-page-")
        ]
        if len(artifacts) != 1:
            raise ValueError("Renderer did not produce a single output artifact")
        artifact = artifacts[0]
        if artifact.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("Output artifact exceeds 128 MiB")
        self.builds[job_id] = {
            "path": str(artifact),
            "filename": artifact.name,
            "format": format_name,
            "expires_at": time.time() + 1800,
        }
        job.update(
            state="succeeded",
            artifact={
                "id": job_id,
                "url": f"/api/artifacts/{job_id}",
                "filename": artifact.name,
                "format": format_name,
            },
            finished=time.time(),
        )


def install_studio(app, workspace, build_root, builds, write_lock):
    studio = Studio(workspace, build_root, builds)
    app.state.studio = studio

    def path(relative):
        try:
            return safe_path(workspace, relative)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/lint")
    def lint_workspace(req: SnapshotRequest):
        """Lint the visible workspace snapshot, including unsaved text buffers."""
        if len(req.buffers) > 100:
            raise HTTPException(413, "At most 100 unsaved buffers can be included")
        try:
            with tempfile.TemporaryDirectory(prefix="lint-", dir=build_root) as directory:
                snapshot_workspace, _ = make_snapshot(
                    workspace, Path(directory) / "project", req.buffers
                )
                from md_doc.linter import lint_directory

                source_root = _find_repo_root(workspace)
                depth = len(workspace.relative_to(source_root).parts)
                snapshot_root = (
                    snapshot_workspace.parents[depth - 1] if depth else snapshot_workspace
                )
                results = lint_directory(
                    snapshot_workspace,
                    repo_root=snapshot_root,
                )
                issues = []
                for issue_path, found in sorted(results.items()):
                    relative = issue_path.relative_to(snapshot_workspace).as_posix()
                    for item in found:
                        issues.append(
                            {
                                "path": relative,
                                "severity": item.severity,
                                "message": item.message,
                                "line": getattr(item, "line", None),
                            }
                        )
                import re

                image_ref = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
                for document in snapshot_workspace.rglob("*.md"):
                    if any(
                        part.startswith(".")
                        for part in document.relative_to(snapshot_workspace).parts
                    ):
                        continue
                    for line_number, line in enumerate(
                        document.read_text(errors="replace").splitlines(), 1
                    ):
                        for match in image_ref.finditer(line):
                            target = match.group(1).strip().split()[0].strip("<>")
                            if "://" in target or target.startswith(("data:", "#", "/")):
                                continue
                            resolved = (document.parent / target.split("#", 1)[0]).resolve()
                            if (
                                not resolved.is_relative_to(snapshot_workspace)
                                or not resolved.is_file()
                            ):
                                issues.append(
                                    {
                                        "path": document.relative_to(snapshot_workspace).as_posix(),
                                        "severity": "error",
                                        "message": f"Line {line_number}: image file not found: {target}",
                                        "line": line_number,
                                    }
                                )
                return {"issues": issues, "revision": req.revision, "checked": len(issues)}
        except (ValueError, OSError, yaml.YAMLError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/assets")
    def list_assets():
        return {
            "assets": [
                {"path": p.relative_to(workspace).as_posix(), "name": p.name}
                for p in project_files(workspace)
                if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            ]
        }

    @app.get("/api/capabilities")
    def capabilities():
        return {
            "workspace": str(workspace),
            "name": getattr(app.state, "workspace_info", {}).get("name", workspace.name),
            "remote": getattr(app.state, "workspace_info", {}).get("remote", False),
            "configuredRoot": getattr(app.state, "workspace_info", {}).get("path", str(workspace)),
            "session": studio.token,
            "formats": ["pdf", "docx", "dotx", "pptx"],
            "exactPreview": ["pdf"],
            "snapshotLimitMiB": 128,
            "workers": 2,
            "timeoutSeconds": 180,
            "projectRoot": str(_find_repo_root(workspace)),
        }

    @app.post("/api/outline")
    def outline(req: SnapshotRequest):
        from .outline import document_outline

        full = path(req.path)
        if full.suffix != ".md" or (not full.is_file() and req.path not in req.buffers):
            raise HTTPException(400, "Choose a Markdown document")
        try:
            with tempfile.TemporaryDirectory(prefix="outline-", dir=build_root) as directory:
                snapshot_workspace, _ = make_snapshot(
                    workspace, Path(directory) / "project", req.buffers
                )
                result = document_outline(snapshot_workspace / req.path, snapshot_workspace)
                return {**result, "path": req.path, "revision": req.revision}
        except (ValueError, OSError, TemplateError, RecursionError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/preview/jobs")
    async def create_job(req: SnapshotRequest):
        full = path(req.path)
        if full.suffix != ".md" or (not full.is_file() and req.path not in req.buffers):
            raise HTTPException(400, "Choose a Markdown document to preview")
        if req.format not in {"pdf", "docx", "dotx", "pptx"}:
            raise HTTPException(400, "Unsupported output format")
        if len(req.buffers) > 100:
            raise HTTPException(413, "At most 100 unsaved buffers can be included")
        active = sum(job["state"] in {"queued", "running"} for job in studio.jobs.values())
        if active >= 8:
            raise HTTPException(429, "Render queue is full; retry shortly")
        for identifier, job in list(studio.jobs.items()):
            if job["created"] < time.time() - 1800 and job["state"] not in {"queued", "running"}:
                studio.jobs.pop(identifier, None)
                studio.tasks.pop(identifier, None)
            elif (
                req.purpose == "preview"
                and job.get("client") == req.client
                and job.get("purpose") == "preview"
            ):
                await studio.cancel(identifier)
        identifier = secrets.token_urlsafe(24)
        directory = build_root / identifier
        try:
            snapshot_workspace, fingerprint = await asyncio.to_thread(
                make_snapshot,
                workspace,
                directory / "project",
                req.buffers,
            )
            inspector = inspect_snapshot(snapshot_workspace / req.path, snapshot_workspace)
            # Rewrite snapshot paths to the real inherited project paths for display.
            from md_doc.config import _find_repo_root

            # Compare JSON-escaped paths: json.dumps doubles Windows backslashes.
            snapshot_root = json.dumps(str(directory / "project"))[1:-1]
            real_root = json.dumps(str(_find_repo_root(workspace)))[1:-1]
            inspector = json.loads(json.dumps(inspector).replace(snapshot_root, real_root))
        except (ValueError, OSError, yaml.YAMLError) as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise HTTPException(422, str(exc)) from exc
        job = {
            "id": identifier,
            "state": "queued",
            "path": req.path,
            "revision": req.revision,
            "fingerprint": fingerprint,
            "created": time.time(),
            "purpose": req.purpose,
            "client": req.client,
            "inspection": inspector,
        }
        studio.jobs[identifier] = job
        task = asyncio.create_task(studio.run(identifier, req, directory, snapshot_workspace))
        studio.tasks[identifier] = task
        return JSONResponse(job, status_code=202)

    @app.get("/api/jobs/{identifier}")
    def get_job(identifier: str):
        if identifier not in studio.jobs:
            raise HTTPException(404, "Render job expired")
        return studio.jobs[identifier]

    @app.delete("/api/jobs/{identifier}")
    async def cancel_job(identifier: str):
        await studio.cancel(identifier)
        return {"ok": True}

    @app.get("/api/artifacts/{identifier}")
    def artifact(identifier: str, download: bool = False):
        entry = builds.get(identifier)
        if not entry or entry["expires_at"] < time.time() or not Path(entry["path"]).exists():
            raise HTTPException(404, "Preview expired; refresh to render again")
        entry["expires_at"] = time.time() + 1800
        types = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "dotx": "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        return FileResponse(
            entry["path"],
            media_type=types[entry["format"]],
            filename=entry["filename"],
            content_disposition_type="attachment" if download else "inline",
        )

    @app.get("/api/changes")
    def changes():
        from md_doc.config import _find_repo_root

        files = {}
        for index, full in enumerate(project_files(_find_repo_root(workspace))):
            if index >= 10000:
                break
            stat = full.stat()
            files[str(full)] = [stat.st_mtime_ns, stat.st_size]
        return {"signature": revision(json.dumps(files, sort_keys=True).encode())}

    @app.get("/api/search")
    def search(q: str):
        if not q or len(q) > 200:
            return {"results": []}
        found = []
        for full in project_files(workspace):
            if (
                full.suffix not in {".md", ".css", ".yml", ".yaml"}
                or full.stat().st_size > 2 * 1024 * 1024
            ):
                continue
            for number, line in enumerate(full.read_text(errors="replace").splitlines(), 1):
                if q.casefold() in line.casefold():
                    found.append(
                        {
                            "path": full.relative_to(workspace).as_posix(),
                            "line": number,
                            "text": line[:250],
                        }
                    )
                if len(found) >= 200:
                    return {"results": found, "truncated": True}
        return {"results": found}

    @app.post("/api/assets")
    def upload_asset(req: AssetRequest):
        full = path(req.path)
        if full.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            raise HTTPException(400, "Choose a PNG, JPEG, GIF or WebP image")
        try:
            raw = base64.b64decode(req.data, validate=True)
            if len(raw) > 10 * 1024 * 1024:
                raise ValueError("Image exceeds 10 MiB")
            from PIL import Image

            with Image.open(io.BytesIO(raw)) as image:
                expected = {
                    ".png": "PNG",
                    ".jpg": "JPEG",
                    ".jpeg": "JPEG",
                    ".gif": "GIF",
                    ".webp": "WEBP",
                }
                if image.format != expected[full.suffix.lower()]:
                    raise ValueError("Image type does not match its file extension")
                image.verify()
        except (ValueError, OSError, binascii.Error) as exc:
            raise HTTPException(422, str(exc)) from exc
        with write_lock:
            if full.exists():
                raise HTTPException(
                    409, "An asset already exists at that path; choose a new filename"
                )
            if any(part.startswith(".") for part in Path(req.path).parts):
                raise HTTPException(400, "Assets cannot be stored in hidden directories")
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(raw)
        return {"path": req.path, "bytes": len(raw)}

    @app.post("/api/import")
    def import_document(req: ImportRequest):
        """Convert an uploaded document to Markdown; nothing is written to disk."""
        from md_doc.extractors import (
            SUPPORTED_SUFFIXES,
            extract_document,
            split_embedded_images,
            suggest_frontmatter,
        )

        suffix = Path(req.name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                400, "Choose a Word, PowerPoint, Excel, HTML or PDF file (" + suffix + ")"
            )
        try:
            raw = base64.b64decode(req.data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(422, "The file could not be read") from exc
        if len(raw) > 25 * 1024 * 1024:
            raise HTTPException(413, "File exceeds 25 MiB")
        magic = {".pdf": b"%PDF", ".html": None, ".htm": None}.get(suffix, b"PK\x03\x04")
        if magic and not raw.startswith(magic):
            raise HTTPException(422, f"This is not a valid {suffix[1:].upper()} file")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / f"import{suffix}"
            source.write_bytes(raw)
            try:
                extraction = extract_document(str(source), keep_images=req.images)
            except Exception as exc:  # converter errors vary by format
                raise HTTPException(422, f"Could not convert this file: {exc}") from exc
        markdown = extraction.markdown
        images: list[dict[str, str]] = []
        if req.images:
            markdown, images = split_embedded_images(markdown)
        return {
            "markdown": markdown,
            "format": suffix[1:],
            "images": images,
            "fields": extraction.fields,
            "frontmatter": suggest_frontmatter(req.name, extraction.fields),
        }

    @app.post("/api/files/action")
    def file_action(req: FileAction):
        source = path(req.path)
        destination = path(req.destination) if req.destination else None
        if source == workspace or source.name.startswith("."):
            raise HTTPException(400, "Select a document or folder")
        with write_lock:
            if req.action in {"new", "folder"}:
                if source.exists():
                    raise HTTPException(409, "A file or folder already exists here")
                if not source.parent.is_dir():
                    raise HTTPException(400, "Parent directory does not exist")
                if req.action == "folder":
                    source.mkdir()
                    atomic_write(
                        source / "_meta.yml", "# Settings inherited by documents in this folder\n"
                    )
                else:
                    if source.suffix not in {".md", ".css", ".yml", ".yaml"}:
                        raise HTTPException(400, "Choose a Markdown, YAML or CSS filename")
                    if len(req.content.encode()) > 20 * 1024 * 1024:
                        raise HTTPException(413, "File too large")
                    atomic_write(source, req.content)
            elif req.action in {"rename", "duplicate"}:
                if (
                    not source.is_file()
                    or not destination
                    or destination.exists()
                    or not destination.parent.is_dir()
                ):
                    raise HTTPException(409, "Select an existing file and an unused destination")
                if req.action == "rename":
                    source.rename(destination)
                else:
                    shutil.copy2(source, destination)
            elif req.action == "trash":
                if not source.is_file():
                    raise HTTPException(400, "Only files can be moved to trash")
                trash = workspace / ".editor-trash"
                trash.mkdir(exist_ok=True)
                identifier = secrets.token_hex(12)
                folder = trash / identifier
                folder.mkdir()
                source.rename(folder / source.name)
                (folder / "location.json").write_text(json.dumps({"path": req.path}))
                return {"ok": True, "restore": identifier}
            elif req.action == "restore":
                import re

                if not re.fullmatch(r"[a-f0-9]{24}", req.destination):
                    raise HTTPException(400, "Invalid trash item")
                folder = workspace / ".editor-trash" / req.destination
                if not folder.is_dir() or folder.is_symlink():
                    raise HTTPException(404, "Trash item missing")
                original = path(json.loads((folder / "location.json").read_text())["path"])
                if original.exists():
                    raise HTTPException(409, "Original filename is occupied")
                (folder / original.name).rename(original)
                shutil.rmtree(folder)
            else:
                raise HTTPException(400, "Unknown file action")
        return {
            "ok": True,
            "path": req.destination if req.action in {"rename", "duplicate"} else req.path,
        }
