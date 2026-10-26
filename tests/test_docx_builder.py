"""Tests for the DOCX/DOTX builder — table column width config."""

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from md_doc.builders.docx import build


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def _build_docx(tmp_repo: Path, body: str, config: dict, fmt: str = "docx") -> Document:
    md = f"---\ntitle: Test\noutputs: [{fmt}]\n---\n\n{body}"
    out = tmp_repo / f"out.{fmt}"
    build(md, {"title": "Test", "cover_page": False, **config}, out, output_format=fmt)
    if fmt == "dotx":
        from io import BytesIO
        import zipfile

        buffer = BytesIO()
        with zipfile.ZipFile(out) as source, zipfile.ZipFile(buffer, "w") as target:
            for entry in source.infolist():
                data = source.read(entry.filename)
                if entry.filename == "[Content_Types].xml":
                    data = data.replace(
                        b"wordprocessingml.template.main+xml", b"wordprocessingml.document.main+xml"
                    )
                target.writestr(entry, data)
        buffer.seek(0)
        return Document(buffer)
    return Document(str(out))


def _col_widths(doc: Document) -> list[int]:
    """Return gridCol w values from the first table."""
    tbl = doc.tables[0]._tbl
    grid = tbl.find(qn("w:tblGrid"))
    if grid is None:
        return []
    return [int(gc.get(qn("w:w"), 0)) for gc in grid.findall(qn("w:gridCol"))]


class TestTableColWidths:
    def test_default_widths_follow_content(self, tmp_repo):
        doc = _build_docx(
            tmp_repo,
            "| ID | Description |\n|---|---|\n| 1 | A much longer description |\n",
            {},
        )
        widths = _col_widths(doc)
        assert len(widths) == 2
        assert widths[1] > widths[0]

    def test_identical_content_gets_equal_default_widths(self, tmp_repo):
        doc = _build_docx(tmp_repo, "| A | A |\n|---|---|\n| 1 | 1 |\n", {})
        widths = _col_widths(doc)
        assert len(widths) == 2
        assert abs(widths[0] - widths[1]) <= 1  # rounding tolerance of 1 twip

    def test_custom_col_widths_applied(self, tmp_repo):
        doc = _build_docx(
            tmp_repo, "| A | B |\n|---|---|\n| 1 | 2 |\n", {"table_col_widths": [30, 70]}
        )
        widths = _col_widths(doc)
        assert len(widths) == 2
        # 30:70 ratio — second column should be more than twice the first
        assert widths[1] > widths[0] * 2

    def test_col_widths_sum_to_text_width(self, tmp_repo):
        doc = _build_docx(
            tmp_repo, "| A | B |\n|---|---|\n| 1 | 2 |\n", {"table_col_widths": [40, 60]}
        )
        widths = _col_widths(doc)
        tbl = doc.tables[0]._tbl
        tblPr = tbl.find(qn("w:tblPr"))
        tblW = tblPr.find(qn("w:tblW"))
        total_declared = int(tblW.get(qn("w:w"), 0))
        assert sum(widths) == total_declared

    def test_mismatched_col_widths_falls_back_to_equal(self, tmp_repo):
        # [30, 70] has 2 values but table has 3 columns — falls back to equal
        doc = _build_docx(
            tmp_repo,
            "| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n",
            {"table_col_widths": [30, 70]},
        )
        widths = _col_widths(doc)
        assert len(widths) == 3
        assert abs(widths[0] - widths[1]) <= 1
        assert abs(widths[1] - widths[2]) <= 1

    def test_cell_widths_match_grid(self, tmp_repo):
        doc = _build_docx(
            tmp_repo, "| A | B |\n|---|---|\n| 1 | 2 |\n", {"table_col_widths": [30, 70]}
        )
        grid_widths = _col_widths(doc)
        table = doc.tables[0]
        for row in table.rows:
            for c_idx, cell in enumerate(row.cells):
                tcPr = cell._tc.find(qn("w:tcPr"))
                tcW = tcPr.find(qn("w:tcW"))
                assert int(tcW.get(qn("w:w"))) == grid_widths[c_idx]

    def test_only_one_tblgrid(self, tmp_repo):
        """Fixed layout must not have duplicate tblGrid elements."""
        doc = _build_docx(tmp_repo, "| A | B |\n|---|---|\n| 1 | 2 |\n", {})
        tbl = doc.tables[0]._tbl
        grids = tbl.findall(qn("w:tblGrid"))
        assert len(grids) == 1

    def test_short_rows_all_cells_get_tcW(self, tmp_repo):
        """Rows with fewer cells than max_cols must still have explicit tcW on all cells."""
        # Row 1 has 3 cols, row 2 has 2 cols — the 3rd cell in row 2 must still get tcW
        body = "| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n| x | y |\n"
        doc = _build_docx(tmp_repo, body, {})
        table = doc.tables[0]
        for row in table.rows:
            for cell in row.cells:
                tcPr = cell._tc.find(qn("w:tcPr"))
                assert tcPr is not None
                tcW = tcPr.find(qn("w:tcW"))
                assert tcW is not None, "Every cell must have explicit tcW for fixed layout"
                assert int(tcW.get(qn("w:w"))) > 0


class TestColWidthsComment:
    def test_comment_sets_widths_for_that_table(self, tmp_repo):
        body = "<!-- col-widths: 30, 70 -->\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        doc = _build_docx(tmp_repo, body, {})
        widths = _col_widths(doc)
        assert len(widths) == 2
        assert widths[1] > widths[0] * 2

    def test_comment_only_applies_to_next_table(self, tmp_repo):
        second_table = "| Description | ID |\n|---|---|\n| A much longer description | 4 |\n"
        body = "<!-- col-widths: 30, 70 -->\n| A | B |\n|---|---|\n| 1 | 2 |\n\n" + second_table
        doc = _build_docx(tmp_repo, body, {})

        def grid_widths(table_idx):
            tbl = doc.tables[table_idx]._tbl
            grid = tbl.find(qn("w:tblGrid"))
            return [int(gc.get(qn("w:w"), 0)) for gc in grid.findall(qn("w:gridCol"))]

        w1 = grid_widths(0)
        w2 = grid_widths(1)
        # First table: 30/70 split
        assert w1[1] > w1[0] * 2
        # The second table uses its own content, exactly as it does in isolation.
        assert w2[0] > w2[1]
        assert w2 == _col_widths(_build_docx(tmp_repo, second_table, {}))

    def test_comment_overrides_config_widths(self, tmp_repo):
        body = "<!-- col-widths: 60, 40 -->\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        doc = _build_docx(tmp_repo, body, {"table_col_widths": [30, 70]})
        widths = _col_widths(doc)
        # Comment says 60/40, config says 30/70 — comment wins, so first >= second
        assert widths[0] > widths[1]


class TestMergeFieldsInTableCells:
    def _dotx_xml(self, path: Path) -> str:
        import zipfile

        with zipfile.ZipFile(path) as zf:
            return zf.read("word/document.xml").decode("utf-8")

    def test_form_field_in_cell_creates_word_field(self, tmp_repo):
        body = "| Label | Value |\n|---|---|\n| Client | [[contact_name]] |\n"
        out = tmp_repo / "out.dotx"
        from md_doc.builders.docx import build

        build(
            "---\ntitle: T\n---\n\n" + body,
            {"title": "T", "cover_page": False},
            out,
            output_format="dotx",
        )
        xml = self._dotx_xml(out)
        assert "fldChar" in xml or "bookmarkStart" in xml

    def test_form_field_not_left_as_literal_text(self, tmp_repo):
        body = "| Label | Value |\n|---|---|\n| Client | [[contact_name]] |\n"
        out = tmp_repo / "out.dotx"
        from md_doc.builders.docx import build

        build(
            "---\ntitle: T\n---\n\n" + body,
            {"title": "T", "cover_page": False},
            out,
            output_format="dotx",
        )
        xml = self._dotx_xml(out)
        assert "[[contact_name]]" not in xml

    def test_merge_field_in_cell(self, tmp_repo):
        body = "| Label | Value |\n|---|---|\n| Client | [[contact_name]] |\n"
        out = tmp_repo / "out.dotx"
        from md_doc.builders.docx import build

        build(
            "---\ntitle: T\n---\n\n" + body,
            {"title": "T", "cover_page": False, "dotx_field_type": "merge"},
            out,
            output_format="dotx",
        )
        xml = self._dotx_xml(out)
        assert "MERGEFIELD" in xml


@pytest.mark.parametrize("marker", ["-", "1."])
def test_callout_lists_keep_box_and_indentation(marker):
    from md_doc.builders.docx import _DocxBuilder

    builder = _DocxBuilder(
        Document(),
        theme={"blockquote_background_color": "#eeeeee", "blockquote_border_color": "#123456"},
    )
    # Tight, loose, nested and continuation paragraphs must all stay in the box.
    builder.feed(
        f'<blockquote><p>Intro</p><{"ul" if marker == "-" else "ol"}>'
        "<li>First</li><li><p>Second</p><p>Continuation</p>"
        "<ul><li>Nested</li></ul></li>"
        f'</{"ul" if marker == "-" else "ol"}></blockquote><p>Outside</p>'
    )
    paragraphs = {p.text: p for p in builder.doc.paragraphs}
    for text in ("Intro", "First", "Second", "Continuation", "Nested"):
        p = paragraphs[text]
        assert p._p.find(".//" + qn("w:shd")).get(qn("w:fill")) == "EEEEEE"
        assert len(p._p.findall(".//" + qn("w:pBdr"))) == 1
    assert paragraphs["First"].style.name == ("List Bullet" if marker == "-" else "List Number")
    assert (
        paragraphs["Second"].paragraph_format.left_indent
        == paragraphs["Continuation"].paragraph_format.left_indent
    )
    assert (
        paragraphs["Nested"].paragraph_format.left_indent
        > paragraphs["First"].paragraph_format.left_indent
    )
    assert paragraphs["Outside"]._p.find(".//" + qn("w:shd")) is None


@pytest.mark.parametrize("fmt", ["docx", "dotx"])
def test_callout_color_override_is_local(tmp_repo, fmt):
    doc = _build_docx(
        tmp_repo,
        """<blockquote markdown="1" style="background-color: #fef3c7; border-left-color: #d90">

- Coloured item

</blockquote>

Outside

> Default quote
""",
        {},
        fmt,
    )
    item = next(p for p in doc.paragraphs if p.text == "Coloured item")
    assert item._p.find(".//" + qn("w:shd")).get(qn("w:fill")) == "FEF3C7"
    assert item._p.find(".//" + qn("w:left")).get(qn("w:color")) == "DD9900"
    default = next(p for p in doc.paragraphs if p.text == "Default quote")
    shading = default._p.find(".//" + qn("w:shd"))
    assert shading is None or shading.get(qn("w:fill")) != "FEF3C7"


class TestComponentsInWord:
    def test_callouts_are_shaded_with_coloured_rule(self, tmp_repo):
        doc = _build_docx(tmp_repo, "::: must\nAct now.\n:::\n\n::: may\nOr not.\n:::\n", {})
        xml = doc.element.xml.upper()
        assert 'W:FILL="FDECEB"' in xml and 'W:COLOR="C0392B"' in xml
        assert 'W:FILL="E7F4EC"' in xml and "MUST" in xml

    def test_rings_figure_is_embedded_as_picture(self, tmp_repo):
        doc = _build_docx(tmp_repo, "::: rings\ncaption: Figure 1.2 Test\n:::\n", {})
        assert doc.inline_shapes
        assert any("Figure 1.2 Test" in p.text for p in doc.paragraphs)

    def test_toc_becomes_word_field_with_title(self, tmp_repo):
        doc = _build_docx(
            tmp_repo,
            "[TOC]\n\n## One\n\ntext\n",
            {"toc_title": "Contents", "toc_depth": 2},
        )
        xml = doc.element.xml
        assert "TOC \\o" in xml and '"1-2"' in xml
        assert any(p.text == "Contents" for p in doc.paragraphs)
        assert doc.settings.element.find(qn("w:updateFields")) is not None

    def test_bullet_style_sets_picture_bullet(self, tmp_repo):
        doc = _build_docx(
            tmp_repo, "- a\n- b\n", {"bullet_style": "leaf", "bullet_color": "#5ab379"}
        )
        numbering = doc.part.numbering_part.element
        assert numbering.find(qn("w:numPicBullet")) is not None
        assert numbering.xpath("//w:lvlPicBulletId")


def test_cover_subtitle_and_version_in_word(tmp_repo):
    doc = _build_docx(
        tmp_repo,
        "# Heading\n\ntext\n",
        {
            "cover_page": True,
            "cover_subtitle": "A subtitle",
            "cover_version": "Version 2.0",
            "cover_date": False,
        },
    )
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "A subtitle" in text and "Version 2.0" in text
    assert "Date" not in text


class TestCaptionListsInWord:
    def test_lists_become_fields_and_captions_are_styled(self, tmp_repo):
        doc = _build_docx(
            tmp_repo,
            "::: list-of\nfigures\n:::\n\n::: list-of\ntables\n:::\n\n"
            "::: tiers\ncaption: 'Figure 1.1: Structure'\n:::\n\nTable 2.1: Things\n\n| A |\n|---|\n| 1 |\n",
            {},
        )
        xml = doc.element.xml
        assert 'TOC \\h \\z \\t "Figure Caption,1"' in xml
        assert 'TOC \\h \\z \\t "Table Caption,1"' in xml
        styles = {p.text: p.style.name for p in doc.paragraphs}
        assert styles["Figure 1.1: Structure"] == "Figure Caption"
        assert styles["Table 2.1: Things"] == "Table Caption"
        assert "@@" not in xml

    @pytest.mark.parametrize("name", ["tiers", "cards", "matrix", "process", "flow"])
    def test_each_diagram_is_embedded_as_a_picture(self, tmp_repo, name):
        doc = _build_docx(tmp_repo, f"::: {name}\n:::\n", {})
        assert len(doc.inline_shapes) == 1


def test_cover_subtitle_detail_and_stripe_text(tmp_repo):
    doc = _build_docx(
        tmp_repo,
        "# Title\n\nBody.\n",
        {
            "cover_page": True,
            "cover_bar": False,
            "author": "Jane Author",
            "cover_meta_label": "",
            "cover_subtitle": "A study of things",
            "cover_meta_detail": "Line one\nLine two",
            "cover_stripe": True,
            "cover_stripe_text": "Jane Author",
            "cover_stripe_color": "#1e4632",
        },
    )
    texts = [p.text for p in doc.paragraphs]
    assert "A study of things" in texts
    # Empty meta label: the author line has no leading label run.
    assert "Jane Author" in texts
    author_i = texts.index("Jane Author")
    assert texts[author_i + 1 : author_i + 3] == ["Line one", "Line two"]

    stripe = doc.tables[0]
    cell = stripe.rows[0].cells[0]
    tc_pr = cell._tc.tcPr
    assert tc_pr.find(qn("w:textDirection")).get(qn("w:val")) == "btLr"
    assert tc_pr.find(qn("w:shd")).get(qn("w:fill")).upper() == "1E4632"
    assert cell.paragraphs[0].text == "Jane Author"


def test_table_font_family_from_theme(tmp_repo):
    from md_doc.builders.docx import build as build_docx

    (tmp_repo / "_theme.css").write_text(
        "body { font-family: 'DejaVu Serif'; }\ntable { font-family: 'DejaVu Sans', sans-serif; }\n",
        encoding="utf-8",
    )
    doc_path = tmp_repo / "d.md"
    md = "---\ntitle: T\n---\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    doc_path.write_text(md, encoding="utf-8")
    out = tmp_repo / "d.docx"
    build_docx(
        md,
        {"title": "T", "cover_page": False},
        out,
        output_format="docx",
        doc_path=doc_path,
        repo_root=tmp_repo,
    )
    doc = Document(str(out))
    cell_runs = [
        r for row in doc.tables[0].rows for c in row.cells for p in c.paragraphs for r in p.runs
    ]
    assert cell_runs and all(r.font.name == "DejaVu Sans" for r in cell_runs)
    body = [p for p in doc.paragraphs if p.runs]
    assert all(r.font.name != "DejaVu Sans" for p in body for r in p.runs)


def _build_with_theme(tmp_repo, css: str, body: str) -> Document:
    from md_doc.builders.docx import build as build_docx

    (tmp_repo / "_theme.css").write_text(css, encoding="utf-8")
    doc_path = tmp_repo / "d.md"
    md = f"---\ntitle: T\n---\n\n{body}"
    doc_path.write_text(md, encoding="utf-8")
    out = tmp_repo / "d.docx"
    build_docx(
        md,
        {"title": "T", "cover_page": False},
        out,
        output_format="docx",
        doc_path=doc_path,
        repo_root=tmp_repo,
    )
    return Document(str(out))


def test_paragraph_class_becomes_word_style(tmp_repo):
    css = (
        "body { font-size: 10pt; }\n"
        ".report-body p.byline { font-family: 'DejaVu Sans'; font-size: 8pt; color: #5c5c58;"
        " margin: 0 0 9mm 0; }\n"
        "p.summary { font-weight: 600; }\n"
        ".cover-title { font-size: 30pt; }\n"
    )
    doc = _build_with_theme(
        tmp_repo, css, "Jane\n{: .byline }\n\nBold summary.\n{: .summary }\n\nPlain.\n"
    )
    by_text = {p.text: p for p in doc.paragraphs}
    byline = by_text["Jane"].style
    assert byline.name == "byline"
    assert byline.font.size.pt == 8
    assert byline.font.name == "DejaVu Sans"
    assert str(byline.font.color.rgb) == "5C5C58"
    assert round(byline.paragraph_format.space_after.mm) == 9
    assert by_text["Bold summary."].style.name == "summary"
    assert by_text["Bold summary."].style.font.bold is True
    assert by_text["Plain."].style.name == "Normal"
    # Only p.class rules become styles.
    assert "cover-title" not in [s.name for s in doc.styles]


def test_book_indent_follows_pdf_rule(tmp_repo):
    css = "p { margin: 0; }\n.report-body p + p { text-indent: 10pt; }\n"
    body = "## Heading\n\nFirst.\n\nSecond.\n\n> Quote.\n\nAfter quote.\n\nNext.\n"
    doc = _build_with_theme(tmp_repo, css, body)
    indent = {
        p.text: (
            p.paragraph_format.first_line_indent.pt if p.paragraph_format.first_line_indent else 0
        )
        for p in doc.paragraphs
    }
    assert indent["First."] == 0
    assert indent["Second."] == 10
    assert indent["Quote."] == 0
    assert indent["After quote."] == 0
    assert indent["Next."] == 10


def test_no_indent_without_rule(tmp_repo):
    doc = _build_with_theme(tmp_repo, "p { margin: 0; }\n", "One.\n\nTwo.\n")
    assert all(p.paragraph_format.first_line_indent is None for p in doc.paragraphs)


_RULED_PAGE = """
@page {
  size: A4;
  margin: 33mm 36mm 24mm 36mm;
  --docx-header-distance: 12mm;
  @top-left { content: ""; border-bottom: 1pt solid #1e4632; margin-bottom: 9mm; }
  @bottom-right { content: counter(page); font-size: 7.5pt; color: #5c5c58; }
}
"""


def test_header_rule_and_footer_border_follow_theme(tmp_repo):
    doc = _build_with_theme(tmp_repo, _RULED_PAGE, "Body.\n")
    section = doc.sections[0]
    header_p = section.header.paragraphs[0]
    bottom = header_p._p.pPr.find(qn("w:pBdr")).find(qn("w:bottom"))
    assert bottom.get(qn("w:color")) == "1e4632"
    assert bottom.get(qn("w:sz")) == "8"
    # Rule sits 9mm above the 33mm top margin: 33 - 12 (header distance) - 9 = 12mm.
    assert round(header_p.paragraph_format.line_spacing.mm) == 12
    # Footer boxes without border-top: no rule above the footer.
    footer_p = section.footer.paragraphs[0]
    pbdr = footer_p._p.pPr.find(qn("w:pBdr"))
    assert pbdr is None or pbdr.find(qn("w:top")) is None


def test_footer_keeps_default_hairline_without_theme_boxes(tmp_repo):
    doc = _build_with_theme(tmp_repo, "body {}\n", "Body.\n")
    footer = doc.sections[0].footer
    # No footer content configured → no footer paragraph styling to check;
    # with footer_right set, the default hairline is kept.
    from md_doc.builders.docx import build as build_docx

    md = "---\ntitle: T\n---\n\nBody.\n"
    out = tmp_repo / "f.docx"
    build_docx(
        md,
        {"title": "T", "cover_page": False, "footer_right": "x"},
        out,
        output_format="docx",
        doc_path=tmp_repo / "d.md",
        repo_root=tmp_repo,
    )
    para = Document(str(out)).sections[0].footer.paragraphs[0]
    top = para._p.pPr.find(qn("w:pBdr")).find(qn("w:top"))
    assert top.get(qn("w:color")) == "d5d8dc"
    assert footer is not None


def test_page_footnotes_are_real_word_footnotes(tmp_repo):
    import zipfile

    body = (
        "Claim one.[^a] Claim *two*.[^b]\n\n| Col |\n|---|\n| In table[^c] |\n\n"
        "[^a]: First *note*.\n[^b]: Second note.\n[^c]: Table note.\n"
    )
    doc = _build_docx(tmp_repo, body, {"page_footnotes": True})
    out = tmp_repo / "out.docx"
    with zipfile.ZipFile(out) as z:
        notes = z.read("word/footnotes.xml").decode()
        document = z.read("word/document.xml").decode()
        settings = z.read("word/settings.xml").decode()
    assert document.count("<w:footnoteReference") == 3
    for text in ("First ", "note", "Second note.", "Table note."):
        assert text in notes
    assert "w:footnotePr" in settings
    # The end-of-document list is gone.
    assert not any("Second note." in p.text for p in doc.paragraphs)


def test_end_footnotes_keep_the_list(tmp_repo):
    import zipfile

    doc = _build_docx(tmp_repo, "Claim.[^a]\n\n[^a]: The note.\n", {})
    with zipfile.ZipFile(tmp_repo / "out.docx") as z:
        assert "word/footnotes.xml" not in z.namelist()
    assert any("The note." in p.text for p in doc.paragraphs)
