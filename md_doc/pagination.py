"""Explicit Markdown section boundaries shared by the PDF and Word builders."""

import re

from .literal import transform_outside_code

_SECTION_COMMENT = re.compile(
    r"<!--\s*sectionbreak(?:\s*:\s*(portrait|landscape))?\s*-->", re.IGNORECASE
)
_SECTION_HTML = re.compile(
    r'<div class="md-doc-section-break" data-orientation="(portrait|landscape|default)"></div>'
)


def inject_section_breaks(markdown: str) -> str:
    """Expand section comments while preserving literal code examples."""
    return transform_outside_code(
        markdown,
        lambda body: _SECTION_COMMENT.sub(
            lambda match: '\n\n<div class="md-doc-section-break" data-orientation="'
            + (match.group(1) or "default").lower()
            + '"></div>\n\n',
            body,
        ),
    )


def pdf_sections(html: str, page_size: tuple[float, float]) -> tuple[str, str]:
    """Wrap section contents in named pages, preserving the theme's paper size."""
    parts = _SECTION_HTML.split(html)
    result = [parts[0]]
    rules = []
    for index in range(1, len(parts), 2):
        orientation, content = parts[index : index + 2]
        width, height = page_size
        if orientation == "landscape":
            width, height = max(page_size), min(page_size)
        elif orientation == "portrait":
            width, height = min(page_size), max(page_size)
        name = f"md-doc-section-{index}"
        rules.append(f"@page {name} {{ size: {width}mm {height}mm; }}")
        # A distinct named page forces a new page even when orientation is unchanged.
        result.append(f'<div style="page: {name}; break-before: page">{content}</div>')
    return "".join(result), "\n".join(rules)
