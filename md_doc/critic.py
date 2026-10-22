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

``hybrid``  the final text with a light highlight on each change and a change bar in the
            margin, and the full change (what was deleted, what was added) written out in
            the review column beside it, with the comments (PDF; Word shows ``show``)

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
MODES: tuple[str, ...] = ("accept", "reject", "show", "simple", "hybrid")

#: ``review_exports`` variants: name → (``review_markup`` mode, file-name suffix).
VARIANTS: dict[str, tuple[str, str]] = {
    "clean": ("accept", "-clean"),
    "original": ("reject", "-original"),
    "simple": ("simple", "-simple"),
    "hybrid": ("hybrid", "-hybrid"),
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


def mode_for(config: dict[str, Any] | None, fmt: str) -> str:
    """The mode a builder for *fmt* acts on.

    Slides cannot show review marks, so ``show``, ``simple`` and ``hybrid`` act as
    ``accept`` there. Word has no review column: ``hybrid`` is ``show`` (tracked changes,
    which Word can display in balloons).
    """
    mode = review_mode(config)
    if fmt == "pptx" and mode in ("show", "simple", "hybrid"):
        return "accept"
    if fmt in ("docx", "dotx") and mode == "hybrid":
        return "show"
    return mode


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


def _wrap_lines(
    text: str, tag: str, cls: str, *, bar_only: bool = False, with_bar: bool = False
) -> str:
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
        bar = _BAR if with_bar else ""
        return f'{lead}{bar}<{tag} class="{cls}">{body}</{tag}>{trail}'

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


class _Palette:
    """Colour index (1..SIZE) for each reviewer item, in document order.

    A highlight and the comment right after it share one colour, so the tinted text and
    its margin note match. Colours repeat after ``SIZE`` items; neighbours always differ.
    """

    SIZE = 10

    def __init__(self) -> None:
        self.n = 0
        self.highlight: tuple[int, int] | None = None  # (colour, end offset in this chunk)

    def new_chunk(self) -> None:
        self.highlight = None

    def next(self) -> int:
        self.n += 1
        return (self.n - 1) % self.SIZE + 1

    def for_match(self, match: re.Match[str]) -> tuple[int, bool]:
        """``(colour, follows_a_highlight)`` for a mark."""
        if match.group("hl") is not None:
            colour = self.next()
            self.highlight = (colour, match.end())
            return colour, False
        if (
            match.group("comment") is not None
            and self.highlight
            and self.highlight[1] == match.start()
        ):
            return self.highlight[0], True
        return self.next(), False


def _comment_html(text: str, colour: int = 1, linked: bool = False) -> str:
    flat = " ".join(text.split())
    return (
        f'<span class="critic-comment" data-comment="{_html.escape(flat, quote=True)}" '
        f'data-c="{colour}" data-mark="{0 if linked else 1}"></span>'
    )


def _highlight(match: re.Match[str], colour: int) -> str:
    """A reviewer highlight; one with a comment straight after takes that item's colour."""
    paired = match.string.startswith("{>>", match.end())
    cls = f"critic-hl critic-c{colour}" if paired else "critic-hl"
    return _wrap_lines(match.group("hl"), "mark", cls)


def _show(match: re.Match[str], palette: _Palette) -> str:
    if match.group("hl") is not None or match.group("comment") is not None:
        colour, linked = palette.for_match(match)
        if match.group("hl") is not None:
            return _highlight(match, colour)
        return _comment_html(match.group("comment") or "", colour, linked)
    if match.group("add") is not None:
        return _wrap_lines(match.group("add"), "ins", "critic-ins")
    if match.group("del") is not None:
        return _wrap_lines(match.group("del"), "del", "critic-del")
    if match.group("old") is not None:
        return _wrap_lines(match.group("old"), "del", "critic-del") + _wrap_lines(
            match.group("new"), "ins", "critic-ins"
        )
    return ""


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


def _resolve_simple(match: re.Match[str], palette: _Palette) -> str:
    """Changes applied, with a change-bar marker; highlights and comments kept."""
    if match.group("hl") is not None or match.group("comment") is not None:
        colour, linked = palette.for_match(match)
        if match.group("hl") is not None:
            return _highlight(match, colour)
        return _comment_html(match.group("comment") or "", colour, linked)
    if match.group("add") is not None:
        return _wrap_lines(match.group("add"), "span", "", bar_only=True)
    if match.group("del") is not None:
        return _BAR
    if match.group("old") is not None:
        new = match.group("new")
        return _wrap_lines(new, "span", "", bar_only=True) if new.strip() else _BAR
    return ""


def _change_note(
    kind: str, old: str = "", new: str = "", colour: int = 1, marker: bool = True
) -> str:
    """An empty anchor that ``margin_notes`` turns into a colour-matched margin note.

    ``marker`` asks for a small coloured tick in the text (a deletion has no text to tint).
    """

    def clean(text: str) -> str:
        flat = " ".join(text.split())
        flat = flat if len(flat) <= 90 else flat[:87].rstrip() + "..."
        return _html.escape(flat, quote=True)

    return (
        f'<span class="critic-change-note" data-kind="{kind}" '
        f'data-old="{clean(old)}" data-new="{clean(new)}" '
        f'data-c="{colour}" data-mark="{1 if marker else 0}"></span>'
    )


def _resolve_hybrid(match: re.Match[str], palette: _Palette) -> str:
    """Changes applied and tinted with a change bar; the detail goes in the margin."""
    if match.group("hl") is not None or match.group("comment") is not None:
        colour, linked = palette.for_match(match)
        if match.group("hl") is not None:
            return _highlight(match, colour)
        return _comment_html(match.group("comment") or "", colour, linked)
    colour = palette.next()
    tint = f"critic-chg critic-c{colour}"
    if match.group("add") is not None:
        text = match.group("add")
        return _wrap_lines(text, "span", tint, with_bar=True) + _change_note(
            "add", new=text, colour=colour, marker=False
        )
    if match.group("del") is not None:
        return _BAR + _change_note("del", old=match.group("del"), colour=colour)
    old, new = match.group("old"), match.group("new")
    shown = _wrap_lines(new, "span", tint, with_bar=True) if new.strip() else _BAR
    return shown + _change_note("sub", old=old, new=new, colour=colour, marker=not new.strip())


_PREFIX_ONLY_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)]|>|#{1,6})?[ \t]*$")
_EMPTY_BLOCK_LINE_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)]|>|#{1,6})[ \t]*(?:\n|\Z)", re.MULTILINE)


def _resolve_all(prose: str, mode: str, palette: _Palette) -> str:
    """Accept or reject every mark, tidying the lines a removal leaves behind.

    A mark that disappears while alone on its line(s) takes the line with it (and
    one of two surrounding blank lines); a list item, quote or heading left with
    only its marker is dropped too.
    """
    simple = mode in ("simple", "hybrid")
    out: list[str] = []
    position = 0
    removed = False
    for match in _CRITIC_RE.finditer(prose):
        out.append(prose[position : match.start()])
        if mode == "hybrid":
            replacement = _resolve_hybrid(match, palette)
        elif simple:
            replacement = _resolve_simple(match, palette)
        else:
            replacement = _resolve(match, mode == "accept")
        position = match.end()
        before = "".join(out)
        line_start = before.rfind("\n") + 1
        line_end = prose.find("\n", position)
        line_end = len(prose) if line_end == -1 else line_end
        owns_lines = not before[line_start:].strip() and not prose[position:line_end].strip()
        if simple and match.group("del") is not None:
            # A deleted line (or list item) leaves nothing to put a change bar beside.
            if _PREFIX_ONLY_RE.match(before[line_start:]) and not prose[position:line_end].strip():
                if mode == "hybrid":
                    # The line goes, but its note rides at the end of the line above.
                    anchor = replacement.replace(_BAR, "", 1)  # the note, without a bar
                    above = before[:line_start].rstrip("\n")
                    gap = before[len(above) : line_start]
                    if above and above.lstrip().startswith("|") and above.rstrip().endswith("|"):
                        above = above.rstrip()[:-1] + anchor + " |"
                    elif above:
                        above = above + anchor
                    out = [above + gap]
                    position = min(line_end + 1, len(prose))
                    removed = True
                    continue
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
    if mode in ("show", "simple", "hybrid") and fmt == "pptx":
        mode = "accept"
    if mode == "hybrid" and fmt in ("docx", "dotx"):
        mode = "show"
    if "{" not in markdown or not has_markup(markdown):
        return markdown

    palette = _Palette()

    def transform(prose: str) -> str:
        palette.new_chunk()
        if mode == "show":
            return _CRITIC_RE.sub(lambda m: _show(m, palette), prose)
        return _resolve_all(prose, mode, palette)

    front = _FRONTMATTER_RE.match(markdown)
    head, body = (markdown[: front.end()], markdown[front.end() :]) if front else ("", markdown)
    return head + transform_outside_code(body, transform)


def prepare(rendered_md: str, config: dict[str, Any] | None, fmt: str) -> str:
    """What each builder calls: apply the configured ``review_markup`` mode."""
    return apply(rendered_md, mode_for(config, fmt), fmt=fmt)


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


_ANY_NOTE_RE = re.compile(
    r'<span class="critic-comment" data-comment="([^"]*)" data-c="(\d+)" data-mark="(\d)"></span>'
    r'|<span class="critic-change-note" data-kind="(\w+)" data-old="([^"]*)" data-new="([^"]*)" '
    r'data-c="(\d+)" data-mark="(\d)"></span>'
)


_OWNER_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


def _owner_spans(html: str) -> list[tuple[int, int, int, str]]:
    """``(open_start, insert_at, close_end, tag)`` of every paragraph-like block in *html*."""
    spans: list[tuple[int, int, int, str]] = []
    stack: list[tuple[str, int, int]] = []
    for match in _TAG_RE.finditer(html):
        closing, tag = match.group(1), match.group(2).lower()
        if tag not in _OWNER_TAGS:
            continue
        if not closing:
            stack.append((tag, match.start(), match.end()))
            continue
        while stack and stack[-1][0] != tag:
            stack.pop()
        if not stack:
            continue
        _, start, open_end = stack.pop()
        insert_at = open_end
        if tag == "tr":  # a card cannot sit directly in a row: put it in the first cell
            cell = re.compile(r"<t[dh]\b[^>]*>").search(html, open_end, match.start())
            insert_at = cell.end() if cell else open_end
        spans.append((start, insert_at, match.end(), tag))
    return spans


def margin_notes(html: str, author: str) -> str:
    """PDF: turn each comment (and, in ``hybrid`` mode, each change) into a margin note.

    Notes are grouped into one card per paragraph, list item, heading or table row, placed
    level with the start of that block, so a block's notes sit beside it instead of
    drifting down the column behind earlier ones. Inside a card each item has its colour
    as a swatch; the same colour tints its text (a highlight, or the changed words) or, where
    there is no text to tint (a deletion), is a small tick at that spot. The card takes no
    space in the flow, so the document paginates exactly as the clean version does.
    """
    who = f"<strong>{_html.escape(author)}</strong>"
    spans = _owner_spans(html)
    cards: dict[int, list[str]] = {}  # insertion offset -> entries
    edits: list[tuple[int, int, str]] = []

    def entry(match: re.Match[str]) -> tuple[str, str]:
        """``(entry html, tick html)`` for one anchor."""
        if match.group(1) is not None:
            colour, marker = match.group(2), match.group(3) == "1"
            body = f"{who} {_html.escape(_html.unescape(match.group(1)))}"
        else:
            kind, colour, marker = match.group(4), match.group(7), match.group(8) == "1"
            old = _html.escape(_html.unescape(match.group(5)))
            new = _html.escape(_html.unescape(match.group(6)))
            label = {"add": "ADDED", "del": "DELETED", "sub": "CHANGED"}.get(kind, "CHANGED")
            parts = []
            if old:
                parts.append(f'<del class="critic-del">{old}</del>')
            if new:
                parts.append(f'<ins class="critic-ins">{new}</ins>')
            body = f'<span class="critic-kind">{label}</span> {" ".join(parts)}'
        tick = f'<span class="critic-tick critic-c{colour}"></span>' if marker else ""
        swatch = f'<span class="critic-swatch critic-c{colour}"></span>'
        return f'<span class="critic-entry">{swatch}{body}</span>', tick

    for match in _ANY_NOTE_RE.finditer(html):
        item, tick = entry(match)
        owners = [sp for sp in spans if sp[0] <= match.start() and match.end() <= sp[2]]
        if owners:  # the innermost block holds it
            insert_at = max(owners, key=lambda sp: sp[0])[1]
            edits.append((match.start(), match.end(), tick))
        else:  # not inside any block: a card of its own, right here
            insert_at = match.start()
            edits.append((match.start(), match.end(), tick))
        cards.setdefault(insert_at, []).append(item)

    for number, (at, items) in enumerate(sorted(cards.items()), start=1):
        card = (
            f'<span class="critic-margin-note critic-card" data-note="{number}">'
            f'{"".join(items)}</span>'
        )
        edits.append((at, at, card))
    # Later offsets first so earlier ones stay valid; at one offset, an insertion goes before
    # the replacement that starts there.
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[0] != e[1]), reverse=True):
        html = html[:start] + text + html[end:]
    return html


def legend_html(mode: str, summary: dict[str, int], author: str, *, margin: bool = False) -> str:
    """The key for a marked-up PDF: what the colours and bars mean.

    With ``margin`` it is the first item of the review column (so the document itself
    carries no review furniture); otherwise a slim line above the text.
    """
    if mode not in ("show", "simple", "hybrid") or not (summary["changes"] or summary["comments"]):
        return ""
    if mode == "hybrid":
        key = (
            '<span class="critic-legend-bar"></span> Changed: '
            '<span class="critic-chg critic-c1">tinted</span> <span class="critic-chg critic-c2">text</span>'
            ", each colour matched to its margin note"
        )
    elif mode == "show":
        key = (
            '<ins class="critic-ins">Added</ins> <del class="critic-del">Deleted</del> '
            '<mark class="critic-hl critic-c1">Highlight</mark> + a colour-matched comment'
        )
    else:
        key = (
            '<span class="critic-legend-bar"></span> Changed '
            '<mark class="critic-hl critic-c1">Highlight</mark> + a colour-matched comment'
        )
    facts = []
    if summary["changes"]:
        facts.append(f"{summary['changes']} change{'s' if summary['changes'] != 1 else ''}")
    if summary["comments"]:
        facts.append(f"{summary['comments']} comment{'s' if summary['comments'] != 1 else ''}")
    extra = " critic-legend-margin" if margin else ""
    return (
        f'<div class="critic-legend{extra}"><strong>REVIEW</strong> · {_html.escape(author)} · '
        f"{', '.join(facts)}<br>{key}</div>\n"
    )


#: Width of the review column added beside the page for margin comments, in mm.
COLUMN_MM = 72.0


def review_page(
    page_size_mm: tuple[float, float], margins_mm: tuple[float, float], bottom_mm: float
) -> dict[str, Any]:
    """Geometry that makes room for the review column without moving the document.

    The page gets ``COLUMN_MM`` wider on the right, and taller by the same ratio with the
    extra height added to the bottom margin, so the text area, line breaks and page
    breaks are exactly those of the clean version. The PDF is then scaled by ``zoom``
    back to the original width: the page keeps its paper size and the document is
    shrunk to make room for the margin, as Word's "all markup" view does.
    """
    width, height = page_size_mm
    left, right = margins_mm
    new_width = width + COLUMN_MM
    zoom = width / new_width
    new_height = height / zoom
    text_right = width - right  # where the text area ends on the clean page
    return {
        "size": (new_width, new_height),
        "margin_right": right + COLUMN_MM,
        "margin_bottom": bottom_mm + (new_height - height),
        "zoom": zoom,
        "note_left": text_right - left + 12.0,  # past the change-bar strip
        "note_width": right + COLUMN_MM - 12.0 - 4.0,
    }


def review_page_css(geometry: dict[str, Any]) -> str:
    """``@page`` size/margins and the margin-note rules for ``review_page`` geometry."""
    width, height = geometry["size"]
    return (
        "<style>\n"
        f"@page {{ size: {width:.3f}mm {height:.3f}mm; "
        f"margin-right: {geometry['margin_right']:.3f}mm; "
        f"margin-bottom: {geometry['margin_bottom']:.3f}mm; }}\n"
        # The footer stays directly under the text, not at the foot of the taller sheet.
        "@page { @bottom-left { vertical-align: top; } @bottom-center { vertical-align: top; } "
        "@bottom-right { vertical-align: top; } }\n"
        ".critic-legend-margin { position: absolute; top: auto; "
        f"left: {geometry['note_left']:.3f}mm; width: {geometry['note_width']:.3f}mm; "
        "transform: translateY(-100%); margin: -16pt 0 0 0; }\n"
        ".critic-margin-note { position: absolute; top: auto; "
        f"left: {geometry['note_left']:.3f}mm; width: {geometry['note_width']:.3f}mm; }}\n"
        "</style>"
    )


_NOTE_ATTR_RE = re.compile(r'data-note="(\d+)"')


def _place_notes(
    notes: list[dict[str, Any]], gap: float, floor: float, limit: float
) -> list[float]:
    """Top offsets for *notes* (sorted by ``was``) that avoid overlap with least displacement.

    Notes that would collide are merged into a stack, and the stack is centred on where its
    notes wanted to be (so each ends up as near its own line as it can), then kept inside
    the text area.
    """
    # Each block: [start, height, members], members as (note index, offset in block).
    blocks: list[list[Any]] = [[n["was"], n["h"], [(i, 0.0)]] for i, n in enumerate(notes)]

    def settle() -> bool:
        for k in range(len(blocks) - 1):
            a, b = blocks[k], blocks[k + 1]
            if a[0] + a[1] + gap > b[0] + 1e-6:
                offset = a[1] + gap
                members = a[2] + [(i, off + offset) for i, off in b[2]]
                start = sum(notes[i]["was"] - off for i, off in members) / len(members)
                blocks[k : k + 2] = [[start, offset + b[1], members]]
                return True
        return False

    while True:
        while settle():
            pass
        # Keep the whole column inside the text area, then re-check for new collisions.
        moved = False
        if blocks and blocks[0][0] < floor:
            blocks[0][0] = floor
            moved = True
        if blocks and blocks[-1][0] + blocks[-1][1] > limit:
            blocks[-1][0] = max(floor, limit - blocks[-1][1])
            moved = True
        if not (
            moved
            and any(
                blocks[k][0] + blocks[k][1] + gap > blocks[k + 1][0] + 1e-6
                for k in range(len(blocks) - 1)
            )
        ):
            break
    placed = [0.0] * len(notes)
    for start, _height, members in blocks:
        for i, off in members:
            placed[i] = start + off
    return placed


def spread_margin_notes(html: str, measure: Any, gap_px: float = 5.0) -> str:
    """Nudge margin notes apart so none overlaps another or runs off the page.

    ``measure(html)`` lays the page out and returns a WeasyPrint ``Document``. Notes sit
    beside their anchor line; where two would collide the later one moves down, and
    where the last would pass the foot of the page the stack moves up. The change is a
    ``margin-top`` on each note, which cannot affect the flow.
    """
    if "critic-margin-note" not in html:
        return html
    document = measure(html)
    shifts: dict[str, float] = {}
    for page in document.pages:
        page_box = page._page_box
        # Notes stay inside the text area (WeasyPrint will not draw an absolutely
        # positioned box past its foot). A page with more comments than the column holds
        # packs them tightly from the top.
        floor = page_box.content_box_y()
        limit = floor + page_box.height
        notes: list[dict[str, Any]] = []

        def visit(box: Any) -> None:
            element = getattr(box, "element", None)
            if (
                element is not None
                and type(box).__name__ in {"BlockBox", "AbsolutePlaceholder"}
                and "critic-margin-note" in (element.get("class") or "")
            ):
                top = box.position_y + box.margin_top
                notes.append(
                    {"id": element.get("data-note"), "was": top, "y": top, "h": box.border_height()}
                )
                return
            for child in getattr(box, "children", []) or []:
                visit(child)

        visit(page_box)
        notes.sort(key=lambda n: n["was"])
        for note, y in zip(notes, _place_notes(notes, gap_px, floor, limit)):
            note["y"] = y
        for note in notes:
            if note["id"] is not None and abs(note["y"] - note["was"]) > 0.5:
                shifts[note["id"]] = note["y"] - note["was"]

    def style(match: re.Match[str]) -> str:
        delta = shifts.get(match.group(1))
        tail = f' style="margin-top: {delta:.2f}px"' if delta else ""
        return match.group(0) + tail

    return _NOTE_ATTR_RE.sub(style, html)


def legend_text(mode: str, summary: dict[str, int], author: str) -> str:
    """Plain-text legend for Word, where changes and comments are native."""
    if mode not in ("show", "simple", "hybrid") or not (summary["changes"] or summary["comments"]):
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


#: Stylesheet for ``show``, ``simple`` and ``hybrid`` in PDF; added only when the document has marks.
#: The review layer has its own look (neutral greys, colour-coded tints and swatches, no
#: boxes or rules from the theme) so it never reads as part of the document's own styling.
_BASE_CSS = """\
ins.critic-ins { color: #0b5d1e; background: #c8f0d2; text-decoration: underline; }
del.critic-del { color: #a40e26; background: #ffd6d9; text-decoration: line-through; }
mark.critic-hl { background: #ffe97a; color: inherit; }
.critic-chg { background: #e9e5ff; }
.critic-margin-note { font: 11pt/1.3 Helvetica, Arial, sans-serif; color: #374151; text-align: left;
  border-top: 2pt solid #9ca3af; padding-top: 3pt; break-inside: avoid; }
.critic-margin-note strong { color: #111827; }
.critic-entry { display: block; margin-top: 4pt; }
.critic-entry:first-child { margin-top: 0; }
.critic-swatch { display: inline-block; width: 10pt; height: 10pt; border-radius: 2pt;
  margin-right: 5pt; vertical-align: baseline; }
.critic-tick { display: inline-block; width: 4pt; height: 1.2em; border-radius: 1pt;
  vertical-align: text-bottom; margin: 0 1.5pt; }
.critic-kind { font-size: 8pt; font-weight: 700; letter-spacing: 0.6pt; color: #6b7280; }
.critic-margin-change ins.critic-ins, .critic-margin-change del.critic-del { padding: 0 1pt; }
.critic-legend { font: 9.5pt/1.5 Helvetica, Arial, sans-serif; color: #4b5563;
  border-top: 0.75pt solid #9ca3af; padding-top: 2pt; margin: 0 0 8pt 0; break-inside: avoid; }
.critic-legend strong { letter-spacing: 1pt; color: #111827; }
.critic-legend-bar { display: inline-block; width: 3pt; height: 9pt; background: #cf222e;
  vertical-align: middle; margin-right: 2pt; }
"""

#: (light tint on the text, strong accent for the swatch/tick/underline) per item colour.
COLOURS: tuple[tuple[str, str], ...] = (
    ("#c9e2ff", "#2f80ed"),  # blue
    ("#d9c9ff", "#7a4dff"),  # violet
    ("#ffd5a3", "#f08c1a"),  # orange
    ("#b4ebe5", "#0f9d94"),  # teal
    ("#f8bcd9", "#d6336c"),  # pink
    ("#ffe58a", "#d9a400"),  # amber
    ("#c3cdf7", "#4263eb"),  # indigo
    ("#ffc4b5", "#e8590c"),  # vermilion
    ("#d6f0b0", "#5fa31b"),  # lime
    ("#bfeaf7", "#1aa3cf"),  # cyan
)

CSS = _BASE_CSS + "".join(
    f".critic-chg.critic-c{n}, mark.critic-hl.critic-c{n} "
    f"{{ background: {tint}; border-bottom: 1.5pt solid {accent}; }}\n"
    f".critic-swatch.critic-c{n}, .critic-tick.critic-c{n} {{ background: {accent}; }}\n"
    for n, (tint, accent) in enumerate(COLOURS, start=1)
)
