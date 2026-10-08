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
    return "".join(out)


@lru_cache(maxsize=256)
def _layout(
    html: str, css_path: str, css_mtime: float, width_pt: float
) -> tuple[float, ...] | None:
    del css_mtime  # part of the cache key only: a changed theme must re-layout
    try:
        from weasyprint import CSS, HTML

        path = Path(css_path)
        document = HTML(
            string=(
                '<!doctype html><html><body><div class="report-body">' f"{html}</div></body></html>"
            ),
            base_url=str(path.parent) + "/",
        ).render(
            stylesheets=[
                CSS(filename=str(path)),
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
