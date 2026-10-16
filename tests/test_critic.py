"""CriticMarkup review marks: resolve, render, lint and round-trip through Word."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from md_doc import critic
from md_doc.cli import main

SAMPLE = """---
title: T
note: "{++frontmatter stays++}"
---
# {++New ++}title

Hello {--old --}{~~colour~>color~~} {==world==}{>>check *this*<<} end.

- {++added item++}
- keep
- {--gone item--}

before

{++
para one

para two
++}

after

`{++code++}`

```
{--fenced--}
```
"""


def test_accept_applies_every_change():
    out = critic.apply(SAMPLE, "accept")
    assert "# New title" in out
    assert "Hello color world end." in out
    assert "- added item\n- keep\n" in out and "gone item" not in out
    assert "para one\n\npara two" in out
    assert "check" not in out


def test_reject_reverts_every_change():
    out = critic.apply(SAMPLE, "reject")
    assert "# title" in out
    assert "Hello old colour world end." in out
    assert "- keep\n- gone item" in out and "added item" not in out
    assert "para one" not in out


def test_code_and_frontmatter_are_left_alone():
    for mode in critic.MODES:
        out = critic.apply(SAMPLE, mode)
        assert 'note: "{++frontmatter stays++}"' in out
        assert "`{++code++}`" in out
        assert "{--fenced--}" in out


def test_removed_marks_leave_no_stray_lines():
    reject = critic.apply("a\n\n{++\nnew para\n++}\n\nb\n- {++x++}\n", "reject")
    assert reject == "a\n\nb\n"
    accept = critic.apply("a\n\n{++\nnew para\n++}\n\nb\n", "accept")
    assert accept == "a\n\nnew para\n\nb\n"
    assert critic.apply("## {--Old heading--}\n\ntext\n", "accept").strip() == "text"


def test_show_renders_inline_html():
    out = critic.apply(SAMPLE, "show")
    assert '# <ins class="critic-ins">New</ins> title' in out
    assert '<del class="critic-del">old</del> <del class="critic-del">colour</del>' in out
    assert '<ins class="critic-ins">color</ins>' in out
    assert '<mark class="critic-hl">world</mark>' in out
    assert '<span class="critic-comment" data-comment="check *this*"></span>' in out
    assert '- <ins class="critic-ins">added item</ins>' in out
    assert '<ins class="critic-ins">para one</ins>\n\n<ins class="critic-ins">para two</ins>' in out


def test_show_wraps_table_cells_not_the_row():
    out = critic.apply("| a | b |\n|---|---|\n| {++x++} | y |\n", "show")
    assert '| <ins class="critic-ins">x</ins> | y |' in out
    assert "|---|---|" in out


def test_comment_text_is_escaped():
    out = critic.apply('{>>say "hi" <b>now</b><<}', "show")
    assert 'data-comment="say &quot;hi&quot; &lt;b&gt;now&lt;/b&gt;"' in out


def test_slides_cannot_show_review_marks():
    assert critic.apply("{++a++}{--b--}", "show", fmt="pptx") == "a"


def test_modes_and_defaults():
    assert critic.review_mode({}) == "accept"
    assert critic.review_mode({"review_markup": "SHOW"}) == "show"
    assert critic.review_mode({"review_markup": "bogus"}) == "accept"
    assert critic.review_author({}) == "Reviewer"
    assert critic.review_author({"review_author": " Ada L "}) == "Ada L"
    assert critic.apply("no marks here {x}", "show") == "no marks here {x}"


def test_stamp_honours_source_date_epoch(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "86400")
    assert critic.review_stamp() == "1970-01-02T00:00:00Z"


def test_problems_report_only_broken_marks():
    found = critic.problems("ok {++a++}\nbad {++ b\n\n{~~x~~}\n`{--code`\n")
    assert [line for line, _ in found] == [2, 4]
    assert "never closed" in found[0][1] and "~>" in found[1][1]
    assert critic.problems("{++a++} {--b--} {~~c~>d~~} {==e==}{>>f<<}") == []


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

DOC = """---
title: Review
author: Ada
review_author: Greg Shallard
---
# Review

Hello {--old --}{~~colour~>color~~} {==world==}{>>Check this<<} end.

- {++New bullet++}

| A | B |
|---|---|
| {++x++} | {--y--} |
"""


def build_docx(tmp_path: Path, mode: str | None) -> Path:
    from md_doc.builders import docx

    (tmp_path / ".git").mkdir(exist_ok=True)
    config = {"title": "Review", "review_author": "Greg Shallard"}
    if mode:
        config["review_markup"] = mode
    out = tmp_path / f"{mode}.docx"
    docx.build(DOC, config, out, repo_root=tmp_path, doc_path=tmp_path / "d.md")
    return out


def xml_of(path: Path, part: str = "word/document.xml") -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read(part).decode()


def test_word_show_builds_tracked_changes_and_comments(tmp_path):
    from docx import Document

    out = build_docx(tmp_path, "show")
    xml = xml_of(out)
    assert len(re.findall(r"<w:ins ", xml)) == 2  # color, New bullet
    assert len(re.findall(r"<w:del ", xml)) == 2  # old, colour
    assert len(re.findall(r"<w:delText", xml)) == 2
    assert 'w:author="Greg Shallard"' in xml
    assert 'w:highlight w:val="yellow"' in xml
    comments = [(c.author, c.text) for c in Document(str(out)).comments]
    assert comments == [("Greg Shallard", "Check this")]
    assert "commentRangeStart" in xml


def test_word_table_cells_show_marks_as_formatting(tmp_path):
    xml = xml_of(build_docx(tmp_path, "show"))
    assert "<w:strike/>" in xml and "<w:u " in xml


@pytest.mark.parametrize("mode", [None, "accept", "reject"])
def test_word_clean_modes_have_no_revisions(tmp_path, mode):
    out = build_docx(tmp_path, mode)
    xml = xml_of(out)
    assert "<w:ins " not in xml and "<w:del " not in xml
    assert "word/comments.xml" not in zipfile.ZipFile(out).namelist()
    from docx import Document

    text = " ".join(p.text for p in Document(str(out)).paragraphs)
    assert ("Hello color" in text) == (mode != "reject")
    assert ("Hello old colour" in text) == (mode == "reject")


def test_pdf_show_renders_marks_and_comment_footnotes(tmp_path, monkeypatch):
    weasyprint = pytest.importorskip("weasyprint")
    from md_doc.builders import pdf

    seen = {}
    real = weasyprint.HTML.render

    def spy(self, *a, **k):
        seen["document"] = real(self, *a, **k)
        return seen["document"]

    monkeypatch.setattr(weasyprint.HTML, "render", spy)
    (tmp_path / ".git").mkdir()
    captured = {}
    real_write = pdf._write_pdf
    monkeypatch.setattr(
        pdf,
        "_write_pdf",
        lambda html, base, out, options: (
            captured.update(html=html),
            real_write(html, base, out, options),
        ),
    )
    pdf.build(
        DOC,
        {"review_markup": "show"},
        tmp_path / "o.pdf",
        repo_root=tmp_path,
        doc_path=tmp_path / "d.md",
    )
    assert "ins.critic-ins" in captured["html"] and 'class="critic-ins"' in captured["html"]
    page = seen["document"].pages[0]._page_box
    assert any(type(c).__name__ == "FootnoteAreaBox" for c in page.children)
    texts = " ".join(b.text for b in page.descendants() if type(b).__name__ == "TextBox")
    assert "Check this" in texts

    pdf.build(DOC, {}, tmp_path / "o.pdf", repo_root=tmp_path, doc_path=tmp_path / "d.md")
    assert "critic-" not in captured["html"] and "Check this" not in captured["html"]


# ---------------------------------------------------------------------------
# Extract, lint, schema, CLI
# ---------------------------------------------------------------------------


def test_tracked_changes_round_trip_through_extract(tmp_path):
    from md_doc.extractors import extract_file

    text = extract_file(str(build_docx(tmp_path, "show")))
    assert "{--old--}" in text
    assert "{~~colour~>color~~}" in text
    assert "{==world==}{>>Check this<<}" in text
    assert "{++New bullet++}" in text


def test_extract_leaves_clean_documents_alone(tmp_path):
    from md_doc.extractors import extract_file

    text = extract_file(str(build_docx(tmp_path, "accept")))
    assert "{++" not in text and "{--" not in text and "color" in text


def lint(tmp_path: Path, frontmatter: str, body: str):
    from md_doc.linter import lint_file

    (tmp_path / ".git").mkdir(exist_ok=True)
    doc = tmp_path / "d.md"
    doc.write_text(f"---\ntitle: T\n{frontmatter}---\n{body}")
    return lint_file(doc, repo_root=tmp_path)


def test_lint_flags_broken_marks_and_final_documents(tmp_path):
    issues = lint(tmp_path, "", "# T\n\nbad {++ mark\n")
    assert any(i.severity == "error" and "never closed" in i.message for i in issues)
    issues = lint(tmp_path, "status: final\n", "# T\n\nOk {++add++}\n")
    assert [i.severity for i in issues] == ["warning"] and "final" in issues[0].message
    assert lint(tmp_path, "status: draft\n", "# T\n\nOk {++add++}\n") == []
    assert lint(tmp_path, "status: final\n", "# T\n\n`{++code++}`\n") == []


def test_schema_checks_the_review_keys():
    from md_doc.config_schema import validate_config

    assert validate_config({"review_markup": "show", "review_author": "Ada"}) == []
    assert validate_config({"review_markup": "maybe"})[0][0] == "error"


def test_cli_review_flag_overrides_the_config(tmp_path):
    (tmp_path / ".git").mkdir()
    doc = tmp_path / "d.md"
    doc.write_text("---\ntitle: T\noutputs: [docx]\n---\n# T\n\nHello {++there++}.\n")
    runner = CliRunner()
    result = runner.invoke(main, ["build", str(doc), "--review", "show", "--force"])
    assert result.exit_code == 0, result.output
    assert "<w:ins " in xml_of(tmp_path / "d.docx")
    result = runner.invoke(main, ["build", str(doc), "--force"])
    assert result.exit_code == 0, result.output
    assert "<w:ins " not in xml_of(tmp_path / "d.docx")


# ---------------------------------------------------------------------------
# simple mode and review_exports
# ---------------------------------------------------------------------------

BAR = '<span class="critic-bar"></span>'


def test_simple_applies_changes_and_marks_them():
    out = critic.apply(SAMPLE, "simple")
    assert f"# {BAR}New title" in out
    assert f"Hello {BAR}{BAR}color " in out  # deletion marker, then the new text
    assert f"- {BAR}added item\n- keep\n" in out
    assert "gone item" not in out and "removed" not in out
    assert '<mark class="critic-hl">world</mark>' in out
    assert 'data-comment="check *this*"' in out
    assert "<ins" not in out and "<del" not in out


def test_simple_drops_wholly_deleted_lines():
    out = critic.apply("a\n\n{--\nremoved para\n--}\n\n- {--gone--}\n- keep\n", "simple")
    assert out == "a\n\n- keep\n"


def test_simple_is_accept_for_slides():
    assert critic.apply("{++a++}{--b--}", "simple", fmt="pptx") == "a"


def test_changed_blocks_get_a_class():
    html = critic.mark_changed_blocks(
        f'<h1>{BAR}T</h1><ul><li>a<ul><li>{BAR}b</li></ul></li></ul><p class="x">{BAR}q</p><p>z</p>'
    )
    assert '<h1 class="critic-changed">' in html
    assert '<li class="critic-changed">' in html and html.count("critic-changed") == 3
    assert '<p class="critic-changed x">' in html and "<p>z</p>" in html


def test_pdf_simple_draws_change_bars_and_keeps_comments(tmp_path, monkeypatch):
    weasyprint = pytest.importorskip("weasyprint")
    from md_doc.builders import pdf

    captured = {}
    real_write = pdf._write_pdf
    monkeypatch.setattr(
        pdf,
        "_write_pdf",
        lambda html, base, out, opts: (
            captured.update(html=html),
            real_write(html, base, out, opts),
        ),
    )
    (tmp_path / ".git").mkdir()
    pdf.build(
        DOC,
        {"review_markup": "simple"},
        tmp_path / "o.pdf",
        repo_root=tmp_path,
        doc_path=tmp_path / "d.md",
    )
    html = captured["html"]
    assert 'class="critic-changed"' in html and ".critic-changed::before" in html
    assert 'data-comment="Check this"' in html
    assert "<ins" not in html.split("<body>")[1] and weasyprint is not None


def test_word_simple_has_change_bars_comments_and_no_revisions(tmp_path):
    from docx import Document

    out = build_docx(tmp_path, "simple")
    xml = xml_of(out)
    assert "<w:ins " not in xml and "<w:del " not in xml
    assert 'w:left w:val="single"' in xml and 'w:highlight w:val="yellow"' in xml
    assert [c.text for c in Document(str(out)).comments] == ["Check this"]


def test_show_titles_are_clean_text(tmp_path, monkeypatch):
    from md_doc.builders import pdf

    assert pdf._extract_title('# <ins class="critic-ins">New</ins> title\n') == "New title"


def write_variants_doc(tmp_path: Path, exports: str) -> Path:
    (tmp_path / ".git").mkdir(exist_ok=True)
    doc = tmp_path / "report.md"
    doc.write_text(
        f"---\ntitle: T\noutputs: [docx]\nreview_exports: {exports}\n---\n"
        "# T\n\nHello {--old --}{~~colour~>color~~} there.\n"
    )
    return doc


def test_review_exports_writes_one_file_per_variant(tmp_path):
    doc = write_variants_doc(tmp_path, "[clean, original, simple, markup]")
    result = CliRunner().invoke(main, ["build", str(doc), "--force"])
    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in tmp_path.glob("*.docx"))
    assert names == [
        "report-clean.docx",
        "report-markup.docx",
        "report-original.docx",
        "report-simple.docx",
    ]
    assert "<w:ins " in xml_of(tmp_path / "report-markup.docx")
    assert "<w:ins " not in xml_of(tmp_path / "report-clean.docx")
    assert "<w:left " in xml_of(tmp_path / "report-simple.docx")


def test_review_flag_replaces_review_exports(tmp_path):
    doc = write_variants_doc(tmp_path, "[clean, markup]")
    result = CliRunner().invoke(main, ["build", str(doc), "--review", "show", "--force"])
    assert result.exit_code == 0, result.output
    assert [p.name for p in tmp_path.glob("*.docx")] == ["report.docx"]
    assert "<w:ins " in xml_of(tmp_path / "report.docx")


def test_review_exports_are_incremental_and_validated(tmp_path):
    from md_doc.config_schema import validate_config

    doc = write_variants_doc(tmp_path, "full")
    first = CliRunner().invoke(main, ["build", str(doc)])
    again = CliRunner().invoke(main, ["build", str(doc)])
    assert "report-markup.docx" in first.output and "up to date" in again.output
    assert validate_config({"review_exports": ["clean", "simple"]}) == []
    assert validate_config({"review_exports": ["nope"]})[0][0] == "error"
    assert validate_config({"review_markup": "simple"}) == []


def test_changes_inside_a_callout_mark_the_whole_box():
    html = critic.mark_changed_blocks(
        f"<blockquote><p>a</p><ul><li>{BAR}b</li></ul></blockquote><blockquote><p>c</p></blockquote>"
    )
    assert html.startswith('<blockquote class="critic-changed">')
    assert html.count("critic-changed") == 1 and "<li>" in html


def test_word_callout_paragraphs_get_the_bar_on_the_other_side(tmp_path):
    from md_doc.builders import docx

    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / "_pdf-theme.css").write_text(
        "blockquote { background: #eef5fa; border-left: 3pt solid #2e86c1; padding: 6pt 10pt; }"
    )
    out = tmp_path / "c.docx"
    docx.build(
        "# T\n\n> **Note**\n>\n> Callout with {++new text++}.\n\nPlain {++new++} line.\n",
        {"title": "T", "review_markup": "simple"},
        out,
        repo_root=tmp_path,
        doc_path=tmp_path / "d.md",
    )
    xml = xml_of(out)
    # Both callout paragraphs (the whole box) get the right-hand bar; the plain one the left.
    assert xml.count('<w:right w:val="single" w:sz="12" w:space="8" w:color="CF222E"/>') == 2
    assert xml.count('<w:left w:val="single" w:sz="12" w:space="8" w:color="CF222E"/>') == 1
