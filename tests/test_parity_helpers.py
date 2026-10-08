"""Regression tests for helpers added during the PDF/Word parity work."""

from __future__ import annotations

from md_doc.forms import collapse_select_markup
from md_doc.table_layout import css_code_line_pitch, css_column_weights, table_html


def test_table_html_strips_images_and_marks_headers() -> None:
    html = table_html([[(True, "H"), (True, "I")], [(False, 'a<img src="x.png">'), (False, "b")]])
    assert "<th>H</th>" in html
    assert "<img" not in html
    assert html.count("<td>") == 2


def test_table_layout_without_theme_is_none(tmp_path) -> None:
    rows = [[(False, "a"), (False, "b")]]
    assert css_column_weights(rows, None, 400) is None
    assert css_column_weights(rows, tmp_path / "missing.css", 400) is None
    assert css_code_line_pitch(None, 400) is None


def test_css_column_weights_follow_content(tmp_path) -> None:
    css = tmp_path / "t.css"
    css.write_text("table { border-collapse: collapse } td { padding: 2pt }")
    rows = [[(False, "x"), (False, "a much longer cell of text " * 3)]]
    widths = css_column_weights(rows, css, 400)
    assert widths is not None and len(widths) == 2
    assert widths[1] > widths[0]


def test_code_line_pitch_is_positive(tmp_path) -> None:
    css = tmp_path / "t.css"
    css.write_text("pre { font-size: 9pt; line-height: 1.4 }")
    pitch = css_code_line_pitch(css, 400)
    assert pitch is not None and pitch > 0


def test_collapse_select_markup_single_line() -> None:
    src = '<select name="a">\n<option>A</option>\n<option>B</option>\n</select>'
    out = collapse_select_markup(src)
    assert "\n" not in out
    assert "<option>B</option>" in out


def test_form_support_css_uses_theme_colour() -> None:
    from md_doc.builders.pdf import _form_support_css

    css = _form_support_css("#1b4f72")
    assert "__" not in css
    assert "#1b4f72" in css  # label colour
    assert "solid #000000" not in css
    assert "#000000" not in _form_support_css(None)


def test_discovery_skips_agent_instruction_files(tmp_path) -> None:
    from md_doc.cli import _discover_markdown

    for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md", "real-doc.md"):
        (tmp_path / name).write_text("# x\n")
    assert [p.name for p in _discover_markdown(tmp_path)] == ["real-doc.md"]
