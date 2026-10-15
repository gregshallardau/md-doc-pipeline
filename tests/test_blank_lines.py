"""Extra blank lines are honoured as vertical space (preserve_blank_lines)."""

from __future__ import annotations

from md_doc.builders.pdf import _inject_blank_lines

SPACER = 'class="md-doc-blank"'


def test_single_blank_line_unchanged():
    src = "One.\n\nTwo.\n"
    assert _inject_blank_lines(src) == src


def test_each_extra_blank_line_adds_one_spacer():
    out = _inject_blank_lines("One.\n\n\n\nTwo.\n")  # three blank lines
    assert out.count(SPACER) == 2
    assert out.startswith("One.") and out.rstrip().endswith("Two.")


def test_whitespace_only_lines_count_as_blank():
    assert _inject_blank_lines("A\n\n \t\nB\n").count(SPACER) == 1


def test_code_blocks_untouched():
    src = "```\na\n\n\n\nb\n```\n"
    assert _inject_blank_lines(src) == src


def test_disabled_collapses():
    src = "A\n\n\n\nB\n"
    assert _inject_blank_lines(src, enabled=False) == src


def test_docx_emits_empty_paragraph(tmp_path):
    from docx import Document

    from md_doc.cli import main as cli
    from click.testing import CliRunner

    (tmp_path / "d.md").write_text(
        "---\ntitle: T\noutputs: [docx]\n---\n\nOne.\n\n\n\nTwo.\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    result = CliRunner().invoke(cli, ["build", str(tmp_path / "d.md"), "--force"])
    assert result.exit_code == 0, result.output
    texts = [p.text for p in Document(str(tmp_path / "d.docx")).paragraphs]
    one, two = texts.index("One."), texts.index("Two.")
    assert two - one == 3 and texts[one + 1 : two] == ["", ""]
