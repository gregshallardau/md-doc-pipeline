"""
Pluggable sync module for md-doc-pipeline.

Syncs built output files (PDF, DOCX, and optionally .md) to a remote or local
destination. Backend and destination are configured via _meta.yml:

    sync_target: azure   # "azure", "s3", or "local"
    sync_config:
      # backend-specific keys (see each backend module)

The ``include_md_in_share`` config key controls whether .md source files are
included in the sync output (default: false).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config import load_config, should_sync_md

# Extensions treated as "built outputs" to always include
_OUTPUT_EXTENSIONS: set[str] = {".pdf", ".docx"}

# Directories to exclude from sync discovery
_EXCLUDE_DIRS: set[str] = {".git", "__pycache__", "themes", "templates"}


def _collect_files(root: Path, include_md: bool) -> list[Path]:
    """Return the list of files to sync under root."""
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # Skip excluded directories
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        # Skip _meta.yml files and hidden files
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        if path.suffix in _OUTPUT_EXTENSIONS:
            files.append(path)
        elif include_md and path.suffix == ".md":
            files.append(path)
    return files


def _get_backend_name(root: Path, cli_backend: str | None) -> str:
    """Resolve the backend name from CLI arg or root config."""
    if cli_backend:
        return cli_backend.lower()
    config = load_config(root)
    target = config.get("sync_target")
    if not target:
        raise ValueError(
            "No sync backend specified. Set 'sync_target' in _meta.yml or use --backend."
        )
    return str(target).lower()


def run(root: Path, backend: str | None = None, dry_run: bool = False) -> None:
    """
    Sync built documents under *root* to the configured storage backend.

    Parameters
    ----------
    root:
        Directory to scan for built output files.
    backend:
        Override backend name ("azure", "s3", "local"). If omitted, read from
        ``sync_target`` in the cascading _meta.yml config.
    dry_run:
        If True, print what would be synced without uploading anything.
    """
    root = Path(root).resolve()

    # Load root config for sync settings
    config = load_config(root)
    include_md = should_sync_md(config)
    sync_config: dict[str, Any] = config.get("sync_config", {}) or {}

    backend_name = _get_backend_name(root, backend)

    files = _collect_files(root, include_md)
    if not files:
        print(f"No files to sync under {root}")
        return

    print(f"Backend: {backend_name}")
    print(f"Files to sync ({len(files)}):")
    for f in files:
        print(f"  {f.relative_to(root)}")

    if dry_run:
        return

    if backend_name == "local":
        from .local import sync as _sync
    elif backend_name == "azure":
        from .azure_files import sync as _sync  # type: ignore[import]
    elif backend_name == "s3":
        from .s3 import sync as _sync  # type: ignore[import]
    else:
        raise ValueError(f"Unknown sync backend: {backend_name!r}. Choose from: azure, s3, local.")

    _sync(files, root=root, sync_config=sync_config)
