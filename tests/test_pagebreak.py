"""Tests for the ``<!-- pagebreak -->`` marker.

Covers both the PDF preprocessor (markdown → div) and the DOCX walker
(div → real Word page break).
"""

import pytest

from md_doc.builders.pdf import _inject_page_breaks


@pytest.mark.parametrize("intro", ["", "<p>Introduction</p>"])
def test_pdf_heading_starts_long_table_on_remaining_page(intro):
    from weasyprint import HTML

    from md_doc.builders.pdf import _BASE_FIXES_CSS, _keep_heading_with_next

    table = "<table><thead><tr><th>Header</th></tr></thead><tbody>"
    table += "".join(f"<tr><td>Row {i}</td></tr>" for i in range(9))
    table += "</tbody></table>"
    body = _keep_heading_with_next(f"<h2>Heading</h2>{intro}{table}", split_tables=True)
    document = HTML(
        string=(
            "<style>@page { size: 100mm 120mm; margin: 10mm; }"
            "body { margin: 0; font-size: 10pt; }"
            "h2, p { margin: 0; }"
            "table { page-break-inside: avoid; border-collapse: collapse; }"
            "td, th { height: 10mm; padding: 0; }"
            ".filler { height: 35mm; }"
            ".keep-with-next { break-inside: avoid; }</style>"
            + _BASE_FIXES_CSS
            + f'<div class="report-body"><div class="filler">Before</div>{body}</div>'
        )
    ).render()
    pages = [
        " ".join(box.text for box in page._page_box.descendants() if hasattr(box, "text"))
        for page in document.pages
    ]
    assert len(pages) == 2
    assert "Heading" in pages[0] and "Row 0" in pages[0]
    assert "Row 8" in pages[1]
    assert "Header" in pages[1]


# ── PDF: markdown preprocessor ────────────────────────────────────────────────


class TestInjectPageBreaks:
    def test_basic_substitution(self):
        md = "Top\n\n<!-- pagebreak -->\n\nBottom"
        result = _inject_page_breaks(md)
        assert '<div class="md-doc-page-break"></div>' in result
        assert "<!-- pagebreak -->" not in result

    def test_case_insensitive(self):
        for marker in ("<!-- PAGEBREAK -->", "<!-- PageBreak -->", "<!--pagebreak-->"):
            assert '<div class="md-doc-page-break"></div>' in _inject_page_breaks(marker)

    def test_multiple_markers(self):
        md = "A\n<!-- pagebreak -->\nB\n<!-- pagebreak -->\nC"
        result = _inject_page_breaks(md)
        assert result.count('<div class="md-doc-page-break"></div>') == 2

    def test_no_marker_unchanged(self):
        md = "Just plain content with no marker"
        assert _inject_page_breaks(md) == md

    @pytest.mark.parametrize(
        "example",
        [
            "`<!-- pagebreak -->`",
            "```markdown\n<!-- pagebreak -->\n```",
            "~~~~markdown\n```\n<!-- pagebreak -->\n```\n~~~~",
        ],
    )
    def test_code_examples_stay_literal(self, example):
        from md_doc.builders.pdf import _expand_form_fields

        source = example + "\n\n<!-- pagebreak -->\n\nAfter"
        result = _inject_page_breaks(source)
        assert example in result
        assert result.count('<div class="md-doc-page-break"></div>') == 1
        form_example = example.replace("<!-- pagebreak -->", "?[text: sample]")
        result = _expand_form_fields(form_example + "\n\n?[text: actual]", False)
        assert form_example in result
        assert 'name="actual"' in result
        assert 'name="sample"' not in result

    def test_other_html_comments_untouched(self):
        md = "<!-- not a pagebreak -->\nbody"
        result = _inject_page_breaks(md)
        assert "<!-- not a pagebreak -->" in result
        assert '<div class="md-doc-page-break"></div>' not in result

    def test_div_surrounded_by_blank_lines(self):
        """Markdown needs blank lines around block-level HTML."""
        md = "para 1\n<!-- pagebreak -->\npara 2"
        result = _inject_page_breaks(md)
        # Should have blank lines around the div so markdown parses it as block
        assert '\n\n<div class="md-doc-page-break"></div>\n\n' in result


# ── PDF: end-to-end build smoke test ──────────────────────────────────────────


class TestPdfBuildPagebreak:
    """Verify the marker survives the full PDF build pipeline."""

    @pytest.mark.parametrize("following", ["Second page", "# Second page"])
    def test_custom_theme_starts_a_new_page(self, tmp_path, monkeypatch, following):
        weasyprint = pytest.importorskip("weasyprint")
        from md_doc.builders.pdf import build as build_pdf

        (tmp_path / ".git").mkdir()
        (tmp_path / "_pdf-theme.css").write_text(
            "@page { size: A4; margin: 20mm; }\n"
            "body { font-size: 12pt; }\n"
            "h1 { page-break-before: always; break-before: page; }\n"
        )
        rendered = []

        def write_pdf(html, target, **kwargs):
            document = html.render()
            rendered.append(document)
            return document.write_pdf(target, **kwargs)

        monkeypatch.setattr(weasyprint.HTML, "write_pdf", write_pdf)
        build_pdf(
            f"First page\n\n<!-- pagebreak -->\n\n{following}\n",
            {"cover_page": False},
            tmp_path / "out.pdf",
            repo_root=tmp_path,
        )
        assert len(rendered[0].pages) == 2
        texts = [
            " ".join(
                box.text
                for box in page._page_box.descendants()
                if isinstance(box, weasyprint.formatting_structure.boxes.TextBox)
            )
            for page in rendered[0].pages
        ]
        assert "First page" in texts[0] and "Second page" not in texts[0]
        assert "Second page" in texts[1] and "First page" not in texts[1]

    def test_theme_breaking_after_the_marker_adds_no_blank_page(self, tmp_path, monkeypatch):
        weasyprint = pytest.importorskip("weasyprint")
        from md_doc.builders.pdf import build as build_pdf

        (tmp_path / ".git").mkdir()
        (tmp_path / "_pdf-theme.css").write_text(
            "@page { size: A4; margin: 20mm; }\n.md-doc-page-break { break-after: page; }\n"
        )
        rendered = []

        def write_pdf(html, target, **kwargs):
            document = html.render()
            rendered.append(document)
            return document.write_pdf(target, **kwargs)

        monkeypatch.setattr(weasyprint.HTML, "write_pdf", write_pdf)
        build_pdf(
            "First page\n\n<!-- pagebreak -->\n\nSecond page\n",
            {"cover_page": False},
            tmp_path / "out.pdf",
            repo_root=tmp_path,
        )
        assert len(rendered[0].pages) == 2

    def test_builds_without_error(self, tmp_path):
        pytest.importorskip("weasyprint")
        from md_doc.builders.pdf import build as build_pdf

        (tmp_path / ".git").mkdir()
        out = tmp_path / "out.pdf"

        md = "---\ntitle: Test\n---\n\n" "First page\n\n" "<!-- pagebreak -->\n\n" "Second page\n"

        build_pdf(md, {"title": "Test", "cover_page": False}, out, repo_root=tmp_path)
        assert out.exists()
        assert out.stat().st_size > 0


# ── DOCX: walker emits a real page break ──────────────────────────────────────


class TestDocxPagebreak:
    def test_marker_emits_word_page_break(self, tmp_path):
        from md_doc.builders.docx import build as build_docx

        (tmp_path / ".git").mkdir()
        out = tmp_path / "out.docx"

        md = "---\ntitle: Test\n---\n\n" "Before break\n\n" "<!-- pagebreak -->\n\n" "After break\n"

        build_docx(md, {"title": "Test"}, out, repo_root=tmp_path)
        assert out.exists()

        # Re-open the document and verify a page-break run was inserted.
        # python-docx represents page breaks as <w:br w:type="page"/>.
        from docx import Document

        doc = Document(str(out))
        xml = "\n".join(p._p.xml for p in doc.paragraphs)
        # The break is a pageBreakBefore on the paragraph that starts the page
        # (or an explicit break run when no paragraph follows).
        assert 'w:type="page"' in xml or "pageBreakBefore" in xml

    def test_no_marker_no_page_break(self, tmp_path):
        from md_doc.builders.docx import build as build_docx
        from docx import Document

        (tmp_path / ".git").mkdir()
        out = tmp_path / "no_break.docx"

        md = "---\ntitle: Test\n---\n\nJust one page of content.\n"

        # cover_page=False suppresses the cover page for plain .docx
        build_docx(md, {"title": "Test", "cover_page": False}, out, repo_root=tmp_path)

        doc = Document(str(out))
        xml = "\n".join(p._p.xml for p in doc.paragraphs)
        assert 'w:type="page"' not in xml


def test_section_markers_preserve_code_examples():
    from md_doc.pagination import inject_section_breaks

    example = "```markdown\n<!-- sectionbreak: landscape -->\n```"
    result = inject_section_breaks(example + "\n\n<!-- SECTIONBREAK: LANDSCAPE -->")
    assert example in result
    assert result.count('data-orientation="landscape"') == 1
    assert 'data-orientation="default"' in inject_section_breaks("<!-- sectionbreak -->")


@pytest.mark.parametrize("fmt", ["docx", "dotx"])
@pytest.mark.parametrize("cover", [False, True])
def test_word_sections_switch_orientation_and_table_width(tmp_path, fmt, cover):
    import zipfile
    from xml.etree import ElementTree as ET
    from docx.oxml.ns import qn
    from md_doc.builders.docx import build

    (tmp_path / ".git").mkdir()
    source = tmp_path / "doc.md"
    source.write_text("Placeholder")
    out = tmp_path / f"out.{fmt}"
    build(
        """# First

Portrait content

<!-- sectionbreak: landscape -->

## Wide section

| A | B |
|---|---|
| Wide | Table |

<!-- pagebreak -->

Still landscape

<!-- sectionbreak -->

Back to default
""",
        {"cover_page": cover},
        out,
        doc_path=source,
        repo_root=tmp_path,
        output_format=fmt,
    )
    with zipfile.ZipFile(out) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    sections = root.findall(".//" + qn("w:sectPr"))
    assert len(sections) == 3
    assert (sections[0].find(qn("w:titlePg")) is not None) == cover
    for section in sections[1:]:
        title_page = section.find(qn("w:titlePg"))
        assert title_page is None or title_page.get(qn("w:val")) == "0"
    sizes = [s.find(qn("w:pgSz")) for s in sections]
    assert int(sizes[0].get(qn("w:w"))) < int(sizes[0].get(qn("w:h")))
    assert int(sizes[1].get(qn("w:w"))) > int(sizes[1].get(qn("w:h")))
    assert sizes[2].get(qn("w:w")) == sizes[0].get(qn("w:w"))
    assert sizes[2].get(qn("w:h")) == sizes[0].get(qn("w:h"))
    margins = sections[1].find(qn("w:pgMar"))
    available = (
        int(sizes[1].get(qn("w:w")))
        - int(margins.get(qn("w:left")))
        - int(margins.get(qn("w:right")))
    )
    table = root.findall(".//" + qn("w:tbl"))[-1]
    widths = table.findall(".//" + qn("w:gridCol"))
    assert abs(sum(int(c.get(qn("w:w"))) for c in widths) - available) <= 2


def test_pdf_sections_and_default_headings(tmp_path, monkeypatch):
    import weasyprint
    from md_doc.builders.pdf import build

    (tmp_path / ".git").mkdir()
    rendered = []

    def write_pdf(html, target, **kwargs):
        document = html.render()
        rendered.append(document)
        return document.write_pdf(target, **kwargs)

    monkeypatch.setattr(weasyprint.HTML, "write_pdf", write_pdf)
    build(
        """# First

Intro

# Second

Body

# APPENDIX

## Subsection

Appendix content

<!-- sectionbreak: landscape -->

## Wide section

Wide content

<!-- pagebreak -->

Still wide

<!-- sectionbreak: portrait -->

Portrait again
""",
        {"cover_page": False},
        tmp_path / "out.pdf",
        repo_root=tmp_path,
    )
    pages = rendered[0].pages
    assert len(pages) == 4
    assert pages[0].width < pages[0].height
    assert pages[1].width > pages[1].height
    assert pages[2].width > pages[2].height
    assert pages[3].width < pages[3].height
