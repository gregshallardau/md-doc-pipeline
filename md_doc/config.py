"""
Cascading _meta.yml config inheritance system.

Walks from repo root to document directory, merging all _meta.yml files.
Deeper files override parent values. Document-level frontmatter overrides everything.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict on missing or parse error."""
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as exc:
        logger.warning("Ignoring malformed YAML in %s: %s", path, exc)
        return {}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge: override values take precedence over base values."""
    result = dict(base)
    result.update(override)
    return result


def _extract_frontmatter(md_path: Path) -> dict[str, Any]:
    """
    Extract YAML frontmatter from a Markdown file.

    Frontmatter is delimited by ``---`` lines at the start of the file.
    Returns an empty dict if no frontmatter is present.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    pattern = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
    match = pattern.match(text)
    if not match:
        return {}

    try:
        data = yaml.safe_load(match.group(1))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as exc:
        logger.warning("Ignoring malformed frontmatter in %s: %s", md_path, exc)
        return {}


def _find_repo_root(start: Path) -> Path:
    """
    Walk up from *start* looking for a project-root marker.

    A ``.git`` directory or ``pyproject.toml`` is the strongest signal and wins
    immediately.  Failing that, the **topmost** ancestor containing a
    ``_meta.yml`` marks the ceiling of the config cascade — this lets md-doc
    projects that don't live in a VCS repo (just a tree of ``_meta.yml`` files)
    resolve the same root whether you build the whole directory *or a single
    file inside it*.  Without this, a single-file build in a non-git project
    would fall back to the document's own directory and silently drop every
    parent ``_meta.yml`` (author, theme, outputs …) from the cascade.

    Falls back to *start* itself if no marker is found anywhere.
    """
    current = start.resolve()
    topmost_meta: Path | None = None
    while True:
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            return current
        if (current / "_meta.yml").exists():
            topmost_meta = current  # keep climbing — we want the *highest* one
        parent = current.parent
        if parent == current:
            # Reached filesystem root without a VCS marker; use the highest
            # _meta.yml if we saw one, else the starting point.
            return topmost_meta or start.resolve()
        current = parent


def load_config(doc_path: Path, repo_root: Path | None = None) -> dict[str, Any]:
    """
    Build the merged config for *doc_path* (a Markdown file or directory).

    Resolution order (later overrides earlier):
      1. ``_meta.yml`` at repo root
      2. ``_meta.yml`` files in each directory between root and doc_path
      3. YAML frontmatter inside doc_path (if it is a .md file)

    Parameters
    ----------
    doc_path:
        Path to the target Markdown file or the directory containing it.
    repo_root:
        Optional override for the repo root. Auto-detected if not supplied.

    Returns
    -------
    dict
        Merged configuration. Key fields to expect:

        - ``title``           – document title
        - ``product``         – product / client name
        - ``version``         – version string
        - ``outputs``         – list of output formats, e.g. ``["pdf", "docx"]``
        - ``output_filename``  – output filename stem (no extension); supports Jinja2 variables;
                               extension is appended automatically per format
        - ``include_md_in_share`` – bool, whether to include .md source in sync
    """
    doc_path = Path(doc_path).resolve()

    if doc_path.is_file():
        doc_dir = doc_path.parent
    else:
        doc_dir = doc_path

    if repo_root is None:
        repo_root = _find_repo_root(doc_dir)
    else:
        repo_root = Path(repo_root).resolve()

    # Collect all directories from root → doc_dir (inclusive)
    try:
        rel = doc_dir.relative_to(repo_root)
        parts = [repo_root] + [
            repo_root / Path(*rel.parts[:i]) for i in range(1, len(rel.parts) + 1)
        ]
    except ValueError:
        # doc_dir is not under repo_root – just use doc_dir alone
        parts = [doc_dir]

    # Merge _meta.yml files from shallowest to deepest
    merged: dict[str, Any] = {}
    for directory in parts:
        meta_file = directory / "_meta.yml"
        layer = _load_yaml_file(meta_file)
        merged = _merge(merged, layer)

    # Document frontmatter overrides everything
    if doc_path.is_file() and doc_path.suffix == ".md":
        frontmatter = _extract_frontmatter(doc_path)
        merged = _merge(merged, frontmatter)

    return merged


def load_merge_fields(doc_path: Path, repo_root: Path | None = None) -> dict[str, Any]:
    """
    Build the merged ``[[field]]`` schema for *doc_path*.

    Walks from repo root to the document's directory, loading each
    ``_merge_fields.yml`` file it finds and merging them additively.
    Deeper files override shallower ones when the same key appears.

    Parameters
    ----------
    doc_path:
        Path to the target Markdown file or its directory.
    repo_root:
        Optional repo root override.  Auto-detected if not supplied.

    Returns
    -------
    dict
        Mapping of field name → description string.
    """
    doc_path = Path(doc_path).resolve()
    doc_dir = doc_path.parent if doc_path.is_file() else doc_path

    if repo_root is None:
        repo_root = _find_repo_root(doc_dir)
    else:
        repo_root = Path(repo_root).resolve()

    try:
        rel = doc_dir.relative_to(repo_root)
        parts = [repo_root] + [
            repo_root / Path(*rel.parts[:i]) for i in range(1, len(rel.parts) + 1)
        ]
    except ValueError:
        parts = [doc_dir]

    merged: dict[str, Any] = {}
    for directory in parts:
        layer = _load_yaml_file(directory / "_merge_fields.yml")
        merged = _merge(merged, layer)

    return merged


def get_output_formats(config: dict[str, Any]) -> list[str]:
    """Return the list of output formats from config (defaults to ['pdf'])."""
    outputs = config.get("outputs", ["pdf"])
    if isinstance(outputs, str):
        return [outputs]
    return list(outputs)


def should_sync_md(config: dict[str, Any]) -> bool:
    """Return True if .md source files should be included in sync output."""
    return bool(config.get("include_md_in_share", False))
