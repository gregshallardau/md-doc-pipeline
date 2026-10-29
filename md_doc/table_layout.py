"""CSS auto table layout for Word tables.

A browser or WeasyPrint sizes table columns to their content (CSS 2.1 auto
layout); Word's fixed grid has no such behaviour, so equal columns wrap text
the PDF keeps on one line and every row comes out taller. Rather than
approximating text metrics, lay the table out with WeasyPrint itself, using the
same theme CSS the PDF is built from, and hand the resulting column widths to
the Word builder.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

_log = logging.getLogger(__name__)

_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


_LONG_TOKEN_RE = re.compile(r"\S{25,}")
_TEXT_RE = re.compile(r">([^<>]+)<")


def soften_long_tokens(html: str) -> str:
    """Let very long unbreakable strings (URLs, hashes) wrap inside table cells.

    ``overflow-wrap: anywhere`` on a whole cell also makes every column's
    minimum width one character, which collapses short columns. Cells use
    ``break-word`` instead, and only tokens beyond 24 characters are wrapped in
    a span that may break anywhere. The text itself is unchanged.
    """
    return _TEXT_RE.sub(
        lambda m: ">"
        + _LONG_TOKEN_RE.sub(lambda t: f'<span class="md-wrap">{t.group(0)}</span>', m.group(1))
        + "<",
        html,
    )


def table_html(rows: list[list[tuple[bool, str]]]) -> str:
    """Build a plain ``<table>`` from rows of ``(is_header, cell_html)`` pairs."""
    out = ["<table>"]
    for row in rows:
        cells = []
        for is_header, html in row:
            tag = "th" if is_header else "td"
            cells.append(f"<{tag}>{_IMG_RE.sub('', html)}</{tag}>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return soften_long_tokens("".join(out))


@lru_cache(maxsize=256)
def _layout(
    html: str, css_path: str, css_mtime: float, width_pt: float
) -> tuple[float, ...] | None:
    del css_mtime  # part of the cache key only: a changed theme must re-layout
    try:
        from weasyprint import CSS, HTML
        from .builders.pdf import _BASE_FIXES_CSS

        path = Path(css_path)
        document = HTML(
            string=(
                '<!doctype html><html><body><div class="report-body">' f"{html}</div></body></html>"
            ),
            base_url=str(path.parent) + "/",
        ).render(
            stylesheets=[
                CSS(filename=str(path)),
                CSS(string=re.sub(r"</?style>", "", _BASE_FIXES_CSS)),
                CSS(string=f"@page {{ size: {width_pt}pt 4000pt; margin: 0 }}"),
            ]
        )
        page_box = document.pages[0]._page_box
        cells = [b for b in page_box.descendants() if type(b).__name__ == "TableCellBox"]
        if not cells:
            return None
        first_row_y = min(b.position_y for b in cells)
        first_row = sorted(
            (b for b in cells if abs(b.position_y - first_row_y) < 0.5),
            key=lambda b: b.position_x,
        )
        widths = tuple(float(b.border_width()) for b in first_row)
        return widths if widths and all(w > 0 for w in widths) else None
    except Exception:  # noqa: BLE001 - layout is an enhancement, never fatal
        _log.debug("CSS table layout unavailable; using equal columns", exc_info=True)
        return None


def css_column_weights(
    rows: list[list[tuple[bool, str]]], css_path: Path | None, text_width_pt: float
) -> list[float] | None:
    """Relative column widths WeasyPrint gives this table, or ``None``.

    Returns ``None`` when the theme is unknown, layout fails, or the number of
    laid-out columns differs from the table's (spans, ragged rows).
    """
    if css_path is None or not css_path.is_file() or not rows:
        return None
    columns = max(len(row) for row in rows)
    widths = _layout(
        table_html(rows), str(css_path), css_path.stat().st_mtime, round(text_width_pt, 2)
    )
    if widths is None or len(widths) != columns:
        return None
    return list(widths)


@lru_cache(maxsize=32)
def _code_pitch(css_path: str, css_mtime: float, width_pt: float) -> float | None:
    del css_mtime  # cache key only
    try:
        from weasyprint import CSS, HTML

        path = Path(css_path)
        document = HTML(
            string=(
                '<!doctype html><html><body><div class="report-body">'
                "<pre><code>line\nline\nline\nline\nline</code></pre></div></body></html>"
            ),
            base_url=str(path.parent) + "/",
        ).render(
            stylesheets=[
                CSS(filename=str(path)),
                CSS(string=f"@page {{ size: {width_pt}pt 4000pt; margin: 0 }}"),
            ]
        )
        page_box = document.pages[0]._page_box
        pre = next(
            (
                b
                for b in page_box.descendants()
                if getattr(b, "element_tag", None) == "pre" and type(b).__name__ == "BlockBox"
            ),
            None,
        )
        if pre is None:
            return None
        tops = sorted(
            {round(b.position_y, 3) for b in pre.descendants() if type(b).__name__ == "LineBox"}
        )
        if len(tops) < 3:
            return None
        return (tops[-1] - tops[0]) / (len(tops) - 1) * 0.75  # CSS px -> pt
    except Exception:  # noqa: BLE001 - layout is an enhancement, never fatal
        _log.debug("CSS code layout unavailable; using font-size x line-height", exc_info=True)
        return None


def css_code_line_pitch(css_path: Path | None, text_width_pt: float) -> float | None:
    """Distance between consecutive code-block lines (pt) in the PDF layout, or ``None``.

    A monospace font nested in a body-font ``<pre>`` makes the line box taller than
    ``font-size x line-height``; measure it instead of assuming.
    """
    if css_path is None or not css_path.is_file():
        return None
    return _code_pitch(str(css_path), css_path.stat().st_mtime, round(text_width_pt, 2))


def _form_extra_css() -> str:
    """The stylesheet the PDF builder adds on top of the theme for form documents."""
    import re as _re

    from .builders import pdf as _pdf

    return _re.sub(r"</?style>", "", _pdf._BASE_FIXES_CSS + _pdf._form_support_css(None))


@lru_cache(maxsize=256)
def _row_heights(
    html: str, css_path: str, css_mtime: float, width_pt: float
) -> tuple[float, ...] | None:
    del css_mtime  # cache key only
    try:
        from weasyprint import CSS, HTML

        path = Path(css_path)
        document = HTML(
            string=(
                '<!doctype html><html><body><div class="report-body"><form>'
                f"{html}</form></div></body></html>"
            ),
            base_url=str(path.parent) + "/",
        ).render(
            stylesheets=[
                CSS(filename=str(path)),
                CSS(string=_form_extra_css()),
                CSS(string=f"@page {{ size: {width_pt}pt 4000pt; margin: 0 }}"),
            ]
        )
        page_box = document.pages[0]._page_box
        rows = [b for b in page_box.descendants() if type(b).__name__ == "TableRowBox"]
        heights = tuple(round(float(b.height) * 0.75, 2) for b in rows)  # CSS px -> pt
        return heights if heights and all(h > 0 for h in heights) else None
    except Exception:  # noqa: BLE001 - layout is an enhancement, never fatal
        _log.debug("PDF form row layout unavailable; using fitted heights", exc_info=True)
        return None


def css_row_heights(html: str, css_path: Path | None, width_pt: float) -> list[float] | None:
    """Row heights (pt) the PDF gives a form table, laid out with the real theme CSS."""
    if css_path is None or not css_path.is_file():
        return None
    heights = _row_heights(html, str(css_path), css_path.stat().st_mtime, round(width_pt, 2))
    return list(heights) if heights else None


_TAG_RE = re.compile(r"<[^>]+>")


def _cell_words(html: str) -> list[str]:
    import html as html_lib

    text = html_lib.unescape(_TAG_RE.sub(" ", html))
    # Long tokens (URLs, hashes) are allowed to break anywhere; they never set a minimum
    return [w for w in text.split() if not _LONG_TOKEN_RE.fullmatch(w)]


def clamp_to_longest_words(
    weights: list[float],
    rows: list[list[tuple[bool, str]]],
    width_pt: float,
    font_pt: float = 10.0,
    pad_pt: float = 12.0,
) -> list[float]:
    """Widen columns that are narrower than their longest word.

    ``weights`` are the author's relative widths (``<!-- col-widths -->`` or
    ``table_col_widths``) and ``rows`` the table's ``(is_header, cell_html)``
    cells. A fixed-layout column narrower than a word breaks that word in the
    middle, so each column gets at least its longest word plus its horizontal
    padding (``pad_pt``), and the rest of the width is shared by the other
    columns in the proportions the author gave. If even the minimums do not fit,
    the columns are sized to their minimums' proportions. Returns new weights
    summing to 100, or ``weights`` unchanged when no column needed widening.
    """
    from .mermaid import _text_w

    n = len(weights)
    total = sum(weights)
    if n == 0 or total <= 0 or width_pt <= 0:
        return weights
    need = [0.0] * n
    for row in rows:
        if len(row) != n:
            continue  # rows with spans cannot be matched to columns
        for i, (is_header, cell) in enumerate(row):
            for word in _cell_words(cell):
                if is_header:  # themes often set th in capitals: measure the wider form
                    word = word.upper()
                w = _text_w(word, font_pt, 700 if is_header else 400) * 1.06 + pad_pt
                need[i] = max(need[i], w / width_pt)
    share = [w / total for w in weights]
    if all(s >= m for s, m in zip(share, need)):
        return weights
    if sum(need) >= 1:
        return [m / sum(need) * 100 for m in need]
    fixed: set[int] = set()
    result = list(share)
    while True:
        free = 1 - sum(need[i] for i in fixed)
        flex = [i for i in range(n) if i not in fixed]
        flex_total = sum(share[i] for i in flex) or 1.0
        for i in flex:
            result[i] = share[i] / flex_total * free
        short = [i for i in flex if result[i] < need[i]]
        if not short:
            break
        for i in short:
            fixed.add(i)
            result[i] = need[i]
    return [r * 100 for r in result]
