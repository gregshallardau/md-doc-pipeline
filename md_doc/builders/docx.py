"""
python-docx DOCX builder.

Converts rendered Markdown to a .docx file.

Public API
----------
    build(rendered_md, config, out_path)

The ``rendered_md`` string is the Jinja2-processed Markdown body (including
frontmatter). Config comes from the cascading _meta.yml + frontmatter merge.

Config keys consumed
--------------------
  title        — document title (falls back to first H1 in body)
  author       — author name
  output_docx  — output filename hint (the CLI already resolves out_path,
                  so this key is informational only in this function)

Conversion approach
-------------------
Markdown is converted to HTML via the ``markdown`` library, then the HTML
element tree is walked to populate a python-docx Document with styled runs,
paragraphs, tables, and lists. This avoids pandoc/external-tool dependencies.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import markdown
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from ..docx_theme import apply_theme_to_doc, resolve_docx_theme, set_cell_shading

# Markdown extensions to enable (consistent with pdf builder)
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
# HTML → docx walker
# ---------------------------------------------------------------------------


class _DocxBuilder(HTMLParser):
    """
    Walk an HTML fragment and populate a python-docx Document.

    Handles: h1–h4, p, ul/ol/li, table/thead/tbody/tr/th/td,
             pre/code, blockquote, strong/b, em/i, hr, br.
    """

    def __init__(self, doc: Document, theme: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.doc = doc
        self._theme: dict[str, Any] = theme or {}

        # Apply CSS theme to document styles
        apply_theme_to_doc(self.doc, self._theme)

        # State tracking
        self._paragraph = None  # current paragraph being built
        self._run = None  # current run
        self._bold = False
        self._italic = False
        self._in_pre = False
        self._in_code = False  # inline code inside paragraph
        self._in_blockquote = False
        self._list_stack: list[str] = []  # "ul" or "ol" per level
        self._list_counters: list[int] = []

        # Table state
        self._table = None
        self._row = None
        self._cell = None
        self._in_table = False
        self._in_th = False

        # Accumulate text in pre/code blocks
        self._pre_text = ""

        # Tag stack for nesting
        self._tag_stack: list[str] = []

    # ------------------------------------------------------------------
    # Paragraph helpers
    # ------------------------------------------------------------------

    def _new_para(self, style: str = "Normal") -> None:
        """Start a new paragraph, flushing any current one."""
        self._paragraph = self.doc.add_paragraph(style=style)
        self._run = None

    def _current_para(self) -> Any:
        if self._paragraph is None:
            self._paragraph = self.doc.add_paragraph()
        return self._paragraph

    def _add_text(self, text: str) -> None:
        """Add text to the current paragraph with current bold/italic state."""
        if not text:
            return
        para = self._current_para()
        run = para.add_run(text)
        run.bold = self._bold
        run.italic = self._italic
        if self._in_code:
            run.font.name = self._theme.get("font_code", "Courier New")
            run.font.size = Pt(9)

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag_stack.append(tag)
        tag = tag.lower()

        if tag in ("h1", "h2", "h3", "h4"):
            level = int(tag[1])
            style = f"Heading {level}"
            self._new_para(style)

        elif tag == "p":
            if self._in_blockquote:
                self._new_para("Intense Quote")
            else:
                self._new_para("Normal")

        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._list_counters.append(0)

        elif tag == "li":
            if self._list_stack:
                kind = self._list_stack[-1]
                if kind == "ul":
                    self._paragraph = self.doc.add_paragraph(style="List Bullet")
                else:
                    self._list_counters[-1] += 1
                    self._paragraph = self.doc.add_paragraph(style="List Number")
            else:
                self._new_para("List Bullet")

        elif tag == "pre":
            self._in_pre = True
            self._pre_text = ""

        elif tag == "code":
            if self._in_pre:
                pass  # handled in handle_data / endtag
            else:
                self._in_code = True

        elif tag == "blockquote":
            self._in_blockquote = True

        elif tag in ("strong", "b"):
            self._bold = True

        elif tag in ("em", "i"):
            self._italic = True

        elif tag == "hr":
            self._paragraph = self.doc.add_paragraph()
            self._paragraph.paragraph_format.space_before = Pt(6)
            self._paragraph.paragraph_format.space_after = Pt(6)
            # Add a bottom border as a horizontal rule (OxmlElement works on all versions)
            pPr = self._paragraph._p.get_or_add_pPr()
            pBdr = pPr.find(qn("w:pBdr"))
            if pBdr is None:
                pBdr = OxmlElement("w:pBdr")
                pPr.append(pBdr)
            bottom = pBdr.find(qn("w:bottom"))
            if bottom is None:
                bottom = OxmlElement("w:bottom")
                pBdr.append(bottom)
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "6")
            bottom.set(qn("w:space"), "1")
            bottom.set(qn("w:color"), "AAAAAA")

        elif tag == "br":
            self._add_text("\n")

        elif tag == "table":
            self._in_table = True
            # We'll build the table after parsing — collect rows first
            self._table_rows: list[list[tuple[bool, str]]] = []  # [(is_header, text), ...]
            self._current_row: list[tuple[bool, str]] = []
            self._current_cell_text = ""
            self._in_th = False

        elif tag == "tr":
            self._current_row = []

        elif tag in ("th", "td"):
            self._in_th = tag == "th"
            self._current_cell_text = ""

    def handle_endtag(self, tag: str) -> None:
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        tag = tag.lower()

        if tag in ("h1", "h2", "h3", "h4", "p"):
            self._paragraph = None

        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            if self._list_counters:
                self._list_counters.pop()
            self._paragraph = None

        elif tag == "li":
            self._paragraph = None

        elif tag == "pre":
            self._in_pre = False
            para = self.doc.add_paragraph(style="Normal")
            run = para.add_run(self._pre_text.strip())
            run.font.name = "Courier New"
            run.font.size = Pt(9)
            self._pre_text = ""
            self._paragraph = None

        elif tag == "code":
            if not self._in_pre:
                self._in_code = False

        elif tag == "blockquote":
            self._in_blockquote = False
            self._paragraph = None

        elif tag in ("strong", "b"):
            self._bold = False

        elif tag in ("em", "i"):
            self._italic = False

        elif tag in ("th", "td"):
            if self._in_table:
                self._current_row.append((self._in_th, self._current_cell_text))

        elif tag == "tr":
            if self._in_table:
                self._table_rows.append(self._current_row)

        elif tag == "table":
            self._in_table = False
            self._flush_table()

    def handle_data(self, data: str) -> None:
        if self._in_pre:
            self._pre_text += data
            return
        if self._in_table and not self._in_pre:
            self._current_cell_text += data
            return
        self._add_text(data)

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def _flush_table(self) -> None:
        rows = getattr(self, "_table_rows", [])
        if not rows:
            return
        max_cols = max(len(r) for r in rows)
        if max_cols == 0:
            return

        table = self.doc.add_table(rows=len(rows), cols=max_cols)
        table.style = "Table Grid"

        header_bg = self._theme.get("color_table_header_bg")
        header_text_color = self._theme.get("color_table_header_text")

        for r_idx, row in enumerate(rows):
            for c_idx, (is_header, text) in enumerate(row):
                if c_idx >= max_cols:
                    break
                cell = table.cell(r_idx, c_idx)
                cell.text = text.strip()
                if is_header:
                    for run in cell.paragraphs[0].runs:
                        run.bold = True
                        if header_text_color:
                            from ..docx_theme import _hex_to_rgb
                            r, g, b = _hex_to_rgb(header_text_color)
                            run.font.color.rgb = RGBColor(r, g, b)
                    if header_bg:
                        set_cell_shading(cell, header_bg)

        self._paragraph = None


# ---------------------------------------------------------------------------
# Markdown stripping helpers
# ---------------------------------------------------------------------------


def _strip_frontmatter(md_content: str) -> str:
    """Remove YAML frontmatter if present."""
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", md_content, count=1, flags=re.DOTALL)


def _extract_title(md_content: str) -> str | None:
    match = re.search(r"^#\s+(.+)$", md_content, re.MULTILINE)
    if not match:
        return None
    title = match.group(1).strip()
    title = re.sub(r"\*\*(.+?)\*\*", r"\1", title)
    title = re.sub(r"\*(.+?)\*", r"\1", title)
    title = re.sub(r"`(.+?)`", r"\1", title)
    return title


def _strip_leading_h1(md_content: str) -> str:
    return re.sub(r"^#\s+.+\n?", "", md_content, count=1, flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_docx_theme(doc_path: Path | None, repo_root: Path | None) -> dict[str, Any]:
    """Walk from doc_path up to repo_root looking for _docx-theme.css or _pdf-theme.css.

    Delegates to ``resolve_docx_theme`` from ``docx_theme`` module.
    Returns a parsed theme dict, or an empty dict if no theme file is found.
    """
    if doc_path is None or repo_root is None:
        return {}
    result = resolve_docx_theme(doc_path, repo_root)
    return result if result is not None else {}


def build(
    rendered_md: str,
    config: dict[str, Any],
    out_path: Path,
    doc_path: Path | None = None,
    repo_root: Path | None = None,
) -> None:
    """
    Convert rendered Markdown to a .docx file.

    Only called when 'docx' is in the document's ``outputs`` config list —
    the CLI enforces this before calling this function.

    Parameters
    ----------
    rendered_md:
        Jinja2-rendered Markdown string (may include frontmatter).
    config:
        Merged config dict from load_config().
    out_path:
        Destination path for the generated .docx file.
    doc_path:
        Source .md path. Used to resolve the CSS theme cascade.
    repo_root:
        Repo root path. Used to bound the CSS theme cascade.
    """
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    body = _strip_frontmatter(rendered_md)
    title: str = config.get("title") or _extract_title(body) or out_path.stem
    author: str = config.get("author", "")

    body = _strip_leading_h1(body)

    # Convert markdown → HTML
    md_engine = markdown.Markdown(extensions=_MD_EXTENSIONS)
    html = md_engine.convert(body)

    # Resolve CSS theme for Word styling
    theme = _resolve_docx_theme(doc_path, repo_root)

    # Build document
    doc = Document()

    # Core properties
    props = doc.core_properties
    props.title = title
    if author:
        props.author = author

    # Title paragraph
    doc.add_paragraph(title, style="Title")

    # Walk the HTML into docx elements
    builder = _DocxBuilder(doc, theme=theme)
    builder.feed(html)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
