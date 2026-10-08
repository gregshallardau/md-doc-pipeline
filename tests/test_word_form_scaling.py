"""Word form geometry follows the theme's font sizes and the PDF's form styling."""

from __future__ import annotations

import zipfile
from pathlib import Path

from md_doc.builders.docx import _add_simple_field, _compute_form_dims, build
from md_doc.builders.pdf import form_rule_colors


def test_form_dims_scale_with_theme_fonts() -> None:
    base = _compute_form_dims({})
    big = _compute_form_dims({"font_size_table": 19.0, "font_size_body": 21.0})
    assert big["line"] == base["line"]  # WeasyPrint's input box is a fixed height
    assert big["relief"] == base["relief"] * 2  # descent follows the body font
    assert big["cell_input"] == base["cell_input"] * 2
    assert big["choice_line"] == base["choice_line"] * 2


def test_form_dims_use_theme_margins_and_textarea_min() -> None:
    dims = _compute_form_dims(
        {"form_input": {"margin_top": 4.0, "margin_bottom": 12.0, "textarea_min": 60.0}}
    )
    assert (dims["margin_top"], dims["margin_bottom"], dims["textarea_min"]) == (4.0, 12.0, 60.0)


def test_form_rule_colors_derive_from_primary_with_neutral_fallback() -> None:
    label, rule, soft = form_rule_colors("#1b4f72")
    assert label == "#1b4f72" and rule != soft
    assert form_rule_colors(None)[0] == "#2c3e50"
    assert form_rule_colors("not-a-colour")[0] == "#2c3e50"


def test_page_number_field_returns_every_run_for_styling() -> None:
    from docx import Document

    paragraph = Document().add_paragraph()
    runs = _add_simple_field(paragraph, "PAGE")
    assert len(runs) == 5


def test_form_document_word_footer_hides_running_date_and_grid_uses_theme_tint(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "_theme.css").write_text(
        "h1 { color: #1b4f72; }\n" "@page { @bottom-center { content: string(running-date); } }\n"
    )
    body = "?[box]\n**Name** ?[text: n]\n?[/box]\n"
    md = f"---\ntitle: T\n---\n\n{body}"
    doc = tmp_path / "f.md"
    doc.write_text(md)
    out = tmp_path / "f.docx"
    build(
        md,
        {"title": "T", "cover_page": False, "pdf_forms": True, "date": "1 April 2026"},
        out,
        doc_path=doc,
        repo_root=tmp_path,
    )
    with zipfile.ZipFile(out) as z:
        document = z.read("word/document.xml").decode()
        footers = "".join(z.read(n).decode() for n in z.namelist() if "footer" in n)
    assert "1 April 2026" not in footers
    assert 'w:color="000000"' not in document.split("<w:tblBorders>")[1].split("</w:tblBorders>")[0]


def test_css_row_heights_follow_theme_font(tmp_path: Path) -> None:
    from md_doc.builders.pdf import _expand_box_block
    from md_doc.table_layout import css_row_heights

    html = _expand_box_block(None, "**A** ?[text: a]\nQ | ?[yesno: y]")
    heights = []
    for size in (8, 16):
        css = tmp_path / f"t{size}.css"
        css.write_text(f"table {{ font-size: {size}pt; border-collapse: collapse; }}")
        found = css_row_heights(html, css, 450)
        assert found is not None and len(found) == 2
        heights.append(found)
    assert all(big > small for big, small in zip(heights[1], heights[0], strict=True))


def test_form_table_rows_carry_pdf_row_heights(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "_theme.css").write_text("table { font-size: 9.5pt; border-collapse: collapse; }")
    body = "?[box]\n**Name** ?[text: n]\nQ | ?[yesno: y]\n?[/box]\n"
    md = f"---\ntitle: T\n---\n\n{body}"
    doc = tmp_path / "f.md"
    doc.write_text(md)
    out = tmp_path / "f.docx"
    build(
        md,
        {"title": "T", "cover_page": False, "pdf_forms": True},
        out,
        doc_path=doc,
        repo_root=tmp_path,
    )
    with zipfile.ZipFile(out) as z:
        document = z.read("word/document.xml").decode()
    assert document.count('w:hRule="atLeast"') >= 2


def _word_xml(tmp_path: Path, body: str) -> str:
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / "_theme.css").write_text("table { font-size: 9.5pt; border-collapse: collapse; }")
    md = f"---\ntitle: T\n---\n\n{body}"
    doc = tmp_path / "f.md"
    doc.write_text(md)
    out = tmp_path / "f.docx"
    build(
        md,
        {"title": "T", "cover_page": False, "pdf_forms": True},
        out,
        doc_path=doc,
        repo_root=tmp_path,
    )
    with zipfile.ZipFile(out) as z:
        return z.read("word/document.xml").decode()


def test_standalone_signature_gets_caption_and_em_scaled_line(tmp_path: Path) -> None:
    xml = _word_xml(tmp_path, "Sign below.\n\n?[signature: sig]\n")
    assert "SIGNATURE" in xml
    assert 'w:color="555555"' in xml  # the PDF's rule colour


def test_signature_row_uses_rule_leader_and_captions(tmp_path: Path) -> None:
    xml = _word_xml(tmp_path, "?[row]\n?[signature: sig] | **Date** ?[date: d]\n?[/row]\n")
    assert 'w:leader="underscore"' in xml
    assert "SIGNATURE" in xml and "DATE" in xml
