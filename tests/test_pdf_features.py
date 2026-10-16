"""WeasyPrint features exposed through config keys (md_doc/pdf_features.py)."""

from __future__ import annotations

import logging
import re
from types import SimpleNamespace

import pytest

from md_doc import pdf_features as pf
from md_doc.builders import pdf

weasyprint = pytest.importorskip("weasyprint")


@pytest.fixture()
def render(tmp_path, monkeypatch):
    """Build Markdown to a real PDF and expose the HTML, Document and bytes."""
    (tmp_path / ".git").mkdir()
    captured: dict = {}
    real_write = pdf._write_pdf
    real_render = weasyprint.HTML.render

    def spy_write(html, base_url, out_path, options):
        captured["html"] = html
        captured["options"] = options
        real_write(html, base_url, out_path, options)

    def spy_render(self, *args, **kwargs):
        document = real_render(self, *args, **kwargs)
        captured["document"] = document
        return document

    monkeypatch.setattr(pdf, "_write_pdf", spy_write)
    monkeypatch.setattr(weasyprint.HTML, "render", spy_render)

    def go(markdown: str, **config) -> SimpleNamespace:
        out = tmp_path / "out.pdf"
        pdf.build(markdown, config, out, repo_root=tmp_path, doc_path=tmp_path / "doc.md")
        return SimpleNamespace(
            html=captured["html"],
            document=captured["document"],
            options=captured["options"],
            pdf=out.read_bytes(),
            root=tmp_path,
        )

    return go


@pytest.fixture()
def feature_log():
    """Messages logged by md_doc.pdf_features, regardless of how the CLI configured logging."""
    records: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger = logging.getLogger("md_doc.pdf_features")
    handler, level = Collect(), logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    yield records
    logger.removeHandler(handler)
    logger.setLevel(level)


def page_texts(document) -> list[str]:
    result = []
    for page in document.pages:
        texts = [b.text for b in page._page_box.descendants() if type(b).__name__ == "TextBox"]
        result.append(" ".join(texts))
    return result


def all_text(document) -> str:
    return "\n".join(page_texts(document))


def margin_text(page) -> str:
    out = []
    for child in page._page_box.children:
        if type(child).__name__ == "MarginBox":
            out += [b.text for b in child.descendants() if type(b).__name__ == "TextBox"]
    return " ".join(out)


TWO_CHAPTERS = "# Alpha\n\ntext\n\n# Beta\n\nmore\n"
SECTIONS = "# Title\n\n## Intro\n\ntext\n\n### Detail\n\ntext\n\n## Next\n\ntext\n"


# ---------------------------------------------------------------------------
# Metadata, bookmarks, standards
# ---------------------------------------------------------------------------


def test_metadata_reaches_the_pdf(render):
    out = render(
        "# T\n\ntext\n",
        title="Annual Report",
        author="Ada",
        description="Audited accounts",
        keywords=["finance", "annual"],
        version="1.4",
        status="final",
    )
    meta = out.document.metadata
    assert meta.title == "Annual Report"
    assert meta.authors == ["Ada"]
    assert meta.description == "Audited accounts"
    assert meta.keywords == ["finance", "annual"]
    assert meta.generator.startswith("md-doc-pipeline")
    assert meta.custom == {"version": "1.4", "status": "final"}


def test_custom_metadata_can_be_switched_off(render):
    out = render("# T\n", version="1.4", pdf_custom_metadata=False)
    assert out.document.metadata.custom == {}


def test_keywords_fall_back_to_tags():
    assert pf.keywords_of({"tags": ["a", "b"]}) == ["a", "b"]
    assert pf.keywords_of({"keywords": "x, y", "tags": ["z"]}) == ["x", "y"]


def test_head_meta_escapes_values():
    html = pf.head_meta({"description": 'a "quoted" <b>'}, author="O'Neil")
    assert "&quot;quoted&quot;" in html and "&lt;b&gt;" in html


def labels(tree) -> list[tuple[int, str]]:
    found = []

    def walk(items, level=1):
        for label, _target, children, _state in items:
            found.append((level, label))
            walk(children, level + 1)

    walk(tree)
    return found


def test_headings_become_bookmarks(render):
    out = render(SECTIONS)
    tree = out.document.make_bookmark_tree()
    assert labels(tree) == [(1, "Title"), (2, "Intro"), (3, "Detail"), (2, "Next")]


def test_bookmark_depth_and_off_switch(render):
    shallow = render(SECTIONS, pdf_bookmark_depth=2)
    assert [lab for _, lab in labels(shallow.document.make_bookmark_tree())] == [
        "Title",
        "Intro",
        "Next",
    ]
    assert render(SECTIONS, pdf_bookmarks=False).document.make_bookmark_tree() == []


def test_cover_title_is_bookmarked(render):
    out = render(SECTIONS, cover_page=True, title="Cover Title")
    assert labels(out.document.make_bookmark_tree())[0] == (1, "Cover Title")


def test_pdf_a_variant_and_identifier(render):
    out = render("# T\n", pdf_variant="pdf/a-3b", pdf_attach_source=True, pdf_uncompressed=True)
    assert out.options["pdf_variant"] == "pdf/a-3b"
    assert b"pdfaid" in out.pdf
    assert b"/ID" in out.pdf


def test_unknown_variant_is_ignored_with_a_warning(feature_log):
    opts = pf.render_options({"pdf_variant": "pdf/z-9"}, resolve=lambda _: None)
    assert "pdf_variant" not in opts
    assert any("Ignoring unknown pdf_variant" in m for m in feature_log)


def test_ua_variant_tags_the_pdf(render):
    out = render("# T\n\ntext\n", pdf_variant="pdf/ua-1", pdf_uncompressed=True)
    assert b"StructTreeRoot" in out.pdf


def test_render_options_cover_every_write_option(tmp_path):
    resolve = lambda raw: tmp_path / raw if (tmp_path / raw).exists() else None  # noqa: E731
    (tmp_path / "rights.xml").write_text("<x/>")
    opts = pf.render_options(
        {
            "pdf_version": "1.7",
            "pdf_identifier": "doc-42",
            "pdf_tags": True,
            "pdf_presentational_hints": True,
            "pdf_optimize_images": True,
            "pdf_jpeg_quality": 70,
            "pdf_image_dpi": 150,
            "pdf_uncompressed": True,
            "pdf_srgb": True,
            "pdf_full_fonts": True,
            "pdf_hinting": True,
            "pdf_xmp": ["rights.xml"],
        },
        resolve=resolve,
    )
    assert opts == {
        "pdf_version": "1.7",
        "pdf_identifier": "doc-42",
        "pdf_tags": True,
        "custom_metadata": True,
        "presentational_hints": True,
        "optimize_images": True,
        "jpeg_quality": 70,
        "dpi": 150,
        "uncompressed_pdf": True,
        "srgb": True,
        "full_fonts": True,
        "hinting": True,
        "xmp_metadata": [(tmp_path / "rights.xml").as_uri()],
    }


@pytest.mark.parametrize(
    "key,value",
    [("pdf_jpeg_quality", 99), ("pdf_image_dpi", 5), ("pdf_version", "9"), ("pdf_zoom", 50)],
)
def test_out_of_range_options_are_dropped(key, value):
    opts = pf.render_options({key: value}, resolve=lambda _: None)
    assert not ({"jpeg_quality", "dpi", "pdf_version"} & set(opts))
    assert pf.pdf_zoom({key: value}) is None


def test_zoom_scales_the_page(render):
    normal = render("# T\n")
    zoomed = render("# T\n", pdf_zoom=2)
    assert zoomed.options["zoom"] == 2
    assert normal.pdf != zoomed.pdf


def test_attachments_are_embedded(render, tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    out = render(
        "# T\n\ntext\n",
        pdf_attach_source=True,
        pdf_attachments=["data.csv", "missing.bin"],
        pdf_variant=None,
    )
    names = [a.name for a in out.options["attachments"]]
    assert names == ["doc.md", "data.csv"]
    assert [a.relationship for a in out.options["attachments"]] == ["Source", "Supplement"]
    assert b"EmbeddedFile" in out.pdf


def test_attachment_paths_cannot_escape_the_project(render, tmp_path):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret")
    out = render("# T\n", pdf_attachments=["../secret.txt", str(outside)])
    assert "attachments" not in out.options


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------


def test_font_face_rules(tmp_path):
    for name in ("R.ttf", "B.otf", "M.woff2"):
        (tmp_path / name).write_bytes(b"x")
    resolve = lambda raw: tmp_path / raw if (tmp_path / raw).exists() else None  # noqa: E731
    css = pf.font_face_css(
        {
            "fonts": [
                {"family": "Brand", "regular": "R.ttf", "bold": "B.otf"},
                {"family": "Mono", "path": "M.woff2", "weight": 500, "style": "italic"},
                "R.ttf",
                {"family": "Bad;family", "path": "R.ttf"},
                {"family": "Gone", "path": "none.ttf"},
            ]
        },
        resolve,
    )
    assert css.count("@font-face") == 4
    assert "font-family: 'Brand'" in css and "font-weight: 700" in css
    assert 'format("opentype")' in css and 'format("woff2")' in css
    assert "font-weight: 500; font-style: italic" in css
    assert "font-family: 'R'" in css
    assert "Bad;family" not in css and "Gone" not in css


def test_fonts_reach_the_document_head(render, tmp_path):
    (tmp_path / "Brand.ttf").write_bytes(b"not a font")
    out = render("# T\n", fonts=[{"family": "Brand", "path": "Brand.ttf"}])
    assert "@font-face" in out.html and "Brand.ttf" in out.html


def test_color_profile_rule(tmp_path):
    (tmp_path / "p.icc").write_bytes(b"icc")
    resolve = lambda raw: tmp_path / raw if (tmp_path / raw).exists() else None  # noqa: E731
    assert "@color-profile device-cmyk" in pf.color_profile_css(
        {"pdf_color_profile": "p.icc"}, resolve
    )
    assert pf.color_profile_css({"pdf_color_profile": "nope.icc"}, resolve) == ""


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------


def test_language_and_hyphenation(render):
    out = render(
        "# T\n\ntext\n",
        lang="de",
        hyphenate=True,
        tabular_numbers=True,
        font_features='"liga", "onum"',
    )
    assert '<html lang="de">' in out.html
    assert "hyphens: auto" in out.html
    assert "tabular-nums" in out.html
    assert 'font-feature-settings: "liga", "onum"' in out.html


def test_invalid_language_falls_back_to_english():
    assert pf.document_lang({"lang": "not a tag!"}) == "en"
    assert pf.document_lang({"lang": "en-GB"}) == "en-GB"
    assert pf.document_lang({}) == "en"


def test_typography_is_off_by_default(render):
    out = render("# T\n")
    assert "hyphens: auto" not in out.html and "tabular-nums" not in out.html


# ---------------------------------------------------------------------------
# Headers, footers and running titles
# ---------------------------------------------------------------------------


def test_chapter_and_section_tokens(render):
    out = render(
        "# One\n\n## Alpha\n\ntext\n\n# Two\n\n## Beta\n\ntext\n",
        header_text="{title} / {chapter}",
        footer_right="{section} p{page}",
        title="Doc",
        chapter_break="page",
    )
    assert "Doc / One" in margin_text(out.document.pages[0])
    assert "Alpha p1" in margin_text(out.document.pages[0])
    assert "Doc / Two" in margin_text(out.document.pages[1])
    assert "Beta p2" in margin_text(out.document.pages[1])


def test_title_only_headers_do_not_add_string_set(render):
    out = render("# T\n", header_text="{page}")
    assert "string-set: md-chapter" not in out.html


def test_running_header_and_footer(render, tmp_path):
    from PIL import Image

    Image.new("RGB", (60, 20), (10, 80, 160)).save(tmp_path / "logo.png")
    out = render(
        TWO_CHAPTERS,
        header_layout="running",
        footer_layout="running",
        header_text="{chapter}",
        header_logo="logo.png",
        footer_right="{page}/{pages}",
        chapter_break="page",
    )
    assert "position: running(md-header)" in out.html
    assert "element(md-footer)" in out.html
    assert "Alpha" in margin_text(out.document.pages[0])
    assert "Beta" in margin_text(out.document.pages[1])
    assert "2 / 2" in margin_text(out.document.pages[1])
    headers = [
        c
        for c in out.document.pages[0]._page_box.children
        if type(c).__name__ == "MarginBox" and c.at_keyword == "@top-center"
    ]
    assert headers and any(
        type(b).__name__ in {"InlineReplacedBox", "BlockReplacedBox"}
        for b in headers[0].descendants()
    )


def test_running_bar_helpers_escape_text():
    html = pf.running_text_html("A & B {page}\nnext")
    assert "A &amp; B" in html and 'class="rb-page"' in html and "<br>" in html
    assert pf.header_bar(
        {},
        text=None,
        text_position="left",
        logo_uri=None,
        logo_position="right",
        logo_height_mm=None,
    ) == ("", "")
    assert pf.footer_bar({}, None, None, None) == ("", "")


def test_header_can_skip_the_first_page(render):
    out = render(TWO_CHAPTERS, header_text="HEAD", header_first_page=False, chapter_break="page")
    assert "HEAD" not in margin_text(out.document.pages[0])
    assert "HEAD" in margin_text(out.document.pages[1])


def test_first_page_header_stays_when_a_cover_exists(render):
    out = render(TWO_CHAPTERS, header_text="HEAD", header_first_page=False, cover_page=True)
    assert "@page :first" not in out.html


# ---------------------------------------------------------------------------
# Numbered headings
# ---------------------------------------------------------------------------


def test_numbering_starts_below_a_lone_title(render):
    out = render(
        "# Title\n\n[TOC]\n\n## Scope\n\ntext\n\n### Detail\n\ntext\n\n## Plan\n\ntext\n",
        numbered_headings=True,
    )
    text = all_text(out.document)
    assert "1 " in text and "1.1 " in text and "2 " in text
    assert pf.number_start_level("<h1>T</h1><h2>a</h2>") == 2
    assert pf.number_start_level("<h1>A</h1><h1>B</h1><h2>a</h2>") == 1
    assert pf.number_start_level("<h2>a</h2>") == 1


def test_numbering_style_and_depth(render):
    out = render(
        "# A\n\n## B\n\n### C\n\n# D\n",
        numbered_headings=True,
        heading_number_style="upper-roman",
        numbered_headings_depth=2,
    )
    text = all_text(out.document)
    assert "I. " in text and "II. " in text and "I.1 " in text
    assert "I.1.1" not in text


def test_contents_entries_are_tagged_for_numbering():
    html = (
        '<div class="toc"><ul><li><a href="#a">A</a><ul><li><a href="#b">B</a></li></ul>'
        '</li></ul></div><h1 id="t">T</h1><h2 id="a">A</h2><h3 id="b">B</h3>'
    )
    tagged = pf.mark_toc_levels(html, 2, 3)
    assert 'class="toc-n1"' in tagged and 'class="toc-n2"' in tagged


# ---------------------------------------------------------------------------
# Footnotes and cross-references
# ---------------------------------------------------------------------------

FOOTNOTED = "Claim.[^1] Again.[^2]\n\n[^1]: First note.\n\n[^2]: Second\n    note.\n"


def test_page_footnotes_move_to_the_page_foot(render):
    out = render(FOOTNOTED, page_footnotes=True)
    assert 'class="footnote"' not in out.html
    assert out.html.count('class="md-footnote"') == 2
    page = out.document.pages[0]._page_box
    assert any(type(c).__name__ == "FootnoteAreaBox" for c in page.children)
    assert "First note." in all_text(out.document)


def test_footnotes_stay_at_the_end_by_default(render):
    out = render(FOOTNOTED)
    assert 'class="footnote"' in out.html and "md-footnote" not in out.html.split("<body>")[1]


def test_page_footnotes_without_notes_is_a_no_op():
    assert pf.page_footnotes("<p>plain</p>") == "<p>plain</p>"


def test_empty_links_read_their_target(render):
    out = render("# Intro\n\nSee [](#results).\n\n# Results\n\ntext\n")
    assert re.search(r"See\s+Results\s*\.", all_text(out.document))


def test_toc_shows_page_numbers_with_the_default_theme(render):
    out = render("# T\n\n[TOC]\n\n## A\n\ntext\n")
    dots = [
        b
        for p in out.document.pages
        for b in p._page_box.descendants()
        if type(b).__name__ == "TextBox" and b.text == "."
    ]
    assert dots, "dot leaders missing: the default theme must not hide .toc page numbers"


def test_xref_pages_skip_the_contents_list(render):
    out = render("# T\n\n[TOC]\n\nSee [the end](#end).\n\n# End\n\ntext\n", xref_pages=True)
    assert out.html.count('class="md-xref"') == 1
    assert "(p. 1)" in all_text(out.document)


def test_mark_cross_references_ignores_footnote_links():
    html = '<a href="#fn:1" class="footnote-ref">1</a><a href="#x">x</a>'
    assert pf.mark_cross_references(html).count("md-xref") == 1


# ---------------------------------------------------------------------------
# Directives: columns and grid
# ---------------------------------------------------------------------------


def test_directives_become_styled_divs():
    out = pf.expand_directives(
        "a\n<!-- columns: 2, gap=10mm, rule=0.5pt solid #ccc -->\ntext\n<!-- /columns -->\n"
        "<!-- grid: 3 -->\nx\n<!-- /grid -->\n"
    )
    assert 'class="md-columns"' in out and "column-count: 2" in out
    assert "column-gap: 10mm" in out and "column-rule: 0.5pt solid #ccc" in out
    assert 'class="md-grid"' in out and "repeat(3, 1fr)" in out


def test_directives_inside_code_are_left_alone():
    src = "```\n<!-- columns: 2 -->\n```\n\nUse `<!-- grid: 2 -->` inline.\n"
    assert pf.expand_directives(src) == src


def test_directive_options_are_sanitised():
    out = pf.expand_directives("<!-- columns: 2, gap=1mm;color:red -->\nx\n<!-- /columns -->")
    assert "color:red" not in out and "column-gap: 8mm" in out


def test_unbalanced_directives_are_reported():
    problems = pf.unbalanced_directives(
        "<!-- columns: 2 -->\nx\n\n<!-- /grid -->\n\n```\n<!-- grid: 2 -->\n```\n"
    )
    assert [line for line, _ in problems] == [4, 1]


def test_columns_and_grid_lay_out(render):
    out = render(
        "<!-- columns: 2 -->\nOne two three four five six seven.\n\nSecond block.\n<!-- /columns -->\n\n"
        "<!-- grid: 3 -->\nA\n\nB\n\nC\n<!-- /grid -->\n"
    )
    boxes = list(out.document.pages[0]._page_box.descendants())
    assert any(type(b).__name__ == "GridBox" for b in boxes)
    x = {b.text.split()[0]: b.position_x for b in boxes if type(b).__name__ == "TextBox"}
    assert x["Second"] > x["One"]
    assert x["B"] > x["A"] and x["C"] > x["B"]


def test_body_columns(render):
    out = render("# T\n\ntext " * 5, columns=2, column_gap="6mm", column_rule="1pt solid #999")
    assert "column-count: 2; column-gap: 6mm; column-rule: 1pt solid #999" in out.html
    assert ".report-body h1 { column-span: all; }" in out.html


# ---------------------------------------------------------------------------
# Facing pages, chapter starts, print marks
# ---------------------------------------------------------------------------


def test_duplex_mirrors_margins(render):
    out = render(TWO_CHAPTERS, duplex=True, binding_margin="10mm", chapter_break="page")
    right_page, left_page = out.document.pages[0]._page_box, out.document.pages[1]._page_box
    mm = lambda px: round(px * 25.4 / 96)  # noqa: E731
    assert (mm(right_page.margin_left), mm(right_page.margin_right)) == (35, 20)
    assert (mm(left_page.margin_left), mm(left_page.margin_right)) == (20, 35)


def test_duplex_swaps_header_slots_on_left_pages(render):
    out = render(
        TWO_CHAPTERS,
        duplex=True,
        header_text="OUTER",
        header_text_position="right",
        chapter_break="page",
    )
    first = out.document.pages[0]._page_box
    second = out.document.pages[1]._page_box

    def slot(page, name):
        for c in page.children:
            if type(c).__name__ == "MarginBox" and c.at_keyword == name:
                return " ".join(b.text for b in c.descendants() if type(b).__name__ == "TextBox")
        return ""

    assert slot(first, "@top-right") == "OUTER" and slot(first, "@top-left") == ""
    assert slot(second, "@top-left") == "OUTER" and slot(second, "@top-right") == ""


def test_duplex_is_off_by_default(render):
    assert ":left" not in render(TWO_CHAPTERS).html


def test_recto_chapters_insert_clean_blank_pages(render):
    out = render(
        "# Alpha\n\ntext\n\n# Beta\n\ntext\n",
        chapter_break="recto",
        header_text="HEAD",
        footer_center="FOOT",
    )
    texts = page_texts(out.document)
    assert len(texts) == 3 and "Beta" in texts[2]
    blank = out.document.pages[1]
    assert margin_text(blank) == ""
    assert "HEAD" in margin_text(out.document.pages[0])


def test_chapter_break_never_applies_to_the_first_heading(render):
    out = render(TWO_CHAPTERS, chapter_break="page")
    assert len(out.document.pages) == 2


def test_print_marks_and_bleed(render):
    out = render("# T\n", print_marks="crop cross", bleed="3mm")
    page = out.document.pages[0]
    assert round(page.bleed["top"] * 25.4 / 96, 1) == 3.0
    assert "marks: crop cross; bleed: 3mm" in out.html


def test_unsafe_lengths_are_ignored(render):
    out = render("# T\n", bleed="3mm; background: red", columns=2, column_gap="x;y")
    assert "background: red" not in out.html


def test_image_options(render):
    out = render("# T\n", image_fit="cover", image_resolution="150dpi")
    assert "object-fit: cover" in out.html and "image-resolution: 150dpi" in out.html
    assert ".report-body img { object-fit" not in render("# T\n", image_fit="stretch").html


# ---------------------------------------------------------------------------
# Layout checks
# ---------------------------------------------------------------------------


def _document(html: str):
    return weasyprint.HTML(string=html).render()


def test_stranded_heading_is_found():
    html = (
        "<style>@page{size:100mm 100mm;margin:10mm}p{margin:0;height:70mm}h2{margin:0}</style>"
        "<p>fill</p><h2>Stranded</h2><p style='break-before:page'>next</p>"
    )
    findings = pf.layout_findings(_document(html))
    assert any("Stranded" in f and "page 1" in f for f in findings)


def test_overflow_and_blank_pages_are_found():
    html = (
        "<style>@page{size:100mm 100mm;margin:10mm}</style>"
        "<p style='white-space:nowrap'>" + "wide " * 60 + "</p>"
        "<h1 style='break-before: recto'>after blank</h1>"
    )
    findings = pf.layout_findings(_document(html))
    assert any("past the right margin" in f for f in findings)
    assert any("blank page" in f for f in findings)


def test_clean_documents_have_no_findings():
    html = "<style>@page{size:100mm 100mm;margin:10mm}</style><h1>Hi</h1><p>text</p>"
    assert pf.layout_findings(_document(html)) == []


def test_layout_check_warns_only_when_asked(render, feature_log):
    wide = "<div style='width:400mm;white-space:nowrap'>" + "wide " * 80 + "</div>\n"
    render(wide)
    assert not feature_log
    render(wide, pdf_layout_check=True)
    assert any(m.startswith("layout: page 1") for m in feature_log)


def test_finishers_chain_in_order():
    calls = []
    pf.chain_finishers(lambda d, p: calls.append(1), lambda d, p: calls.append(2))(None, None)
    assert calls == [1, 2]


# ---------------------------------------------------------------------------
# Config validation, lint and Word metadata
# ---------------------------------------------------------------------------


def test_schema_validates_the_new_keys():
    from md_doc.config_schema import validate_config

    bad = validate_config(
        {
            "pdf_variant": "pdf/z",
            "columns": 9,
            "pdf_jpeg_quality": "high",
            "pdf_bookmark_depth": 0,
            "hyphenate": "maybe",
            "pdf_zoom": "x",
            "pdf_attachments": [1],
            "fonts": 3,
            "chapter_break": "sideways",
        }
    )
    assert len([i for i in bad if i[0] == "error"]) == 9
    good = validate_config(
        {
            "pdf_variant": "PDF/A-3B",
            "columns": 2,
            "pdf_jpeg_quality": "80",
            "hyphenate": "yes",
            "pdf_zoom": 1.5,
            "fonts": [{"family": "X", "path": "x.ttf"}, "y.ttf"],
            "print_marks": "crop cross",
            "header_layout": "running",
        }
    )
    assert good == []


def test_lint_reports_unclosed_blocks_and_missing_assets(tmp_path):
    from md_doc.linter import lint_file

    (tmp_path / ".git").mkdir()
    doc = tmp_path / "d.md"
    doc.write_text(
        "---\ntitle: T\npdf_attachments: [nope.csv]\npdf_color_profile: none.icc\n"
        "fonts:\n  - family: F\n    path: gone.ttf\n---\n# T\n\n<!-- columns: 2 -->\ntext\n"
    )
    messages = [i.message for i in lint_file(doc, repo_root=tmp_path)]
    assert any("never closed" in m for m in messages)
    assert any("pdf_attachments" in m for m in messages)
    assert any("pdf_color_profile" in m for m in messages)
    assert any("'fonts'" in m for m in messages)


def test_lint_accepts_balanced_blocks_and_existing_assets(tmp_path):
    from md_doc.linter import lint_file

    (tmp_path / ".git").mkdir()
    (tmp_path / "data.csv").write_text("a")
    doc = tmp_path / "d.md"
    doc.write_text(
        "---\ntitle: T\npdf_attachments: [data.csv]\n---\n# T\n\n"
        "<!-- grid: 2 -->\na\n\nb\n<!-- /grid -->\n"
    )
    assert lint_file(doc, repo_root=tmp_path) == []


def test_word_output_carries_subject_and_keywords(tmp_path):
    from docx import Document

    from md_doc.builders import docx as docx_builder

    (tmp_path / ".git").mkdir()
    out = tmp_path / "o.docx"
    docx_builder.build(
        "# T\n\ntext\n",
        {"title": "T", "description": "About things", "keywords": ["x", "y"]},
        out,
        repo_root=tmp_path,
        doc_path=tmp_path / "d.md",
    )
    props = Document(str(out)).core_properties
    assert props.subject == "About things" and props.keywords == "x, y"


def test_header_text_tokens_in_css_content():
    assert pdf._css_content_value("{chapter} · {section}") == (
        "string(md-chapter, first) ' · ' string(md-section, last)"
    )


def test_every_documented_choice_is_accepted_by_weasyprint(render):
    """The enums the docs list must all render, not just validate."""
    for variant in pf.PDF_VARIANTS:
        out = render("# T\n", pdf_variant=variant)
        assert out.pdf.startswith(b"%PDF"), variant
    for fit in pf.IMAGE_FITS:
        render("# T\n", image_fit=fit)
    for marks in pf.PRINT_MARKS:
        render("# T\n", print_marks=marks)
    for brk in pf.CHAPTER_BREAKS:
        render(TWO_CHAPTERS, chapter_break=brk)
    for style in pf.NUMBER_STYLES:
        render(SECTIONS, numbered_headings=True, heading_number_style=style)


def test_word_header_and_footer_expand_the_same_tokens(tmp_path):
    from docx import Document

    from md_doc.builders import docx as docx_builder

    (tmp_path / ".git").mkdir()
    out = tmp_path / "o.docx"
    docx_builder.build(
        "# T\n\n## S\n\ntext\n",
        {
            "title": "Handbook",
            "header_text": "{title} — {chapter}",
            "footer_right": "{section} · {page}/{pages}",
        },
        out,
        repo_root=tmp_path,
        doc_path=tmp_path / "d.md",
    )
    section = Document(str(out)).sections[0]
    header_xml = section.header._element.xml
    footer_xml = section.footer._element.xml
    assert "Handbook — " in header_xml and 'STYLEREF "Heading 1"' in header_xml
    assert 'STYLEREF "Heading 2"' in footer_xml and "NUMPAGES" in footer_xml
    assert "{chapter}" not in header_xml and "{title}" not in header_xml


def test_shared_image_cache_is_opt_in(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        weasyprint.HTML, "write_pdf", lambda self, target, **kwargs: seen.append(kwargs)
    )
    (tmp_path / ".git").mkdir()

    def build_once():
        pdf.build("# T\n", {}, tmp_path / "o.pdf", repo_root=tmp_path, doc_path=tmp_path / "d.md")

    build_once()
    pdf.use_shared_image_cache()
    try:
        build_once()
        build_once()
    finally:
        pdf.use_shared_image_cache(False)
    build_once()
    assert "cache" not in seen[0] and "cache" not in seen[3]
    assert seen[1]["cache"] is seen[2]["cache"]


def test_layout_check_ignores_header_bars_and_clean_pages(render, tmp_path, feature_log):
    from PIL import Image

    Image.new("RGB", (60, 20), (10, 80, 160)).save(tmp_path / "logo.png")
    render(
        "# T\n\nbody\n\n# U\n\nmore\n",
        pdf_layout_check=True,
        page_header_bar=True,
        header_text="Bar text",
        header_logo="logo.png",
        cover_page=True,
    )
    assert feature_log == []


def test_duplex_is_skipped_under_a_header_bar(render, feature_log):
    out = render(TWO_CHAPTERS, duplex=True, page_header_bar=True)
    assert ":left" not in out.html
    assert any("duplex is ignored" in m for m in feature_log)


def test_css_values_cannot_break_out_of_their_rule(render):
    out = render(
        "# T\n",
        font_features='"liga"\n} body { display: none',
        column_rule="1pt solid red;\n}",
        columns=2,
    )
    assert "display: none" not in out.html and "red;\n}" not in out.html


def test_every_write_option_builds_together(render, tmp_path):
    (tmp_path / "rights.xml").write_text(
        '<rdf:Description xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" rdf:about="">'
        "<dc:rights>All rights reserved</dc:rights></rdf:Description>"
    )
    (tmp_path / "data.csv").write_text("a,b\n")
    out = render(
        "# T\n\n<table align='center' width='50%'><tr><td>x</td></tr></table>\n",
        pdf_variant="pdf/a-3b",
        pdf_version="1.7",
        pdf_identifier="fixed-id",
        pdf_tags=True,
        pdf_optimize_images=True,
        pdf_jpeg_quality=60,
        pdf_image_dpi=96,
        pdf_srgb=True,
        pdf_full_fonts=True,
        pdf_hinting=True,
        pdf_presentational_hints=True,
        pdf_zoom=1.2,
        pdf_xmp=["rights.xml"],
        pdf_attachments=["data.csv"],
        pdf_attach_source=True,
        pdf_uncompressed=True,
    )
    assert out.pdf.startswith(b"%PDF-1.7")
    assert b"All rights reserved" in out.pdf and b"fixed-id" in out.pdf
