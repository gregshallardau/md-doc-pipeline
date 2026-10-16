"""Helpers for alternating table row shading by first-column groups."""

from __future__ import annotations

import re
from html import unescape

_DIRECTIVE = re.compile(
    r"<!--\s*table-striping:\s*group\s*-->"
    r"(?:\s*<!--\s*col-widths:[^>]*-->)*\s*"
    r"(<table\b[^>]*>.*?</table\s*>)",
    re.I | re.S,
)
_ROW = re.compile(r"<tr\b([^>]*)>(.*?)</tr\s*>", re.I | re.S)
_CELL = re.compile(r"<(?:td|th)\b[^>]*>(.*?)</(?:td|th)\s*>", re.I | re.S)


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", value))).strip()


def mark_group_stripes(html: str) -> str:
    """Mark the rows belonging to alternating first-column value groups."""

    def table(match: re.Match[str]) -> str:
        group_index = -1
        previous: str | None = None
        out: list[str] = []
        for row in _ROW.finditer(match.group(0)):
            cells = _CELL.findall(row.group(2))
            key = _plain(cells[0]) if cells else ""
            header = bool(re.search(r"<th\b", row.group(2), re.I))
            if not header:
                # Blank first cells continue the current group. This supports
                # tables that label a group once and leave its following rows empty.
                if key:
                    # Every explicit first-column label starts a group. Repeated
                    # labels are still separate groups unless the later row is blank.
                    group_index += 1
                    previous = key
                elif previous is None:
                    group_index += 1
                    previous = ""
            cls = "md-doc-group-alt" if not header and group_index % 2 else "md-doc-group-base"
            attrs = row.group(1)
            attrs = re.sub(
                r'\sclass="([^"]*)"', lambda m: f' class="{m.group(1)} {cls}"', attrs, count=1
            )
            if not re.search(r"\sclass=", attrs):
                attrs += f' class="{cls}"'
            out.append(f"<tr{attrs}>{row.group(2)}</tr>")
        return _ROW.sub(lambda _: out.pop(0), match.group(0)) if out else match.group(0)

    return _DIRECTIVE.sub(lambda m: table(m), html)
