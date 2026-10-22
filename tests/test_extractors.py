"""Tests for document extraction logic."""

import pytest

from md_doc.extractors import extract_file


class TestPdfExtraction:
    def test_extract_pdf_returns_markdown(self, tmp_path):
        """PDF file should be converted to Markdown string."""
        pdf_path = tmp_path / "sample.pdf"

        # Create a minimal valid PDF
        pdf_bytes = bytes.fromhex(
            "255044462d312e340a312030206f626a0a3c3c202f54797065202f436174616c6f67202f5061676573203220302052203e3e0a656e646f626a0a322030206f626a0a3c3c202f54797065202f5061676573202f4b696473205b33203020525d202f436f756e742031203e3e0a656e646f626a0a332030206f626a0a3c3c202f54797065202f50616765202f506172656e74203220302052202f5265736f7572636573203c3c202f466f6e74203c3c202f4631203420302052203e3e203e3e202f4d65646961426f78205b30203020363132203739325d202f436f6e74656e7473203520302052203e3e0a656e646f626a0a342030206f626a0a3c3c202f54797065202f466f6e74202f53756274797065202f5479706531202f42617365466f6e74202f48656c766574696361203e3e0a656e646f626a0a352030206f626a0a3c3c202f4c656e677468203434203e3e0a73747265616d0a42540a2f46312031322054660a313030203730302054640a2854657374205044462920546a0a45540a656e6473747265616d0a656e646f626a0a787265660a3020360a303030303030303030302036353533352066200a30303030303030303039203030303030206e200a30303030303030303538203030303030206e200a30303030303030313135203030303030206e200a30303030303030323437203030303030206e200a30303030303030333334203030303030206e200a747261696c65720a3c3c202f53697a652036202f526f6f74203120302052203e3e0a7374617274787265660a3432380a2525454f460a"
        )
        pdf_path.write_bytes(pdf_bytes)

        result = extract_file(str(pdf_path))
        assert isinstance(result, str)
        assert len(result) > 0  # Non-empty markdown


class TestDocxExtraction:
    def test_extract_docx_returns_markdown(self, tmp_path):
        """DOCX file should be converted to Markdown string."""
        # Create a minimal DOCX using python-docx
        from docx import Document

        doc = Document()
        doc.add_heading("Test Document", 0)
        doc.add_paragraph("This is a test paragraph.")

        docx_path = tmp_path / "sample.docx"
        doc.save(str(docx_path))

        result = extract_file(str(docx_path))
        assert isinstance(result, str)
        assert "Test Document" in result


class TestExtractFileTypeValidation:
    def test_extract_file_rejects_unsupported_type(self, tmp_path):
        """Unsupported file types should raise ValueError."""
        unsupported = tmp_path / "file.txt"
        unsupported.write_text("text file")

        with pytest.raises(ValueError, match="unsupported file type"):
            extract_file(str(unsupported))


class TestExtractFileNotFound:
    def test_extract_file_not_found(self, tmp_path):
        """Non-existent file should raise FileNotFoundError."""
        missing = tmp_path / "nonexistent.pdf"

        with pytest.raises(FileNotFoundError):
            extract_file(str(missing))


def _docx_with(tmp_path, build, name="in.docx"):
    from docx import Document

    doc = Document()
    build(doc)
    path = tmp_path / name
    doc.save(str(path))
    return path


class TestWordFields:
    def test_merge_and_form_fields_become_double_bracket_fields(self, tmp_path):
        from md_doc.builders.docx import _insert_form_field, _insert_merge_field
        from md_doc.extractors import extract_document

        def build(doc):
            para = doc.add_paragraph("Dear ")
            _insert_merge_field(para, '"First Name"')  # Word quotes names with spaces
            para.add_run(" and ")
            _insert_form_field(para, "company", 1)

        result = extract_document(str(_docx_with(tmp_path, build)))
        assert "Dear [[First_Name]] and [[company]]" in result.markdown
        assert result.fields == ["First_Name", "company"]

    def test_dotx_is_read_as_a_document(self, tmp_path):
        from md_doc.builders.docx import _insert_form_field
        from md_doc.extractors import extract_document

        def build(doc):
            _insert_form_field(doc.add_paragraph("Name: "), "contact_name", 1)

        path = _docx_with(tmp_path, build, "letter.dotx")
        assert extract_document(str(path)).fields == ["contact_name"]

    def test_unnamed_form_field_is_left_as_text(self, tmp_path):
        from md_doc.builders.docx import _insert_form_field
        from md_doc.extractors import extract_document

        def build(doc):
            _insert_form_field(doc.add_paragraph(), "", 1)

        assert extract_document(str(_docx_with(tmp_path, build))).fields == []

    def test_simple_field_and_content_control(self, tmp_path):
        from lxml import etree

        from md_doc.extractors import _W, extract_document

        def build(doc):
            xml = (
                f'<w:p xmlns:w="{_W}">'
                '<w:fldSimple w:instr=" MERGEFIELD city \\* MERGEFORMAT "><w:r><w:t>x</w:t></w:r>'
                "</w:fldSimple>"
                '<w:sdt><w:sdtPr><w:tag w:val="job_title"/></w:sdtPr><w:sdtContent>'
                "<w:r><w:t>Role</w:t></w:r></w:sdtContent></w:sdt>"
                '<w:sdt><w:sdtPr><w:tag w:val="agree"/><w:checkbox/></w:sdtPr><w:sdtContent>'
                "<w:r><w:t>BOX</w:t></w:r></w:sdtContent></w:sdt></w:p>"
            )
            doc.element.body.insert(0, etree.fromstring(xml))

        result = extract_document(str(_docx_with(tmp_path, build)))
        assert "[[city]]" in result.markdown and "[[job_title]]" in result.markdown
        assert "BOX" in result.markdown and "agree" not in result.fields

    def test_extract_file_still_returns_a_string(self, tmp_path):
        from md_doc.builders.docx import _insert_merge_field

        def build(doc):
            _insert_merge_field(doc.add_paragraph(), "city")

        assert "[[city]]" in extract_file(str(_docx_with(tmp_path, build)))


class TestOtherFormats:
    def test_html(self, tmp_path):
        from md_doc.extractors import extract_document

        page = tmp_path / "page.html"
        page.write_text("<h1>Heading</h1><p>Some <b>bold</b> text [[name]].</p>")
        result = extract_document(str(page))
        assert "# Heading" in result.markdown and "**bold**" in result.markdown
        assert result.fields == ["name"]

    def test_pptx(self, tmp_path):
        from pptx import Presentation

        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[0])
        slide.shapes.title.text = "Quarterly review"
        path = tmp_path / "deck.pptx"
        deck.save(str(path))
        assert "Quarterly review" in extract_file(str(path))


class TestSuggestFrontmatter:
    def test_keeps_the_original_name_for_output(self):
        from md_doc.extractors import suggest_frontmatter

        text = suggest_frontmatter("Client Proposal.docx", [])
        assert 'title: "Client Proposal"' in text
        assert 'output_filename: "Client Proposal"' in text
        assert "outputs: [pdf, docx]" in text and text.endswith("---\n\n")

    def test_records_where_the_content_came_from(self):
        from datetime import date

        from md_doc.config_schema import validate_config
        from md_doc.extractors import suggest_frontmatter

        text = suggest_frontmatter("Client Proposal.docx", [], today=date(2026, 10, 22))
        assert 'imported_from: "Client Proposal.docx"' in text
        assert 'imported_on: "2026-10-22"' in text
        import yaml

        data = yaml.safe_load(text.split("---")[1])
        assert not [m for m in validate_config(data) if "Unknown" in m[1]]

    def test_template_with_fields_builds_a_fillable_dotx(self):
        from md_doc.extractors import suggest_frontmatter

        text = suggest_frontmatter("letter.dotx", ["a"])
        assert "outputs: [dotx]" in text and "dotx_field_type: form" in text

    def test_deck(self):
        from md_doc.extractors import suggest_frontmatter

        assert "slide_split: h1" in suggest_frontmatter("deck.pptx", [])

    def test_xlsx(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        book = openpyxl.Workbook()
        book.active.append(["Item", "Cost"])
        book.active.append(["Widget", 5])
        path = tmp_path / "prices.xlsx"
        book.save(str(path))
        text = extract_file(str(path))
        assert "| Item | Cost |" in text and "Widget" in text
