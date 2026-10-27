"""FastAPI server for the md-doc browser editor.

The server is intentionally small.  Five categories of endpoint:

  * ``/api/tree``                — workspace file tree
  * ``/api/file``                — read / write a single file (sandboxed)
  * ``/api/config``, ``/api/css``, ``/api/includes``
                                  — derived data for the right-panel tabs
  * ``/api/refactor/scan``, ``/api/refactor/apply``, ``/api/refactor/ignore``
                                  — find text repeated across documents and move it
                                    into a shared template
  * ``/api/build``               — run ``md-doc build`` and return a token
  * ``/api/build/{token}``       — stream the built PDF/DOCX

The HTML/JS/CSS that drives the SPA lives under ``static/``.
"""

from __future__ import annotations

import re
import os
import shutil
import asyncio
from contextlib import asynccontextmanager
import secrets
import sys
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from md_doc.config import _find_repo_root

from .workspaces import Workspace, discover, find_project

_PACKAGE_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _PACKAGE_DIR / "static"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)

_BUILD_TOKEN_TTL_SECS = 30 * 60


# ── Request models (must live at module level so FastAPI's body-vs-query
# detection picks them up correctly) ─────────────────────────────────────────


class WriteRequest(BaseModel):
    path: str
    content: str
    revision: str | None = None


class RefactorRequest(BaseModel):
    path: str = ""
    min_docs: int = 2
    min_chars: int = 80
    key: str
    name: str
    documents: list[str]
    revisions: dict[str, str]
    folder: str | None = None  # templates folder; default: closest one the documents share


class IgnoreRequest(BaseModel):
    path: str = ""
    key: str
    ignored: bool
    name: str = ""


class ChartSource(BaseModel):
    source: str


class BuildRequest(BaseModel):
    path: str
    format: str = "pdf"


def create_app(
    workspace: Path | None = None,
    *,
    project: Path | None = None,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    """Build a FastAPI app.

    With *workspace* the app is rooted at that one directory and API paths are relative to it.
    Without it the app discovers the project's workspaces (local ``workspace/*`` folders and the
    names in ``workspace/remote-workspaces.yml``) on every request; each is a top-level folder and
    the first segment of every API path. *project* is where discovery starts (default: the
    current directory). *allowed_hosts* restricts the ``Host`` header (blocks DNS rebinding); the
    default ``None`` accepts any host.
    """
    fixed: Workspace | None = None
    if workspace is not None:
        root = Path(workspace).resolve()
        if not root.is_dir():
            raise ValueError(f"Workspace path is not a directory: {root}")
        fixed = Workspace(root.name, root)
    project_root = find_project(project)

    # App-owned storage: an idle sweeper and shutdown cleanup bound disk usage.
    storage = Path(tempfile.gettempdir()) / "md-doc-edit-builds"
    storage.mkdir(mode=0o700, exist_ok=True)
    # Recover abandoned app directories after a crash. Live apps touch their root
    # every minute; allow the full build timeout plus token TTL before removal.
    for orphan in storage.iterdir():
        if (
            not orphan.is_symlink()
            and orphan.is_dir()
            and re.fullmatch(r"[a-f0-9]{32}", orphan.name)
        ):
            if orphan.stat().st_mtime < time.time() - _BUILD_TOKEN_TTL_SECS - 180:
                shutil.rmtree(orphan, ignore_errors=True)
    build_root = storage / secrets.token_hex(16)
    build_root.mkdir(mode=0o700)
    builds: dict[str, dict[str, Any]] = {}
    import threading

    write_lock = threading.RLock()

    def prune_builds() -> None:
        if build_root.exists():
            os.utime(build_root, None)
        for token, entry in list(builds.items()):
            if entry["expires_at"] < time.time():
                builds.pop(token, None)
                shutil.rmtree(build_root / token, ignore_errors=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def sweep() -> None:
            while True:
                prune_builds()
                if hasattr(app.state, "studio"):
                    await app.state.studio.prune_sessions()
                for child in getattr(app.state, "workspace_apps", {}).values():
                    await child.state.studio.prune_sessions()
                await asyncio.sleep(60)

        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            for child in getattr(app.state, "workspace_apps", {}).values():
                await child.state.studio.close()
                shutil.rmtree(child.state.build_root, ignore_errors=True)
            if hasattr(app.state, "studio"):
                await app.state.studio.close()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            shutil.rmtree(build_root, ignore_errors=True)
            builds.clear()

    app = FastAPI(title="md-doc editor", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.builds = builds
    app.state.build_root = build_root

    if allowed_hosts:
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def local_resources_only(request, call_next):
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"detail": "Cross-origin writes are not allowed"}, status_code=403
                )
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(
                    {"detail": "Cross-site writes are not allowed"}, status_code=403
                )
            if (
                origin
                and hasattr(app.state, "studio")
                and request.headers.get("x-editor-token") != app.state.studio.token
            ):
                return JSONResponse(
                    {"detail": "Editor session expired; reload the page"}, status_code=403
                )
        response = await call_next(request)
        # Never load CDN scripts, remote fonts, images, frames or API resources.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
            "frame-src 'self' blob:; object-src 'none'; base-uri 'none'; "
            "form-action 'self'"
        )
        response.headers["X-DNS-Prefetch-Control"] = "off"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if (
            request.url.path.startswith("/api/")
            or request.url.path == "/"
            or (request.url.path.startswith("/static/") and "/vendor/" not in request.url.path)
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ── Path safety ───────────────────────────────────────────────────────────

    def _workspaces() -> list[Workspace]:
        return [fixed] if fixed is not None else discover(project_root)

    def _prefix(ws: Workspace) -> str:
        """Path prefix that identifies *ws* in API paths (none for a fixed single root)."""
        return "" if fixed is not None else f"{ws.name}/"

    def _locate(rel: str) -> tuple[Workspace, Path]:
        """Resolve an API path to its workspace and a file inside it (never outside)."""
        if fixed is not None:
            ws, inner = fixed, rel
        else:
            name, _, inner = rel.strip("/").partition("/")
            ws = next((w for w in _workspaces() if w.name == name), None)  # type: ignore[assignment]
            if ws is None:
                raise HTTPException(status_code=404, detail=f"Unknown workspace '{name}'")
            if not ws.available:
                raise HTTPException(
                    status_code=404, detail=f"Workspace '{name}' is not available (not mounted?)"
                )
        from .snapshots import author_path

        try:
            candidate = author_path(ws.root, inner)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Path escapes workspace") from exc
        return ws, candidate

    def _safe_path(rel: str) -> Path:
        return _locate(rel)[1]

    # ── File tree ─────────────────────────────────────────────────────────────

    def _classify(name: str) -> str | None:
        if name.lower().endswith(".md"):
            return "md"
        if name in ("_meta.yml", "_merge_fields.yml"):
            return "meta"
        if name.lower().endswith(".css"):
            return "css"
        suffix = Path(name).suffix.lower()
        if suffix in {".yml", ".yaml", ".html", ".jinja", ".j2", ".txt", ".csv"}:
            return "meta" if suffix in {".yml", ".yaml"} else "text"
        if suffix == ".pdf":
            return "pdf"
        if suffix in {".docx", ".dotx", ".pptx", ".potx"}:
            return "office"
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
            return "image"
        return None

    def _scan(directory: Path, ws: Workspace, warnings=None) -> list[dict[str, Any]]:
        from .inventory import scan_tree

        return scan_tree(directory, ws.root, _classify, _prefix(ws), warnings=warnings)

    @app.get("/api/tree")
    def get_tree() -> JSONResponse:
        warnings = []
        if fixed is not None:
            tree = _scan(fixed.root, fixed, warnings)
            return JSONResponse(
                {
                    "workspace": str(fixed.root),
                    "tree": tree,
                    "scanWarnings": warnings,
                    "documentCount": sum(
                        node.get("documentCount", int(node["type"] == "md")) for node in tree
                    ),
                }
            )
        listed = _workspaces()
        nodes = [
            {
                "name": ws.name + (" (remote)" if ws.remote else ""),
                "path": ws.name,
                "type": "dir",
                "workspace": True,
                "remote": ws.remote,
                "available": ws.available,
                "children": _scan(ws.root, ws, warnings) if ws.available else [],
            }
            for ws in listed
        ]
        return JSONResponse(
            {
                "workspace": str(project_root),
                "workspaces": [ws.public() for ws in listed],
                "tree": nodes,
                "scanWarnings": warnings,
            }
        )

    # ── Read / write files ───────────────────────────────────────────────────

    @app.get("/api/asset")
    def read_asset(path: str):
        import mimetypes

        full = _safe_path(path)
        if not full.is_file() or _classify(full.name) not in {"pdf", "office", "image"}:
            raise HTTPException(404, "Asset not found")
        media = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
        return FileResponse(
            full,
            media_type=media,
            filename=full.name,
            content_disposition_type=(
                "inline"
                if media == "application/pdf"
                or (media.startswith("image/") and media != "image/svg+xml")
                else "attachment"
            ),
        )

    @app.get("/api/file")
    def read_file(path: str) -> JSONResponse:
        from .snapshots import revision

        full = _safe_path(path)
        if not full.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        content = full.read_bytes()
        return JSONResponse(
            {
                "path": path,
                "content": content.decode("utf-8"),
                "type": _classify(full.name) or "other",
                "revision": revision(content),
            }
        )

    @app.put("/api/file")
    def write_file(req: WriteRequest) -> JSONResponse:
        from .snapshots import atomic_write, preserve_revision, revision

        full = _safe_path(req.path)
        if not full.parent.exists():
            raise HTTPException(status_code=400, detail="Parent directory missing")
        if _classify(full.name) is None:
            raise HTTPException(
                status_code=400, detail="Only document, YAML and CSS files can be edited"
            )
        if len(req.content.encode()) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File exceeds 20 MiB")
        with write_lock:
            original = full.read_bytes() if full.exists() else None
            current = revision(original) if original is not None else None
            if current != req.revision:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "File changed on disk",
                        "revision": current,
                        "content": original.decode("utf-8") if original is not None else "",
                    },
                )
            # Durable recovery copies must succeed before replacing the source.
            if original is not None:
                preserve_revision(full, original)
            preserve_revision(full, req.content.encode("utf-8"))
            atomic_write(full, req.content)
        return JSONResponse(
            {"ok": True, "path": req.path, "revision": revision(req.content.encode())}
        )

    # ── Config cascade panel ──────────────────────────────────────────────────

    @app.get("/api/config")
    def get_config(path: str) -> JSONResponse:
        ws, full = _locate(path)
        return JSONResponse(jsonable_encoder(_config_layers(full, ws.root, _prefix(ws))))

    # ── CSS theme panel ───────────────────────────────────────────────────────

    @app.get("/api/css")
    def get_css(path: str) -> JSONResponse:
        ws, full = _locate(path)
        return JSONResponse(_resolve_css(full, ws.root, _prefix(ws)))

    # ── Chart wizard ──────────────────────────────────────────────────────────

    @app.get("/api/charts/config")
    def chart_config(path: str | None = None) -> JSONResponse:
        """Vega config for the chart wizard's preview, in this document's theme."""
        from md_doc import charts
        from md_doc.mermaid import diagram_theme

        theme = None
        if path:
            ws, full = _locate(path)
            css = _resolve_css(full, ws.root, _prefix(ws))["css"]
            theme = diagram_theme(css) if css else None
        return JSONResponse(charts.vega_config(theme))

    @app.post("/api/charts/parse")
    def chart_parse(req: ChartSource) -> JSONResponse:
        """A chart block's YAML (or JSON) as a spec, so the wizard can read an existing chart back."""
        from md_doc import charts

        try:
            return JSONResponse({"spec": charts.parse_spec(req.source)})
        except charts.ChartError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ── Included templates ────────────────────────────────────────────────────

    @app.get("/api/template")
    def resolve_template(path: str, name: str) -> JSONResponse:
        ws, full = _locate(path)
        if not full.is_file() or full.suffix != ".md":
            raise HTTPException(400, "Select a Markdown document")
        resolved = _resolve_template(name, full, ws.root)
        if resolved is None:
            raise HTTPException(404, "Included template not found")
        if resolved.suffix.lower() not in {".md", ".html", ".jinja", ".j2", ".txt"}:
            raise HTTPException(400, "Only text template fragments can be edited inline")
        relative = (
            _prefix(ws) + resolved.relative_to(ws.root).as_posix()
            if resolved.is_relative_to(ws.root)
            else "project:" + resolved.relative_to(_find_repo_root(full.parent)).as_posix()
        )
        _locate(relative)  # Apply the same authoring boundary as /api/file.
        return JSONResponse({"path": relative, "name": name})

    @app.get("/api/includes")
    def get_includes(path: str) -> JSONResponse:
        ws, full = _locate(path)
        if not full.is_file() or full.suffix != ".md":
            return JSONResponse({"includes": []})
        return JSONResponse(
            {
                "includes": _find_includes(
                    full.read_text(encoding="utf-8"), full, ws.root, _prefix(ws)
                ),
            }
        )

    # ── Shared-content refactor ───────────────────────────────────────────────

    _FRAGMENT_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,60}")
    _IGNORED_FILE = ".editor-ignored-matches.json"

    def _api_path(ws: Workspace, path: Path) -> str:
        return _prefix(ws) + path.relative_to(ws.root).as_posix()

    def _display_path(ws: Workspace, path: Path) -> str:
        """API path for files in the workspace; a project handle for shared templates above it."""
        if path.is_relative_to(ws.root):
            return _api_path(ws, path)
        return "project:" + path.relative_to(_find_repo_root(ws.root)).as_posix()

    def _ignored(ws: Workspace) -> dict[str, Any]:
        import json

        try:
            data = json.loads((ws.root / _IGNORED_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _refactor_groups(path: str, min_docs: int, min_chars: int):
        from md_doc.refactor import find_shared_sections

        ws, folder = _locate(path)
        if not folder.is_dir():
            raise HTTPException(400, "Choose a folder to scan")
        if not 2 <= min_docs <= 100 or not 10 <= min_chars <= 10_000:
            raise HTTPException(400, "Minimum documents or characters out of range")
        return ws, find_shared_sections(folder, min_docs, min_chars)

    @app.get("/api/refactor/scan")
    def refactor_scan(path: str = "", min_docs: int = 2, min_chars: int = 80) -> JSONResponse:
        from md_doc.refactor import _discover

        from .snapshots import revision

        ws, groups = _refactor_groups(path, min_docs, min_chars)
        scanned = len(_discover(_locate(path)[1]))
        ignored = _ignored(ws)
        result = []
        for g in groups:
            lines = g.text.splitlines()
            result.append(
                {
                    "key": g.key,
                    "name": g.name,
                    "existing": g.existing,
                    "ignored": g.key in ignored,
                    "target": _display_path(ws, g.target),
                    "chars": g.chars,
                    "copies": len(g.occurrences),
                    "lines": len(lines),
                    "preview": "\n".join(lines[:8]),
                    "text": g.text[:20_000],
                    "occurrences": [
                        {
                            "path": _api_path(ws, o.doc.path),
                            "line": o.start_line,
                            "endLine": o.end_line,
                            "revision": revision(o.doc.path.read_bytes()),
                        }
                        for o in g.occurrences
                    ],
                }
            )
        return JSONResponse({"scanned": scanned, "groups": result})

    @app.post("/api/refactor/ignore")
    def refactor_ignore(req: IgnoreRequest) -> JSONResponse:
        """Hide (or restore) a match so it moves to the panel's Hidden list."""
        import json

        from .snapshots import atomic_write

        if not re.fullmatch(r"t?[0-9a-f]{15,16}", req.key):
            raise HTTPException(400, "Unknown match")
        ws, _ = _locate(req.path)
        with write_lock:
            data = _ignored(ws)
            if req.ignored:
                data[req.key] = {"name": req.name[:120]}
            else:
                data.pop(req.key, None)
            atomic_write(ws.root / _IGNORED_FILE, json.dumps(data, indent=2, sort_keys=True) + "\n")
        return JSONResponse({"ok": True, "ignored": req.ignored})

    @app.post("/api/refactor/apply")
    def refactor_apply(req: RefactorRequest) -> JSONResponse:
        from md_doc.refactor import apply_groups

        from .snapshots import atomic_write, preserve_revision, revision

        with write_lock:
            ws, groups = _refactor_groups(req.path, req.min_docs, req.min_chars)
            group = next((g for g in groups if g.key == req.key), None)
            if group is None:
                raise HTTPException(409, "This text changed on disk; scan again")
            name = req.name.strip().removesuffix(".md")
            if group.existing:
                if not req.documents:
                    raise HTTPException(400, "Choose at least one document")
            else:
                if not _FRAGMENT_NAME.fullmatch(name) or name.endswith("."):
                    raise HTTPException(
                        400, "Name may use lowercase letters, digits, '-', '_' and '.' only"
                    )
                if len(set(req.documents)) < 2:
                    raise HTTPException(400, "Choose at least two documents")
            chosen = set(req.documents)
            group.occurrences = [
                o for o in group.occurrences if _api_path(ws, o.doc.path) in chosen
            ]
            if {_api_path(ws, o.doc.path) for o in group.occurrences} != chosen:
                raise HTTPException(409, "A chosen document no longer has this text; scan again")
            stale = [
                _api_path(ws, o.doc.path)
                for o in group.occurrences
                if revision(o.doc.path.read_bytes()) != req.revisions.get(_api_path(ws, o.doc.path))
            ]
            if stale:
                raise HTTPException(
                    409, {"message": "Changed on disk since the scan: " + ", ".join(stale)}
                )
            if not group.existing:
                group.name = name
                group.include = f"{name}.md"
                # Includes only resolve from a templates/ folder in the documents' common
                # folder or one of its parents, so those are the only valid locations.
                common = Path(os.path.commonpath([o.doc.path.parent for o in group.occurrences]))
                allowed = [common / "templates"]
                for parent in common.parents:
                    if not parent.is_relative_to(ws.root):
                        break
                    allowed.append(parent / "templates")
                chosen_dir = allowed[0] if req.folder is None else _locate(req.folder)[1]
                if chosen_dir not in allowed:
                    raise HTTPException(
                        400, "Templates must live in a templates folder shared by every document"
                    )
                group.target = chosen_dir / f"{name}.md"
                if group.target.exists():
                    raise HTTPException(409, f"{_api_path(ws, group.target)} already exists")

            def write(target: Path, text: str) -> None:
                if target.exists():
                    preserve_revision(target, target.read_bytes())
                    preserve_revision(target, text.encode("utf-8"))
                atomic_write(target, text)

            try:
                apply_groups([group], _find_repo_root(ws.root), write=write)
            except Exception as exc:
                raise HTTPException(422, f"Nothing was changed: {exc}") from exc
            return JSONResponse(
                {
                    "ok": True,
                    "template": _display_path(ws, group.target),
                    "existing": group.existing,
                    "changed": [
                        {
                            "path": _api_path(ws, o.doc.path),
                            "revision": revision(o.doc.path.read_bytes()),
                        }
                        for o in group.occurrences
                    ],
                }
            )

    # ── Build (calls md-doc CLI as a sidecar) ─────────────────────────────────

    @app.post("/api/build")
    def build(req: BuildRequest) -> JSONResponse:
        """Run ``md-doc build <path> --format <format>`` to a tmp dir and
        return a token the client can exchange for the built file."""
        full = _safe_path(req.path)
        if not full.is_file() or full.suffix != ".md":
            raise HTTPException(status_code=400, detail="path must point to a .md file")
        if req.format not in ("pdf", "docx", "dotx", "pptx"):
            raise HTTPException(status_code=400, detail="invalid format")

        prune_builds()
        token = secrets.token_urlsafe(24)
        tmp_dir = build_root / token
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "md_doc",
                    "build",
                    str(full),
                    "--output",
                    str(tmp_dir),
                    "--format",
                    req.format,
                    "--no-lint",
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except OSError as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(
                status_code=500,
                detail=f"Could not launch pipeline with editor Python: {exc}",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=504, detail="build timed out") from exc

        if proc.returncode != 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            stderr = (proc.stderr or proc.stdout or "").strip()
            raise HTTPException(status_code=500, detail=f"build failed: {stderr[-2000:]}")

        # Find the produced file (any .pdf/.docx/.dotx under tmp_dir)
        ext = req.format
        found: Path | None = None
        for candidate in tmp_dir.rglob(f"*.{ext}"):
            found = candidate
            break
        if found is None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail="build succeeded but no output file found")

        builds[token] = {
            "path": str(found),
            "filename": found.name,
            "format": ext,
            "expires_at": time.time() + _BUILD_TOKEN_TTL_SECS,
        }
        return JSONResponse({"token": token, "filename": found.name, "format": ext})

    @app.get("/api/build/{token}")
    def serve_build(token: str) -> FileResponse:
        prune_builds()
        entry = builds.get(token)
        if entry is None or entry["expires_at"] < time.time():
            raise HTTPException(status_code=404, detail="build expired or unknown")
        # Give an accepted download a fresh lease before constructing the response.
        entry["expires_at"] = time.time() + _BUILD_TOKEN_TTL_SECS
        path = Path(entry["path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="build artefact missing")
        media = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "dotx": "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
        }[entry["format"]]
        return FileResponse(
            path,
            media_type=media,
            filename=entry["filename"],
            content_disposition_type="inline" if entry["format"] == "pdf" else "attachment",
        )

    # ── Static + index ────────────────────────────────────────────────────────

    from .studio import install_studio

    install_studio(
        app, fixed.root if fixed else discover(project_root)[0].root, build_root, builds, write_lock
    )
    from .git_api import install_git

    install_git(app, fixed.root if fixed else discover(project_root)[0].root, write_lock)

    from .static_assets import EditorStaticFiles

    app.mount("/static", EditorStaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    from .discovery import install_discovery

    install_discovery(app, project_root, create_app, fixed=fixed)
    return app


# ── Module-level helpers (kept top-level so tests can import them) ───────────


def _parse_frontmatter(text: str) -> dict[str, Any]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        parsed = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _config_layers(doc_path: Path, workspace: Path, prefix: str = "") -> dict[str, Any]:
    """Walk repo root → doc dir collecting _meta.yml, then frontmatter."""
    repo_root = _find_repo_root(doc_path.parent)
    merged: dict[str, Any] = {}
    layers: list[dict[str, Any]] = []

    dirs: list[Path] = []
    current = doc_path.parent
    while True:
        dirs.append(current)
        if current.resolve() == repo_root.resolve():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    dirs.reverse()  # root first → highest-priority later

    for d in dirs:
        meta = d / "_meta.yml"
        if meta.exists() and meta.resolve().is_relative_to(repo_root):
            try:
                parsed = yaml.safe_load(meta.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                parsed = None
            if isinstance(parsed, dict) and parsed:
                rel = (
                    prefix + meta.relative_to(workspace).as_posix()
                    if meta.is_relative_to(workspace)
                    else str(meta)
                )
                layers.append({"file": rel, "values": parsed})
                merged.update(parsed)

    if doc_path.suffix == ".md" and doc_path.exists():
        fm = _parse_frontmatter(doc_path.read_text(encoding="utf-8"))
        if fm:
            layers.append({"file": "frontmatter", "values": fm})
            merged.update(fm)

    return {"merged": merged, "layers": layers}


_CSS_IMPORT_RE = re.compile(r"""@import\s+(?:url\(\s*)?['"]([^'"]+)['"]\s*\)?\s*;""")
_MAX_CSS_IMPORT_DEPTH = 5


def _inline_css_imports(path: Path, workspace: Path, depth: int = 0) -> str:
    """Return *path*'s CSS with ``@import 'file.css';`` replaced by that file's contents.

    The PDF builder follows relative ``@import`` chains, but a preview iframe cannot,
    so a theme written as ``@import '_theme.css';`` would render unstyled. Imports are
    only followed inside the workspace (never outside it) and to a bounded depth.
    """
    css = path.read_text(encoding="utf-8")
    if depth >= _MAX_CSS_IMPORT_DEPTH:
        return _CSS_IMPORT_RE.sub("", css)

    def replace(match: re.Match[str]) -> str:
        target = (path.parent / match.group(1)).resolve()
        if target.is_file() and target.is_relative_to(workspace):
            return _inline_css_imports(target, workspace, depth + 1) + "\n"
        return ""

    return _CSS_IMPORT_RE.sub(replace, css)


def _resolve_css(doc_path: Path, workspace: Path, prefix: str = "") -> dict[str, Any]:
    """Walk up from doc_path looking for a theme CSS file."""
    root = _find_repo_root(doc_path.parent)
    config = _config_layers(doc_path, workspace)["merged"]
    explicit = config.get("pdf_theme")
    if explicit:
        selected = (root / str(explicit)).resolve()
        if selected.is_relative_to(root) and selected.is_file():
            return {
                "css": _inline_css_imports(selected, root),
                "source": (
                    prefix + selected.relative_to(workspace).as_posix()
                    if selected.is_relative_to(workspace)
                    else str(selected)
                ),
            }
    candidates = ("_pdf-theme.css", "_theme.css")
    current = doc_path.parent
    while True:
        for name in candidates:
            f = current / name
            if f.is_file() and f.resolve().is_relative_to(root):
                rel = (
                    prefix + f.relative_to(workspace).as_posix()
                    if f.is_relative_to(workspace)
                    else str(f)
                )
                return {"css": _inline_css_imports(f, root), "source": rel}
        if current.resolve() == root.resolve():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return {"css": "", "source": None}


def _find_includes(
    content: str, doc_path: Path, workspace: Path, prefix: str = ""
) -> list[dict[str, Any]]:
    names = re.findall(r"\{%-?\s*include\s+[\"']([^\"']+)[\"']\s*-?%\}", content)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        resolved = _resolve_template(name, doc_path, workspace)
        rel: str | None = None
        if resolved is not None and resolved.is_relative_to(workspace):
            rel = prefix + resolved.relative_to(workspace).as_posix()
        elif resolved is not None:
            rel = "project:" + resolved.relative_to(_find_repo_root(doc_path.parent)).as_posix()
        out.append({"name": name, "path": rel, "found": resolved is not None})
    return out


def _resolve_template(name: str, doc_path: Path, workspace: Path) -> Path | None:
    from md_doc.renderer import _MarkdownLoader, _build_search_dirs
    from jinja2 import Environment, TemplateNotFound

    try:
        root = _find_repo_root(doc_path.parent)
        for directory in _build_search_dirs(doc_path, root):
            candidate = directory / name
            # Snapshot inputs never follow symlinks; inspection follows the same rule.
            if any(part.is_symlink() for part in [candidate, *candidate.parents]):
                continue
            try:
                _, filename, _ = _MarkdownLoader([directory], [root]).get_source(
                    Environment(), name
                )
            except TemplateNotFound:
                continue
            resolved = Path(filename).resolve()
            return resolved if resolved.is_relative_to(root) else None
        return None
    except TemplateNotFound:
        return None
