"""A backslash at the end of a line is a hard line break (CommonMark), in every format."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from docx import Document

from md_doc.cli import main
from md_doc.linebreaks import backslash_line_breaks
from md_doc.math import markdown_html


class TestTransform:
    def test_trailing_backslash_becomes_two_spaces(self):
        assert backslash_line_breaks("a\\\nb\n") == "a  \nb\n"

    def test_text_without_backslashes_is_untouched(self):
        text = "one\ntwo\n"
        assert backslash_line_breaks(text) == text

    def test_escaped_backslash_stays_literal(self):
        text = "a \\\\\nb\n"  # a double backslash is an escaped backslash
        assert backslash_line_breaks(text) == text

    def test_three_backslashes_break_after_an_escaped_one(self):
        assert backslash_line_breaks("a\\\\\\\nb\n") == "a\\\\  \nb\n"

    def test_backslash_ending_a_paragraph_stays_literal(self):
        for text in ("end\\\n\nnext\n", "end\\\n", "end\\"):
            assert backslash_line_breaks(text) == text

    def test_fenced_code_is_untouched(self):
        text = "```\nC:\\temp\\\nnext\n```\n"
        assert backslash_line_breaks(text) == text

    def test_inline_code_is_untouched(self):
        text = "path `C:\\temp\\`\nnext\n"
        assert backslash_line_breaks(text) == text

    def test_indented_code_is_untouched(self):
        text = "para\n\n    C:\\dir\\\n    more\n"
        assert backslash_line_breaks(text) == text

    def test_list_item_continuation_is_not_mistaken_for_code(self):
        assert backslash_line_breaks("- one\\\n    two\n") == "- one  \n    two\n"
        assert backslash_line_breaks("- one\n\n    para\\\n    more\n") == (
            "- one\n\n    para  \n    more\n"
        )

    def test_display_math_is_untouched(self):
        text = "$$\na \\\nb\n$$\n"
        assert backslash_line_breaks(text) == text

    def test_table_rows_are_untouched(self):
        text = "| a | b \\\n| --- | --- |\n"
        assert backslash_line_breaks(text) == text

    def test_existing_two_space_breaks_are_unchanged(self):
        text = "a  \nb\n"
        assert backslash_line_breaks(text) == text


class TestHtml:
    def test_backslash_gives_a_br(self):
        assert "<br" in markdown_html("a\\\nb", [])

    def test_without_it_lines_join(self):
        assert "<br" not in markdown_html("a\nb", [])

    def test_no_double_break_with_preserve_line_breaks(self):
        html = markdown_html("a\\\nb", [], line_breaks=True)
        assert html.count("<br") == 1

    def test_list_item(self):
        assert "<br" in markdown_html("- a\\\n  b\n", [])


def _paragraphs(tmp_path: Path, body: str, fmt: str, extra: str = "") -> list[str]:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "d.md").write_text(
        f"---\ntitle: T\noutputs: [{fmt}]\n{extra}---\n\n{body}", encoding="utf-8"
    )
    result = CliRunner().invoke(main, ["build", str(tmp_path / "d.md"), "--force"])
    assert result.exit_code == 0, result.output
    return [p.text for p in Document(str(tmp_path / f"d.{fmt}")).paragraphs]


@pytest.mark.parametrize("fmt", ["docx"])
def test_word_output_breaks_the_line(tmp_path, fmt):
    texts = _paragraphs(tmp_path, "[[Address1]]\\\n[[Address2]]\\\n[[Address3]]\n", fmt)
    assert "[[Address1]]\n[[Address2]]\n[[Address3]]" in texts


def test_dotx_output_breaks_the_line(tmp_path):
    import zipfile

    from lxml import etree

    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "d.md").write_text(
        "---\ntitle: T\noutputs: [dotx]\n---\n\n[[Address1]]\\\n[[Address2]]\n", encoding="utf-8"
    )
    result = CliRunner().invoke(main, ["build", str(tmp_path / "d.md"), "--force"])
    assert result.exit_code == 0, result.output
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    root = etree.fromstring(zipfile.ZipFile(tmp_path / "d.dotx").read("word/document.xml"))
    paragraph = next(p for p in root.iter(f"{{{ns}}}p") if "Address1" in "".join(p.itertext()))
    assert paragraph.find(f".//{{{ns}}}br") is not None


def test_code_block_backslashes_survive_a_build(tmp_path):
    texts = _paragraphs(tmp_path, "```\nC:\\temp\\\nnext\n```\n", "docx")
    assert any("C:\\temp\\" in t for t in texts)
