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

import datetime
import logging
import re
import shutil
import zipfile
from contextvars import ContextVar
from html import escape, unescape
from ._cover import footer_band_geometry
from io import BytesIO
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Mm, Pt, RGBColor

from ..config import coerce_bool
from ..forms import collapse_select_markup
from ..table_layout import css_code_line_pitch, css_column_weights, css_row_heights
from ..docx_theme import (
    _apply_font_name,
    _hex_to_rgb,
    apply_theme_to_doc,
    parse_css_for_word,
    patch_docx_theme_fonts,
    resolve_docx_theme,
    set_cell_shading,
    set_para_shading,
)
from .pdf import _inject_appendix_breaks, _inject_page_breaks, _keep_heading_with_next
from ._assets import (
    _DEFAULT_GEOMETRY,
    _drop_empty_table_headers,
    _length_to_mm,
    _page_geometry,
    apply_theme_config_defaults,
    _EMU_PER_PX,
    _MERMAID_IMG_RE,
    _render_mermaid_to_images,
    _resolve_asset,
    _svg_to_png,
)

logger = logging.getLogger(__name__)

# Re-exported for backwards compatibility (tests/other modules import these
# from docx); the implementations now live in ._assets.
__all__ = [
    "build",
    "_EMU_PER_PX",
    "_MERMAID_IMG_RE",
    "_render_mermaid_to_images",
    "_resolve_asset",
    "_svg_to_png",
]


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

# [[name]] — Word field markers. Also matches the internal markers the dotx
# form-conversion emits for the ?[...] shorthand: [[?cb:name]] (checkbox) and
# [[?dd:name|Option 1|Option 2]] (dropdown). Plain user markers stay \w+ only.
_MERGE_RE = re.compile(r"\[\[(\?(?:cb|dd):[^\[\]]+|\w+)\]\]")


# ---------------------------------------------------------------------------
# Hyperlink helper
# ---------------------------------------------------------------------------


def _bookmark_name(anchor: str) -> str:
    """Sanitize an HTML anchor into a valid Word bookmark name.

    Word bookmark names must start with a letter and contain only letters,
    digits and underscores (footnote anchors like ``fn:1`` are invalid as-is).
    Applied to both bookmark definitions and references so they stay in sync.
    """
    name = re.sub(r"[^0-9A-Za-z_]", "_", anchor)
    if not name or not name[0].isalpha():
        name = "a_" + name
    return name[:40]


def _insert_hyperlink(paragraph: Any, text: str, url: str, *, superscript: bool = False) -> None:
    """Append a clickable hyperlink to *paragraph*.

    External links display as ``text (url)`` when text differs from url, or
    just ``url`` when they're the same — keeping the URL visible in printed
    output (the PDF does this with an ``::after`` rule). Internal ``#anchor``
    links become bookmark jumps with no URL suffix, matching the PDF, which
    suppresses the suffix for fragment links.
    """
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    display = text.strip()
    url_clean = url.strip()

    hyperlink = OxmlElement("w:hyperlink")
    if url_clean.startswith("#"):
        display = display or url_clean
        hyperlink.set(qn("w:anchor"), _bookmark_name(url_clean[1:]))
    else:
        if display and display != url_clean:
            display = f"{display} ({url_clean})"
        else:
            display = url_clean
        r_id = paragraph.part.relate_to(url_clean, RT.HYPERLINK, is_external=True)
        hyperlink.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rStyle = OxmlElement("w:rStyle")
    rStyle.set(qn("w:val"), "Hyperlink")
    rPr.append(rStyle)
    if superscript:
        vert = OxmlElement("w:vertAlign")
        vert.set(qn("w:val"), "superscript")
        rPr.append(vert)
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


# Geometry of a text input in the PDF theme (``padding: 4pt 6pt; border: 1pt;
# margin: 2pt 0 8pt``, 10pt text on a 12pt line). Word field boxes use the same
# numbers so a form page consumes the same vertical space in both formats.
_FIELD_LINE_PT = 12.0
_FIELD_PAD_X_PT = 6.0
_FIELD_PAD_Y_PT = 4.0
_FIELD_BORDER_PT = 1.0
_FIELD_MARGIN_TOP_PT = 2.0
_FIELD_MARGIN_BOTTOM_PT = 8.0
_FIELD_BORDER_COLOR = "5D6D7E"
_FIELD_FILL = "FAFAFA"
_TEXTAREA_MIN_PT = 48.0
# A line holding a checkbox or radio is taller in the PDF (16pt control plus
# 1pt margins, rounded up by the line box).
_CHOICE_LINE_PT = 23.5
# Height of an input line inside a form-grid cell (PDF: 14pt; a bare write-in
# cell with nothing else in it gets a 19pt band).
_CELL_INPUT_PT = 14.7
_CELL_BARE_INPUT_PT = 19.0
# ... and in borderless rows / ordinary tables (PDF: table td > input { height: 13pt }).
_CELL_PLAIN_INPUT_PT = 15.2
_CELL_CHOICE_LINE_PT = 18.3
_CELL_PLAIN_BARE_PT = 13.0
_CHOICE_MARKS = "\u2610\u2611\u25cb"

# The constants above were fitted against themes with 9.5pt table text and
# 10.5pt body text. Measured against WeasyPrint at 8-18pt: a text input's box is
# a fixed height regardless of font size (so ``line`` never scales), while the
# descent an empty input sits above is proportional to the *body* font (0.479 em).
# Cell and choice lines scale with the text they sit in.
_REF_TABLE_FONT_PT = 9.5
_REF_BODY_FONT_PT = 10.5
_RELIEF_PER_BODY_PT = 0.479


def _compute_form_dims(theme: dict[str, Any]) -> dict[str, float]:
    box = theme.get("form_input") or {}
    body_pt = float(theme.get("font_size_body") or _REF_BODY_FONT_PT)
    tab = float(theme.get("font_size_table") or _REF_TABLE_FONT_PT) / _REF_TABLE_FONT_PT
    body = body_pt / _REF_BODY_FONT_PT
    return {
        "body_pt": body_pt,
        "signature_h": 3.0 * body_pt,
        "line": _FIELD_LINE_PT,
        "margin_top": float(box.get("margin_top", _FIELD_MARGIN_TOP_PT)),
        "margin_bottom": float(box.get("margin_bottom", _FIELD_MARGIN_BOTTOM_PT)),
        "relief": _RELIEF_PER_BODY_PT * body_pt,
        "textarea_min": float(box.get("textarea_min", _TEXTAREA_MIN_PT)),
        "choice_line": _CHOICE_LINE_PT * body,
        "cell_input": _CELL_INPUT_PT * tab,
        "cell_bare": _CELL_BARE_INPUT_PT * tab,
        "cell_plain": _CELL_PLAIN_INPUT_PT * tab,
        "cell_plain_bare": _CELL_PLAIN_BARE_PT * tab,
        "cell_choice": _CELL_CHOICE_LINE_PT * tab,
    }


_FORM_DIMS: ContextVar[dict[str, float] | None] = ContextVar("md_doc_form_dims", default=None)


def _dim(name: str) -> float:
    """Form-geometry value for the document being built (theme-scaled)."""
    dims = _FORM_DIMS.get()
    if dims is None:
        dims = _compute_form_dims({})
    return dims[name]


# w:pPr children that must follow w:pBdr / w:shd in schema order.
_PPR_AFTER_SHD = (
    "tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE "
    "autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents "
    "suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId "
    "cnfStyle rPr sectPr pPrChange"
).split()


def _insert_ppr_in_order(pPr: Any, element: Any, successors: list[str]) -> None:
    """Insert *element* into ``w:pPr`` before the first schema successor."""
    for child in pPr:
        if child.tag in {qn(f"w:{name}") for name in successors}:
            child.addprevious(element)
            return
    pPr.append(element)


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


def _logo_height_mm(path: Path, cap_mm: float, forced_mm: float | None = None) -> float:
    """Display height (mm) for a header logo — same rule as the PDF builder.

    ``forced_mm`` (from ``header_logo_height``) wins outright. Otherwise the
    logo renders at its intrinsic height (96dpi), capped at *cap_mm* — never
    upscaled. Falls back to *cap_mm* if the image can't be read.
    """
    if forced_mm is not None:
        return forced_mm
    try:
        from PIL import Image

        with Image.open(path) as im:
            intrinsic_mm = im.height / 96 * 25.4
        return min(intrinsic_mm, cap_mm)
    except Exception:
        return cap_mm


def _parse_mm_cfg(value: Any) -> float | None:
    """Parse a '10mm'-style config value to mm, or None when unset/invalid."""
    if value is None:
        return None
    try:
        return float(re.sub(r"[^\d.]", "", str(value)) or 0) or None
    except ValueError:
        return None


def _insert_checkbox_form_field(paragraph: Any, field_name: str) -> None:
    """Append a Word legacy checkbox form field (FORMCHECKBOX) to *paragraph*."""
    run = paragraph.add_run()
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
    checkbox = OxmlElement("w:checkBox")
    checkbox.append(OxmlElement("w:sizeAuto"))
    default = OxmlElement("w:default")
    default.set(qn("w:val"), "0")
    checkbox.append(default)
    ff_data.append(checkbox)
    fld_begin.append(ff_data)
    run._r.append(fld_begin)

    run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " FORMCHECKBOX "
    run._r.append(instr)

    run = paragraph.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_end)


def _insert_dropdown_form_field(paragraph: Any, field_name: str, options: list[str]) -> None:
    """Append a Word legacy dropdown form field (FORMDROPDOWN) to *paragraph*."""
    run = paragraph.add_run()
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
    dd_list = OxmlElement("w:ddList")
    for opt in options:
        entry = OxmlElement("w:listEntry")
        entry.set(qn("w:val"), opt[:255])  # Word limit per entry
        dd_list.append(entry)
    ff_data.append(dd_list)
    fld_begin.append(ff_data)
    run._r.append(fld_begin)

    run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " FORMDROPDOWN "
    run._r.append(instr)

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
    write_text: Any,
    *,
    bold_override: bool = False,
    insert_math: Any = None,
    insert_image: Any = None,
    input_pt: float = 0.0,
    bare_input_pt: float = 0.0,
    label_style: dict[str, Any] | None = None,
    caption_style: dict[str, Any] | None = None,
) -> None:
    """Parse the inner HTML of a table cell and write runs into *paragraph*.

    Handles inline tags: strong/b (bold), em/i (italic), code (monospace),
    a (hyperlink), br. Text (including ``[[field]]`` markers) is written via
    *write_text*, which is the builder's ``_write_text`` method — ensuring
    field conversion and bookmark tracking work identically to body text.
    """
    from html.parser import HTMLParser as _HP

    bare_input = bool(
        re.fullmatch(r'\s*<span class="docx-input"[^>]*>.*</span>\s*', html, re.DOTALL)
    )

    class _CellParser(_HP):
        def __init__(self) -> None:
            super().__init__()
            self._bold = bold_override
            self._italic = False
            self._code = False
            self._href: str | None = None
            self._link_text = ""
            self._label = False
            self._cap = False

        def handle_starttag(self, tag: str, attrs: list) -> None:
            tag = tag.lower()
            if tag == "span" and "docx-cap" in (dict(attrs).get("class") or ""):
                self._cap = True
            elif tag == "label" and label_style:
                self._label = True
            elif tag in ("strong", "b"):
                self._bold = True
            elif tag in ("em", "i"):
                self._italic = True
            elif tag == "code":
                self._code = True
            elif tag == "a":
                self._href = dict(attrs).get("href") or ""
                self._link_text = ""
            elif tag == "img":
                src = dict(attrs).get("src") or ""
                if src.startswith("math://") and insert_math is not None:
                    insert_math(paragraph, src)
                elif insert_image is not None:
                    insert_image(dict(attrs), paragraph)
            elif tag == "br":
                br_run = paragraph.add_run()
                br_run._r.append(OxmlElement("w:br"))
            elif tag == "span" and "docx-input" in (dict(attrs).get("class") or ""):
                self._start_input(dict(attrs).get("data-h"))

        def _start_input(self, declared: str | None = None) -> None:
            """An input sits on its own line, as tall as the PDF's input."""
            if paragraph.text.strip() or paragraph._p.xpath(".//w:drawing"):
                br_run = paragraph.add_run()
                br_run._r.append(OxmlElement("w:br"))
            height = (bare_input_pt if bare_input else input_pt) or _dim("cell_input")
            if declared:
                height = max(height, float(declared))
            strut = paragraph.add_run("\u00a0")
            # The line grows to the input's height; remembered so the cell's
            # blanket font-size pass can restore it (see _flush_table).
            paragraph.__dict__.setdefault("_struts", []).append((strut, height / 1.17))

        def handle_endtag(self, tag: str) -> None:
            tag = tag.lower()
            if tag in ("strong", "b"):
                self._bold = bold_override  # back to cell default
            elif tag in ("em", "i"):
                self._italic = False
            elif tag == "code":
                self._code = False
            elif tag == "a":
                if self._link_text:
                    if self._href:
                        _insert_hyperlink(paragraph, self._link_text, self._href)
                    else:
                        write_text(paragraph, self._link_text)
                self._href = None
                self._link_text = ""
            elif tag == "label":
                self._label = False
            elif tag == "span":
                self._cap = False

        def handle_data(self, data: str) -> None:
            data = re.sub(r"[ \t\r\n\f]+", " ", data)
            if not data:
                return
            if self._href is not None:
                self._link_text += data
                return
            if self._cap and caption_style:
                self._write_caption(data)
                return
            if self._label and label_style:
                self._write_label(data)
                return
            write_text(paragraph, data, bold=self._bold, italic=self._italic, code=self._code)

        def _write_caption(self, data: str) -> None:
            """Caption under a write-in rule: small bold uppercase, themed colour."""
            assert caption_style is not None
            before = len(paragraph.runs)
            write_text(paragraph, data.upper(), bold=True)
            for run in paragraph.runs[before:]:
                run.font.size = Pt(float(caption_style["size"]))
                r, g, b = _hex_to_rgb(str(caption_style["color"]))
                run.font.color.rgb = RGBColor(r, g, b)
                spacing = OxmlElement("w:spacing")
                spacing.set(qn("w:val"), str(round(float(caption_style["size"]) * 0.07 * 20)))
                run._r.get_or_add_rPr().append(spacing)

        def _write_label(self, data: str) -> None:
            """Field label: the theme's label size / colour / case / tracking."""
            assert label_style is not None
            before = len(paragraph.runs)
            text = data.upper() if label_style.get("upper") else data
            write_text(paragraph, text, bold=bool(label_style.get("bold")))
            for run in paragraph.runs[before:]:
                if label_style.get("size"):
                    run.font.size = Pt(float(label_style["size"]))
                if label_style.get("color"):
                    r, g, b = _hex_to_rgb(str(label_style["color"]))
                    run.font.color.rgb = RGBColor(r, g, b)
                if label_style.get("tracking"):
                    spacing = OxmlElement("w:spacing")
                    spacing.set(qn("w:val"), str(round(float(label_style["tracking"]) * 20)))
                    run._r.get_or_add_rPr().append(spacing)

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
        *,
        mermaid_images: list[tuple[bytes, int, int]] | None = None,
        math_equations: list[Any] | None = None,
        doc_path: Path | None = None,
        repo_root: Path | None = None,
        section_bar: dict[str, Any] | None = None,
        layout_css: Path | None = None,
        form_document: bool = False,
    ) -> None:
        super().__init__()
        self.convert_charrefs = True
        self.doc = doc
        self._theme: dict[str, Any] = theme or {}
        self._field_type = field_type  # None | "form" | "merge"
        self._body_text_align = body_text_align  # default alignment for Normal paragraphs
        self._table_col_widths = table_col_widths  # e.g. [30, 70] — relative column widths
        self._mermaid_images = mermaid_images or []
        self._math_equations = math_equations or []
        self._doc_path = doc_path
        self._repo_root = repo_root
        self._section_bar = section_bar  # None or parsed section_bar config
        self._layout_css = layout_css  # PDF theme CSS used for table auto-layout
        # pdf_forms documents draw ordinary tables as plain black grids.
        self._form_document = form_document

        apply_theme_to_doc(self.doc, self._theme)

        # State tracking
        self._paragraph = None
        self._run = None
        self._bold = False
        self._italic = False
        self._in_pre = False
        self._in_code = False
        self._in_blockquote = False
        self._sup = False
        self._sub = False
        self._strike = False
        self._list_stack: list[str] = []
        self._list_num_ids: list[int | None] = []
        self._list_counters: list[int] = []
        # Loose-list handling: markdown wraps list-item text in <p> when items
        # are separated by blank lines.  The first <p> inside an <li> must
        # reuse the bullet/number paragraph the <li> created — replacing it
        # would leave an empty bullet followed by unbulleted body text.
        self._li_depth = 0
        self._li_fresh = False
        # First body H1 never forces a page break (parity with the PDF's
        # h1:first-of-type suppression).
        self._seen_h1 = False

        # Table state — cells store raw inner HTML to preserve inline markup
        self._in_table = False
        self._in_cell = False  # True while cursor is inside a <th> or <td>
        self._in_th = False
        self._table_form_kind: str | None = None
        self._table_pdf_html: str | None = None
        self._table_rows: list[list[tuple[bool, str, str | None]]] = []
        self._current_row: list[tuple[bool, str, str | None, dict[str, str]]] = []
        self._table_style: dict[str, str] = {}
        self._table_gap = 0.0
        self._current_cell_style: dict[str, str] = {}
        self._current_cell_html = ""
        self._current_cell_align: str | None = None  # per-cell text-align from markdown :--:
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
        self._div_stack: list[int | None] = []
        self._page_break_pending = False
        self._bq_paras: list[Any] = []
        # Margins (before, after) that must not collapse with a neighbour.
        self._fixed_margins: dict[Any, tuple[float, float]] = {}

        # Hyperlink state — set while inside <a href="...">
        self._current_href: str | None = None
        self._link_text_buf: str = ""

        # Section-bar state — the heading tag currently wearing a bar (or None)
        self._section_bar_active_tag: str | None = None

        # Body-length baseline for page-break-before headings.  A heading that
        # is the very first content element must not force a break (matching
        # CSS, where a forced break at the top of a page collapses).  build()
        # re-baselines this after the cover page is added.
        self.mark_content_start()

    def mark_content_start(self) -> None:
        """Record the current body length as the start of report content."""
        self._body_baseline = len(self.doc.element.body)

    def _add_bookmark(self, paragraph: Any, anchor: str) -> None:
        """Insert a Word bookmark named after *anchor* into *paragraph*.

        Targets for internal ``#anchor`` hyperlinks (headings, footnote
        definitions, footnote references).
        """
        name = _bookmark_name(anchor)
        start = OxmlElement("w:bookmarkStart")
        start.set(qn("w:id"), str(self._bookmark_id))
        start.set(qn("w:name"), name)
        end = OxmlElement("w:bookmarkEnd")
        end.set(qn("w:id"), str(self._bookmark_id))
        self._bookmark_id += 1
        paragraph._p.append(start)
        paragraph._p.append(end)

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
    # Section bar helpers (mirror pdf._build_section_bar_style)
    # ------------------------------------------------------------------

    def _apply_section_bar_start(self, tag: str) -> None:
        """Apply the section-bar background/border to a freshly created heading.

        Mirrors the PDF's ``padding: 6pt 12pt`` (bar) / ``border-top: 4pt;
        padding-top: 6pt`` (band) while leaving the heading's own margins alone.
        Padding is paragraph-border spacing, which Word shades along with the
        text, and the left/right padding doubles as the text inset so the bar
        spans the full text width.
        """
        self._section_bar_active_tag = None
        sb = self._section_bar
        if not sb or tag not in sb["headings"] or self._paragraph is None:
            return
        self._section_bar_active_tag = tag
        para = self._paragraph
        color = sb["color"].lstrip("#").upper()
        pPr = para._p.get_or_add_pPr()
        for old in pPr.findall(qn("w:pBdr")):
            pPr.remove(old)
        pBdr = OxmlElement("w:pBdr")

        def edge(side: str, size: int, space: int) -> None:
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), str(size))
            el.set(qn("w:space"), str(space))
            el.set(qn("w:color"), color)
            pBdr.append(el)

        if sb["text_on_bar"]:
            set_para_shading(para, color)
            # Hairline edges in the fill colour carry the padding (Word shades
            # the space inside a border); the 12pt side padding is also the
            # text inset, so the indent keeps the bar on the text margins.
            edge("top", 2, 6)
            edge("left", 2, 12)
            edge("bottom", 2, 6)
            edge("right", 2, 12)
            # Adjacent paragraphs with identical borders *and* indents merge into
            # one bordered block in Word; a one-twip step per heading level keeps
            # consecutive bars (H1 then H2) separate and visually identical.
            inset = 12.25 + 0.05 * (int(tag[1]) - 1)
            para.paragraph_format.left_indent = Pt(inset)
            para.paragraph_format.right_indent = Pt(inset)
        else:
            # border-top: 4pt, padding-top: 6pt. One eighth-point per level keeps
            # consecutive bands from merging into a single bordered block.
            edge("top", round(4 * 8) - (int(tag[1]) - 1), 6)
        _insert_ppr_in_order(pPr, pBdr, ["shd", *_PPR_AFTER_SHD])

    def _apply_section_bar_runs(self) -> None:
        """Colour the heading's runs white once its text has been written."""
        sb = self._section_bar
        if not sb or not sb["text_on_bar"] or self._paragraph is None:
            return
        r, g, b = _hex_to_rgb(sb["text_color"])
        for run in self._paragraph.runs:
            run.font.color.rgb = RGBColor(r, g, b)

    # ------------------------------------------------------------------
    # Paragraph helpers
    # ------------------------------------------------------------------

    def _new_para(self, style: str = "Normal") -> None:
        after_table = len(self.doc._element.body) > 1 and self.doc._element.body[-2].tag == qn(
            "w:tbl"
        )
        self._paragraph = self.doc.add_paragraph(style=style)
        if after_table and self._theme.get("table_space_after"):
            self._paragraph.paragraph_format.space_before = Pt(self._theme["table_space_after"])
        self._run = None
        if self._page_break_pending:
            self._page_break_pending = False
            self._begin_page_with(self._paragraph)

    def _current_para(self) -> Any:
        if self._paragraph is None:
            self._new_para()
        return self._paragraph

    def _style_signature_line(self, para: Any) -> None:
        """Signature field: a ruled slot 3 body-em high, 60% of the width (as the PDF)."""
        body = _dim("body_pt")
        fmt = para.paragraph_format
        # The PDF block margins (1.2em / 1.4em) collapse with neighbours like any
        # CSS margin, so they are ordinary (not fixed) paragraph spacing here.
        self._fixed_margins.pop(para._p, None)
        fmt.space_before = Pt(1.2 * body)
        fmt.space_after = Pt(0)
        fmt.left_indent = Pt(0)
        text_width_pt = self._text_width_emu() / 12700
        fmt.right_indent = Pt(text_width_pt * 0.4)
        fmt.line_spacing = Pt(_dim("signature_h"))
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.keep_with_next = True
        pPr = para._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "8")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "555555")
        pBdr.append(bottom)
        _insert_ppr_in_order(pPr, pBdr, ["shd", *_PPR_AFTER_SHD])

    def _start_signature_caption(self) -> None:
        """The small uppercase caption under a signature rule."""
        body = _dim("body_pt")
        self._new_para("Normal")
        para = self._paragraph
        fmt = para.paragraph_format
        size = 0.75 * body
        fmt.space_before = Pt(0.3 * body)
        fmt.space_after = Pt(1.4 * body)
        fmt.left_indent = Pt(0)
        fmt.right_indent = Pt(self._text_width_emu() / 12700 * 0.4)
        fmt.line_spacing = Pt(size * 1.65)
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.alignment = WD_ALIGN_PARAGRAPH.LEFT
        self._signature_caption = para

    def _finish_signature_caption(self) -> None:
        para = self.__dict__.get("_signature_caption")
        if para is None:
            return
        self._signature_caption = None
        size = 0.75 * _dim("body_pt")
        for run in para.runs:
            run.text = run.text.upper()
            run.font.size = Pt(size)
            run.font.color.rgb = RGBColor(0x7F, 0x8C, 0x9A)
            spacing = OxmlElement("w:spacing")
            spacing.set(qn("w:val"), str(int(size * 0.2 * 20)))
            run._r.get_or_add_rPr().append(spacing)

    def _add_rule(self) -> None:
        """A horizontal rule: a hairline paragraph carrying the CSS ``hr`` margins.

        The PDF draws ``hr`` as a thin ruled line with ``margin: 12pt 0``. A
        Word rule paragraph would otherwise keep a full text-line height, so
        use an exact 1pt line; neighbouring margins collapse in
        :func:`_collapse_paragraph_margins`.
        """
        para = self.doc.add_paragraph()
        self._paragraph = para
        fmt = para.paragraph_format
        fmt.space_before = Pt(float(self._theme.get("hr_space_before", 6.0)))
        fmt.space_after = Pt(float(self._theme.get("hr_space_after", 6.0)))
        fmt.line_spacing = Pt(1)
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.keep_with_next = True
        if self._page_break_pending:
            self._page_break_pending = False
            self._begin_page_with(para)
        para.add_run().font.size = Pt(1)
        hr_color = (self._theme.get("color_hr") or "#aaaaaa").lstrip("#").upper()
        hr_sz = str(max(1, round(self._theme.get("size_hr", 0.75) * 8)))
        pPr = para._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), hr_sz)
        bottom.set(qn("w:space"), "0")
        bottom.set(qn("w:color"), hr_color)
        pBdr.append(bottom)
        _insert_ppr_in_order(pPr, pBdr, ["shd", *_PPR_AFTER_SHD])

    def _apply_box_model(self, para: Any, kind: str) -> None:
        """Shade a paragraph like a CSS box: background, left rule, padding, margins.

        ``kind`` is ``"pre"`` or ``"blockquote"``. Vertical padding becomes
        paragraph-border spacing drawn in the background colour (Word shades the
        space inside a border), so the filled box is as tall as the PDF's.
        """
        theme = self._theme
        bg = theme.get("pre_background_color" if kind == "pre" else "blockquote_background_color")
        border_color = theme.get("pre_border_color" if kind == "pre" else "blockquote_border_color")
        border_pt = float(theme.get(f"{kind}_border_pt", 3.0))
        pad_left = float(theme.get(f"{kind}_padding_left", 10.0))
        pad_top = float(theme.get(f"{kind}_padding_top", 0.0))
        pad_bottom = float(theme.get(f"{kind}_padding_bottom", 0.0))
        if kind == "blockquote":
            # The first/last paragraph's own margins sit *inside* the CSS box (the
            # padding keeps them from collapsing out), so shade them: fold them
            # into the padding of every paragraph, which Word applies only at the
            # ends of the continuous bordered block.
            pad_top += float(theme.get("blockquote_p_margin_top", 0.0))
            pad_bottom += float(
                theme.get("blockquote_p_margin_bottom", theme.get("para_space_after", 0.0))
            )
        default_top, default_bottom = (6.0, 10.0) if kind == "pre" else (6.0, 8.0)
        margin_top = float(theme.get(f"{kind}_margin_top", default_top))
        margin_bottom = float(theme.get(f"{kind}_margin_bottom", default_bottom))

        fmt = para.paragraph_format
        fmt.space_before = Pt(margin_top)
        fmt.space_after = Pt(margin_bottom)
        if kind == "blockquote":
            # Margins between paragraphs of the quote; its own outer margins are
            # restored on the first and last paragraph in _finish_blockquote.
            fmt.space_before = Pt(0)
            fmt.space_after = Pt(float(theme.get("blockquote_p_margin_bottom", 0.0)))
        pPr = para._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        if bg:
            set_para_shading(para, bg)
            for side, pad in (("top", pad_top), ("bottom", pad_bottom)):
                if pad > 0:
                    edge = OxmlElement(f"w:{side}")
                    edge.set(qn("w:val"), "single")
                    edge.set(qn("w:sz"), "2")  # hairline in the fill colour
                    edge.set(qn("w:space"), str(round(pad)))
                    edge.set(qn("w:color"), bg.lstrip("#").upper())
                    pBdr.append(edge)
        else:
            fmt.space_before = Pt(margin_top + pad_top)
            fmt.space_after = Pt(margin_bottom + pad_bottom)
        if border_color:
            left = OxmlElement("w:left")
            left.set(qn("w:val"), "single")
            left.set(qn("w:sz"), str(max(1, round(border_pt * 8))))
            left.set(qn("w:space"), str(round(pad_left)))
            left.set(qn("w:color"), border_color.lstrip("#").upper())
            pBdr.append(left)
            # Word draws the rule *outside* the indent: indent by rule + padding
            # so the rule sits on the text margin as it does in the PDF.
            fmt.left_indent = Pt(border_pt + pad_left)
        elif bg:
            fmt.left_indent = Pt(pad_left)
        if len(pBdr):
            order = {"top": 0, "left": 1, "bottom": 2, "right": 3}
            for edge in sorted(pBdr, key=lambda e: order[e.tag.split("}")[1]]):
                pBdr.remove(edge)
                pBdr.append(edge)
            _insert_ppr_in_order(pPr, pBdr, ["shd", *_PPR_AFTER_SHD])

    def _finish_blockquote(self) -> None:
        """Restore the blockquote's outer margins on its first and last paragraph."""
        paras, self._bq_paras = self._bq_paras, []
        if not paras:
            return
        theme = self._theme
        paras[0].paragraph_format.space_before = Pt(float(theme.get("blockquote_margin_top", 6.0)))
        paras[-1].paragraph_format.space_after = Pt(
            float(theme.get("blockquote_margin_bottom", 8.0))
        )

    def _begin_page_with(self, para: Any) -> None:
        """Start a new page at *para*, keeping its top margin like the PDF does.

        CSS keeps a block's margin-top after a forced break. Word 2013+ layout
        drops space-before at the top of a page (LibreOffice follows suit), so
        the margin is carried by an empty exact-height line that holds the page
        break itself, and the paragraph's own space-before becomes zero.
        """
        previous = para._p.getprevious()
        for candidate in (para._p, previous):
            pPr = candidate.find(qn("w:pPr")) if candidate is not None else None
            if pPr is not None and pPr.find(qn("w:pageBreakBefore")) is not None:
                return  # already starts a page (marker and theme rule can both ask)
        before = _effective_spacing(para, "before")
        if before <= 0:
            para.paragraph_format.page_break_before = True
            return
        spacer = self.doc.add_paragraph(style="Normal")
        _set_para_mark_size(spacer)
        fmt = spacer.paragraph_format
        fmt.page_break_before = True
        fmt.space_before = Pt(0)
        fmt.space_after = Pt(0)
        fmt.line_spacing = Pt(before)
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        para._p.addprevious(spacer._p)
        para.paragraph_format.space_before = Pt(0)

    def _flush_pending_break(self) -> None:
        """Emit a deferred page break as its own paragraph (no paragraph follows)."""
        if self._page_break_pending:
            self._page_break_pending = False
            self.doc.add_page_break()

    def _body_blocks(self) -> list[Any]:
        return [el for el in self.doc.element.body if el.tag != qn("w:sectPr")]

    def _block_count(self) -> int:
        return len(self._body_blocks())

    def _keep_blocks_together(self, start: int) -> None:
        """Chain every block added since *start* so Word keeps them on one page.

        Mirrors the PDF's ``break-inside: avoid`` container: each paragraph (and
        each table row) except the very last is kept with the next one.
        """
        blocks = self._body_blocks()[start:]
        if not blocks:
            return
        last = blocks[-1]
        for el in blocks:
            if el.tag == qn("w:p"):
                if el is not last:
                    self._set_keep_next(el)
            elif el.tag == qn("w:tbl"):
                rows = el.findall(qn("w:tr"))
                for idx, row in enumerate(rows):
                    if el is last and idx == len(rows) - 1:
                        continue
                    for para in row.iter(qn("w:p")):
                        self._set_keep_next(para)

    @staticmethod
    def _set_keep_next(p_el: Any) -> None:
        pPr = p_el.get_or_add_pPr()
        if pPr.find(qn("w:keepNext")) is None:
            keep = OxmlElement("w:keepNext")
            # keepNext follows pStyle in the schema sequence.
            style = pPr.find(qn("w:pStyle"))
            if style is not None:
                style.addnext(keep)
            else:
                pPr.insert(0, keep)

    def _last_body_paragraph(self) -> Any | None:
        """The paragraph that directly precedes the insertion point, if any."""
        from docx.text.paragraph import Paragraph

        body = self.doc.element.body
        blocks = [el for el in body if el.tag != qn("w:sectPr")]
        if blocks and blocks[-1].tag == qn("w:p"):
            para = Paragraph(blocks[-1], self.doc._body)
            if para.text.strip() and para.style.name == "Normal":
                return para
        return None

    def _start_field_box(self, attrs: dict[str, str | None]) -> None:
        """Open a full-width bordered paragraph standing in for an input.

        The PDF draws every text input as a bordered, shaded box that fills the
        text column (``padding: 4pt 6pt; border: 1pt; margin: 2pt 0 8pt``), so
        a fill-in underline in Word would make form pages physically shorter.
        This reproduces that box with paragraph borders and an exact line
        height so both formats consume the same vertical space.
        """
        try:
            content_pt = float(attrs.get("data-h") or _dim("line"))
        except ValueError:
            content_pt = _dim("line")
        label = self._last_body_paragraph()
        self._new_para("Normal")
        para = self._paragraph
        fmt = para.paragraph_format
        fmt.space_before = Pt(_dim("margin_top"))
        # The PDF input lives inside its paragraph, so that paragraph's bottom
        # margin falls after the box rather than between label and box.
        # The box margin lives inside the PDF's line box and never collapses
        # with neighbours; the enclosing paragraph's own bottom margin does.
        # A filled PDF input sits on its text; an empty one on the baseline with the
        # line's descent below it, which grows with the body font. The base is the
        # filled line (margin less the descent at the reference size).
        base_after = _dim("margin_bottom") - _RELIEF_PER_BODY_PT * _REF_BODY_FONT_PT
        fixed_after = base_after + (0.0 if attrs.get("data-filled") else _dim("relief"))
        fmt.space_after = Pt(fixed_after + float(self._theme.get("para_space_after", 0)))
        self._fixed_margins[para._p] = (_dim("margin_top"), fixed_after)
        if label is not None:
            # Never strand a label from its input across a page break.
            label.paragraph_format.keep_with_next = True
        if attrs.get("data-style") == "line":
            self._style_signature_line(para)
            return
        metrics = _field_metrics(self._theme)
        _style_field_box_paragraph(
            para,
            content_pt,
            metrics,
            self._text_width_emu() / 12700,
            arrow=bool(attrs.get("data-arrow")),
        )

    def _style_inline_run(
        self,
        run: Any,
        *,
        bold: bool = False,
        italic: bool = False,
        code: bool = False,
        sup: bool = False,
        sub: bool = False,
        strike: bool = False,
    ) -> None:
        """Apply inline formatting + theme colours to a text run."""
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
        if sup:
            run.font.superscript = True
        if sub:
            run.font.subscript = True
        if strike:
            run.font.strike = True

    def _write_text(
        self,
        paragraph: Any,
        text: str,
        *,
        bold: bool = False,
        italic: bool = False,
        code: bool = False,
        sup: bool = False,
        sub: bool = False,
        strike: bool = False,
    ) -> None:
        """Write *text* to *paragraph*, handling ``[[field]]`` markers when
        field_type is set, and converting bare ``\\n`` to Word line breaks.
        """
        if not text:
            return

        fmt = dict(bold=bold, italic=italic, code=code, sup=sup, sub=sub, strike=strike)

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
                                self._style_inline_run(paragraph.add_run(line), **fmt)
                else:
                    # Field marker. [[?cb:name]] / [[?dd:name|opts]] are the
                    # internal markers the dotx ?[...] conversion emits.
                    if part.startswith("?cb:"):
                        _insert_checkbox_form_field(paragraph, part[4:])
                    elif part.startswith("?dd:"):
                        dd_name, *dd_opts = part[4:].split("|")
                        _insert_dropdown_form_field(paragraph, dd_name, dd_opts)
                    elif self._field_type == "merge":
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
                    self._style_inline_run(paragraph.add_run(line), **fmt)

    def _add_text(self, text: str) -> None:
        if not text:
            return
        if self._last_was_br:
            text = text.lstrip()
            self._last_was_br = False
        if self._current_href is not None:
            self._link_text_buf += text
            return
        if self._paragraph is None and not text.strip():
            return
        # HTML formatting whitespace between <li> and its <p> (loose lists)
        # must not become a line break at the start of the bullet paragraph.
        if self._li_fresh and not text.strip() and not self._current_para().runs:
            return
        self._write_text(
            self._current_para(),
            text,
            bold=self._bold,
            italic=self._italic,
            code=self._in_code,
            sup=self._sup,
            sub=self._sub,
            strike=self._strike,
        )

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag_stack.append(tag)
        tag = tag.lower()

        # A deferred page break rides on the next heading/paragraph; anything
        # else (lists, tables, rules, code) gets an explicit break paragraph.
        if self._page_break_pending and tag not in (
            "h1",
            "h2",
            "h3",
            "h4",
            "p",
            "div",
            "strong",
            "hr",
        ):
            if not (tag == "em" or tag == "span" or tag == "br"):
                self._flush_pending_break()

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
            if self._paragraph is not None:
                if word_align is not None:
                    self._paragraph.alignment = word_align
                # Keep the heading on the same page as the content that follows
                # (mirrors the PDF builder's keep-heading-with-next behaviour so
                # headings don't strand at a page bottom in one format only).
                self._paragraph.paragraph_format.keep_with_next = True
                # Forced page break before this heading level (mirrors the PDF
                # theme's `.report-body h1 { page-break-before: always }`).
                # Skipped for the FIRST H1 of the body (even after a letterhead
                # include — the PDF suppresses it via h1:first-of-type) and for
                # the first content element of any level (a forced break at the
                # top of a page collapses in CSS, so Word must not add one).
                first_h1 = tag == "h1" and not self._seen_h1
                if tag == "h1":
                    self._seen_h1 = True
                if (
                    self._theme.get(f"page_break_before_{tag}")
                    and not first_h1
                    and (len(self.doc.element.body) - self._body_baseline > 1)
                ):
                    self._begin_page_with(self._paragraph)
                # Headings carry id attrs (toc extension) — bookmark them so
                # [TOC] and internal #links can jump to them like in the PDF.
                heading_id = dict(attrs).get("id")
                if heading_id:
                    self._add_bookmark(self._paragraph, heading_id)
            self._apply_section_bar_start(tag)

        elif tag == "p":
            if self._li_depth and self._li_fresh and self._paragraph is not None:
                # Loose list (<li><p>…</p></li>): keep the bullet/number
                # paragraph the <li> just created.
                self._li_fresh = False
            elif self._li_depth and not self._in_blockquote:
                # Later paragraphs of the same list item — indented
                # continuation text under the bullet.
                self._new_para("Normal")
                depth = max(len(self._list_stack), 1)
                self._paragraph.paragraph_format.left_indent = Pt(18 * depth)
            else:
                self._new_para("Normal")
            inline_align = self._parse_text_align(attrs)
            word_align = self._effective_alignment(inline_align)
            if word_align is not None and self._paragraph is not None:
                self._paragraph.alignment = word_align
            if self._in_blockquote and self._paragraph is not None:
                self._apply_box_model(self._paragraph, "blockquote")
                self._bq_paras.append(self._paragraph)

        elif tag == "div":
            self._alignment_stack.append(self._parse_text_align(attrs))
            classes = (dict(attrs).get("class") or "").split()
            # Both the explicit <!-- pagebreak --> marker and the APPENDIX
            # auto-break marker (shared with the PDF builder) emit a real Word
            # page break so the two formats break at the same points.
            if "md-doc-page-break" in classes or "appendix-template-break" in classes:
                # Defer: a break on the *next* paragraph keeps that paragraph's
                # top margin, which an empty break paragraph would swallow.
                self._flush_pending_break()
                self._page_break_pending = True
            if "docx-field" in classes:
                self._start_field_box(dict(attrs))
            if "docx-caption" in classes:
                self._start_signature_caption()
            self._div_stack.append(self._block_count() if "keep-with-next" in classes else None)

        elif tag == "a":
            self._current_href = dict(attrs).get("href") or ""
            self._link_text_buf = ""

        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._list_counters.append(0)
            num_id = None
            if tag == "ol":
                numbering = self.doc.part.numbering_part.element
                style_num = self.doc.styles["List Number"].element.pPr.numPr.numId.val
                base_num = next(
                    n
                    for n in numbering.findall(qn("w:num"))
                    if int(n.get(qn("w:numId"))) == style_num
                )
                num_id = max(int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))) + 1
                number = OxmlElement("w:num")
                number.set(qn("w:numId"), str(num_id))
                abstract = OxmlElement("w:abstractNumId")
                abstract.set(qn("w:val"), base_num.find(qn("w:abstractNumId")).get(qn("w:val")))
                number.append(abstract)
                override = OxmlElement("w:lvlOverride")
                override.set(qn("w:ilvl"), "0")
                start = OxmlElement("w:startOverride")
                try:
                    first = int(dict(attrs).get("start") or 1)
                except ValueError:
                    first = 1
                start.set(qn("w:val"), str(first))
                override.append(start)
                number.append(override)
                numbering.append(number)
            self._list_num_ids.append(num_id)

        elif tag == "li":
            if self._list_stack:
                kind = self._list_stack[-1]
                if kind == "ul":
                    self._paragraph = self.doc.add_paragraph(style="List Bullet")
                else:
                    self._list_counters[-1] += 1
                    self._paragraph = self.doc.add_paragraph(style="List Number")
                    num_pr = self._paragraph._p.get_or_add_pPr().get_or_add_numPr()
                    num_pr.get_or_add_ilvl().val = 0
                    num_pr.get_or_add_numId().val = self._list_num_ids[-1]
            else:
                self._new_para("List Bullet")
            self._li_depth += 1
            self._li_fresh = True
            # Indent nested list items so depth is visible (the base list styles
            # only indent one level, matching CSS nested-list indentation).
            depth = max(len(self._list_stack), 1)
            if depth > 1 and self._paragraph is not None:
                self._paragraph.paragraph_format.left_indent = Pt(18 * depth)
            # Footnote definitions carry id="fn:N" — bookmark them so the
            # in-text reference links can jump here.
            li_id = dict(attrs).get("id")
            if li_id and self._paragraph is not None:
                self._add_bookmark(self._paragraph, li_id)

        elif tag == "dt":
            # Definition-list term — a bold Normal paragraph.
            self._new_para("Normal")
            self._bold = True

        elif tag == "dd":
            # Definition-list description — indented Normal paragraph.
            self._new_para("Normal")
            if self._paragraph is not None:
                self._paragraph.paragraph_format.left_indent = Pt(18)

        elif tag == "pre":
            self._in_pre = True
            self._pre_text = ""

        elif tag == "code":
            if not self._in_pre:
                self._in_code = True

        elif tag == "blockquote":
            self._in_blockquote = True
            self._bq_paras = []
            # Blockquote content is italic by default (CSS font-style: italic)
            self._italic = True

        elif tag in ("strong", "b"):
            self._bold = True

        elif tag in ("em", "i"):
            self._italic = True

        elif tag == "sup":
            self._sup = True
            # Footnote references carry id="fnref:N" — bookmark them so the
            # ↩ back-reference in the footnote list can jump back.
            sup_id = dict(attrs).get("id")
            if sup_id and self._paragraph is not None:
                self._add_bookmark(self._paragraph, sup_id)

        elif tag == "sub":
            self._sub = True

        elif tag in ("del", "s", "strike"):
            self._strike = True

        elif tag == "br":
            run = self._current_para().add_run()
            run._r.append(OxmlElement("w:br"))
            self._last_was_br = True

        elif tag == "img":
            src = dict(attrs).get("src") or ""
            if src.startswith("math://"):
                self._insert_math(self._current_para(), src)
            else:
                self._embed_image(dict(attrs))

        elif tag == "hr":
            self._add_rule()

        elif tag == "table":
            classes = (dict(attrs).get("class") or "").split()
            self._table_form_kind = next(
                (c for c in classes if c in ("field-row", "field-box", "flex-row")), None
            )
            try:
                self._table_gap = float(dict(attrs).get("data-gap") or 0.0)
            except ValueError:
                self._table_gap = 0.0
            self._table_pdf_html = dict(attrs).get("data-pdf")
            self._in_table = True
            self._table_style = _parse_inline_style(dict(attrs).get("style"))
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
            # Markdown column alignment (:--:, --:) arrives as an inline
            # style="text-align: …" on the cell — capture it for _flush_table.
            self._current_cell_align = self._parse_text_align(attrs)
            self._current_cell_style = _parse_inline_style(dict(attrs).get("style"))
            if dict(attrs).get("colspan"):
                self._current_cell_style["colspan"] = str(dict(attrs)["colspan"])

    def handle_endtag(self, tag: str) -> None:
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        tag = tag.lower()

        # Inside a cell, collect closing inline tags as raw HTML
        if self._in_cell and tag not in ("th", "td"):
            self._current_cell_html += f"</{tag}>"
            return

        if tag in ("h1", "h2", "h3", "h4") and self._paragraph is not None:
            self._apply_section_bar_runs()

        if (
            tag == "h1"
            and self._paragraph is not None
            and self._section_bar_active_tag is None  # section bar replaces the default rule
        ):
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
            self._section_bar_active_tag = None
            self._paragraph = None

        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
                self._list_num_ids.pop()
            if self._list_counters:
                self._list_counters.pop()
            self._paragraph = None

        elif tag == "li":
            self._li_depth = max(0, self._li_depth - 1)
            self._li_fresh = False
            self._paragraph = None

        elif tag == "dt":
            self._bold = False
            self._paragraph = None

        elif tag == "dd":
            self._paragraph = None

        elif tag == "pre":
            self._in_pre = False
            para = self.doc.add_paragraph(style="Normal")
            pre_size = self._theme.get("font_size_pre", 9.0)
            pre_font = self._theme.get("font_code", "Courier New")
            self._apply_box_model(para, "pre")
            pre_line = self._theme.get("pre_line_height")
            if pre_line:
                # Prefer the pitch WeasyPrint actually produces (monospace metrics
                # enlarge the line box); fall back to font-size x line-height.
                measured = css_code_line_pitch(self._layout_css, self._text_width_emu() / 12700)
                para.paragraph_format.line_spacing = Pt(measured or pre_size * float(pre_line))
                para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
            # Keep the whole code block on one page (mirrors the PDF theme's
            # `pre { page-break-inside: avoid }`).
            para.paragraph_format.keep_together = True
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
            self._finish_blockquote()

        elif tag == "div":
            if self._alignment_stack:
                self._alignment_stack.pop()
            self._finish_signature_caption()
            self._paragraph = None
            if self._div_stack:
                keep_from = self._div_stack.pop()
                if keep_from is not None:
                    self._keep_blocks_together(keep_from)

        elif tag == "a":
            if self._link_text_buf and self._paragraph is not None:
                if self._current_href:
                    _insert_hyperlink(
                        self._current_para(),
                        self._link_text_buf,
                        self._current_href,
                        superscript=self._sup,
                    )
                else:
                    self._write_text(self._current_para(), self._link_text_buf)
            self._current_href = None
            self._link_text_buf = ""

        elif tag in ("strong", "b"):
            self._bold = False

        elif tag in ("em", "i"):
            self._italic = False

        elif tag == "sup":
            self._sup = False

        elif tag == "sub":
            self._sub = False

        elif tag in ("del", "s", "strike"):
            self._strike = False

        elif tag in ("th", "td"):
            if self._in_table:
                self._current_row.append(
                    (
                        self._in_th,
                        self._current_cell_html,
                        self._current_cell_align,
                        self._current_cell_style,
                    )
                )
            self._in_cell = False

        elif tag == "tr":
            if self._in_table:
                self._table_rows.append(self._current_row)

        elif tag == "table":
            self._in_table = False
            self._flush_table()

    def _text_width_emu(self) -> int:
        section = self.doc.sections[0]
        return int(section.page_width - section.left_margin - section.right_margin)

    def _insert_math(self, paragraph: Any, src: str) -> None:
        if not src.startswith("math://"):
            return
        from copy import deepcopy

        equation = deepcopy(self._math_equations[int(src[7:])])
        paragraph._p.append(equation)
        # Fractions and display equations can exceed the fixed body line box.
        paragraph.paragraph_format.line_spacing = 1.0

    def _embed_image(self, attrs: dict[str, str | None], paragraph: Any = None) -> None:
        """Embed an <img> as a picture: a mermaid:// reference or a file asset."""
        src = attrs.get("src") or ""
        text_width = self._text_width_emu()

        stream: Any = None
        native_w_emu: int | None = None
        m = _MERMAID_IMG_RE.fullmatch(src)
        if m:
            idx = int(m.group(1))
            if idx >= len(self._mermaid_images):
                return
            png, w_px, _h_px = self._mermaid_images[idx]
            stream = BytesIO(png)
            native_w_emu = (
                text_width
                if attrs.get("width") == "100%"
                else int(attrs.get("width") or w_px) * _EMU_PER_PX
            )
        else:
            path = _resolve_asset(src, self._doc_path, self._repo_root)
            if path is None:
                # Unresolved image — fall back to alt text so nothing is silently lost.
                alt = attrs.get("alt")
                if alt:
                    self._write_text(
                        paragraph if paragraph is not None else self._current_para(), str(alt)
                    )
                logger.warning("docx: could not resolve image %r — skipped.", src)
                return
            stream = str(path)
            try:
                from PIL import Image

                with Image.open(path) as im:
                    native_w_emu = int(im.width * _EMU_PER_PX)
            except Exception:
                native_w_emu = None

        width = text_width if native_w_emu is None else min(native_w_emu, text_width)

        para = paragraph if paragraph is not None else self._current_para()
        if paragraph is None:
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            # Reuse the surrounding Markdown paragraph; an extra empty
            # paragraph before the picture shifts Word away from PDF layout.
        # Inline pictures must be allowed to expand the line box.
        para.paragraph_format.line_spacing = 1.0
        run = para.add_run()
        try:
            run.add_picture(stream, width=Emu(width))
        except Exception as exc:
            logger.warning("docx: failed to embed image %r: %s", src, exc)
        self._paragraph = None

    def handle_data(self, data: str) -> None:
        if self._in_pre:
            self._pre_text += data
            return
        if self._in_table:
            self._current_cell_html += data
            return
        # HTML soft whitespace wraps naturally; only <br> creates a hard break.
        self._add_text(re.sub(r"[ \t\r\n\f]+", " ", data))

    def handle_comment(self, data: str) -> None:
        if self._in_table:
            return
        stripped = data.strip()
        if stripped.lower().startswith("col-widths:"):
            raw = stripped[len("col-widths:") :].strip()
            try:
                widths = [float(v.strip()) for v in raw.split(",") if v.strip()]
                if widths:
                    self._next_table_col_widths = widths
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def _add_table_spacer_if_needed(self) -> None:
        """Insert a tiny paragraph when the previous body block is a table.

        OOXML treats consecutive ``w:tbl`` elements as ONE table — Word
        visually merges them no matter how they were authored. A ``w:p``
        between them keeps the tables distinct; sized to mirror the PDF's
        ``table + table { margin-top: 10pt }`` gap (2pt line + 8pt after).
        """
        last_block = None
        for child in reversed(list(self.doc.element.body)):
            if child.tag == qn("w:sectPr"):
                continue
            last_block = child
            break
        if last_block is None or not last_block.tag.endswith("}tbl"):
            return

        spacer = self.doc.add_paragraph()
        fmt = spacer.paragraph_format
        fmt.space_before = Pt(0)
        fmt.space_after = Pt(8)
        # The body style's line height is exact, so the paragraph mark's font size
        # alone would not shrink the line: set the 2pt height explicitly.
        fmt.line_spacing = Pt(2)
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pPr = spacer._p.get_or_add_pPr()
        rPr = OxmlElement("w:rPr")
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), "4")  # half-points: 2pt
        rPr.append(sz)
        pPr.append(rPr)

    def _render_segmented_cell(
        self,
        cell: Any,
        segments: list[tuple[str, str]],
        *,
        width_pt: float,
        size: float | None,
        font_body: str | None,
    ) -> None:
        """A cell holding labels and input boxes: one paragraph per piece.

        Labels take the theme's label style; each input is the same bordered,
        shaded box the body uses (``_style_field_box_paragraph``).
        """
        theme = self._theme
        metrics = _field_metrics(theme)
        label_style = theme.get("form_label")
        label_gap = float((label_style or {}).get("gap", 0.0))
        body_pt = float(size or theme.get("font_size_body", 10.0))
        first = True
        for kind, piece in segments:
            para = cell.paragraphs[0] if first else cell.add_paragraph()
            first = False
            fmt = para.paragraph_format
            fmt.space_before = Pt(0)
            fmt.space_after = Pt(0)
            fmt.alignment = WD_ALIGN_PARAGRAPH.LEFT
            if kind == "text":
                _render_cell_html(
                    para,
                    piece.strip(),
                    theme,
                    self._write_text,
                    insert_math=self._insert_math,
                    insert_image=self._embed_image,
                    label_style=label_style,
                )
                fmt.line_spacing = Pt(body_pt * float(theme.get("line_height_body", 1.65)))
                fmt.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
                for run in para.runs:
                    if font_body and not run.font.name:
                        run.font.name = font_body
                    if not run.font.size and size:
                        run.font.size = Pt(size)
                fmt.space_after = Pt(label_gap)
                fmt.keep_with_next = True
            else:
                attrs, text = _parse_box_segment(piece)
                content = float(attrs.get("h") or _dim("line"))
                _style_field_box_paragraph(
                    para, content, metrics, width_pt, arrow=bool(attrs.get("arrow"))
                )
                run = para.add_run(text)
                run.font.size = Pt(body_pt)
                if font_body:
                    run.font.name = font_body

    def _form_colors(self) -> tuple[str, str, str]:
        """Label / outer-rule / inner-rule colours of the form grids (same as the PDF's)."""
        cached = self.__dict__.get("_form_colors_cache")
        if cached is None:
            from ..mermaid import extract_theme_from_css
            from .pdf import form_rule_colors

            primary = None
            path = self._layout_css
            if path is not None and path.is_file():
                try:
                    primary = extract_theme_from_css(path.read_text(encoding="utf-8")).get(
                        "primary"
                    )
                except Exception:  # noqa: BLE001 - colours fall back to the neutral slate
                    primary = None
            cached = self.__dict__["_form_colors_cache"] = form_rule_colors(primary)
        return cached  # type: ignore[no-any-return]

    @staticmethod
    def _rule_fill_lines(para: Any, width_pt: float, color: str) -> None:
        """Replace ``____`` stand-ins with a full-width write-in rule (a tab leader).

        The PDF draws bare ``?[row]`` inputs as a 1pt rule in the theme colour.
        """
        from docx.enum.text import WD_TAB_LEADER

        for run in para.runs:
            if run.text and set(run.text) <= {"_"}:
                run.text = ""
                run.add_tab()
                r, g, b = _hex_to_rgb(color)
                run.font.color.rgb = RGBColor(r, g, b)
                para.paragraph_format.tab_stops.add_tab_stop(
                    Pt(width_pt), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.LINES
                )
                break

    @staticmethod
    def _blank_fill_lines(para: Any) -> None:
        """The PDF's cell inputs are blank until filled: drop the ``____`` stand-ins."""
        for run in para.runs:
            if run.text and set(run.text) <= {"_"}:
                run.text = ""

    def _style_field_box_cell(self, para: Any, size: float, label_color: str) -> None:
        """Match the PDF's field-box cell text: small-caps-style labels, smaller hints,
        and no fill-in underscores (the PDF cell is blank until filled)."""
        r, g, b = _hex_to_rgb(label_color)
        for run in para.runs:
            if run.bold:
                run.text = run.text.upper()
                run.font.color.rgb = RGBColor(r, g, b)
                if size:
                    run.font.size = Pt(size * 0.85)
                rPr = run._r.get_or_add_rPr()
                spacing = OxmlElement("w:spacing")
                spacing.set(qn("w:val"), str(int(size * 0.04 * 20)))
                rPr.append(spacing)
            elif run.italic and size:
                run.font.size = Pt(size * 0.8)

    def _flush_table(self) -> None:
        rows = self._table_rows
        if not rows:
            return
        max_cols = max(sum(_cell_colspan(c[3]) for c in r) for r in rows)
        if max_cols == 0:
            return

        # An inline ``border: none`` marks a layout table (side-by-side form
        # fields); it must not pick up the report table's rules and shading.
        border_style = self._table_style.get("border", "").lower()
        form_kind = self._table_form_kind or (
            "field-row"
            if border_style in ("none", "0") or border_style.startswith("none")
            else None
        )
        self._add_table_spacer_if_needed()
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
        if not weights:
            declared = [_style_width_percent(cell[3]) for cell in rows[0]]
            if len(declared) == max_cols and all(w is not None for w in declared):
                weights = [float(w) for w in declared if w is not None]
        if not weights and form_kind in (None, "form-grid"):
            # Size columns to their content exactly as the PDF's CSS layout does.
            weights = css_column_weights(
                [[(cell[0], cell[1]) for cell in row] for row in rows],
                self._layout_css,
                text_width_twips / 20,
            )
        self._active_table_col_widths = None
        if weights and len(weights) == max_cols and sum(weights) > 0:
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
        if form_kind:
            # PDF: field-box cells keep the theme's td padding; borderless rows
            # carry their own inline padding.
            if form_kind == "flex-row":
                tb_pt = lr_pt = 0.0
            elif form_kind != "field-box":
                tb_pt, lr_pt = 2.0, 8.0
        tblCellMar = OxmlElement("w:tblCellMar")
        for side_name, pt_val in (
            ("top", tb_pt),
            ("left", lr_pt),
            ("bottom", tb_pt),
            ("right", lr_pt),
        ):
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

        if form_kind:
            header_bg = row_alt_bg = None
            ruled = form_kind == "field-box"
            form_label_color, form_rule, form_soft = self._form_colors()
            borders = OxmlElement("w:tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                edge = OxmlElement(f"w:{side}")
                edge.set(qn("w:val"), "single" if ruled else "nil")
                # 1pt outer rule, 0.5pt inner rules in the theme's tints
                # (PDF: table.field-box border / td border)
                inner = side.startswith("inside")
                edge.set(qn("w:sz"), "4" if inner else "8")
                edge.set(qn("w:color"), (form_soft if inner else form_rule).lstrip("#"))
                borders.append(edge)
            tblPr.append(borders)
        n_rows = len(rows)
        # Row heights the PDF gives this form table, laid out with the real theme
        # CSS: they depend on the theme (input display, padding, fonts), so Word
        # rows take them as minimums rather than relying on fitted constants.
        pdf_heights: list[float] | None = None
        if form_kind in ("field-box", "field-row") and self._table_pdf_html:
            pdf_heights = css_row_heights(
                self._table_pdf_html, self._layout_css, self._text_width_emu() / 12700
            )
            if pdf_heights is not None and len(pdf_heights) != n_rows:
                pdf_heights = None
        header_rows = 1 if all(cell[0] for cell in rows[0]) else 0

        for r_idx, row_cells in enumerate(rows):
            is_last_row = r_idx == n_rows - 1
            # Question/answer rows (no bold label in any cell) centre vertically,
            # as in the PDF; labelled rows keep the label at the top of the cell.
            qa_row = form_kind == "field-box" and not any(
                "<strong" in c[1] or "<b>" in c[1] for c in row_cells
            )
            # Keep each row on one page (mirrors the PDF theme's
            # `tr { page-break-inside: avoid }`).
            trPr = table.rows[r_idx]._tr.get_or_add_trPr()
            if trPr.find(qn("w:cantSplit")) is None:
                trPr.append(OxmlElement("w:cantSplit"))
            if pdf_heights is not None:
                tr_height = OxmlElement("w:trHeight")
                tr_height.set(qn("w:val"), str(int(pdf_heights[r_idx] * 20)))
                tr_height.set(qn("w:hRule"), "atLeast")
                trPr.append(tr_height)
            if r_idx == 0 and all(cell[0] for cell in row_cells):
                trPr.append(OxmlElement("w:tblHeader"))
            c_idx = 0
            for is_header, cell_html, cell_align, cell_style in row_cells:
                if c_idx >= max_cols:
                    break
                span = min(_cell_colspan(cell_style), max_cols - c_idx)
                start, c_idx = c_idx, c_idx + span
                cell = table.cell(r_idx, start)
                if span > 1:
                    cell = cell.merge(table.cell(r_idx, start + span - 1))
                cell.text = ""
                # Explicitly set cell width so fixed-layout tables honour the
                # grid widths rather than falling back to Word's own heuristic.
                tc = cell._tc
                tcPr = tc.get_or_add_tcPr()
                for old in tcPr.findall(qn("w:tcW")):
                    tcPr.remove(old)
                tcW_el = OxmlElement("w:tcW")
                tcW_el.set(qn("w:w"), str(sum(col_widths_twips[start : start + span])))
                tcW_el.set(qn("w:type"), "dxa")
                tcPr.append(tcW_el)
                padding = _style_padding_pt(cell_style)
                if form_kind == "flex-row" and start + span < max_cols and self._table_gap:
                    padding = {"top": 0.0, "left": 0.0, "bottom": 0.0, "right": self._table_gap}
                if padding:
                    _set_cell_margins(cell, padding)
                segments = [] if is_header else _split_field_segments(cell_html)
                if any(kind == "box" for kind, _ in segments):
                    cell_pt = sum(col_widths_twips[start : start + span]) / 20
                    if padding:
                        cell_pt -= padding.get("left", 0.0) + padding.get("right", 0.0)
                    self._render_segmented_cell(
                        cell,
                        segments,
                        width_pt=cell_pt - (lr_pt * 2 if not padding else 0.0),
                        size=body_font_size,
                        font_body=font_body,
                    )
                    continue
                para = cell.paragraphs[0]
                # Zero paragraph spacing so cell padding alone controls whitespace
                para.paragraph_format.space_before = Pt(0)
                para.paragraph_format.space_after = Pt(0)
                if is_header:
                    para.paragraph_format.keep_with_next = True

                _render_cell_html(
                    para,
                    cell_html.strip(),
                    self._theme,
                    self._write_text,
                    bold_override=is_header,
                    insert_math=self._insert_math,
                    insert_image=self._embed_image,
                    caption_style=(
                        {
                            "size": (body_font_size or 9.5) * 0.7,
                            "color": self._form_colors()[0],
                        }
                        if form_kind == "field-row"
                        else None
                    ),
                    input_pt=_dim("cell_input") if form_kind == "field-box" else _dim("cell_plain"),
                    bare_input_pt=(
                        _dim("cell_bare") if form_kind == "field-box" else _dim("cell_plain_bare")
                    ),
                )

                # Apply alignment — the cell's own text-align (markdown column
                # alignment, :--:/--:) wins; body cells otherwise resolve
                # through the div > body_text_align cascade (Word table cells
                # don't inherit document-level alignment the way body text does).
                word_align = self._effective_alignment(cell_align)
                if cell_align is None and word_align == WD_ALIGN_PARAGRAPH.JUSTIFY:
                    # Page-level justify never reaches into cells: wrapped text
                    # in a narrow column stretches into rivers of whitespace.
                    # A cell/column's own text-align: justify still applies.
                    word_align = WD_ALIGN_PARAGRAPH.LEFT
                if cell_align is None and is_header:
                    word_align = None  # headers keep Word's default unless explicit
                if word_align is None and self._theme.get("text_align_body") == "justify":
                    # A theme with body { text-align: justify } justifies the
                    # Normal style — cells would inherit it, so pin them left.
                    word_align = WD_ALIGN_PARAGRAPH.LEFT
                if word_align is not None:
                    para.alignment = word_align

                # Apply body font explicitly (Word table cells don't always inherit Normal)
                if font_body:
                    for run in para.runs:
                        if run.font.name is None or run.font.name not in (font_code, "Courier New"):
                            run.font.name = font_body

                # Apply font sizes
                size = header_font_size if is_header else body_font_size
                if size:
                    cell_line_height = (
                        1.3
                        if form_kind == "field-box"
                        else self._theme.get("line_height_body", 1.65)
                    )
                    para.paragraph_format.line_spacing = Pt(size * cell_line_height)
                    # Cell text uses its own size; pictures/equations may expand
                    # the minimum line box rather than getting clipped.
                    para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
                    for run in para.runs:
                        run.font.size = Pt(size)
                    for strut, strut_size in para.__dict__.get("_struts", []):
                        strut.font.size = Pt(strut_size)
                    if form_kind and any(mark in para.text for mark in _CHOICE_MARKS):
                        # A checkbox/radio makes the PDF line taller than its text.
                        para.paragraph_format.line_spacing = Pt(
                            max(size * cell_line_height, _dim("cell_choice"))
                        )

                if self._form_document and form_kind not in ("field-row", "flex-row"):
                    self._blank_fill_lines(para)
                if form_kind == "field-row":
                    rule_pt = sum(col_widths_twips[start : start + span]) / 20 - 8.0
                    self._rule_fill_lines(para, rule_pt, self._form_colors()[0])
                if form_kind == "field-box" and not is_header:
                    self._style_field_box_cell(para, size or 0.0, form_label_color)
                    if qa_row:
                        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

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
                    # Alternating row shading. Markdown tables put the header in a
                    # <thead> and the body in a <tbody>, and CSS tr:nth-child(even)
                    # counts within the tbody: the first body row is unshaded, the
                    # second shaded (verified against the rendered PDF).
                    if row_alt_bg and (r_idx - header_rows) % 2 == 1:
                        set_cell_shading(cell, row_alt_bg)
                    # Bottom border
                    if not form_kind:
                        _set_cell_bottom_border(
                            cell,
                            color=last_border_color if is_last_row else cell_border_color,
                            pt=last_border_size if is_last_row else cell_border_size,
                        )

            # Rows shorter than max_cols still have Word cells that need
            # explicit tcW; without it fixed-layout tables render incorrectly.
            for c_idx in range(c_idx, max_cols):
                cell = table.cell(r_idx, c_idx)
                tc = cell._tc
                tcPr = tc.get_or_add_tcPr()
                for old in tcPr.findall(qn("w:tcW")):
                    tcPr.remove(old)
                tcW_el = OxmlElement("w:tcW")
                tcW_el.set(qn("w:w"), str(col_widths_twips[c_idx]))
                tcW_el.set(qn("w:type"), "dxa")
                tcPr.append(tcW_el)

        self._paragraph = None


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------


# Named page sizes in mm, portrait (w, h) — matches WeasyPrint/CSS @page sizes.
def _setup_page(doc: Document, geometry: dict[str, float] | None = None) -> None:
    """Set page size and margins to match the PDF layout (from theme @page)."""
    g = geometry or _DEFAULT_GEOMETRY
    section = doc.sections[0]
    section.page_width = Mm(g["w"])
    section.page_height = Mm(g["h"])
    section.top_margin = Mm(g["top"])
    section.right_margin = Mm(g["right"])
    section.bottom_margin = Mm(g["bottom"])
    section.left_margin = Mm(g["left"])
    if "header_distance" in g:
        section.header_distance = Mm(g["header_distance"])
    if "footer_distance" in g:
        section.footer_distance = Mm(g["footer_distance"])


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------


_TWIPS_PER_MM = 1440 / 25.4


def _cfg_mm(value: Any, default_mm: float) -> float:
    """Parse a config length (e.g. ``"10mm"``, ``"1cm"``) to mm."""
    if value is None:
        return default_mm
    mm = _length_to_mm(str(value))
    return mm if mm is not None else default_mm


def _set_para_mark_size(paragraph: Any, half_points: int = 2) -> None:
    """Shrink a paragraph's mark so an empty paragraph takes ~no vertical space."""
    pPr = paragraph._p.get_or_add_pPr()
    rPr = pPr.find(qn("w:rPr"))
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        pPr.append(rPr)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(half_points))
    rPr.append(sz)


def _tiny_spacer(doc: Document) -> Any:
    """Add a ~zero-height paragraph (separates consecutive floating tables)."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    _set_para_mark_size(p)
    p.paragraph_format.line_spacing = Pt(1)
    return p


def _add_floating_table(
    doc: Document,
    *,
    width_twips: int,
    height_mm: float,
    fill: str,
    y_spec: str | None = None,
    y_mm: float | None = None,
    x_mm: float | None = None,
    height_rule: str = "exact",
    inline_indent_twips: int | None = None,
) -> Any:
    """Add a 1×1 borderless shaded table band for the cover page.

    By default the band is floated to an absolute page position (used for the
    top bar/stripe so they sit at the physical page edges the way the PDF
    cover's full-bleed elements do, given ``@page cover { margin: 0 }``).
    With *inline_indent_twips* the band stays in the normal flow instead and
    bleeds into the margins via a negative table indent — used where the PDF
    also lays the element out in flow (e.g. the bottom cover bar).
    """
    try:
        table = doc.add_table(rows=1, cols=1)
    except TypeError:  # Header/footer containers require an explicit width.
        table = doc.add_table(rows=1, cols=1, width=Emu(width_twips * 635))
    try:
        table.style = "Table Normal"
    except KeyError:
        table.style = "Normal Table"
    _clear_table_borders(table)

    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)

    if inline_indent_twips is None:
        # Absolute page positioning (w:tblpPr) + allow overlap with other floats.
        tblpPr = OxmlElement("w:tblpPr")
        tblpPr.set(qn("w:horzAnchor"), "page")
        tblpPr.set(qn("w:vertAnchor"), "page")
        if x_mm is None:
            tblpPr.set(qn("w:tblpXSpec"), "left")
        else:
            tblpPr.set(qn("w:tblpX"), str(max(1, round(x_mm * _TWIPS_PER_MM))))
        if y_mm is not None:
            tblpPr.set(qn("w:tblpY"), str(max(1, round(y_mm * _TWIPS_PER_MM))))
        else:
            tblpPr.set(qn("w:tblpYSpec"), y_spec or "top")
        overlap = OxmlElement("w:tblOverlap")
        overlap.set(qn("w:val"), "overlap")
        tblStyle = tblPr.find(qn("w:tblStyle"))
        if tblStyle is not None:
            tblStyle.addnext(tblpPr)
        else:
            tblPr.insert(0, tblpPr)
        tblpPr.addnext(overlap)
    else:
        tblInd = OxmlElement("w:tblInd")
        tblInd.set(qn("w:w"), str(inline_indent_twips))
        tblInd.set(qn("w:type"), "dxa")
        tblPr.append(tblInd)

    # Fixed layout at the exact requested width.
    for old in tblPr.findall(qn("w:tblW")):
        tblPr.remove(old)
    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:w"), str(width_twips))
    tblW.set(qn("w:type"), "dxa")
    tblPr.append(tblW)
    for old in tblPr.findall(qn("w:tblLayout")):
        tblPr.remove(old)
    tblLayout = OxmlElement("w:tblLayout")
    tblLayout.set(qn("w:type"), "fixed")
    tblPr.append(tblLayout)

    # Zero default cell margins so the shading fills the full band.
    tblCellMar = OxmlElement("w:tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        mar = OxmlElement(f"w:{side}")
        mar.set(qn("w:w"), "0")
        mar.set(qn("w:type"), "dxa")
        tblCellMar.append(mar)
    tblPr.append(tblCellMar)

    for old_grid in tbl.findall(qn("w:tblGrid")):
        tbl.remove(old_grid)
    tblGrid = OxmlElement("w:tblGrid")
    gridCol = OxmlElement("w:gridCol")
    gridCol.set(qn("w:w"), str(width_twips))
    tblGrid.append(gridCol)
    tbl.insert(list(tbl).index(tblPr) + 1, tblGrid)

    tr = table.rows[0]._tr
    trPr = tr.get_or_add_trPr()
    trHeight = OxmlElement("w:trHeight")
    trHeight.set(qn("w:val"), str(max(1, int(Mm(height_mm).pt * 20))))
    trHeight.set(qn("w:hRule"), height_rule)
    trPr.append(trHeight)

    cell = table.rows[0].cells[0]
    set_cell_shading(cell, fill)
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:tcW")):
        tcPr.remove(old)
    tcW_el = OxmlElement("w:tcW")
    tcW_el.set(qn("w:w"), str(width_twips))
    tcW_el.set(qn("w:type"), "dxa")
    tcPr.append(tcW_el)
    tcBorders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "none")
        tcBorders.append(b)
    tcPr.append(tcBorders)
    vAlign = OxmlElement("w:vAlign")
    vAlign.set(qn("w:val"), "center")
    tcPr.append(vAlign)
    p0 = cell.paragraphs[0]
    p0.paragraph_format.space_before = Pt(0)
    p0.paragraph_format.space_after = Pt(0)
    _set_para_mark_size(p0)
    p0.paragraph_format.line_spacing = Pt(1)

    return table


def _set_cell_margins_mm(cell: Any, top: float, right: float, bottom: float, left: float) -> None:
    """Set explicit tcMar margins (mm) on a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:tcMar")):
        tcPr.remove(old)
    tcMar = OxmlElement("w:tcMar")
    for side, mm_val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        mar = OxmlElement(f"w:{side}")
        mar.set(qn("w:w"), str(max(0, round(mm_val * _TWIPS_PER_MM))))
        mar.set(qn("w:type"), "dxa")
        tcMar.append(mar)
    tcPr.append(tcMar)


def _anchor_cover_picture(shape: Any, x_mm: float, y_mm: float, z_order: int = 1) -> None:
    """Position a decorative picture against physical page coordinates.

    ``z_order`` is the drawing's ``relativeHeight``: equal values fall back to
    part order, which differs between renderers, so layers are numbered
    explicitly (page background lowest, then bands, then logos).
    """
    inline = shape._inline
    anchor = OxmlElement("wp:anchor")
    for key, value in {
        "distT": "0",
        "distB": "0",
        "distL": "0",
        "distR": "0",
        "simplePos": "0",
        "relativeHeight": str(z_order),
        "behindDoc": "1",
        "locked": "0",
        "layoutInCell": "1",
        "allowOverlap": "1",
    }.items():
        anchor.set(key, value)
    simple = OxmlElement("wp:simplePos")
    simple.set("x", "0")
    simple.set("y", "0")
    anchor.append(simple)
    for axis, position in (("H", int(Mm(x_mm))), ("V", int(Mm(y_mm)))):
        pos = OxmlElement(f"wp:position{axis}")
        pos.set("relativeFrom", "page")
        offset = OxmlElement("wp:posOffset")
        offset.text = str(position)
        pos.append(offset)
        anchor.append(pos)
    anchor.append(inline.find(qn("wp:extent")))
    anchor.append(OxmlElement("wp:wrapNone"))
    for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
        anchor.append(inline.find(qn(tag)))
    inline.getparent().replace(inline, anchor)


def _add_docx_cover_page(
    doc: Document,
    config: dict[str, Any],
    builder: "_DocxBuilder",
    theme: dict[str, Any],
) -> None:
    """Insert a styled cover page for .docx output, then a page break.

    Mirrors the PDF cover design element for element: full-bleed coloured
    bar(s) at the physical page top/bottom, optional accent stripe and logo,
    cover label, title, short divider rule, metadata (author / date) and a
    footer positioned ~14mm from the page bottom — matching the geometry of
    the PDF's ``@page cover { margin: 0 }`` + ``.cover-content`` padding.
    """
    title = config.get("title", "")
    author = config.get("author", "")
    date_str = config.get("date", "")
    label = str(config.get("cover_label", "Report"))
    show_bar = bool(config.get("cover_bar", True))
    bar_pos = str(config.get("cover_bar_position", "top")).lower()
    bar_h = _cfg_mm(config.get("cover_bar_height"), 10.0)
    bar_top_h = _cfg_mm(config.get("cover_bar_top_height"), bar_h)
    bar_bot_h = _cfg_mm(config.get("cover_bar_bottom_height"), bar_h)
    show_stripe = bool(config.get("cover_stripe", False))
    stripe_h = _cfg_mm(config.get("cover_stripe_height"), 120.0)
    stripe_w = _cfg_mm(config.get("cover_stripe_width"), 6.0)
    text_on_bar = bool(config.get("cover_text_on_bar", False))
    show_divider = bool(config.get("cover_divider", True))
    show_footer = bool(config.get("cover_footer", True))
    show_footer_line = bool(config.get("cover_footer_line", True))
    footer_text = config.get("cover_footer_text") or (
        f"{author}  ·  Confidential" if author else ""
    )
    meta_label = str(config.get("cover_meta_label", "Prepared by"))
    meta_author = str(config.get("cover_meta_author", author))

    # Match the PDF cover: bar + title + divider use $primary (color_h1); the
    # label uses the accent (color_h2); meta value is muted grey with a
    # body-coloured bold label.
    primary = (theme.get("color_h1") or theme.get("color_table_header_bg") or "1b4f72").lstrip("#")
    bar_color = primary
    title_color = primary
    accent = (theme.get("color_h2") or theme.get("color_h1") or "2e86c1").lstrip("#")
    label_color = accent
    divider_color = primary  # .cover-divider { border-top: 3pt solid $primary }
    meta_label_color = (theme.get("color_body") or theme.get("color_strong") or "212529").lstrip(
        "#"
    )
    meta_value_color = (theme.get("color_em") or "5d6d7e").lstrip("#")
    if text_on_bar:
        title_color = label_color = divider_color = "ffffff"
        meta_label_color = meta_value_color = "ffffff"
    font_body = theme.get("font_body")
    text_align = str(config.get("cover_text_align", "left")).lower()
    para_align = {
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
    }.get(text_align, WD_ALIGN_PARAGRAPH.LEFT)

    section = doc.sections[0]
    page_w_mm = section.page_width / 36000
    page_h_mm = section.page_height / 36000
    top_margin_mm = section.top_margin / 36000
    text_width_mm = (section.page_width - section.left_margin - section.right_margin) / 36000
    page_twips = round(section.page_width / 635)

    background = str(config.get("cover_background", "white"))
    if background.lower() not in ("white", "#fff", "#ffffff"):
        from PIL import Image

        image = BytesIO()
        Image.new("RGB", (1, 1), background).save(image, format="PNG")
        image.seek(0)
        paragraph = section.first_page_header.paragraphs[0]
        paragraph.paragraph_format.line_spacing = Pt(1)
        picture = paragraph.add_run().add_picture(
            image, width=section.page_width, height=section.page_height
        )
        _anchor_cover_picture(picture, 0, 0, z_order=1)

    has_top_bar = show_bar and bar_pos in ("top", "both")
    has_bottom_bar = show_bar and bar_pos in ("bottom", "both")

    # 1. Full-bleed bars + accent stripe, floated to absolute page positions
    #    (the PDF cover has margin: 0, so its bars touch the physical edges).
    if has_top_bar and not text_on_bar:
        _add_floating_table(
            doc, width_twips=page_twips, height_mm=bar_top_h, fill=bar_color, y_spec="top"
        )
        _tiny_spacer(doc)

    if show_stripe:
        stripe_y = bar_top_h if has_top_bar else 10.0
        _add_floating_table(
            doc,
            width_twips=max(1, round(stripe_w * _TWIPS_PER_MM)),
            height_mm=stripe_h,
            fill=accent,
            y_mm=stripe_y,
        )
        _tiny_spacer(doc)

    bar_logo_val = config.get("cover_bar_logo")
    bar_logo_path = (
        _resolve_asset(str(bar_logo_val), builder._doc_path, builder._repo_root)
        if bar_logo_val
        else None
    )

    # 2. Content container. Normally content flows in the body; with
    #    cover_text_on_bar it sits inside the top bar itself (PDF wraps
    #    .cover-content in .cover-bar-wrapper with the primary background).
    container: Any = doc
    first_space_before_pt = 0.0
    base_indent_l_mm = 28.0 - section.left_margin / 36000
    base_indent_r_mm = 30.0 - section.right_margin / 36000
    avail_mm = text_width_mm - base_indent_l_mm - base_indent_r_mm
    if text_on_bar and has_top_bar:
        wrap_tbl = _add_floating_table(
            doc,
            width_twips=page_twips,
            # Word adds cell padding to the minimum row content height.
            # CSS min-height applies to the whole wrapper in this cover layout.
            height_mm=max(0.1, bar_top_h - 50.0 - 20.0),
            fill=bar_color,
            y_spec="top",
            height_rule="atLeast",
        )
        wrap_cell = wrap_tbl.rows[0].cells[0]
        wrap_cell._tc.get_or_add_tcPr().find(qn("w:vAlign")).set(qn("w:val"), "top")
        # Mirror .cover-content { padding: 50mm 30mm 20mm 28mm; }
        _set_cell_margins_mm(wrap_cell, top=50.0, right=30.0, bottom=20.0, left=28.0)
        container = wrap_cell
        base_indent_l_mm = base_indent_r_mm = 0.0
        avail_mm = page_w_mm - 28.0 - 30.0
        _tiny_spacer(doc)
    else:
        # .cover-content padding-top is 50mm below the top bar; subtract the
        # section top margin since flow content starts there.
        content_top_mm = (bar_top_h if has_top_bar else 0.0) + 50.0
        first_space_before_pt = max(0.0, (content_top_mm - top_margin_mm) * 72.0 / 25.4)

    used_first_cell_para = False

    def _cover_para(space_before: float, space_after: float) -> Any:
        nonlocal used_first_cell_para
        if container is not doc and not used_first_cell_para:
            used_first_cell_para = True
            p = container.paragraphs[0]
        else:
            p = container.add_paragraph()
        p.alignment = para_align
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after = Pt(space_after)
        _set_para_mark_size(p)
        if base_indent_l_mm:
            p.paragraph_format.left_indent = Mm(base_indent_l_mm)
        if base_indent_r_mm:
            p.paragraph_format.right_indent = Mm(base_indent_r_mm)
        return p

    pending_space_before = first_space_before_pt

    # 3. Optional cover logo above the label (PDF: .cover-logo before .cover-label).
    logo_val = config.get("cover_logo")
    logo_path = (
        _resolve_asset(str(logo_val), builder._doc_path, builder._repo_root) if logo_val else None
    )
    if logo_path:
        lp = _cover_para(pending_space_before, 12)
        pending_space_before = 0.0
        # The body style's line height is exact; a logo taller than that would
        # overflow upward out of its line. Let the line grow to the picture.
        lp.paragraph_format.line_spacing = 1.0
        lp.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = lp.add_run()
        try:
            logo_w_emu: int | None = None
            try:
                from PIL import Image

                with Image.open(logo_path) as im:
                    logo_w_emu = int(im.width * _EMU_PER_PX)
            except Exception:
                logo_w_emu = None
            max_w_emu = int(Mm(avail_mm))
            if logo_w_emu:
                run.add_picture(str(logo_path), width=Emu(min(logo_w_emu, max_w_emu)))
            else:
                run.add_picture(str(logo_path))
        except Exception as exc:
            logger.warning("docx cover logo embed failed: %s", exc)

    # 4. Cover label (e.g. "REPORT") — small uppercase accent, tracked out.
    #    PDF: .cover-label { 8.5pt / 700 / letter-spacing 2.5pt / 10mm below }.
    if label:
        lp = _cover_para(pending_space_before, Mm(10).pt)  # 10mm ≈ 28pt below
        pending_space_before = 0.0
        lp.paragraph_format.line_spacing = Pt(8.5 * 1.2)
        run = lp.add_run(label.upper())
        run.bold = True
        run.font.size = Pt(8.5)
        if font_body:
            _apply_font_name(run.font, font_body)
        r, g, b = _hex_to_rgb(label_color)
        run.font.color.rgb = RGBColor(r, g, b)
        # Letter-spacing 2.5pt (val is in twentieths of a point).
        rPr = run._r.get_or_add_rPr()
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:val"), "50")
        rPr.append(spacing)

    # 5. Title — large bold run in $primary using the body font (NOT the
    #    built-in serif "Title" style, which looks nothing like the PDF).
    #    PDF: .cover-title { 24pt / 700 / 8mm below }.
    title_para = _cover_para(pending_space_before, Mm(8).pt)  # 8mm ≈ 23pt below
    pending_space_before = 0.0
    title_para.paragraph_format.line_spacing = Pt(24 * 1.2)
    trun = title_para.add_run(title or "Document")
    trun.bold = True
    trun.font.size = Pt(24)
    if font_body:
        _apply_font_name(trun.font, font_body)
    r, g, b = _hex_to_rgb(title_color)
    trun.font.color.rgb = RGBColor(r, g, b)

    # 6. Short divider rule — 40mm, 3pt, $primary (PDF: .cover-divider).
    #    A bottom-bordered empty paragraph, indented from the far side so the
    #    rule is 40mm wide rather than full-width.
    if show_divider:
        dp = _cover_para(0, Mm(7.5).pt)  # 8mm below
        _set_para_mark_size(dp)
        dp.paragraph_format.line_spacing = Pt(0.1)
        gap_mm = max(0.0, avail_mm - 40.0)
        if para_align == WD_ALIGN_PARAGRAPH.RIGHT:
            dp.paragraph_format.left_indent = Mm(base_indent_l_mm + gap_mm)
        elif para_align == WD_ALIGN_PARAGRAPH.CENTER:
            dp.paragraph_format.left_indent = Mm(base_indent_l_mm + gap_mm / 2)
            dp.paragraph_format.right_indent = Mm(base_indent_r_mm + gap_mm / 2)
        else:
            dp.paragraph_format.right_indent = Mm(base_indent_r_mm + gap_mm)
        pPr = dp._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bot = OxmlElement("w:bottom")
        bot.set(qn("w:val"), "single")
        bot.set(qn("w:sz"), "24")  # 3pt
        bot.set(qn("w:space"), "0")
        bot.set(qn("w:color"), divider_color.upper())
        pBdr.append(bot)
        pPr.append(pBdr)

    # 7. Author / date metadata — bold body-coloured label + muted value, no
    #    colons (matches the PDF's "<strong>Prepared by</strong> {author}").
    def _meta_line(bold_label: str, value: str) -> None:
        mp = _cover_para(0, 0)
        mp.paragraph_format.line_spacing = Pt(10.5 * 1.8)
        lbl = mp.add_run(f"{bold_label} ")
        lbl.bold = True
        lbl.font.size = Pt(10.5)
        if font_body:
            _apply_font_name(lbl.font, font_body)
        lr, lg, lb = _hex_to_rgb(meta_label_color)
        lbl.font.color.rgb = RGBColor(lr, lg, lb)
        val = mp.add_run(value)
        val.font.size = Pt(10.5)
        if font_body:
            _apply_font_name(val.font, font_body)
        vr, vg, vb = _hex_to_rgb(meta_value_color)
        val.font.color.rgb = RGBColor(vr, vg, vb)

    if meta_author:
        _meta_line(meta_label, meta_author)
    if date_str:
        _meta_line("Date", date_str)

    # 8. A page-anchored drawing avoids office clipping/repositioning of
    # floating tables below the body area. Cover text stays editable.
    if has_bottom_bar:
        from PIL import Image

        band = BytesIO()
        Image.new("RGB", (1, 1), f"#{bar_color}").save(band, format="PNG")
        band.seek(0)
        paragraph = section.first_page_footer.paragraphs[0]
        paragraph.paragraph_format.line_spacing = Pt(1)
        shape = paragraph.add_run().add_picture(band, width=Mm(page_w_mm), height=Mm(bar_bot_h))
        _anchor_cover_picture(shape, 0, page_h_mm - bar_bot_h, z_order=2)
        if bar_logo_path:
            try:
                logo_h = _logo_height_mm(bar_logo_path, min(bar_bot_h * 0.7, 8.0))
                logo = paragraph.add_run().add_picture(str(bar_logo_path), height=Mm(logo_h))
                _anchor_cover_picture(
                    logo,
                    page_w_mm - 30 - logo.width / 36000,
                    page_h_mm - bar_bot_h + (bar_bot_h - logo_h) / 2,
                    z_order=3,
                )
            except Exception as exc:
                logger.warning("docx cover bar logo embed failed: %s", exc)

    # 9. Footer (confidentiality notice) — a text frame positioned so its text
    #    sits ~14mm from the physical page bottom, spanning the PDF cover
    #    footer's 28mm→(width−20mm) span, with an optional thin top rule
    #    (PDF: .cover-footer { bottom: 14mm; border-top: 1pt #d5d8dc; 8pt }).
    if show_footer and footer_text:
        fp = doc.add_paragraph()
        fp.alignment = para_align
        pPr = fp._p.get_or_add_pPr()
        framePr = OxmlElement("w:framePr")
        frame_w_mm = max(10.0, page_w_mm - 28.0 - 20.0)
        frame_top_mm = max(0.0, page_h_mm - 14.0 - 9.4)  # ≈ rule + padding + one 8pt line
        band_footer = footer_band_geometry(config, bar_bot_h)
        if band_footer:
            bottom_gap, footer_height = band_footer
            frame_top_mm = page_h_mm - bottom_gap - footer_height
            fp.paragraph_format.space_before = Pt(0)
            fp.paragraph_format.space_after = Pt(0)
            fp.paragraph_format.line_spacing = Pt(8 * 1.65)
        framePr.set(qn("w:w"), str(round(frame_w_mm * _TWIPS_PER_MM)))
        framePr.set(qn("w:h"), "0")
        framePr.set(qn("w:hRule"), "auto")
        framePr.set(qn("w:wrap"), "around")
        framePr.set(qn("w:hAnchor"), "page")
        framePr.set(qn("w:x"), str(round(28.0 * _TWIPS_PER_MM)))
        framePr.set(qn("w:vAnchor"), "page")
        framePr.set(qn("w:y"), str(round(frame_top_mm * _TWIPS_PER_MM)))
        pPr.append(framePr)
        if show_footer_line:
            # Thin top rule above the footer text (PDF: 1pt #d5d8dc, 4mm padding).
            pBdr = OxmlElement("w:pBdr")
            top = OxmlElement("w:top")
            top.set(qn("w:val"), "single")
            top.set(qn("w:sz"), "8")  # 1pt
            top.set(qn("w:space"), "8")  # ~4pt padding above text
            top.set(qn("w:color"), "D5D8DC")
            pBdr.append(top)
            pPr.append(pBdr)
        run = fp.add_run(re.sub(r"\s+", " ", footer_text))
        run.font.size = Pt(8)
        if font_body:
            _apply_font_name(run.font, font_body)
        col = config.get("cover_footer_color") or "#7f8c9a"  # PDF .cover-footer colour
        r, g, b = _hex_to_rgb(str(col))
        run.font.color.rgb = RGBColor(r, g, b)

    # The body starts on a new page; defer the break so the first heading keeps
    # its top margin (see _DocxBuilder._begin_page_with).
    # A framed footer anchors to the paragraph after it; keep that on the cover.
    _tiny_spacer(doc)
    builder._page_break_pending = True


# ---------------------------------------------------------------------------
# .dotx content-type patch
# ---------------------------------------------------------------------------


def _patch_compatibility_mode(path: Path) -> None:
    """Upgrade compatibilityMode from 14 (Word 2010) to 15 (Word 2016+).

    python-docx's built-in template ships with compatibilityMode=14, which
    causes Word to open the file in Compatibility Mode.  Patching to 15 tells
    Word the document is fully modern and suppresses the banner.
    """
    tmp = path.with_suffix(".tmp")
    shutil.move(str(path), str(tmp))
    try:
        with zipfile.ZipFile(tmp, "r") as zin:
            with zipfile.ZipFile(path, "w") as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "word/settings.xml":
                        data = data.replace(
                            b'w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="14"',
                            b'w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"',
                        )
                    zout.writestr(item, data)
    except Exception:
        shutil.move(str(tmp), str(path))
        raise
    finally:
        if tmp.exists():
            tmp.unlink()


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


_STRUCT_MARKER_RE = re.compile(r"^\?\[(/?(row|box)(:[^\]]*)?)\]\s*$", re.MULTILINE)


def _word_html_forms(source: str, field_type: str | None) -> str:
    """Retain HTML controls instead of silently dropping them in Word."""

    class Controls(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.parts: list[str] = []
            self.control: str | None = None
            self.attrs: dict[str, str | None] = {}
            self.options: list[str] = []
            self.text = ""
            self.index = 0
            self.cells = 0
            self.flex_cells: list[bool] = []
            self.selected: int | None = None

        @property
        def boxed(self) -> bool:
            """Inputs are drawn as boxes in body text and in the theme's flex-row cells."""
            return not self.cells or bool(self.flex_cells and self.flex_cells[-1])

        def box(self, text: str, **flags: str) -> str:
            """Inline-safe field box: no blank lines inside a raw HTML block."""
            return _field_box(text, filled=False if field_type else None, **flags).strip()

        def field_name(self, attrs: dict[str, str | None]) -> str:
            self.index += 1
            return attrs.get("name") or attrs.get("id") or f"html_field_{self.index}"

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = dict(attrs)
            if tag in ("td", "th"):
                self.cells += 1
                self.flex_cells.append("flex-cell" in (values.get("class") or ""))
            if self.control:
                if tag == "option":
                    if self.text.strip():
                        self.options.append(self.text.strip())
                    if "selected" in values:
                        self.selected = len(self.options)
                    self.text = ""
                return
            if tag == "input":
                kind = values.get("type") or "text"
                if kind in ("hidden", "submit", "reset", "button"):
                    return
                if field_type:
                    name = self.field_name(values)
                    text = f"[[?cb:{name}]]" if kind in ("checkbox", "radio") else f"[[{name}]]"
                elif kind in ("checkbox", "radio"):
                    text = "☑" if "checked" in values else ("○" if kind == "radio" else "☐")
                else:
                    text = values.get("value") or "________"
                if kind not in ("checkbox", "radio") and self.boxed:
                    shown = text if field_type else (values.get("value") or "")
                    self.parts.append(self.box(shown))
                else:
                    self.parts.append(escape(text))
            elif tag in ("select", "textarea"):
                self.control, self.attrs, self.options, self.text = tag, values, [], ""
                self.selected = None
            else:
                self.parts.append(self.get_starttag_text())

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.handle_starttag(tag, attrs)

        def handle_endtag(self, tag: str) -> None:
            if self.control:
                if tag != self.control:
                    return
                if self.text.strip():
                    self.options.append(self.text.strip())
                if field_type:
                    name = self.field_name(self.attrs)
                    options = "|".join(self.options)
                    text = (
                        f"[[?dd:{name}|{options}]]"
                        if self.control == "select" and options
                        else f"[[{name}]]"
                    )
                elif self.control == "select":
                    text = "________ (" + " / ".join(self.options) + ")"
                else:
                    text = self.text or "________"
                if not self.boxed:
                    self.parts.append(escape(unescape(text)))
                elif self.control == "select":
                    chosen = self.options[self.selected or 0] if self.options else ""
                    shown = text if field_type else chosen
                    self.parts.append(self.box(unescape(shown), arrow="1"))
                else:
                    try:
                        rows = float(self.attrs.get("rows") or 4)
                    except ValueError:
                        rows = 4.0
                    height = max(_dim("textarea_min"), rows * _dim("line"))
                    shown = text if field_type else self.text
                    self.parts.append(self.box(unescape(shown), height=height))
                self.control = None
            else:
                if tag in ("td", "th"):
                    self.cells = max(0, self.cells - 1)
                    if self.flex_cells:
                        self.flex_cells.pop()
                self.parts.append(f"</{tag}>")

        def handle_data(self, data: str) -> None:
            if self.control:
                self.text += data
            else:
                self.parts.append(data)

        def handle_entityref(self, name: str) -> None:
            self.handle_data(f"&{name};")

        def handle_charref(self, name: str) -> None:
            self.handle_data(f"&#{name};")

        def handle_comment(self, data: str) -> None:
            if not self.control:
                self.parts.append(f"<!--{data}-->")

    parser = Controls()
    parser.feed(source)
    parser.close()
    return "".join(parser.parts)


def _word_form_layout(md_content: str) -> str:
    """Keep side-by-side field groups and grids as real Word tables."""
    import markdown

    pattern = re.compile(
        r"^\?\[(row|box)(?::([^\]]*))?\]\s*\n(.*?)^\?\[/\1\]\s*$", re.MULTILINE | re.DOTALL
    )

    def table(match: re.Match) -> str:
        kind, args, content = match.groups()
        rows = []
        for line in content.strip().splitlines():
            if line.strip():
                # Option separators inside ?[...] / [[...]] belong to a field.
                cells = re.split(r"\|(?![^\[]*\])", line.strip())
                rows.append(
                    [markdown.markdown(c.strip(), extensions=["extra"]) for c in cells if c.strip()]
                )
        width = re.search(r"widths\s*=\s*([\d.,\s]+)", args or "")
        prefix = f"<!-- col-widths: {width.group(1).strip()} -->\n" if width else ""
        columns = max((len(row) for row in rows), default=0)

        def row_html(row: list[str]) -> str:
            cells = []
            for index, cell in enumerate(row):
                # A short row in a ?[box] grid spans the remaining columns, as in the PDF.
                last = index == len(row) - 1
                span = columns - len(row) + 1 if kind == "box" and last else 1
                attr = f' colspan="{span}"' if span > 1 else ""
                cells.append(f"<td{attr}>{cell}</td>")
            return "<tr>" + "".join(cells) + "</tr>"

        body = "".join(row_html(row) for row in rows)
        import base64

        token = re.search(r"pdf=([A-Za-z0-9_=-]+)", args or "")
        pdf_html = base64.urlsafe_b64decode(token.group(1)).decode() if token else ""
        return (
            f'\n\n{prefix}<table class="field-{kind}" '
            f'data-pdf="{escape(pdf_html, quote=True)}">{body}</table>\n\n'
        )

    return pattern.sub(table, md_content)


_CHOICE_TYPES = frozenset({"checkbox", "yesno", "checkbox-inline", "radio", "radio-inline"})

_FORM_BLOCK_RE = re.compile(
    r"^\?\[(row|box)(?::([^\]]*))?\]\s*\n(.*?)^\?\[/\1\]\s*$", re.MULTILINE | re.DOTALL
)


def _field_metrics(theme: dict[str, Any]) -> dict[str, Any]:
    """Box metrics of a text input: from the theme's input rule, else the root theme's."""
    box = theme.get("form_input") or {}
    border_box = bool(box.get("border_box"))
    return {
        "border_box": border_box,
        "textarea_min": float(box.get("textarea_min", _dim("textarea_min") + 10.0)),
        "pad_x": float(box.get("pad_x", _FIELD_PAD_X_PT)),
        # border-box controls ignore vertical padding (see _parse_form_css)
        "pad_y": 0.0 if border_box else float(box.get("pad_y", _FIELD_PAD_Y_PT)),
        "border": float(box.get("border_pt", _FIELD_BORDER_PT)),
        "color": str(box.get("border_color", _FIELD_BORDER_COLOR)).lstrip("#").upper(),
        "fill": str(box.get("fill", _FIELD_FILL)).lstrip("#").upper(),
    }


def _style_field_box_paragraph(
    para: Any,
    content_pt: float,
    metrics: dict[str, Any],
    text_width_pt: float,
    *,
    arrow: bool = False,
) -> None:
    """Make *para* a full-width bordered, shaded input box with an exact line height.

    The border sits outside the paragraph indent in Word, so indent by border +
    padding to line the visible box up with the surrounding text column.
    """
    fmt = para.paragraph_format
    if metrics["border_box"]:
        # Total box height: one text line for an input, ``min-height`` for a textarea.
        total = metrics["textarea_min"] if content_pt > _dim("line") else _dim("line") + 1.0
        content_pt = total - 2 * metrics["border"]
    fmt.line_spacing = Pt(content_pt)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.keep_together = True
    fmt.alignment = WD_ALIGN_PARAGRAPH.LEFT
    edge_pt = metrics["pad_x"] + metrics["border"]
    fmt.left_indent = Pt(edge_pt)
    fmt.right_indent = Pt(edge_pt)
    pPr = para._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    for side, space in (
        ("top", metrics["pad_y"]),
        ("left", metrics["pad_x"]),
        ("bottom", metrics["pad_y"]),
        ("right", metrics["pad_x"]),
    ):
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:val"), "single")
        edge.set(qn("w:sz"), str(round(metrics["border"] * 8)))
        edge.set(qn("w:space"), str(round(space)))
        edge.set(qn("w:color"), metrics["color"])
        pBdr.append(edge)
    _insert_ppr_in_order(pPr, pBdr, ["shd", *_PPR_AFTER_SHD])
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), metrics["fill"])
    _insert_ppr_in_order(pPr, shd, _PPR_AFTER_SHD)
    if arrow:
        width_twips = round((text_width_pt - 2 * edge_pt) * 20)
        fmt.tab_stops.add_tab_stop(Emu(width_twips * 635), WD_TAB_ALIGNMENT.RIGHT)


_FIELD_BLOCK_RE = re.compile(r'(<div class="docx-field"[^>]*>.*?</div>)', re.DOTALL)


def _split_field_segments(cell_html: str) -> list[tuple[str, str]]:
    """Split cell HTML into ``("text", html)`` and ``("box", html)`` pieces."""
    parts = []
    for piece in _FIELD_BLOCK_RE.split(cell_html):
        if not piece.strip():
            continue
        parts.append(("box" if piece.startswith('<div class="docx-field"') else "text", piece))
    return parts


def _parse_box_segment(segment: str) -> tuple[dict[str, str], str]:
    """Attributes and visible text of a ``<div class="docx-field">`` segment."""
    match = re.match(r'<div class="docx-field"([^>]*)>(.*)</div>', segment, re.DOTALL)
    attrs = dict(re.findall(r'data-([\w-]+)="([^"]*)"', match.group(1))) if match else {}
    text = unescape(re.sub(r"<[^>]+>", "", match.group(2))) if match else ""
    return attrs, text


def _cell_textarea_height(attrs: dict[str, str | bool]) -> float:
    """A textarea in a grid cell: ``rows`` lines at the cell's 1.25 line height + padding."""
    try:
        rows = float(attrs.get("rows") or 4)
    except (TypeError, ValueError):
        rows = 4.0
    return rows * 12.5 + 2.0


def _cell_input(text: str, height: float | None = None) -> str:
    """Inline marker for an input inside a form-grid cell (see ``_render_cell_html``)."""
    attr = f' data-h="{height:g}"' if height else ""
    return f'<span class="docx-input"{attr}>{text}</span>'


def _field_box(
    text: str = "", *, height: float | None = None, filled: bool | None = None, **flags: str
) -> str:
    """Block-level HTML for a bordered input box (see ``_start_field_box``).

    ``filled`` says the PDF input holds default text (so it is baseline-aligned
    to that text rather than to its bottom edge). It defaults to "has text".
    """
    attrs = f' data-h="{height:g}"' if height else ""
    if text.strip() if filled is None else filled:
        attrs += ' data-filled="1"'
    attrs += "".join(f' data-{k}="{v}"' for k, v in flags.items())
    return f'\n\n<div class="docx-field"{attrs}>{escape(text)}</div>\n\n'


def _textarea_height(attrs: dict[str, str | bool]) -> float:
    """Content height of a textarea: ``rows`` x 12pt, never under the 48pt minimum."""
    try:
        rows = float(attrs.get("rows") or 4)
    except (TypeError, ValueError):
        rows = 4.0
    return max(_dim("textarea_min"), rows * _dim("line"))


def _with_pdf_table(block: re.Match, converted: str) -> str:
    """Tag a converted ``?[row]``/``?[box]`` block with the PDF's own HTML for it.

    The PDF builder's table markup (from the *original* source) is what gets laid
    out to find the row heights Word must reproduce; it rides along in the opening
    marker as ``pdf=<base64>`` and is read back by ``_word_form_layout``.
    """
    import base64

    from .pdf import _expand_box_block, _expand_row_block

    kind, args, content = block.groups()
    pdf_html = _expand_box_block(args, content) if kind == "box" else _expand_row_block(content)
    token = base64.urlsafe_b64encode(pdf_html.encode()).decode()
    prefix = f"{args};" if args else ""
    return re.sub(
        r"^\?\[(?:row|box)(?::[^\]]*)?\]",
        lambda _m: f"?[{kind}:{prefix}pdf={token}]",
        converted,
        count=1,
        flags=re.MULTILINE,
    )


def _convert_form_markup(md_content: str, inline: Any, boxed: Any) -> str:
    """Rewrite ``?[...]`` markers: *boxed* for body fields, *inline* inside grids.

    Fields in prose become stand-alone bordered boxes, as the PDF draws them.
    Fields inside ``?[row]``/``?[box]`` grids and pipe-table rows stay inline:
    the PDF renders those borderless, filling their cell.
    """
    from ..forms import FIELD_RE

    def prose(segment: str) -> str:
        lines: list[str] = []
        previous = ""
        for line in segment.split("\n"):
            fn = inline if line.lstrip().startswith("|") else boxed

            def convert(match: re.Match, line: str = line, previous: str = previous) -> str:
                text = fn(match)
                if fn is not boxed or 'class="docx-field"' not in text:
                    return text
                # The PDF draws the input inside the paragraph that holds its
                # label; remember that so Word can drop the gap between them.
                before = line[: match.start()].strip()
                prior = previous.strip()
                # Block syntax (headings, rules, quotes, lists, tables, HTML) never
                # shares a paragraph with the field on the next line; emphasis does.
                prior_is_text = bool(prior) and (
                    prior.startswith(("**", "_"))
                    or (prior.startswith("*") and not prior.startswith("* "))
                    or not prior.startswith(("#", "<", "|", ">", "-", "+", "`", "!"))
                )
                joined = bool(before) or prior_is_text
                return (
                    text.replace(
                        '<div class="docx-field"', '<div class="docx-field" data-join="1"', 1
                    )
                    if joined
                    else text
                )

            lines.append(FIELD_RE.sub(convert, line))
            previous = line
        return "\n".join(lines)

    out: list[str] = []
    pos = 0
    for block in _FORM_BLOCK_RE.finditer(md_content):
        out.append(prose(md_content[pos : block.start()]))
        text = block.group(0)
        if block.group(1) == "row" and "?[signature" in text:
            # PDF: labels in a signature row become captions under their rule.
            text = re.sub(
                r"\*\*([^*|]+?)\*\*\s*(\?\[[^\]]*\])",
                r'\2<br><span class="docx-cap">\1</span>',
                text,
            )
        out.append(_with_pdf_table(block, FIELD_RE.sub(inline, text)))
        pos = block.end()
    out.append(prose(md_content[pos:]))
    return _STRUCT_MARKER_RE.sub("", _word_form_layout("".join(out)))


def _strip_form_fields_for_docx(md_content: str) -> str:
    """Render PDF ``?[...]`` form markers as visible, PDF-sized boxes for Word.

    Plain ``.docx`` retains the boxes, choice labels, defaults and grids.
    Interactive fields are available in the companion DOTX template.
    """
    from ..forms import INPUT_TYPES, OPTION_TYPES, parse_field_spec

    def inline(match: re.Match) -> str:
        parsed = parse_field_spec(match.group(1))
        if parsed is None:
            return match.group(0) if _STRUCT_MARKER_RE.fullmatch(match.group(0)) else ""
        ftype, _name, options, attrs = parsed
        if ftype == "checkbox":
            return ("\u2611" if attrs.get("checked") else "\u2610") + (
                " " + str(attrs["label"]) if attrs.get("label") else ""
            )
        if ftype == "yesno":
            return "\u2610 Yes   \u2610 No"
        if ftype in ("checkbox-inline", "radio", "radio-inline"):
            mark = "\u2610" if ftype == "checkbox-inline" else "\u25cb"
            # A block radio group lists one option per line, as the PDF does.
            separator = "<br>" if ftype == "radio" else "   "
            return separator.join(f"{mark} {option}" for option in options)
        if ftype in OPTION_TYPES:
            return _cell_input("\\_" * 8 + " (" + " / ".join(options) + ")")
        value = attrs.get("value")
        shown = escape(str(value)) if value is not None else "\\_" * 8
        cell = _cell_input(shown, _cell_textarea_height(attrs) if ftype == "textarea" else None)
        if ftype == "signature":
            cell += '<br><span class="docx-cap">Signature</span>'
        return cell

    def boxed(match: re.Match) -> str:
        parsed = parse_field_spec(match.group(1))
        if parsed is None:
            return inline(match)
        ftype, _name, options, attrs = parsed
        value = "" if attrs.get("value") is None else str(attrs["value"])
        if ftype == "textarea":
            return _field_box(value, height=_textarea_height(attrs))
        if ftype == "signature":
            return (
                _field_box(value, height=_dim("signature_h"), style="line")
                + '\n\n<div class="docx-caption">Signature</div>\n\n'
            )
        if ftype == "select":
            first = options[0] if options else ""
            return _field_box(first, arrow="1")
        if ftype in INPUT_TYPES or ftype not in _CHOICE_TYPES:
            return _field_box(value)
        return inline(match)

    return _convert_form_markup(md_content, inline, boxed)


def _convert_form_fields_for_dotx(md_content: str) -> str:
    """Map ``?[...]`` form markers to Word form fields for ``.dotx`` output.

    The same source that produces a fillable PDF produces a fillable Word
    template: text-ish fields become Text Form Fields (via the existing
    ``[[name]]`` machinery), checkboxes become FORMCHECKBOX, selects/radios
    become FORMDROPDOWN, and a ``yesno`` becomes a pair of labelled
    checkboxes. Row/box layout markers become Word tables;
    submit buttons have no Word equivalent and are removed.
    """
    from ..forms import INPUT_TYPES, OPTION_TYPES, parse_field_spec

    def convert(m: re.Match) -> str:
        spec = m.group(1).strip()
        parsed = parse_field_spec(spec)
        if parsed is None:
            return m.group(0) if _STRUCT_MARKER_RE.fullmatch(m.group(0)) else ""
        ftype, name, options, attrs = parsed
        if ftype == "checkbox":
            label = attrs.get("label")
            suffix = f" {label}" if label and label is not True else ""
            return f"[[?cb:{name}]]{suffix}"
        if ftype == "checkbox-inline":
            return "   ".join(
                f"[[?cb:{name}_{o.lower().replace(' ', '_').replace('-', '_')}]] {o}"
                for o in options
            )
        if ftype == "yesno":
            return f"[[?cb:{name}_yes]] Yes   [[?cb:{name}_no]] No"
        if ftype in OPTION_TYPES:  # select / radio / radio-inline
            opts = "|".join(o for o in options if not o.startswith("--"))
            return _cell_input(f"[[?dd:{name}|{opts}]]" if opts else f"[[{name}]]")
        # text / email / date / number / tel / url / textarea / signature / unknown
        return _cell_input(
            f"[[{name}]]", _cell_textarea_height(attrs) if ftype == "textarea" else None
        )

    def boxed(m: re.Match) -> str:
        parsed = parse_field_spec(m.group(1).strip())
        if parsed is None:
            return convert(m)
        ftype, name, options, attrs = parsed
        marker = convert(m)
        if ftype == "textarea":
            return _field_box(marker, height=_textarea_height(attrs), filled=False)
        if ftype == "signature":
            return _field_box(marker, height=40.0, style="line", filled=False)
        if ftype == "select" or ftype in INPUT_TYPES or ftype not in _CHOICE_TYPES:
            return _field_box(marker, filled=False)
        return marker

    return _convert_form_markup(md_content, convert, boxed)


def _merge_pdf_form_css(
    theme: dict[str, Any], config: dict[str, Any], repo_root: Path | None, doc_path: Path | None
) -> None:
    """Take form layout rules from the PDF theme when the Word theme lacks them.

    Input boxes, field labels and flex rows exist only in the PDF stylesheet
    (the Word theme usually imports just the brand rules), and the PDF is the
    layout the Word export has to follow.
    """
    if repo_root is None or all(k in theme for k in ("form_input", "form_label", "flex_rows")):
        return
    try:
        from .pdf import _resolve_css

        css_path = _resolve_css(config, repo_root, doc_path=doc_path)
        if not css_path or not Path(css_path).exists():
            return
        pdf_theme = parse_css_for_word(Path(css_path))
    except Exception:  # noqa: BLE001 - layout hints are best-effort
        return
    for key in ("form_input", "form_label", "flex_rows"):
        if key in pdf_theme and key not in theme:
            theme[key] = pdf_theme[key]


def _resolve_docx_theme(
    doc_path: Path | None,
    repo_root: Path | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if doc_path is None or repo_root is None:
        return {}
    result = resolve_docx_theme(doc_path, repo_root, config)
    return result if result is not None else {}


def _add_page_header_bar(
    doc: Document,
    config: dict[str, Any],
    doc_path: Path | None,
    repo_root: Path | None,
) -> None:
    """Add a coloured header bar with optional text/logos to every page.

    Mirrors the PDF's ``.page-header-bar-fixed``: a full-bleed bar at the
    physical page top (the PDF positions it with negative margin offsets),
    8pt regular text, logos capped at 70% of the bar height, content aligned
    with the page margins, and the content area starting ``height + padding``
    below the top.
    """
    if not config.get("page_header_bar"):
        return

    color_hex = str(config.get("page_header_bar_color", "#2563eb")).lstrip("#")
    text_color_hex = str(config.get("page_header_bar_text_color", "#ffffff")).lstrip("#")
    height_mm = _cfg_mm(config.get("page_header_bar_height"), 12.0)
    gap_mm = _cfg_mm(config.get("page_header_bar_padding"), 6.0)
    offset_mm = max(0.0, _cfg_mm(config.get("page_header_bar_offset"), 0.0))
    header_text = config.get("header_text", "")
    text_position = str(config.get("header_text_position", "left")).lower()

    single_logo = config.get("page_header_bar_logo") or config.get("header_logo")
    single_logo_position = str(
        config.get("page_header_bar_logo_position") or config.get("header_logo_position", "right")
    ).lower()

    section = doc.sections[0]

    # The PDF bar starts at the physical page top and content begins
    # height + padding below it (@page { margin-top: calc(h + p) }).
    section.header_distance = Mm(offset_mm)
    section.top_margin = Mm(offset_mm + height_mm + gap_mm)

    header = section.header
    header.is_linked_to_previous = False
    for para in list(header.paragraphs):
        para._p.getparent().remove(para._p)

    left_margin_twips = round(section.left_margin / 635)
    page_twips = round(section.page_width / 635)

    table = header.add_table(rows=1, cols=3, width=section.page_width)

    # Set the same style as body tables so the style-level tblInd is 0.
    # Without this, Word applies the default table style (tblInd ~108 twips)
    # which shifts the bar right of body content even with explicit tblInd=0.
    try:
        table.style = "Table Normal"
    except KeyError:
        table.style = "Normal Table"

    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)

    # Full page width, bleeding into both margins via a negative left indent.
    for old in tblPr.findall(qn("w:tblW")):
        tblPr.remove(old)
    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:w"), str(page_twips))
    tblW.set(qn("w:type"), "dxa")
    tblPr.append(tblW)

    for old in tblPr.findall(qn("w:tblLayout")):
        tblPr.remove(old)
    tblLayout = OxmlElement("w:tblLayout")
    tblLayout.set(qn("w:type"), "fixed")
    tblPr.append(tblLayout)

    for old in tblPr.findall(qn("w:tblInd")):
        tblPr.remove(old)
    tblInd = OxmlElement("w:tblInd")
    tblInd.set(qn("w:w"), str(-left_margin_twips))
    tblInd.set(qn("w:type"), "dxa")
    tblPr.append(tblInd)

    # Zero default cell margins; the outer cells re-add the page margins so
    # bar content aligns with body content (PDF: padding 0 20mm 0 25mm).
    tblCellMar = OxmlElement("w:tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        mar = OxmlElement(f"w:{side}")
        mar.set(qn("w:w"), "0")
        mar.set(qn("w:type"), "dxa")
        tblCellMar.append(mar)
    tblPr.append(tblCellMar)

    # 3 slots: left / center / right. The PDF splits the *text width* 35/30/35
    # (its bar is padded by the page margins), so the outer cells here add the
    # page margins to their widths; otherwise the left slot is ~27pt narrower
    # than the PDF's and a long header wraps onto a second line.
    right_margin_twips = round(section.right_margin / 635)
    text_twips = page_twips - left_margin_twips - right_margin_twips
    side_w = round(text_twips * 0.35)
    col_widths = [
        left_margin_twips + side_w,
        text_twips - 2 * side_w,
        right_margin_twips + side_w,
    ]
    for old_grid in tbl.findall(qn("w:tblGrid")):
        tbl.remove(old_grid)
    tblGrid = OxmlElement("w:tblGrid")
    for cw in col_widths:
        gridCol = OxmlElement("w:gridCol")
        gridCol.set(qn("w:w"), str(cw))
        tblGrid.append(gridCol)
    tbl.insert(list(tbl).index(tblPr) + 1, tblGrid)

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
    trHeight.set(qn("w:hRule"), "exact")
    trPr.append(trHeight)

    aligns = (WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.RIGHT)
    for c_idx, cell in enumerate(row.cells):
        set_cell_shading(cell, color_hex)
        tcPr = cell._tc.get_or_add_tcPr()
        for old in tcPr.findall(qn("w:tcW")):
            tcPr.remove(old)
        tcW_el = OxmlElement("w:tcW")
        tcW_el.set(qn("w:w"), str(col_widths[c_idx]))
        tcW_el.set(qn("w:type"), "dxa")
        tcPr.append(tcW_el)
        tcBorders = OxmlElement("w:tcBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "none")
            tcBorders.append(b)
        tcPr.append(tcBorders)
        vAlign = OxmlElement("w:vAlign")
        vAlign.set(qn("w:val"), "center")
        tcPr.append(vAlign)
        para = cell.paragraphs[0]
        para.alignment = aligns[c_idx]
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)
        _set_para_mark_size(para)
        para.paragraph_format.line_spacing = 1.0
    # Align outer-cell content with the page margins.
    _set_cell_margins_mm(row.cells[0], top=0, right=0, bottom=0, left=section.left_margin / 36000)
    _set_cell_margins_mm(row.cells[2], top=0, right=section.right_margin / 36000, bottom=0, left=0)

    slot_paras = {
        "left": row.cells[0].paragraphs[0],
        "center": row.cells[1].paragraphs[0],
        "right": row.cells[2].paragraphs[0],
    }
    # PDF: .phb-logo max-height = 70% of the bar height (or header_logo_height).
    # Intrinsically smaller logos keep their natural size — never upscaled.
    logo_forced = _parse_mm_cfg(config.get("header_logo_height"))
    logo_cap = height_mm * 0.7 if logo_forced is None else logo_forced

    if header_text:
        para = slot_paras.get(text_position, slot_paras["left"])
        run = para.add_run(str(header_text))
        run.font.size = Pt(8)  # PDF: .phb-text { font-size: 8pt; } (not bold)
        run.font.color.rgb = RGBColor.from_string(text_color_hex.upper())

    def _slot_picture(pos: str, path: Path) -> None:
        para = slot_paras.get(pos, slot_paras["center"])
        if para.runs:
            para.add_run("  ")
        try:
            h = _logo_height_mm(path, logo_cap, logo_forced)
            para.add_run().add_picture(str(path), height=Mm(h))
        except Exception as exc:
            logger.warning("docx header bar logo embed failed: %s", exc)

    if single_logo:
        logo_path = _resolve_asset(str(single_logo), doc_path, repo_root)
        if logo_path:
            _slot_picture(single_logo_position, logo_path)

    for entry in config.get("page_header_bar_logos", []) or []:
        if isinstance(entry, dict):
            lpath = _resolve_asset(str(entry.get("path", "")), doc_path, repo_root)
            pos = str(entry.get("position", "center")).lower()
        else:
            lpath = _resolve_asset(str(entry), doc_path, repo_root)
            pos = "center"
        if lpath:
            _slot_picture(pos, lpath)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------


_FOOTER_TOKEN_RE = re.compile(r"(\{pages?\})")

_CSS_CONTENT_TOKEN_RE = re.compile(
    r'"([^"]*)"'  # double-quoted string
    r"|'([^']*)'"  # single-quoted string
    r"|counter\(\s*pages\s*\)"
    r"|counter\(\s*page\s*\)"
    r"|string\([^)]*\)"
)


def _css_content_to_text(value: str, date_str: str) -> str | None:
    """Convert a CSS ``content`` value into footer text.

    Quoted strings become literals, ``counter(page)``/``counter(pages)`` become
    the ``{page}``/``{pages}`` tokens the Word footer expands to live fields,
    and ``string(...)`` (the theme's running date) becomes *date_str*.
    """
    if value.strip().lower() in ("none", "normal"):
        return None
    out: list[str] = []
    for m in _CSS_CONTENT_TOKEN_RE.finditer(value):
        if m.group(1) is not None:
            out.append(m.group(1))
        elif m.group(2) is not None:
            out.append(m.group(2))
        elif m.group(0).startswith("string"):
            out.append(date_str)
        elif "pages" in m.group(0):
            out.append("{pages}")
        else:
            out.append("{page}")
    text = "".join(out)
    return text or None


def _css_footer_defaults(css_text: str | None, date_str: str) -> dict[str, tuple[str, float, str]]:
    """Extract the theme's default ``@page`` footer boxes for Word.

    The PDF renders ``@bottom-left/center/right`` margin boxes straight from
    the theme CSS (org name, running date, "Page N of M") even when no
    ``footer_*`` config keys are set. Parse those defaults so the Word footer
    shows the same content. Returns ``{slot: (text, font_size_pt, color_hex)}``.
    """
    if not css_text:
        return {}
    clean = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    m = re.search(r"@page\s*\{", clean)
    if not m:
        return {}
    # Brace-match the @page block (it contains nested margin-box blocks).
    depth, i = 1, m.end()
    while i < len(clean) and depth:
        if clean[i] == "{":
            depth += 1
        elif clean[i] == "}":
            depth -= 1
        i += 1
    block = clean[m.end() : i - 1]

    result: dict[str, tuple[str, float, str]] = {}
    for slot in ("left", "center", "right"):
        bm = re.search(rf"@bottom-{slot}\s*\{{([^}}]*)\}}", block)
        if not bm:
            continue
        props: dict[str, str] = {}
        for decl in bm.group(1).split(";"):
            if ":" in decl:
                prop, _, val = decl.partition(":")
                props[prop.strip().lower()] = val.strip()
        text = _css_content_to_text(props.get("content", ""), date_str)
        if not text:
            continue
        size_m = re.search(r"([\d.]+)\s*pt", props.get("font-size", ""))
        size = float(size_m.group(1)) if size_m else 7.5
        color_m = re.search(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", props.get("color", ""))
        color = color_m.group(0) if color_m else "#7f8c9a"
        result[slot] = (text, size, color)
    return result


def _add_simple_field(paragraph: Any, instr: str) -> list[Any]:
    """Append a simple Word field (e.g. ``PAGE``/``NUMPAGES``); return all its runs.

    Every run (not just the result) is returned so the caller can style them:
    renderers take the field result's formatting from the field's first run.
    """
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    run._r.append(begin)

    run2 = paragraph.add_run()
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = f" {instr} "
    run2._r.append(instr_el)

    run3 = paragraph.add_run()
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    run3._r.append(sep)

    value_run = paragraph.add_run("1")

    run5 = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run5._r.append(end)
    return [run, run2, run3, value_run, run5]


def _emit_footer_segment(paragraph: Any, text: str, lead_tabs: int = 0) -> list[Any]:
    """Write *text* into *paragraph*, expanding ``{page}``/``{pages}`` to fields.

    ``lead_tabs`` is the number of tabs that reach this slot's tab stop (0 =
    left, 1 = centre, 2 = right); continuation lines after a soft break re-tab
    to the same stop so a multiline centre/right slot doesn't fall back to the
    left margin.

    Returns every run created so the caller can apply a consistent footer style.
    """
    runs: list[Any] = []
    for part in _FOOTER_TOKEN_RE.split(text):
        if part == "{page}":
            runs.extend(_add_simple_field(paragraph, "PAGE"))
        elif part == "{pages}":
            runs.extend(_add_simple_field(paragraph, "NUMPAGES"))
        elif part:
            for i, line in enumerate(part.split("\n")):
                if i > 0:
                    br = paragraph.add_run()
                    br.add_break()
                    runs.append(br)
                    for _ in range(lead_tabs):
                        tab = paragraph.add_run()
                        tab.add_tab()
                        runs.append(tab)
                if line:
                    runs.append(paragraph.add_run(line))
    return runs


def _add_footer(
    doc: Document,
    config: dict[str, Any],
    *,
    css_text: str | None = None,
    date_str: str = "",
    hide_running_date: bool = False,
) -> None:
    """Populate the document footer from footer_left/center/right.

    The three slots are laid out with centre and right tab stops so they mirror
    the PDF ``@bottom-left/center/right`` margin boxes. ``{page}`` and
    ``{pages}`` tokens become live Word page-number fields (the same tokens work
    in the PDF footer). A top border separates the footer from body content.

    Per-slot resolution matches the PDF exactly: an explicitly configured
    ``footer_*`` key wins (6pt, #7f8c9a — the style ``_build_footer_style``
    injects), an empty string suppresses the slot, and an absent key falls back
    to the theme CSS's ``@bottom-*`` default box (its own font-size/colour).
    """
    defaults = _css_footer_defaults(css_text, date_str)
    if hide_running_date:
        # Form PDFs hide the running date (``.running-date { display: none }``).
        defaults = {slot: v for slot, v in defaults.items() if not (date_str and v[0] == date_str)}

    slots: dict[str, tuple[str, float, str] | None] = {}
    for slot in ("left", "center", "right"):
        cfg_val = config.get(f"footer_{slot}")
        if cfg_val is not None:
            # Explicit config — empty string suppresses the slot (content: none).
            slots[slot] = (str(cfg_val), 6.0, "#7f8c9a") if str(cfg_val) else None
        else:
            slots[slot] = defaults.get(slot)

    if not any(slots.values()):
        return

    section = doc.sections[0]
    section.footer.is_linked_to_previous = False
    footer = section.footer

    # Clear the default empty paragraph Word adds
    for para in list(footer.paragraphs):
        p = para._element
        p.getparent().remove(p)

    text_width_emu = int(section.page_width - section.left_margin - section.right_margin)

    para = footer.add_paragraph()
    # Slots are positioned by tab stops, so the paragraph itself must be
    # left-aligned. Without this it inherits the Normal style — a theme with
    # body text-align: justify stretched the footer across the full width
    # instead of centring the middle slot.
    para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    # Never inherit the theme's body line-height/paragraph spacing either —
    # a 1.6 line height + 10pt space-after turns a 6pt footer line into a
    # ~30pt-tall header/footer container.
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0

    from docx.enum.text import WD_TAB_ALIGNMENT

    tabs = para.paragraph_format.tab_stops
    tabs.add_tab_stop(Emu(text_width_emu // 2), WD_TAB_ALIGNMENT.CENTER)
    tabs.add_tab_stop(Emu(text_width_emu), WD_TAB_ALIGNMENT.RIGHT)

    # Top border (theme @bottom-* boxes: 0.5pt #d5d8dc). The PDF drops the
    # footer border when a page header bar is enabled — mirror that here.
    if not config.get("page_header_bar"):
        pPr = para._element.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        top = OxmlElement("w:top")
        top.set(qn("w:val"), "single")
        top.set(qn("w:sz"), "4")
        top.set(qn("w:space"), "4")
        top.set(qn("w:color"), "d5d8dc")
        pBdr.append(top)
        pPr.append(pBdr)

    for i, slot in enumerate(("left", "center", "right")):
        if i > 0:
            para.add_run().add_tab()
        entry = slots[slot]
        if not entry:
            continue
        text, size_pt, color_hex = entry
        r, g, b = _hex_to_rgb(color_hex)
        for run in _emit_footer_segment(para, text, lead_tabs=i):
            run.font.size = Pt(size_pt)
            run.font.color.rgb = RGBColor(r, g, b)


def _add_plain_header(
    doc: Document,
    config: dict[str, Any],
    doc_path: Path | None,
    repo_root: Path | None,
) -> None:
    """Add header_text / header_logo to the page header when no header bar is used.

    Mirrors the PDF ``@top-left``/``@top-right`` margin boxes so a document that
    only sets ``header_text``/``header_logo`` (without ``page_header_bar``) still
    shows them in Word.
    """
    if config.get("page_header_bar"):
        return  # the coloured bar already renders header text/logo
    header_text = config.get("header_text")
    logo_file = config.get("header_logo")
    if not header_text and not logo_file:
        return

    text_position = str(config.get("header_text_position", "left")).lower()
    logo_position = str(config.get("header_logo_position", "right")).lower()
    logo_path = _resolve_asset(str(logo_file), doc_path, repo_root) if logo_file else None

    section = doc.sections[0]
    section.header.is_linked_to_previous = False
    header = section.header
    for para in list(header.paragraphs):
        para._p.getparent().remove(para._p)

    text_width_emu = int(section.page_width - section.left_margin - section.right_margin)
    para = header.add_paragraph()
    # Tab stops position the slots — never inherit the Normal style's
    # alignment (a justified body theme would stretch the header line).
    para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    # Never inherit the theme's body line-height/paragraph spacing either —
    # a 1.6 line height + 10pt space-after turns a 6pt footer line into a
    # ~30pt-tall header/footer container.
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    from docx.enum.text import WD_TAB_ALIGNMENT

    tabs = para.paragraph_format.tab_stops
    tabs.add_tab_stop(Emu(text_width_emu // 2), WD_TAB_ALIGNMENT.CENTER)
    tabs.add_tab_stop(Emu(text_width_emu), WD_TAB_ALIGNMENT.RIGHT)

    # Hairline under the header content (theme @top-* boxes carry a
    # border-bottom: 0.5pt solid #d5d8dc in the PDF).
    pPr = para._element.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bot = OxmlElement("w:bottom")
    bot.set(qn("w:val"), "single")
    bot.set(qn("w:sz"), "4")
    bot.set(qn("w:space"), "3")
    bot.set(qn("w:color"), "d5d8dc")
    pBdr.append(bot)
    pPr.append(pBdr)

    # Place text and logo into left/center/right slots via tab stops.
    slots: dict[str, list[Any]] = {"left": [], "center": [], "right": []}

    def _slot_text(pos: str) -> None:
        run = para.add_run(str(header_text))
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x5D, 0x6D, 0x7E)

    def _slot_logo(pos: str) -> None:
        run = para.add_run()
        try:
            # min(intrinsic, 8mm) by default; header_logo_height forces an
            # exact height — same rule as the PDF's margin-box logo.
            h = _logo_height_mm(logo_path, 8.0, _parse_mm_cfg(config.get("header_logo_height")))
            run.add_picture(str(logo_path), height=Mm(h))
        except Exception as exc:
            logger.warning("docx header logo embed failed: %s", exc)

    # Build an ordered slot plan, then emit with tabs between left/center/right.
    plan: dict[str, Any] = {}
    if header_text:
        plan[text_position if text_position in slots else "left"] = _slot_text
    if logo_path:
        plan[logo_position if logo_position in slots else "right"] = _slot_logo

    if "left" in plan:
        plan["left"]("left")
    para.add_run().add_tab()
    if "center" in plan:
        plan["center"]("center")
    para.add_run().add_tab()
    if "right" in plan:
        plan["right"]("right")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _parse_inline_style(style: str | None) -> dict[str, str]:
    """``style="a: b; c: d"`` -> ``{"a": "b", "c": "d"}`` (lower-cased names)."""
    out: dict[str, str] = {}
    for part in (style or "").split(";"):
        name, sep, value = part.partition(":")
        if sep and name.strip():
            out[name.strip().lower()] = value.strip()
    return out


def _style_padding_pt(style: dict[str, str]) -> dict[str, float] | None:
    """Resolve inline ``padding`` (shorthand and per-side) to top/right/bottom/left pt."""
    from ..docx_theme import _parse_margin, _parse_pt

    sides: dict[str, float] = {}
    if "padding" in style:
        sides = {k: v for k, v in _parse_margin(style["padding"]).items() if v is not None}
    for side in ("top", "right", "bottom", "left"):
        value = style.get(f"padding-{side}")
        if value is not None:
            pt = 0.0 if value.strip() == "0" else _parse_pt(value)
            if pt is not None:
                sides[side] = pt
    return sides or None


def _cell_colspan(style: dict[str, str]) -> int:
    try:
        return max(1, int(style.get("colspan", "1")))
    except ValueError:
        return 1


def _style_width_percent(style: dict[str, str]) -> float | None:
    match = re.fullmatch(r"([\d.]+)%", style.get("width", "").strip())
    return float(match.group(1)) if match else None


def _set_cell_margins(cell: Any, padding: dict[str, float]) -> None:
    """Per-cell padding (``w:tcMar``), inserted in schema order within ``w:tcPr``."""
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:tcMar")):
        tcPr.remove(old)
    mar = OxmlElement("w:tcMar")
    for side in ("top", "left", "bottom", "right"):
        if side in padding:
            edge = OxmlElement(f"w:{side}")
            edge.set(qn("w:w"), str(round(padding[side] * 20)))
            edge.set(qn("w:type"), "dxa")
            mar.append(edge)
    successors = {qn(f"w:{n}") for n in ("textDirection", "tcFitText", "vAlign", "hideMark")}
    for child in tcPr:
        if child.tag in successors:
            child.addprevious(mar)
            return
    tcPr.append(mar)


def _size_choice_lines(doc: Any) -> None:
    """Give body lines that carry a checkbox/radio mark the PDF's taller line box."""
    from docx.text.paragraph import Paragraph

    for el in doc.element.body.iterchildren(qn("w:p")):
        para = Paragraph(el, doc._body)
        if not any(mark in para.text for mark in _CHOICE_MARKS):
            continue
        fmt = para.paragraph_format
        fmt.line_spacing = Pt(_dim("choice_line"))
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY


def _effective_spacing(para: Any, which: str) -> float:
    """Paragraph ``space_before``/``space_after`` in pt, following style inheritance."""
    attr = f"space_{which}"
    value = getattr(para.paragraph_format, attr)
    style = para.style
    while value is None and style is not None:
        value = getattr(style.paragraph_format, attr)
        style = style.base_style
    return float(value.pt) if value is not None else 0.0


def _collapse_paragraph_margins(doc: Any, fixed: dict[Any, tuple[float, float]]) -> None:
    """Make adjacent paragraph margins collapse the way CSS does.

    CSS gives two touching vertical margins the *larger* of the two. Word adds
    the first paragraph's space-after to the next one's space-before, so a 7pt
    paragraph margin above a 14pt heading margin came out 21pt tall instead of
    14pt. Move the shared gap onto the first paragraph as the larger value and
    zero the second; the total is then correct whether a renderer adds or maxes.
    ``fixed`` holds margins that sit inside a line box (form-field boxes) and
    must be left alone.
    """
    from docx.text.paragraph import Paragraph

    blocks = [el for el in doc.element.body if el.tag != qn("w:sectPr")]
    for first, second in zip(blocks, blocks[1:]):
        if first.tag != qn("w:p") or second.tag != qn("w:p"):
            continue
        if first.find(f".//{qn('w:br')}[@{qn('w:type')}='page']") is not None:
            continue  # margins never collapse across a page break
        second_pPr = second.find(qn("w:pPr"))
        if second_pPr is not None and second_pPr.find(qn("w:pageBreakBefore")) is not None:
            continue
        a = Paragraph(first, doc._body)
        b = Paragraph(second, doc._body)
        fixed_after = fixed.get(first, (0.0, 0.0))[1]
        fixed_before = fixed.get(second, (0.0, 0.0))[0]
        after = max(0.0, _effective_spacing(a, "after") - fixed_after)
        before = max(0.0, _effective_spacing(b, "before") - fixed_before)
        if after <= 0 or before <= 0:
            continue
        a.paragraph_format.space_after = Pt(fixed_after + max(after, before))
        b.paragraph_format.space_before = Pt(fixed_before)


def _flex_rows_to_tables(html: str, flex_rows: dict[str, dict[str, Any]] | None) -> str:
    """Render the theme's ``display: flex`` rows as Word-friendly structures.

    A flex container whose children are columns (``.form-row`` > ``.form-group``)
    becomes a borderless one-row table with one cell per child; a wrapping
    container (``.checkbox-group``) becomes a paragraph whose items are spaced
    by the CSS gap. Word has no flexbox, so this keeps the PDF's columns.
    """
    if not flex_rows:
        return html

    class Rewriter(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.out: list[str] = []
            self.roles: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag != "div":
                self.out.append(self.get_starttag_text() or "")
                return
            classes = (dict(attrs).get("class") or "").split()
            rule = next((flex_rows[c] for c in classes if c in flex_rows), None)
            parent = self.roles[-1] if self.roles else ""
            if rule and not rule["wrap"]:
                self.roles.append("row")
                self.out.append(f'<table class="flex-row" data-gap="{rule["gap"]:g}"><tr>')
            elif rule:
                self.roles.append("wrap")
                self.out.append(f'<p class="flex-wrap" data-gap="{rule["gap"]:g}">')
            elif parent == "row":
                self.roles.append("cell")
                self.out.append('<td class="flex-cell">')
            else:
                self.roles.append("other")
                self.out.append(self.get_starttag_text() or "")

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.out.append(self.get_starttag_text() or "")

        def handle_endtag(self, tag: str) -> None:
            if tag == "div" and self.roles:
                role = self.roles.pop()
                self.out.append(
                    {"row": "</tr></table>", "wrap": "</p>", "cell": "</td>"}.get(role, "</div>")
                )
                return
            self.out.append(f"</{tag}>")
            if tag == "label" and self.roles and self.roles[-1] == "wrap":
                self.out.append("&emsp;&emsp;")  # the flex gap between wrapped items

        def handle_data(self, data: str) -> None:
            self.out.append(data)

        def handle_entityref(self, name: str) -> None:
            self.out.append(f"&{name};")

        def handle_charref(self, name: str) -> None:
            self.out.append(f"&#{name};")

        def handle_comment(self, data: str) -> None:
            self.out.append(f"<!--{data}-->")

    rewriter = Rewriter()
    rewriter.feed(html)
    rewriter.close()
    return "".join(rewriter.out)


_JOINED_BOX_RE = re.compile(
    r'</p>\s*(<div class="docx-field" data-join="1"[^>]*>.*?</div>)', re.DOTALL
)


def _merge_joined_field_boxes(html: str) -> str:
    """Move a field box into the label paragraph it continues.

    The PDF draws an input inside the paragraph holding its label, so the pair
    is one block for the heading keep-together rule; keep it one block here.
    """
    previous = None
    while previous != html:
        previous = html
        html = _JOINED_BOX_RE.sub(lambda m: m.group(1) + "</p>", html)
    return html


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

    # --mddoc-* custom properties in the Word theme cascade provide brand
    # defaults for the look-related config keys (YAML always wins).
    if doc_path is not None and repo_root is not None:
        try:
            from ..docx_theme import find_docx_theme_css

            _word_css = find_docx_theme_css(doc_path, repo_root, config)
            if _word_css is not None:
                config = apply_theme_config_defaults(config, _word_css.read_text(encoding="utf-8"))
        except Exception:
            pass

    is_dotx = output_format == "dotx"

    field_type: str | None = None
    cover_page = coerce_bool(config.get("cover_page"), False)

    if is_dotx:
        ft = str(config.get("dotx_field_type", "form")).lower()
        field_type = ft if ft in ("form", "merge") else "form"

    body = _strip_frontmatter(rendered_md)
    title: str = config.get("title") or _extract_title(body) or out_path.stem
    # Same defaults as the PDF builder so the cover carries identical metadata
    # (the PDF always shows an author and a date).
    author: str = config.get("author", "Document Producer")
    date_str: str = config.get("date") or datetime.date.today().strftime("%-d %B %Y")

    if cover_page:
        # The first H1 becomes the cover title. Without a cover the H1 stays in
        # the body as a Heading 1 — exactly what the PDF does.
        body = _strip_leading_h1(body)

    # Inject the same page breaks the PDF builder uses so both formats break at
    # identical points: APPENDIX section H2s and explicit <!-- pagebreak -->.
    body = _inject_appendix_breaks(body)
    body = _inject_page_breaks(body)
    body = collapse_select_markup(body)
    if output_format == "dotx":
        # Same source, fillable Word template: ?[...] → Word form fields.
        body = _convert_form_fields_for_dotx(body)
    else:
        body = _strip_form_fields_for_docx(body)

    from ..math import markdown_html, render_math

    theme = _resolve_docx_theme(doc_path, repo_root, config)
    _merge_pdf_form_css(theme, config, repo_root, doc_path)
    _FORM_DIMS.set(_compute_form_dims(theme))
    html, math_equations = render_math(
        _word_html_forms(
            _flex_rows_to_tables(markdown_html(body, _MD_EXTENSIONS), theme.get("flex_rows")),
            field_type,
        ),
        word=True,
    )
    html = _drop_empty_table_headers(html)

    # Render mermaid diagrams to embedded PNGs, themed from the same CSS the PDF
    # uses so diagram colours match across formats. Falls back to leaving the
    # code block if cairosvg is unavailable.
    mermaid_theme = None
    css_text: str | None = None
    layout_css_path: Path | None = None
    try:
        from .pdf import _resolve_css
        from ..mermaid import extract_theme_from_css

        css_path = _resolve_css(config, repo_root, doc_path=doc_path)
        if css_path and css_path.exists():
            css_text = css_path.read_text(encoding="utf-8")
            layout_css_path = css_path
            mermaid_theme = extract_theme_from_css(css_text)
    except Exception:
        mermaid_theme = None
    html, mermaid_images = _render_mermaid_to_images(html, mermaid_theme)

    doc = Document()
    # Match the PDF's paper size + margins (parsed from the theme's @page) so
    # both formats share the same text width and break at the same points.
    geometry = _page_geometry(css_text)
    # The Word-only --docx-header/footer-distance props live in whichever CSS
    # the Word theme cascade uses (_docx-theme.css if present) — overlay them.
    if doc_path is not None and repo_root is not None:
        try:
            from ..docx_theme import find_docx_theme_css

            word_css = find_docx_theme_css(doc_path, repo_root, config)
            if word_css is not None:
                word_geom = _page_geometry(word_css.read_text(encoding="utf-8"))
                for key in ("header_distance", "footer_distance"):
                    if key in word_geom:
                        geometry[key] = word_geom[key]
        except Exception:
            pass
    _setup_page(doc, geometry)

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
    _add_plain_header(doc, config, doc_path, repo_root)
    _add_footer(
        doc,
        config,
        css_text=css_text,
        date_str=date_str,
        hide_running_date=coerce_bool(config.get("pdf_forms", False)),
    )

    if cover_page:
        # The PDF's @page cover rule suppresses every header/footer margin box
        # on the cover — Word's "different first page" does the same. The
        # first-page header/footer parts are created empty (unlinked).
        section = doc.sections[0]
        section.different_first_page_header_footer = True
        section.first_page_header.is_linked_to_previous = False
        section.first_page_footer.is_linked_to_previous = False

    body_text_align = str(config.get("body_text_align", "")).lower() or None

    raw_col_widths = config.get("table_col_widths")
    table_col_widths: list[float] | None = None
    if isinstance(raw_col_widths, list) and all(
        isinstance(v, (int, float)) for v in raw_col_widths
    ):
        table_col_widths = [float(v) for v in raw_col_widths]

    section_bar: dict[str, Any] | None = None
    if config.get("section_bar"):
        headings_raw = str(config.get("section_bar_headings", "h1,h2"))
        section_bar = {
            "color": str(config.get("section_bar_color", "#2563eb")),
            "text_color": str(config.get("section_bar_text_color", "#ffffff")),
            "text_on_bar": bool(config.get("section_bar_text_on_bar", True)),
            "headings": {h.strip().lower() for h in headings_raw.split(",") if h.strip()},
        }

    builder = _DocxBuilder(
        doc,
        theme=theme,
        field_type=field_type,
        body_text_align=body_text_align,
        table_col_widths=table_col_widths,
        mermaid_images=mermaid_images,
        math_equations=math_equations,
        doc_path=doc_path,
        repo_root=repo_root,
        section_bar=section_bar,
        layout_css=layout_css_path,
        form_document=coerce_bool(config.get("pdf_forms", False)),
    )

    if cover_page:
        # Both docx and dotx use the richer composable cover; _write_text keeps
        # [[field]] markers working in dotx output.
        _add_docx_cover_page(
            doc,
            {**config, "title": title, "author": author, "date": date_str},
            builder,
            theme,
        )

    # Content after the cover starts the pagination baseline — the first body
    # heading must not force an extra page break on top of the cover's.
    builder.mark_content_start()
    # Mirror the PDF's "heading + next two blocks stay together" rule so both
    # formats break pages at the same places.
    html = _keep_heading_with_next(_merge_joined_field_boxes(html))
    builder.feed(html)
    _size_choice_lines(doc)
    _collapse_paragraph_margins(doc, builder._fixed_margins)

    doc.save(str(out_path))

    # Patch the document theme XML to match the CSS font — ensures LibreOffice
    # and other renderers show the correct font family instead of Calibri/Cambria.
    font_body = theme.get("font_body")
    if font_body:
        patch_docx_theme_fonts(out_path, font_body)

    _patch_compatibility_mode(out_path)

    if is_dotx:
        _patch_to_dotx(out_path)
