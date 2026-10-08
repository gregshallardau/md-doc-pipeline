"""Isolated, bounded filesystem snapshots shared by inspection and output jobs.

Preserving the project-relative tree lets the existing pipeline resolve metadata,
includes, imports and assets without a second implementation of its cascade.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from md_doc.config import _find_repo_root

TEXT_SUFFIXES = {".md", ".css", ".yml", ".yaml", ".html", ".jinja", ".j2", ".txt", ".csv"}
ASSET_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".pptx",
    ".potx",
}
EXCLUDED = {
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "Exports",
    "md-doc-web-editor",
    "filament-md-doc",
}
MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 10000


def revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def safe_path(workspace: Path, relative: str) -> Path:
    path = (workspace / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(workspace):
        raise ValueError("Path escapes workspace")
    return path


def author_path(workspace: Path, relative: str) -> Path:
    """Project dependency handles allow editing inherited themes and fragments."""
    if not relative.startswith("project:"):
        return safe_path(workspace, relative)
    root = _find_repo_root(workspace)
    handle = relative.removeprefix("project:")
    path = safe_path(root, handle)
    if any(part.startswith(".") for part in Path(handle).parts):
        raise ValueError("Hidden project dependencies cannot be edited")
    if not (
        path.name in {"_meta.yml", "_merge_fields.yml"}
        or path.suffix == ".css"
        or (path.suffix == ".md" and "templates" in Path(handle).parts)
    ):
        raise ValueError("Only inherited metadata, themes and template fragments can be edited")
    return path


def project_files(root: Path):
    """Walk local authoring inputs, excluding secrets, packages and outputs."""
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [
            name
            for name in sorted(dirs)
            if not name.startswith(".")
            and name not in EXCLUDED
            and not (Path(directory) / name).is_symlink()
        ]
        for name in sorted(files):
            path = Path(directory) / name
            if name.startswith(".") or path.is_symlink():
                continue
            if path.suffix.lower() in TEXT_SUFFIXES | ASSET_SUFFIXES:
                yield path


def make_snapshot(workspace: Path, destination: Path, buffers: dict[str, str]) -> tuple[Path, str]:
    root = _find_repo_root(workspace)
    # No project marker: selected workspace is still the minimum context.
    if not workspace.is_relative_to(root):
        root = workspace
    if destination.resolve().is_relative_to(root):
        raise ValueError("Snapshot storage must be outside the source project")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "pyproject.toml").write_text("# Editor snapshot project boundary\n")
    fingerprint = hashlib.sha256()
    size = 0
    count = 0
    for source in project_files(root):
        count += 1
        if count > MAX_FILES:
            raise ValueError("Project exceeds 10,000 snapshot inputs; select a smaller project")
        raw = source.read_bytes()
        original = raw
        size += len(raw)
        if len(raw) > MAX_FILE_BYTES or size > MAX_SNAPSHOT_BYTES:
            raise ValueError("Project exceeds the 128 MiB snapshot or 20 MiB file limit")
        rel = source.relative_to(root)
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in TEXT_SUFFIXES:
            # Absolute project-local references must resolve inside the snapshot.
            raw = raw.replace(str(root).encode(), str(destination).encode())
        target.write_bytes(raw)
        fingerprint.update(str(rel).encode() + original)
    for relative, content in sorted(buffers.items()):
        source = author_path(workspace, relative)
        if source.suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError("Only text authoring buffers can be previewed")
        raw = content.encode()
        size += len(raw)
        if len(raw) > MAX_FILE_BYTES or size > MAX_SNAPSHOT_BYTES:
            raise ValueError("Buffer snapshot is too large")
        target = destination / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw.replace(str(root).encode(), str(destination).encode()))
        fingerprint.update(relative.encode() + raw)
    return destination / workspace.relative_to(root), fingerprint.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    import tempfile

    descriptor, name = tempfile.mkstemp(prefix=".editor-save-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
