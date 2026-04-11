"""
WeasyPrint PDF builder.

Converts rendered Markdown to a professional PDF report.

Public API
----------
    build(rendered_md, config, out_path, *, repo_root=None)

The ``rendered_md`` string is the Jinja2-processed Markdown body (including
frontmatter). Config comes from the cascading _meta.yml + frontmatter merge
performed by :func:`md_doc.config.load_config`.

Config keys consumed
--------------------
  title        — document title (falls back to first H1 in body)
  author       — author name shown on cover/footer  (default: "Document Producer")
  date         — date string for cover page          (default: today)
  pdf_theme    — path to CSS file, relative to repo root or absolute
                  (default: themes/default/pdf-theme.css)
"""

from __future__ import annotations

import datetime
import logging
import re
from pathlib import Path
from typing import Any

logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fonttools").setLevel(logging.ERROR)

import markdown
import weasyprint

# Markdown extensions to enable
_MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    "footnotes",
    "def_list",
    "abbr",
    "attr_list",
    "md_in_html",
    "toc",
]


# ---------------------------------------------------------------------------
# Internal helpers (ported from document-designer/generate-pdf.py)
# ---------------------------------------------------------------------------

def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _extract_title(md_content: str) -> str | None:
    """Return the first H1 heading from markdown, stripped of inline markup."""
    match = re.search(r"^#\s+(.+)$", md_content, re.MULTILINE)
    if not match:
        return None
    title = match.group(1).strip()
    title = re.sub(r"\*\*(.+?)\*\*", r"\1", title)
    title = re.sub(r"\*(.+?)\*", r"\1", title)
    title = re.sub(r"`(.+?)`", r"\1", title)
    return title


def _strip_leading_h1(md_content: str) -> str:
    """Remove the first H1 line (it becomes the cover title)."""
    return re.sub(r"^#\s+.+\n?", "", md_content, count=1, flags=re.MULTILINE)


def _inject_appendix_breaks(md_content: str) -> str:
    """Insert page-break markers before each H2 inside an APPENDIX section."""
    lines = md_content.split("\n")
    result: list[str] = []
    in_appendix = False

    for line in lines:
        if re.match(r"^#\s+APPENDIX\b", line, re.IGNORECASE):
            in_appendix = True
        elif re.match(r"^#\s+", line):
            in_appendix = False

        if in_appendix and re.match(r"^##\s+", line):
            result.extend(["", '<div class="appendix-template-break"></div>', ""])

        result.append(line)

    return "\n".join(result)


def _build_html(title: str, date_str: str, author: str, html_body: str, css_path: Path) -> str:
    css_uri = css_path.as_uri()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{_escape_html(title)}</title>
  <link rel="stylesheet" href="{css_uri}">
</head>
<body>

  <!-- COVER PAGE -->
  <div class="cover">
    <div class="cover-bar"></div>
    <div class="cover-stripe"></div>
    <div class="cover-content">
      <p class="cover-label">Report</p>
      <h1 class="cover-title">{_escape_html(title)}</h1>
      <hr class="cover-divider">
      <p class="cover-meta">
        <strong>Prepared by</strong> {_escape_html(author)}<br>
        <strong>Date</strong> {_escape_html(date_str)}
      </p>
    </div>
    <div class="cover-footer">
      {_escape_html(author)} &nbsp;·&nbsp; Confidential
    </div>
  </div>

  <!-- REPORT BODY -->
  <div class="report-body">
    <span class="running-date">{_escape_html(date_str)}</span>
    {html_body}
  </div>

</body>
</html>"""


def _resolve_css(
    config: dict[str, Any],
    repo_root: Path | None,
    doc_path: Path | None = None,
) -> Path:
    """Resolve the CSS theme path from config, nested project dirs, or package default.

    Resolution order:
    1. ``pdf_theme`` config key (absolute path or relative to repo_root)
    2. ``pdf-theme.css`` in each directory from doc_path up to repo_root (deepest wins)
    3. ``themes/default/pdf-theme.css`` at repo root
    4. Package-bundled default theme

    This mirrors the cascading behaviour of ``_meta.yml`` — a CSS file placed
    next to (or near) a document overrides the repo-level default.
    """
    theme_val = config.get("pdf_theme")
    if theme_val:
        p = Path(theme_val)
        if p.is_absolute() and p.exists():
            return p
        if repo_root and (repo_root / p).exists():
            return (repo_root / p).resolve()

    # Walk from doc_path up to repo_root looking for pdf-theme.css (deepest wins)
    if doc_path is not None and repo_root is not None:
        doc_dir = doc_path.parent if doc_path.is_file() else doc_path
        try:
            rel = doc_dir.relative_to(repo_root)
            # All dirs from repo_root to doc_dir (inclusive), deepest first
            candidate_dirs = [
                repo_root / Path(*rel.parts[:i])
                for i in range(len(rel.parts), 0, -1)
            ]
        except ValueError:
            candidate_dirs = [doc_dir]
        for directory in candidate_dirs:
            candidate = directory / "pdf-theme.css"
            if candidate.exists():
                return candidate.resolve()

    # Fallback: repo-level themes/default/pdf-theme.css
    if repo_root and (repo_root / "themes" / "default" / "pdf-theme.css").exists():
        return (repo_root / "themes" / "default" / "pdf-theme.css").resolve()

    # Package fallback: look relative to this file's location
    pkg_default = Path(__file__).parent.parent.parent / "themes" / "default" / "pdf-theme.css"
    if pkg_default.exists():
        return pkg_default.resolve()

    raise FileNotFoundError(
        "PDF theme CSS not found. Set 'pdf_theme' in _meta.yml or place "
        "themes/default/pdf-theme.css at the repo root."
    )


def _find_repo_root(start: Path) -> Path:
    """Walk up from start looking for .git or pyproject.toml."""
    current = start.resolve()
    while True:
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            return start.resolve()
        current = parent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build(
    rendered_md: str,
    config: dict[str, Any],
    out_path: Path,
    *,
    repo_root: Path | None = None,
    doc_path: Path | None = None,
) -> None:
    """
    Convert rendered Markdown to a PDF file using WeasyPrint.

    Parameters
    ----------
    rendered_md:
        Jinja2-rendered Markdown string (may include frontmatter).
    config:
        Merged config dict from load_config().
    out_path:
        Destination path for the generated PDF.
    repo_root:
        Optional repo root for resolving the CSS theme path. Auto-detected
        from out_path if not provided.
    doc_path:
        Optional path to the source .md file. When provided, enables nested
        CSS resolution — a ``pdf-theme.css`` placed in any ancestor directory
        between the document and the repo root will be used (deepest wins).
    """
    out_path = Path(out_path).resolve()

    if repo_root is None:
        repo_root = _find_repo_root(out_path.parent)

    # Strip frontmatter (already processed by renderer)
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", rendered_md, count=1, flags=re.DOTALL)

    title: str = config.get("title") or _extract_title(body) or out_path.stem
    author: str = config.get("author", "Document Producer")
    date_str: str = config.get("date") or datetime.date.today().strftime("%-d %B %Y")

    body = _strip_leading_h1(body)
    body = _inject_appendix_breaks(body)

    md_engine = markdown.Markdown(extensions=_MD_EXTENSIONS)
    html_body = md_engine.convert(body)

    css_path = _resolve_css(config, repo_root, doc_path=doc_path)
    html = _build_html(title, date_str, author, html_body, css_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    weasyprint.HTML(string=html, base_url=str(out_path.parent)).write_pdf(str(out_path))
