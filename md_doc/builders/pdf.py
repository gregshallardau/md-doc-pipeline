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
                  (default: auto-generated _pdf-theme.css at repo root on first build)
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


_BLOCK_TAG = r"(?:p|pre|ul|ol|table|blockquote|div|dl)"
_BLOCK_RE = re.compile(
    rf"(<{_BLOCK_TAG}[^>]*>.*?</{_BLOCK_TAG}>)", re.DOTALL
)


def _keep_heading_with_next(html_body: str) -> str:
    """Wrap each heading + up to two following block elements in a keep-together div.

    WeasyPrint can ignore CSS break-after:avoid on headings when the next
    element is large.  Wrapping both in a container with break-inside:avoid
    forces them onto the same page.  We grab up to two siblings to handle
    the common pattern: heading → short intro paragraph → code/table block.
    """
    heading_re = re.compile(r"(<h[2-4][^>]*>.*?</h[2-4]>)", re.DOTALL)
    parts = heading_re.split(html_body)
    result: list[str] = []

    i = 0
    while i < len(parts):
        if heading_re.fullmatch(parts[i]):
            heading = parts[i]
            tail = parts[i + 1] if i + 1 < len(parts) else ""
            blocks = _BLOCK_RE.findall(tail)
            if len(blocks) >= 2:
                keep = blocks[0] + blocks[1]
                rest = tail[tail.index(blocks[0]) + len(blocks[0]) + tail[tail.index(blocks[0]) + len(blocks[0]):].index(blocks[1]) + len(blocks[1]):]
                before = tail[:tail.index(blocks[0])]
                result.append(before)
                result.append(f'<div class="keep-with-next">{heading}{blocks[0]}{blocks[1]}</div>')
                result.append(rest)
            elif len(blocks) == 1:
                before = tail[:tail.index(blocks[0])]
                after = tail[tail.index(blocks[0]) + len(blocks[0]):]
                result.append(before)
                result.append(f'<div class="keep-with-next">{heading}{blocks[0]}</div>')
                result.append(after)
            else:
                result.append(heading)
                result.append(tail)
            i += 2
        else:
            result.append(parts[i])
            i += 1

    return "".join(result)


def _resolve_logo(logo_val: str | None, repo_root: Path | None, doc_path: Path | None) -> Path | None:
    """Resolve header_logo to an absolute path, searching doc dir → ancestors → repo root."""
    if not logo_val:
        return None
    p = Path(logo_val)
    if p.is_absolute() and p.exists():
        return p
    search_dirs: list[Path] = []
    if doc_path is not None:
        doc_dir = doc_path.parent if doc_path.is_file() else doc_path
        search_dirs.append(doc_dir)
        if repo_root:
            try:
                rel = doc_dir.relative_to(repo_root)
                for i in range(len(rel.parts) - 1, 0, -1):
                    search_dirs.append(repo_root / Path(*rel.parts[:i]))
            except ValueError:
                pass
    if repo_root:
        search_dirs.append(repo_root)
    for d in search_dirs:
        candidate = d / logo_val
        if candidate.exists():
            return candidate.resolve()
    return None


def _build_html(
    title: str,
    date_str: str,
    author: str,
    html_body: str,
    css_path: Path,
    *,
    cover_page: bool = True,
    cover_label: str = "Report",
    header_logo_uri: str | None = None,
    header_logo_position: str = "right",
    header_text: str | None = None,
    header_text_position: str = "left",
) -> str:
    css_uri = css_path.as_uri()

    header_style = _build_header_style(
        header_logo_uri, header_logo_position,
        header_text, header_text_position,
    )

    cover_html = ""
    if cover_page:
        cover_html = f"""
  <!-- COVER PAGE -->
  <div class="cover">
    <div class="cover-bar"></div>
    <div class="cover-stripe"></div>
    <div class="cover-content">
      <p class="cover-label">{_escape_html(cover_label)}</p>
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
"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{_escape_html(title)}</title>
  <link rel="stylesheet" href="{css_uri}">
  {header_style}
</head>
<body>
{cover_html}
  <!-- REPORT BODY -->
  <div class="report-body">
    <span class="running-date">{_escape_html(date_str)}</span>
    {html_body}
  </div>

</body>
</html>"""


_HEADER_POSITIONS = {"left": "@top-left", "center": "@top-center", "right": "@top-right"}


def _build_header_style(
    logo_uri: str | None,
    logo_position: str,
    text: str | None,
    text_position: str,
) -> str:
    """Generate an inline <style> block for page header margin boxes."""
    if not logo_uri and not text:
        return ""
    rules: list[str] = []
    cover_overrides: list[str] = []

    if logo_uri:
        pos = _HEADER_POSITIONS.get(logo_position, "@top-right")
        rules.append(f"  {pos} {{ content: url('{logo_uri}'); vertical-align: middle; }}")
        cover_overrides.append(f"  {pos} {{ content: none; }}")

    if text:
        pos = _HEADER_POSITIONS.get(text_position, "@top-left")
        rules.append(
            f"  {pos} {{ content: '{_escape_html(text)}'; "
            f"font-size: 8pt; color: #5d6d7e; vertical-align: middle; }}"
        )
        cover_overrides.append(f"  {pos} {{ content: none; }}")

    lines = ["<style>", "@page {"]
    lines.extend(rules)
    lines.append("}")
    if cover_overrides:
        lines.append("@page cover {")
        lines.extend(cover_overrides)
        lines.append("}")
    lines.append("</style>")
    return "\n".join(lines)


def _resolve_css(
    config: dict[str, Any],
    repo_root: Path | None,
    doc_path: Path | None = None,
) -> Path:
    """Resolve the CSS theme path, auto-generating a default if none exists.

    Resolution order:
    1. ``pdf_theme`` config key (absolute path or relative to repo_root)
    2. ``_pdf-theme.css`` in each directory from doc_path up to repo_root (deepest wins)
    3. Auto-generate ``_pdf-theme.css`` at repo root on first build

    This mirrors the cascading behaviour of ``_meta.yml`` — a CSS file placed
    next to (or near) a document overrides the repo-level default.
    Run ``md-doc theme init`` to replace the generated default with a branded theme.
    """
    theme_val = config.get("pdf_theme")
    if theme_val:
        p = Path(theme_val)
        if p.is_absolute() and p.exists():
            return p
        if repo_root and (repo_root / p).exists():
            return (repo_root / p).resolve()

    # Walk from doc_path up to repo_root looking for _pdf-theme.css (deepest wins)
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
            candidate = directory / "_pdf-theme.css"
            if candidate.exists():
                return candidate.resolve()

    # Nothing found — generate a default _pdf-theme.css at the repo root
    # (or alongside the document if there is no repo root) and inform the user.
    generate_at = (repo_root if repo_root else (doc_path.parent if doc_path else Path.cwd()))
    default_path = generate_at / "_pdf-theme.css"

    from ..theme import generate_default_theme  # avoid circular import at module level
    default_path.write_text(generate_default_theme(), encoding="utf-8")

    logging.getLogger(__name__).warning(
        "No _pdf-theme.css found — created default theme at %s. "
        "Run 'md-doc theme init' to customise it.",
        default_path,
    )
    return default_path.resolve()


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
        CSS resolution — a ``_pdf-theme.css`` placed in any ancestor directory
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
    cover_label: str = config.get("cover_label", "Report")

    cover_page: bool = bool(config.get("cover_page", True))

    header_logo_path = _resolve_logo(config.get("header_logo"), repo_root, doc_path)
    header_logo_uri = header_logo_path.as_uri() if header_logo_path else None
    header_logo_position: str = config.get("header_logo_position", "right")
    header_text: str | None = config.get("header_text")
    header_text_position: str = config.get("header_text_position", "left")

    if cover_page:
        body = _strip_leading_h1(body)
    body = _inject_appendix_breaks(body)

    md_engine = markdown.Markdown(extensions=_MD_EXTENSIONS)
    html_body = _keep_heading_with_next(md_engine.convert(body))

    css_path = _resolve_css(config, repo_root, doc_path=doc_path)
    html = _build_html(
        title, date_str, author, html_body, css_path,
        cover_page=cover_page,
        cover_label=cover_label,
        header_logo_uri=header_logo_uri,
        header_logo_position=header_logo_position,
        header_text=header_text,
        header_text_position=header_text_position,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wp_kwargs = {"pdf_forms": True} if config.get("pdf_forms") else {}
    weasyprint.HTML(string=html, base_url=str(out_path.parent)).write_pdf(str(out_path), **wp_kwargs)
