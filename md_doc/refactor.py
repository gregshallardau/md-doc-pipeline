"""
Detect Markdown passages repeated across documents and move them to a template.

``find_shared_sections`` scans a folder for runs of consecutive blocks
(paragraphs, lists, tables, fenced code, ...) that appear verbatim in several
documents.  ``apply_groups`` writes each run to a ``templates/`` fragment and
replaces every occurrence with an ``{% include %}`` line, then re-renders the
affected documents to prove the output did not change (rolling back if it did).

Matching is exact after whitespace normalisation: a boilerplate section that
differs by a client name is not detected until the varying part is a
``{{ variable }}``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .renderer import _strip_frontmatter, render

_SKIP_DIRS = {"templates", "Exports", "node_modules", "__pycache__"}
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_JINJA_OPEN = re.compile(r"\{%-?\s*(?:if|for|block|macro|call|filter|with|raw)\b")
_JINJA_CLOSE = re.compile(r"\{%-?\s*end\w+")
_JINJA_INCLUDE = re.compile(r"^\{%-?\s*include\b")
_MAX_RUN = 60


@dataclass
class Block:
    norm: str
    start: int  # first line index in the file
    end: int  # one past the last line index


@dataclass
class Doc:
    path: Path
    lines: list[str]
    blocks: list[Block]
    ids: list[int] = field(default_factory=list)


@dataclass
class Occurrence:
    doc: Doc
    first: int  # block index
    last: int  # block index, inclusive


@dataclass
class Group:
    name: str
    target: Path  # fragment file
    include: str  # string used in {% include "..." %}
    occurrences: list[Occurrence]
    text: str  # fragment content
    chars: int

    @property
    def docs(self) -> list[Path]:
        return sorted({o.doc.path for o in self.occurrences})


def _split_blocks(lines: list[str], offset: int) -> list[Block]:
    """Group lines from ``offset`` on into blank-line separated blocks."""
    blocks: list[Block] = []
    start: int | None = None
    in_fence = False
    for i in range(offset, len(lines) + 1):
        line = lines[i] if i < len(lines) else ""
        if i < len(lines) and _FENCE.match(line):
            in_fence = not in_fence
        blank = not line.strip() and not in_fence
        if blank or i == len(lines):
            if start is not None:
                text = "\n".join(lines[start:i])
                blocks.append(Block(" ".join(text.split()), start, i))
                start = None
        elif start is None:
            start = i
    return blocks


def _read_doc(path: Path) -> Doc:
    content = path.read_text(encoding="utf-8")
    frontmatter, _ = _strip_frontmatter(content)
    lines = content.split("\n")
    offset = frontmatter.count("\n")
    return Doc(path, lines, _split_blocks(lines, offset))


def _discover(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith((".", "_"))
        )
        for name in sorted(filenames):
            if name.endswith(".md") and not name.startswith(("_", ".")):
                found.append(Path(dirpath) / name)
    return found


def _balanced(text: str) -> bool:
    return len(_JINJA_OPEN.findall(text)) == len(_JINJA_CLOSE.findall(text))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _suggest_name(first_block: str) -> str:
    for line in first_block.splitlines():
        m = _HEADING.match(line.strip())
        if m:
            slug = _slug(re.sub(r"[`*_\[\]]", "", m.group(1)))
            if slug:
                return slug[:40].strip("-")
    words = _slug(" ".join(re.sub(r"[{}%#*`>|\[\]-]", " ", first_block).split()[:4]))
    return words[:40].strip("-") or "shared"


def find_shared_sections(
    root: Path,
    min_docs: int = 2,
    min_chars: int = 80,
    templates_dir: Path | None = None,
) -> list[Group]:
    """Return repeated runs of blocks found in at least ``min_docs`` documents.

    Runs are chosen greedily by ``characters * (copies - 1)`` (the amount of
    duplicated text removed), so the biggest shared section is claimed first and
    smaller overlaps are found from what remains.
    """
    root = Path(root).resolve()
    docs = [_read_doc(p) for p in _discover(root)]

    table: dict[str, int] = {}
    for doc in docs:
        doc.ids = [table.setdefault(b.norm, len(table)) for b in doc.blocks]

    norms = {v: k for k, v in table.items()}
    holders: dict[int, set[int]] = {}
    for di, doc in enumerate(docs):
        for bid in doc.ids:
            holders.setdefault(bid, set()).add(di)
    candidate = {
        bid
        for bid, who in holders.items()
        if len(who) >= min_docs and not _JINJA_INCLUDE.match(norms[bid])
    }

    masked = [[False] * len(d.ids) for d in docs]
    groups: list[Group] = []
    taken_names: set[tuple[Path, str]] = set()

    while True:
        windows: dict[tuple[int, ...], dict[int, list[tuple[int, int]]]] = {}
        for di, doc in enumerate(docs):
            n = len(doc.ids)
            for i in range(n):
                if masked[di][i] or doc.ids[i] not in candidate:
                    continue
                for j in range(i, min(n, i + _MAX_RUN)):
                    if masked[di][j] or doc.ids[j] not in candidate:
                        break
                    key = tuple(doc.ids[i : j + 1])
                    windows.setdefault(key, {}).setdefault(di, []).append((i, j))

        best: tuple[int, int, tuple[int, ...]] | None = None
        for key, per_doc in windows.items():
            if len(per_doc) < min_docs:
                continue
            chars = sum(len(norms[b]) for b in key)
            if chars < min_chars or not _balanced(" ".join(norms[b] for b in key)):
                continue
            copies = sum(len(v) for v in per_doc.values())
            score = (chars * (copies - 1), len(key))
            if best is None or score > (best[0], best[1]):
                best = (score[0], score[1], key)
        if best is None:
            break

        key = best[2]
        occurrences: list[Occurrence] = []
        for di, spans in windows[key].items():
            last_end = -1
            for i, j in spans:
                if i <= last_end:
                    continue
                occurrences.append(Occurrence(docs[di], i, j))
                for k in range(i, j + 1):
                    masked[di][k] = True
                last_end = j
        if len({o.doc.path for o in occurrences}) < min_docs:
            break  # overlap trimming dropped it below the threshold

        first = occurrences[0]
        text = "\n".join(
            first.doc.lines[first.doc.blocks[first.first].start : first.doc.blocks[first.last].end]
        )
        common = Path(os.path.commonpath([o.doc.path.parent for o in occurrences]))
        directory = templates_dir.resolve() if templates_dir else common / "templates"
        base = _suggest_name(text)
        name, n = base, 2
        while (directory / f"{name}.md").exists() or (directory, name) in taken_names:
            name, n = f"{base}-{n}", n + 1
        taken_names.add((directory, name))
        groups.append(
            Group(
                name=name,
                target=directory / f"{name}.md",
                include=f"{name}.md",
                occurrences=occurrences,
                text=text.rstrip("\n") + "\n",
                chars=sum(len(norms[b]) for b in key),
            )
        )

    groups.sort(key=lambda g: g.chars * (len(g.occurrences) - 1), reverse=True)
    return groups


def _rendered(path: Path, repo_root: Path | None) -> str:
    return " ".join(render(path, repo_root=repo_root).split())


def apply_groups(
    groups: list[Group],
    repo_root: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[Path]:
    """Write fragments and splice includes into the documents.

    Every affected document is rendered before and after; if any output
    differs, all files are restored and ``RuntimeError`` is raised.
    Returns the fragment files written.
    """
    affected = sorted({o.doc.path for g in groups for o in g.occurrences})
    before = {p: _rendered(p, repo_root) for p in affected}
    originals = {p: p.read_text(encoding="utf-8") for p in affected}
    created: list[Path] = []

    try:
        for g in groups:
            g.target.parent.mkdir(parents=True, exist_ok=True)
            g.target.write_text(g.text, encoding="utf-8")
            created.append(g.target)

        edits: dict[Path, list[tuple[int, int, str]]] = {}
        for g in groups:
            for o in g.occurrences:
                start = o.doc.blocks[o.first].start
                end = o.doc.blocks[o.last].end
                edits.setdefault(o.doc.path, []).append(
                    (start, end, '{% include "' + g.include + '" %}')
                )
        for path, spans in edits.items():
            lines = originals[path].split("\n")
            for start, end, repl in sorted(spans, reverse=True):
                lines[start:end] = [repl]
            path.write_text("\n".join(lines), encoding="utf-8")
            if on_progress:
                on_progress(str(path))

        for p in affected:
            if _rendered(p, repo_root) != before[p]:
                raise RuntimeError(f"rendered output of {p} would change")
    except Exception:
        for p, text in originals.items():
            p.write_text(text, encoding="utf-8")
        for f in created:
            f.unlink(missing_ok=True)
        raise
    return created
