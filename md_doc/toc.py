"""Table of contents options: ``toc_title``, ``toc_depth`` and ``toc_page_numbers``.

``[TOC]`` in the Markdown becomes a linked list of headings. PDF shows dot
leaders and page numbers; Word gets a real ``TOC`` field that Word fills in
(and refreshes) when the document is opened.
"""

from __future__ import annotations

import re
from typing import Any

#: Marker paragraph the Word builder swaps for a TOC field after conversion.
WORD_TOC_MARKER = "@@MDDOC_TOC@@"

_TOC_DIV_RE = re.compile(r'<div class="toc">.*?</div>', re.DOTALL)

PAGE_NUMBER_CSS = """\
.toc ul { list-style: none; padding-left: 0; }
.toc ul ul { padding-left: 14pt; }
.toc a { text-decoration: none; display: block; color: inherit; }
.toc a::after { content: leader('.') target-counter(attr(href url), page); }
"""


def toc_depth(config: dict[str, Any] | None) -> int | None:
    """The configured ``toc_depth`` (1-6), or None for every heading level."""
    raw = (config or {}).get("toc_depth")
    try:
        depth = int(raw)
    except (TypeError, ValueError):
        return None
    return depth if 1 <= depth <= 6 else None


def toc_title(config: dict[str, Any] | None) -> str:
    return str((config or {}).get("toc_title") or "").strip()


def toc_extension_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Options for Python-Markdown's ``toc`` extension."""
    options: dict[str, Any] = {}
    if toc_title(config):
        options["title"] = toc_title(config)
    depth = toc_depth(config)
    if depth:
        options["toc_depth"] = depth
    return options


def page_number_css(config: dict[str, Any] | None) -> str:
    value = (config or {}).get("toc_page_numbers", True)
    off = str(value).strip().lower() in {"false", "no", "0", "off"}
    return "" if off else PAGE_NUMBER_CSS


def html_toc_to_marker(html: str) -> str:
    """Swap the rendered ``[TOC]`` block for a marker paragraph (Word)."""
    return _TOC_DIV_RE.sub(f"<p>{WORD_TOC_MARKER}</p>", html, count=1)


def insert_word_toc_fields(doc: Any, config: dict[str, Any] | None) -> bool:
    """Replace marker paragraphs with a Word TOC field. Returns True if any."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    found = False
    levels = toc_depth(config) or 3
    title = toc_title(config)
    for paragraph in list(doc.paragraphs):
        if paragraph.text.strip() != WORD_TOC_MARKER:
            continue
        found = True
        for run in list(paragraph.runs):
            run._r.getparent().remove(run._r)
        if title:
            heading = paragraph.insert_paragraph_before(title)
            for run in heading.runs:
                run.bold = True
        run = paragraph.add_run()
        for kind, text in (
            ("begin", None),
            ("instr", f' TOC \\o "1-{levels}" \\h \\z \\u '),
            ("separate", None),
            ("text", "Right-click and choose Update Field to build the contents."),
            ("end", None),
        ):
            if kind == "instr":
                el = OxmlElement("w:instrText")
                el.set(qn("xml:space"), "preserve")
                el.text = text
            elif kind == "text":
                el = OxmlElement("w:t")
                el.text = text
            else:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), kind)
            run._r.append(el)
    if found:
        settings = doc.settings.element
        if settings.find(qn("w:updateFields")) is None:
            update = OxmlElement("w:updateFields")
            update.set(qn("w:val"), "true")
            settings.append(update)
    return found
