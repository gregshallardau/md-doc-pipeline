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

    def test_root_theme_css_found_for_root_doc(self, tmp_repo):
        """A hand-written _theme.css at the repo root applies to a doc at the root.

        Regression: the candidate walk excluded the repo root itself, so the
        root theme was skipped and a default _pdf-theme.css was generated next
        to it, silently shadowing the brand theme forever after.
        """
        css = tmp_repo / "_theme.css"
        css.write_text("body { color: navy; }")
        doc = tmp_repo / "form.md"
        doc.write_text("# F\n")
        result = _resolve_css({}, tmp_repo, doc_path=doc)
        assert result == css.resolve()
        assert not (tmp_repo / "_pdf-theme.css").exists()  # no shadow generated

    def test_root_theme_css_found_for_subdir_doc(self, tmp_repo):
        css = tmp_repo / "_theme.css"
        css.write_text("body { color: navy; }")
        sub = tmp_repo / "clients"
        sub.mkdir()
        doc = sub / "form.md"
        doc.write_text("# F\n")
        assert _resolve_css({}, tmp_repo, doc_path=doc) == css.resolve()

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
        html = self._built_html(tmp_repo, {"cover_page": True, "cover_text_align": "right"})
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

    def test_cover_page_defaults_to_false(self, tmp_repo):
        # Absent cover_page ⇒ no cover; the leading H1 stays in the body.
        no_cfg = self._built_html(tmp_repo, {})
        assert '<div class="cover' not in no_cfg
        assert "<!-- COVER PAGE -->" not in no_cfg
        # Opt in explicitly to get one.
        with_cover = self._built_html(tmp_repo, {"cover_page": True})
        assert '<div class="cover' in with_cover


class TestCssVars:
    """css_vars — override a CSS asset/value per-document from YAML."""

    def _style(self, tmp_repo, css_vars):
        from md_doc.builders.pdf import _build_css_vars_style

        doc = tmp_repo / "doc.md"
        doc.write_text("# x\n")
        return _build_css_vars_style({"css_vars": css_vars}, tmp_repo, doc)

    def test_image_asset_becomes_file_url(self, tmp_repo):
        from PIL import Image

        Image.new("RGB", (10, 10), "navy").save(tmp_repo / "wm.png")
        style = self._style(tmp_repo, {"cover-watermark": "wm.png"})
        assert "--cover-watermark: url(" in style
        assert style.count("file://") == 1 and "wm.png" in style

    def test_literal_value_injected_verbatim(self, tmp_repo):
        style = self._style(tmp_repo, {"accent": "#ff8800"})
        assert "--accent: #ff8800;" in style

    def test_missing_asset_is_skipped(self, tmp_repo):
        style = self._style(tmp_repo, {"cover-watermark": "nope.png"})
        assert "cover-watermark" not in style

    def test_invalid_name_is_skipped(self, tmp_repo):
        style = self._style(tmp_repo, {"bad name}": "#fff"})
        assert style == ""

    def test_literal_value_cannot_break_out_of_block(self, tmp_repo):
        style = self._style(tmp_repo, {"x": "red; } body { display:none"})
        assert "}" not in style.split(":root")[1].split("--x:")[1].split("\n")[0]

    def test_no_css_vars_emits_nothing(self, tmp_repo):
        assert self._style(tmp_repo, None) == ""
        assert self._style(tmp_repo, {}) == ""


class TestBodyAlignTableCells:
    def test_justify_excludes_table_cells(self):
        from md_doc.builders.pdf import _build_body_align_style

        style = _build_body_align_style({"body_text_align": "justify"})
        assert ".report-body { text-align: justify; }" in style
        assert ".report-body th, .report-body td { text-align: left; }" in style

    def test_other_alignments_cascade_into_cells(self):
        from md_doc.builders.pdf import _build_body_align_style

        style = _build_body_align_style({"body_text_align": "center"})
        assert "td" not in style


class TestApplyTableColWidths:
    def _html(self, md_text: str) -> str:
        import markdown

        return markdown.markdown(md_text, extensions=["tables"])

    def test_comment_binds_to_next_table(self):
        from md_doc.builders.pdf import _apply_table_col_widths

        html = self._html("| A | B |\n| --- | --- |\n| 1 | 2 |")
        html = "<!-- col-widths: 25, 75 -->\n" + html
        out = _apply_table_col_widths(html)
        assert 'style="width: 25.0000%;"' in out
        assert 'style="width: 75.0000%;"' in out
        assert "table-layout: fixed" in out

    def test_comment_beats_config(self):
        from md_doc.builders.pdf import _apply_table_col_widths

        html = "<!-- col-widths: 10, 90 -->\n" + self._html("| A | B |\n| --- | --- |\n| 1 | 2 |")
        out = _apply_table_col_widths(html, [50.0, 50.0])
        assert "width: 10.0000%" in out and "width: 90.0000%" in out
        assert "width: 50.0000%" not in out

    def test_config_applies_to_matching_tables_only(self):
        from md_doc.builders.pdf import _apply_table_col_widths

        two = self._html("| A | B |\n| --- | --- |\n| 1 | 2 |")
        three = self._html("| X | Y | Z |\n| --- | --- | --- |\n| 1 | 2 | 3 |")
        out = _apply_table_col_widths(two + three, [30.0, 70.0])
        assert "width: 30.0000%" in out and "width: 70.0000%" in out
        # the 3-column table is untouched — no fixed layout forced onto it
        assert out.count("table-layout: fixed") == 1

    def test_mismatched_comment_is_ignored(self):
        from md_doc.builders.pdf import _apply_table_col_widths

        html = "<!-- col-widths: 30, 70 -->\n" + self._html(
            "| X | Y | Z |\n| --- | --- | --- |\n| 1 | 2 | 3 |"
        )
        out = _apply_table_col_widths(html)
        assert "width:" not in out and "table-layout" not in out

    def test_classed_tables_are_left_alone(self):
        from md_doc.builders.pdf import _apply_table_col_widths

        html = '<table class="field-box"><tr><td>a</td><td>b</td></tr></table>'
        out = _apply_table_col_widths(html, [30.0, 70.0])
        assert out == html

    def test_column_alignment_style_is_preserved(self):
        from md_doc.builders.pdf import _apply_table_col_widths

        html = "<!-- col-widths: 40, 60 -->\n" + self._html("| L | C |\n| --- | :---: |\n| a | b |")
        out = _apply_table_col_widths(html)
        assert "width: 60.0000%; text-align: center;" in out


class TestDropEmptyTableHeaders:
    def test_all_empty_thead_removed(self):
        from md_doc.builders._assets import _drop_empty_table_headers

        html = (
            "<table><thead>\n<tr>\n<th></th>\n<th></th>\n</tr>\n</thead><tbody>...</tbody></table>"
        )
        assert "<thead>" not in _drop_empty_table_headers(html)

    def test_populated_thead_kept(self):
        from md_doc.builders._assets import _drop_empty_table_headers

        html = "<table><thead>\n<tr>\n<th>A</th>\n<th></th>\n</tr>\n</thead></table>"
        assert "<thead>" in _drop_empty_table_headers(html)
