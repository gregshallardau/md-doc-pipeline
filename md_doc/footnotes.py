"""Real Word footnotes for ``page_footnotes: true``, and a WeasyPrint footnote fix.

Python-Markdown's ``footnotes`` extension collects every note into a
``<div class="footnote">`` list at the end of the document. With
``page_footnotes: true`` the PDF builder moves each note to the foot of the
page that cites it (``md_doc.pdf_features.page_footnotes``); for Word,
:func:`mark_for_word` replaces each reference with a marker the Word builder
turns into a real footnote (``w:footnoteReference``).
"""

from __future__ import annotations

import re

_BLOCK_RE = re.compile(
    r'<div class="footnote">\s*<hr\s*/?>\s*<ol>(?P<items>.*?)</ol>\s*</div>', re.DOTALL
)
_ITEM_RE = re.compile(r'<li id="fn:(?P<id>[^"]+)">(?P<body>.*?)</li>', re.DOTALL)
_REF_RE = re.compile(
    r'<sup id="fnref\d*:(?P<id>[^"]+)"><a class="footnote-ref" href="#fn:(?P=id)">(?P<num>\d+)</a></sup>'
)
_BACKREF_RE = re.compile(r'(?:&#160;| )?<a class="footnote-backref"[^>]*>.*?</a>', re.DOTALL)
_PARA_RE = re.compile(r"<p>(.*?)</p>", re.DOTALL)


def extract_notes(html: str) -> tuple[str, dict[str, str]]:
    """Remove the end-of-document footnote list; return the HTML and ``{id: note HTML}``.

    Each note's paragraphs are joined with ``<br>`` and its back-links removed.
    """
    notes: dict[str, str] = {}
    block = _BLOCK_RE.search(html)
    if not block:
        return html, notes
    for item in _ITEM_RE.finditer(block.group("items")):
        body = _BACKREF_RE.sub("", item.group("body"))
        paragraphs = [p.strip() for p in _PARA_RE.findall(body)] or [body.strip()]
        notes[item.group("id")] = "<br>".join(p for p in paragraphs if p)
    return html[: block.start()] + html[block.end() :], notes


def mark_for_word(html: str) -> tuple[str, list[str]]:
    """Replace each reference with a marker; return the HTML and the notes in order.

    A marker is ``<sup class="md-doc-fnref" data-fn="N"></sup>`` where *N*
    indexes the returned list. A note referenced twice becomes two Word
    footnotes, as Word numbers each reference.
    """
    html, notes = extract_notes(html)
    if not notes:
        return html, []
    ordered: list[str] = []

    def replace(match: re.Match[str]) -> str:
        note = notes.get(match.group("id"))
        if note is None:
            return match.group(0)
        ordered.append(note)
        return f'<sup class="md-doc-fnref" data-fn="{len(ordered) - 1}"></sup>'

    return _REF_RE.sub(replace, html), ordered


_PATCHED = False


def patch_weasyprint_footnote_rounding() -> None:
    """Stop WeasyPrint moving a footnote to the next page over a rounding error.

    WeasyPrint checks whether the footnote area overflows with a bare
    ``last_child_bottom > area_bottom``. With fractional border, padding or
    margin values on ``@footnote`` (``0.5pt``, ``5pt`` …) the two sums differ in
    the last bits and a note that fits is deferred to the next page. When the
    area is not capped by ``max-height`` its height is fitted to the notes, so
    a real overflow is impossible and the result is treated as fitting.
    Idempotent; does nothing if WeasyPrint's internals differ.
    """
    global _PATCHED
    if _PATCHED:
        return
    try:
        from weasyprint.layout import LayoutContext
    except ImportError:  # pragma: no cover - WeasyPrint missing
        return
    original = getattr(LayoutContext, "_update_footnote_area", None)
    if original is None:  # pragma: no cover - different WeasyPrint
        return

    def _update_footnote_area(self):  # type: ignore[no-untyped-def]
        overflow = original(self)
        if overflow:
            area = self.current_footnote_area
            height, max_height = area.height, getattr(area, "max_height", None)
            if (
                isinstance(height, (int, float))
                and isinstance(max_height, (int, float))
                and height < max_height - 0.01
            ):
                return False
        return overflow

    LayoutContext._update_footnote_area = _update_footnote_area
    _PATCHED = True
