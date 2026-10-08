"""Discover the workspaces the editor should offer, without any configuration.

Run from inside an md-doc project and the editor finds, on every request:

* **Local workspaces**: each folder directly under ``<project>/workspace/`` (one per company or
  client library). On a fresh checkout that has none yet, the sample projects under
  ``<project>/examples/`` are offered instead, and failing that the project folder itself.
* **Remote workspaces**: the names in ``<project>/workspace/remote-workspaces.yml`` (the same
  file ``md-doc build -w NAME`` uses), for example a mounted share. One that is not mounted is
  listed as unavailable rather than hidden.

Every workspace becomes a top-level folder of the file tree and is the first path segment of
every API path (``acme/proposals/q1.md``), so the editor itself needs no workspace picker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from md_doc.config import _find_repo_root

_REMOTE_FILE = Path("workspace") / "remote-workspaces.yml"
_SKIP_DIRS = {"__pycache__", "node_modules"}


@dataclass(frozen=True)
class Workspace:
    name: str  # first path segment in the API, also the label in the tree
    root: Path  # resolved directory (may not exist for an unmounted remote)
    remote: bool = False
    available: bool = True
    description: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "remote": self.remote,
            "available": self.available,
            "description": self.description,
            "path": str(self.root),
        }


def _slug(name: str) -> str:
    """A name safe to use as one URL/path segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name)).strip("-.")
    return cleaned or "workspace"


def _unique(name: str, taken: set[str], suffix: str) -> str:
    candidate = _slug(name)
    if candidate in taken:
        candidate = f"{candidate}-{suffix}"
    base, n = candidate, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    taken.add(candidate)
    return candidate


def _subfolders(directory: Path) -> list[Path]:
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    return [
        e
        for e in entries
        if e.is_dir() and not e.name.startswith((".", "_")) and e.name not in _SKIP_DIRS
    ]


def _remote_entries(project: Path) -> list[tuple[str, Path, str]]:
    """``(name, path, description)`` for each entry in ``workspace/remote-workspaces.yml``."""
    file = project / _REMOTE_FILE
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8")) if file.is_file() else None
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[tuple[str, Path, str]] = []
    for name, entry in data.items():
        raw = entry.get("path", "") if isinstance(entry, dict) else entry
        description = str(entry.get("description", "")) if isinstance(entry, dict) else ""
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = project / path
        out.append((str(name), path, description))
    return out


def find_project(start: Path | None = None) -> Path:
    """The md-doc project (repo) root containing *start* (default: the current directory)."""
    return _find_repo_root((start or Path.cwd()).resolve())


def discover(project: Path | None = None) -> list[Workspace]:
    """Every workspace to offer, local first then remote. Never empty."""
    project = find_project(project)
    taken: set[str] = set()
    found: list[Workspace] = []

    local = _subfolders(project / "workspace")
    if not local:
        local = _subfolders(project / "examples")
    if not local:
        local = [project]
    for folder in local:
        found.append(Workspace(_unique(folder.name, taken, "local"), folder.resolve()))

    for name, path, description in _remote_entries(project):
        resolved = path.resolve() if path.exists() else path
        found.append(
            Workspace(
                _unique(name, taken, "remote"),
                resolved,
                remote=True,
                available=resolved.is_dir(),
                description=description,
            )
        )
    return found
