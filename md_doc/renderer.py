"""
Jinja2 template renderer for Markdown documents.

Processes a Markdown file through Jinja2 before passing rendered content
to the build step. Supports {% include "templates/fragment.md" %} syntax
for document composition from reusable blocks (headers, footers, product
intros, etc.).

All merged config variables from load_config() are available as template
context, plus a special ``include_path`` helper for fragment discovery.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import (
    BaseLoader,
    Environment,
    TemplateNotFound,
    Undefined,
    StrictUndefined,
)

from .config import load_config


class _MarkdownLoader(BaseLoader):
    """
    Jinja2 loader that resolves template paths relative to a list of search
    directories.  Searches in order:

    1. The document's own directory
    2. A ``templates/`` subdirectory inside the document's directory
    3. ``templates/`` subdirectories in each ancestor directory (deepest first)
    4. A ``templates/`` subdirectory at the repo root
    5. Any additional ``search_dirs`` supplied by the caller
    """

    def __init__(self, search_dirs: list[Path]) -> None:
        self._dirs: list[Path] = [Path(d) for d in search_dirs]

    def get_source(self, environment: Environment, template: str) -> tuple[str, str, Any]:
        for directory in self._dirs:
            candidate = directory / template
            if candidate.is_file():
                source = candidate.read_text(encoding="utf-8")
                mtime = candidate.stat().st_mtime
                return source, str(candidate), lambda: candidate.stat().st_mtime == mtime
        raise TemplateNotFound(template)

    def list_templates(self) -> list[str]:  # pragma: no cover
        templates: list[str] = []
        for directory in self._dirs:
            if directory.is_dir():
                for p in directory.rglob("*"):
                    if p.is_file():
                        templates.append(str(p.relative_to(directory)))
        return templates


def _build_search_dirs(doc_path: Path, repo_root: Path) -> list[Path]:
    """Return ordered list of directories to search for included fragments.

    Resolution order (deepest/most-specific first):
    1. Document's own directory  ({% include "fragment.md" %})
    2. doc-local templates/ subdir  ({% include "templates/x.md" %} via local override)
    3. templates/ subdirs in intermediate ancestor dirs (deepest first)
    4. repo root  ({% include "templates/fragment.md" %} resolves to repo_root/templates/...)
    5. repo-root templates/ subdir  ({% include "fragment.md" %} falls back to shared)

    This mirrors the cascading behaviour of ``_meta.yml`` — deeper directories
    take precedence over shallower ones, so a project-level ``templates/``
    overrides the repo-level one.
    """
    doc_dir = doc_path.parent if doc_path.is_file() else doc_path

    # Collect intermediate ancestor dirs between repo_root and doc_dir (exclusive)
    try:
        rel = doc_dir.relative_to(repo_root)
        # Parts from shallowest to deepest, not including repo_root or doc_dir itself
        ancestor_dirs = [repo_root / Path(*rel.parts[:i]) for i in range(1, len(rel.parts))]
    except ValueError:
        ancestor_dirs = []

    dirs: list[Path] = [doc_dir, doc_dir / "templates"]
    # Intermediate ancestor dirs, deepest first.
    # Each ancestor is added both as-is (so "templates/x.md" resolves as
    # ancestor/templates/x.md) and as its templates/ subdir (so "x.md"
    # resolves as ancestor/templates/x.md directly).
    for ancestor in reversed(ancestor_dirs):
        dirs.append(ancestor / "templates")
        dirs.append(ancestor)
    dirs.extend([repo_root / "templates", repo_root])

    return [d for d in dict.fromkeys(dirs)]  # deduplicate, preserve order


def _strip_frontmatter(md_content: str) -> tuple[str, str]:
    """
    Split YAML frontmatter from the body of a Markdown file.

    Returns
    -------
    (frontmatter_block, body)
        ``frontmatter_block`` is the raw ``---\\n...\\n---\\n`` block (or empty
        string if none).  ``body`` is the remaining Markdown.
    """
    pattern = re.compile(r"^(---\s*\n.*?\n---\s*\n)", re.DOTALL)
    match = pattern.match(md_content)
    if match:
        return match.group(1), md_content[match.end() :]
    return "", md_content


def render(
    doc_path: Path,
    repo_root: Path | None = None,
    extra_context: dict[str, Any] | None = None,
    extra_search_dirs: list[Path] | None = None,
    strict: bool = False,
) -> str:
    """
    Render a Markdown file through Jinja2.

    The frontmatter block (if present) is preserved verbatim and is not
    processed through Jinja2 — only the document body is templated.

    Parameters
    ----------
    doc_path:
        Path to the source ``.md`` file.
    repo_root:
        Optional repo root override; auto-detected from ``doc_path`` if omitted.
    extra_context:
        Additional variables to inject into the Jinja2 context (override
        config values if keys collide).
    extra_search_dirs:
        Extra directories to search for included template fragments.
    strict:
        When True, use :class:`~jinja2.StrictUndefined` so any missing
        variable raises an error.  Default is False (silently renders blank).

    Returns
    -------
    str
        Fully rendered Markdown content (frontmatter + rendered body).
    """
    doc_path = Path(doc_path).resolve()

    config = load_config(doc_path, repo_root=repo_root)

    if repo_root is None:
        from .config import _find_repo_root

        repo_root = _find_repo_root(doc_path.parent)
    else:
        repo_root = Path(repo_root).resolve()

    search_dirs = _build_search_dirs(doc_path, repo_root)
    if extra_search_dirs:
        search_dirs = search_dirs + [Path(d) for d in extra_search_dirs]

    loader = _MarkdownLoader(search_dirs)

    undefined_cls = StrictUndefined if strict else Undefined
    env = Environment(
        loader=loader,
        undefined=undefined_cls,
        keep_trailing_newline=True,
        autoescape=False,  # Markdown — no HTML escaping
    )

    raw = doc_path.read_text(encoding="utf-8")
    frontmatter, body = _strip_frontmatter(raw)

    context: dict[str, Any] = dict(config)
    if extra_context:
        context.update(extra_context)

    tmpl = env.from_string(body)
    rendered_body = tmpl.render(**context)

    return frontmatter + rendered_body


def render_string(
    source: str,
    context: dict[str, Any],
    search_dirs: list[Path] | None = None,
    strict: bool = False,
) -> str:
    """
    Render a raw Markdown string through Jinja2.

    Useful for testing or when the source does not live on disk.

    Parameters
    ----------
    source:
        Raw Markdown (may include Jinja2 directives).
    context:
        Template variables.
    search_dirs:
        Directories to search for ``{% include %}`` fragments.
    strict:
        Raise on undefined variables when True.

    Returns
    -------
    str
        Rendered Markdown string.
    """
    undefined_cls = StrictUndefined if strict else Undefined
    loader = _MarkdownLoader(search_dirs or [])
    env = Environment(
        loader=loader,
        undefined=undefined_cls,
        keep_trailing_newline=True,
        autoescape=False,
    )
    tmpl = env.from_string(source)
    return tmpl.render(**context)
