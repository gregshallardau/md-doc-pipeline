"""Tests for _build_footer_style() and its integration into build()."""

from unittest.mock import patch, MagicMock

import pytest

from md_doc.builders.pdf import _build_footer_style


class TestBuildFooterStyleEmpty:
    def test_all_none_returns_empty_string(self):
        result = _build_footer_style(None, None, None)
        assert result == ""


class TestBuildFooterStyleLeftOnly:
    def test_left_emits_bottom_left_rule(self):
        result = _build_footer_style("Affinity IB", None, None)
        assert "@bottom-left" in result
        assert "Affinity IB" in result

    def test_left_does_not_emit_bottom_center(self):
        result = _build_footer_style("Affinity IB", None, None)
        assert "@bottom-center" not in result

    def test_left_does_not_emit_bottom_right(self):
        result = _build_footer_style("Affinity IB", None, None)
        assert "@bottom-right" not in result

    def test_left_adds_cover_override_for_bottom_left(self):
        result = _build_footer_style("Affinity IB", None, None)
        assert "@page cover" in result
        # The cover override must clear the bottom-left slot
        cover_section = result[result.index("@page cover"):]
        assert "@bottom-left" in cover_section
        assert "content: none" in cover_section

    def test_left_cover_does_not_override_unused_slots(self):
        result = _build_footer_style("Affinity IB", None, None)
        cover_section = result[result.index("@page cover"):]
        assert "@bottom-center" not in cover_section
        assert "@bottom-right" not in cover_section


class TestBuildFooterStyleRightOnly:
    def test_right_emits_bottom_right_rule(self):
        result = _build_footer_style(None, None, "Page X")
        assert "@bottom-right" in result
        assert "Page X" in result

    def test_right_does_not_emit_bottom_left(self):
        result = _build_footer_style(None, None, "Page X")
        assert "@bottom-left" not in result

    def test_right_does_not_emit_bottom_center(self):
        result = _build_footer_style(None, None, "Page X")
        assert "@bottom-center" not in result


class TestBuildFooterStyleAllThree:
    def test_all_three_emit_all_slots(self):
        result = _build_footer_style("Left", "Center", "Right")
        assert "@bottom-left" in result
        assert "@bottom-center" in result
        assert "@bottom-right" in result

    def test_all_three_content_present(self):
        result = _build_footer_style("Left", "Center", "Right")
        assert "Left" in result
        assert "Center" in result
        assert "Right" in result

    def test_all_three_cover_overrides_all_slots(self):
        result = _build_footer_style("Left", "Center", "Right")
        cover_section = result[result.index("@page cover"):]
        assert "@bottom-left" in cover_section
        assert "@bottom-center" in cover_section
        assert "@bottom-right" in cover_section


class TestBuildFooterStyleFontStyle:
    def test_font_size_applied(self):
        result = _build_footer_style("Footer text", None, None)
        assert "6pt" in result

    def test_color_applied(self):
        result = _build_footer_style("Footer text", None, None)
        assert "#7f8c9a" in result

    def test_white_space_pre_applied(self):
        result = _build_footer_style("Footer text", None, None)
        assert "white-space: pre" in result


class TestBuildFooterStyleNewlines:
    def test_newline_converted_to_css_A(self):
        result = _build_footer_style("line1\nline2", None, None)
        assert "\\A " in result
        assert "\n" not in result.split("content:")[1].split(";")[0]

    def test_multiline_center(self):
        text = "Line One\nLine Two\nLine Three"
        result = _build_footer_style(None, text, None)
        assert "\\A " in result
        assert "@bottom-center" in result

    def test_empty_string_suppresses_slot(self):
        result = _build_footer_style("", None, None)
        assert "content: none" in result
        assert "@bottom-left" in result

    def test_empty_center_suppresses_slot(self):
        result = _build_footer_style(None, "", None)
        assert "content: none" in result
        assert "@bottom-center" in result


class TestBuildFooterStyleEscaping:
    def test_ampersand_escaped(self):
        result = _build_footer_style("A & B", None, None)
        assert "&amp;" in result
        assert " & " not in result

    def test_less_than_escaped(self):
        result = _build_footer_style("<Left>", None, None)
        assert "&lt;" in result

    def test_greater_than_escaped(self):
        result = _build_footer_style("<Left>", None, None)
        assert "&gt;" in result

    def test_double_quote_escaped(self):
        result = _build_footer_style('Say "hi"', None, None)
        assert "&quot;" in result

    def test_special_chars_in_center(self):
        result = _build_footer_style(None, "A & B", None)
        assert "&amp;" in result

    def test_special_chars_in_right(self):
        result = _build_footer_style(None, None, '"quoted"')
        assert "&quot;" in result


class TestBuildFooterStyleStructure:
    def test_wraps_in_style_tag(self):
        result = _build_footer_style("Footer", None, None)
        assert result.strip().startswith("<style>")
        assert result.strip().endswith("</style>")

    def test_has_page_at_rule(self):
        result = _build_footer_style("Footer", None, None)
        assert "@page {" in result or "@page{" in result


class TestBuildIntegration:
    """Integration test: build() reads footer_left from config and injects CSS."""

    def test_build_reads_footer_left_from_config(self, tmp_path):
        """build() with footer_left in config produces HTML containing @bottom-left."""
        (tmp_path / ".git").mkdir()
        doc = tmp_path / "report.md"
        doc.write_text("# My Report\n\nSome content.\n")
        out = tmp_path / "report.pdf"

        config = {"footer_left": "Affinity Equine"}

        with patch("weasyprint.HTML") as mock_wp:
            mock_doc = MagicMock()
            mock_wp.return_value = mock_doc

            from md_doc.builders.pdf import build as build_pdf

            build_pdf(
                rendered_md="# My Report\n\nSome content.\n",
                config=config,
                out_path=out,
                doc_path=doc,
                repo_root=tmp_path,
            )

        mock_wp.assert_called_once()
        html_arg = mock_wp.call_args[1]["string"]
        assert "@bottom-left" in html_arg
        assert "Affinity Equine" in html_arg

    def test_build_no_footer_keys_omits_bottom_rules(self, tmp_path):
        """build() with no footer_* keys does not inject @bottom-* rules."""
        (tmp_path / ".git").mkdir()
        doc = tmp_path / "report.md"
        doc.write_text("# My Report\n\nSome content.\n")
        out = tmp_path / "report.pdf"

        config = {}

        with patch("weasyprint.HTML") as mock_wp:
            mock_doc = MagicMock()
            mock_wp.return_value = mock_doc

            from md_doc.builders.pdf import build as build_pdf

            build_pdf(
                rendered_md="# My Report\n\nSome content.\n",
                config=config,
                out_path=out,
                doc_path=doc,
                repo_root=tmp_path,
            )

        mock_wp.assert_called_once()
        html_arg = mock_wp.call_args[1]["string"]
        assert "@bottom-left" not in html_arg
        assert "@bottom-center" not in html_arg
        assert "@bottom-right" not in html_arg
