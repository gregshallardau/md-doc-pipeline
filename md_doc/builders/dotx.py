"""
Word merge-template (.dotx) builder.

Converts rendered Markdown to a Word Template file (.dotx) suitable for
mail merge by a downstream application.

Merge field syntax
------------------
Use ``[[field_name]]`` in Markdown source to produce a Word MERGEFIELD.
This syntax is intentionally distinct from Jinja2 ``{{ }}`` so both can
coexist in the same document:

    Dear [[contact_name]],

    This is version {{ version }} of our proposal for [[client]].

- ``{{ version }}``     — resolved at build time from _meta.yml / frontmatter
- ``[[contact_name]]``  — becomes a Word «contact_name» MERGEFIELD in the .dotx

``{% include %}`` fragments work normally; the renderer processes them
before this builder runs.

Config keys consumed
--------------------
  title       — cover page heading (may contain [[merge fields]])
  author      — author name (may contain [[merge fields]])
  date        — date string (may contain [[merge fields]])
  product     — product / client subtitle on cover page
  cover_page  — bool (default: true); set false to omit the cover page
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import markdown
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from .docx import (
    _DocxBuilder,
    _MD_EXTENSIONS,
    _extract_title,
    _strip_frontmatter,
    _strip_leading_h1,
)

_MERGE_RE = re.compile(r'\[\[(\w+)\]\]')


# ---------------------------------------------------------------------------
# MERGEFIELD helpers
# ---------------------------------------------------------------------------

def _insert_merge_field(
    paragraph: Any,
    field_name: str,
    *,
    bold: bool = False,
    italic: bool = False,
) -> None:
    """Append a Word MERGEFIELD for *field_name* to *paragraph*."""
    # begin
    run = paragraph.add_run()
    run.bold = bold
    run.italic = italic
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run._r.append(fld_begin)

    # instruction
    run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" MERGEFIELD {field_name} "
    run._r.append(instr)

    # separate
    run = paragraph.add_run()
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    run._r.append(fld_sep)

    # display text (shown in Word before merge is executed)
    run = paragraph.add_run(f"«{field_name}»")
    run.bold = bold
    run.italic = italic

    # end
    run = paragraph.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_end)


def _write_text(
    paragraph: Any,
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
) -> None:
    """Write *text* to *paragraph*, converting ``[[field]]`` to MERGEFIELDs."""
    if not text:
        return
    parts = _MERGE_RE.split(text)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Plain text segment
            if part:
                run = paragraph.add_run(part)
                run.bold = bold
                run.italic = italic
                if code:
                    run.font.name = "Courier New"
                    run.font.size = Pt(9)
        else:
            # Merge field name
            _insert_merge_field(paragraph, part, bold=bold, italic=italic)


# ---------------------------------------------------------------------------
# HTML → docx walker (merge-field aware)
# ---------------------------------------------------------------------------

class _DotxBuilder(_DocxBuilder):
    """
    Extends _DocxBuilder to convert ``[[field]]`` markers to Word MERGEFIELDs.

    Only _add_text and _flush_table are overridden; all structural parsing
    (headings, lists, blockquotes, etc.) is inherited unchanged.
    """

    def _add_text(self, text: str) -> None:
        if not text:
            return
        para = self._current_para()
        _write_text(
            para,
            text,
            bold=self._bold,
            italic=self._italic,
            code=self._in_code,
        )

    def _flush_table(self) -> None:
        rows = getattr(self, "_table_rows", [])
        if not rows:
            return
        max_cols = max(len(r) for r in rows)
        if max_cols == 0:
            return

        table = self.doc.add_table(rows=len(rows), cols=max_cols)
        table.style = "Table Grid"

        for r_idx, row in enumerate(rows):
            for c_idx, (is_header, text) in enumerate(row):
                if c_idx >= max_cols:
                    break
                cell = table.cell(r_idx, c_idx)
                cell.text = ""  # clear default content
                _write_text(cell.paragraphs[0], text.strip(), bold=is_header)

        self._paragraph = None


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------

def _add_cover_page(doc: Document, config: dict[str, Any]) -> None:
    """
    Insert a cover page section followed by a page break.

    All text values may contain ``[[merge_field]]`` markers.
    """
    title = config.get("title", "")
    author = config.get("author", "")
    date = config.get("date", "")
    product = config.get("product", "")

    title_para = doc.add_paragraph(style="Title")
    _write_text(title_para, title or "«Document Title»")

    if product:
        sub_para = doc.add_paragraph(style="Subtitle")
        _write_text(sub_para, product)

    # Metadata block
    if author or date:
        doc.add_paragraph()  # spacer
        if author:
            meta = doc.add_paragraph()
            run = meta.add_run("Prepared by: ")
            run.bold = True
            _write_text(meta, author)
        if date:
            meta = doc.add_paragraph()
            run = meta.add_run("Date: ")
            run.bold = True
            _write_text(meta, date)

    doc.add_page_break()


# ---------------------------------------------------------------------------
# .dotx content-type patch
# ---------------------------------------------------------------------------

def _patch_to_dotx(path: Path) -> None:
    """
    Re-write *path* with the Word Template content type.

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
        # Restore original on failure
        shutil.move(str(tmp), str(path))
        raise
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build(
    rendered_md: str,
    config: dict[str, Any],
    out_path: Path,
    *,
    doc_path: Path | None = None,
) -> None:
    """
    Convert rendered Markdown to a .dotx Word merge template.

    Parameters
    ----------
    rendered_md:
        Jinja2-rendered Markdown string. ``[[field]]`` markers are left
        intact by the renderer and converted to MERGEFIELDs here.
    config:
        Merged config dict from load_config().
    out_path:
        Destination path for the generated .dotx file.
    doc_path:
        Source .md path (unused currently, reserved for future use).
    """
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    body = _strip_frontmatter(rendered_md)
    title: str = config.get("title") or _extract_title(body) or out_path.stem
    author: str = config.get("author", "")
    cover_page: bool = bool(config.get("cover_page", True))

    if cover_page:
        body = _strip_leading_h1(body)

    # Markdown → HTML
    md_engine = markdown.Markdown(extensions=_MD_EXTENSIONS)
    html = md_engine.convert(body)

    # Build document
    doc = Document()

    props = doc.core_properties
    props.title = re.sub(r"\[\[\w+\]\]", "", title).strip()  # strip merge markers for metadata
    if author:
        props.author = re.sub(r"\[\[\w+\]\]", "", author).strip()

    if cover_page:
        _add_cover_page(doc, {**config, "title": title})

    builder = _DotxBuilder(doc)
    builder.feed(html)

    # Save as .docx first (python-docx limitation), then patch content type
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    _patch_to_dotx(out_path)
