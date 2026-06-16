"""
python-docx builder for .docx and .dotx output.

Converts rendered Markdown to a Word document.  When ``output_format="dotx"``
the builder also converts ``[[field_name]]`` markers to Word fields and patches
the saved ZIP's content type so Word opens it as a template.

Public API
----------
    build(rendered_md, config, out_path, *, doc_path, repo_root, output_format)

Field syntax (.dotx only)
-------------------------
Use ``[[field_name]]`` in Markdown source alongside Jinja2 ``{{ }}``:

    Dear [[contact_name]],          # Word field in .dotx
    This is version {{ version }}.  # resolved at build time

``dotx_field_type`` config key controls field type:
  "form"  (default) — Text Form Fields with Bookmark; fillable in Word without
                       a mail merge data source.
  "merge"           — Classic MERGEFIELD (``«field_name»``); requires a data
                       source and a mail merge run.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import markdown
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from ..docx_theme import (
    _hex_to_rgb,
    apply_theme_to_doc,
    patch_docx_theme_fonts,
    resolve_docx_theme,
    set_cell_shading,
    set_para_shading,
)
from .pdf import _inject_page_breaks

# Markdown extensions (consistent with pdf builder)
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

_MERGE_RE = re.compile(r"\[\[(\w+)\]\]")


# ---------------------------------------------------------------------------
# Hyperlink helper
# ---------------------------------------------------------------------------


def _insert_hyperlink(paragraph: Any, text: str, url: str) -> None:
    """Append a clickable hyperlink to *paragraph*.

    Display text is ``text (url)`` when text differs from url, or just ``url``
    when they're the same (e.g. bare URL links). This keeps the URL visible
    in printed output.
    """
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    display = text.strip()
    url_clean = url.strip()
    if display and display != url_clean:
        display = f"{display} ({url_clean})"
    else:
        display = url_clean

    part = paragraph.part
    r_id = part.relate_to(url_clean, RT.HYPERLINK, is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rStyle = OxmlElement("w:rStyle")
    rStyle.set(qn("w:val"), "Hyperlink")
    rPr.append(rStyle)
    run.append(rPr)

    t = OxmlElement("w:t")
    t.text = display
    if display.startswith(" ") or display.endswith(" "):
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(t)

    hyperlink.append(run)
    paragraph._p.append(hyperlink)


# ---------------------------------------------------------------------------
# Field helpers — MERGEFIELD and Text Form Field
# ---------------------------------------------------------------------------


def _insert_merge_field(
    paragraph: Any,
    field_name: str,
    *,
    bold: bool = False,
    italic: bool = False,
) -> None:
    """Append a Word MERGEFIELD for *field_name* to *paragraph*."""
    run = paragraph.add_run()
    if bold:
        run.bold = True
    if italic:
        run.italic = True
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run._r.append(fld_begin)

    run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" MERGEFIELD {field_name} "
    run._r.append(instr)

    run = paragraph.add_run()
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    run._r.append(fld_sep)

    run = paragraph.add_run(f"«{field_name}»")
    if bold:
        run.bold = True
    if italic:
        run.italic = True

    run = paragraph.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_end)


def _insert_form_field(
    paragraph: Any,
    field_name: str,
    bookmark_id: int,
    *,
    bold: bool = False,
    italic: bool = False,
) -> None:
    """Append a Word Text Form Field named *field_name* to *paragraph*.

    The field name is stored in ffData/name and is directly fillable in Word
    without a mail merge data source.  Bookmarks are intentionally omitted —
    they are not needed for fill-in use and cause Word to render extra visual
    line breaks when multiple fields appear consecutively in the same paragraph.
    """
    run = paragraph.add_run()
    if bold:
        run.bold = True
    if italic:
        run.italic = True
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    ff_data = OxmlElement("w:ffData")
    ff_name = OxmlElement("w:name")
    ff_name.set(qn("w:val"), field_name)
    ff_data.append(ff_name)
    ff_data.append(OxmlElement("w:enabled"))
    ff_calc = OxmlElement("w:calcOnExit")
    ff_calc.set(qn("w:val"), "0")
    ff_data.append(ff_calc)
    ff_data.append(OxmlElement("w:textInput"))
    fld_begin.append(ff_data)
    run._r.append(fld_begin)

    run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " FORMTEXT "
    run._r.append(instr)

    run = paragraph.add_run()
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    run._r.append(fld_sep)

    run = paragraph.add_run(f"«{field_name}»")
    if bold:
        run.bold = True
    if italic:
        run.italic = True

    run = paragraph.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_end)


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------


def _set_cell_bottom_border(cell: Any, color: str = "d5d8dc", pt: float = 0.5) -> None:
    """Add a bottom border to a table cell. ``pt`` is the border thickness in points."""
    sz = str(max(1, round(pt * 8)))  # Word sz unit = 1/8 pt
    fill = color.lstrip("#").upper()
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = tcPr.find(qn("w:tcBorders"))
    if tcBorders is None:
        tcBorders = OxmlElement("w:tcBorders")
        tcPr.append(tcBorders)
    bottom = tcBorders.find(qn("w:bottom"))
    if bottom is None:
        bottom = OxmlElement("w:bottom")
        tcBorders.append(bottom)
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), sz)
    bottom.set(qn("w:space"), "0")
    bottom.set(qn("w:color"), fill)


def _clear_table_borders(table: Any) -> None:
    """Explicitly set all table-level borders to none so cell borders control the look."""
    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    for existing in tblPr.findall(qn("w:tblBorders")):
        tblPr.remove(existing)
    tblBorders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "none")
        b.set(qn("w:sz"), "0")
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), "auto")
        tblBorders.append(b)
    tblPr.append(tblBorders)


def _render_cell_html(
    paragraph: Any,
    html: str,
    theme: dict,
    field_type: str | None,
    bookmark_id: int,
    *,
    bold_override: bool = False,
) -> None:
    """Parse the inner HTML of a table cell and write runs into *paragraph*.

    Handles inline tags: strong/b (bold), em/i (italic), code (monospace).
    Plain text is written with *bold_override* when no inline tag is active.
    """
    from html.parser import HTMLParser as _HP

    class _CellParser(_HP):
        def __init__(self) -> None:
            super().__init__()
            self._bold = bold_override
            self._italic = False
            self._code = False

        def handle_starttag(self, tag: str, attrs: list) -> None:
            tag = tag.lower()
            if tag in ("strong", "b"):
                self._bold = True
            elif tag in ("em", "i"):
                self._italic = True
            elif tag == "code":
                self._code = True

        def handle_endtag(self, tag: str) -> None:
            tag = tag.lower()
            if tag in ("strong", "b"):
                self._bold = bold_override  # back to cell default
            elif tag in ("em", "i"):
                self._italic = False
            elif tag == "code":
                self._code = False

        def handle_data(self, data: str) -> None:
            if not data:
                return
            run = paragraph.add_run(data)
            run.bold = self._bold
            run.italic = self._italic
            if self._code:
                run.font.name = theme.get("font_code", "Courier New")
                run.font.size = Pt(theme.get("font_size_code", 9.0))
                col = theme.get("color_code")
                if col:
                    r2, g2, b2 = _hex_to_rgb(col)
                    run.font.color.rgb = RGBColor(r2, g2, b2)

    _CellParser().feed(html)


# ---------------------------------------------------------------------------
# HTML → docx walker
# ---------------------------------------------------------------------------


class _DocxBuilder(HTMLParser):
    """
    Walk an HTML fragment and populate a python-docx Document.

    Handles: h1–h4, p, ul/ol/li, table/thead/tbody/tr/th/td,
             pre/code, blockquote, strong/b, em/i, hr, br.

    When *field_type* is ``"form"`` or ``"merge"``, ``[[field_name]]``
    markers in text are converted to the appropriate Word field type
    instead of being written as literal text.
    """

    def __init__(
        self,
        doc: Document,
        theme: dict[str, Any] | None = None,
        field_type: str | None = None,
        body_text_align: str | None = None,
        table_col_widths: list[float] | None = None,
    ) -> None:
        super().__init__()
        self.doc = doc
        self._theme: dict[str, Any] = theme or {}
        self._field_type = field_type  # None | "form" | "merge"
        self._body_text_align = body_text_align  # default alignment for Normal paragraphs
        self._table_col_widths = table_col_widths  # e.g. [30, 70] — relative column widths

        apply_theme_to_doc(self.doc, self._theme)

        # State tracking
        self._paragraph = None
        self._run = None
        self._bold = False
        self._italic = False
        self._in_pre = False
        self._in_code = False
        self._in_blockquote = False
        self._list_stack: list[str] = []
        self._list_counters: list[int] = []

        # Table state — cells store raw inner HTML to preserve inline markup
        self._in_table = False
        self._in_cell = False   # True while cursor is inside a <th> or <td>
        self._in_th = False
        self._table_rows: list[list[tuple[bool, str]]] = []
        self._current_row: list[tuple[bool, str]] = []
        self._current_cell_html = ""
        # Set by <!-- col-widths: 30, 70 --> comments; consumed by the next table
        self._next_table_col_widths: list[float] | None = None
        self._active_table_col_widths: list[float] | None = None

        self._pre_text = ""
        self._tag_stack: list[str] = []

        # Field-mode state
        self._bookmark_id = 0

        # Set to True after a <br> element is written so the leading \n of the
        # next handle_data call (which is just HTML formatting whitespace after
        # the <br> tag, not a meaningful line break) is stripped rather than
        # converted to an extra <w:br/>.
        self._last_was_br = False

        # Alignment context stack — pushed/popped by <div style="text-align: ...">
        self._alignment_stack: list[str | None] = []

        # Hyperlink state — set while inside <a href="...">
        self._current_href: str | None = None
        self._link_text_buf: str = ""

    # ------------------------------------------------------------------
    # Alignment helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_text_align(attrs: list[tuple[str, str | None]]) -> str | None:
        """Extract text-align value from a style attribute, e.g. 'justify'."""
        for name, value in attrs:
            if name == "style" and value:
                for part in value.split(";"):
                    part = part.strip()
                    if part.lower().startswith("text-align:"):
                        return part.split(":", 1)[1].strip().lower()
        return None

    @staticmethod
    def _to_word_alignment(align: str | None) -> Any:
        _map = {
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
        }
        return _map.get(align or "")

    def _effective_alignment(self, inline_align: str | None = None) -> Any:
        """Return the Word alignment constant for the current context."""
        align = inline_align
        if align is None:
            # Walk stack top-to-bottom for nearest div override
            for a in reversed(self._alignment_stack):
                if a is not None:
                    align = a
                    break
        if align is None:
            align = self._body_text_align
        return self._to_word_alignment(align)

    # ------------------------------------------------------------------
    # Paragraph helpers
    # ------------------------------------------------------------------

    def _new_para(self, style: str = "Normal") -> None:
        self._paragraph = self.doc.add_paragraph(style=style)
        self._run = None

    def _current_para(self) -> Any:
        if self._paragraph is None:
            self._paragraph = self.doc.add_paragraph()
        return self._paragraph

    def _write_text(
        self,
        paragraph: Any,
        text: str,
        *,
        bold: bool = False,
        italic: bool = False,
        code: bool = False,
    ) -> None:
        """Write *text* to *paragraph*, handling ``[[field]]`` markers when
        field_type is set, and converting bare ``\\n`` to Word line breaks.
        """
        if not text:
            return

        if self._field_type:
            # Field-aware path: split on [[field]] markers
            parts = _MERGE_RE.split(text)
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    # Literal text segment — split on \n for line breaks
                    if part:
                        lines = part.split("\n")
                        for j, line in enumerate(lines):
                            if j > 0:
                                br_run = paragraph.add_run()
                                br_run._r.append(OxmlElement("w:br"))
                            if line:
                                run = paragraph.add_run(line)
                                if bold:
                                    run.bold = True
                                    col = self._theme.get("color_strong")
                                    if col:
                                        r, g, b = _hex_to_rgb(col)
                                        run.font.color.rgb = RGBColor(r, g, b)
                                if italic:
                                    run.italic = True
                                    if not bold:
                                        col = self._theme.get("color_em")
                                        if col:
                                            r, g, b = _hex_to_rgb(col)
                                            run.font.color.rgb = RGBColor(r, g, b)
                                if code:
                                    run.font.name = self._theme.get("font_code", "Courier New")
                                    run.font.size = Pt(self._theme.get("font_size_code", 9.0))
                                    col = self._theme.get("color_code")
                                    if col:
                                        r, g, b = _hex_to_rgb(col)
                                        run.font.color.rgb = RGBColor(r, g, b)
                else:
                    # Field marker
                    if self._field_type == "merge":
                        _insert_merge_field(paragraph, part, bold=bold, italic=italic)
                    else:
                        _insert_form_field(
                            paragraph, part, self._bookmark_id, bold=bold, italic=italic
                        )
                        self._bookmark_id += 1
        else:
            # Plain text path: split on \n for line breaks
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if i > 0:
                    br_run = paragraph.add_run()
                    br_run._r.append(OxmlElement("w:br"))
                if line:
                    run = paragraph.add_run(line)
                    if bold:
                        run.bold = True
                        col = self._theme.get("color_strong")
                        if col:
                            r, g, b = _hex_to_rgb(col)
                            run.font.color.rgb = RGBColor(r, g, b)
                    if italic:
                        run.italic = True
                        if not bold:
                            col = self._theme.get("color_em")
                            if col:
                                r, g, b = _hex_to_rgb(col)
                                run.font.color.rgb = RGBColor(r, g, b)
                    if code:
                        run.font.name = self._theme.get("font_code", "Courier New")
                        run.font.size = Pt(self._theme.get("font_size_code", 9.0))
                        col = self._theme.get("color_code")
                        if col:
                            r, g, b = _hex_to_rgb(col)
                            run.font.color.rgb = RGBColor(r, g, b)

    def _add_text(self, text: str) -> None:
        if not text:
            return
        if self._last_was_br:
            text = text.lstrip("\n")
            self._last_was_br = False
        if self._current_href is not None:
            self._link_text_buf += text
            return
        if self._paragraph is None and not text.strip():
            return
        self._write_text(
            self._current_para(),
            text,
            bold=self._bold,
            italic=self._italic,
            code=self._in_code,
        )

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag_stack.append(tag)
        tag = tag.lower()

        # Inside a cell, collect all inline tags as raw HTML instead of processing them
        if self._in_cell:
            attr_str = ""
            for k, v in attrs:
                attr_str += f' {k}="{v}"' if v is not None else f" {k}"
            self._current_cell_html += f"<{tag}{attr_str}>"
            return

        if tag in ("h1", "h2", "h3", "h4"):
            self._new_para(f"Heading {int(tag[1])}")
            inline_align = self._parse_text_align(attrs)
            word_align = self._effective_alignment(inline_align)
            if word_align is not None and self._paragraph is not None:
                self._paragraph.alignment = word_align

        elif tag == "p":
            self._new_para("Normal")
            inline_align = self._parse_text_align(attrs)
            word_align = self._effective_alignment(inline_align)
            if word_align is not None and self._paragraph is not None:
                self._paragraph.alignment = word_align
            if self._in_blockquote:
                # Apply left border accent from theme
                bq_color = self._theme.get("blockquote_border_color")
                bq_pt = self._theme.get("blockquote_border_pt", 3.0)
                if bq_color:
                    pPr = self._paragraph._p.get_or_add_pPr()
                    pBdr = OxmlElement("w:pBdr")
                    left = OxmlElement("w:left")
                    left.set(qn("w:val"), "single")
                    left.set(qn("w:sz"), str(max(1, round(bq_pt * 8))))
                    left.set(qn("w:space"), "12")
                    left.set(qn("w:color"), bq_color.lstrip("#").upper())
                    pBdr.append(left)
                    pPr.append(pBdr)
                # Indentation to match CSS padding-left
                ind = self._paragraph._p.get_or_add_pPr().get_or_add_ind()
                ind.set(qn("w:left"), str(int(10 * 20)))  # 10pt indent

        elif tag == "div":
            self._alignment_stack.append(self._parse_text_align(attrs))
            class_attr = dict(attrs).get("class") or ""
            if "md-doc-page-break" in class_attr.split():
                # Emit a real Word page break.  The marker div has no content
                # so nothing else needs to be rendered for it.
                self.doc.add_page_break()

        elif tag == "a":
            self._current_href = dict(attrs).get("href") or ""
            self._link_text_buf = ""

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
            if not self._in_pre:
                self._in_code = True

        elif tag == "blockquote":
            self._in_blockquote = True
            # Blockquote content is italic by default (CSS font-style: italic)
            self._italic = True

        elif tag in ("strong", "b"):
            self._bold = True

        elif tag in ("em", "i"):
            self._italic = True

        elif tag == "br":
            run = self._current_para().add_run()
            run._r.append(OxmlElement("w:br"))
            self._last_was_br = True

        elif tag == "hr":
            self._paragraph = self.doc.add_paragraph()
            self._paragraph.paragraph_format.space_before = Pt(6)
            self._paragraph.paragraph_format.space_after = Pt(6)
            hr_color = (self._theme.get("color_hr") or "#aaaaaa").lstrip("#").upper()
            hr_sz = str(max(1, round(self._theme.get("size_hr", 0.75) * 8)))
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
            bottom.set(qn("w:sz"), hr_sz)
            bottom.set(qn("w:space"), "1")
            bottom.set(qn("w:color"), hr_color)

        elif tag == "table":
            self._in_table = True
            self._table_rows = []
            self._current_row = []
            self._current_cell_html = ""
            self._in_cell = False
            self._in_th = False
            # Consume any col-widths comment that immediately preceded this table
            self._active_table_col_widths = self._next_table_col_widths
            self._next_table_col_widths = None

        elif tag == "tr":
            self._current_row = []

        elif tag in ("th", "td"):
            self._in_th = tag == "th"
            self._in_cell = True
            self._current_cell_html = ""

    def handle_endtag(self, tag: str) -> None:
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        tag = tag.lower()

        # Inside a cell, collect closing inline tags as raw HTML
        if self._in_cell and tag not in ("th", "td"):
            self._current_cell_html += f"</{tag}>"
            return

        if tag == "h1" and self._paragraph is not None:
            color = self._theme.get("h1_border_color")
            pt = self._theme.get("h1_border_pt", 1.5)
            if color:
                pPr = self._paragraph._p.get_or_add_pPr()
                pBdr = OxmlElement("w:pBdr")
                bot = OxmlElement("w:bottom")
                bot.set(qn("w:val"), "single")
                bot.set(qn("w:sz"), str(max(1, round(pt * 8))))
                bot.set(qn("w:space"), "6")
                bot.set(qn("w:color"), color.lstrip("#").upper())
                pBdr.append(bot)
                pPr.append(pBdr)

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
            pre_size = self._theme.get("font_size_pre", 9.0)
            pre_font = self._theme.get("font_code", "Courier New")
            pre_border_color = self._theme.get("pre_border_color")
            pre_border_pt = self._theme.get("pre_border_pt", 3.0)
            pre_bg = self._theme.get("pre_background_color")
            # Apply background shading (CSS background)
            if pre_bg:
                set_para_shading(para, pre_bg)
            # Apply left accent border (CSS border-left)
            if pre_border_color:
                pPr = para._p.get_or_add_pPr()
                pBdr = OxmlElement("w:pBdr")
                left = OxmlElement("w:left")
                left.set(qn("w:val"), "single")
                left.set(qn("w:sz"), str(max(1, round(pre_border_pt * 8))))
                left.set(qn("w:space"), "12")
                left.set(qn("w:color"), pre_border_color.lstrip("#").upper())
                pBdr.append(left)
                pPr.append(pBdr)
                ind = pPr.get_or_add_ind()
                ind.set(qn("w:left"), str(int(10 * 20)))  # 10pt indent
            para.paragraph_format.space_before = Pt(6)
            para.paragraph_format.space_after = Pt(10)
            run = para.add_run(self._pre_text.strip())
            run.font.name = pre_font
            run.font.size = Pt(pre_size)
            self._pre_text = ""
            self._paragraph = None

        elif tag == "code":
            if not self._in_pre:
                self._in_code = False

        elif tag == "blockquote":
            self._in_blockquote = False
            self._italic = False
            self._paragraph = None

        elif tag == "div":
            if self._alignment_stack:
                self._alignment_stack.pop()
            self._paragraph = None

        elif tag == "a":
            if self._link_text_buf and self._paragraph is not None:
                if self._current_href:
                    _insert_hyperlink(self._current_para(), self._link_text_buf, self._current_href)
                else:
                    self._write_text(self._current_para(), self._link_text_buf)
            self._current_href = None
            self._link_text_buf = ""

        elif tag in ("strong", "b"):
            self._bold = False

        elif tag in ("em", "i"):
            self._italic = False

        elif tag in ("th", "td"):
            if self._in_table:
                self._current_row.append((self._in_th, self._current_cell_html))
            self._in_cell = False

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
        if self._in_table:
            self._current_cell_html += data
            return
        self._add_text(data)

    def handle_comment(self, data: str) -> None:
        stripped = data.strip()
        if stripped.lower().startswith("col-widths:"):
            raw = stripped[len("col-widths:"):].strip()
            try:
                widths = [float(v.strip()) for v in raw.split(",") if v.strip()]
                if widths:
                    self._next_table_col_widths = widths
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def _flush_table(self) -> None:
        rows = self._table_rows
        if not rows:
            return
        max_cols = max(len(r) for r in rows)
        if max_cols == 0:
            return

        table = self.doc.add_table(rows=len(rows), cols=max_cols)
        try:
            table.style = "Table Normal"
        except KeyError:
            table.style = "Normal Table"

        # Explicitly set all table-level borders to none
        _clear_table_borders(table)

        # Set table to 100% text width with fixed layout and equal column widths.
        # autofit collapses columns in DOTX templates because form-field cells
        # have no content to measure against; fixed layout uses the declared
        # gridCol widths regardless of content.
        tbl = table._tbl
        tblPr = tbl.find(qn("w:tblPr"))
        if tblPr is None:
            tblPr = OxmlElement("w:tblPr")
            tbl.insert(0, tblPr)

        section = self.doc.sections[0]
        text_width_emu = section.page_width - section.left_margin - section.right_margin
        text_width_twips = round(text_width_emu / 914400 * 1440)

        # Build per-column widths. Priority: <!-- col-widths --> comment on this
        # table > table_col_widths config key > equal distribution.
        col_widths_twips: list[int]
        weights = self._active_table_col_widths or self._table_col_widths
        self._active_table_col_widths = None
        if weights and len(weights) == max_cols:
            total = sum(weights)
            col_widths_twips = [round(text_width_twips * w / total) for w in weights]
            # Correct rounding drift so columns exactly fill the text width
            diff = text_width_twips - sum(col_widths_twips)
            col_widths_twips[-1] += diff
        else:
            col_width_twips = text_width_twips // max_cols
            col_widths_twips = [col_width_twips] * max_cols

        for existing_w in tblPr.findall(qn("w:tblW")):
            tblPr.remove(existing_w)
        tblW = OxmlElement("w:tblW")
        tblW.set(qn("w:w"), str(text_width_twips))
        tblW.set(qn("w:type"), "dxa")
        tblPr.append(tblW)

        for existing_layout in tblPr.findall(qn("w:tblLayout")):
            tblPr.remove(existing_layout)
        tblLayout = OxmlElement("w:tblLayout")
        tblLayout.set(qn("w:type"), "fixed")
        tblPr.append(tblLayout)

        for old in tblPr.findall(qn("w:tblInd")):
            tblPr.remove(old)
        tblInd = OxmlElement("w:tblInd")
        tblInd.set(qn("w:w"), "0")
        tblInd.set(qn("w:type"), "dxa")
        tblPr.append(tblInd)

        # Replace the tblGrid python-docx already created with our own.
        # Must remove first: with fixed layout Word reads tblGrid, and having
        # two of them produces invalid OOXML that corrupts table rendering.
        for old_grid in tbl.findall(qn("w:tblGrid")):
            tbl.remove(old_grid)
        tblGrid = OxmlElement("w:tblGrid")
        for cw in col_widths_twips:
            gridCol = OxmlElement("w:gridCol")
            gridCol.set(qn("w:w"), str(cw))
            tblGrid.append(gridCol)
        tbl.insert(list(tbl).index(tblPr) + 1, tblGrid)

        # Cell margins from CSS td { padding }
        tb_pt = self._theme.get("padding_cell_tb_pt", 5.0)
        lr_pt = self._theme.get("padding_cell_lr_pt", 9.0)
        tblCellMar = OxmlElement("w:tblCellMar")
        for side_name, pt_val in (("top", tb_pt), ("left", lr_pt), ("bottom", tb_pt), ("right", lr_pt)):
            mar = OxmlElement(f"w:{side_name}")
            mar.set(qn("w:w"), str(int(pt_val * 20)))  # twips = pt * 20
            mar.set(qn("w:type"), "dxa")
            tblCellMar.append(mar)
        tblPr.append(tblCellMar)

        header_bg = self._theme.get("color_table_header_bg")
        header_text_color = self._theme.get("color_table_header_text")
        header_font_size = self._theme.get("font_size_th")
        body_font_size = self._theme.get("font_size_table")
        row_alt_bg = self._theme.get("color_table_row_alt_bg")
        cell_border_color = self._theme.get("color_table_cell_border", "d5d8dc")
        cell_border_size = self._theme.get("size_table_cell_border", 0.5)
        last_border_color = self._theme.get("color_table_last_row_border", cell_border_color)
        last_border_size = self._theme.get("size_table_last_row_border", 1.0)
        font_body = self._theme.get("font_body")
        font_code = self._theme.get("font_code", "Courier New")
        uppercase_th = self._theme.get("uppercase_th", False)
        letter_spacing_th = self._theme.get("letter_spacing_th_pt")

        n_rows = len(rows)

        for r_idx, row_cells in enumerate(rows):
            is_last_row = r_idx == n_rows - 1
            for c_idx, (is_header, cell_html) in enumerate(row_cells):
                if c_idx >= max_cols:
                    break
                cell = table.cell(r_idx, c_idx)
                cell.text = ""
                # Explicitly set cell width so fixed-layout tables honour the
                # grid widths rather than falling back to Word's own heuristic.
                tc = cell._tc
                tcPr = tc.get_or_add_tcPr()
                for old in tcPr.findall(qn("w:tcW")):
                    tcPr.remove(old)
                tcW_el = OxmlElement("w:tcW")
                tcW_el.set(qn("w:w"), str(col_widths_twips[c_idx]))
                tcW_el.set(qn("w:type"), "dxa")
                tcPr.append(tcW_el)
                para = cell.paragraphs[0]
                # Zero paragraph spacing so cell padding alone controls whitespace
                para.paragraph_format.space_before = Pt(0)
                para.paragraph_format.space_after = Pt(0)

                _render_cell_html(para, cell_html.strip(), self._theme, self._field_type,
                                  self._bookmark_id, bold_override=is_header)

                # Apply body font explicitly (Word table cells don't always inherit Normal)
                if font_body:
                    for run in para.runs:
                        if run.font.name is None or run.font.name not in (font_code, "Courier New"):
                            run.font.name = font_body

                # Apply font sizes
                size = header_font_size if is_header else body_font_size
                if size:
                    for run in para.runs:
                        run.font.size = Pt(size)

                # Header styling
                if is_header:
                    if uppercase_th:
                        for run in para.runs:
                            run.text = run.text.upper()
                    if header_text_color:
                        r, g, b = _hex_to_rgb(header_text_color)
                        for run in para.runs:
                            run.font.color.rgb = RGBColor(r, g, b)
                    if letter_spacing_th:
                        twips = int(letter_spacing_th * 20)
                        for run in para.runs:
                            rPr = run._r.get_or_add_rPr()
                            spacing = OxmlElement("w:spacing")
                            spacing.set(qn("w:val"), str(twips))
                            rPr.append(spacing)
                    if header_bg:
                        set_cell_shading(cell, header_bg)
                else:
                    # Alternating row shading (even body rows: r_idx 2, 4, 6, …)
                    if row_alt_bg and r_idx % 2 == 0:
                        set_cell_shading(cell, row_alt_bg)
                    # Bottom border
                    _set_cell_bottom_border(
                        cell,
                        color=last_border_color if is_last_row else cell_border_color,
                        pt=last_border_size if is_last_row else cell_border_size,
                    )

        self._paragraph = None


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------


def _setup_page(doc: Document) -> None:
    """Set A4 page size and margins matching the default PDF layout."""
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Mm(25)
    section.right_margin = Mm(20)
    section.top_margin = Mm(25)
    section.bottom_margin = Mm(22)


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------


def _add_docx_cover_page(
    doc: Document,
    config: dict[str, Any],
    builder: "_DocxBuilder",
    theme: dict[str, Any],
) -> None:
    """Insert a styled cover page for .docx output, then a page break.

    Approximates the PDF cover design: coloured top bar, cover label, title,
    thin divider, and metadata (author / date).
    """
    title = config.get("title", "")
    author = config.get("author", "")
    date_str = config.get("date", "")
    product = config.get("product", "")
    label = str(config.get("cover_label", "Report"))
    show_bar = bool(config.get("cover_bar", True))
    bar_height_str = str(config.get("cover_bar_height", "10mm"))
    footer_text = config.get("cover_footer_text") or (
        f"{author}  ·  Confidential" if author else ""
    )
    meta_label = str(config.get("cover_meta_label", "Prepared by"))

    bar_color = (theme.get("color_table_header_bg") or theme.get("color_h1") or "1b4f72").lstrip("#")
    label_color = (theme.get("color_h2") or theme.get("color_h1") or "2e86c1").lstrip("#")
    bar_mm = float(re.sub(r"[^\d.]", "", bar_height_str) or "10")

    # 1. Coloured top bar — full page width, bleeds into margins
    if show_bar:
        section = doc.sections[0]
        left_margin = section.left_margin
        page_width = section.page_width
        # Twips: 1 EMU = 1/635 twips
        page_twips = round(page_width / 635)
        left_twips = round(left_margin / 635)

        bar_tbl = doc.add_table(rows=1, cols=1)
        _clear_table_borders(bar_tbl)

        # Set table width to full page width
        tbl = bar_tbl._tbl
        tblPr = tbl.find(qn("w:tblPr"))
        if tblPr is None:
            tblPr = OxmlElement("w:tblPr")
            tbl.insert(0, tblPr)
        for old in tblPr.findall(qn("w:tblW")):
            tblPr.remove(old)
        tblW = OxmlElement("w:tblW")
        tblW.set(qn("w:w"), str(page_twips))
        tblW.set(qn("w:type"), "dxa")
        tblPr.append(tblW)
        # Negative left indent to bleed into left margin
        tblInd = OxmlElement("w:tblInd")
        tblInd.set(qn("w:w"), str(-left_twips))
        tblInd.set(qn("w:type"), "dxa")
        tblPr.append(tblInd)
        tr = bar_tbl.rows[0]._tr
        trPr = tr.get_or_add_trPr()
        trHeight = OxmlElement("w:trHeight")
        trHeight.set(qn("w:val"), str(int(Mm(bar_mm).pt * 20)))
        trHeight.set(qn("w:hRule"), "exact")
        trPr.append(trHeight)
        cell = bar_tbl.rows[0].cells[0]
        set_cell_shading(cell, bar_color)
        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = OxmlElement("w:tcBorders")
        for side in ("top", "left", "bottom", "right"):
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "none")
            tcBorders.append(b)
        tcPr.append(tcBorders)
        cell.paragraphs[0].paragraph_format.space_before = Pt(0)
        cell.paragraphs[0].paragraph_format.space_after = Pt(0)

    # 2. Cover label (e.g. "REPORT")
    if label:
        lp = doc.add_paragraph()
        lp.paragraph_format.space_before = Pt(30)
        lp.paragraph_format.space_after = Pt(0)
        run = lp.add_run(label.upper())
        run.bold = True
        run.font.size = Pt(8.5)
        r, g, b = _hex_to_rgb(label_color)
        run.font.color.rgb = RGBColor(r, g, b)

    # 3. Title
    title_para = doc.add_paragraph(style="Title")
    title_para.paragraph_format.space_before = Pt(10)
    builder._write_text(title_para, title or "Document")

    # 4. Product subtitle
    if product:
        sub_para = doc.add_paragraph(style="Subtitle")
        builder._write_text(sub_para, product)

    # 5. Divider line (3pt, uses bar colour)
    div_para = doc.add_paragraph()
    div_para.paragraph_format.space_before = Pt(14)
    div_para.paragraph_format.space_after = Pt(14)
    pPr = div_para._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bot = OxmlElement("w:bottom")
    bot.set(qn("w:val"), "single")
    bot.set(qn("w:sz"), "24")  # 3pt
    bot.set(qn("w:space"), "0")
    bot.set(qn("w:color"), bar_color.upper())
    pBdr.append(bot)
    pPr.append(pBdr)

    # 6. Author / date metadata
    if author:
        mp = doc.add_paragraph()
        mp.paragraph_format.space_before = Pt(0)
        mp.paragraph_format.space_after = Pt(4)
        mp.add_run(f"{meta_label}: ").bold = True
        builder._write_text(mp, author)
    if date_str:
        mp = doc.add_paragraph()
        mp.paragraph_format.space_before = Pt(0)
        mp.paragraph_format.space_after = Pt(4)
        mp.add_run("Date: ").bold = True
        builder._write_text(mp, date_str)

    # 7. Footer text (confidentiality notice)
    if footer_text:
        doc.add_paragraph()  # spacer
        fp = doc.add_paragraph()
        fp.paragraph_format.space_before = Pt(0)
        run = fp.add_run(footer_text)
        run.font.size = Pt(8)
        col = theme.get("color_em") or theme.get("color_h3")
        if col:
            r, g, b = _hex_to_rgb(col)
            run.font.color.rgb = RGBColor(r, g, b)

    doc.add_page_break()


def _add_cover_page(doc: Document, config: dict[str, Any], builder: "_DocxBuilder") -> None:
    """Insert a cover page section followed by a page break.

    All text values may contain ``[[field]]`` markers — rendered via *builder*
    so the correct field type (form/merge) and bookmark ID counter are used.
    """
    title = config.get("title", "")
    author = config.get("author", "")
    date = config.get("date", "")
    product = config.get("product", "")

    title_para = doc.add_paragraph(style="Title")
    builder._write_text(title_para, title or "«Document Title»")

    if product:
        sub_para = doc.add_paragraph(style="Subtitle")
        builder._write_text(sub_para, product)

    if author or date:
        doc.add_paragraph()  # spacer
        if author:
            meta = doc.add_paragraph()
            meta.add_run("Prepared by: ").bold = True
            builder._write_text(meta, author)
        if date:
            meta = doc.add_paragraph()
            meta.add_run("Date: ").bold = True
            builder._write_text(meta, date)

    doc.add_page_break()


# ---------------------------------------------------------------------------
# .dotx content-type patch
# ---------------------------------------------------------------------------


def _patch_to_dotx(path: Path) -> None:
    """Re-write *path* with the Word Template content type.

    python-docx always saves with the .docx content type. A .dotx differs
    only in one attribute inside ``[Content_Types].xml`` inside the ZIP.
    """
    tmp = path.with_suffix(".tmp")
    shutil.move(str(path), str(tmp))
    try:
        with zipfile.ZipFile(tmp, "r") as zin:
            with zipfile.ZipFile(path, "w") as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "[Content_Types].xml":
                        data = data.replace(
                            b"wordprocessingml.document.main+xml",
                            b"wordprocessingml.template.main+xml",
                        )
                    zout.writestr(item, data)
    except Exception:
        shutil.move(str(tmp), str(path))
        raise
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _strip_frontmatter(md_content: str) -> str:
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


def _resolve_docx_theme(doc_path: Path | None, repo_root: Path | None) -> dict[str, Any]:
    if doc_path is None or repo_root is None:
        return {}
    result = resolve_docx_theme(doc_path, repo_root)
    return result if result is not None else {}


def _resolve_asset(filename: str, doc_path: Path | None, repo_root: Path | None) -> Path | None:
    p = Path(filename)
    if p.is_absolute():
        return p if p.exists() else None
    search_dirs: list[Path] = []
    if doc_path:
        d = doc_path.parent if doc_path.is_file() else doc_path
        search_dirs.append(d)
        if repo_root:
            try:
                rel = d.relative_to(repo_root)
                for i in range(len(rel.parts) - 1, 0, -1):
                    search_dirs.append(repo_root / Path(*rel.parts[:i]))
            except ValueError:
                pass
            search_dirs.append(repo_root)
    for d in search_dirs:
        candidate = d / filename
        if candidate.exists():
            return candidate
    return None


def _add_page_header_bar(
    doc: Document,
    config: dict[str, Any],
    doc_path: Path | None,
    repo_root: Path | None,
) -> None:
    """Add a coloured header bar with optional logo to every page."""
    if not config.get("page_header_bar"):
        return

    color_hex = str(config.get("page_header_bar_color", "#2563eb")).lstrip("#")
    text_color_hex = str(config.get("page_header_bar_text_color", "#ffffff")).lstrip("#")
    height_str = str(config.get("page_header_bar_height", "12mm"))
    padding_str = str(config.get("page_header_bar_padding", "6mm"))
    logo_file = config.get("page_header_bar_logo") or config.get("header_logo")
    header_text = config.get("header_text", "")

    height_mm = float(re.sub(r"[^\d.]", "", height_str) or "12")
    gap_mm = float(re.sub(r"[^\d.]", "", padding_str) or "6")

    logo_path = _resolve_asset(str(logo_file), doc_path, repo_root) if logo_file else None

    section = doc.sections[0]
    header = section.header

    header_distance_mm = section.header_distance / 914400 * 25.4  # EMU → mm
    section.top_margin = Mm(header_distance_mm + height_mm + gap_mm)

    for para in list(header.paragraphs):
        para._p.getparent().remove(para._p)

    text_width = section.page_width - section.left_margin - section.right_margin
    cols = 2 if logo_path else 1
    table = header.add_table(rows=1, cols=cols, width=text_width)

    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)

    # Override width to 100% (pct) — matches body tables and avoids any
    # rounding difference vs the absolute-EMU value set by add_table().
    for old in tblPr.findall(qn("w:tblW")):
        tblPr.remove(old)
    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:w"), "5000")
    tblW.set(qn("w:type"), "pct")
    tblPr.append(tblW)

    # Zero the table indent so the bar starts at the left margin — Word
    # applies a default ~108-twip indent which makes the header narrower
    # than body tables.
    for old in tblPr.findall(qn("w:tblInd")):
        tblPr.remove(old)
    tblInd = OxmlElement("w:tblInd")
    tblInd.set(qn("w:w"), "0")
    tblInd.set(qn("w:type"), "dxa")
    tblPr.append(tblInd)

    tblBorders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "none")
        tblBorders.append(b)
    tblPr.append(tblBorders)

    row = table.rows[0]
    tr = row._tr
    trPr = tr.get_or_add_trPr()
    trHeight = OxmlElement("w:trHeight")
    trHeight.set(qn("w:val"), str(int(Mm(height_mm).pt * 20)))
    trHeight.set(qn("w:hRule"), "atLeast")
    trPr.append(trHeight)

    for cell in row.cells:
        set_cell_shading(cell, color_hex)
        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = OxmlElement("w:tcBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "none")
            tcBorders.append(b)
        tcPr.append(tcBorders)
        vAlign = OxmlElement("w:vAlign")
        vAlign.set(qn("w:val"), "center")
        tcPr.append(vAlign)

    if header_text:
        para = row.cells[0].paragraphs[0]
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)
        run = para.add_run(str(header_text))
        run.bold = True
        run.font.color.rgb = RGBColor.from_string(text_color_hex)
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT

    if logo_path:
        para = row.cells[-1].paragraphs[0]
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = para.add_run()
        run.add_picture(str(logo_path), height=Mm(max(height_mm * 0.7, 4)))


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------


def _add_footer(doc: Document, config: dict[str, Any]) -> None:
    """Add footer_center text to the document's default section footer.

    Newlines in the text become separate paragraphs so each line renders
    independently. The first paragraph gets a top border to visually separate
    the footer from body content.
    """
    center_text: str | None = config.get("footer_center")
    if not center_text:
        return

    section = doc.sections[0]
    section.footer.is_linked_to_previous = False
    footer = section.footer

    # Clear the default empty paragraph Word adds
    for para in list(footer.paragraphs):
        p = para._element
        p.getparent().remove(p)

    lines = center_text.split("\n")
    para = footer.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    pPr = para._element.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single")
    top.set(qn("w:sz"), "4")
    top.set(qn("w:space"), "4")
    top.set(qn("w:color"), "d5d8dc")
    pBdr.append(top)
    pPr.append(pBdr)

    for i, line in enumerate(lines):
        if i > 0:
            para.add_run().add_break()
        run = para.add_run(line)
        run.font.size = Pt(6)
        run.font.color.rgb = RGBColor(0x73, 0x85, 0x99)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build(
    rendered_md: str,
    config: dict[str, Any],
    out_path: Path,
    *,
    doc_path: Path | None = None,
    repo_root: Path | None = None,
    output_format: str = "docx",
) -> None:
    """Convert rendered Markdown to a .docx or .dotx file.

    Parameters
    ----------
    rendered_md:
        Jinja2-rendered Markdown string (may include frontmatter).
    config:
        Merged config dict from load_config().
    out_path:
        Destination path for the generated file.
    doc_path:
        Source .md path — used to resolve the CSS theme cascade.
    repo_root:
        Repo root — used to bound the CSS theme cascade.
    output_format:
        ``"docx"`` (default) or ``"dotx"``.  When ``"dotx"``, ``[[field]]``
        markers are converted to Word fields and the saved file is patched to
        the Word Template content type.
    """
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_dotx = output_format == "dotx"

    field_type: str | None = None
    cover_page = bool(config.get("cover_page", True))

    if is_dotx:
        ft = str(config.get("dotx_field_type", "form")).lower()
        field_type = ft if ft in ("form", "merge") else "form"

    body = _strip_frontmatter(rendered_md)
    title: str = config.get("title") or _extract_title(body) or out_path.stem
    author: str = config.get("author", "")

    if cover_page:
        body = _strip_leading_h1(body)
    elif not is_dotx:
        body = _strip_leading_h1(body)

    body = _inject_page_breaks(body)

    md_engine = markdown.Markdown(extensions=_MD_EXTENSIONS)
    html = md_engine.convert(body)

    theme = _resolve_docx_theme(doc_path, repo_root)
    doc = Document()
    _setup_page(doc)

    props = doc.core_properties
    if is_dotx:
        props.title = re.sub(r"\[\[\w+\]\]", "", title).strip()
        if author:
            props.author = re.sub(r"\[\[\w+\]\]", "", author).strip()
    else:
        props.title = title
        if author:
            props.author = author

    _add_page_header_bar(doc, config, doc_path, repo_root)
    _add_footer(doc, config)

    body_text_align = str(config.get("body_text_align", "")).lower() or None

    raw_col_widths = config.get("table_col_widths")
    table_col_widths: list[float] | None = None
    if isinstance(raw_col_widths, list) and all(isinstance(v, (int, float)) for v in raw_col_widths):
        table_col_widths = [float(v) for v in raw_col_widths]

    builder = _DocxBuilder(
        doc,
        theme=theme,
        field_type=field_type,
        body_text_align=body_text_align,
        table_col_widths=table_col_widths,
    )

    if cover_page:
        if is_dotx:
            _add_cover_page(doc, {**config, "title": title}, builder)
        else:
            _add_docx_cover_page(doc, {**config, "title": title}, builder, theme)
    elif not is_dotx:
        doc.add_paragraph(title, style="Title")

    builder.feed(html)

    doc.save(str(out_path))

    # Patch the document theme XML to match the CSS font — ensures LibreOffice
    # and other renderers show the correct font family instead of Calibri/Cambria.
    font_body = theme.get("font_body")
    if font_body:
        patch_docx_theme_fonts(out_path, font_body)

    if is_dotx:
        _patch_to_dotx(out_path)
