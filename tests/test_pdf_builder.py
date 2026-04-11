"""Tests for the PDF builder — focused on CSS resolution."""

from pathlib import Path

import pytest

from md_doc.builders.pdf import _resolve_css


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
