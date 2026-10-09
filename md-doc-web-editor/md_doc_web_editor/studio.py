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


class FileAction(BaseModel):
    action: str
    path: str
    destination: str = ""
    content: str = ""


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

    async def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            return
        if job["state"] in {"queued", "running"}:
            job["state"] = "cancelled"
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
            # Let the runner reap its process and clean its directory.

    async def close(self):
        for job_id in list(self.jobs):
            await self.cancel(job_id)
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def run(self, job_id, req, directory, snapshot_workspace):
        job = self.jobs[job_id]
        try:
            async with self.slots:
                if job["state"] == "cancelled":
                    return
                job["state"] = "running"
                output = directory / "output"
                output.mkdir()
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
                artifacts = list(output.rglob(f"*.{req.format}"))
                if len(artifacts) != 1:
                    raise ValueError("Renderer did not produce a single output artifact")
                artifact = artifacts[0]
                if artifact.stat().st_size > 128 * 1024 * 1024:
                    raise ValueError("Output artifact exceeds 128 MiB")
                self.builds[job_id] = {
                    "path": str(artifact),
                    "filename": artifact.name,
                    "format": req.format,
                    "expires_at": time.time() + 1800,
                }
                job.update(
                    state="succeeded",
                    artifact={
                        "id": job_id,
                        "url": f"/api/artifacts/{job_id}",
                        "filename": artifact.name,
                        "format": req.format,
                    },
                    finished=time.time(),
                )
        except Exception as exc:
            if job["state"] != "cancelled":
                job.update(state="failed", error=str(exc), finished=time.time())
        finally:
            self.processes.pop(job_id, None)
            if job["state"] != "succeeded":
                shutil.rmtree(directory, ignore_errors=True)
            else:
                # Output is immutable; discard potentially large source snapshots.
                shutil.rmtree(directory / "project", ignore_errors=True)


def install_studio(app, workspace, build_root, builds, write_lock):
    studio = Studio(workspace, build_root, builds)
    app.state.studio = studio

    def path(relative):
        try:
            return safe_path(workspace, relative)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

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

            inspector = json.loads(
                json.dumps(inspector).replace(
                    str(directory / "project"), str(_find_repo_root(workspace))
                )
            )
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
