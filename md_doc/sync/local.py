"""
Local filesystem sync backend.

Copies built output files to a local directory, preserving relative path structure.

_meta.yml config:
    sync_target: local
    sync_config:
      path: /path/to/output/directory   # required
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def sync(files: list[Path], root: Path, sync_config: dict[str, Any]) -> None:
    """
    Copy *files* to the local destination directory.

    Parameters
    ----------
    files:
        Absolute paths of files to copy.
    root:
        Source root (used to compute relative paths for mirroring).
    sync_config:
        Must contain ``path`` — the destination directory.
    """
    dest_root_str = sync_config.get("path")
    if not dest_root_str:
        raise ValueError("local sync backend requires 'path' in sync_config.")

    dest_root = Path(dest_root_str).expanduser().resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    for src in files:
        rel = src.relative_to(root)
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"  copied  {rel}  →  {dest}")
