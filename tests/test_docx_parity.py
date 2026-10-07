"""Tests for PDF↔Word parity features in the DOCX/DOTX builder.

Covers the features that previously rendered only in PDF: body images,
mermaid diagrams, section heading bars, three-slot footers with page-number
fields, nested-list indentation, and graceful mermaid fallback.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from docx import Document

from md_doc.builders.docx import build


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def _png(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (80, 40), "navy").save(path)


def _build(tmp_repo: Path, body: str, config: dict, fmt: str = "docx") -> Path:
    md = f"---\ntitle: T\n---\n\n{body}"
    doc_path = tmp_repo / "doc.md"
    doc_path.write_text(md, encoding="utf-8")
    out = tmp_repo / f"out.{fmt}"
    build(
        md,
        {"title": "T", "cover_page": False, **config},
        out,
        output_format=fmt,
        doc_path=doc_path,
        repo_root=tmp_repo,
    )
    return out


def _media_names(out: Path) -> list[str]:
    with zipfile.ZipFile(out) as z:
        return [n for n in z.namelist() if n.startswith("word/media/")]


def _part(out: Path, name: str) -> str:
    with zipfile.ZipFile(out) as z:
        return z.read(name).decode("utf-8")


def test_body_image_is_embedded(tmp_repo):
    _png(tmp_repo / "pic.png")
    out = _build(tmp_repo, "Text\n\n![logo](pic.png)\n", {})
    assert len(_media_names(out)) == 1


def test_unresolved_image_falls_back_to_alt_text(tmp_repo):
    out = _build(tmp_repo, "![my alt text](missing.png)\n", {})
    doc = Document(str(out))
    assert any("my alt text" in p.text for p in doc.paragraphs)
    assert _media_names(out) == []


def test_mermaid_diagram_is_rasterized(tmp_repo):
    pytest.importorskip("cairosvg")
    out = _build(tmp_repo, '```mermaid\npie\n"Done" : 100\n```\n', {})
    assert len(_media_names(out)) == 1
    # The diagram source must not leak as literal text.
    assert "language-mermaid" not in _part(out, "word/document.xml")


def test_mermaid_falls_back_to_code_when_no_rasterizer(tmp_repo, monkeypatch):
    import md_doc.builders._assets as assets

    monkeypatch.setattr(assets, "_svg_to_png", lambda *a, **k: None)
    out = _build(tmp_repo, '```mermaid\npie\n"Done" : 100\n```\n', {})
    # No image embedded, but the build still succeeds (renders as a code block).
    assert _media_names(out) == []


def test_section_bar_shades_headings(tmp_repo):
    out = _build(
        tmp_repo,
        "## Heading\n\nBody.\n",
        {"section_bar": True, "section_bar_color": "#123456"},
    )
    assert 'w:fill="123456"' in _part(out, "word/document.xml")


def test_footer_three_slots_and_page_fields(tmp_repo):
    out = _build(
        tmp_repo,
        "Body.\n",
        {
            "footer_left": "Left",
            "footer_center": "Center",
            "footer_right": "Page {page} of {pages}",
        },
    )
    footer = _part(out, "word/footer1.xml")
    assert "Left" in footer and "Center" in footer
    assert "PAGE" in footer and "NUMPAGES" in footer


def test_nested_lists_are_indented(tmp_repo):
    out = _build(
        tmp_repo,
        "- a\n    - b\n        - c\n",
        {},
    )
    doc_xml = _part(out, "word/document.xml")
    # Deeper levels carry explicit left indents.
    assert 'w:left="720"' in doc_xml and 'w:left="1080"' in doc_xml


# ── PDF↔DOCX page-break / structural parity ─────────────────────────────────


def test_appendix_h2_forces_page_break(tmp_repo):
    # APPENDIX section H2s break the page in both PDF and docx (shared markers).
    # The leading "# Doc" title H1 is what _strip_leading_h1 removes, leaving the
    # in-body "# APPENDIX" heading for the appendix-break pass to find.
    with_appendix = _part(
        _build(tmp_repo, "# Doc\n\n## Intro\n\ntext\n\n# APPENDIX\n\n## A1\n\none\n", {}),
        "word/document.xml",
    )
    assert 'w:type="page"' in with_appendix
    without = _part(_build(tmp_repo, "# Doc\n\n## Intro\n\ntext\n", {}), "word/document.xml")
    assert 'w:type="page"' not in without


def test_explicit_pagebreak_marker(tmp_repo):
    xml = _part(_build(tmp_repo, "a\n\n<!-- pagebreak -->\n\nb\n", {}), "word/document.xml")
    assert 'w:type="page"' in xml


def test_headings_keep_with_next(tmp_repo):
    d = Document(str(_build(tmp_repo, "## Heading\n\nbody text\n", {})))
    h = next(p for p in d.paragraphs if p.text == "Heading")
    assert h.paragraph_format.keep_with_next is True


def test_definition_list_renders(tmp_repo):
    d = Document(str(_build(tmp_repo, "Term A\n:   Definition of A\n", {})))
    term = next(p for p in d.paragraphs if p.text == "Term A")
    assert term.runs[0].bold is True
    dd = next(p for p in d.paragraphs if p.text == "Definition of A")
    assert dd.paragraph_format.left_indent is not None


def test_page_geometry_parser():
    from md_doc.builders.docx import _page_geometry

    a4 = _page_geometry("@page { size: A4; margin: 25mm 20mm 22mm 25mm; }")
    assert (a4["w"], a4["h"]) == (210.0, 297.0)
    assert (a4["top"], a4["right"], a4["bottom"], a4["left"]) == (25.0, 20.0, 22.0, 25.0)
    letter = _page_geometry("@page { size: Letter; margin: 1in; }")
    assert (round(letter["w"], 1), round(letter["h"], 1)) == (215.9, 279.4)
    assert round(letter["top"], 1) == 25.4
    assert _page_geometry(None)["w"] == 210.0  # default A4


# ── Parity-review fixes: content fidelity in Word ───────────────────────────


def test_loose_list_keeps_bullets(tmp_repo):
    # Blank lines between items wrap the text in <li><p>…</p></li>; the first
    # <p> must reuse the bullet paragraph, not replace it with a Normal one.
    d = Document(str(_build(tmp_repo, "- alpha\n\n- beta\n", {})))
    bullets = [p for p in d.paragraphs if p.style.name == "List Bullet"]
    assert [p.text for p in bullets] == ["alpha", "beta"]
    # No stray empty bullets, no unbulleted copies of the item text.
    assert not any(p.text in ("alpha", "beta") for p in d.paragraphs if p.style.name == "Normal")


def test_loose_list_continuation_paragraph_is_indented(tmp_repo):
    d = Document(str(_build(tmp_repo, "- alpha\n\n    second para\n", {})))
    bullet = next(p for p in d.paragraphs if p.style.name == "List Bullet")
    assert bullet.text == "alpha"
    cont = next(p for p in d.paragraphs if p.text == "second para")
    assert cont.style.name == "Normal"
    assert cont.paragraph_format.left_indent is not None


def test_internal_links_are_bookmark_jumps(tmp_repo):
    # TOC/anchor links must become w:anchor jumps with NO "(#target)" suffix
    # (the PDF suppresses the URL suffix for fragment links).
    out = _build(tmp_repo, "## My Target\n\nSee [the target](#my-target).\n", {})
    xml = _part(out, "word/document.xml")
    assert 'w:anchor="my_target"' in xml  # sanitized bookmark name
    assert 'w:name="my_target"' in xml  # heading bookmark exists
    assert "(#my-target)" not in xml


def test_footnotes_render_superscript_with_working_links(tmp_repo):
    out = _build(tmp_repo, "Fact.[^1]\n\n[^1]: The footnote text.\n", {})
    xml = _part(out, "word/document.xml")
    # Reference is a superscript bookmark jump, not literal "1 (#fn:1)".
    assert "(#fn" not in xml and "(#fnref" not in xml
    assert 'w:val="superscript"' in xml
    assert 'w:anchor="fn_1"' in xml


def test_sup_sub_strike_runs(tmp_repo):
    out = _build(tmp_repo, "x<sup>2</sup> and H<sub>2</sub>O and <del>gone</del>\n", {})
    d = Document(str(out))
    runs = [r for p in d.paragraphs for r in p.runs]
    assert any(r.text == "2" and r.font.superscript for r in runs)
    assert any(r.text == "2" and r.font.subscript for r in runs)
    assert any(r.text == "gone" and r.font.strike for r in runs)


def test_markdown_column_alignment_in_cells(tmp_repo):
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    body = "| L | C | R |\n|:--|:--:|--:|\n| a | b | c |\n"
    d = Document(str(_build(tmp_repo, body, {})))
    table = d.tables[0]
    assert table.cell(1, 1).paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert table.cell(1, 2).paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT


def test_hyperlink_inside_table_cell(tmp_repo):
    body = "| Link |\n|------|\n| [docs](https://example.com/d) |\n"
    out = _build(tmp_repo, body, {})
    xml = _part(out, "word/document.xml")
    assert "<w:hyperlink" in xml and "docs" in xml
    rels = _part(out, "word/_rels/document.xml.rels")
    assert "https://example.com/d" in rels


def test_table_rows_cant_split_and_code_keeps_lines(tmp_repo):
    body = "| A |\n|---|\n| 1 |\n\n```\ncode line\n```\n"
    out = _build(tmp_repo, body, {})
    xml = _part(out, "word/document.xml")
    assert "<w:cantSplit/>" in xml
    d = Document(str(out))
    code = next(p for p in d.paragraphs if p.text == "code line")
    assert code.paragraph_format.keep_together is True


def test_pdf_theme_override_applies_to_docx(tmp_repo):
    # A --theme/pdf_theme override must restyle Word typography too, not just
    # the PDF, so a single override drives all formats.
    (tmp_repo / "_pdf-theme.css").write_text("h1 { color: #111111; }\n", encoding="utf-8")
    override = tmp_repo / "brand.css"
    override.write_text("h1 { color: #ff00aa; }\n", encoding="utf-8")
    out = _build(tmp_repo, "# Head\n\ntext\n", {"pdf_theme": "brand.css"})
    d = Document(str(out))
    from docx.shared import RGBColor

    h1_style = d.styles["Heading 1"]
    assert h1_style.font.color.rgb == RGBColor(0xFF, 0x00, 0xAA)


def test_cover_matches_pdf_design(tmp_repo):
    # The cover title must be an explicit large bold coloured run (mirroring the
    # PDF's .cover-title) — NOT the built-in serif "Title" style — and the
    # metadata must be colon-free ("Prepared by {author}", not "Prepared by:").
    (tmp_repo / "_pdf-theme.css").write_text(
        "@page { size: A4; margin: 25mm 20mm 22mm 25mm; }\n"
        "body { font-family: Arial; }\n"
        "h1 { color: #1b4f72; }\n"
        "h2 { color: #2e86c1; }\n",
        encoding="utf-8",
    )
    md = "---\ntitle: My Report\n---\n\n# My Report\n\nBody.\n"
    doc_path = tmp_repo / "doc.md"
    doc_path.write_text(md, encoding="utf-8")
    out = tmp_repo / "cover.docx"
    from md_doc.builders.docx import build

    build(
        md,
        {"title": "My Report", "author": "Ada Lovelace", "date": "March 2026", "cover_page": True},
        out,
        output_format="docx",
        doc_path=doc_path,
        repo_root=tmp_repo,
    )
    d = Document(str(out))
    from docx.shared import Pt, RGBColor

    title = next(p for p in d.paragraphs if p.text == "My Report" and p.style.name != "Title")
    trun = title.runs[0]
    assert trun.bold is True
    assert trun.font.size == Pt(24)
    assert trun.font.color.rgb == RGBColor(0x1B, 0x4F, 0x72)  # $primary (color_h1)

    # Metadata carries the author/date with NO colon after the label.
    meta = [p.text for p in d.paragraphs]
    assert "Prepared by Ada Lovelace" in meta
    assert "Date March 2026" in meta
    assert not any(t.startswith("Prepared by:") for t in meta)

    # Footer is a text frame anchored ~14mm from the physical page bottom
    # (matching the PDF's .cover-footer { bottom: 14mm }).
    xml = _part(out, "word/document.xml")
    assert "w:framePr" in xml and 'w:vAnchor="page"' in xml and 'w:y="' in xml
    # The cover bar floats at the physical page top (full-bleed, like the
    # PDF's @page cover { margin: 0 }).
    assert "w:tblpPr" in xml and 'w:tblpYSpec="top"' in xml
    # Headers/footers are suppressed on the cover via "different first page".
    assert "<w:titlePg/>" in xml


def test_docx_page_size_matches_theme(tmp_repo):
    # A Letter-sized PDF theme must produce a Letter-sized docx (not hardcoded A4)
    # so the two formats share text width and pagination.
    (tmp_repo / "_pdf-theme.css").write_text(
        "@page { size: Letter; margin: 25mm 20mm 22mm 25mm; }\nbody { font-family: Arial; }\n",
        encoding="utf-8",
    )
    d = Document(str(_build(tmp_repo, "## S\n\nbody\n", {})))
    section = d.sections[0]
    assert round(section.page_width / 36000, 1) == 215.9  # EMU → mm
    assert round(section.page_height / 36000, 1) == 279.4


def test_h1_page_break_before_from_theme(tmp_repo):
    # The PDF theme forces every report-body H1 onto a new page; the docx
    # builder mirrors that — but never on the first content element (a forced
    # break at the top of a page collapses in CSS).
    (tmp_repo / "_pdf-theme.css").write_text(
        "@page { size: A4; margin: 25mm 20mm 22mm 25mm; }\n"
        "body { font-family: Arial; }\n"
        ".report-body h1 { page-break-before: always; break-before: page; }\n",
        encoding="utf-8",
    )
    out = _build(tmp_repo, "# First\n\ntext\n\n# Second\n\nmore\n", {})
    d = Document(str(out))
    first = next(p for p in d.paragraphs if p.text == "First")
    second = next(p for p in d.paragraphs if p.text == "Second")
    assert first.paragraph_format.page_break_before is not True
    assert second.paragraph_format.page_break_before is True


def test_theme_default_footers_render_in_word(tmp_repo):
    # With no footer_* config, the PDF still renders the theme's @bottom-*
    # margin boxes (org name / running date / page numbers). The docx footer
    # must show the same defaults.
    (tmp_repo / "_pdf-theme.css").write_text(
        "@page { size: A4; margin: 25mm 20mm 22mm 25mm;\n"
        '  @bottom-left { content: "Org Name"; font-size: 7.5pt; color: #7f8c9a; }\n'
        "  @bottom-center { content: string(research-date); }\n"
        '  @bottom-right { content: "Page " counter(page) " of " counter(pages); }\n'
        "}\n"
        "body { font-family: Arial; }\n",
        encoding="utf-8",
    )
    md = "---\ntitle: T\n---\n\n## S\n\nbody\n"
    doc_path = tmp_repo / "doc.md"
    doc_path.write_text(md, encoding="utf-8")
    out = tmp_repo / "out.docx"
    from md_doc.builders.docx import build

    build(
        md,
        {"title": "T", "cover_page": False, "date": "1 May 2026"},
        out,
        doc_path=doc_path,
        repo_root=tmp_repo,
    )
    footer = _part(out, "word/footer1.xml")
    assert "Org Name" in footer
    assert "1 May 2026" in footer  # string(research-date) → document date
    assert "PAGE" in footer and "NUMPAGES" in footer
    # An explicitly configured slot still wins over the CSS default.
    build(
        md,
        {"title": "T", "cover_page": False, "date": "1 May 2026", "footer_left": "Custom"},
        out,
        doc_path=doc_path,
        repo_root=tmp_repo,
    )
    footer = _part(out, "word/footer1.xml")
    assert "Custom" in footer and "Org Name" not in footer


def test_no_cover_keeps_h1_in_body(tmp_repo):
    # cover_page: false leaves the leading H1 in the body as a Heading 1 —
    # exactly what the PDF does — rather than a serif "Title" paragraph.
    d = Document(str(_build(tmp_repo, "# My Doc\n\nbody\n", {})))
    h1 = next(p for p in d.paragraphs if p.text == "My Doc")
    assert h1.style.name == "Heading 1"


def test_keep_with_next_excludes_page_break_divs():
    # A forced page-break div must never be swallowed into the PDF's
    # keep-together wrapper — that strands the heading on its own page and can
    # emit an entirely blank page.
    from md_doc.builders.pdf import _keep_heading_with_next

    html = "<h2>Rollout</h2>\n<p>intro</p>\n" '<div class="md-doc-page-break"></div>\n<p>after</p>'
    result = _keep_heading_with_next(html)
    keep = result.split('<div class="keep-with-next">')[1].split("</div>")[0]
    assert "md-doc-page-break" not in keep


def test_adjacent_tables_stay_separate(tmp_repo):
    # OOXML merges consecutive w:tbl elements into ONE table — Word showed two
    # authored tables (blank line between them) as a single merged block. The
    # builder now inserts a tiny spacer paragraph between adjacent tables.
    body = "| A | B |\n| --- | --- |\n| 1 | 2 |\n" "\n" "| C | D |\n| --- | --- |\n| 3 | 4 |\n"
    out = _build(tmp_repo, body, {})
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    docbody = Document(str(out)).element.body
    tags = [c.tag.replace(ns, "") for c in docbody]
    first, second = [i for i, t in enumerate(tags) if t == "tbl"]
    between = tags[first + 1 : second]
    assert between == ["p"], f"expected one spacer paragraph, got {between}"
    # The spacer is a 2pt paragraph mark, not a visible blank line.
    spacer = docbody[first + 1]
    sz = spacer.find(f"{ns}pPr/{ns}rPr/{ns}sz")
    assert sz is not None and sz.get(f"{ns}val") == "4"
    assert "".join(spacer.itertext()) == ""


def test_three_adjacent_tables_two_spacers(tmp_repo):
    body = "\n\n".join(f"| H{i} |\n| --- |\n| v{i} |" for i in range(3))
    out = _build(tmp_repo, body, {})
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    tags = [c.tag.replace(ns, "") for c in Document(str(out)).element.body]
    tbl_idx = [i for i, t in enumerate(tags) if t == "tbl"]
    assert len(tbl_idx) == 3
    for a, b in zip(tbl_idx, tbl_idx[1:]):
        assert "p" in tags[a + 1 : b], "adjacent tables need a w:p between them"


def test_single_table_gets_no_spacer(tmp_repo):
    out = _build(tmp_repo, "Intro\n\n| A |\n| --- |\n| 1 |\n", {})
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    docbody = Document(str(out)).element.body
    tags = [c.tag.replace(ns, "") for c in docbody]
    tbl = tags.index("tbl")
    # The block right before the table is the intro paragraph, not a spacer.
    prev = docbody[tbl - 1]
    assert "Intro" in "".join(prev.itertext())
    assert prev.find(f"{ns}pPr/{ns}rPr/{ns}sz") is None


def test_footer_never_inherits_justified_body(tmp_repo):
    # A theme with body text-align: justify sets the Normal style to justify;
    # the footer paragraph is positioned by tab stops and must stay explicitly
    # left-aligned or Word stretches the slots across the page width.
    (tmp_repo / "_docx-theme.css").write_text(
        "body { font-family: Calibri; font-size: 10pt; text-align: justify; }\n",
        encoding="utf-8",
    )
    out = _build(
        tmp_repo,
        "Body.\n",
        {"footer_center": "Confidential", "header_text": "Hdr"},
    )
    import re

    styles = _part(out, "word/styles.xml")
    normal = re.search(r'<w:style [^>]*w:styleId="Normal".*?</w:style>', styles, re.S)
    assert '<w:jc w:val="both"/>' in normal.group(0)  # precondition: theme applied
    assert '<w:jc w:val="left"/>' in _part(out, "word/footer1.xml")
    assert '<w:jc w:val="left"/>' in _part(out, "word/header1.xml")
    assert '<w:jc w:val="both"/>' not in _part(out, "word/footer1.xml")


def test_multiline_center_footer_retabs_to_center(tmp_repo):
    # Continuation lines after a soft break must re-tab to their slot's stop —
    # line 2 of a centre slot used to restart at the left margin.
    out = _build(tmp_repo, "Body.\n", {"footer_center": "Line one\nLine two"})
    footer = _part(out, "word/footer1.xml")
    after_break = footer.split("<w:br/>", 1)[1]
    before_line2 = after_break.split("Line two", 1)[0]
    assert "<w:tab/>" in before_line2


def test_page_justify_never_reaches_table_cells(tmp_repo):
    # body_text_align: justify stretched wrapped cell text into rivers of
    # whitespace in narrow columns. Cells now pin to left; body text stays
    # justified; explicit markdown column alignment still wins.
    import re

    body = "Body.\n\n| H | C |\n| --- | :---: |\n| wrapped text | x |\n"
    out = _build(tmp_repo, body, {"body_text_align": "justify"})
    xml = _part(out, "word/document.xml")
    before_tbl, tbl = xml.split("<w:tbl>", 1)
    assert '<w:jc w:val="both"/>' in before_tbl  # body paragraph justified
    cell_jcs = re.findall(r'<w:jc w:val="(\w+)"/>', tbl)
    assert "both" not in cell_jcs
    assert "center" in cell_jcs  # :---: column alignment still applies
    assert "left" in cell_jcs


def test_theme_justify_never_reaches_table_cells(tmp_repo):
    # A theme with body { text-align: justify } justifies Word's Normal style;
    # cell paragraphs would inherit it, so they are pinned left explicitly.
    import re

    (tmp_repo / "_docx-theme.css").write_text(
        "body { font-size: 10pt; text-align: justify; }\n", encoding="utf-8"
    )
    out = _build(tmp_repo, "| A | B |\n| --- | --- |\n| 1 | 2 |\n", {})
    tbl = _part(out, "word/document.xml").split("<w:tbl>", 1)[1]
    cell_jcs = re.findall(r'<w:jc w:val="(\w+)"/>', tbl)
    assert cell_jcs and set(cell_jcs) == {"left"}


def test_empty_header_row_renders_headerless_table(tmp_repo):
    # Markdown requires a header row, so `| | |` is the idiom for a headerless
    # table — the all-empty header row must not render as an empty shaded band.
    out = _build(tmp_repo, "| | |\n| --- | --- |\n| Greg | [[signed]] |\n", {})
    import re

    tbl = _part(out, "word/document.xml").split("<w:tbl>", 1)[1].split("</w:tbl>", 1)[0]
    rows = re.findall(r"<w:tr[ >]", tbl)
    assert len(rows) == 1  # only the data row


def test_footer_header_never_inherit_body_line_spacing(tmp_repo):
    # A theme's line-height/paragraph spacing on Normal made the header and
    # footer containers ~3x taller than their 6-8pt content.
    (tmp_repo / "_docx-theme.css").write_text(
        "body { font-size: 10pt; line-height: 1.6; }\np { margin: 0 0 10pt 0; }\n",
        encoding="utf-8",
    )
    out = _build(tmp_repo, "Body.\n", {"header_text": "H", "footer_center": "F"})
    for part in ("word/footer1.xml", "word/header1.xml"):
        xml = _part(out, part)
        assert 'w:line="240"' in xml  # single spacing, not the theme's 1.6
        assert 'w:before="0"' in xml and 'w:after="0"' in xml


def test_header_footer_distance_from_css(tmp_repo):
    # @page { --docx-header-distance / --docx-footer-distance } set Word's
    # header/footer-from-edge (python-docx defaults both to 12.7mm).
    (tmp_repo / "_docx-theme.css").write_text(
        "@page { size: A4; margin: 24mm 20mm 20mm 25mm;"
        " --docx-header-distance: 8mm; --docx-footer-distance: 6mm; }\n",
        encoding="utf-8",
    )
    out = _build(tmp_repo, "Body.\n", {"header_text": "H", "footer_center": "F"})
    import re

    pgmar = re.search(r"<w:pgMar[^/]*/>", _part(out, "word/document.xml")).group(0)
    header = int(re.search(r'w:header="(\d+)"', pgmar).group(1))
    footer = int(re.search(r'w:footer="(\d+)"', pgmar).group(1))
    assert round(header / 56.7) == 8
    assert round(footer / 56.7) == 6


def test_list_spacing_from_theme_li_rules(tmp_repo):
    # li { margin / line-height } in the theme CSS controls Word's List
    # Bullet/Number style spacing — previously bullets inherited Normal's
    # paragraph spacing and line height, so lists couldn't be tightened.
    import re

    (tmp_repo / "_docx-theme.css").write_text(
        "body { font-size: 10pt; line-height: 1.6; }\n"
        "p { margin: 0 0 10pt 0; }\n"
        "li { margin: 0 0 2pt 0; line-height: 1.2; }\n",
        encoding="utf-8",
    )
    out = _build(tmp_repo, "- alpha\n- beta\n\n1. one\n2. two\n", {})
    styles = _part(out, "word/styles.xml")
    for sid in ("ListBullet", "ListNumber"):
        block = re.search(rf'<w:style [^>]*w:styleId="{sid}".*?</w:style>', styles, re.S)
        assert block, f"{sid} style missing"
        spacing = block.group(0)
        assert 'w:after="40"' in spacing  # 2pt
        assert 'w:line="240"' in spacing  # 10pt × 1.2 = 12pt leading
        assert 'w:lineRule="atLeast"' in spacing


def test_page_geometry_survives_nested_margin_boxes():
    # WeasyPrint themes nest @top-*/@bottom-* boxes inside @page; margins
    # declared after a nested box were silently dropped in Word (the naive
    # regex truncated at the first inner brace) — the PDF read them fine.
    from md_doc.builders.docx import _page_geometry

    css = (
        "@page {\n  size: A4;\n"
        '  @top-right { content: url("logo.png"); }\n'
        '  @bottom-center { content: "Page " counter(page); }\n'
        "  margin: 25mm 20mm 20mm 25mm;\n"
        "  --docx-footer-distance: 6mm;\n}\n"
    )
    g = _page_geometry(css)
    assert (g["top"], g["right"], g["bottom"], g["left"]) == (25.0, 20.0, 20.0, 25.0)
    assert g.get("footer_distance") == 6.0


def test_source_soft_wraps_do_not_create_word_line_breaks(tmp_repo):
    out = _build(
        tmp_repo,
        "First soft\nwrapped paragraph.\n\nExplicit  \nbreak.\n\n<table><tr><td>soft\nwrap</td></tr></table>",
        {},
    )
    paragraphs = Document(out).paragraphs
    assert any(p.text == "First soft wrapped paragraph." for p in paragraphs)
    assert any(p.text == "Explicit\nbreak." for p in paragraphs)
    assert Document(out).tables[0].cell(0, 0).text == "soft wrap"


@pytest.mark.parametrize("fmt", ["docx", "dotx"])
def test_word_form_grids_preserve_columns_widths_and_labels(tmp_repo, fmt):
    body = "?[row]\n**City** ?[text: city] | **Post code** ?[text: postcode]\n?[/row]\n\n?[box: widths=70,30]\nQuestion | Response\nNeed cover? | ?[yesno: cover]\n?[/box]"
    out = _build(tmp_repo, body, {}, fmt)
    xml = _part(out, "word/document.xml")
    assert xml.count("<w:tbl>") == 2
    assert "City" in xml and "Post code" in xml and "Yes" in xml and "No" in xml
    assert 'w:val="nil"' in xml and 'w:val="single"' in xml
    if fmt == "dotx":
        assert "FORMTEXT" in xml and xml.count("FORMCHECKBOX") == 2
    assert "?[" not in xml


def test_docx_form_choices_and_values_are_not_lost(tmp_repo):
    out = _build(
        tmp_repo,
        "?[checkbox: agree, label=I agree]\n\n?[radio-inline: contact | Email | Phone]\n\n?[text: name, value=Alice]",
        {},
    )
    xml = _part(out, "word/document.xml")
    assert all(text in xml for text in ("I agree", "Email", "Phone", "Alice", "☐", "○"))


@pytest.mark.parametrize("fmt", ["docx", "dotx"])
def test_raw_html_form_controls_are_not_dropped(tmp_repo, fmt):
    out = _build(
        tmp_repo,
        '<p>Name <input name="name" value="Alice"></p>\n<p><input type="checkbox" name="agree"> Agree</p>\n<p><select name="region"><option>North &amp; East</option><option>South</option></select></p>\n<p><textarea name="comments">Notes</textarea></p>',
        {},
        fmt,
    )
    xml = _part(out, "word/document.xml")
    if fmt == "docx":
        assert "Alice" in xml and "☐" in xml and "North &amp; East" in xml and "Notes" in xml
    else:
        assert all(field in xml for field in ("FORMTEXT", "FORMCHECKBOX", "FORMDROPDOWN"))
        assert 'w:val="North &amp; East"' in xml


def test_separate_numbered_lists_restart_and_preserve_explicit_start(tmp_repo):
    out = _build(
        tmp_repo,
        '1. First\n2. Second\n\nParagraph\n\n1. Another\n\n<ol start="5"><li>Fifth</li></ol>',
        {},
    )
    doc = Document(out)
    ids = [p._p.pPr.numPr.numId.val for p in doc.paragraphs if p.style.name == "List Number"]
    assert ids[0] == ids[1] and len(set(ids)) == 3
    assert 'w:val="5"' in _part(out, "word/numbering.xml")


def test_table_line_spacing_uses_cell_font_size_without_clipping(tmp_repo):
    from docx.enum.text import WD_LINE_SPACING

    (tmp_repo / "_theme.css").write_text(
        "body { font-size: 11pt; line-height: 1.5; } td { font-size: 9pt; } th { font-size: 8pt; }"
    )
    out = _build(tmp_repo, "| A | B |\n| --- | --- |\n| One | Two |", {})
    table = Document(out).tables[0]
    assert table.cell(0, 0).paragraphs[0].paragraph_format.line_spacing.pt == 12
    assert table.cell(1, 0).paragraphs[0].paragraph_format.line_spacing.pt == 13.5
    assert (
        table.cell(1, 0).paragraphs[0].paragraph_format.line_spacing_rule
        == WD_LINE_SPACING.AT_LEAST
    )


def test_list_line_spacing_matches_css_leading(tmp_repo):
    from docx.enum.text import WD_LINE_SPACING

    (tmp_repo / "_theme.css").write_text("body { font-size: 10pt; } li { line-height: 1.6; }")
    out = _build(tmp_repo, "- One\n- Two", {})
    style = Document(out).styles["List Bullet"].paragraph_format
    assert style.line_spacing.pt == 16
    assert style.line_spacing_rule == WD_LINE_SPACING.AT_LEAST
