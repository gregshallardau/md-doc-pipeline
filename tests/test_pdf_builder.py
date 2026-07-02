"""Tests for the PDF builder — focused on CSS resolution."""

from unittest.mock import patch, MagicMock

import pytest

from md_doc.builders.pdf import _resolve_css, build as build_pdf


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


class TestResolveCss:
    def test_explicit_pdf_theme_absolute(self, tmp_repo):
        css = tmp_repo / "custom.css"
        css.write_text("body {}")
        result = _resolve_css({"pdf_theme": str(css)}, tmp_repo)
        assert result == css.resolve()

    def test_explicit_pdf_theme_relative_to_repo(self, tmp_repo):
        css_dir = tmp_repo / "themes" / "custom"
        css_dir.mkdir(parents=True)
        css = css_dir / "theme.css"
        css.write_text("body {}")
        result = _resolve_css({"pdf_theme": "themes/custom/theme.css"}, tmp_repo)
        assert result == css.resolve()

    def test_auto_generates_default_theme(self, tmp_repo):
        """When no _pdf-theme.css exists anywhere, one is generated at the repo root."""
        result = _resolve_css({}, tmp_repo)
        generated = tmp_repo / "_pdf-theme.css"
        assert generated.exists()
        assert result == generated.resolve()

    def test_nested_css_in_doc_dir(self, tmp_repo):
        """_pdf-theme.css placed next to the document is picked up."""
        doc_dir = tmp_repo / "products" / "alpha"
        doc_dir.mkdir(parents=True)
        css = doc_dir / "_pdf-theme.css"
        css.write_text("body { color: red; }")
        doc = doc_dir / "report.md"
        doc.write_text("# Report\n")
        result = _resolve_css({}, tmp_repo, doc_path=doc)
        assert result == css.resolve()

    def test_nested_css_in_ancestor_dir(self, tmp_repo):
        """_pdf-theme.css in an intermediate ancestor is found when none is closer."""
        mid = tmp_repo / "products"
        mid.mkdir()
        deep = mid / "alpha"
        deep.mkdir()
        css = mid / "_pdf-theme.css"
        css.write_text("body { color: blue; }")
        doc = deep / "report.md"
        doc.write_text("# Report\n")
        result = _resolve_css({}, tmp_repo, doc_path=doc)
        assert result == css.resolve()

    def test_deeper_css_overrides_ancestor(self, tmp_repo):
        """A _pdf-theme.css closer to the document wins over one higher up."""
        mid = tmp_repo / "products"
        deep = mid / "alpha"
        deep.mkdir(parents=True)
        mid_css = mid / "_pdf-theme.css"
        mid_css.write_text("body { color: blue; }")
        deep_css = deep / "_pdf-theme.css"
        deep_css.write_text("body { color: green; }")
        doc = deep / "report.md"
        doc.write_text("# Report\n")
        result = _resolve_css({}, tmp_repo, doc_path=doc)
        assert result == deep_css.resolve()

    def test_explicit_pdf_theme_overrides_nested(self, tmp_repo):
        """pdf_theme config key takes priority over any nested _pdf-theme.css."""
        doc_dir = tmp_repo / "docs"
        doc_dir.mkdir()
        nested_css = doc_dir / "_pdf-theme.css"
        nested_css.write_text("body { color: red; }")
        explicit_css = tmp_repo / "explicit.css"
        explicit_css.write_text("body { color: purple; }")
        doc = doc_dir / "report.md"
        doc.write_text("# Report\n")
        result = _resolve_css({"pdf_theme": str(explicit_css)}, tmp_repo, doc_path=doc)
        assert result == explicit_css.resolve()


class TestPdfFormsFlag:
    def test_pdf_forms_true_passed_to_weasyprint(self, tmp_repo):
        (tmp_repo / "_pdf-theme.css").write_text("body {}")
        doc = tmp_repo / "form.md"
        doc.write_text("# My Form\n")

        mock_html_inst = MagicMock()
        with patch("md_doc.builders.pdf.weasyprint") as mock_wp:
            mock_wp.HTML.return_value = mock_html_inst
            build_pdf(
                "# My Form\n",
                {"pdf_forms": True},
                tmp_repo / "form-form.pdf",
                repo_root=tmp_repo,
                doc_path=doc,
            )

        _, kwargs = mock_html_inst.write_pdf.call_args
        assert kwargs.get("pdf_forms") is True

    def test_pdf_forms_not_passed_when_unset(self, tmp_repo):
        (tmp_repo / "_pdf-theme.css").write_text("body {}")
        doc = tmp_repo / "report.md"
        doc.write_text("# My Report\n")

        mock_html_inst = MagicMock()
        with patch("md_doc.builders.pdf.weasyprint") as mock_wp:
            mock_wp.HTML.return_value = mock_html_inst
            build_pdf(
                "# My Report\n",
                {},
                tmp_repo / "report.pdf",
                repo_root=tmp_repo,
                doc_path=doc,
            )

        _, kwargs = mock_html_inst.write_pdf.call_args
        assert "pdf_forms" not in kwargs


class TestBodyAlignAndCoverCss:
    """Parity-review fixes: config keys that were Word-only or broken in PDF."""

    def _built_html(self, tmp_repo, config):
        (tmp_repo / "_pdf-theme.css").write_text("body {}")
        doc = tmp_repo / "report.md"
        doc.write_text("# My Report\n\nBody text.\n")
        with patch("md_doc.builders.pdf.weasyprint") as mock_wp:
            mock_wp.HTML.return_value = MagicMock()
            build_pdf(
                doc.read_text(),
                config,
                tmp_repo / "report.pdf",
                repo_root=tmp_repo,
                doc_path=doc,
            )
            _, kwargs = mock_wp.HTML.call_args
        return kwargs["string"]

    def test_body_text_align_injected(self, tmp_repo):
        html = self._built_html(tmp_repo, {"body_text_align": "justify"})
        assert ".report-body { text-align: justify; }" in html

    def test_body_text_align_absent_by_default(self, tmp_repo):
        html = self._built_html(tmp_repo, {})
        assert "text-align: justify" not in html

    def test_body_text_align_rejects_unsafe_values(self, tmp_repo):
        html = self._built_html(tmp_repo, {"body_text_align": "evil;}</style>"})
        assert "evil" not in html

    def test_cover_align_and_footer_line_css_present(self, tmp_repo):
        # cover_text_align / cover_footer_line previously emitted classes with
        # no CSS behind them — the support rules must ship with the cover.
        html = self._built_html(tmp_repo, {"cover_text_align": "right"})
        assert ".cover-align-right { text-align: right; }" in html
        assert ".cover-footer-no-line { border-top: none !important" in html
        assert 'class="cover cover-align-right"' in html

    def test_page_header_bar_logo_beats_header_logo(self, tmp_repo):
        # Same precedence as the docx builder: the more-specific
        # page_header_bar_logo wins inside the bar.
        from PIL import Image

        Image.new("RGB", (10, 10), "red").save(tmp_repo / "generic.png")
        Image.new("RGB", (10, 10), "blue").save(tmp_repo / "bar.png")
        html = self._built_html(
            tmp_repo,
            {
                "page_header_bar": True,
                "header_logo": "generic.png",
                "page_header_bar_logo": "bar.png",
            },
        )
        assert "bar.png" in html
        assert "generic.png" not in html
