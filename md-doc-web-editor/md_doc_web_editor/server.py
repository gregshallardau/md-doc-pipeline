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
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from md_doc.config import _find_repo_root

_PACKAGE_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _PACKAGE_DIR / "static"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)

# In-memory build artefact cache: token → (file path, expiry timestamp)
_BUILD_TOKEN_TTL_SECS = 30 * 60
_BUILDS: dict[str, dict[str, Any]] = {}


# ── Request models (must live at module level so FastAPI's body-vs-query
# detection picks them up correctly) ─────────────────────────────────────────


class WriteRequest(BaseModel):
    path: str
    content: str


class BuildRequest(BaseModel):
    path: str
    format: str = "pdf"


def create_app(workspace: Path) -> FastAPI:
    """Build a FastAPI app rooted at ``workspace``."""
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError(f"Workspace path is not a directory: {workspace}")

    app = FastAPI(title="md-doc editor", docs_url=None, redoc_url=None)

    # ── Path safety ───────────────────────────────────────────────────────────

    def _safe_path(rel: str) -> Path:
        candidate = (workspace / rel).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Path escapes workspace") from exc
        return candidate

    # ── File tree ─────────────────────────────────────────────────────────────

    def _classify(name: str) -> str | None:
        if name.endswith(".md"):
            return "md"
        if name in ("_meta.yml", "_merge_fields.yml"):
            return "meta"
        if name.endswith(".css"):
            return "css"
        return None

    def _scan(directory: Path) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except OSError:
            return items
        for entry in entries:
            if entry.name.startswith("."):
                continue
            rel = entry.relative_to(workspace).as_posix()
            if entry.is_dir():
                items.append(
                    {
                        "name": entry.name,
                        "path": rel,
                        "type": "dir",
                        "children": _scan(entry),
                    }
                )
            else:
                kind = _classify(entry.name)
                if kind is not None:
                    items.append({"name": entry.name, "path": rel, "type": kind})
        return items

    @app.get("/api/tree")
    def get_tree() -> JSONResponse:
        return JSONResponse({"workspace": str(workspace), "tree": _scan(workspace)})

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
        full = _safe_path(path)
        return JSONResponse(_config_layers(full, workspace))

    # ── CSS theme panel ───────────────────────────────────────────────────────

    @app.get("/api/css")
    def get_css(path: str) -> JSONResponse:
        full = _safe_path(path)
        return JSONResponse(_resolve_css(full, workspace))

    # ── Included templates ────────────────────────────────────────────────────

    @app.get("/api/includes")
    def get_includes(path: str) -> JSONResponse:
        full = _safe_path(path)
        if not full.is_file() or full.suffix != ".md":
            return JSONResponse({"includes": []})
        return JSONResponse(
            {
                "includes": _find_includes(full.read_text(encoding="utf-8"), full, workspace),
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

        token = secrets.token_urlsafe(24)
        tmp_dir = Path(tempfile.gettempdir()) / "md-doc-edit-builds" / token
        tmp_dir.mkdir(parents=True, exist_ok=True)

        bin_path = shutil.which("md-doc") or "md-doc"
        try:
            proc = subprocess.run(
                [
                    bin_path,
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
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"md-doc CLI not on PATH: {exc}",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="build timed out") from exc

        if proc.returncode != 0:
            stderr = (proc.stderr or proc.stdout or "").strip()
            raise HTTPException(status_code=500, detail=f"build failed: {stderr[-2000:]}")

        # Find the produced file (any .pdf/.docx/.dotx under tmp_dir)
        ext = req.format
        found: Path | None = None
        for candidate in tmp_dir.rglob(f"*.{ext}"):
            found = candidate
            break
        if found is None:
            raise HTTPException(status_code=500, detail="build succeeded but no output file found")

        _BUILDS[token] = {
            "path": str(found),
            "filename": found.name,
            "format": ext,
            "expires_at": time.time() + _BUILD_TOKEN_TTL_SECS,
        }
        return JSONResponse({"token": token, "filename": found.name, "format": ext})

    @app.get("/api/build/{token}")
    def serve_build(token: str) -> FileResponse:
        entry = _BUILDS.get(token)
        if entry is None or entry["expires_at"] < time.time():
            raise HTTPException(status_code=404, detail="build expired or unknown")
        path = Path(entry["path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="build artefact missing")
        media = (
            "application/pdf"
            if entry["format"] == "pdf"
            else ("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        )
        return FileResponse(
            path,
            media_type=media,
            filename=entry["filename"],
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


def _config_layers(doc_path: Path, workspace: Path) -> dict[str, Any]:
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
        if meta.exists():
            try:
                parsed = yaml.safe_load(meta.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                parsed = None
            if isinstance(parsed, dict) and parsed:
                rel = (
                    meta.relative_to(workspace).as_posix()
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


def _resolve_css(doc_path: Path, workspace: Path) -> dict[str, Any]:
    """Walk up from doc_path looking for a theme CSS file."""
    candidates = ("_pdf-theme.css", "_docx-theme.css", "_theme.css")
    current = doc_path.parent
    while True:
        for name in candidates:
            f = current / name
            if f.exists():
                rel = f.relative_to(workspace).as_posix() if f.is_relative_to(workspace) else str(f)
                return {"css": f.read_text(encoding="utf-8"), "source": rel}
        if current.resolve() == workspace.resolve():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return {"css": "", "source": None}


def _find_includes(content: str, doc_path: Path, workspace: Path) -> list[dict[str, Any]]:
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
            rel = resolved.relative_to(workspace).as_posix()
        out.append({"name": name, "path": rel, "found": resolved is not None})
    return out


def _resolve_template(name: str, doc_path: Path, workspace: Path) -> Path | None:
    doc_dir = doc_path.parent
    search = [doc_dir, doc_dir / "templates"]
    current = doc_dir.parent
    while True:
        search.append(current / "templates")
        if current.resolve() == workspace.resolve():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    for d in search:
        candidate = d / name
        if candidate.exists():
            return candidate.resolve()
    return None
