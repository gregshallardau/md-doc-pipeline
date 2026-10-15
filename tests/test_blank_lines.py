"""Extra blank lines are honoured as vertical space (preserve_blank_lines)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from docx import Document

from md_doc.builders.pdf import _inject_blank_lines
from md_doc.cli import main
from md_doc.renderer import BLANK_MARKER, mark_blank_lines, render

SPACER = 'class="md-doc-blank"'


def _render(tmp_path: Path, text: str, **frontmatter: object) -> str:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    fm = "".join(f"{k}: {v}\n" for k, v in frontmatter.items())
    doc = tmp_path / "d.md"
    doc.write_text(f"---\ntitle: T\n{fm}---\n{text}", encoding="utf-8")
    return render(doc, repo_root=tmp_path)


def test_single_blank_line_unmarked():
    src = "One.\n\nTwo.\n"
    assert mark_blank_lines(src) == src


def test_each_extra_blank_line_adds_one_marker():
    out = mark_blank_lines("One.\n\n\n\nTwo.\n")  # three blank lines
    assert out.count(BLANK_MARKER) == 2
    assert _inject_blank_lines(out).count(SPACER) == 2


def test_whitespace_only_lines_count_as_blank():
    assert mark_blank_lines("A\n\n \t\nB\n").count(BLANK_MARKER) == 1


def test_code_blocks_untouched():
    src = "```\na\n\n\n\nb\n```\n"
    assert mark_blank_lines(src) == src


def test_leading_blank_lines_add_no_space():
    assert BLANK_MARKER not in mark_blank_lines("\n\n\n# Title\n")


def test_jinja_tag_lines_do_not_fake_blank_lines(tmp_path):
    """trim_blocks eats the newline after a tag; that must not look like a blank line."""
    out = _render(
        tmp_path,
        "\nBefore.\n\n{% if true %}\n\nInside.\n\n{% endif %}\n\n"
        "{% for i in [1, 2] %}\n\nItem {{ i }}\n\n{% endfor %}\n\nAfter.\n",
    )
    assert BLANK_MARKER not in out


def test_extra_blank_lines_survive_jinja(tmp_path):
    out = _render(tmp_path, "\nBefore.\n\n\n{% if true %}\nInside.\n{% endif %}\n\n\n\nAfter.\n")
    assert out.count(BLANK_MARKER) == 3  # 1 before the tag + 2 before After.


def test_blank_lines_in_included_fragment(tmp_path):
    (tmp_path / "f.md").write_text("Frag one.\n\n\nFrag two.\n", encoding="utf-8")
    out = _render(tmp_path, '\nTop.\n\n{% include "f.md" %}\n\nBottom.\n')
    assert out.count(BLANK_MARKER) == 1


def test_crlf_source(tmp_path):
    out = _render(tmp_path, "\nOne.\n\n\nTwo.\n").replace("\r", "")
    assert out.count(BLANK_MARKER) == 1
    (tmp_path / "c.md").write_bytes(b"---\r\ntitle: T\r\n---\r\n\r\nOne.\r\n\r\n\r\nTwo.\r\n")
    assert render(tmp_path / "c.md", repo_root=tmp_path).count(BLANK_MARKER) == 1


def test_disabled_collapses(tmp_path):
    out = _render(tmp_path, "\nOne.\n\n\n\nTwo.\n", preserve_blank_lines="false")
    assert BLANK_MARKER not in out


def test_docx_emits_empty_paragraphs(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "d.md").write_text(
        "---\ntitle: T\noutputs: [docx]\n---\n\nOne.\n\n\n\nTwo.\n", encoding="utf-8"
    )
    result = CliRunner().invoke(main, ["build", str(tmp_path / "d.md"), "--force"])
    assert result.exit_code == 0, result.output
    texts = [p.text for p in Document(str(tmp_path / "d.docx")).paragraphs]
    one, two = texts.index("One."), texts.index("Two.")
    assert texts[one + 1 : two] == ["", ""]


def _build_docx(tmp_path: Path, extra: str = "") -> list[str]:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "d.md").write_text(
        f"---\ntitle: T\noutputs: [docx]\n{extra}---\n\nLine one\nLine two\n\n- a\n  b\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, ["build", str(tmp_path / "d.md"), "--force"])
    assert result.exit_code == 0, result.output
    return [p.text for p in Document(str(tmp_path / "d.docx")).paragraphs]


def test_single_newlines_join_by_default(tmp_path):
    texts = _build_docx(tmp_path)
    assert "Line one Line two" in texts and "a b" in texts


def test_preserve_line_breaks_keeps_newlines(tmp_path):
    texts = _build_docx(tmp_path, "preserve_line_breaks: true\n")
    assert "Line one\nLine two" in texts and "a\nb" in texts


def test_preserve_line_breaks_in_pdf_html():
    from md_doc.math import markdown_html

    assert "<br" not in markdown_html("a\nb", [])
    assert "<br" in markdown_html("a\nb", [], line_breaks=True)
