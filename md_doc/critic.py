"""CriticMarkup review markup: ``{++add++}``, ``{--delete--}``, ``{~~old~>new~~}``,
``{==highlight==}`` and ``{>>comment<<}``.

Reviewers edit the Markdown source with these marks; the ``review_markup`` config
key (or ``md-doc build --review``) decides what a build does with them:

``accept``  apply every change (the default, so clean output never leaks edits)
``reject``  revert every change
``show``    keep them visible: coloured insertions/deletions and comment footnotes in
            PDF, real Word tracked changes and Word comments in ``.docx``
``simple``  the final text with changes applied, a change bar beside each changed
            line (PDF margin bar, Word paragraph border), and the highlights and
            comments kept (Word's "Simple Markup")

Highlights and comments carry no text change, so ``accept`` and ``reject`` keep a
highlight's text and drop its comment. Formats with no review rendering (slides)
treat ``show`` and ``simple`` as ``accept``.

``review_exports`` builds several of these at once, one file per variant
(``clean``, ``original``, ``simple``, ``markup``).

The pass runs on the Markdown body after Jinja and before Markdown conversion, with
fenced and inline code left alone. In ``show`` mode the marks become inline HTML
(``<ins class="critic-ins">`` and friends) that both the PDF and Word builders know.
"""

from __future__ import annotations

import datetime
import html as _html
import os
import re
from typing import Any

from .literal import transform_outside_code

#: Values of the ``review_markup`` key.
MODES: tuple[str, ...] = ("accept", "reject", "show", "simple")

#: ``review_exports`` variants: name → (``review_markup`` mode, file-name suffix).
VARIANTS: dict[str, tuple[str, str]] = {
    "clean": ("accept", "-clean"),
    "original": ("reject", "-original"),
    "simple": ("simple", "-simple"),
    "markup": ("show", "-markup"),
    "full": ("show", "-markup"),
}

_BAR = '<span class="critic-bar"></span>'
DEFAULT_MODE = "accept"

_CRITIC_RE = re.compile(
    r"\{\+\+(?P<add>.*?)\+\+\}"
    r"|\{--(?P<del>.*?)--\}"
    r"|\{~~(?P<old>.*?)~>(?P<new>.*?)~~\}"
    r"|\{==(?P<hl>.*?)==\}"
    r"|\{>>(?P<comment>.*?)<<\}",
    re.DOTALL,
)

#: A mark that was opened but never closed (or a substitution without ``~>``).
_OPENERS = (
    ("{++", "++}", "insertion"),
    ("{--", "--}", "deletion"),
    ("{==", "==}", "highlight"),
    ("{>>", "<<}", "comment"),
)

_BLOCK_PREFIX_RE = re.compile(r"^(\s*(?:#{1,6}[ \t]+|[-*+][ \t]+|\d+[.)][ \t]+|>[ \t]*)+)(.*)$")
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*\n", re.DOTALL)


def review_mode(config: dict[str, Any] | None) -> str:
    """The configured ``review_markup`` mode, ``accept`` when unset or unknown."""
    raw = str((config or {}).get("review_markup") or "").strip().lower()
    return raw if raw in MODES else DEFAULT_MODE


def review_author(config: dict[str, Any] | None) -> str:
    """Author name on tracked changes and comments (``review_author``, else "Reviewer")."""
    return str((config or {}).get("review_author") or "").strip() or "Reviewer"


def review_stamp() -> str:
    """ISO timestamp for tracked changes; honours ``SOURCE_DATE_EPOCH`` for reproducibility."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "")
    if epoch.isdigit():
        moment = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)
    else:
        moment = datetime.datetime.now(datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def has_markup(text: str) -> bool:
    """True when *text* contains at least one complete CriticMarkup mark."""
    return _CRITIC_RE.search(text) is not None


# ---------------------------------------------------------------------------
# Rendering one mark
# ---------------------------------------------------------------------------


def _wrap_lines(text: str, tag: str, cls: str, *, bar_only: bool = False) -> str:
    """Wrap *text* in ``<tag class=cls>``, line by line.

    A mark can span lines, list items, headings or table rows, so the wrapper goes
    around each line's content rather than the whole span: Markdown block syntax
    at the start of a line (``- ``, ``## ``, ``> ``, ``|``) stays outside it.
    """

    def wrap(core: str) -> str:
        match = re.match(r"(\s*)(.*?)(\s*)\Z", core, re.DOTALL)
        assert match is not None
        lead, body, trail = match.groups()
        if not body:
            return core
        if bar_only:  # change bar: a marker before the text, the text itself unwrapped
            return f"{lead}{_BAR}{body}{trail}"
        return f'{lead}<{tag} class="{cls}">{body}</{tag}>{trail}'

    out: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            out.append(line)
        elif stripped.startswith("|"):
            if re.fullmatch(r"\|?[\s:|-]+\|?", stripped):
                out.append(line)  # table separator row
            else:
                cells = line.rstrip("\n").split("|")
                newline = "\n" if line.endswith("\n") else ""
                out.append("|".join(wrap(c) if c.strip() else c for c in cells) + newline)
        else:
            prefix = _BLOCK_PREFIX_RE.match(line.rstrip("\n"))
            if prefix and prefix.group(2).strip():
                newline = "\n" if line.endswith("\n") else ""
                out.append(prefix.group(1) + wrap(prefix.group(2)) + newline)
            else:
                out.append(wrap(line))
    return "".join(out)


def _comment_html(text: str) -> str:
    flat = " ".join(text.split())
    return f'<span class="critic-comment" data-comment="{_html.escape(flat, quote=True)}"></span>'


def _show(match: re.Match[str]) -> str:
    if match.group("add") is not None:
        return _wrap_lines(match.group("add"), "ins", "critic-ins")
    if match.group("del") is not None:
        return _wrap_lines(match.group("del"), "del", "critic-del")
    if match.group("old") is not None:
        return _wrap_lines(match.group("old"), "del", "critic-del") + _wrap_lines(
            match.group("new"), "ins", "critic-ins"
        )
    if match.group("hl") is not None:
        return _wrap_lines(match.group("hl"), "mark", "critic-hl")
    return _comment_html(match.group("comment") or "")


def _resolve(match: re.Match[str], accept: bool) -> str:
    if match.group("add") is not None:
        return match.group("add") if accept else ""
    if match.group("del") is not None:
        return "" if accept else match.group("del")
    if match.group("old") is not None:
        return match.group("new") if accept else match.group("old")
    if match.group("hl") is not None:
        return match.group("hl")
    return ""  # comments never reach clean output


def _resolve_simple(match: re.Match[str]) -> str:
    """Changes applied, with a change-bar marker; highlights and comments kept."""
    if match.group("add") is not None:
        return _wrap_lines(match.group("add"), "span", "", bar_only=True)
    if match.group("del") is not None:
        return _BAR
    if match.group("old") is not None:
        new = match.group("new")
        return _wrap_lines(new, "span", "", bar_only=True) if new.strip() else _BAR
    if match.group("hl") is not None:
        return _wrap_lines(match.group("hl"), "mark", "critic-hl")
    return _comment_html(match.group("comment") or "")


_PREFIX_ONLY_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)]|>|#{1,6})?[ \t]*$")
_EMPTY_BLOCK_LINE_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)]|>|#{1,6})[ \t]*(?:\n|\Z)", re.MULTILINE)


def _resolve_all(prose: str, mode: str) -> str:
    """Accept or reject every mark, tidying the lines a removal leaves behind.

    A mark that disappears while alone on its line(s) takes the line with it (and
    one of two surrounding blank lines); a list item, quote or heading left with
    only its marker is dropped too.
    """
    simple = mode == "simple"
    out: list[str] = []
    position = 0
    removed = False
    for match in _CRITIC_RE.finditer(prose):
        out.append(prose[position : match.start()])
        replacement = _resolve_simple(match) if simple else _resolve(match, mode == "accept")
        position = match.end()
        before = "".join(out)
        line_start = before.rfind("\n") + 1
        line_end = prose.find("\n", position)
        line_end = len(prose) if line_end == -1 else line_end
        owns_lines = not before[line_start:].strip() and not prose[position:line_end].strip()
        if simple and match.group("del") is not None:
            # A deleted line (or list item) leaves nothing to put a change bar beside.
            if _PREFIX_ONLY_RE.match(before[line_start:]) and not prose[position:line_end].strip():
                replacement, owns_lines = "", True
        if replacement == "":
            removed = True
            if owns_lines:
                out = [before[:line_start]]  # the mark owned its line(s)
                position = min(line_end + 1, len(prose))
                if out[0].endswith("\n\n") and prose.startswith("\n", position):
                    position += 1
                continue
        elif owns_lines:
            replacement = replacement.strip("\n")  # a block insertion: no stray blank lines
        out.append(replacement)
    out.append(prose[position:])
    result = "".join(out)
    return _EMPTY_BLOCK_LINE_RE.sub("", result) if removed else result


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def apply(markdown: str, mode: str, *, fmt: str = "pdf") -> str:
    """Resolve or render the CriticMarkup in *markdown* (frontmatter is left alone).

    *fmt* is the output format; ``pptx`` has no review rendering, so ``show`` is
    treated as ``accept`` there.
    """
    if mode not in MODES:
        mode = DEFAULT_MODE
    if mode in ("show", "simple") and fmt == "pptx":
        mode = "accept"
    if "{" not in markdown or not has_markup(markdown):
        return markdown

    def transform(prose: str) -> str:
        if mode == "show":
            return _CRITIC_RE.sub(_show, prose)
        return _resolve_all(prose, mode)

    front = _FRONTMATTER_RE.match(markdown)
    head, body = (markdown[: front.end()], markdown[front.end() :]) if front else ("", markdown)
    return head + transform_outside_code(body, transform)


def prepare(rendered_md: str, config: dict[str, Any] | None, fmt: str) -> str:
    """What each builder calls: apply the configured ``review_markup`` mode."""
    return apply(rendered_md, review_mode(config), fmt=fmt)


def problems(markdown: str) -> list[tuple[int, str]]:
    """``(line, message)`` for marks that are opened but never closed.

    Complete marks are removed first, so only genuinely broken ones remain: a stray
    opener, or a ``{~~`` substitution missing its ``~>`` separator.
    """
    found: list[tuple[int, str]] = []

    def scan(prose: str) -> str:
        blanked = _CRITIC_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), prose)
        for opener, closer, name in _OPENERS:
            for match in re.finditer(re.escape(opener), blanked):
                line = blanked.count("\n", 0, match.start()) + 1
                found.append(
                    (line, f"CriticMarkup {name} '{opener}' is never closed with '{closer}'")
                )
        for match in re.finditer(re.escape("{~~"), blanked):
            line = blanked.count("\n", 0, match.start()) + 1
            found.append((line, "CriticMarkup substitution '{~~' needs 'old~>new~~}'"))
        return prose

    transform_outside_code(markdown, scan)
    return sorted(found)


_BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>")


def mark_changed_blocks(html: str) -> str:
    """Give each block that holds a change-bar marker the class ``critic-changed``.

    The marker is an empty ``<span class="critic-bar">`` written by ``simple`` mode.
    The block is the paragraph, list item, heading or table *row*, or the whole
    callout for a change inside a blockquote. The PDF builder then draws the bar in
    the page margin from the laid-out position of each tagged block
    (``pdf_features.change_bars_finisher``), so bars line up down the page whatever
    the nesting.
    """
    if 'class="critic-bar"' not in html:
        return html
    stack: list[tuple[str, int, int]] = []  # (tag, start, end) of open block tags
    marked: set[int] = set()
    for match in _TAG_RE.finditer(html):
        closing, tag, attrs = match.group(1), match.group(2).lower(), match.group(3)
        if tag in _BLOCK_TAGS:
            if closing:
                while stack and stack[-1][0] != tag:
                    stack.pop()
                if stack:
                    stack.pop()
            else:
                stack.append((tag, match.start(), match.end()))
        elif tag == "span" and not closing and 'class="critic-bar"' in attrs and stack:
            # A change inside a callout (blockquote) marks the whole box, so the bar
            # sits outside it rather than on top of the callout's own rule.
            box = next((entry for entry in stack if entry[0] == "blockquote"), stack[-1])
            marked.add(box[1])
    out = html
    for start in sorted(marked, reverse=True):
        end = out.index(">", start)
        opening = out[start : end + 1]
        if "class=" in opening:
            opening = re.sub(r'class="', 'class="critic-changed ', opening, count=1)
        else:
            opening = opening[:-1] + ' class="critic-changed">'
        out = out[:start] + opening + out[end + 1 :]
    return out


_COMMENT_SPAN_RE = re.compile(r'<span class="critic-comment" data-comment="([^"]*)"></span>')
_NOTE_BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote"}


def counts(markdown: str) -> dict[str, int]:
    """How many changes, highlights and comments the Markdown holds (frontmatter and code ignored)."""
    front = _FRONTMATTER_RE.match(markdown)
    body = markdown[front.end() :] if front else markdown
    found = {"changes": 0, "highlights": 0, "comments": 0}

    def tally(prose: str) -> str:
        for match in _CRITIC_RE.finditer(prose):
            if match.group("hl") is not None:
                found["highlights"] += 1
            elif match.group("comment") is not None:
                found["comments"] += 1
            else:
                found["changes"] += 1
        return prose

    transform_outside_code(body, tally)
    return found


def comment_notes(html: str, author: str) -> str:
    """PDF: turn each comment into a numbered reference and a visible note box.

    The reference (``[1]``) replaces the empty comment span; the note, with the
    reviewer's name, follows the paragraph, list item, heading, table or callout
    that holds it, so a comment is read beside the text it is about.
    """
    if 'class="critic-comment"' not in html:
        return html
    stack: list[list[Any]] = []  # [tag, notes] for open note-capable blocks
    replacements: list[tuple[int, int, str]] = []
    insertions: list[tuple[int, str]] = []
    number = 0
    skip_until = 0
    for match in _TAG_RE.finditer(html):
        if match.start() < skip_until:
            continue
        closing, tag = match.group(1), match.group(2).lower()
        if tag in _NOTE_BLOCKS:
            if closing:
                while stack and stack[-1][0] != tag:
                    stack.pop()
                if stack:
                    notes = stack.pop()[1]
                    if notes:
                        insertions.append((match.end(), "".join(notes)))
            else:
                stack.append([tag, []])
        elif tag == "span" and not closing:
            span = _COMMENT_SPAN_RE.match(html, match.start())
            if span and stack:
                number += 1
                text = _html.unescape(span.group(1))
                replacements.append(
                    (span.start(), span.end(), f'<sup class="critic-ref">[{number}]</sup>')
                )
                # A comment in a table is noted after the table, not inside a row.
                owner = next((e for e in stack if e[0] == "table"), stack[-1])
                owner[1].append(
                    '<div class="critic-note">'
                    f'<span class="critic-note-n">[{number}]</span> '
                    f"<strong>{_html.escape(author)}:</strong> {_html.escape(text)}</div>"
                )
                skip_until = span.end()
    edits = [(a, b, new) for a, b, new in replacements] + [
        (pos, pos, new) for pos, new in insertions
    ]
    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        html = html[:start] + new + html[end:]
    return html


def legend_html(mode: str, summary: dict[str, int], author: str) -> str:
    """The key printed above a marked-up PDF: what the colours and bars mean."""
    if mode not in ("show", "simple") or not (summary["changes"] or summary["comments"]):
        return ""
    if mode == "show":
        key = (
            '<ins class="critic-ins">Added</ins> <del class="critic-del">Deleted</del> '
            '<mark class="critic-hl">Highlighted</mark> '
            '<sup class="critic-ref">[1]</sup> Comment'
        )
    else:
        key = (
            '<span class="critic-legend-bar"></span> Changed (red bar in the right margin) '
            '<mark class="critic-hl">Highlighted</mark> <sup class="critic-ref">[1]</sup> Comment'
        )
    facts = []
    if summary["changes"]:
        facts.append(f"{summary['changes']} change{'s' if summary['changes'] != 1 else ''}")
    if summary["comments"]:
        facts.append(f"{summary['comments']} comment{'s' if summary['comments'] != 1 else ''}")
    return (
        '<div class="critic-legend"><strong>Review markup</strong> '
        f"· {_html.escape(author)} · {', '.join(facts)}<br>{key}</div>\n"
    )


def legend_text(mode: str, summary: dict[str, int], author: str) -> str:
    """Plain-text legend for Word, where changes and comments are native."""
    if mode not in ("show", "simple") or not (summary["changes"] or summary["comments"]):
        return ""
    facts = []
    if summary["changes"]:
        facts.append(f"{summary['changes']} change{'s' if summary['changes'] != 1 else ''}")
    if summary["comments"]:
        facts.append(f"{summary['comments']} comment{'s' if summary['comments'] != 1 else ''}")
    how = (
        "Changes are tracked: accept or reject them on Word's Review tab."
        if mode == "show"
        else "A red bar in the right margin marks each changed paragraph; comments are in the margin."
    )
    return f"Review markup · {author} · {', '.join(facts)}. {how}"


#: Stylesheet for ``show`` and ``simple`` modes in PDF; added only when the document has marks.
CSS = """\
ins.critic-ins { color: #0b5d1e; background: #c8f0d2; text-decoration: underline; }
del.critic-del { color: #a40e26; background: #ffd6d9; text-decoration: line-through; }
mark.critic-hl { background: #ffe97a; color: inherit; }
sup.critic-ref { color: #7a4b00; background: #ffe97a; font-weight: 700; font-size: 70%;
  line-height: 0; padding: 0 1.5pt; border-radius: 2pt; font-style: normal; }
.critic-note { margin: 2pt 0 7pt 0; padding: 4pt 8pt; background: #fff8dc;
  border-left: 3pt solid #d4a017; font-size: 8.5pt; line-height: 1.35; font-style: normal;
  color: #4a3b00; break-inside: avoid; break-before: avoid; }
.critic-note-n { font-weight: 700; color: #9a6700; }
.critic-legend { margin: 0 0 10pt 0; padding: 4pt 8pt; background: #f3f4f6; border: 0.5pt solid #d1d5db;
  font-size: 8pt; line-height: 1.6; color: #374151; break-inside: avoid; }
.critic-legend-bar { display: inline-block; width: 2.5pt; height: 8pt; background: #cf222e;
  vertical-align: middle; margin-right: 2pt; }
"""
