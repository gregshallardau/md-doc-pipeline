"""Backslash hard line breaks (CommonMark) for Python-Markdown.

CommonMark, GitHub and Pandoc end a line with a backslash for a forced line break; the
Markdown library used here only knows two trailing spaces. ``backslash_line_breaks``
rewrites the former into the latter before conversion, so both spellings work in every
format.
"""

from __future__ import annotations

import re

from .literal import transform_outside_code

_LIST_MARKER_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s")


def _breaks(prose: str) -> str:
    lines = prose.split("\n")
    in_math = False
    in_list = False  # the last unindented line started a list item
    in_code = False  # inside an indented (four-space) code block
    previous_blank = True
    for index, line in enumerate(lines):
        blank = not line.strip()
        indent = len(line) - len(line.lstrip(" \t"))
        if not blank and indent < 4:
            in_list = bool(_LIST_MARKER_RE.match(line))
            in_code = False
        elif not blank and indent >= 4 and not in_list and (previous_blank or in_code):
            in_code = True
        previous_blank = blank

        if line.count("$$") % 2:  # a display-math delimiter: LaTeX owns what is inside
            in_math = not in_math
            continue
        if in_math or in_code or blank or not line.endswith("\\"):
            continue
        trailing = len(line) - len(line.rstrip("\\"))
        if trailing % 2 == 0:  # an escaped backslash, not a break
            continue
        if line.lstrip().startswith("|"):  # a table row
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if not following.strip():  # a break needs more text after it in the block
            continue
        lines[index] = line[:-1] + "  "
    return "\n".join(lines)


def backslash_line_breaks(text: str) -> str:
    """Turn a backslash at the end of a line into a hard line break.

    Fenced code, inline code, display maths, indented code, table rows and an even run
    of backslashes (an escaped backslash) are left alone, and so is a backslash that ends
    a paragraph, which stays literal as in CommonMark.
    """
    if "\\" not in text:
        return text
    return transform_outside_code(text, _breaks)
