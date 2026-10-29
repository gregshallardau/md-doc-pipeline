"""Column widths never split a word: ``table_layout.clamp_to_longest_words``."""

from __future__ import annotations

import re

from md_doc.builders.pdf import _apply_table_col_widths
from md_doc.mermaid import _text_w
from md_doc.table_layout import clamp_to_longest_words

ROWS = [
    [(True, "Responsibility"), (True, "Description"), (True, "Owner")],
    [
        (False, "Interdepartmental"),
        (False, "Coordination of the programme"),
        (False, "Commissioner"),
    ],
]


def test_short_column_is_widened_and_the_rest_keeps_its_proportions():
    out = clamp_to_longest_words([10, 60, 30], ROWS, width_pt=450, font_pt=10, pad_pt=12)
    assert abs(sum(out) - 100) < 1e-6
    need = (_text_w("RESPONSIBILITY", 10, 700) * 1.06 + 12) / 450 * 100
    assert out[0] >= need - 1e-6 and out[0] > 10
    assert abs(out[1] / out[2] - 2.0) < 1e-6  # 60:30 still


def test_widths_that_fit_are_returned_unchanged():
    weights = [40, 40, 20]
    assert clamp_to_longest_words(weights, ROWS, width_pt=450) is weights


def test_long_tokens_and_spanned_rows_set_no_minimum():
    rows = [[(False, "https://example.com/" + "x" * 40), (False, "b")], [(False, "only one cell")]]
    assert clamp_to_longest_words([5, 95], rows, width_pt=450) == [5, 95]


def test_minimums_that_cannot_all_fit_share_the_width():
    rows = [[(False, "Supercalifragilistic"), (False, "Antidisestablishment")]]
    out = clamp_to_longest_words([10, 90], rows, width_pt=100, font_pt=10)
    assert abs(sum(out) - 100) < 1e-6 and abs(out[0] - out[1]) < 15


def test_pdf_table_widths_are_clamped():
    html = (
        "<!-- col-widths: 10, 60, 30 --><table><thead><tr><th>Responsibility</th>"
        "<th>Description</th><th>Owner</th></tr></thead><tbody><tr><td>Interdepartmental</td>"
        "<td>Coordination</td><td>Commissioner</td></tr></tbody></table>"
    )
    plain = _apply_table_col_widths(html)
    fitted = _apply_table_col_widths(html, fit=(450.0, 10.0, 12.0))
    first = [float(w) for w in re.findall(r'<th style="width: ([\d.]+)%', plain)]
    clamped = [float(w) for w in re.findall(r'<th style="width: ([\d.]+)%', fitted)]
    assert first[0] == 10.0 and clamped[0] > 10.0
    assert abs(sum(clamped) - 100) < 0.01
