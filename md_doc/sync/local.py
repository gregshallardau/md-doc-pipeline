"""
Local filesystem sync backend.

Copies built output files to a local directory, preserving relative path structure.

_meta.yml config:
    sync_target: local
    sync_config:
      path: /path/to/output/directory   # required
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable


def make_uploader(root: Path, sync_config: dict[str, Any]) -> Callable[[Path], str]:
    """Return a function that copies one file to the local destination.

    Config (``path``) is validated once here so problems surface before the
    per-file loop rather than being retried. Copies are written atomically
    (temp file + rename) so an interrupted copy can't leave a half-written file.
    """
    dest_root_str = sync_config.get("path")
    if not dest_root_str:
        raise ValueError("local sync backend requires 'path' in sync_config.")

    dest_root = Path(dest_root_str).expanduser().resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    def _upload(src: Path) -> str:
        rel = src.relative_to(root)
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)  # atomic within the same filesystem
        return f"copied  {rel}  →  {dest}"

    return _upload


def sync(files: list[Path], root: Path, sync_config: dict[str, Any]) -> None:
    """Copy *files* to the local destination directory (compat wrapper)."""
    upload = make_uploader(root, sync_config)
    for src in files:
        print(f"  {upload(src)}")
