"""FastAPI server for the md-doc browser editor.

The server is intentionally small.  Five categories of endpoint:

  * ``/api/tree``                — workspace file tree
  * ``/api/file``                — read / write a single file (sandboxed)
  * ``/api/config``, ``/api/css``, ``/api/includes``
                                  — derived data for the right-panel tabs
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
from fastapi.staticfiles import StaticFiles
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


class BuildRequest(BaseModel):
    path: str
    format: str = "pdf"


def create_app(workspace: Path | None = None, *, project: Path | None = None) -> FastAPI:
    """Build a FastAPI app.

    With *workspace* the app is rooted at that one directory and API paths are relative to it.
    Without it the app discovers the project's workspaces (local ``workspace/*`` folders and the
    names in ``workspace/remote-workspaces.yml``) on every request; each is a top-level folder and
    the first segment of every API path. *project* is where discovery starts (default: the
    current directory).
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
                await asyncio.sleep(60)

        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
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

    @app.middleware("http")
    async def local_resources_only(request, call_next):
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
        candidate = (ws.root / inner).resolve()
        try:
            candidate.relative_to(ws.root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Path escapes workspace") from exc
        return ws, candidate

    def _safe_path(rel: str) -> Path:
        return _locate(rel)[1]

    # ── File tree ─────────────────────────────────────────────────────────────

    def _classify(name: str) -> str | None:
        if name.endswith(".md"):
            return "md"
        if name in ("_meta.yml", "_merge_fields.yml"):
            return "meta"
        if name.endswith(".css"):
            return "css"
        return None

    def _scan(directory: Path, ws: Workspace) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except OSError:
            return items
        for entry in entries:
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            rel = _prefix(ws) + entry.relative_to(ws.root).as_posix()
            if entry.is_dir():
                items.append(
                    {
                        "name": entry.name,
                        "path": rel,
                        "type": "dir",
                        "children": _scan(entry, ws),
                    }
                )
            else:
                kind = _classify(entry.name)
                if kind is not None:
                    items.append({"name": entry.name, "path": rel, "type": kind})
        return items

    @app.get("/api/tree")
    def get_tree() -> JSONResponse:
        if fixed is not None:
            return JSONResponse({"workspace": str(fixed.root), "tree": _scan(fixed.root, fixed)})
        listed = _workspaces()
        nodes = [
            {
                "name": ws.name + (" (remote)" if ws.remote else ""),
                "path": ws.name,
                "type": "dir",
                "workspace": True,
                "remote": ws.remote,
                "available": ws.available,
                "children": _scan(ws.root, ws) if ws.available else [],
            }
            for ws in listed
        ]
        return JSONResponse(
            {
                "workspace": str(project_root),
                "workspaces": [ws.public() for ws in listed],
                "tree": nodes,
            }
        )

    # ── Read / write files ───────────────────────────────────────────────────

    @app.get("/api/file")
    def read_file(path: str) -> JSONResponse:
        full = _safe_path(path)
        if not full.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return JSONResponse(
            {
                "path": path,
                "content": full.read_text(encoding="utf-8"),
                "type": _classify(full.name) or "other",
            }
        )

    @app.put("/api/file")
    def write_file(req: WriteRequest) -> JSONResponse:
        full = _safe_path(req.path)
        if not full.parent.exists():
            raise HTTPException(status_code=400, detail="Parent directory missing")
        full.write_text(req.content, encoding="utf-8")
        return JSONResponse({"ok": True, "path": req.path})

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

    # ── Included templates ────────────────────────────────────────────────────

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

    # ── Build (calls md-doc CLI as a sidecar) ─────────────────────────────────

    @app.post("/api/build")
    def build(req: BuildRequest) -> JSONResponse:
        """Run ``md-doc build <path> --format <format>`` to a tmp dir and
        return a token the client can exchange for the built file."""
        full = _safe_path(req.path)
        if not full.is_file() or full.suffix != ".md":
            raise HTTPException(status_code=400, detail="path must point to a .md file")
        if req.format not in ("pdf", "docx", "dotx"):
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

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

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
    """Walk up from doc_path to the theme the PDF builder would use.

    At each folder ``_pdf-theme.css`` comes before the shared ``_theme.css``; the
    Word-only ``_docx-theme.css`` is not a PDF theme and is ignored. ``@import``s are
    inlined so the preview matches the PDF.
    """
    candidates = ("_pdf-theme.css", "_theme.css")
    workspace = workspace.resolve()
    current = doc_path.parent
    while True:
        for name in candidates:
            f = current / name
            if f.is_file() and f.resolve().is_relative_to(workspace):
                rel = prefix + f.resolve().relative_to(workspace).as_posix()
                return {"css": _inline_css_imports(f.resolve(), workspace), "source": rel}
        if current.resolve() == workspace:
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
        out.append({"name": name, "path": rel, "found": resolved is not None})
    return out


def _resolve_template(name: str, doc_path: Path, workspace: Path) -> Path | None:
    from md_doc.renderer import _MarkdownLoader, _build_search_dirs
    from jinja2 import Environment, TemplateNotFound

    try:
        _, filename, _ = _MarkdownLoader(
            _build_search_dirs(doc_path, workspace), [workspace]
        ).get_source(Environment(), name)
        resolved = Path(filename).resolve()
        return resolved if resolved.is_relative_to(workspace) else None
    except TemplateNotFound:
        return None
