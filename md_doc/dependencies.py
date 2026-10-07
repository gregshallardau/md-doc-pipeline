"""Conservative dependency signatures for incremental document builds.

Track workspace inputs, including directory membership, so removed fragments and
assets invalidate outputs too. Unrelated input changes may rebuild extra documents.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def signature(root: Path, config: dict[str, Any], extra: list[Path] | None = None) -> str:
    records: list[tuple[str, int, int]] = []
    pending = list(extra or [])
    ignored = {"node_modules", "__pycache__", "dist", "build"}
    outputs = {".pdf", ".docx", ".dotx", ".pptx"}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ignored)
        for name in sorted(files):
            p = Path(directory) / name
            if name.startswith(".") or (p.suffix in outputs and not name.startswith("_")):
                continue
            if p.suffix == ".css":
                pending.append(p)
            try:
                stat = p.stat()
                records.append((str(p), stat.st_mtime_ns, stat.st_size))
            except OSError:
                records.append((str(p), -1, -1))
    # Explicit external themes and their local imports are inputs too.
    if config.get("pdf_theme"):
        pending.append(root / str(config["pdf_theme"]))
    seen: set[Path] = set()
    while pending:
        p = pending.pop().resolve()
        if p in seen:
            continue
        seen.add(p)
        try:
            stat = p.stat()
            records.append((str(p), stat.st_mtime_ns, stat.st_size))
            if p.suffix == ".css":
                import re

                for ref in re.findall(
                    r"""(?:url\(\s*|@import\s+)["']?([^\s"') ;]+)""", p.read_text()
                ):
                    if not ref.startswith(("data:", "http:", "https:", "//")):
                        pending.append(p.parent / ref)
        except OSError:
            records.append((str(p), -1, -1))
    payload = json.dumps([sorted(records), config], sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()
