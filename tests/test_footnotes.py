"""Word page footnotes and the WeasyPrint footnote rounding fix."""

from md_doc.footnotes import extract_notes, mark_for_word
from md_doc.math import markdown_html

SOURCE = "A[^a] and B[^a] and C[^b].\n\n[^a]: Note *one*.\n\n    Second para.\n[^b]: Two.\n"


def _html() -> str:
    return markdown_html(SOURCE, ["footnotes"])


def test_extract_notes_strips_list_and_backrefs():
    html, notes = extract_notes(_html())
    assert 'class="footnote"' not in html
    assert notes["a"] == "Note <em>one</em>.<br>Second para."
    assert notes["b"] == "Two."
    assert "footnote-backref" not in "".join(notes.values())


def test_mark_for_word_numbers_each_reference():
    html, notes = mark_for_word(_html())
    assert notes == [
        "Note <em>one</em>.<br>Second para.",
        "Note <em>one</em>.<br>Second para.",
        "Two.",
    ]
    assert '<sup class="md-doc-fnref" data-fn="2"></sup>' in html


def test_html_without_footnotes_is_unchanged():
    html = markdown_html("Plain.", ["footnotes"])
    assert mark_for_word(html) == (html, [])


def test_fractional_footnote_spacing_keeps_note_on_its_page(tmp_path):
    # WeasyPrint compares float sums without tolerance; 0.5pt border + 5pt
    # padding used to push a fitting note to a second page.
    import pypdfium2

    from md_doc.builders.pdf import _write_pdf

    html = (
        "<style>@page { size: A4; margin: 33mm 36mm 24mm 36mm;"
        " @footnote { border-top: 0.5pt solid black; padding-top: 5pt; margin-top: 8pt;"
        " max-height: 50%; } }"
        " .md-footnote { float: footnote; font-size: 8pt; line-height: 1.4; }</style>"
        '<p>Short line.<span class="md-footnote">A note.</span></p>'
    )
    out = tmp_path / "n.pdf"
    _write_pdf(html, str(tmp_path), out, {})
    assert len(pypdfium2.PdfDocument(str(out))) == 1


def test_real_footnote_overflow_still_continues(tmp_path):
    import pypdfium2

    from md_doc.builders.pdf import _write_pdf

    note = '<span class="md-footnote">' + "A long note that wraps. " * 6 + "</span>"
    html = (
        "<style>@page { size: A4; @footnote { max-height: 50%; } }"
        " .md-footnote { float: footnote; font-size: 8pt; }</style>"
        + "".join(f"<p>Line {i}.{note}</p>" for i in range(60))
    )
    out = tmp_path / "m.pdf"
    _write_pdf(html, str(tmp_path), out, {})
    assert len(pypdfium2.PdfDocument(str(out))) > 1
