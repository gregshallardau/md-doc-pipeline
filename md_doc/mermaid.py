"""Mermaid diagram parser and branded SVG renderer.

Parses a subset of Mermaid syntax and renders to SVG using colours from the
active PDF theme.  No external dependencies -- pure Python.

Supported diagram types
-----------------------
    flowchart LR|TD|TB|RL|BT   -- directed graphs with nodes, edges, subgraphs
    pie                         -- pie charts with title and labelled slices
    sequenceDiagram             -- sequence diagrams with participants and messages

Supported flowchart syntax
--------------------------
    A["label"]                    rectangle node
    B{"label"}                    diamond (decision) node
    C(["label"])                  stadium (rounded) node
    D("label")                    rounded rectangle node
    E(("label"))                  circle node
    F[("label")]                  cylinder (database) node
    G{{"label"}}                  hexagon node
    H[["label"]]                  subroutine node
    A --> B                       solid edge
    A -.-> B                      dotted edge
    A ==> B                       thick edge
    A --- B                       line (no arrow)
    A -- "label" --> B            labelled edge
    A -->|"label"| B              pipe-syntax labelled edge
    A --> B --> C                  chained edges
    subgraph id["Label"]          grouped nodes
      ...
    end
    A -- text --> B               text-labelled edge (also -. text .->, == text ==>)
    A --o B / A --x B / A <--> B  circle end, cross end, two-way arrow
    A --> B & C                   fan out / in
    A:::name, classDef, class,
    style A fill:#abc, linkStyle  per-node and per-edge overrides
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import logging
import math
import re
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


logger = logging.getLogger(__name__)


@dataclass
class Node:
    id: str
    label: str
    shape: str = (
        "rect"  # rect | diamond | stadium | rounded | circle | cylinder | hexagon | subroutine
    )
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    classes: list[str] = field(default_factory=list)
    css: dict[str, str] = field(default_factory=dict)  # resolved style overrides


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    style: str = "solid"  # solid | dotted | thick | none (plain line, no arrow)
    head: str = "arrow"  # end marker: arrow | circle | cross | none
    tail: str = "none"  # start marker (bidirectional edges): arrow | circle | cross | none
    css: dict[str, str] = field(default_factory=dict)


@dataclass
class Subgraph:
    id: str
    label: str
    node_ids: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)  # ids of nested subgraphs
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


@dataclass
class Flowchart:
    direction: str = "LR"  # LR | TD | TB | RL | BT
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    subgraphs: list[Subgraph] = field(default_factory=list)
    # edge index -> lane points (node-centre coordinates) for edges that span levels
    waypoints: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    crossings: int = 0  # edge crossings between adjacent levels after ordering
    crossings_unordered: int = 0  # same, before ordering (for comparison)
    end_marker_space: float = 0.0  # extra gap per edge end for wide markers (crow's feet)


@dataclass
class PieChart:
    title: str = ""
    slices: list[tuple[str, float]] = field(default_factory=list)
    show_data: bool = False


@dataclass
class SeqMessage:
    src: str
    dst: str
    label: str = ""
    arrow: str = "->"  # -> | ->> | --> | -->> | -x | --x | -) | --) | <<->> | <<-->>
    activate: str = ""  # "+" activates the target, "-" deactivates the source


@dataclass
class SeqNote:
    position: str  # left | right | over
    targets: list[str]
    text: str


@dataclass
class SeqBlock:
    kind: str  # loop | alt | opt | par | critical | break | rect | else | and | option | end
    label: str = ""


@dataclass
class SeqActivation:
    participant: str
    on: bool


@dataclass
class SequenceDiagram:
    participants: list[str] = field(default_factory=list)  # ids, in order of appearance
    messages: list[SeqMessage] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)  # id -> display name (`as` alias)
    actors: set[str] = field(default_factory=set)
    events: list[SeqMessage | SeqNote | SeqBlock | SeqActivation] = field(default_factory=list)
    autonumber: bool = False


@dataclass
class BarChart:
    title: str = ""
    labels: list[str] = field(default_factory=list)
    datasets: list[tuple[str, list[float]]] = field(default_factory=list)  # (kind, values)
    horizontal: bool = False
    series_names: list[str] = field(default_factory=list)  # optional, parallel to datasets
    x_title: str = ""
    y_title: str = ""
    y_min: float | None = None
    y_max: float | None = None


@dataclass
class GaugeChart:
    title: str = ""
    value: float = 0
    max_val: float = 100
    min_val: float = 0
    label: str = ""


@dataclass
class TimelineEntry:
    period: str = ""
    events: list[str] = field(default_factory=list)
    section: str = ""


@dataclass
class Timeline:
    title: str = ""
    entries: list[TimelineEntry] = field(default_factory=list)


@dataclass
class GanttTask:
    name: str = ""
    task_id: str = ""
    start: str = ""
    duration: str = ""
    section: str = ""
    tags: set[str] = field(default_factory=set)  # done | active | crit | milestone


@dataclass
class GanttChart:
    title: str = ""
    date_format: str = "YYYY-MM-DD"
    tasks: list[GanttTask] = field(default_factory=list)


@dataclass
class MindNode:
    label: str = ""
    children: list["MindNode"] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0


@dataclass
class TreeRow:
    label: str
    depth: int = 0
    is_dir: bool = False
    desc: str = ""
    highlight: bool = False
    icon: str | None = None


@dataclass
class EREntity:
    name: str = ""
    attributes: list[str] = field(default_factory=list)  # "type name"
    keys: list[str] = field(
        default_factory=list
    )  # parallel to attributes: "PK", "FK", "PK,FK" or ""


@dataclass
class ERRelation:
    entity_a: str = ""
    entity_b: str = ""
    card_a: str = ""  # one | zero_one | one_many | zero_many
    card_b: str = ""
    label: str = ""
    style: str = "solid"  # solid or dotted


@dataclass
class ERDiagram:
    entities: dict[str, EREntity] = field(default_factory=dict)
    relations: list[ERRelation] = field(default_factory=list)


@dataclass
class StateTransition:
    src: str = ""
    dst: str = ""
    label: str = ""


@dataclass
class StateDiagram:
    direction: str = "LR"
    states: list[str] = field(default_factory=list)
    transitions: list[StateTransition] = field(default_factory=list)


@dataclass
class ClassMember:
    text: str
    visibility: str = ""  # + - # ~
    method: bool = False
    static: bool = False
    abstract: bool = False


@dataclass
class ClassDef:
    name: str
    label: str = ""
    annotation: str = ""  # interface, abstract, enumeration, service, ...
    members: list[ClassMember] = field(default_factory=list)


@dataclass
class ClassRelation:
    a: str
    b: str
    end_a: str = "none"  # inherit | composition | aggregation | arrow | none
    end_b: str = "none"
    dashed: bool = False
    label: str = ""
    card_a: str = ""
    card_b: str = ""


@dataclass
class ClassDiagram:
    classes: dict[str, ClassDef] = field(default_factory=dict)
    relations: list[ClassRelation] = field(default_factory=list)
    notes: list[tuple[str, str]] = field(default_factory=list)  # (class, text)
    namespaces: list[Subgraph] = field(default_factory=list)
    direction: str = "TB"


@dataclass
class JourneyTask:
    name: str
    score: float
    actors: list[str] = field(default_factory=list)
    section: str = ""


@dataclass
class Journey:
    title: str = ""
    tasks: list[JourneyTask] = field(default_factory=list)


@dataclass
class GitCommit:
    id: str
    branch: str
    parents: list[str] = field(default_factory=list)
    tag: str = ""
    kind: str = "normal"  # normal | highlight | reverse | merge | cherry
    seq: int = 0
    msg: str = ""
    explicit_id: bool = False


@dataclass
class GitGraph:
    commits: list[GitCommit] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    branch_base: dict[str, str] = field(default_factory=dict)  # branch -> commit it starts from
    order: dict[str, int] = field(default_factory=dict)
    cherry_sources: dict[int, str] = field(default_factory=dict)  # seq -> source commit id
    direction: str = "LR"


@dataclass
class QuadrantChart:
    title: str = ""
    x_low: str = ""
    x_high: str = ""
    y_low: str = ""
    y_high: str = ""
    quadrants: list[str] = field(default_factory=lambda: ["", "", "", ""])
    points: list[tuple[str, float, float, dict[str, str], str]] = field(default_factory=list)


@dataclass
class Sankey:
    links: list[tuple[str, str, float]] = field(default_factory=list)


@dataclass
class Radar:
    title: str = ""
    axes: list[tuple[str, str]] = field(default_factory=list)  # (id, label)
    curves: list[tuple[str, list[float]]] = field(default_factory=list)  # (label, values)
    max_val: float | None = None
    min_val: float = 0.0
    ticks: int = 5
    graticule: str = "circle"
    show_legend: bool = True


@dataclass
class TreeItem:
    name: str
    value: float | None = None
    children: list["TreeItem"] = field(default_factory=list)


@dataclass
class Packet:
    title: str = ""
    fields: list[tuple[int, int, str]] = field(default_factory=list)  # (start, end, label)


@dataclass
class BlockItem:
    id: str
    label: str = ""
    kind: str = "node"  # node | space | arrow | group
    span: int = 1
    shape: str = "rect"
    children: list["BlockItem"] = field(default_factory=list)
    columns: int = 0  # 0 = one row (auto)
    arrow: list[str] = field(default_factory=list)  # block-arrow directions
    classes: list[str] = field(default_factory=list)
    css: dict[str, str] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


@dataclass
class BlockDiagram:
    root: BlockItem = field(default_factory=lambda: BlockItem("", kind="group"))
    edges: list[tuple[str, str, str, str]] = field(default_factory=list)  # src, dst, label, head


@dataclass
class KanbanItem:
    text: str
    meta: dict[str, str] = field(default_factory=dict)


@dataclass
class KanbanColumn:
    title: str
    items: list[KanbanItem] = field(default_factory=list)


@dataclass
class ArchItem:
    id: str
    label: str = ""
    icon: str = ""
    parent: str = ""
    junction: bool = False


@dataclass
class ArchEdge:
    a: str
    side_a: str
    b: str
    side_b: str
    arrow_a: bool = False
    arrow_b: bool = False


@dataclass
class Architecture:
    groups: dict[str, ArchItem] = field(default_factory=dict)
    services: dict[str, ArchItem] = field(default_factory=dict)
    edges: list[ArchEdge] = field(default_factory=list)
    aligns: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class C4Element:
    alias: str
    label: str
    level: str  # person | system | container | component
    ext: bool = False
    shape: str = "box"  # box | db | queue
    techn: str = ""
    descr: str = ""


@dataclass
class C4Boundary:
    alias: str
    label: str
    type: str = ""
    kind: str = "boundary"  # boundary | deployment
    elements: list[C4Element] = field(default_factory=list)
    boundaries: list["C4Boundary"] = field(default_factory=list)


@dataclass
class C4Rel:
    src: str
    dst: str
    label: str = ""
    techn: str = ""
    bi: bool = False


@dataclass
class C4Diagram:
    kind: str = "C4Context"
    title: str = ""
    root: C4Boundary = field(default_factory=lambda: C4Boundary("", ""))
    elements: dict[str, C4Element] = field(default_factory=dict)
    rels: list[C4Rel] = field(default_factory=list)
    shape_in_row: int = 4
    boundary_in_row: int = 2


@dataclass
class ReqNode:
    name: str
    kind: str  # display type, e.g. "Functional Requirement" or "Element"
    fields: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class RequirementDiagram:
    nodes: dict[str, ReqNode] = field(default_factory=dict)
    relations: list[tuple[str, str, str]] = field(default_factory=list)  # src, dst, type
    direction: str = "TD"


# ---------------------------------------------------------------------------
# Default theme (matches _pdf-theme.css palette)
# ---------------------------------------------------------------------------

DEFAULT_THEME: dict[str, str] = {
    "primary": "#1b4f72",
    "accent": "#2e86c1",
    "body": "#1f2328",
    "muted": "#5d6d7e",
    "font": "Segoe UI, Helvetica Neue, Arial, sans-serif",
}

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
# One type scale, one ink ramp and one validated categorical palette shared by
# every renderer, so all diagrams read as one family and sit at body-text size
# (1 SVG px renders as 0.75pt, so 12px labels sit beside ~10pt body text).

_FS = 12.0  # primary labels: node text, slice names, categories
_FS_SM = 10.5  # secondary text: edge labels, ticks, legend values
_FS_TITLE = 13.5  # diagram titles
_CHAR_W = 0.56  # average glyph advance as a fraction of font size (layout estimate)

_INK = "#1f2328"
_INK_2 = "#57606a"
_MUTED = "#8c959f"
_GRID = "#e8e7e2"
_BASELINE = "#c3c2b7"
_EDGE = "#8a939d"

# Categorical slots for data charts, assigned in this fixed order (never cycled):
# the order is what keeps adjacent slots distinguishable with colour-vision
# deficiencies (adjacent-pair CVD delta-E >= 9 on a light surface).
_CATEGORICAL = [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#6250d6",
    "#e34948",
]
_OTHER = "#b9b8b0"  # folded tail ("Other") once the eight slots are used
_CRITICAL = "#d03b3b"  # status colour, reserved for `crit` gantt tasks


# Validated dark-surface steps of the same eight hues (same order)
_CATEGORICAL_DARK = [
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#008300",
    "#9085e9",
    "#e66767",
]
_OTHER_DARK = "#6e7681"
_DARK_SURFACE = "#0d1117"


# ---------------------------------------------------------------------------
# Text measurement
# ---------------------------------------------------------------------------
# Layout needs real text widths: an estimate is fine for Inter but too narrow
# for wide faces such as DejaVu Sans, which overflows its boxes. Widths come
# from the actual font file (resolved the way the renderers resolve it), with
# the estimate as a fallback when no file can be found.

_ACTIVE_FONT: ContextVar[str] = ContextVar("mermaid_font", default="")
_ACTIVE_SURFACE: ContextVar[str] = ContextVar("mermaid_surface", default="")
_ACTIVE_CONFIG: ContextVar[dict] = ContextVar("mermaid_config", default={})  # noqa: B039
_REGISTERED_FONTS: dict[str, dict[int, Path]] = {}  # family (lower) -> weight -> file
_FONT_FILE_CACHE: dict[tuple[str, int], Path | None] = {}
_METRICS_CACHE: dict[Path, "_FontMetrics | None"] = {}
_FC_ADDED: set[Path] = set()
_FONT_GENERATION = [0]  # bumped whenever a new font file is registered


def font_generation() -> int:
    """Changes whenever :func:`register_fonts` adds a font (rasterisers drop caches then)."""
    return _FONT_GENERATION[0]


class _FontMetrics:
    """Advance widths from one font file (no shaping or kerning: close enough for layout)."""

    def __init__(self, path: Path) -> None:
        from fontTools.ttLib import TTFont

        font = TTFont(str(path), lazy=True, fontNumber=0)
        self.cmap = font.getBestCmap() or {}
        self.hmtx = font["hmtx"].metrics
        self.upm = float(font["head"].unitsPerEm)
        fallback = self.cmap.get(ord("n"))
        self.default = self.hmtx[fallback][0] if fallback in self.hmtx else self.upm * 0.55

    def width(self, text: str, size: float) -> float:
        total = 0.0
        for ch in text:
            glyph = self.cmap.get(ord(ch))
            total += self.hmtx[glyph][0] if glyph in self.hmtx else self.default
        return total / self.upm * size


def _weight_num(weight: object) -> int:
    text = str(weight).strip().lower()
    if text.isdigit():
        return int(text)
    return 700 if text == "bold" else 400


def register_fonts(faces: Iterable[tuple[str, str | Path, object]]) -> None:
    """Make ``(family, file, weight)`` fonts available to diagrams.

    Used for the ``fonts`` config key: layout measures text with these files, and
    they are added to fontconfig so Word/PowerPoint rasters draw them too.
    """
    for family, path, weight in faces:
        file = Path(path)
        if not file.is_file():
            continue
        _REGISTERED_FONTS.setdefault(family.strip().lower(), {})[_weight_num(weight)] = file
        if file not in _FC_ADDED:
            _FC_ADDED.add(file)
            _FONT_GENERATION[0] += 1
            try:
                lib = ctypes.util.find_library("fontconfig")
                if lib:
                    fc = ctypes.CDLL(lib)
                    fc.FcConfigAppFontAddFile(None, str(file).encode())
            except Exception as exc:  # pragma: no cover - platform dependent
                logger.debug("fontconfig registration failed for %s: %s", file, exc)
    _FONT_FILE_CACHE.clear()


def _font_file(stack: str, weight: int) -> Path | None:
    """The file that will draw ``stack`` at ``weight``: registered fonts, then fontconfig."""
    key = (stack, 700 if weight >= 600 else 500 if weight >= 500 else 400)
    if key in _FONT_FILE_CACHE:
        return _FONT_FILE_CACHE[key]
    families = [f.strip().strip("'\"") for f in stack.split(",") if f.strip()]
    found: Path | None = None
    for fam in families:
        faces = _REGISTERED_FONTS.get(fam.lower())
        if faces:
            found = faces[min(faces, key=lambda w: abs(w - key[1]))]
            break
    if found is None and shutil.which("fc-match"):
        fc_weight = {400: 80, 500: 100, 700: 200}[key[1]]
        pattern = ",".join(families or ["sans-serif"]) + f":weight={fc_weight}"
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{file}", pattern],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            ).stdout.strip()
            found = Path(out) if out and Path(out).is_file() else None
        except Exception:  # pragma: no cover - fontconfig missing/misconfigured
            found = None
    _FONT_FILE_CACHE[key] = found
    return found


def _metrics(weight: int) -> "_FontMetrics | None":
    stack = _ACTIVE_FONT.get() or DEFAULT_THEME["font"]
    path = _font_file(stack, weight)
    if path is None:
        return None
    if path not in _METRICS_CACHE:
        try:
            _METRICS_CACHE[path] = _FontMetrics(path)
        except Exception as exc:
            logger.debug("font metrics unavailable for %s: %s", path, exc)
            _METRICS_CACHE[path] = None
    return _METRICS_CACHE[path]


def _text_w(text: str, size: float = _FS, weight: int = 400) -> float:
    """Rendered width of ``text`` at ``size`` px in the active diagram font."""
    m = _metrics(weight)
    if m is None:
        return len(text) * size * _CHAR_W * (1.06 if weight >= 600 else 1.0)
    return m.width(text, size) * 1.03  # a hair of slack for kerning/hinting differences


# ---------------------------------------------------------------------------
# Colour helpers and token sets
# ---------------------------------------------------------------------------


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(color: str, toward: str, factor: float) -> str:
    """Blend ``color`` toward ``toward`` by ``factor`` (0 = color, 1 = toward)."""
    (r1, g1, b1), (r2, g2, b2) = _rgb(color), _rgb(toward)
    return "#{:02x}{:02x}{:02x}".format(
        *(int(round(a + (b - a) * factor)) for a, b in ((r1, r2), (g1, g2), (b1, b2)))
    )


def _luminance(color: str) -> float:
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _tint(color: str, factor: float, t: dict[str, str]) -> str:
    """A tint of ``color`` toward the diagram surface (white, or the dark surface)."""
    return _mix(color, t["surface"], factor)


def _palette(t: dict[str, str]) -> list[str]:
    series = t.get("series")
    if series:
        return series.split(",")
    return _CATEGORICAL_DARK if t.get("mode") == "dark" else _CATEGORICAL


def _distance(a: str, b: str) -> float:
    ra, rb = _rgb(a), _rgb(b)
    return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5


def _series_palette(
    lead: list[str], fallback: list[str], size: int = 8, keep_lead: bool = False
) -> list[str]:
    """Eight series colours: the ``lead`` colours first (all of them when ``keep_lead``,
    else only those clearly different from each other), then the validated categorical
    colours that stay clearly different from every colour chosen so far."""
    chosen: list[str] = list(lead[:size]) if keep_lead else []
    for colour in [] if keep_lead else lead:
        if len(chosen) < size and all(_distance(colour, c) >= 90 for c in chosen):
            chosen.append(colour)
    for colour in fallback:
        if len(chosen) == size:
            break
        if all(_distance(colour, c) >= 90 for c in chosen):
            chosen.append(colour)
    for colour in fallback:  # never run short, even if every candidate was close
        if len(chosen) == size:
            break
        if colour not in chosen:
            chosen.append(colour)
    return chosen


def _tokens(theme: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve the full colour/typography token set for one render.

    Brand colours come from the theme (``primary``/``accent``/``body``/``font``);
    every tint is derived from them so diagrams follow the document's brand.
    ``mode: dark`` switches to the dark token set. Explicit keys in ``theme``
    (e.g. ``node_fill``) still win.
    """
    given = theme or {}
    t = {**DEFAULT_THEME, **given}
    dark = t.get("mode") == "dark"
    surface = t.get("surface") or (_DARK_SURFACE if dark else "#ffffff")
    t["surface"] = surface
    primary, accent = t["primary"], t["accent"]
    if dark:
        # Brand colours are usually dark; lift them until they read on the surface
        while _luminance(primary) < 0.12:
            primary = _mix(primary, "#ffffff", 0.18)
        while _luminance(accent) < 0.16:
            accent = _mix(accent, "#ffffff", 0.18)
        body = t.get("body", "")
        derived = {
            "ink": body if body and _luminance(body) > 0.5 else "#e6edf3",
            "ink2": "#b1bac4",
            "chrome": "#8b949e",
            "grid": "#262c33",
            "baseline": "#3d444d",
            "edge": "#7d8590",
            "hairline": "#262c33",
            "card": _mix(surface, "#ffffff", 0.05),
            "shadow": "0",
            "msg": "#b1bac4",
            "lifeline": "#3d444d",
            "frame": "#3d444d",
            "tag_fill": _mix(surface, "#ffffff", 0.08),
            "node_fill": _mix(primary, surface, 0.78),
            "node_stroke": _mix(primary, surface, 0.25),
            "term_fill": primary,
            "diamond_fill": _mix(accent, surface, 0.8),
            "diamond_stroke": _mix(accent, surface, 0.2),
            "subgraph_fill": _mix(primary, surface, 0.93),
            "subgraph_stroke": _mix(primary, surface, 0.7),
            "subgraph_label": "#b1bac4",
            "note_fill": "#2d2610",
            "note_stroke": "#5c4a1a",
            "other": _OTHER_DARK,
        }
    else:
        derived = {
            "ink": t.get("body", _INK),
            "ink2": _INK_2,
            "chrome": _MUTED,
            "grid": _GRID,
            "baseline": _BASELINE,
            "edge": _EDGE,
            "hairline": "#eef0f2",
            "card": "#ffffff",
            "shadow": "0.07",
            "msg": "#57606a",
            "lifeline": "#d0d7de",
            "frame": "#c9ced4",
            "tag_fill": "#f3f4f6",
            "node_fill": _mix(primary, surface, 0.94),
            "node_stroke": _mix(primary, surface, 0.55),
            "term_fill": primary,
            "diamond_fill": _mix(accent, surface, 0.9),
            "diamond_stroke": _mix(accent, surface, 0.35),
            "subgraph_fill": _mix(primary, surface, 0.975),
            "subgraph_stroke": _mix(primary, surface, 0.82),
            "subgraph_label": _INK_2,
            "note_fill": "#fff8e6",
            "note_stroke": "#ecd9a6",
            "other": _OTHER,
        }
    t["primary"], t["accent"] = primary, accent
    fallback = _CATEGORICAL_DARK if dark else _CATEGORICAL
    if "series" not in given:
        if given.get("palette"):
            t["series"] = ",".join(
                _series_palette(given["palette"].split(","), fallback, keep_lead=True)
            )
        elif given.get("brand") == "1":
            t["series"] = ",".join(_series_palette([primary, accent], fallback))
    for key, value in derived.items():
        if key not in given:
            t[key] = value
    if "term_text" not in given:
        t["term_text"] = "#ffffff" if _luminance(t["term_fill"]) < 0.4 else "#1f2328"
    _ACTIVE_FONT.set(t["font"])
    _ACTIVE_SURFACE.set(surface if dark else "")
    return t


def _svg_root(width: float, height: float, body: str | list[str], font: str = "") -> str:
    """Wrap SVG content in a root element sized by its viewBox."""
    if isinstance(body, list):
        body = "\n".join(body)
    font_attr = f' font-family="{_escape(font)}"' if font else ""
    surface = _ACTIVE_SURFACE.get()
    surface_attr = f' data-surface="{surface}"' if surface else ""
    if surface and 'data-panel="1"' not in body:
        # A dark diagram brings its own panel, so it reads on a light page too
        width, height = width + 28, height + 28
        body = (
            f'<rect data-panel="1" width="{width:g}" height="{height:g}" rx="8" fill="{surface}"/>\n'
            f'<g transform="translate(14,14)">\n{body}\n</g>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width:g} {height:g}" preserveAspectRatio="xMidYMid meet"'
        f"{font_attr}{surface_attr}>\n"
        f"{body}\n</svg>"
    )


def svg_natural_width(svg: str) -> float | None:
    """The diagram's natural width in px (its viewBox width), if known."""
    m = re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"', svg)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# CSS theme extraction
# ---------------------------------------------------------------------------


_VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)")
_DECL_VAR_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+)")


def _css_variables(css_text: str) -> dict[str, str]:
    """Custom properties declared anywhere in the CSS; a later declaration wins."""
    clean = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    return {name: value.strip() for name, value in _DECL_VAR_RE.findall(clean)}


def _resolve_vars(value: str, variables: dict[str, str], depth: int = 0) -> str:
    """Replace ``var(--name, fallback)`` with its value (nested, depth-limited)."""
    if depth > 8 or "var(" not in value:
        return value

    def sub(m: re.Match[str]) -> str:
        found = variables.get(m.group(1))
        return found if found is not None else (m.group(2) or "")

    return _resolve_vars(_VAR_RE.sub(sub, value), variables, depth + 1)


def css_color_to_hex(value: str, variables: dict[str, str] | None = None) -> str | None:
    """A CSS colour (hex, ``rgb()``, ``hsl()``, a name, ``var(--x)``) as ``#rrggbb``."""
    value = _resolve_vars(value.strip().rstrip(";"), variables or {}).strip()
    value = re.sub(r"\s*!important$", "", value, flags=re.IGNORECASE)
    if not value or value.lower() in ("transparent", "inherit", "initial", "currentcolor", "none"):
        return None
    # Modern space-separated syntax: rgb(10 20 30 / 50%) -> rgb(10,20,30)
    m = re.fullmatch(r"(rgba?|hsla?)\(([^)]*)\)", value, flags=re.IGNORECASE)
    if m:
        parts = re.split(r"\s*[,/\s]\s*", m.group(2).strip())
        value = f"{m.group(1).lower()[:3]}({','.join(parts[:3])})"
        value = value.replace("deg", "")
    try:
        from PIL import ImageColor

        r, g, b = ImageColor.getrgb(value)[:3]
    except Exception:
        return None
    return f"#{r:02x}{g:02x}{b:02x}"


def extract_theme_from_css(css_text: str) -> dict[str, str]:
    """Extract diagram theme colours from a theme CSS file (after ``@import``s are merged).

    Explicit ``--mddoc-diagram-*`` custom properties win; otherwise colours are
    read from the headings, links, body and cover rules. Colours may be hex,
    ``rgb()``, ``hsl()``, names or ``var(--x)``. Where a theme is layered
    (a client theme importing the brand theme), the declaration that comes last
    in the merged CSS wins, as in the cascade.
    """
    theme: dict[str, str] = {}
    variables = _css_variables(css_text)
    clean = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    value = r"([^;{}]+)"

    def _latest(patterns: list[str], colour: bool = True) -> str | None:
        """The match that appears last in the CSS across all alternatives."""
        best: tuple[int, str] | None = None
        for pattern in patterns:
            for m in re.finditer(pattern + value, clean, re.IGNORECASE):
                got = (
                    css_color_to_hex(m.group(1), variables)
                    if colour
                    else _resolve_vars(m.group(1), variables).strip()
                )
                if got and (best is None or m.start() >= best[0]):
                    best = (m.start(), got)
        return best[1] if best else None

    def _prop(rule: str, prop: str) -> str:
        return rf"{rule}[^{{}}]*\{{[^}}]*{prop}\s*:\s*"

    primary = _latest(
        [
            _prop(r"\.cover-title\b", "color"),
            _prop(r"\bh1\b", "color"),
            _prop(r"\bth\b", r"background(?:-color)?"),
        ]
    )
    accent = _latest(
        [
            _prop(r"\bh2\b", "color"),
            _prop(r"\ba\b", "color"),
            _prop(r"\.cover-label\b", "color"),
        ]
    )
    body = _latest([_prop(r"\bbody\b", "color")])
    muted = _latest([_prop(r"\bh3\b", "color"), _prop(r"\bem\b", "color")])
    font = _latest([_prop(r"\bbody\b", "font-family")], colour=False)
    background = _latest(
        [_prop(r"\bbody\b", r"background(?:-color)?"), _prop(r"@page", r"background(?:-color)?")]
    )

    # Explicit diagram properties always win over what is inferred.
    def _explicit(name: str) -> str | None:
        raw = variables.get(f"--mddoc-diagram-{name}")
        return css_color_to_hex(raw, variables) if raw else None

    primary = _explicit("primary") or primary
    accent = _explicit("accent") or accent
    body = _explicit("text") or body
    muted = _explicit("muted") or muted
    background = _explicit("surface") or background
    raw_font = variables.get("--mddoc-diagram-font")
    if raw_font:
        font = _resolve_vars(raw_font, variables).strip()

    if primary:
        theme["primary"] = primary
        theme["brand"] = "1"  # chart series start from the brand colours
    if accent:
        theme["accent"] = accent
    if body:
        theme["body"] = body
    if muted:
        theme["muted"] = muted
    if font:
        theme["font"] = font

    palette = variables.get("--mddoc-diagram-palette", "").strip()
    if palette.lower() in ("default", "validated", "none"):
        theme["brand"] = "0"  # keep the built-in validated palette
    elif palette:
        colours = [
            hexed
            for part in re.split(r",(?![^()]*\))", _resolve_vars(palette, variables))
            if (hexed := css_color_to_hex(part, variables))
        ]
        if colours:
            theme["palette"] = ",".join(colours)

    mode = variables.get("--mddoc-diagram-mode", "").strip().lower()
    if mode == "dark" or (mode != "light" and background and _luminance(background) < 0.2):
        theme["mode"] = "dark"
        if background:
            theme["surface"] = background
    elif _explicit("surface"):
        theme["surface"] = background or ""  # a tinted light surface, e.g. cream paper
    return theme


def _lighten(hex_color: str, factor: float) -> str:
    """Lighten a hex colour toward white by factor (0=original, 1=white)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Flowchart parser
# ---------------------------------------------------------------------------

# Patterns for node shapes in definitions and inline in edges
_NODE_PATTERNS = [
    # Order matters — more specific patterns first
    # A(["label"]) — stadium
    (re.compile(r'^([A-Za-z_]\w*)\(\["([^"]+)"\]\)$'), "stadium"),
    (re.compile(r"^([A-Za-z_]\w*)\(\['([^']+)'\]\)$"), "stadium"),
    # A(("label")) — circle
    (re.compile(r'^([A-Za-z_]\w*)\(\("([^"]+)"\)\)$'), "circle"),
    (re.compile(r"^([A-Za-z_]\w*)\(\('([^']+)'\)\)$"), "circle"),
    # A[("label")] — cylinder
    (re.compile(r'^([A-Za-z_]\w*)\[\("([^"]+)"\)\]$'), "cylinder"),
    (re.compile(r"^([A-Za-z_]\w*)\[\('([^']+)'\)\]$"), "cylinder"),
    # A{{"label"}} — hexagon
    (re.compile(r'^([A-Za-z_]\w*)\{\{"([^"]+)"\}\}$'), "hexagon"),
    (re.compile(r"^([A-Za-z_]\w*)\{\{'([^']+)'\}\}$"), "hexagon"),
    # A[["label"]] — subroutine
    (re.compile(r'^([A-Za-z_]\w*)\[\["([^"]+)"\]\]$'), "subroutine"),
    (re.compile(r"^([A-Za-z_]\w*)\[\['([^']+)'\]\]$"), "subroutine"),
    # A{"label"} — diamond
    (re.compile(r'^([A-Za-z_]\w*)\{"([^"]+)"\}$'), "diamond"),
    (re.compile(r"^([A-Za-z_]\w*)\{'([^']+)'\}$"), "diamond"),
    # A("label") — rounded rectangle
    (re.compile(r'^([A-Za-z_]\w*)\("([^"]+)"\)$'), "rounded"),
    (re.compile(r"^([A-Za-z_]\w*)\('([^']+)'\)$"), "rounded"),
    # A["label"] — rect (must be after [["]] and [(")])
    (re.compile(r'^([A-Za-z_]\w*)\["([^"]+)"\]$'), "rect"),
    (re.compile(r"^([A-Za-z_]\w*)\['([^']+)'\]$"), "rect"),
    # Slanted shapes and flag
    (re.compile(r"^([A-Za-z_]\w*)\[/(.*?)\\\]$"), "trapezoid"),  # A[/label\]
    (re.compile(r"^([A-Za-z_]\w*)\[\\(.*?)/\]$"), "trapezoid_alt"),  # A[\label/]
    (re.compile(r"^([A-Za-z_]\w*)\[/(.*?)/\]$"), "parallelogram"),  # A[/label/]
    (re.compile(r"^([A-Za-z_]\w*)\[\\(.*?)\\\]$"), "parallelogram_alt"),  # A[\label\]
    (re.compile(r"^([A-Za-z_]\w*)>([^\]]+)\]$"), "flag"),  # A>label]
    # ---- Unquoted labels (the common Mermaid form, e.g. A[Plan]) ----
    # Ordered specific-first so multi-char delimiters win over single-char ones.
    (re.compile(r"^([A-Za-z_]\w*)\(\[([^\]]+)\]\)$"), "stadium"),  # A([label])
    (re.compile(r"^([A-Za-z_]\w*)\(\(([^)]+)\)\)$"), "circle"),  # A((label))
    (re.compile(r"^([A-Za-z_]\w*)\[\(([^)]+)\)\]$"), "cylinder"),  # A[(label)]
    (re.compile(r"^([A-Za-z_]\w*)\{\{([^}]+)\}\}$"), "hexagon"),  # A{{label}}
    (re.compile(r"^([A-Za-z_]\w*)\[\[([^\]]+)\]\]$"), "subroutine"),  # A[[label]]
    (re.compile(r"^([A-Za-z_]\w*)\{([^}]+)\}$"), "diamond"),  # A{label}
    (re.compile(r"^([A-Za-z_]\w*)\(([^)]+)\)$"), "rounded"),  # A(label)
    (re.compile(r"^([A-Za-z_]\w*)\[([^\]]+)\]$"), "rect"),  # A[label]
]

# Edge operators. One regex covers every Mermaid link form:
#   plain      -->  ---  --o  --x  ==>  ===  -.->  -.-   (any extra length)
#   text       -- text -->   == text ==>   -. text .->
#   both ways  <-->  o--o  x--x
# optionally followed by a pipe label:  -->|label|
_EDGE_RE = re.compile(
    r"""
    (?:(?P<lhead><)|(?<!\w)(?P<lmark>[ox])(?=[-=.]))?
    (?:
        (?P<tdash>--|==|-\.)[ \t]+(?P<text>[^<>|]*?\S)[ \t]+
        (?P<tend>-{2,}>|-{3,}|-{2}[ox](?=\s|$)|={2,}>|={3,}|={2}[ox](?=\s|$)
                 |\.-+>|\.-+(?![>\w])|\.-[ox](?=\s|$))
      |
        (?P<plain>-{2,}>|-{3,}|-{2,}[ox](?=\s|$|\|)|={2,}>|={3,}|={2,}[ox](?=\s|$|\|)
                 |-\.+-?>|-\.+-(?![>\w]))
    )
    (?:\|(?P<pipe>[^|]*)\|)?
    [ \t]*
    """,
    re.VERBOSE,
)


def _mask(text: str) -> str:
    """Blank out quoted text and bracketed node labels so operators inside them are ignored."""
    out: list[str] = []
    depth = 0
    quote = False
    for i, ch in enumerate(text):
        if quote:
            out.append("\0")
            quote = ch != '"'
        elif ch == '"':
            out.append("\0")
            quote = True
        elif ch in "([{" or (ch == ">" and i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")):
            depth += 1
            out.append(ch if depth == 1 else "\0")
        elif ch in ")]}":
            out.append(ch if depth == 1 else "\0")
            depth = max(depth - 1, 0)
        else:
            out.append("\0" if depth else ch)
    return "".join(out)


def _end_marker(op: str) -> str:
    return {">": "arrow", "o": "circle", "x": "cross"}.get(op[-1:], "none")


def _parse_css(text: str) -> dict[str, str]:
    """Parse ``fill:#f9f,stroke:#333,stroke-width:2px`` into a dict."""
    out: dict[str, str] = {}
    for decl in re.split(r",(?![^(]*\))", text):
        if ":" in decl:
            key, value = decl.split(":", 1)
            out[key.strip().lower()] = value.strip().rstrip(";")
    return out


def _ensure_node(fc: Flowchart, token: str) -> str:
    """Parse a node token, register it if new, return the node ID."""
    token = token.strip()
    if not token:
        return ""

    classes: list[str] = []
    while True:
        cm = re.match(r"^(.*?)\s*:::\s*([\w-]+)$", token)
        if not cm:
            break
        token = cm.group(1).strip()
        classes.insert(0, cm.group(2))

    meta: dict[str, str] = {}
    mm = re.match(r"^(.*?)\s*@\{(.*)\}$", token, re.DOTALL)
    if mm:
        token = mm.group(1).strip()
        for key, value in re.findall(r"(\w+)\s*:\s*(\"[^\"]*\"|'[^']*'|[^,]+)", mm.group(2)):
            meta[key.lower()] = value.strip().strip("\"'")

    nid = _ensure_node_token(fc, token)
    if nid in fc.nodes:
        node = fc.nodes[nid]
        node.classes.extend(c for c in classes if c not in node.classes)
        if meta.get("shape"):
            node.shape = _SHAPE_ALIASES.get(meta["shape"].lower(), "rect")
        if meta.get("label"):
            node.label = meta["label"]
    return nid


# Mermaid v11 named shapes (``A@{ shape: cyl }``) and the agentflow aliases
_SHAPE_ALIASES = {
    **{k: "rect" for k in ("rect", "rectangle", "proc", "process", "card", "notched-rectangle")},
    **{k: "rounded" for k in ("rounded", "event", "task")},
    **{k: "stadium" for k in ("stadium", "pill", "terminal")},
    **{k: "subroutine" for k in ("subroutine", "subproc", "fr-rect", "framed-rectangle", "tool")},
    **{k: "cylinder" for k in ("cyl", "cylinder", "database", "db", "h-cyl", "das")},
    **{k: "circle" for k in ("circle", "circ", "dbl-circ", "double-circle", "sm-circ", "start")},
    **{k: "diamond" for k in ("diamond", "diam", "decision", "question")},
    **{k: "hexagon" for k in ("hex", "hexagon", "prepare", "action")},
    **{k: "parallelogram" for k in ("lean-r", "lean-right", "in-out", "input")},
    **{k: "parallelogram_alt" for k in ("lean-l", "lean-left", "out-in")},
    **{k: "trapezoid" for k in ("trap-b", "trapezoid", "priority")},
    **{k: "trapezoid_alt" for k in ("trap-t", "inv-trapezoid", "manual")},
    **{k: "document" for k in ("doc", "document", "lin-doc", "docs", "documents", "refdoc")},
    **{k: "flag" for k in ("flag", "asym", "paper-tape")},
    "ellipse": "ellipse",
    "actor": "actor",
}


def _ensure_node_token(fc: Flowchart, token: str) -> str:
    for pattern, shape in _NODE_PATTERNS:
        m = pattern.match(token)
        if m:
            nid, label = m.group(1), m.group(2).strip()
            if nid not in fc.nodes:
                fc.nodes[nid] = Node(id=nid, label=label, shape=shape)
            else:
                fc.nodes[nid].label = label
                fc.nodes[nid].shape = shape
            return nid

    # Plain ID (no shape/label decoration)
    nid = token
    if re.match(r"^[A-Za-z_]\w*$", nid) and nid not in fc.nodes:
        fc.nodes[nid] = Node(id=nid, label=nid, shape="rect")
    return nid


def _slug(text: str) -> str:
    return re.sub(r"\W+", "_", text).strip("_") or "group"


def parse(source: str) -> Flowchart:
    """Parse Mermaid flowchart source into a Flowchart model."""
    fc = Flowchart()
    subgraph_stack: list[Subgraph] = []
    class_defs: dict[str, dict[str, str]] = {}
    class_assign: list[tuple[list[str], list[str]]] = []
    node_styles: dict[str, dict[str, str]] = defaultdict(dict)
    link_styles: list[tuple[list[int] | None, dict[str, str]]] = []

    for raw_line in source.strip().splitlines():
        line = raw_line.strip().rstrip(";").strip()
        if not line or line.startswith("%%"):
            continue

        dir_m = re.match(r"^(?:flowchart|graph)(?:\s+(LR|TD|TB|RL|BT))?\s*$", line, re.IGNORECASE)
        if dir_m:
            if dir_m.group(1):
                fc.direction = dir_m.group(1).upper()
            continue
        if re.match(r"^direction\s+(LR|TD|TB|RL|BT)\s*$", line, re.IGNORECASE) or line.startswith(
            ("click ", "accTitle", "accDescr")
        ):
            continue

        # Styling statements
        m = re.match(r"^style\s+(\S+)\s+(.+)$", line)
        if m:
            for nid in m.group(1).split(","):
                node_styles[nid.strip()].update(_parse_css(m.group(2)))
            continue
        m = re.match(r"^classDef\s+(\S+)\s+(.+)$", line)
        if m:
            for name in m.group(1).split(","):
                class_defs.setdefault(name.strip(), {}).update(_parse_css(m.group(2)))
            continue
        m = re.match(r"^class\s+(\S+)\s+(\S+)$", line)
        if m:
            class_assign.append(
                (
                    [x.strip() for x in m.group(1).split(",")],
                    [x.strip() for x in m.group(2).split(",")],
                )
            )
            continue
        m = re.match(r"^linkStyle\s+(default|[\d,\s]+?)\s+(.+)$", line)
        if m:
            idxs = None if m.group(1) == "default" else [int(x) for x in m.group(1).split(",")]
            link_styles.append((idxs, _parse_css(m.group(2))))
            continue

        # Subgraphs: `subgraph id`, `subgraph id [Title]`, `subgraph "Title"`, `subgraph Title`
        m = re.match(r"^subgraph\s+(.+)$", line)
        if m:
            rest = m.group(1).strip()
            tm = re.match(r'^([A-Za-z_][\w-]*)\s*\[\s*"?(.*?)"?\s*\]$', rest)
            if tm:
                sg_id, sg_label = tm.group(1), tm.group(2)
            else:
                sg_label = rest.strip('"')
                sg_id = _slug(sg_label)
            sg = Subgraph(id=sg_id, label=sg_label)
            if subgraph_stack:
                subgraph_stack[-1].children.append(sg.id)
            subgraph_stack.append(sg)
            fc.subgraphs.append(sg)  # outer groups first so they are drawn behind inner ones
            continue
        if line == "end":
            if subgraph_stack:
                subgraph_stack.pop()
            continue

        before = set(fc.nodes)
        if any(True for _ in _EDGE_RE.finditer(_mask(line))):
            _parse_edge_line(fc, line)
        else:
            _ensure_node(fc, line)
        # Mermaid scopes a node to the group where it is first mentioned.
        if subgraph_stack:
            for nid in fc.nodes:
                if nid not in before and nid not in subgraph_stack[-1].node_ids:
                    subgraph_stack[-1].node_ids.append(nid)

    _apply_styles(fc, class_defs, class_assign, node_styles, link_styles)
    _attach_subgraph_edges(fc)
    return fc


def _subgraph_members(fc: Flowchart, sg: Subgraph) -> list[str]:
    by_id = {g.id: g for g in fc.subgraphs}
    out = [n for n in sg.node_ids if n in fc.nodes]
    for child in sg.children:
        if child in by_id:
            out += _subgraph_members(fc, by_id[child])
    return out


def _attach_subgraph_edges(fc: Flowchart) -> None:
    """``A --> group`` targets the group's first node; ``group --> B`` leaves from its last."""
    groups = {sg.id: sg for sg in fc.subgraphs}
    hits = {e.src for e in fc.edges if e.src in groups} | {
        e.dst for e in fc.edges if e.dst in groups
    }
    for gid in hits:
        node = fc.nodes.get(gid)
        if node is not None and node.label == gid:
            del fc.nodes[gid]  # created by the edge parser, not a real node
            for sg in fc.subgraphs:
                if gid in sg.node_ids:
                    sg.node_ids.remove(gid)
    for e in fc.edges:
        if e.dst in groups and e.dst not in fc.nodes:
            members = _subgraph_members(fc, groups[e.dst])
            if members:
                e.dst = members[0]
        if e.src in groups and e.src not in fc.nodes:
            members = _subgraph_members(fc, groups[e.src])
            if members:
                e.src = members[-1]
    fc.edges = [e for e in fc.edges if e.src in fc.nodes and e.dst in fc.nodes]


def _apply_styles(
    fc: Flowchart,
    class_defs: dict[str, dict[str, str]],
    class_assign: list[tuple[list[str], list[str]]],
    node_styles: dict[str, dict[str, str]],
    link_styles: list[tuple[list[int] | None, dict[str, str]]],
) -> None:
    """Resolve classDef / class / style / linkStyle into per-node and per-edge overrides."""
    assigned: dict[str, list[str]] = defaultdict(list)
    for ids, names in class_assign:
        for nid in ids:
            assigned[nid].extend(names)
    for nid, node in fc.nodes.items():
        css = dict(class_defs.get("default", {}))
        for name in [*node.classes, *assigned.get(nid, [])]:
            css.update(class_defs.get(name, {}))
        css.update(node_styles.get(nid, {}))
        node.css = css
    for idxs, css in link_styles:
        for i in range(len(fc.edges)) if idxs is None else idxs:
            if 0 <= i < len(fc.edges):
                fc.edges[i].css.update(css)


def _parse_edge_line(fc: Flowchart, line: str) -> None:
    """Parse a line holding one or more chained edges (``A --> B & C -.-> D``)."""
    masked = _mask(line)
    spans: list[tuple[int, int]] = []
    ops: list[Edge] = []
    pos = 0
    for m in _EDGE_RE.finditer(masked):
        spans.append((pos, m.start()))
        pos = m.end()
        op = m.group("plain") or m.group("tend") or ""
        label = ""
        if m.group("text") is not None:
            label = line[m.start("text") : m.end("text")]
        elif m.group("pipe") is not None:
            label = line[m.start("pipe") : m.end("pipe")]
        label = re.sub(r"<br\s*/?>", " ", label.strip().strip('"').strip())
        style = "thick" if "=" in op else "dotted" if "." in op else "solid"
        tail = (
            "arrow"
            if m.group("lhead")
            else {"o": "circle", "x": "cross"}.get(m.group("lmark") or "", "none")
        )
        ops.append(Edge("", "", label, style, _end_marker(op), tail))
    spans.append((pos, len(line)))

    groups: list[list[str]] = []
    for start, end in spans:
        chunk, mchunk = line[start:end], masked[start:end]
        cuts = [i for i, c in enumerate(mchunk) if c == "&"]
        pieces, last = [], 0
        for cut in [*cuts, len(chunk)]:
            pieces.append(chunk[last:cut])
            last = cut + 1
        ids = [nid for nid in (_ensure_node(fc, piece) for piece in pieces) if nid in fc.nodes]
        groups.append(ids)

    for i, op in enumerate(ops):
        for src in groups[i]:
            for dst in groups[i + 1]:
                fc.edges.append(Edge(src, dst, op.label, op.style, op.head, op.tail))


# ---------------------------------------------------------------------------
# Pie chart parser
# ---------------------------------------------------------------------------


def parse_pie(source: str) -> PieChart:
    """Parse a Mermaid pie chart definition (``pie [showData] [title …]``)."""
    pc = PieChart()
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        head = re.match(r"^(?:pie|donut)\b(.*)$", line, re.IGNORECASE)
        if head:
            rest = head.group(1).strip()
            if re.match(r"^showData\b", rest, re.IGNORECASE):
                pc.show_data = True
                rest = rest[8:].strip()
            title_m = re.match(r"^title\s+(.+)$", rest, re.IGNORECASE)
            if title_m:
                pc.title = title_m.group(1).strip()
            continue

        title_m = re.match(r"^title\s+(.+)$", line, re.IGNORECASE)
        if title_m:
            pc.title = title_m.group(1).strip()
            continue

        slice_m = re.match(r'^"([^"]+)"\s*:\s*([\d.]+)\s*$', line)
        if slice_m:
            pc.slices.append((slice_m.group(1), float(slice_m.group(2))))

    return pc


# ---------------------------------------------------------------------------
# Sequence diagram parser
# ---------------------------------------------------------------------------

_SEQ_MSG_RE = re.compile(
    r"^(.+?)\s*(<<-->>|<<->>|-->>|->>|--x|-x|--\)|-\)|-->|->)\s*([+-]?)\s*([^:]+?)"
    r"(?:\s*:\s*(.*))?$"
)

_SEQ_NOTE_RE = re.compile(r"^Note\s+(left|right|over)\s+(?:of\s+)?(.+?):\s*(.+)$", re.IGNORECASE)


def parse_sequence(source: str) -> SequenceDiagram:
    """Parse a Mermaid sequence diagram definition."""
    sd = SequenceDiagram()

    def add(pid: str, label: str = "", actor: bool = False) -> None:
        if pid not in sd.participants:
            sd.participants.append(pid)
        if label:
            sd.labels[pid] = label
        if actor:
            sd.actors.add(pid)

    for raw_line in source.strip().splitlines():
        line = raw_line.strip().rstrip(";")
        if not line or line.startswith("%%") or line.lower().startswith("sequencediagram"):
            continue

        m = re.match(r"^(participant|actor)\s+(.+?)(?:\s+as\s+(.+))?$", line, re.IGNORECASE)
        if m:
            add(m.group(2).strip(), (m.group(3) or "").strip(), m.group(1).lower() == "actor")
            continue
        if re.match(r"^autonumber\b", line, re.IGNORECASE):
            sd.autonumber = True
            continue
        m = re.match(r"^(activate|deactivate)\s+(.+)$", line, re.IGNORECASE)
        if m:
            add(m.group(2).strip())
            sd.events.append(SeqActivation(m.group(2).strip(), m.group(1).lower() == "activate"))
            continue
        m = _SEQ_NOTE_RE.match(line)
        if m:
            targets = [x.strip() for x in m.group(2).split(",") if x.strip()]
            for x in targets:
                add(x)
            sd.events.append(SeqNote(m.group(1).lower(), targets, m.group(3).strip()))
            continue
        m = re.match(
            r"^(loop|alt|opt|par|critical|break|rect|else|and|option|end)\b\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        if m:
            sd.events.append(SeqBlock(m.group(1).lower(), m.group(2).strip()))
            continue
        msg_m = _SEQ_MSG_RE.match(line)
        if msg_m:
            src, arrow, act, dst, label = msg_m.groups()
            src, dst, label = src.strip(), dst.strip(), label or ""
            add(src)
            add(dst)
            msg = SeqMessage(src=src, dst=dst, label=label.strip(), arrow=arrow, activate=act)
            sd.messages.append(msg)
            sd.events.append(msg)

    return sd


# ---------------------------------------------------------------------------
# Bar chart parser (xychart-beta or custom "bar" keyword)
# ---------------------------------------------------------------------------


def parse_bar(source: str) -> BarChart:
    """Parse ``xychart-beta`` (or the simple ``bar`` keyword) into a BarChart."""
    bc = BarChart()
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^(xychart-beta|xychart|bar)\b", line, re.IGNORECASE) and "[" not in line:
            if "horizontal" in line.lower():
                bc.horizontal = True
            continue

        title_m = re.match(r'^title\s+"?([^"]+)"?\s*$', line, re.IGNORECASE)
        if title_m:
            bc.title = title_m.group(1).strip()
            continue

        # x-axis ["Q1", "Q2", ...]  /  x-axis "Quarter" [Q1, Q2]
        xaxis_m = re.match(r'^x-axis\s+(?:"([^"]*)"\s*)?\[(.+)\]\s*$', line, re.IGNORECASE)
        if xaxis_m:
            bc.x_title = xaxis_m.group(1) or ""
            bc.labels = [s.strip().strip('"').strip("'") for s in xaxis_m.group(2).split(",")]
            continue

        # y-axis "Revenue" 0 --> 200
        yaxis_m = re.match(
            r'^y-axis\s+(?:"([^"]*)"|(\S+))?\s*(?:(-?[\d.]+)\s*-->\s*(-?[\d.]+))?\s*$',
            line,
            re.IGNORECASE,
        )
        if yaxis_m:
            bc.y_title = yaxis_m.group(1) or ""
            if yaxis_m.group(3) is not None:
                bc.y_min, bc.y_max = float(yaxis_m.group(3)), float(yaxis_m.group(4))
            continue

        # bar [120, 150, ...]  /  line "Target" [100, 130, ...]
        data_m = re.match(r'^(bar|line)\s+(?:"([^"]*)"\s*)?\[(.+)\]\s*$', line, re.IGNORECASE)
        if data_m:
            kind = data_m.group(1).lower()
            vals = [float(v.strip()) for v in data_m.group(3).split(",") if v.strip()]
            bc.datasets.append((kind, vals))
            bc.series_names.append(data_m.group(2) or "")
            continue

        # Simple format: "Label": value
        simple_m = re.match(r'^"([^"]+)"\s*:\s*([\d.]+)\s*$', line)
        if simple_m:
            bc.labels.append(simple_m.group(1))
            if not bc.datasets:
                bc.datasets.append(("bar", []))
                bc.series_names.append("")
            bc.datasets[0][1].append(float(simple_m.group(2)))

    return bc


# ---------------------------------------------------------------------------
# Gauge chart parser (custom syntax)
# ---------------------------------------------------------------------------


def parse_gauge(source: str) -> GaugeChart:
    """Parse a gauge definition (``value 42`` or ``value: 42``)."""
    gc = GaugeChart()
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^gauge\b", line, re.IGNORECASE):
            continue
        m = re.match(r"^(title|value|max|min|label)\s*:?\s*(.+?)\s*$", line, re.IGNORECASE)
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2).strip().strip('"')
        if key in ("title", "label"):
            setattr(gc, key, val)
            continue
        try:
            num = float(val)
        except ValueError:
            continue
        if key == "value":
            gc.value = num
        elif key == "max":
            gc.max_val = num
        else:
            gc.min_val = num
    return gc


# ---------------------------------------------------------------------------
# Timeline parser
# ---------------------------------------------------------------------------


def parse_timeline(source: str) -> Timeline:
    """Parse a Mermaid timeline definition (with optional sections)."""
    tl = Timeline()
    section = ""
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^timeline\b", line, re.IGNORECASE):
            continue

        title_m = re.match(r"^title\s+(.+)$", line, re.IGNORECASE)
        if title_m:
            tl.title = title_m.group(1).strip()
            continue
        sec_m = re.match(r"^section\s+(.+)$", line, re.IGNORECASE)
        if sec_m:
            section = sec_m.group(1).strip()
            continue

        # "period : event1 : event2"; a line starting with ":" adds events to the last period
        if ":" in line:
            parts = [p.strip() for p in line.split(":")]
            events = [e for e in parts[1:] if e]
            if not parts[0] and tl.entries:
                tl.entries[-1].events.extend(events)
            else:
                tl.entries.append(TimelineEntry(period=parts[0], events=events, section=section))
        else:
            tl.entries.append(TimelineEntry(period=line, events=[], section=section))

    return tl


# ---------------------------------------------------------------------------
# Gantt chart parser
# ---------------------------------------------------------------------------


_GANTT_TAGS = {"done", "active", "crit", "milestone"}


def parse_gantt(source: str) -> GanttChart:
    """Parse a Mermaid gantt chart definition."""
    gc = GanttChart()
    current_section = ""
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^gantt\b", line, re.IGNORECASE):
            continue

        title_m = re.match(r"^title\s+(.+)$", line, re.IGNORECASE)
        if title_m:
            gc.title = title_m.group(1).strip()
            continue

        fmt_m = re.match(r"^dateFormat\s+(.+)$", line, re.IGNORECASE)
        if fmt_m:
            gc.date_format = fmt_m.group(1).strip()
            continue

        if re.match(
            r"^(axisFormat|excludes|includes|todayMarker|tickInterval|weekday)\b",
            line,
            re.IGNORECASE,
        ):
            continue

        sec_m = re.match(r"^section\s+(.+)$", line, re.IGNORECASE)
        if sec_m:
            current_section = sec_m.group(1).strip()
            continue

        # Task line: "Task name :[tags,] [id,] [start,] duration"
        task_m = re.match(r"^(.+?)\s*:\s*(.+)$", line)
        if task_m:
            name = task_m.group(1).strip()
            params = [p.strip() for p in task_m.group(2).split(",")]
            task = GanttTask(name=name, section=current_section)
            for p in params:
                if p.lower() in _GANTT_TAGS:
                    task.tags.add(p.lower())
                    continue
                if p.startswith("after "):
                    task.start = p
                elif re.match(r"^\w+$", p) and not task.task_id and not re.match(r"^\d", p):
                    task.task_id = p
                elif not task.start:
                    task.start = p
                else:
                    task.duration = p
            gc.tasks.append(task)

    return gc


# ---------------------------------------------------------------------------
# Mind map parser
# ---------------------------------------------------------------------------


def parse_mindmap(source: str) -> MindNode:
    """Parse a Mermaid mindmap definition into a tree."""
    root = MindNode(label="Root")
    stack: list[tuple[int, MindNode]] = []  # (indent_level, node)

    for raw_line in source.strip().splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("%%"):
            continue
        if re.match(r"^\s*mindmap\b", raw_line, re.IGNORECASE):
            continue
        stripped = raw_line.lstrip()
        if stripped.startswith("::icon(") or stripped.startswith(":::"):
            continue
        indent = len(raw_line) - len(stripped)

        label = re.sub(r"\s*:::.*$", "", stripped.strip())
        # Shape decorations around the label: id((x)), (x), [x], {{x}}, ))x((, )x(
        shape_m = re.match(
            r"^[\w-]*\s*(\(\((.+)\)\)|\(\[(.+)\]\)|\{\{(.+)\}\}|\)\)(.+)\(\(|\)(.+)\(|\((.+)\)|\[(.+)\])$",
            label,
        )
        if shape_m:
            label = next(g for g in shape_m.groups()[1:] if g is not None)
        label = label.strip().strip('"')

        node = MindNode(label=label)
        if not stack:
            root = node
            stack.append((indent, node))
        else:
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack:
                stack[-1][1].children.append(node)
            else:
                root.children.append(node)
            stack.append((indent, node))

    return root


# ---------------------------------------------------------------------------
# ER diagram parser
# ---------------------------------------------------------------------------


def _er_marker_defs(color: str, surface: str = "#ffffff") -> str:
    """Crow's-foot ends (one, zero-or-one, one-or-many, zero-or-many) for both line ends."""
    shapes = {
        "one": "M 13,2 V 12 M 9,2 V 12",
        "zero_one": "M 13,2 V 12",
        "one_many": "M 19,1 L 11,7 L 19,13 M 11,7 H 19 M 8,2 V 12",
        "zero_many": "M 19,1 L 11,7 L 19,13 M 11,7 H 19",
    }
    circles = {"zero_one": 6.0, "zero_many": 6.0}
    out = ["<defs>"]
    for kind, d in shapes.items():
        circle = (
            f'<circle cx="{circles[kind]:g}" cy="7" r="3.2" fill="{surface}" stroke="{color}" '
            f'stroke-width="1.25"/>'
            if kind in circles
            else ""
        )
        body = f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.25"/>{circle}'
        common = (
            'markerUnits="userSpaceOnUse" markerWidth="20" markerHeight="14" refY="7" orient="auto"'
        )
        out.append(f'<marker id="er-{kind}" refX="19" {common}>{body}</marker>')
        out.append(
            f'<marker id="er-{kind}-s" refX="1" {common}>'
            f'<g transform="matrix(-1 0 0 1 20 0)">{body}</g></marker>'
        )
    out.append("</defs>")
    return "\n".join(out)


def parse_er(source: str) -> ERDiagram:
    """Parse a Mermaid ER diagram (entities, typed attributes with keys, relationships)."""
    erd = ERDiagram()
    current_entity: str | None = None
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^erDiagram\b", line, re.IGNORECASE):
            continue

        if line == "}":
            current_entity = None
            continue

        if current_entity is not None:
            attr_m = re.match(
                r"^([\w()\[\],.-]+)\s+(\w+)(?:\s+((?:PK|FK|UK)(?:\s*,\s*(?:PK|FK|UK))*))?", line
            )
            if attr_m:
                ent = erd.entities[current_entity]
                ent.attributes.append(f"{attr_m.group(1)} {attr_m.group(2)}")
                ent.keys.append(re.sub(r"\s+", "", attr_m.group(3) or ""))
            continue

        rel_m = re.match(
            r'^(\S+?)\s*([|}o][|o])(--|\.\.)([|o][|{o])\s*(\S+?)\s*:\s*"?(.*?)"?\s*$', line
        )
        if rel_m:
            a, left, link, right, b, label = rel_m.groups()
            erd.relations.append(
                ERRelation(
                    entity_a=a,
                    entity_b=b,
                    card_a=_ER_LEFT.get(left, "one"),
                    card_b=_ER_RIGHT.get(right, "one"),
                    label=label.strip(),
                    style="dotted" if link == ".." else "solid",
                )
            )
            for name in (a, b):
                if name not in erd.entities:
                    erd.entities[name] = EREntity(name=name)
            continue

        ent_m = re.match(r"^([\w-]+)\s*\{\s*$", line)
        if ent_m:
            name = ent_m.group(1)
            if name not in erd.entities:
                erd.entities[name] = EREntity(name=name)
            current_entity = name
            continue
        bare_m = re.match(r"^([\w-]+)$", line)
        if bare_m and bare_m.group(1) not in erd.entities:
            erd.entities[bare_m.group(1)] = EREntity(name=bare_m.group(1))

    return erd


# ---------------------------------------------------------------------------
# State diagram parser
# ---------------------------------------------------------------------------


def parse_state(source: str) -> StateDiagram:
    """Parse a Mermaid state diagram."""
    sd = StateDiagram()
    seen: set[str] = set()

    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^stateDiagram", line, re.IGNORECASE):
            continue
        if line.startswith("direction "):
            sd.direction = line.split(None, 1)[1].strip().upper()
            continue

        # Transition: State1 --> State2 : label
        trans_m = re.match(r"^(\S+)\s*-->\s*(\S+)(?:\s*:\s*(.+))?$", line)
        if trans_m:
            src, dst, label = trans_m.group(1), trans_m.group(2), trans_m.group(3) or ""
            sd.transitions.append(StateTransition(src=src, dst=dst, label=label.strip()))
            for s in (src, dst):
                if s not in seen:
                    sd.states.append(s)
                    seen.add(s)

    return sd


# ---------------------------------------------------------------------------
# Layout engine
# ---------------------------------------------------------------------------


def _compute_levels(fc: Flowchart) -> dict[str, int]:
    """Assign each node a level (column for LR, row for TD).

    Back edges (those closing a cycle) are ignored so loops don't push a node
    past its own descendants; every other node sits one level after its deepest
    predecessor.
    """
    children: dict[str, list[str]] = defaultdict(list)
    has_parent: set[str] = set()
    for e in fc.edges:
        if e.dst not in children[e.src]:
            children[e.src].append(e.dst)
        has_parent.add(e.dst)

    roots = [nid for nid in fc.nodes if nid not in has_parent]
    if not roots and fc.nodes:
        roots = [next(iter(fc.nodes))]

    visiting: set[str] = set()
    done: set[str] = set()
    back: set[tuple[str, str]] = set()
    postorder: list[str] = []

    def _dfs(nid: str) -> None:
        visiting.add(nid)
        for child in children.get(nid, []):
            if child in visiting:
                back.add((nid, child))
            elif child not in done:
                _dfs(child)
        visiting.discard(nid)
        done.add(nid)
        postorder.append(nid)

    for nid in [*roots, *fc.nodes]:
        if nid not in done:
            _dfs(nid)

    levels: dict[str, int] = {nid: 0 for nid in fc.nodes}
    for nid in reversed(postorder):
        for child in children.get(nid, []):
            if (nid, child) not in back:
                levels[child] = max(levels[child], levels[nid] + 1)
    return levels


def _crossings_between(
    upper: list[str], lower: list[str], children_map: dict[str, list[str]]
) -> int:
    """Count edge crossings between two adjacent levels for the given orderings."""
    pos = {n: i for i, n in enumerate(lower)}
    edges = [(i, pos[c]) for i, u in enumerate(upper) for c in children_map.get(u, []) if c in pos]
    return sum(
        1
        for a in range(len(edges))
        for b in range(a + 1, len(edges))
        if (edges[a][0] - edges[b][0]) * (edges[a][1] - edges[b][1]) < 0
    )


def _total_crossings(order: dict[int, list[str]], children_map: dict[str, list[str]]) -> int:
    lv = sorted(order)
    return sum(_crossings_between(order[a], order[b], children_map) for a, b in zip(lv, lv[1:]))


def _minimize_crossings(
    level_groups: dict[int, list[str]],
    children_map: dict[str, list[str]],
    parents_map: dict[str, list[str]],
) -> dict[int, list[str]]:
    """Order the nodes within each level to reduce edge crossings.

    Alternating barycentre sweeps (down by parents, up by children) followed by
    adjacent-swap refinement; the best ordering seen is kept.
    """
    order = {lvl: list(nids) for lvl, nids in level_groups.items()}
    levels = sorted(order)
    best = {lvl: list(nids) for lvl, nids in order.items()}
    best_count = _total_crossings(order, children_map)

    def local(lvl: int) -> int:
        total = 0
        if lvl - 1 in order:
            total += _crossings_between(order[lvl - 1], order[lvl], children_map)
        if lvl + 1 in order:
            total += _crossings_between(order[lvl], order[lvl + 1], children_map)
        return total

    for sweep in range(24):
        if best_count == 0:
            break
        down = sweep % 2 == 0
        step = 1 if down else -1
        for lvl in levels[1:] if down else reversed(levels[:-1]):
            ref = {n: i for i, n in enumerate(order[lvl - step])}
            nbrs = parents_map if down else children_map
            here = {n: i for i, n in enumerate(order[lvl])}

            def _bary(
                n: str, ref: dict[str, int] = ref, here: dict[str, int] = here, nbrs=nbrs
            ) -> float:
                ks = [ref[x] for x in nbrs.get(n, []) if x in ref]
                return sum(ks) / len(ks) if ks else float(here[n])

            order[lvl].sort(key=_bary)

        improved = True
        while improved:
            improved = False
            for lvl in levels:
                row = order[lvl]
                for i in range(len(row) - 1):
                    before = local(lvl)
                    row[i], row[i + 1] = row[i + 1], row[i]
                    if local(lvl) < before:
                        improved = True
                    else:
                        row[i], row[i + 1] = row[i + 1], row[i]

        count = _total_crossings(order, children_map)
        if count < best_count:
            best = {lvl: list(nids) for lvl, nids in order.items()}
            best_count = count
    return best


def _group_contiguous(fc: Flowchart, order: dict[int, list[str]]) -> dict[int, list[str]]:
    """Keep each top-level subgraph's members side by side within a rank.

    Groups stay where their first member landed; a lane carrying a long edge
    joins the group of the node it leads to, so it runs inside that frame.
    """
    child_ids = {c for sg in fc.subgraphs for c in sg.children}
    group: dict[str, int] = {}
    for gi, sg in enumerate(sg for sg in fc.subgraphs if sg.id not in child_ids):
        for nid in _subgraph_members(fc, sg):
            group.setdefault(nid, gi)
    for nid in fc.nodes:
        m = re.match(r"__lane(\d+)_", nid)
        if m:
            e = fc.edges[int(m.group(1))]
            g = group.get(e.dst, group.get(e.src))
            if g is not None:
                group[nid] = g
    out: dict[int, list[str]] = {}
    for lvl, row in order.items():
        first: dict[object, int] = {}
        for i, n in enumerate(row):
            first.setdefault(group.get(n, ("solo", n)), i)
        out[lvl] = sorted(row, key=lambda n: first[group.get(n, ("solo", n))])
    return out


def _layout_layered(
    fc: Flowchart,
    levels: dict[str, int],
    level_groups: dict[int, list[str]],
    children_map: dict[str, list[str]],
    major_pos: dict[int, float],
    horizontal: bool,
    padding: float,
    gap: float,
    major_size: dict[int, float] | None = None,
) -> int:
    """Place nodes level by level, minimising crossings and overlaps.

    ``major_pos`` is the position of each level along the flow axis. Within a
    level nodes are ordered by their parents' positions, siblings sharing the
    same parents are packed as a cluster centred under them, and a top-down,
    bottom-up, top-down sweep settles parents and children against each other.
    Lane (``dummy``) nodes carrying long edges are packed tighter.
    """

    def minor(n: str) -> float:
        return fc.nodes[n].h if horizontal else fc.nodes[n].w

    def spacing(a: str, b: str) -> float:
        return gap * 0.5 if "dummy" in (fc.nodes[a].shape, fc.nodes[b].shape) else gap

    parents_map: dict[str, list[str]] = defaultdict(list)
    for src, kids in children_map.items():
        for k in kids:
            if levels.get(src, 0) < levels.get(k, 0):
                parents_map[k].append(src)

    order = _minimize_crossings(level_groups, children_map, parents_map)
    if fc.subgraphs:
        order = _group_contiguous(fc, order)
    crossings = _total_crossings(order, children_map)

    center: dict[str, float] = {}

    def _pack(clusters: list[tuple[list[str], float | None]]) -> None:
        right: float | None = None
        prev_id = ""
        for members, desired in clusters:
            width = sum(minor(n) for n in members) + sum(
                spacing(a, b) for a, b in zip(members, members[1:])
            )
            left = padding if right is None else right + spacing(prev_id, members[0])
            if desired is not None:
                left = max(left, desired - width / 2)
            for i, n in enumerate(members):
                center[n] = left + minor(n) / 2
                left += minor(n) + (spacing(n, members[i + 1]) if i + 1 < len(members) else 0)
            right = left
            prev_id = members[-1]

    def _top_down() -> None:
        for lvl in sorted(order):
            clusters: list[tuple[list[str], float | None]] = []
            prev_key: tuple[str, ...] | None = None
            for n in order[lvl]:
                ps = [p for p in parents_map.get(n, []) if p in center]
                key = tuple(ps)
                desired = sum(center[p] for p in ps) / len(ps) if ps else None
                if ps and key == prev_key:
                    clusters[-1][0].append(n)
                else:
                    clusters.append(([n], desired if ps else center.get(n)))
                prev_key = key if ps else None
            _pack(clusters)

    def _bottom_up() -> None:
        for lvl in sorted(order, reverse=True):
            clusters = []
            for n in order[lvl]:
                ks = [k for k in children_map.get(n, []) if levels.get(k, 0) > lvl and k in center]
                desired = sum(center[k] for k in ks) / len(ks) if ks else center.get(n)
                clusters.append(([n], desired))
            _pack(clusters)

    _top_down()
    _bottom_up()
    _top_down()

    shift = min(center[n] - minor(n) / 2 for n in center) - padding
    for n, c in center.items():
        node = fc.nodes[n]
        pos = c - minor(n) / 2 - shift
        lvl = levels[n]
        # Centre each node within its column (LR) or row (TD)
        extent = (major_size or {}).get(lvl, node.w if horizontal else node.h)
        if horizontal:
            node.x, node.y = major_pos[lvl] + (extent - node.w) / 2, pos
        else:
            node.x, node.y = pos, major_pos[lvl] + (extent - node.h) / 2
    return crossings


def layout(fc: Flowchart, theme: dict[str, str] | None = None) -> None:
    """Position all nodes in the flowchart."""
    if not fc.nodes:
        return

    font_size = 12

    # Compute text-based node sizes
    for node in fc.nodes.values():
        if node.shape in ("start", "end"):
            node.w = node.h = 20
            continue
        if node.shape == "fixed":  # caller-sized (ER entity cards)
            continue
        lines = re.split(r"<br\s*/?>|\n", node.label)
        num_lines = len(lines)

        node.w = max(max(_text_w(line, font_size, 500) for line in lines) + 32, 96)
        node.h = max(num_lines * font_size * 1.3 + 22, 40)

        if node.shape == "diamond":
            node.w = max(node.w * 1.4, 100)
            node.h = max(node.h * 1.4, 60)
        elif node.shape == "circle":
            diameter = max(node.w, node.h) * 1.1
            node.w = diameter
            node.h = diameter
        elif node.shape == "hexagon":
            node.w = max(node.w + 24, 110)
        elif node.shape in (
            "parallelogram",
            "parallelogram_alt",
            "trapezoid",
            "trapezoid_alt",
            "flag",
        ):
            node.w += 2 * _SLANT_INSET
        elif node.shape == "cylinder":
            node.h = max(node.h + 16, 56)
        elif node.shape == "document":
            node.h += 8
        elif node.shape == "ellipse":
            node.w, node.h = node.w * 1.22, node.h + 10
        elif node.shape == "actor":
            node.w = max(max(_text_w(line, font_size, 500) for line in lines) + 12, 56)
            node.h = 50 + num_lines * font_size * 1.3

    # Assign levels
    levels = _compute_levels(fc)

    # Edges spanning several levels (and back edges) get a chain of invisible
    # lane nodes so they reserve space and route around the real nodes.
    chain_pairs: list[tuple[str, str]] = []
    lanes: dict[int, list[str]] = {}
    for i, e in enumerate(fc.edges):
        if e.src not in fc.nodes or e.dst not in fc.nodes:
            continue
        ls, ld = levels[e.src], levels[e.dst]
        lo, hi = (e.src, e.dst) if ls <= ld else (e.dst, e.src)
        prev = lo
        ids: list[str] = []
        for lvl in range(min(ls, ld) + 1, max(ls, ld)):
            did = f"__lane{i}_{lvl}"
            fc.nodes[did] = Node(did, "", "dummy", w=10, h=10)
            levels[did] = lvl
            chain_pairs.append((prev, did))
            prev = did
            ids.append(did)
        chain_pairs.append((prev, hi))
        if ids:
            lanes[i] = ids if ls <= ld else ids[::-1]

    # Group nodes by level
    level_groups: dict[int, list[str]] = defaultdict(list)
    for nid, lvl in levels.items():
        level_groups[lvl].append(nid)

    children_map: dict[str, list[str]] = defaultdict(list)
    for a_id, b_id in chain_pairs:
        if b_id not in children_map[a_id]:
            children_map[a_id].append(b_id)

    is_horizontal = fc.direction in ("LR", "RL")
    gap_major: float = 60
    gap_minor = 30
    padding = 30

    major_pos: dict[int, float] = {}
    cursor: float = padding
    if is_horizontal:
        # Each gap is as wide as the labels drawn in it need: a label sits on its
        # edge's last segment, i.e. in the gap just before the target column
        # (or just after it for an edge running backwards).
        gap_need: dict[int, float] = defaultdict(float)
        for e in fc.edges:
            if e.label and e.src in levels and e.dst in levels:
                ls, ld = levels[e.src], levels[e.dst]
                gap = ld - 1 if ld > ls else ld
                gap_need[gap] = max(
                    gap_need[gap], _text_w(e.label, _FS_SM) + 28 + 2 * fc.end_marker_space
                )

        # Normalize widths in each column
        for lvl, nids in level_groups.items():
            rect_nodes = [
                fc.nodes[n] for n in nids if fc.nodes[n].shape in ("rect", "rounded", "subroutine")
            ]
            if len(rect_nodes) > 1:
                max_w = max(n.w for n in rect_nodes)
                for n in rect_nodes:
                    n.w = max_w

        for lvl in sorted(level_groups):
            major_pos[lvl] = cursor
            cursor += max(fc.nodes[n].w for n in level_groups[lvl])
            cursor += max(48.0 + 2 * fc.end_marker_space, gap_need.get(lvl, 0.0))
    else:
        for lvl in sorted(level_groups):
            major_pos[lvl] = cursor
            cursor += max(fc.nodes[n].h for n in level_groups[lvl]) + gap_major

    baseline = _total_crossings(level_groups, children_map)
    major_size = {
        lvl: max(fc.nodes[n].w if is_horizontal else fc.nodes[n].h for n in nids)
        for lvl, nids in level_groups.items()
    }
    fc.crossings = _layout_layered(
        fc,
        levels,
        level_groups,
        children_map,
        major_pos,
        is_horizontal,
        padding,
        gap_minor,
        major_size,
    )
    fc.crossings_unordered = baseline

    # Hand the lane positions to the edge router and drop the helper nodes
    # Each lane crosses its column (row) straight, entering and leaving at the
    # column edges, so every bend of a long edge happens in a gap between ranks.
    fc.waypoints = {}
    for i, ids in lanes.items():
        e = fc.edges[i]
        forward = levels[e.src] <= levels[e.dst]
        pts: list[tuple[float, float]] = []
        for nid in ids:
            lane = fc.nodes[nid]
            lvl = levels[nid]
            a, b = major_pos[lvl], major_pos[lvl] + major_size[lvl]
            if not forward:
                a, b = b, a
            centre = lane.y + lane.h / 2 if is_horizontal else lane.x + lane.w / 2
            pts += [(a, centre), (b, centre)] if is_horizontal else [(centre, a), (centre, b)]
        fc.waypoints[i] = pts
    for nid in [n for n, node in fc.nodes.items() if node.shape == "dummy"]:
        del fc.nodes[nid]

    _frame_subgraphs(fc, is_horizontal)
    _separate_frames(fc, is_horizontal)


def _frame_subgraphs(fc: Flowchart, horizontal: bool = True) -> None:
    """Size every subgraph frame around its members."""
    # Inner frames first so an outer frame can wrap its children
    by_id = {sg.id: sg for sg in fc.subgraphs}
    sg_pad = 12
    for sg in reversed(fc.subgraphs):
        boxes = [
            (member.x, member.y, member.x + member.w, member.y + member.h)
            for nid in sg.node_ids
            if (member := fc.nodes.get(nid)) is not None
        ]
        boxes += [
            (c.x, c.y, c.x + c.w, c.y + c.h)
            for cid in sg.children
            if (c := by_id.get(cid)) is not None and c.w > 0
        ]
        if not boxes:
            continue
        # A long edge into this group runs inside the frame on the ranks it shares
        members = set(sg.node_ids)
        lo_x, hi_x = min(b[0] for b in boxes), max(b[2] for b in boxes)
        lo_y, hi_y = min(b[1] for b in boxes), max(b[3] for b in boxes)
        for i, pts in fc.waypoints.items():
            if fc.edges[i].dst in members and fc.edges[i].src not in members:
                for px, py in pts:
                    if (lo_x <= px <= hi_x) if horizontal else (lo_y <= py <= hi_y):
                        boxes.append((px - 4, py - 4, px + 4, py + 4))
        x0 = min(b[0] for b in boxes) - sg_pad
        y0 = min(b[1] for b in boxes) - sg_pad - 18  # room for the title
        sg.x, sg.y = x0, y0
        sg.w = max(b[2] for b in boxes) + sg_pad - x0
        sg.h = max(b[3] for b in boxes) + sg_pad - y0


def _separate_frames(fc: Flowchart, is_horizontal: bool) -> None:
    """Push apart sibling top-level frames whose panels overlap.

    Members of different groups can share a rank, so their frames may
    interleave; everything past the overlap moves along the cross axis.
    """
    child_ids = {c for sg in fc.subgraphs for c in sg.children}
    for _ in range(8):
        tops = [sg for sg in fc.subgraphs if sg.id not in child_ids and sg.w > 0]
        clash = None
        for a in tops:
            for b in tops:
                if a is b:
                    continue
                if a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h:
                    a0 = a.y if is_horizontal else a.x
                    b0 = b.y if is_horizontal else b.x
                    if a0 <= b0:
                        clash = (a, b)
                        break
            if clash:
                break
        if clash is None:
            return
        a, b = clash
        if is_horizontal:
            shift, start = a.y + a.h + 10 - b.y, b.y
        else:
            shift, start = a.x + a.w + 10 - b.x, b.x
        keep = set(_subgraph_members(fc, a))
        for nid, node in fc.nodes.items():
            if nid in keep:
                continue
            if is_horizontal and node.y + node.h > start:
                node.y += shift
            elif not is_horizontal and node.x + node.w > start:
                node.x += shift
        for k, pts in fc.waypoints.items():
            if fc.edges[k].dst in keep and fc.edges[k].src not in keep:
                continue  # runs inside frame a, which stays put
            fc.waypoints[k] = [
                (
                    (x, y + shift if y > start else y)
                    if is_horizontal
                    else (x + shift if x > start else x, y)
                )
                for x, y in pts
            ]
        _frame_subgraphs(fc, is_horizontal)


# ---------------------------------------------------------------------------
# SVG renderer — shared helpers
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    """Escape text for SVG/XML."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _color_suffix(color: str | None) -> str:
    return "-" + re.sub(r"\W", "", color) if color else ""


def _make_arrow_defs(t: dict[str, str], prefix: str = "", colors: tuple[str, ...] = ()) -> str:
    """SVG marker definitions: arrow, thick arrow, circle and cross ends (+ start variants).

    Markers use fixed user-space sizes so arrowheads look the same on thin and thick
    lines, and one set is emitted per distinct edge colour.
    """
    muted = t.get("edge", _EDGE)
    out = ["<defs>"]
    for color in (None, *colors):
        c = color or muted
        sfx = _color_suffix(color)
        common = 'markerUnits="userSpaceOnUse" orient="auto"'
        out += [
            f'<marker id="{prefix}arr{sfx}" markerWidth="9" markerHeight="7" refX="8" refY="3.5" {common}>'
            f'<polygon points="0 0.5, 8 3.5, 0 6.5" fill="{c}"/></marker>',
            f'<marker id="{prefix}arr-thick{sfx}" markerWidth="12" markerHeight="9" refX="11" refY="4.5" {common}>'
            f'<polygon points="0 0.5, 11 4.5, 0 8.5" fill="{c}"/></marker>',
            f'<marker id="{prefix}arr-s{sfx}" markerWidth="9" markerHeight="7" refX="1" refY="3.5" {common}>'
            f'<polygon points="9 0.5, 1 3.5, 9 6.5" fill="{c}"/></marker>',
            f'<marker id="{prefix}circle{sfx}" markerWidth="10" markerHeight="10" refX="9" refY="5" {common}>'
            f'<circle cx="5" cy="5" r="3.6" fill="{t["surface"]}" stroke="{c}" stroke-width="1.4"/></marker>',
            f'<marker id="{prefix}circle-s{sfx}" markerWidth="10" markerHeight="10" refX="1" refY="5" {common}>'
            f'<circle cx="5" cy="5" r="3.6" fill="{t["surface"]}" stroke="{c}" stroke-width="1.4"/></marker>',
            f'<marker id="{prefix}cross{sfx}" markerWidth="10" markerHeight="10" refX="9" refY="5" {common}>'
            f'<path d="M2 2 L8 8 M8 2 L2 8" stroke="{c}" stroke-width="1.6" fill="none"/></marker>',
            f'<marker id="{prefix}cross-s{sfx}" markerWidth="10" markerHeight="10" refX="1" refY="5" {common}>'
            f'<path d="M2 2 L8 8 M8 2 L2 8" stroke="{c}" stroke-width="1.6" fill="none"/></marker>',
            f'<marker id="{prefix}triangle{sfx}" markerWidth="15" markerHeight="13" refX="14" refY="6.5" {common}>'
            f'<path d="M 1,1 L 14,6.5 L 1,12 Z" fill="{t["surface"]}" stroke="{c}" stroke-width="1.3" '
            f'stroke-linejoin="round"/></marker>',
        ]
    out.append("</defs>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# SVG renderer — flowchart
# ---------------------------------------------------------------------------


def _flow_extent(fc: Flowchart, pad: float = 10.0) -> tuple[float, float, float, float]:
    """(origin x, origin y, width, height) of everything drawn: nodes, frames, lanes, labels."""
    xs0 = [n.x for n in fc.nodes.values()] + [sg.x for sg in fc.subgraphs if sg.w > 0]
    ys0 = [n.y for n in fc.nodes.values()] + [sg.y for sg in fc.subgraphs if sg.w > 0]
    xs1 = [n.x + n.w for n in fc.nodes.values()] + [sg.x + sg.w for sg in fc.subgraphs if sg.w > 0]
    ys1 = [n.y + n.h for n in fc.nodes.values()] + [sg.y + sg.h for sg in fc.subgraphs if sg.w > 0]
    for pts in fc.waypoints.values():
        xs0 += [px for px, _ in pts]
        xs1 += [px for px, _ in pts]
        ys0 += [py for _, py in pts]
        ys1 += [py for _, py in pts]
    longest_label = max((_text_w(e.label, _FS_SM) for e in fc.edges), default=0.0)
    right_pad = pad + (longest_label / 2 + 8 if fc.direction not in ("LR", "RL") else 0)
    ox, oy = min(xs0) - pad, min(ys0) - pad
    return ox, oy, max(xs1) - ox + right_pad, max(ys1) - oy + pad


def _wrap_label(label: str, max_w: float, weight: int = 500) -> str:
    """Word-wrap a node label (keeping explicit line breaks) to ``max_w`` px."""
    out: list[str] = []
    for line in re.split(r"<br\s*/?>|\n", label):
        words, cur = line.split(), ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if cur and _text_w(trial, _FS, weight) > max_w:
                out.append(cur)
                cur = word
            else:
                cur = trial
        out.append(cur)
    return "\n".join(out)


def _fit_to_column(fc: Flowchart, t: dict[str, str], wrap: bool = True) -> None:
    """Keep a laid-out diagram within the text column instead of shrinking its text.

    Too wide: wrap long node labels; still too wide, try the other flow direction
    (left-to-right <-> top-down) and keep it if it fits or is clearly narrower.
    Opt out per diagram with ``%%{init: {"flowchart": {"autoFit": false}}}%%``.
    """
    if t.get("auto_fit") == "0" or not fc.nodes:
        return
    column = float(t.get("column_px") or 640)
    width = _flow_extent(fc)[2]
    if width <= column:
        return
    if wrap:
        for node in fc.nodes.values():
            if node.shape not in ("start", "end", "fixed", "dummy"):
                node.label = _wrap_label(node.label, 132)
        layout(fc, t)
        width = _flow_extent(fc)[2]
        if width <= column:
            return
    original = fc.direction
    fc.direction = "TD" if original in ("LR", "RL") else "LR"
    layout(fc, t)
    flipped = _flow_extent(fc)[2]
    if flipped <= column or flipped < width * 0.8:
        return
    fc.direction = original
    layout(fc, t)


def render_svg(fc: Flowchart, theme: dict[str, str] | None = None) -> str:
    """Render a laid-out Flowchart to an SVG string."""
    t = _tokens(theme)
    layout(fc, t)
    _fit_to_column(fc, t)

    if not fc.nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    parts: list[str] = []

    ox, oy, width, height = _flow_extent(fc)

    edge_colors = tuple(sorted({e.css["stroke"] for e in fc.edges if "stroke" in e.css}))
    parts.append(_make_arrow_defs(t, colors=edge_colors))
    parts.append(f'<g transform="translate({-ox:g},{-oy:g})">')

    # Draw subgraphs (behind everything)
    for sg in fc.subgraphs:
        parts.append(_render_subgraph(sg, t))

    # Draw edges (behind nodes)
    ports = _assign_ports(fc)
    for edge_idx, edge in enumerate(fc.edges):
        src = fc.nodes.get(edge.src)
        dst = fc.nodes.get(edge.dst)
        if not src or not dst:
            continue
        lane = 0.0
        if any(o.src == edge.dst and o.dst == edge.src for o in fc.edges):
            lane = -7.0 if edge.src < edge.dst else 7.0
        parts.append(
            _render_edge(
                src,
                dst,
                edge.label,
                fc.direction,
                t,
                edge.style,
                lane,
                fc.waypoints.get(edge_idx),
                ports.get((edge_idx, "out")),
                ports.get((edge_idx, "in")),
                edge,
            )
        )

    # Draw nodes
    for node in fc.nodes.values():
        parts.append(_render_node(node, t))
    parts.append("</g>")

    return _svg_root(width, height, parts, t["font"])


def _render_subgraph(sg: Subgraph, t: dict[str, str]) -> str:
    """Render a subgraph frame: a softly tinted panel with its title."""
    if sg.w <= 0 or sg.h <= 0:
        return ""
    font = t.get("font", DEFAULT_THEME["font"])
    fill = t["subgraph_fill"]
    stroke = t["subgraph_stroke"]
    label_color = t["subgraph_label"]

    return "\n".join(
        [
            f'<rect x="{sg.x}" y="{sg.y}" width="{sg.w}" height="{sg.h}" '
            f'rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1"/>',
            f'<text x="{sg.x + 10}" y="{sg.y + 15}" '
            f'font-family="{font}" font-size="{_FS_SM:g}" font-weight="600" '
            f'fill="{label_color}">{_escape(sg.label)}</text>',
        ]
    )


_SHADOW_SHAPES = ("rect", "rounded", "stadium", "subroutine")
_SLANT_INSET = 14.0


def _node_polygon(node: Node) -> str | None:
    """Vertex list for polygon-shaped nodes (None for other shapes)."""
    x, y, w, h = node.x, node.y, node.w, node.h
    cy = y + h / 2
    i = _SLANT_INSET
    pts: list[tuple[float, float]] | None = {
        "diamond": [(x + w / 2, y), (x + w, cy), (x + w / 2, y + h), (x, cy)],
        "hexagon": [
            (x + 12, y),
            (x + w - 12, y),
            (x + w, cy),
            (x + w - 12, y + h),
            (x + 12, y + h),
            (x, cy),
        ],
        "parallelogram": [(x + i, y), (x + w, y), (x + w - i, y + h), (x, y + h)],
        "parallelogram_alt": [(x, y), (x + w - i, y), (x + w, y + h), (x + i, y + h)],
        "trapezoid": [(x + i, y), (x + w - i, y), (x + w, y + h), (x, y + h)],
        "trapezoid_alt": [(x, y), (x + w, y), (x + w - i, y + h), (x + i, y + h)],
        "flag": [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x + i, cy)],
    }.get(node.shape)
    return " ".join(f"{px},{py}" for px, py in pts) if pts else None


def _apply_node_css(parts: list[str], css: dict[str, str]) -> list[str]:
    """Apply ``style`` / ``classDef`` overrides to a node's SVG elements."""
    out: list[str] = []
    for part in parts:
        if "data-shadow" in part:  # the soft shadow keeps its own look
            out.append(part)
            continue
        if part.startswith("<text"):
            if "color" in css:
                part = re.sub(r'fill="[^"]*"', f'fill="{css["color"]}"', part, count=1)
        else:
            for prop in ("fill", "stroke", "stroke-width", "stroke-dasharray"):
                if prop not in css or (prop == "stroke" and 'stroke="none"' in part):
                    continue
                if re.search(rf'(?<![\w-]){prop}="', part):
                    part = re.sub(
                        rf'(?<![\w-]){prop}="[^"]*"', f'{prop}="{css[prop]}"', part, count=1
                    )
                else:
                    part = re.sub(r"/>$", f' {prop}="{css[prop]}"/>', part)
        out.append(part)
    return out


def _render_node(node: Node, t: dict[str, str]) -> str:
    """Render a single node to SVG elements."""
    font = t.get("font", DEFAULT_THEME["font"])
    cx = node.x + node.w / 2
    cy = node.y + node.h / 2
    parts: list[str] = []
    sw = 1.25

    if node.shape in ("start", "end"):
        primary = t["term_fill"]
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{node.w / 2}" fill="{primary}"/>')
        if node.shape == "end":
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{node.w / 2 - 3}" fill="{t["surface"]}"/>'
            )
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{node.w / 2 - 5}" fill="{primary}"/>')
        return "\n".join(parts)

    terminal = node.shape in ("stadium", "circle")
    text_color = t["term_text"] if terminal else t["ink"]
    if node.shape == "diamond":
        fill, stroke = t["diamond_fill"], t["diamond_stroke"]
    elif terminal:
        fill, stroke = t["term_fill"], t["term_fill"]
    else:
        fill, stroke = t["node_fill"], t["node_stroke"]
    style = f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"'

    corner = {"rect": 6, "rounded": 12, "subroutine": 4, "stadium": node.h / 2}.get(node.shape)
    if node.shape in _SHADOW_SHAPES:
        parts.append(
            f'<rect x="{node.x}" y="{node.y + 1.5}" width="{node.w}" height="{node.h}" '
            f'rx="{corner}" fill="#0b1f33" fill-opacity="{t["shadow"]}" data-shadow="1"/>'
        )

    poly = _node_polygon(node)
    if poly:
        parts.append(f'<polygon points="{poly}" {style} stroke-linejoin="round"/>')
    elif node.shape == "circle":
        r = min(node.w, node.h) / 2
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" {style}/>')
    elif node.shape == "ellipse":
        parts.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{node.w / 2}" ry="{node.h / 2}" {style}/>')
    elif node.shape == "document":
        x0, y0, x1, y1 = node.x, node.y, node.x + node.w, node.y + node.h - 6
        parts.append(
            f'<path d="M {x0:g},{y0 + 5:g} Q {x0:g},{y0:g} {x0 + 5:g},{y0:g} H {x1 - 5:g} '
            f"Q {x1:g},{y0:g} {x1:g},{y0 + 5:g} V {y1:g} "
            f"C {x1 - node.w / 4:g},{y1 - 8:g} {x0 + node.w * 0.6:g},{y1 + 12:g} {x0 + node.w / 2:g},{y1:g} "
            f'C {x0 + node.w * 0.35:g},{y1 - 10:g} {x0 + node.w / 6:g},{y1 + 2:g} {x0:g},{y1:g} Z" {style}/>'
        )
        cy -= 3
    elif node.shape == "actor":
        hx, hy = cx, node.y + 8
        ink2 = t["ink2"]
        parts.append(
            f'<g fill="none" stroke="{ink2}" stroke-width="1.5" stroke-linecap="round">'
            f'<circle cx="{hx:g}" cy="{hy:g}" r="7" fill="{t["surface"]}"/>'
            f'<path d="M {hx:g},{hy + 7:g} V {hy + 24:g} M {hx - 12:g},{hy + 13:g} H {hx + 12:g} '
            f'M {hx:g},{hy + 24:g} L {hx - 9:g},{hy + 36:g} M {hx:g},{hy + 24:g} L {hx + 9:g},{hy + 36:g}"/>'
            f"</g>"
        )
        text_color = t["ink"]
        cy = node.y + 50 + (node.h - 50) / 2 - 2
    elif node.shape == "cylinder":
        ry = 8  # ellipse cap height
        body_top = node.y + ry
        body_h = node.h - 2 * ry
        parts.append(
            f'<rect x="{node.x}" y="{body_top}" width="{node.w}" height="{body_h}" '
            f'fill="{fill}" stroke="none"/>'
        )
        for lx in (node.x, node.x + node.w):
            parts.append(
                f'<line x1="{lx}" y1="{body_top}" x2="{lx}" y2="{body_top + body_h}" '
                f'stroke="{stroke}" stroke-width="{sw}"/>'
            )
        for ey in (body_top, body_top + body_h):
            parts.append(f'<ellipse cx="{cx}" cy="{ey}" rx="{node.w / 2}" ry="{ry}" {style}/>')
    else:  # rect / rounded / stadium / subroutine
        parts.append(
            f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" '
            f'rx="{corner if corner is not None else 6}" {style}/>'
        )
        if node.shape == "subroutine":
            for lx in (node.x + 8, node.x + node.w - 8):
                parts.append(
                    f'<line x1="{lx}" y1="{node.y}" x2="{lx}" y2="{node.y + node.h}" '
                    f'stroke="{stroke}" stroke-width="1"/>'
                )

    # Label (support multi-line via \n or <br>)
    label = re.sub(r"<br\s*/?>", "\n", node.label)
    lines = label.split("\n")
    line_height = _FS * 1.3
    start_y = cy - (len(lines) - 1) * line_height / 2

    for i, line_text in enumerate(lines):
        text_y = start_y + i * line_height + _FS * 0.35
        parts.append(
            f'<text x="{cx}" y="{text_y:g}" text-anchor="middle" '
            f'font-family="{font}" font-size="{_FS:g}" font-weight="500" '
            f'fill="{text_color}">{_escape(line_text.strip())}</text>'
        )

    if node.css:
        parts = _apply_node_css(parts, node.css)
    return "\n".join(parts)


_PORT_SHAPES = ("rect", "rounded", "stadium", "subroutine", "fixed")
_PORT_STEP = 5.0  # spacing between staggered edge turns


@dataclass
class _Port:
    """Where an edge meets a node side, and how far out its turn is staggered."""

    offset: float = 0.0  # shift along the node side
    away: float = 0.0  # stagger of the turn, measured away from the node


def _assign_ports(fc: Flowchart) -> dict[tuple[int, str], _Port]:
    """Spread the edges meeting each node side across it, ordered by where they go.

    Edges are sorted by the position of their far end so fanned-out lines don't
    cross their neighbours, and the one reaching furthest turns closest to the
    node, so branches nest instead of overlapping on a shared trunk.
    """
    horizontal = fc.direction in ("LR", "RL")

    def major(n: Node) -> float:
        return n.x + n.w / 2 if horizontal else n.y + n.h / 2

    def minor(pt: tuple[float, float]) -> float:
        return pt[1] if horizontal else pt[0]

    groups: dict[tuple[str, str], list[tuple[int, str, float]]] = defaultdict(list)
    for i, e in enumerate(fc.edges):
        src, dst = fc.nodes.get(e.src), fc.nodes.get(e.dst)
        if not src or not dst or abs(major(src) - major(dst)) < 1:
            continue
        via = fc.waypoints.get(i)
        src_c = (src.x + src.w / 2, src.y + src.h / 2)
        dst_c = (dst.x + dst.w / 2, dst.y + dst.h / 2)
        fwd = major(src) < major(dst)
        out_far = minor(via[0]) if via else minor(dst_c)
        in_far = minor(via[-1]) if via else minor(src_c)
        groups[(e.src, "a" if fwd else "b")].append((i, "out", out_far))
        groups[(e.dst, "b" if fwd else "a")].append((i, "in", in_far))

    ports: dict[tuple[int, str], _Port] = {}
    for (nid, _side), items in groups.items():
        node = fc.nodes[nid]
        centre = minor((node.x + node.w / 2, node.y + node.h / 2))
        extent = node.h if horizontal else node.w
        n = len(items)
        ranked = sorted(items, key=lambda it: -abs(it[2] - centre))
        away = {(it[0], it[1]): k * _PORT_STEP for k, it in enumerate(ranked)}
        for k, (i, role, _far) in enumerate(sorted(items, key=lambda it: (it[2], it[0]))):
            offset = 0.0
            if node.shape in _PORT_SHAPES and n > 1:
                offset = ((k + 1) / (n + 1) - 0.5) * extent * 0.8
            ports[(i, role)] = _Port(offset, away[(i, role)] - (n - 1) * _PORT_STEP / 2)
    return ports


def _round_polyline(pts: list[tuple[float, float]], radius: float = 7.0) -> str:
    """SVG path through ``pts`` with the corners rounded (never past half a segment)."""
    clean = [pts[0]]
    for pt in pts[1:]:
        if abs(pt[0] - clean[-1][0]) > 0.01 or abs(pt[1] - clean[-1][1]) > 0.01:
            clean.append(pt)
    d = f"M {clean[0][0]:g},{clean[0][1]:g}"
    for prev, vert, nxt in zip(clean, clean[1:], clean[2:]):
        d1 = math.hypot(prev[0] - vert[0], prev[1] - vert[1])
        d2 = math.hypot(nxt[0] - vert[0], nxt[1] - vert[1])
        r = min(radius, d1 / 2, d2 / 2)
        a = (vert[0] + (prev[0] - vert[0]) * r / d1, vert[1] + (prev[1] - vert[1]) * r / d1)
        b = (vert[0] + (nxt[0] - vert[0]) * r / d2, vert[1] + (nxt[1] - vert[1]) * r / d2)
        d += f" L {a[0]:g},{a[1]:g} Q {vert[0]:g},{vert[1]:g} {b[0]:g},{b[1]:g}"
    if len(clean) > 1:
        d += f" L {clean[-1][0]:g},{clean[-1][1]:g}"
    return d


def _routed_path(
    src: Node,
    dst: Node,
    via: list[tuple[float, float]],
    horizontal: bool,
    label: str,
    out_port: _Port | None = None,
    in_port: _Port | None = None,
    lane: float = 0.0,
) -> tuple[str, tuple[float, float] | None]:
    """Orthogonal path from ``src`` to ``dst``, through the lane points ``via``.

    Returns the SVG path data and a position for the edge label (``None`` when
    the edge is a straight line, so the caller uses the midpoint). The label sits
    on the final segment so it never lands on another edge's trunk.
    """
    out_port, in_port = out_port or _Port(), in_port or _Port()
    sc = (src.x + src.w / 2, src.y + src.h / 2)
    dc = (dst.x + dst.w / 2, dst.y + dst.h / 2)
    ax = 0 if horizontal else 1  # flow axis index (0 = x, 1 = y)
    mx = 1 - ax  # minor axis index

    def pt(major: float, minor: float) -> tuple[float, float]:
        return (major, minor) if horizontal else (minor, major)

    same_row = abs(sc[ax] - dc[ax]) < 1
    if same_row:  # side to side along the minor axis
        right = sc[mx] <= dc[mx]
        extent_s = src.h if horizontal else src.w
        extent_d = dst.h if horizontal else dst.w
        start = pt(sc[ax], sc[mx] + (extent_s / 2 if right else -extent_s / 2))
        end = pt(dc[ax], dc[mx] + (-extent_d / 2 if right else extent_d / 2))
        return f"M {start[0]},{start[1]} L {end[0]},{end[1]}", None

    fwd = sc[ax] < dc[ax]
    half_s = (src.w if horizontal else src.h) / 2
    half_d = (dst.w if horizontal else dst.h) / 2
    start = pt(sc[ax] + (half_s if fwd else -half_s), sc[mx] + out_port.offset + lane)
    end = pt(dc[ax] + (-half_d if fwd else half_d), dc[mx] + in_port.offset + lane)

    pts = [start, *via, end]
    last = len(pts) - 2
    verts = [pts[0]]
    mid = 0.0
    seg_start = pts[0]
    straight_only = True
    for k, (p, q) in enumerate(zip(pts, pts[1:])):
        seg_start = p
        direction = 1.0 if q[ax] >= p[ax] else -1.0
        mid = (p[ax] + q[ax]) / 2 + lane
        if k == 0:
            mid += direction * out_port.away
        if k == last:
            mid -= direction * in_port.away
        if abs(p[mx] - q[mx]) < 1.5 and len(pts) == 2:
            verts.append(q)
            continue
        straight_only = False
        verts += [pt(mid, p[mx]), pt(mid, q[mx]), q]
    d = _round_polyline(verts)

    if straight_only:
        return d, None
    if horizontal:
        # On the last bend, centred on its vertical run (the label's pill sits over the line)
        label_xy = (mid, (seg_start[1] + end[1]) / 2 + _FS_SM * 0.35)
    else:
        label_xy = (end[0] + len(label) * 2.75 + 8, (mid + end[1]) / 2 + 3)
    return d, label_xy


def _render_edge(
    src: Node,
    dst: Node,
    label: str,
    direction: str,
    t: dict[str, str],
    style: str = "solid",
    lane: float = 0.0,
    via: list[tuple[float, float]] | None = None,
    out_port: _Port | None = None,
    in_port: _Port | None = None,
    edge: Edge | None = None,
) -> str:
    """Render an edge between two nodes."""
    font = t.get("font", DEFAULT_THEME["font"])
    parts: list[str] = []
    css = edge.css if edge else {}
    head = "none" if style == "none" else (edge.head if edge else "arrow")
    tail = edge.tail if edge else "none"

    stroke = css.get("stroke", t["edge"])
    width = css.get("stroke-width", "2.5" if style == "thick" else "1.25")
    stroke_attrs = f'stroke="{stroke}" stroke-width="{width}" fill="none"'
    if style == "dotted":
        stroke_attrs += ' stroke-dasharray="5 3"'
    if "stroke-dasharray" in css:
        stroke_attrs += f' stroke-dasharray="{css["stroke-dasharray"]}"'
    stroke_attrs += ' stroke-linejoin="round"'

    sfx = _color_suffix(css.get("stroke"))

    def marker_id(kind: str, start: bool = False) -> str:
        base = {"arrow": "arr-thick" if style == "thick" and not start else "arr"}.get(kind, kind)
        return f"{base}{'-s' if start else ''}{sfx}"

    marker = f' marker-end="url(#{marker_id(head)})"' if head != "none" else ""
    if tail != "none":
        marker += f' marker-start="url(#{marker_id(tail, True)})"'

    is_h = direction in ("LR", "RL")
    d, label_xy = _routed_path(src, dst, via or [], is_h, label, out_port, in_port, lane)
    parts.append(f'<path d="{d}" {stroke_attrs}{marker}/>')

    # Edge label
    if label:
        lx = (src.x + src.w / 2 + dst.x + dst.w / 2) / 2
        ly = (src.y + src.h / 2 + dst.y + dst.h / 2) / 2
        if label_xy:
            lx, ly = label_xy
        elif is_h:
            ly += lane * 2.2 if lane else _FS_SM * 0.35
        else:
            lx += lane * 2.2 if lane else 10
        # White pill behind the text so it reads over crossing lines
        est_w = _text_w(label, _FS_SM) + 10
        parts.append(
            f'<rect x="{lx - est_w / 2:g}" y="{ly - 11:g}" width="{est_w:g}" height="15" '
            f'rx="3" fill="{t["surface"]}"/>'
        )
        parts.append(
            f'<text x="{lx:g}" y="{ly:g}" text-anchor="middle" '
            f'font-family="{font}" font-size="{_FS_SM:g}" fill="{css.get("color", t["ink2"])}">'
            f"{_escape(label)}</text>"
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# SVG renderer — pie chart
# ---------------------------------------------------------------------------


def _nice_step(span: float, target: int = 5) -> float:
    """A 1/2/2.5/5 x 10^n step giving about ``target`` intervals over ``span``."""
    if span <= 0:
        return 1.0
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if mult * mag >= raw:
            return mult * mag
    return 10 * mag


def _nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    """Round tick values covering ``lo``..``hi`` (always including zero when in range)."""
    if hi <= lo:
        hi = lo + 1
    step = _nice_step(hi - lo, target)
    start = math.floor(lo / step) * step
    end = math.ceil(hi / step) * step
    count = int(round((end - start) / step))
    return [round(start + i * step, 10) for i in range(count + 1)]


def _fmt_num(value: float) -> str:
    """Compact number: 950, 1.2K, 12K, 3.4M; integers stay integers."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= limit:
            scaled = v / limit
            # Round half up (format() rounds half to even: 1.25 would show as 1.2)
            if scaled < 10:
                text = f"{math.floor(scaled * 10 + 0.5) / 10:.1f}".rstrip("0").rstrip(".")
            else:
                text = f"{math.floor(scaled + 0.5):.0f}"
            return f"{sign}{text}{suffix}"
    if float(v).is_integer():
        return f"{sign}{int(v)}"
    return f"{sign}{v:.2f}".rstrip("0").rstrip(".")


def _text_on(fill: str, t: dict[str, str]) -> str:
    """Ink or white, whichever reads on ``fill`` (relative luminance)."""
    h = fill.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return "#ffffff" if lum < 0.45 else "#1f2328"


def _svg_text(
    x: float,
    y: float,
    text: str,
    t: dict[str, str],
    size: float = _FS,
    color: str | None = None,
    weight: int = 400,
    anchor: str = "start",
    extra: str = "",
) -> str:
    return (
        f'<text x="{x:g}" y="{y:g}" text-anchor="{anchor}" font-family="{_escape(t["font"])}" '
        f'font-size="{size:g}" font-weight="{weight}" fill="{color or t["ink"]}"{extra}>'
        f"{_escape(text)}</text>"
    )


def _chart_title(title: str, t: dict[str, str], x: float = 0.0) -> tuple[list[str], float]:
    """Left-aligned chart title; returns (elements, height consumed)."""
    if not title:
        return [], 0.0
    return [_svg_text(x, _FS_TITLE, title, t, _FS_TITLE, weight=600)], _FS_TITLE + 14


def _wrap_words(text: str, max_w: float, size: float = _FS) -> list[str]:
    """Greedy word wrap by estimated width (at most two lines, ellipsis after)."""
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and _text_w(trial, size) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    if len(lines) > 2:
        lines = [lines[0], lines[1] + "…"]
    return lines or [""]


def _fold_slices(
    slices: list[tuple[str, float]], palette: list[str] = _CATEGORICAL, other_color: str = _OTHER
) -> list[tuple[str, float, str]]:
    """Assign categorical slots in source order; past eight, fold the smallest into Other."""
    data = [(label, value) for label, value in slices if value > 0]
    if len(data) > len(palette):
        keep = sorted(range(len(data)), key=lambda i: -data[i][1])[: len(palette) - 1]
        kept = [data[i] for i in sorted(keep)]
        other = sum(v for i, (_, v) in enumerate(data) if i not in keep)
        return [(lbl, v, palette[i]) for i, (lbl, v) in enumerate(kept)] + [
            ("Other", other, other_color)
        ]
    return [(lbl, v, palette[i]) for i, (lbl, v) in enumerate(data)]


def _render_part_to_whole(pc: PieChart, t: dict[str, str], hole: float) -> str:
    """Pie (``hole`` = 0) or donut (``hole`` = inner/outer radius ratio)."""
    slices = _fold_slices(pc.slices, _palette(t), t["other"])
    if not slices:
        return _svg_root(120, 40, _svg_text(0, 20, "No data", t, color=t["ink2"]), t["font"])
    total = sum(v for _, v, _ in slices)
    parts, top = _chart_title(pc.title, t)

    r = 92.0
    ri = r * hole
    cx, cy = r + 2, top + r + 4

    angle = -math.pi / 2
    for label, value, color in slices:
        share = value / total
        sweep = share * 2 * math.pi
        if share >= 0.9999:
            parts.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="{color}"/>')
            if ri:
                parts.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{ri:g}" fill="{t["surface"]}"/>')
        else:
            a0, a1 = angle, angle + sweep
            large = 1 if sweep > math.pi else 0
            x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            if ri:
                ix0, iy0 = cx + ri * math.cos(a1), cy + ri * math.sin(a1)
                ix1, iy1 = cx + ri * math.cos(a0), cy + ri * math.sin(a0)
                d = (
                    f"M {x0:.2f},{y0:.2f} A {r:g},{r:g} 0 {large} 1 {x1:.2f},{y1:.2f} "
                    f"L {ix0:.2f},{iy0:.2f} A {ri:g},{ri:g} 0 {large} 0 {ix1:.2f},{iy1:.2f} Z"
                )
            else:
                d = (
                    f"M {cx:g},{cy:g} L {x0:.2f},{y0:.2f} "
                    f"A {r:g},{r:g} 0 {large} 1 {x1:.2f},{y1:.2f} Z"
                )
            # 2px surface gap between neighbouring slices
            parts.append(
                f'<path d="{d}" fill="{color}" stroke="{t["surface"]}" stroke-width="2" '
                f'stroke-linejoin="round"/>'
            )
        # Direct label only where the slice is big enough to hold it
        if share >= 0.07:
            mid = angle + sweep / 2
            lr = (r + ri) / 2 if ri else r * 0.64
            lx, ly = cx + lr * math.cos(mid), cy + lr * math.sin(mid)
            if share >= 0.9999:
                lx, ly = cx, cy - (r + ri) / 2 if ri else cy
            parts.append(
                _svg_text(
                    lx,
                    ly + 4,
                    f"{share * 100:.0f}%",
                    t,
                    11,
                    _text_on(color, t),
                    600,
                    "middle",
                )
            )
        angle += sweep

    if ri:
        parts.append(_svg_text(cx, cy + 2, _fmt_num(total), t, 22, weight=600, anchor="middle"))
        parts.append(_svg_text(cx, cy + 18, "Total", t, _FS_SM, t["ink2"], anchor="middle"))

    # Legend: swatch, name, value (always present for two or more slices)
    lx = cx + r + 32
    name_w = max(_text_w(lbl) for lbl, _, _ in slices)
    values = [
        (f"{_fmt_num(v)}  ·  " if pc.show_data else "") + f"{v / total * 100:.0f}%"
        for _, v, _ in slices
    ]
    val_w = max(_text_w(v, _FS_SM) for v in values)
    row = 22.0
    ly0 = cy - (len(slices) - 1) * row / 2
    for i, ((label, _value, color), vtext) in enumerate(zip(slices, values)):
        y = ly0 + i * row
        parts.append(
            f'<rect x="{lx:g}" y="{y - 5:g}" width="10" height="10" rx="2.5" fill="{color}"/>'
        )
        parts.append(_svg_text(lx + 18, y + 4, label, t))
        parts.append(
            _svg_text(
                lx + 18 + name_w + 16 + val_w, y + 4, vtext, t, _FS_SM, t["ink2"], anchor="end"
            )
        )
    width = lx + 18 + name_w + 16 + val_w + 4
    height = max(cy + r + 4, ly0 + len(slices) * row)
    return _svg_root(width, height, parts, t["font"])


def _gantt_ticks(origin: date, lo: float, hi: float) -> tuple[list[float], str]:
    """Calendar-aligned axis ticks (days, weeks or month starts) and their label style."""
    span = max(hi - lo, 1.0)
    start = origin + timedelta(days=math.floor(lo))
    end = origin + timedelta(days=math.ceil(hi))
    if span <= 70:
        step = next(s for s in (1, 2, 7, 14) if span / s <= 8) if span > 8 else 1
        first = start
        if step >= 7:  # weeks start on Monday
            first = start + timedelta(days=(7 - start.weekday()) % 7)
        days = []
        d = first
        while d <= end:
            days.append(float((d - origin).days))
            d += timedelta(days=step)
        return days, "day"
    months = next(m for m in (1, 2, 3, 6, 12) if span / (30.4 * m) <= 8)
    y, mo = start.year, start.month
    if start.day != 1:
        mo += 1
    ticks = []
    while True:
        y += (mo - 1) // 12
        mo = (mo - 1) % 12 + 1
        d = date(y, mo, 1)
        if d > end:
            break
        if (mo - 1) % months == 0:
            ticks.append(float((d - origin).days))
        mo += 1
    return ticks, "month"


def render_pie_svg(pc: PieChart, theme: dict[str, str] | None = None) -> str:
    """Render a PieChart to an SVG string."""
    return _render_part_to_whole(pc, _tokens(theme), 0.0)


# ---------------------------------------------------------------------------
# SVG renderer — sequence diagram
# ---------------------------------------------------------------------------


def render_sequence_svg(sd: SequenceDiagram, theme: dict[str, str] | None = None) -> str:
    """Render a sequence diagram: participants, lifelines, messages, notes and frames."""
    t = _tokens(theme)
    if not sd.participants:
        return _svg_root(
            120, 40, _svg_text(0, 20, "No participants", t, color=t["ink2"]), t["font"]
        )

    msg_color = t["msg"]
    life_color = t["lifeline"]
    frame_color = t["frame"]
    n = len(sd.participants)
    index = {p: i for i, p in enumerate(sd.participants)}
    label_of = {p: sd.labels.get(p, p) for p in sd.participants}
    box_w = [max(_text_w(label_of[p], _FS) + 28, 92.0) for p in sd.participants]
    box_h = 34.0
    actor_h = 46.0
    head_h = actor_h if sd.actors else box_h

    def lines_of(text: str) -> list[str]:
        return [s.strip() for s in re.split(r"<br\s*/?>", text)]

    # Column spacing: wide enough for every message label and note it carries
    dist = [max(box_w[i] / 2 + box_w[i + 1] / 2 + 36, 128.0) for i in range(n - 1)]
    right_extra = 0.0
    needs: list[tuple[int, int, float]] = []
    for ev in sd.events:
        if isinstance(ev, SeqMessage):
            a, b = sorted((index[ev.src], index[ev.dst]))
            w = max(_text_w(s, 11) for s in lines_of(ev.label)) + 36
            if a == b:
                if a < n - 1:
                    needs.append((a, a + 1, w + 30))
                else:
                    right_extra = max(right_extra, w + 30)
            else:
                needs.append((a, b, w))
        elif isinstance(ev, SeqNote):
            w = max(_text_w(s, 11) for s in lines_of(ev.text)) + 24
            idx = sorted(index[x] for x in ev.targets)
            if ev.position == "right":
                if idx[-1] < n - 1:
                    needs.append((idx[-1], idx[-1] + 1, w + 24))
                else:
                    right_extra = max(right_extra, w + 16)
            elif ev.position == "left" and idx[0] > 0:
                needs.append((idx[0] - 1, idx[0], w + 24))
            elif ev.position == "over" and idx[0] != idx[-1]:
                needs.append((idx[0], idx[-1], w - 40))
    for a, b, w in sorted(needs, key=lambda x: x[1] - x[0]):
        have = sum(dist[a:b])
        if have < w:
            for k in range(a, b):
                dist[k] += (w - have) / (b - a)

    left_extra = 0.0
    for ev in sd.events:
        if isinstance(ev, SeqNote) and ev.position == "left" and index[ev.targets[0]] == 0:
            left_extra = max(left_extra, max(_text_w(s, 11) for s in lines_of(ev.text)) + 40)

    pad = 24.0
    x0 = max(pad + box_w[0] / 2, left_extra + 8)
    xs = [x0]
    for d in dist:
        xs.append(xs[-1] + d)
    px = {p: xs[i] for i, p in enumerate(sd.participants)}

    # ---- vertical layout pass
    y = head_h + 26.0
    active: dict[str, list[float]] = defaultdict(list)
    bars: list[tuple[str, float, float, int]] = []
    frames: list[dict] = []
    open_frames: list[dict] = []
    drawn: list[str] = []
    number = 0

    def act_offset(p: str) -> float:
        return 5.0 * len(active[p])

    def involve(*ps: str) -> None:
        for f in open_frames:
            f["who"].update(ps)

    for ev in sd.events:
        if isinstance(ev, SeqBlock):
            if ev.kind in ("else", "and", "option"):
                if open_frames:
                    open_frames[-1]["dividers"].append((y, ev.label))
                y += 28
            elif ev.kind == "end":
                if open_frames:
                    f = open_frames.pop()
                    f["y1"] = y
                    f["depth"] = len(open_frames)
                    frames.append(f)
                y += 14
            else:
                open_frames.append(
                    {"kind": ev.kind, "label": ev.label, "y0": y, "who": set(), "dividers": []}
                )
                y += 30
            continue
        if isinstance(ev, SeqActivation):
            if ev.on:
                active[ev.participant].append(y)
            elif active[ev.participant]:
                bars.append(
                    (ev.participant, active[ev.participant].pop(), y, len(active[ev.participant]))
                )
            continue
        if isinstance(ev, SeqNote):
            idx = sorted(index[x] for x in ev.targets)
            text_lines = lines_of(ev.text)
            tw = max(_text_w(s, 11) for s in text_lines) + 20
            nh = 12 + 15 * len(text_lines)
            if ev.position == "over":
                left, right = xs[idx[0]], xs[idx[-1]]
                w = max(tw, right - left + 40)
                nx = (left + right) / 2 - w / 2
            elif ev.position == "right":
                w, nx = tw, xs[idx[-1]] + 14
            else:
                w = tw
                nx = xs[idx[0]] - 14 - w
            drawn.append(
                f'<rect x="{nx:g}" y="{y:g}" width="{w:g}" height="{nh:g}" rx="4" '
                f'fill="{t["note_fill"]}" stroke="{t["note_stroke"]}" stroke-width="1"/>'
            )
            for li, s in enumerate(text_lines):
                drawn.append(_svg_text(nx + w / 2, y + 17 + li * 15, s, t, 11, anchor="middle"))
            involve(*ev.targets)
            y += nh + 14
            continue

        # Message
        msg: SeqMessage = ev  # type: ignore[assignment]
        number += 1
        text_lines = lines_of(msg.label) if msg.label else []
        y += 15 * len(text_lines) + 4
        sx_, dx_ = px[msg.src], px[msg.dst]
        dashed = msg.arrow.startswith("--") or msg.arrow.startswith("<<--")
        head = (
            "arrow"
            if msg.arrow.endswith(">>")
            else (
                "cross"
                if msg.arrow.endswith("x")
                else ("open" if msg.arrow.endswith(")") else "none")
            )
        )
        both = msg.arrow.startswith("<<")
        dash = ' stroke-dasharray="5 3"' if dashed else ""
        mk_end = f' marker-end="url(#seq-{head})"' if head != "none" else ""
        mk_start = ' marker-start="url(#seq-arrow-s)"' if both else ""
        if msg.src == msg.dst:
            x1 = sx_ + act_offset(msg.src)
            loop_w = 34.0
            drawn.append(
                f'<path d="M {x1:g},{y:g} H {x1 + loop_w:g} V {y + 22:g} H {x1 + 2:g}" fill="none" '
                f'stroke="{msg_color}" stroke-width="1.25"{dash}{mk_end}/>'
            )
            for li, s in enumerate(text_lines):
                drawn.append(
                    _svg_text(
                        x1 + loop_w + 8, y + 15 - 15 * (len(text_lines) - 1 - li) - 2, s, t, 11
                    )
                )
            line_y = y
            y += 34
        else:
            direction = 1 if dx_ > sx_ else -1
            x1 = sx_ + direction * act_offset(msg.src)
            dst_off = act_offset(msg.dst) + (5.0 if msg.activate == "+" else 0.0)
            x2 = dx_ - direction * dst_off
            drawn.append(
                f'<line x1="{x1:g}" y1="{y:g}" x2="{x2:g}" y2="{y:g}" stroke="{msg_color}" '
                f'stroke-width="1.25"{dash}{mk_end}{mk_start}/>'
            )
            cx = (x1 + x2) / 2
            for li, s in enumerate(text_lines):
                drawn.append(
                    _svg_text(
                        cx, y - 7 - 15 * (len(text_lines) - 1 - li), s, t, 11, anchor="middle"
                    )
                )
            line_y = y
            y += 22
        if sd.autonumber:
            nx = px[msg.src]
            drawn.append(
                f'<circle cx="{nx:g}" cy="{line_y:g}" r="8" fill="{t["term_fill"]}" '
                f'stroke="{t["surface"]}" stroke-width="1.5"/>'
            )
            drawn.append(
                _svg_text(nx, line_y + 3.5, str(number), t, 9.5, t["term_text"], 600, "middle")
            )
        if msg.activate == "+":
            active[msg.dst].append(line_y)
        elif msg.activate == "-" and active[msg.src]:
            bars.append((msg.src, active[msg.src].pop(), line_y, len(active[msg.src])))
        involve(msg.src, msg.dst)

    # Close anything left open
    for p, starts in active.items():
        while starts:
            bars.append((p, starts.pop(), y, len(starts)))
    while open_frames:
        f = open_frames.pop()
        f["y1"], f["depth"] = y, len(open_frames)
        frames.append(f)

    bottom_y = y + 8
    total_h = bottom_y + head_h + 6
    width = xs[-1] + box_w[-1] / 2 + max(pad, right_extra)

    parts: list[str] = [
        "<defs>",
        f'<marker id="seq-arrow" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="7" '
        f'refX="8" refY="3.5" orient="auto"><polygon points="0 0.5, 8 3.5, 0 6.5" fill="{msg_color}"/></marker>',
        f'<marker id="seq-arrow-s" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="7" '
        f'refX="1" refY="3.5" orient="auto"><polygon points="9 0.5, 1 3.5, 9 6.5" fill="{msg_color}"/></marker>',
        f'<marker id="seq-open" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="8" '
        f'refX="8" refY="4" orient="auto"><path d="M1,0.5 L8,4 L1,7.5" fill="none" stroke="{msg_color}" '
        f'stroke-width="1.25"/></marker>',
        f'<marker id="seq-cross" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" '
        f'refX="5" refY="5" orient="auto"><path d="M1.5,1.5 L8.5,8.5 M8.5,1.5 L1.5,8.5" stroke="{msg_color}" '
        f'stroke-width="1.5"/></marker>',
        "</defs>",
    ]

    # Frames (loop/alt/...) behind everything, outer ones first
    for f in sorted(frames, key=lambda f: f["depth"]):
        who = [index[p] for p in f["who"]] or list(range(n))
        margin = 26.0 - 7 * f["depth"]
        fx0 = xs[min(who)] - margin - 22
        fx1 = xs[max(who)] + margin + 22
        tag = f["kind"]
        tag_w = _text_w(tag, 10) + 16
        fx1 = max(fx1, fx0 + tag_w + _text_w(f"[{f['label']}]", _FS_SM) + 24)
        fy0, fy1 = f["y0"] + 2, f["y1"] + 4
        fill = _tint(t["primary"], 0.97, t) if tag == "rect" else "none"
        parts.append(
            f'<rect x="{fx0:g}" y="{fy0:g}" width="{fx1 - fx0:g}" height="{fy1 - fy0:g}" rx="4" '
            f'fill="{fill}" stroke="{frame_color}" stroke-width="1"/>'
        )
        if tag != "rect":
            parts.append(
                f'<path d="M {fx0:g},{fy0 + 4:g} Q {fx0:g},{fy0:g} {fx0 + 4:g},{fy0:g} H {fx0 + tag_w:g} '
                f'V {fy0 + 12:g} L {fx0 + tag_w - 6:g},{fy0 + 18:g} H {fx0:g} Z" fill="{t["tag_fill"]}" '
                f'stroke="{frame_color}" stroke-width="1"/>'
            )
            parts.append(_svg_text(fx0 + 7, fy0 + 13, tag, t, 10, t["ink2"], 600))
            if f["label"]:
                parts.append(
                    _svg_text(fx0 + tag_w + 8, fy0 + 13, f"[{f['label']}]", t, _FS_SM, t["ink2"])
                )
        for dy, dlabel in f["dividers"]:
            parts.append(
                f'<line x1="{fx0:g}" y1="{dy:g}" x2="{fx1:g}" y2="{dy:g}" stroke="{frame_color}" '
                f'stroke-width="1" stroke-dasharray="4 3"/>'
            )
            if dlabel:
                parts.append(_svg_text(fx0 + 8, dy + 14, f"[{dlabel}]", t, _FS_SM, t["ink2"]))

    # Lifelines
    for p in sd.participants:
        parts.append(
            f'<line x1="{px[p]:g}" y1="{head_h:g}" x2="{px[p]:g}" y2="{bottom_y:g}" '
            f'stroke="{life_color}" stroke-width="1" stroke-dasharray="4 4"/>'
        )
    # Activation bars
    for p, ya, yb, depth in bars:
        bx = px[p] - 5 + 5 * depth
        parts.append(
            f'<rect x="{bx:g}" y="{ya - 4:g}" width="10" height="{max(yb - ya + 8, 12):g}" rx="2" '
            f'fill="{t["node_fill"]}" stroke="{t["node_stroke"]}" stroke-width="1"/>'
        )
    parts += drawn

    # Participants, top and bottom
    for i, p in enumerate(sd.participants):
        for top in (0.0, bottom_y):
            cx = xs[i]
            if p in sd.actors:
                hy = top + 8
                parts.append(
                    f'<g fill="none" stroke="{t["ink2"]}" stroke-width="1.4" stroke-linecap="round">'
                    f'<circle cx="{cx:g}" cy="{hy:g}" r="6" fill="{t["surface"]}"/>'
                    f'<path d="M {cx:g},{hy + 6:g} V {hy + 18:g} M {cx - 9:g},{hy + 10:g} H {cx + 9:g} '
                    f"M {cx:g},{hy + 18:g} L {cx - 7:g},{hy + 27:g} M {cx:g},{hy + 18:g} "
                    f'L {cx + 7:g},{hy + 27:g}"/></g>'
                )
                parts.append(
                    _svg_text(
                        cx, top + actor_h - 2, label_of[p], t, _FS, weight=500, anchor="middle"
                    )
                )
            else:
                by = head_h - box_h if top == 0.0 else top
                parts.append(
                    f'<rect x="{cx - box_w[i] / 2:g}" y="{by:g}" width="{box_w[i]:g}" height="{box_h:g}" '
                    f'rx="6" fill="{t["card"]}" stroke="{t["node_stroke"]}" stroke-width="1.25"/>'
                )
                parts.append(
                    _svg_text(
                        cx, by + box_h / 2 + 4.2, label_of[p], t, _FS, weight=500, anchor="middle"
                    )
                )

    return _svg_root(width, total_h, parts, t["font"])


# ---------------------------------------------------------------------------
# SVG renderer — bar chart
# ---------------------------------------------------------------------------


def render_bar_svg(bc: BarChart, theme: dict[str, str] | None = None) -> str:
    """Render a bar/line chart: thin rounded bars, hairline grid, round ticks."""
    t = _tokens(theme)
    series = [(kind, vals) for kind, vals in bc.datasets if vals]
    if not series:
        return _svg_root(120, 40, _svg_text(0, 20, "No data", t, color=t["ink2"]), t["font"])
    n_cat = max(len(v) for _, v in series)
    labels = (bc.labels + [""] * n_cat)[:n_cat]
    colors = [_palette(t)[i % 8] for i in range(len(series))]
    bar_idx = [i for i, (kind, _) in enumerate(series) if kind == "bar"]
    line_idx = [i for i, (kind, _) in enumerate(series) if kind == "line"]

    all_vals = [v for _, vals in series for v in vals]
    lo = min(0.0, min(all_vals)) if bc.y_min is None else bc.y_min
    hi = max(all_vals) if bc.y_max is None else bc.y_max
    ticks = _nice_ticks(lo, hi)
    lo, hi = ticks[0], ticks[-1]

    parts, top = _chart_title(bc.title, t)
    names = [n for n in bc.series_names if n]
    if len(series) > 1 and names:
        # Legend row under the title (identity is never colour alone)
        x = 0.0
        for i, (kind, _vals) in enumerate(series):
            name = bc.series_names[i] if i < len(bc.series_names) else ""
            if not name:
                continue
            if kind == "line":
                parts.append(
                    f'<line x1="{x:g}" y1="{top + 5:g}" x2="{x + 14:g}" y2="{top + 5:g}" '
                    f'stroke="{colors[i]}" stroke-width="2" stroke-linecap="round"/>'
                )
            else:
                parts.append(
                    f'<rect x="{x + 2:g}" y="{top:g}" width="10" height="10" rx="2.5" '
                    f'fill="{colors[i]}"/>'
                )
            parts.append(_svg_text(x + 20, top + 9, name, t, _FS_SM, t["ink2"]))
            x += 20 + _text_w(name, _FS_SM) + 18
        top += 24

    tick_w = max(_text_w(_fmt_num(v), _FS_SM) for v in ticks) + 10
    n_bars = max(len(bar_idx), 1)

    if bc.horizontal:
        cat_w = min(max(_text_w(lbl) for lbl in labels) + 12, 180)
        band = max(30.0, n_bars * 16 + 14)
        plot_w = 400.0
        x0, y0 = cat_w, top + 4
        plot_h = band * n_cat

        def sx(v: float) -> float:
            return x0 + (v - lo) / (hi - lo) * plot_w

        for v in ticks:
            gx = sx(v)
            color = t["baseline"] if v == 0 else t["grid"]
            parts.append(
                f'<line x1="{gx:g}" y1="{y0:g}" x2="{gx:g}" y2="{y0 + plot_h:g}" '
                f'stroke="{color}" stroke-width="1"/>'
            )
            parts.append(
                _svg_text(
                    gx, y0 + plot_h + 16, _fmt_num(v), t, _FS_SM, t["chrome"], anchor="middle"
                )
            )
        thick = min(16.0, (band - 12) / n_bars)
        for c in range(n_cat):
            by = y0 + c * band + (band - thick * n_bars - 2 * (n_bars - 1)) / 2
            parts.append(
                _svg_text(x0 - 10, y0 + c * band + band / 2 + 4, labels[c], t, anchor="end")
            )
            for k, i in enumerate(bar_idx):
                vals = series[i][1]
                if c >= len(vals):
                    continue
                v = vals[c]
                a, b = sx(min(0.0, v) if lo <= 0 else lo), sx(max(0.0, v) if lo <= 0 else v)
                y = by + k * (thick + 2)
                w = max(b - a, 0.5)
                rr = min(4.0, w / 2, thick / 2)
                if v >= 0:
                    d = (
                        f"M {a:g},{y:g} H {a + w - rr:g} Q {a + w:g},{y:g} {a + w:g},{y + rr:g} "
                        f"V {y + thick - rr:g} Q {a + w:g},{y + thick:g} {a + w - rr:g},{y + thick:g} "
                        f"H {a:g} Z"
                    )
                else:
                    d = (
                        f"M {b:g},{y:g} H {a + rr:g} Q {a:g},{y:g} {a:g},{y + rr:g} "
                        f"V {y + thick - rr:g} Q {a:g},{y + thick:g} {a + rr:g},{y + thick:g} "
                        f"H {b:g} Z"
                    )
                parts.append(f'<path d="{d}" fill="{colors[i]}"/>')
                if n_cat * n_bars <= 16:
                    tx = b + 6 if v >= 0 else a - 6
                    parts.append(
                        _svg_text(
                            tx,
                            y + thick / 2 + 4,
                            _fmt_num(v),
                            t,
                            _FS_SM,
                            t["ink2"],
                            anchor="start" if v >= 0 else "end",
                        )
                    )
        width = x0 + plot_w + 40
        height = y0 + plot_h + 24
        return _svg_root(width, height, parts, t["font"])

    # Vertical columns
    band = max(48.0, min(110.0, 560.0 / max(n_cat, 1)))
    thick = min(24.0, (band * 0.6 - 2 * (n_bars - 1)) / n_bars)
    plot_h = 200.0
    x0, y0 = tick_w, top + 10
    plot_w = band * n_cat
    if bc.y_title:
        parts.append(_svg_text(0, top + 2, bc.y_title, t, _FS_SM, t["ink2"]))
        y0 += 12

    def sy(v: float) -> float:
        return y0 + plot_h - (v - lo) / (hi - lo) * plot_h

    for v in ticks:
        gy = sy(v)
        parts.append(
            f'<line x1="{x0:g}" y1="{gy:g}" x2="{x0 + plot_w:g}" y2="{gy:g}" '
            f'stroke="{t["grid"]}" stroke-width="1"/>'
        )
        parts.append(_svg_text(x0 - 8, gy + 3.5, _fmt_num(v), t, _FS_SM, t["chrome"], anchor="end"))
    base_y = sy(0.0) if lo <= 0 <= hi else sy(lo)

    label_lines = [_wrap_words(lbl, band - 8, 11) for lbl in labels]
    for c in range(n_cat):
        cxm = x0 + c * band + band / 2
        for li, text in enumerate(label_lines[c]):
            parts.append(
                _svg_text(cxm, y0 + plot_h + 18 + li * 13, text, t, 11, t["ink2"], anchor="middle")
            )
        group_w = thick * n_bars + 2 * (n_bars - 1)
        for k, i in enumerate(bar_idx):
            vals = series[i][1]
            if c >= len(vals):
                continue
            v = vals[c]
            x = cxm - group_w / 2 + k * (thick + 2)
            ytop, ybot = sorted((sy(v), base_y))
            h = max(ybot - ytop, 0.5)
            rr = min(4.0, thick / 2, h)
            if v >= 0:  # rounded data end, square at the baseline
                d = (
                    f"M {x:g},{ybot:g} V {ytop + rr:g} Q {x:g},{ytop:g} {x + rr:g},{ytop:g} "
                    f"H {x + thick - rr:g} Q {x + thick:g},{ytop:g} {x + thick:g},{ytop + rr:g} "
                    f"V {ybot:g} Z"
                )
            else:
                d = (
                    f"M {x:g},{ytop:g} V {ybot - rr:g} Q {x:g},{ybot:g} {x + rr:g},{ybot:g} "
                    f"H {x + thick - rr:g} Q {x + thick:g},{ybot:g} {x + thick:g},{ybot - rr:g} "
                    f"V {ytop:g} Z"
                )
            parts.append(f'<path d="{d}" fill="{colors[i]}"/>')
            if n_cat * n_bars <= 16:
                ty = ytop - 6 if v >= 0 else ybot + 13
                parts.append(
                    _svg_text(x + thick / 2, ty, _fmt_num(v), t, _FS_SM, t["ink2"], anchor="middle")
                )

    # Baseline over the bars' square ends
    parts.append(
        f'<line x1="{x0:g}" y1="{base_y:g}" x2="{x0 + plot_w:g}" y2="{base_y:g}" '
        f'stroke="{t["baseline"]}" stroke-width="1"/>'
    )

    for i in line_idx:
        vals = series[i][1]
        pts = [(x0 + c * band + band / 2, sy(v)) for c, v in enumerate(vals)]
        poly = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        parts.append(
            f'<polyline points="{poly}" fill="none" stroke="{colors[i]}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for px, py in pts:
            parts.append(
                f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{colors[i]}" '
                f'stroke="{t["surface"]}" stroke-width="2"/>'
            )

    extra = 13 * (max(len(lines) for lines in label_lines) - 1)
    if bc.x_title:
        parts.append(
            _svg_text(
                x0 + plot_w / 2,
                y0 + plot_h + 40 + extra,
                bc.x_title,
                t,
                _FS_SM,
                t["ink2"],
                anchor="middle",
            )
        )
        extra += 16
    width = x0 + plot_w + 6
    height = y0 + plot_h + 28 + extra
    return _svg_root(width, height, parts, t["font"])


# ---------------------------------------------------------------------------
# SVG renderer — donut chart (pie variant)
# ---------------------------------------------------------------------------


def render_donut_svg(pc: PieChart, theme: dict[str, str] | None = None) -> str:
    """Render a PieChart as a donut, with the total in the centre."""
    return _render_part_to_whole(pc, _tokens(theme), 0.6)


# ---------------------------------------------------------------------------
# SVG renderer — gauge chart
# ---------------------------------------------------------------------------


def render_gauge_svg(gc: GaugeChart, theme: dict[str, str] | None = None) -> str:
    """Render a semicircular meter: tinted track, filled arc, hero value."""
    t = _tokens(theme)
    fill = t["accent"]
    track = _tint(fill, 0.85, t)
    parts, top = _chart_title(gc.title, t)
    r, sw = 86.0, 16.0
    cx, cy = r + sw / 2 + 4, top + r + sw / 2 + 4
    span = (gc.max_val - gc.min_val) or 1.0
    frac = max(0.0, min(1.0, (gc.value - gc.min_val) / span))

    def pt(f: float) -> tuple[float, float]:
        a = math.pi * (1 - f)
        return cx + r * math.cos(a), cy - r * math.sin(a)

    sx, sy = pt(0.0)
    ex, ey = pt(1.0)
    parts.append(
        f'<path d="M {sx:.2f},{sy:.2f} A {r:g},{r:g} 0 0 1 {ex:.2f},{ey:.2f}" fill="none" '
        f'stroke="{track}" stroke-width="{sw:g}" stroke-linecap="round"/>'
    )
    if frac > 0:
        vx, vy = pt(frac)
        parts.append(
            f'<path d="M {sx:.2f},{sy:.2f} A {r:g},{r:g} 0 0 1 {vx:.2f},{vy:.2f}" fill="none" '
            f'stroke="{fill}" stroke-width="{sw:g}" stroke-linecap="round"/>'
        )
    parts.append(_svg_text(cx, cy - 10, _fmt_num(gc.value), t, 30, weight=600, anchor="middle"))
    parts.append(
        _svg_text(
            cx,
            cy + 8,
            gc.label or f"of {_fmt_num(gc.max_val)}",
            t,
            _FS_SM,
            t["ink2"],
            anchor="middle",
        )
    )
    parts.append(
        _svg_text(
            sx, cy + sw / 2 + 14, _fmt_num(gc.min_val), t, _FS_SM, t["chrome"], anchor="middle"
        )
    )
    parts.append(
        _svg_text(
            ex, cy + sw / 2 + 14, _fmt_num(gc.max_val), t, _FS_SM, t["chrome"], anchor="middle"
        )
    )
    width = 2 * cx
    height = cy + sw / 2 + 20
    return _svg_root(width, height, parts, t["font"])


# ---------------------------------------------------------------------------
# SVG renderer — timeline
# ---------------------------------------------------------------------------


def render_timeline_svg(tl: Timeline, theme: dict[str, str] | None = None) -> str:
    """Render a vertical timeline: periods on the left, events beside a hairline axis."""
    t = _tokens(theme)
    if not tl.entries:
        return _svg_root(120, 40, _svg_text(0, 20, "No entries", t, color=t["ink2"]), t["font"])
    parts, top = _chart_title(tl.title, t)

    period_w = max(_text_w(e.period, _FS) for e in tl.entries) + 4
    axis_x = period_w + 20
    text_x = axis_x + 20
    event_w = max([_text_w(ev, _FS) for e in tl.entries for ev in e.events] + [60.0])
    dot_rows: list[float] = []
    y = top + 10
    section = None
    for entry in tl.entries:
        if entry.section and entry.section != section:
            section = entry.section
            if dot_rows:
                y += 6
            parts.append(_svg_text(text_x, y + 10, entry.section, t, _FS_SM, t["ink2"], 600))
            y += 24
        lines = entry.events or [""]
        cy = y + 8
        dot_rows.append(cy)
        parts.append(
            _svg_text(axis_x - 18, cy + 4.2, entry.period, t, _FS, weight=600, anchor="end")
        )
        for i, ev in enumerate(lines):
            parts.append(_svg_text(text_x, cy + 4.2 + i * 18, ev, t, _FS, t["ink"]))
        y += 18 * len(lines) + 16

    axis = (
        f'<line x1="{axis_x:g}" y1="{dot_rows[0]:g}" x2="{axis_x:g}" y2="{dot_rows[-1]:g}" '
        f'stroke="{t["baseline"]}" stroke-width="1.5" stroke-linecap="round"/>'
    )
    dots = [
        f'<circle cx="{axis_x:g}" cy="{cy:g}" r="5" fill="{t["term_fill"]}" '
        f'stroke="{t["surface"]}" stroke-width="2"/>'
        for cy in dot_rows
    ]
    parts = [axis, *dots, *parts]
    width = text_x + event_w + 8
    return _svg_root(width, y - 6, parts, t["font"])


# ---------------------------------------------------------------------------
# SVG renderer — gantt chart
# ---------------------------------------------------------------------------


_GANTT_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([dwMmyh])$")
_GANTT_UNIT_DAYS = {"d": 1.0, "w": 7.0, "M": 30.0, "y": 365.0, "h": 1 / 24, "m": 1 / 1440}


def _gantt_date(text: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _gantt_days(text: str) -> float | None:
    m = _GANTT_DURATION_RE.match(text.strip())
    return float(m.group(1)) * _GANTT_UNIT_DAYS[m.group(2)] if m else None


def _resolve_gantt(gc: GanttChart) -> tuple[date, list[tuple[float, float]]]:
    """Return (origin date, [(start_day, end_day), ...]) aligned with ``gc.tasks``.

    Handles absolute dates, ``after id`` dependencies, bare durations, end dates and
    tasks with no start (which follow the previous task).
    """
    spans: dict[str, tuple[float, float]] = {}
    out: list[tuple[float, float]] = []
    origin: date | None = None
    for task in gc.tasks:
        d = _gantt_date(task.start)
        if d is not None:
            origin = origin or d
    origin = origin or date.today()
    prev_end = 0.0
    for task in gc.tasks:
        start_text, dur_text = task.start.strip(), task.duration.strip()
        dur = _gantt_days(dur_text)
        if dur is None and _gantt_days(start_text) is not None:
            dur, start_text = _gantt_days(start_text), ""
        start: float | None = None
        if start_text.lower().startswith("after "):
            deps = [spans[i][1] for i in start_text[6:].split() if i in spans]
            start = max(deps) if deps else prev_end
        elif (d := _gantt_date(start_text)) is not None:
            start = float((d - origin).days)
        if start is None:
            start = prev_end
        end_date = _gantt_date(dur_text)
        if end_date is not None:
            end = float((end_date - origin).days)
        else:
            end = start + (dur if dur is not None else 1.0)
        end = max(end, start + 0.25)
        if task.task_id:
            spans[task.task_id] = (start, end)
        out.append((start, end))
        prev_end = end
    return origin, out


def render_gantt_svg(gc: GanttChart, theme: dict[str, str] | None = None) -> str:
    """Render a GanttChart: date-scaled bars coloured by section on a calendar axis."""
    t = _tokens(theme)
    if not gc.tasks:
        return _svg_root(120, 40, _svg_text(0, 20, "No tasks", t, color=t["ink2"]), t["font"])

    origin, timeline = _resolve_gantt(gc)
    min_day = min(a for a, _ in timeline)
    max_day = max(b for _, b in timeline)

    sections: list[str] = []
    for task in gc.tasks:
        if task.section not in sections:
            sections.append(task.section)
    sec_color = {s: _palette(t)[i % 8] for i, s in enumerate(sections)}

    parts, top = _chart_title(gc.title, t)
    label_w = min(
        max([_text_w(task.name, 11) for task in gc.tasks] + [_text_w(s, 11) for s in sections])
        + 20,
        200,
    )
    chart_w = max(320.0, 570.0 - label_w)
    row_h, bar_h = 24.0, 12.0
    axis_h = 20.0
    x0 = label_w
    px_per_day = chart_w / max(max_day - min_day, 1.0)

    def sx(day: float) -> float:
        return x0 + (day - min_day) * px_per_day

    rows: list[tuple[str, object]] = []
    for sec in sections:
        if sec:
            rows.append(("section", sec))
        for idx, task in enumerate(gc.tasks):
            if task.section == sec:
                rows.append(("task", idx))
    body_top = top + axis_h
    body_h = len(rows) * row_h

    # Calendar axis: hairline gridlines, labels above
    ticks, style = _gantt_ticks(origin, min_day, max_day)
    last_year = None
    for day in ticks:
        if day < min_day - 0.01 or day > max_day + 0.01:
            continue
        gx = sx(day)
        d = origin + timedelta(days=round(day))
        if style == "day":
            text = f"{d.day} {d:%b}"
        else:
            text = f"{d:%b}" if d.year == last_year else f"{d:%b} {d.year}"
            last_year = d.year
        parts.append(
            f'<line x1="{gx:.1f}" y1="{body_top:g}" x2="{gx:.1f}" y2="{body_top + body_h:g}" '
            f'stroke="{t["grid"]}" stroke-width="1"/>'
        )
        parts.append(_svg_text(gx, body_top - 7, text, t, 10, t["chrome"], anchor="middle"))

    y = body_top
    first = True
    for kind, ref in rows:
        if kind == "section":
            if not first:
                parts.append(
                    f'<line x1="0" y1="{y:g}" x2="{x0 + chart_w:g}" y2="{y:g}" '
                    f'stroke="{t["baseline"]}" stroke-width="1"/>'
                )
            parts.append(_svg_text(0, y + row_h / 2 + 4, str(ref), t, 11, t["ink"], 600))
            y += row_h
            first = False
            continue
        idx = int(ref)  # type: ignore[call-overload]
        task = gc.tasks[idx]
        first = False
        a, b = timeline[idx]
        color = _CRITICAL if "crit" in task.tags else sec_color[task.section]
        parts.append(
            _svg_text(12 if task.section else 0, y + row_h / 2 + 4, task.name, t, 11, t["ink2"])
        )
        cy = y + row_h / 2
        if "milestone" in task.tags or (b - a) <= 0.26:
            mx, s = sx(a), 6.5
            parts.append(
                f'<path d="M {mx:.1f},{cy - s:.1f} L {mx + s:.1f},{cy:.1f} L {mx:.1f},{cy + s:.1f} '
                f'L {mx - s:.1f},{cy:.1f} Z" fill="{color}"/>'
            )
            parts.append(
                _svg_text(
                    mx + s + 6,
                    cy + 4,
                    f"{(origin + timedelta(days=round(a))).day} "
                    f"{(origin + timedelta(days=round(a))):%b}",
                    t,
                    _FS_SM,
                    t["ink2"],
                )
            )
        else:
            bx, bw = sx(a), max((b - a) * px_per_day, 3.0)
            opacity = ' fill-opacity="0.4"' if "done" in task.tags else ""
            parts.append(
                f'<rect x="{bx:.1f}" y="{cy - bar_h / 2:g}" width="{bw:.1f}" height="{bar_h:g}" '
                f'rx="3" fill="{color}"{opacity}/>'
            )
            dur = task.duration if _gantt_days(task.duration) else f"{b - a:g}d"
            if bw >= _text_w(dur, 9.5) + 12 and "done" not in task.tags:
                parts.append(
                    _svg_text(bx + bw / 2, cy + 3.5, dur, t, 9.5, _text_on(color, t), 600, "middle")
                )
            else:
                parts.append(_svg_text(bx + bw + 5, cy + 3.5, dur, t, 9.5, t["ink2"]))
        y += row_h

    # Room for labels drawn past the last date (milestones, durations beside short bars)
    width = x0 + chart_w + 52
    height = body_top + body_h + 6
    return _svg_root(width, height, parts, t["font"])


# ---------------------------------------------------------------------------
# SVG renderer — mind map
# ---------------------------------------------------------------------------


def render_mindmap_svg(root: MindNode, theme: dict[str, str] | None = None) -> str:
    """Render a mind map balanced left and right of a central topic."""
    t = _tokens(theme)

    def size(node: MindNode, depth: int) -> tuple[float, float]:
        fs = 13.0 if depth == 0 else _FS if depth == 1 else 11.5
        pad_x = 18 if depth == 0 else 12
        return _text_w(node.label, fs) + 2 * pad_x, (
            34.0 if depth == 0 else 28.0 if depth == 1 else 24.0
        )

    def leaves(node: MindNode) -> int:
        return max(1, sum(leaves(c) for c in node.children))

    # Split top-level branches between the two sides, balancing leaf counts
    right: list[tuple[int, MindNode]] = []
    left: list[tuple[int, MindNode]] = []
    rl = ll = 0
    for i, child in enumerate(root.children):
        if rl <= ll:
            right.append((i, child))
            rl += leaves(child)
        else:
            left.append((i, child))
            ll += leaves(child)

    gap_x, gap_y = 40.0, 8.0
    boxes: list[tuple[MindNode, int, float, float, float, float, str]] = (
        []
    )  # node, depth, x, y, w, h, color
    links: list[tuple[float, float, float, float, str, int]] = []

    def col_widths(branches: list[tuple[int, MindNode]]) -> list[float]:
        widths: dict[int, float] = defaultdict(float)

        def walk(node: MindNode, depth: int) -> None:
            widths[depth] = max(widths[depth], size(node, depth)[0])
            for c in node.children:
                walk(c, depth + 1)

        for _, b in branches:
            walk(b, 1)
        return [widths[d] for d in range(1, max(widths, default=0) + 1)]

    def place(
        node: MindNode, depth: int, side: int, offsets: list[float], y: float, color: str
    ) -> tuple[float, float]:
        """Lay out a subtree; return (centre y, next free y)."""
        w, h = size(node, depth)
        if node.children:
            cys = []
            cursor = y
            for c in node.children:
                ccy, cursor = place(c, depth + 1, side, offsets, cursor, color)
                cys.append(ccy)
            cy = (cys[0] + cys[-1]) / 2
            nxt = max(cursor, cy + h / 2 + gap_y)
        else:
            cy = y + h / 2
            nxt = y + h + gap_y
        inner = offsets[depth - 1]
        x = inner if side > 0 else -inner - w
        boxes.append((node, depth, x, cy - h / 2, w, h, color))
        return cy, nxt

    rw, lw = size(root, 0)
    sides: dict[int, tuple[float, float]] = {}
    for side, branches in ((1, right), (-1, left)):
        if not branches:
            continue
        widths = col_widths(branches)
        offsets, acc = [], rw / 2 + gap_x + 12
        for wcol in widths:
            offsets.append(acc)
            acc += wcol + gap_x
        y = 0.0
        tops = []
        for i, branch in branches:
            color = _palette(t)[i % 8]
            cy, y = place(branch, 1, side, offsets, y, color)
            tops.append(cy)
            y += 10
        sides[side] = (0.0, y)

    # Centre each side vertically on the root
    side_h = {s: h for s, (_, h) in sides.items()}
    total_h = max(side_h.values(), default=lw)
    shifted = []
    for node, depth, x, by, w, h, color in boxes:
        side = 1 if x >= 0 else -1
        shift = (total_h - side_h.get(side, total_h)) / 2
        shifted.append((node, depth, x, by + shift, w, h, color))
    boxes = shifted
    root_cy = total_h / 2 - 5
    pos = {id(b[0]): b for b in boxes}

    # Links from each parent edge to child edge (smooth cubic curves)
    def edge_point(node: MindNode, side: int, outward: bool) -> tuple[float, float]:
        if node is root:
            return (side * rw / 2, root_cy)
        _, _, x, by, w, h, _ = pos[id(node)]
        cx = x + w if (side > 0) == outward else x
        return (cx, by + h / 2)

    def link_walk(node: MindNode, side: int) -> None:
        for c in node.children:
            sx, sy = edge_point(node, side, True)
            ex, ey = edge_point(c, side, False)
            color = pos[id(c)][6]
            depth = pos[id(c)][1]
            links.append((sx, sy, ex, ey, color, depth))
            link_walk(c, side)

    for side, branches in ((1, right), (-1, left)):
        for _, b in branches:
            sx, sy = edge_point(root, side, True)
            ex, ey = edge_point(b, side, False)
            links.append((sx, sy, ex, ey, pos[id(b)][6], 1))
            link_walk(b, side)

    xs = [x for _, _, x, _, _, _, _ in boxes] + [-rw / 2]
    xe = [x + w for _, _, x, _, w, _, _ in boxes] + [rw / 2]
    ys = [by for _, _, _, by, _, _, _ in boxes] + [root_cy - lw / 2]
    ye = [by + h for _, _, _, by, _, h, _ in boxes] + [root_cy + lw / 2]
    pad = 6.0
    ox, oy = min(xs) - pad, min(ys) - pad
    parts = [f'<g transform="translate({-ox:g},{-oy:g})">']
    for sx, sy, ex, ey, color, depth in links:
        mx = (sx + ex) / 2
        parts.append(
            f'<path d="M {sx:.1f},{sy:.1f} C {mx:.1f},{sy:.1f} {mx:.1f},{ey:.1f} {ex:.1f},{ey:.1f}" '
            f'fill="none" stroke="{_tint(color, 0.25 if depth == 1 else 0.45, t)}" '
            f'stroke-width="{2 if depth == 1 else 1.5}" stroke-linecap="round"/>'
        )
    parts.append(
        f'<rect x="{-rw / 2:g}" y="{root_cy - lw / 2:g}" width="{rw:g}" height="{lw:g}" '
        f'rx="{lw / 2:g}" fill="{t["term_fill"]}"/>'
    )
    parts.append(_svg_text(0, root_cy + 4.6, root.label, t, 13, t["term_text"], 600, "middle"))
    for node, depth, x, by, w, h, color in boxes:
        if depth == 1:
            fill, stroke, fs, weight = _tint(color, 0.86, t), _tint(color, 0.35, t), _FS, 500
        else:
            fill, stroke, fs, weight = t["card"], _tint(color, 0.6, t), 11.5, 400
        parts.append(
            f'<rect x="{x:g}" y="{by:g}" width="{w:g}" height="{h:g}" rx="{h / 2:g}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.25"/>'
        )
        parts.append(
            _svg_text(
                x + w / 2, by + h / 2 + fs * 0.35, node.label, t, fs, weight=weight, anchor="middle"
            )
        )
    parts.append("</g>")
    return _svg_root(max(xe) - ox + pad, max(ye) - oy + pad, parts, t["font"])


_ER_LEFT = {"||": "one", "|o": "zero_one", "o|": "zero_one", "}|": "one_many", "}o": "zero_many"}
_ER_RIGHT = {"||": "one", "o|": "zero_one", "|o": "zero_one", "|{": "one_many", "o{": "zero_many"}


# ---------------------------------------------------------------------------
# SVG renderer — ER diagram
# ---------------------------------------------------------------------------


def render_er_svg(erd: ERDiagram, theme: dict[str, str] | None = None) -> str:
    """Render an ER diagram: entity cards laid out in ranks, crow's-foot relationships."""
    t = _tokens(theme)
    if not erd.entities:
        return _svg_root(120, 40, _svg_text(0, 20, "No entities", t, color=t["ink2"]), t["font"])

    head_h, row_h = 28.0, 22.0
    cards: dict[str, tuple[float, float, float, float]] = {}  # name -> (w, h, type_col, key_col)
    for name, ent in erd.entities.items():
        types = [a.split(" ", 1)[0] for a in ent.attributes]
        names = [a.split(" ", 1)[1] if " " in a else "" for a in ent.attributes]
        type_col = max([_text_w(x, _FS_SM) for x in types] + [0.0])
        name_col = max([_text_w(x, 11.5) for x in names] + [0.0])
        key_col = max([_text_w(k, 9.5) for k in ent.keys if k] + [0.0])
        w = max(
            _text_w(name, _FS) + 32,
            12 + type_col + 14 + name_col + (key_col + 16 if key_col else 0) + 12,
            120,
        )
        h = head_h + (len(ent.attributes) * row_h + 4 if ent.attributes else 0)
        cards[name] = (w, h, type_col, key_col)

    fc = Flowchart(direction="LR", end_marker_space=20.0)
    for name, (w, h, _, _) in cards.items():
        fc.nodes[name] = Node(name, "", "fixed", w=w, h=h)
    for rel in erd.relations:
        fc.edges.append(Edge(rel.entity_a, rel.entity_b, rel.label))
    layout(fc, t)
    _fit_to_column(fc, t, wrap=False)
    ports = _assign_ports(fc)
    vertical = fc.direction not in ("LR", "RL")

    color = t["edge"]
    xs0 = [n.x for n in fc.nodes.values()]
    ys0 = [n.y for n in fc.nodes.values()]
    xs1 = [n.x + n.w for n in fc.nodes.values()]
    ys1 = [n.y + n.h for n in fc.nodes.values()]
    for pts in fc.waypoints.values():
        xs0 += [p[0] for p in pts]
        xs1 += [p[0] for p in pts]
        ys0 += [p[1] for p in pts]
        ys1 += [p[1] for p in pts]
    pad = 10.0
    ox, oy = min(xs0) - pad, min(ys0) - pad
    parts = [_er_marker_defs(color, t["surface"]), f'<g transform="translate({-ox:g},{-oy:g})">']

    for i, rel in enumerate(erd.relations):
        src, dst = fc.nodes.get(rel.entity_a), fc.nodes.get(rel.entity_b)
        if not src or not dst:
            continue
        d, label_xy = _routed_path(
            src,
            dst,
            fc.waypoints.get(i, []),
            not vertical,
            rel.label,
            ports.get((i, "out")),
            ports.get((i, "in")),
        )
        dash = ' stroke-dasharray="5 3"' if rel.style == "dotted" else ""
        parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.25"{dash} '
            f'marker-start="url(#er-{rel.card_a}-s)" marker-end="url(#er-{rel.card_b})"/>'
        )
        if rel.label:
            lx, ly = label_xy or (
                (src.x + src.w / 2 + dst.x + dst.w / 2) / 2,
                (src.y + src.h / 2 + dst.y + dst.h / 2) / 2 + _FS_SM * 0.35,
            )
            lw = _text_w(rel.label, _FS_SM) + 10
            parts.append(
                f'<rect x="{lx - lw / 2:g}" y="{ly - 11:g}" width="{lw:g}" height="15" rx="3" fill="{t["surface"]}"/>'
            )
            parts.append(_svg_text(lx, ly, rel.label, t, _FS_SM, t["ink2"], anchor="middle"))

    for name, ent in erd.entities.items():
        node = fc.nodes[name]
        x, y, w, h = node.x, node.y, node.w, node.h
        _, _, type_col, _key_col = cards[name]
        r = 6.0
        parts.append(
            f'<rect x="{x:g}" y="{y + 1.5:g}" width="{w:g}" height="{h:g}" rx="{r:g}" '
            f'fill="#0b1f33" fill-opacity="{t["shadow"]}"/>'
        )
        parts.append(
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{r:g}" fill="{t["card"]}" '
            f'stroke="{t["node_stroke"]}" stroke-width="1.25"/>'
        )
        hb = head_h if ent.attributes else h
        rb = 0.0 if ent.attributes else r
        parts.append(
            f'<path d="M {x:g},{y + hb - rb:g} V {y + r:g} Q {x:g},{y:g} {x + r:g},{y:g} H {x + w - r:g} '
            f"Q {x + w:g},{y:g} {x + w:g},{y + r:g} V {y + hb - rb:g} "
            + (
                f"Q {x + w:g},{y + hb:g} {x + w - r:g},{y + hb:g} H {x + r:g} Q {x:g},{y + hb:g} {x:g},{y + hb - r:g} "
                if rb
                else f"H {x:g} "
            )
            + f'Z" fill="{t["term_fill"]}"/>'
        )
        parts.append(
            _svg_text(x + w / 2, y + hb / 2 + 4.3, name, t, _FS, t["term_text"], 600, "middle")
        )
        for k, (attr, key) in enumerate(
            zip(ent.attributes, ent.keys or [""] * len(ent.attributes))
        ):
            ry = y + head_h + 2 + k * row_h
            typ, _, aname = attr.partition(" ")
            if k:
                parts.append(
                    f'<line x1="{x + 1:g}" y1="{ry:g}" x2="{x + w - 1:g}" y2="{ry:g}" '
                    f'stroke="{t["hairline"]}" stroke-width="1"/>'
                )
            parts.append(_svg_text(x + 12, ry + row_h / 2 + 3.8, typ, t, _FS_SM, t["chrome"]))
            parts.append(_svg_text(x + 12 + type_col + 14, ry + row_h / 2 + 4, aname, t, 11.5))
            if key:
                parts.append(
                    _svg_text(x + w - 12, ry + row_h / 2 + 3.5, key, t, 9.5, t["ink2"], 700, "end")
                )
    parts.append("</g>")
    return _svg_root(max(xs1) - ox + pad, max(ys1) - oy + pad, parts, t["font"])


# ---------------------------------------------------------------------------
# SVG renderer — state diagram
# ---------------------------------------------------------------------------


def _uml_text(text: str) -> str:
    """Mermaid generics ``List~int~`` -> ``List<int>``."""
    return re.sub(r"~([^~]+)~", r"<\1>", text)


def _parse_member(raw: str) -> ClassMember:
    text = raw.strip()
    member = ClassMember(text=text)
    if text.endswith("$"):
        member.static, text = True, text[:-1].rstrip()
    elif text.endswith("*"):
        member.abstract, text = True, text[:-1].rstrip()
    # Method return-type classifiers can also sit right after the parentheses
    m = re.match(r"^(.*\))\s*([$*])\s*(.*)$", text)
    if m:
        member.static = member.static or m.group(2) == "$"
        member.abstract = member.abstract or m.group(2) == "*"
        text = f"{m.group(1)} {m.group(3)}".strip()
    if text[:1] in "+-#~":
        member.visibility, text = text[0], text[1:].strip()
    member.text = _uml_text(text)
    member.method = "(" in text
    return member


_CLASS_REL_RE = re.compile(
    r'^([\w.`-]+)\s*(?:"([^"]*)"\s*)?'
    r"(<\|--|<\|\.\.|\*--|o--|<--|<\.\.|--\|>|\.\.\|>|--\*|--o|-->|\.\.>|<\|--\|>|--|\.\.)"
    r'\s*(?:"([^"]*)"\s*)?([\w.`-]+)\s*(?::\s*(.+))?$'
)


def parse_class(source: str) -> ClassDiagram:
    """Parse a Mermaid class diagram."""
    cd = ClassDiagram()
    current: str | None = None
    namespace: Subgraph | None = None

    def ensure(name: str) -> ClassDef:
        name = name.strip("`")
        if name not in cd.classes:
            generic = re.match(r"^(\w+)~(.+)~$", name)
            label = f"{generic.group(1)}<{generic.group(2)}>" if generic else name
            base = generic.group(1) if generic else name
            cd.classes[base] = ClassDef(name=base, label=label)
            if namespace is not None:
                namespace.node_ids.append(base)
            return cd.classes[base]
        return cd.classes[name]

    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^classDiagram", line, re.IGNORECASE):
            continue
        if current is not None:
            if line.startswith("}"):
                current = None
                continue
            ann = re.match(r"^<<(.+)>>$", line)
            if ann:
                cd.classes[current].annotation = ann.group(1).strip()
            else:
                cd.classes[current].members.append(_parse_member(line))
            continue

        m = re.match(r"^direction\s+(TB|TD|BT|LR|RL)$", line, re.IGNORECASE)
        if m:
            cd.direction = m.group(1).upper()
            continue
        m = re.match(r"^namespace\s+([\w.-]+)\s*\{$", line)
        if m:
            namespace = Subgraph(id=m.group(1), label=m.group(1))
            cd.namespaces.append(namespace)
            continue
        if line == "}" and namespace is not None:
            namespace = None
            continue
        m = re.match(r'^class\s+([\w`~.-]+)(?:\s*\["([^"]*)"\])?\s*(?:::::?\w+)?\s*(\{)?\s*$', line)
        if m:
            cls = ensure(m.group(1))
            if m.group(2):
                cls.label = m.group(2)
            if m.group(3):
                current = cls.name
            continue
        m = re.match(r"^<<(.+)>>\s+([\w`~.-]+)$", line)
        if m:
            ensure(m.group(2)).annotation = m.group(1).strip()
            continue
        m = re.match(r'^note\s+for\s+([\w`~.-]+)\s+"(.*)"$', line)
        if m:
            cd.notes.append((ensure(m.group(1)).name, m.group(2).replace("\\n", "\n")))
            continue
        if re.match(r'^note\s+"', line) or line.startswith(
            ("click ", "link ", "callback ", "style ", "classDef ", "cssClass ")
        ):
            continue
        m = _CLASS_REL_RE.match(line)
        if m:
            a, card_a, op, card_b, b, label = m.groups()
            a, b = ensure(a).name, ensure(b).name
            dashed = ".." in op
            left = {"<|": "inherit", "*": "composition", "o": "aggregation", "<": "arrow"}
            right = {"|>": "inherit", "*": "composition", "o": "aggregation", ">": "arrow"}
            body = op.replace("--", " ").replace("..", " ")
            lhs, _, rhs = body.partition(" ")
            rel = ClassRelation(
                a,
                b,
                left.get(lhs.strip(), "none"),
                right.get(rhs.strip(), "none"),
                dashed,
                (label or "").strip(),
                card_a or "",
                card_b or "",
            )
            # Lay parents/wholes above (or before) their children/parts
            if rel.end_b in ("inherit", "composition", "aggregation") and rel.end_a == "none":
                rel = ClassRelation(
                    b, a, rel.end_b, "none", dashed, rel.label, rel.card_b, rel.card_a
                )
            cd.relations.append(rel)
            continue
        m = re.match(r"^([\w`~.-]+)\s*:\s*(.+)$", line)
        if m:
            ensure(m.group(1)).members.append(_parse_member(m.group(2)))
            continue
        m = re.match(r"^([\w`~.-]+)$", line)
        if m:
            ensure(m.group(1))
    return cd


def _class_marker_defs(color: str, surface: str) -> str:
    """UML relationship ends: inheritance triangle, composition/aggregation diamonds, open arrow."""
    shapes = {
        "inherit": f'<path d="M 1,1 L 15,7 L 1,13 Z" fill="{surface}" stroke="{color}" stroke-width="1.25" stroke-linejoin="round"/>',
        "composition": f'<path d="M 1,7 L 8,2 L 15,7 L 8,12 Z" fill="{color}" stroke="{color}" stroke-width="1.25"/>',
        "aggregation": f'<path d="M 1,7 L 8,2 L 15,7 L 8,12 Z" fill="{surface}" stroke="{color}" stroke-width="1.25"/>',
        "arrow": f'<path d="M 6,2 L 15,7 L 6,12" fill="none" stroke="{color}" stroke-width="1.25" stroke-linecap="round"/>',
    }
    out = ["<defs>"]
    common = (
        'markerUnits="userSpaceOnUse" markerWidth="16" markerHeight="14" refY="7" orient="auto"'
    )
    for kind, body in shapes.items():
        out.append(f'<marker id="cls-{kind}" refX="15" {common}>{body}</marker>')
        out.append(
            f'<marker id="cls-{kind}-s" refX="1" {common}>'
            f'<g transform="matrix(-1 0 0 1 16 0)">{body}</g></marker>'
        )
    out.append("</defs>")
    return "\n".join(out)


def _path_ends(
    d: str,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]:
    """First two and last two distinct points of an SVG path (for placing end labels)."""
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d)]
    pts: list[tuple[float, float]] = []
    for i in range(0, len(nums) - 1, 2):
        pt = (nums[i], nums[i + 1])
        if not pts or abs(pts[-1][0] - pt[0]) > 0.01 or abs(pts[-1][1] - pt[1]) > 0.01:
            pts.append(pt)
    if len(pts) < 2:
        pts = pts * 2 if pts else [(0.0, 0.0), (1.0, 0.0)]
    return pts[0], pts[1], pts[-1], pts[-2]


def _path_midpoint(d: str) -> tuple[float, float]:
    """Point halfway along a path's vertices (by length)."""
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d)]
    pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
    segs = [(a, b, math.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(pts, pts[1:])]
    half = sum(length for _, _, length in segs) / 2
    for a, b, length in segs:
        if half <= length and length > 0:
            f = half / length
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        half -= length
    return pts[len(pts) // 2] if pts else (0.0, 0.0)


def render_class_svg(cd: ClassDiagram, theme: dict[str, str] | None = None) -> str:
    """Render a UML class diagram."""
    t = _tokens(theme)
    if not cd.classes:
        return _svg_root(120, 40, _svg_text(0, 20, "No classes", t, color=t["ink2"]), t["font"])

    row_h, head_h, pad = 19.0, 30.0, 12.0
    sizes: dict[str, tuple[float, float, float, float]] = {}  # w, h, header h, attr h
    for name, cls in cd.classes.items():
        attrs = [mb for mb in cls.members if not mb.method]
        methods = [mb for mb in cls.members if mb.method]
        hh = head_h + (13 if cls.annotation else 0)
        widths = [_text_w(cls.label, _FS, 600) + 28, 120.0]
        if cls.annotation:
            widths.append(_text_w(f"«{cls.annotation}»", _FS_SM) + 28)
        for mb in cls.members:
            widths.append(_text_w(mb.text, 11.5) + (16 if mb.visibility else 0) + 2 * pad)
        ah = len(attrs) * row_h + 10
        mh = len(methods) * row_h + 10
        sizes[name] = (max(widths), hh + ah + mh, hh, ah)

    fc = Flowchart(
        direction={"TB": "TD", "BT": "TD"}.get(cd.direction, cd.direction), end_marker_space=12.0
    )
    for name, (w, h, _, _) in sizes.items():
        fc.nodes[name] = Node(name, "", "fixed", w=w, h=h)
    note_ids: list[str] = []
    for i, (target, text) in enumerate(cd.notes):
        nid = f"__note{i}"
        lines = text.split("\n")
        fc.nodes[nid] = Node(
            nid, "", "fixed", w=max(_text_w(x, 11) for x in lines) + 24, h=16 * len(lines) + 14
        )
        note_ids.append(nid)
        fc.edges.append(Edge(nid, target, ""))
    rel_offset = len(fc.edges)
    for rel in cd.relations:
        fc.edges.append(Edge(rel.a, rel.b, rel.label))
    fc.subgraphs = [Subgraph(ns.id, ns.label, list(ns.node_ids)) for ns in cd.namespaces]
    layout(fc, t)
    _fit_to_column(fc, t, wrap=False)
    ports = _assign_ports(fc)
    horizontal = fc.direction in ("LR", "RL")

    ox, oy, width, height = _flow_extent(fc, pad=14.0)
    color = t["edge"]
    parts = [_class_marker_defs(color, t["surface"]), f'<g transform="translate({-ox:g},{-oy:g})">']
    for sg in fc.subgraphs:
        parts.append(_render_subgraph(sg, t))

    # Note connectors
    for i, nid in enumerate(note_ids):
        src, dst = fc.nodes[nid], fc.nodes[cd.notes[i][0]]
        d, _ = _routed_path(
            src,
            dst,
            fc.waypoints.get(i, []),
            horizontal,
            "",
            ports.get((i, "out")),
            ports.get((i, "in")),
        )
        parts.append(
            f'<path d="{d}" fill="none" stroke="{t["note_stroke"]}" stroke-width="1.25" stroke-dasharray="4 3"/>'
        )

    cards: list[tuple[float, float, str, float]] = []
    for k, rel in enumerate(cd.relations):
        i = rel_offset + k
        src, dst = fc.nodes[rel.a], fc.nodes[rel.b]
        d, label_xy = _routed_path(
            src,
            dst,
            fc.waypoints.get(i, []),
            horizontal,
            rel.label,
            ports.get((i, "out")),
            ports.get((i, "in")),
        )
        dash = ' stroke-dasharray="5 3"' if rel.dashed else ""
        mk = ""
        if rel.end_a != "none":
            mk += f' marker-start="url(#cls-{rel.end_a}-s)"'
        if rel.end_b != "none":
            mk += f' marker-end="url(#cls-{rel.end_b})"'
        parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.25"{dash}{mk}/>')
        if rel.label:
            lx, ly = _path_midpoint(d)
            ly += _FS_SM * 0.35
            lw = _text_w(rel.label, _FS_SM) + 10
            parts.append(
                f'<rect x="{lx - lw / 2:g}" y="{ly - 11:g}" width="{lw:g}" height="15" rx="3" '
                f'fill="{t["surface"]}"/>'
            )
            parts.append(_svg_text(lx, ly, rel.label, t, _FS_SM, t["ink2"], anchor="middle"))
        start, nxt, end, prev = _path_ends(d)
        for (p0, p1), card in (((start, nxt), rel.card_a), ((end, prev), rel.card_b)):
            if not card:
                continue
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            length = math.hypot(dx, dy) or 1.0
            ux, uy = dx / length, dy / length
            cw = _text_w(card, _FS_SM) + 6
            # Beside the line, just past the end marker
            cx = p0[0] + ux * 24 + (-uy) * (cw / 2 + 5)
            cy = p0[1] + uy * 24 + ux * 11
            cards.append((cx, cy, card, cw))

    for cx, cy, card, cw in cards:
        parts.append(
            f'<rect x="{cx - cw / 2:g}" y="{cy - 10:g}" width="{cw:g}" height="14" rx="3" '
            f'fill="{t["surface"]}"/>'
        )
        parts.append(_svg_text(cx, cy + 1, card, t, _FS_SM, t["ink2"], anchor="middle"))

    for i, nid in enumerate(note_ids):
        n = fc.nodes[nid]
        parts.append(
            f'<rect x="{n.x:g}" y="{n.y:g}" width="{n.w:g}" height="{n.h:g}" rx="4" '
            f'fill="{t["note_fill"]}" stroke="{t["note_stroke"]}" stroke-width="1"/>'
        )
        for li, text in enumerate(cd.notes[i][1].split("\n")):
            parts.append(_svg_text(n.x + 12, n.y + 20 + li * 16, text, t, 11))

    for name, cls in cd.classes.items():
        n = fc.nodes[name]
        x, y, w, h = n.x, n.y, n.w, n.h
        _, _, hh, ah = sizes[name]
        r = 6.0
        parts.append(
            f'<rect x="{x:g}" y="{y + 1.5:g}" width="{w:g}" height="{h:g}" rx="{r:g}" '
            f'fill="#0b1f33" fill-opacity="{t["shadow"]}"/>'
        )
        parts.append(
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{r:g}" fill="{t["card"]}" '
            f'stroke="{t["node_stroke"]}" stroke-width="1.25"/>'
        )
        parts.append(
            f'<path d="M {x:g},{y + hh:g} V {y + r:g} Q {x:g},{y:g} {x + r:g},{y:g} H {x + w - r:g} '
            f'Q {x + w:g},{y:g} {x + w:g},{y + r:g} V {y + hh:g} Z" fill="{t["node_fill"]}" '
            f'stroke="{t["node_stroke"]}" stroke-width="1.25"/>'
        )
        ty = y + 19
        if cls.annotation:
            parts.append(
                _svg_text(
                    x + w / 2, ty - 2, f"«{cls.annotation}»", t, _FS_SM, t["ink2"], anchor="middle"
                )
            )
            ty += 13
        abstract = cls.annotation.lower() in ("abstract", "interface")
        parts.append(
            _svg_text(
                x + w / 2,
                ty,
                cls.label,
                t,
                _FS,
                weight=600,
                anchor="middle",
                extra=' font-style="italic"' if abstract else "",
            )
        )
        parts.append(
            f'<line x1="{x:g}" y1="{y + hh + ah:g}" x2="{x + w:g}" y2="{y + hh + ah:g}" '
            f'stroke="{t["node_stroke"]}" stroke-width="1"/>'
        )
        attrs = [mb for mb in cls.members if not mb.method]
        methods = [mb for mb in cls.members if mb.method]
        for group, top in ((attrs, y + hh + 5), (methods, y + hh + ah + 5)):
            for k, mb in enumerate(group):
                by = top + k * row_h + 13.5
                tx = x + pad
                if mb.visibility:
                    parts.append(_svg_text(tx, by, mb.visibility, t, 11.5, t["chrome"], 600))
                    tx += 14
                extra = ' font-style="italic"' if mb.abstract else ""
                parts.append(_svg_text(tx, by, mb.text, t, 11.5, extra=extra))
                if mb.static:
                    uw = _text_w(mb.text, 11.5)
                    parts.append(
                        f'<line x1="{tx:g}" y1="{by + 2:g}" x2="{tx + uw:g}" y2="{by + 2:g}" '
                        f'stroke="{t["ink"]}" stroke-width="0.8"/>'
                    )
    parts.append("</g>")
    return _svg_root(width, height, parts, t["font"])


def parse_journey(source: str) -> Journey:
    """Parse a Mermaid user journey."""
    jr = Journey()
    section = ""
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^journey\b", line, re.IGNORECASE):
            continue
        m = re.match(r"^title\s+(.+)$", line, re.IGNORECASE)
        if m:
            jr.title = m.group(1).strip()
            continue
        m = re.match(r"^section\s+(.+)$", line, re.IGNORECASE)
        if m:
            section = m.group(1).strip()
            continue
        m = re.match(r"^(.+?)\s*:\s*(\d+(?:\.\d+)?)\s*(?::\s*(.*))?$", line)
        if m:
            actors = [a.strip() for a in (m.group(3) or "").split(",") if a.strip()]
            score = max(1.0, min(5.0, float(m.group(2))))
            jr.tasks.append(JourneyTask(m.group(1).strip(), score, actors, section))
    return jr


# Satisfaction carries meaning (good / bad), so it uses the reserved status colours
_SCORE_COLORS = {1: "#d03b3b", 2: "#ec835a", 3: "#fab219", 4: "#5cb85c", 5: "#0ca30c"}


def render_journey_svg(jr: Journey, theme: dict[str, str] | None = None) -> str:
    """Render a user journey: sections, task cards, a satisfaction curve and actors."""
    t = _tokens(theme)
    if not jr.tasks:
        return _svg_root(120, 40, _svg_text(0, 20, "No tasks", t, color=t["ink2"]), t["font"])
    parts, top = _chart_title(jr.title, t)

    actors: list[str] = []
    for task in jr.tasks:
        for a in task.actors:
            if a not in actors:
                actors.append(a)
    actor_color = {a: _palette(t)[i % 8] for i, a in enumerate(actors)}
    sections: list[str] = []
    for task in jr.tasks:
        if task.section not in sections:
            sections.append(task.section)
    sec_color = {s: _palette(t)[i % 8] for i, s in enumerate(sections)}

    axis_w = 26.0
    col_w = max(104.0, max(min(_text_w(task.name, 11.5) + 20, 150.0) for task in jr.tasks))
    lines = [_wrap_words(task.name, col_w - 16, 11.5) for task in jr.tasks]
    card_h = 14 + 15 * max(len(x) for x in lines)
    band_y = top
    card_y = band_y + (30 if any(sections) else 0)
    track_y = card_y + card_h + 22
    level_h = 22.0
    track_h = level_h * 4

    def cx(i: int) -> float:
        return axis_w + i * col_w + col_w / 2

    def sy(score: float) -> float:
        return track_y + (5 - score) * level_h

    # Section bands
    for sec in sections:
        idx = [i for i, task in enumerate(jr.tasks) if task.section == sec]
        if not sec:
            continue
        x0 = axis_w + idx[0] * col_w + 3
        x1 = axis_w + (idx[-1] + 1) * col_w - 3
        color = sec_color[sec]
        parts.append(
            f'<rect x="{x0:g}" y="{band_y:g}" width="{x1 - x0:g}" height="22" rx="5" '
            f'fill="{_tint(color, 0.85, t)}"/>'
        )
        parts.append(_svg_text(x0 + 10, band_y + 15, sec, t, 11, t["ink"], 600))

    # Task cards
    for i, task in enumerate(jr.tasks):
        x0 = axis_w + i * col_w + 4
        stroke = _tint(sec_color[task.section], 0.55, t) if task.section else t["node_stroke"]
        parts.append(
            f'<rect x="{x0:g}" y="{card_y:g}" width="{col_w - 8:g}" height="{card_h:g}" rx="6" '
            f'fill="{t["card"]}" stroke="{stroke}" stroke-width="1.25"/>'
        )
        for li, text in enumerate(lines[i]):
            parts.append(_svg_text(cx(i), card_y + 19 + li * 15, text, t, 11.5, anchor="middle"))

    # Satisfaction track: five hairline levels, labelled at the left
    for score in range(1, 6):
        y = sy(score)
        parts.append(
            f'<line x1="{axis_w:g}" y1="{y:g}" x2="{axis_w + col_w * len(jr.tasks):g}" y2="{y:g}" '
            f'stroke="{t["grid"]}" stroke-width="1"/>'
        )
        parts.append(
            _svg_text(axis_w - 8, y + 3.5, str(score), t, _FS_SM, t["chrome"], anchor="end")
        )

    pts = [(cx(i), sy(task.score)) for i, task in enumerate(jr.tasks)]
    if len(pts) > 1:
        d = f"M {pts[0][0]:.1f},{pts[0][1]:.1f}"
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            mx = (x0 + x1) / 2
            d += f" C {mx:.1f},{y0:.1f} {mx:.1f},{y1:.1f} {x1:.1f},{y1:.1f}"
        parts.append(
            f'<path d="{d}" fill="none" stroke="{t["ink2"]}" stroke-width="2" stroke-linecap="round"/>'
        )
    for (px, py), task in zip(pts, jr.tasks):
        color = _SCORE_COLORS[int(round(task.score))]
        parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="9" fill="{color}" stroke="{t["surface"]}" stroke-width="2"/>'
        )
        parts.append(
            _svg_text(px, py + 3.6, f"{task.score:g}", t, 10, _text_on(color, t), 700, "middle")
        )

    # Actors under each task, then a legend
    actor_y = track_y + track_h + 22
    for i, task in enumerate(jr.tasks):
        n = len(task.actors)
        for k, a in enumerate(task.actors):
            ax = cx(i) + (k - (n - 1) / 2) * 13
            parts.append(
                f'<circle cx="{ax:.1f}" cy="{actor_y:g}" r="4.5" fill="{actor_color[a]}"/>'
            )
    height = actor_y + 10
    if actors:
        lx, ly = axis_w, actor_y + 24
        for a in actors:
            parts.append(
                f'<circle cx="{lx + 5:g}" cy="{ly - 4:g}" r="4.5" fill="{actor_color[a]}"/>'
            )
            parts.append(_svg_text(lx + 14, ly, a, t, _FS_SM, t["ink2"]))
            lx += 14 + _text_w(a, _FS_SM) + 18
        height = ly + 8
    width = axis_w + col_w * len(jr.tasks) + 4
    return _svg_root(width, height, parts, t["font"])


def parse_git(source: str) -> GitGraph:
    """Parse a Mermaid gitGraph into commits on branches."""
    gg = GitGraph()
    branches: dict[str, list[str]] = {"main": []}  # branch -> commit ids
    gg.branches = ["main"]
    current = "main"
    seq = 0

    def quoted(text: str) -> dict[str, str]:
        out = {k.lower(): v for k, v in re.findall(r'(\w+):\s*"([^"]*)"', text)}
        for k, v in re.findall(r"(\w+):\s*([A-Za-z0-9_-]+)(?=\s|$)", text):
            out.setdefault(k.lower(), v)
        return out

    def add(branch: str, parents: list[str], o: dict[str, str], kind: str = "normal") -> None:
        nonlocal seq
        cid = o.get("id") or f"c{seq}"
        commit_type = o.get("type", "").upper()
        gg.commits.append(
            GitCommit(
                cid,
                branch,
                [p for p in parents if p],
                o.get("tag", ""),
                (
                    kind
                    if kind != "normal"
                    else (
                        commit_type.lower() if commit_type in ("HIGHLIGHT", "REVERSE") else "normal"
                    )
                ),
                seq,
                o.get("msg", ""),
                "id" in o,
            )
        )
        branches.setdefault(branch, []).append(cid)
        seq += 1

    def head(branch: str) -> str:
        return branches[branch][-1] if branches.get(branch) else gg.branch_base.get(branch, "")

    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        m = re.match(r"^gitGraph\s*(LR|TB|BT)?\s*:?\s*$", line, re.IGNORECASE)
        if m:
            if m.group(1):
                gg.direction = m.group(1).upper()
            continue
        if re.match(r"^commit\b", line):
            add(current, [head(current)], quoted(line))
            continue
        m = re.match(r"^branch\s+(\S+)(.*)$", line)
        if m:
            name = m.group(1)
            if name not in gg.branches:
                gg.branches.append(name)
                order = quoted(m.group(2)).get("order")
                if order and order.lstrip("-").isdigit():
                    gg.order[name] = int(order)
            gg.branch_base[name] = head(current)
            branches.setdefault(name, [])
            current = name
            continue
        m = re.match(r"^(?:checkout|switch)\s+(\S+)", line)
        if m:
            current = m.group(1)
            if current not in gg.branches:
                gg.branches.append(current)
                branches.setdefault(current, [])
            continue
        m = re.match(r"^merge\s+(\S+)(.*)$", line)
        if m:
            add(current, [head(current), head(m.group(1))], quoted(m.group(2)), "merge")
            continue
        m = re.match(r"^cherry-pick\s+(.*)$", line)
        if m:
            o = quoted(m.group(1))
            src = o.pop("id", "")
            o.pop("parent", None)
            gg.cherry_sources[seq] = src
            o.setdefault("tag", "")
            add(current, [head(current)], o, "cherry")
            continue
    return gg


def render_git_svg(gg: GitGraph, theme: dict[str, str] | None = None) -> str:
    """Render a git graph: one lane per branch, commits along a shared timeline."""
    t = _tokens(theme)
    if not gg.commits:
        return _svg_root(120, 40, _svg_text(0, 20, "No commits", t, color=t["ink2"]), t["font"])
    lanes = sorted(gg.branches, key=lambda b: (gg.order.get(b, 0), gg.branches.index(b)))
    used = {c.branch for c in gg.commits} | set(gg.branch_base)
    lanes = [b for b in lanes if b in used or b == "main"]
    color = {b: _palette(t)[i % 8] for i, b in enumerate(lanes)}
    vertical = gg.direction in ("TB", "BT")

    pill_w = max(_text_w(b, 11, 600) for b in lanes) + 16
    step = 54.0
    lane_gap = max(46.0, pill_w + 14) if vertical else 46.0
    major0 = 44.0 if vertical else pill_w + 32
    has_tags = any(c.tag for c in gg.commits)
    minor0 = pill_w / 2 + 4 if vertical else (44.0 if has_tags else 26.0)
    by_id = {c.id: c for c in gg.commits}

    def pos(c: GitCommit) -> tuple[float, float]:
        major = major0 + c.seq * step
        minor = minor0 + lanes.index(c.branch) * lane_gap
        return (minor, major) if vertical else (major, minor)

    parts: list[str] = []
    # Branch rails: from the branch point (or first commit) to the last commit on the lane
    for b in lanes:
        commits = [c for c in gg.commits if c.branch == b]
        if not commits:
            continue
        first, last = pos(commits[0]), pos(commits[-1])
        lane_minor = first[0] if vertical else first[1]
        start_major = first[1] if vertical else first[0]
        end_major = last[1] if vertical else last[0]
        if vertical:
            parts.append(
                f'<line x1="{lane_minor:g}" y1="{start_major:g}" x2="{lane_minor:g}" y2="{end_major:g}" '
                f'stroke="{color[b]}" stroke-width="2.5" stroke-linecap="round"/>'
            )
        else:
            parts.append(
                f'<line x1="{start_major:g}" y1="{lane_minor:g}" x2="{end_major:g}" y2="{lane_minor:g}" '
                f'stroke="{color[b]}" stroke-width="2.5" stroke-linecap="round"/>'
            )

    # Branch-off and merge links between lanes (rounded elbows)
    r = 10.0
    for c in gg.commits:
        cx_, cy_ = pos(c)
        for k, pid in enumerate(c.parents):
            p = by_id.get(pid)
            if p is None or p.branch == c.branch and k == 0:
                continue
            px_, py_ = pos(p)
            if vertical:
                # mirror of the horizontal case
                if k == 0:  # first commit on a new branch: leave the parent lane, turn, run down
                    sgn = 1 if cx_ > px_ else -1
                    d = f"M {px_:g},{py_:g} V {cy_ - step / 2 - r:g} Q {px_:g},{cy_ - step / 2:g} {px_ + sgn * r:g},{cy_ - step / 2:g} H {cx_ - sgn * r:g} Q {cx_:g},{cy_ - step / 2:g} {cx_:g},{cy_ - step / 2 + r:g} V {cy_:g}"
                    stroke = color[c.branch]
                else:
                    sgn = 1 if cx_ > px_ else -1
                    d = f"M {px_:g},{py_:g} V {cy_ - r:g} Q {px_:g},{cy_:g} {px_ + sgn * r:g},{cy_:g} H {cx_:g}"
                    stroke = color[p.branch]
            else:
                if k == 0:
                    sgn = 1 if cy_ > py_ else -1
                    d = f"M {px_:g},{py_:g} H {cx_ - step / 2 - r:g} Q {cx_ - step / 2:g},{py_:g} {cx_ - step / 2:g},{py_ + sgn * r:g} V {cy_ - sgn * r:g} Q {cx_ - step / 2:g},{cy_:g} {cx_ - step / 2 + r:g},{cy_:g} H {cx_:g}"
                    stroke = color[c.branch]
                else:
                    sgn = 1 if cy_ > py_ else -1
                    d = f"M {px_:g},{py_:g} H {cx_ - r:g} Q {cx_:g},{py_:g} {cx_:g},{py_ + sgn * r:g} V {cy_:g}"
                    stroke = color[p.branch]
            parts.append(
                f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="2.5" stroke-linecap="round"/>'
            )
        if c.kind == "cherry":
            src = by_id.get(gg.cherry_sources.get(c.seq, ""))
            if src is not None:
                sx_, sy_ = pos(src)
                parts.append(
                    f'<path d="M {sx_:g},{sy_:g} Q {(sx_ + cx_) / 2:g},{min(sy_, cy_) - 20:g} {cx_:g},{cy_:g}" '
                    f'fill="none" stroke="{t["chrome"]}" stroke-width="1.25" stroke-dasharray="4 3"/>'
                )

    # Commits, ids and tags
    for c in gg.commits:
        x, y = pos(c)
        col = color[c.branch]
        if c.kind == "highlight":
            parts.append(
                f'<rect x="{x - 7:g}" y="{y - 7:g}" width="14" height="14" rx="3" fill="{col}" '
                f'stroke="{t["surface"]}" stroke-width="2"/>'
            )
        else:
            parts.append(
                f'<circle cx="{x:g}" cy="{y:g}" r="7.5" fill="{col}" stroke="{t["surface"]}" stroke-width="2"/>'
            )
        if c.kind == "merge":
            parts.append(f'<circle cx="{x:g}" cy="{y:g}" r="3" fill="{t["surface"]}"/>')
        elif c.kind == "reverse":
            parts.append(
                f'<path d="M {x - 3.5:g},{y - 3.5:g} L {x + 3.5:g},{y + 3.5:g} M {x + 3.5:g},{y - 3.5:g} '
                f'L {x - 3.5:g},{y + 3.5:g}" stroke="{t["surface"]}" stroke-width="1.6"/>'
            )
        elif c.kind == "cherry":
            parts.append(f'<circle cx="{x:g}" cy="{y:g}" r="2.5" fill="{t["surface"]}"/>')
        caption = c.msg or (c.id if c.explicit_id else "")
        if caption:
            if vertical:
                parts.append(_svg_text(x + 14, y + 4, caption, t, 10, t["ink2"]))
            else:
                parts.append(_svg_text(x, y + 22, caption, t, 10, t["ink2"], anchor="middle"))
        if c.tag:
            tw = _text_w(c.tag, 9.5, 600) + 12
            tx, ty = (x - tw - 12, y - 8) if vertical else (x - tw / 2, y - 29)
            parts.append(
                f'<rect x="{tx:g}" y="{ty:g}" width="{tw:g}" height="16" rx="8" fill="{t["card"]}" '
                f'stroke="{t["baseline"]}" stroke-width="1"/>'
            )
            parts.append(_svg_text(tx + tw / 2, ty + 11.5, c.tag, t, 9.5, t["ink2"], 600, "middle"))

    # Branch name pills at the start of each lane
    for i, b in enumerate(lanes):
        minor = minor0 + i * lane_gap
        bw = _text_w(b, 11, 600) + 16
        if vertical:
            bx, by_ = minor - bw / 2, 0.0
        else:
            bx, by_ = 0.0, minor - 10
        parts.append(
            f'<rect x="{bx:g}" y="{by_:g}" width="{bw:g}" height="20" rx="10" '
            f'fill="{_tint(color[b], 0.82, t)}" stroke="{_tint(color[b], 0.3, t)}" stroke-width="1"/>'
        )
        parts.append(_svg_text(bx + bw / 2, by_ + 14, b, t, 11, t["ink"], 600, "middle"))

    major_end = major0 + max(c.seq for c in gg.commits) * step + 40
    minor_end = minor0 + (len(lanes) - 1) * lane_gap + 30
    if vertical:
        return _svg_root(minor_end + 90, major_end, parts, t["font"])
    return _svg_root(major_end + 30, minor_end, parts, t["font"])


def _config_section(name: str) -> dict:
    """The ``config.<name>`` block of the diagram being rendered (empty if none)."""
    section = _ACTIVE_CONFIG.get().get(name)
    return section if isinstance(section, dict) else {}


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


# ---------------------------------------------------------------------------
# Quadrant chart
# ---------------------------------------------------------------------------


def parse_quadrant(source: str) -> QuadrantChart:
    """Parse a Mermaid quadrantChart."""
    qc = QuadrantChart()
    classes: dict[str, dict[str, str]] = {}
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^quadrantChart\b", line, re.I):
            continue
        m = re.match(r"^title\s+(.+)$", line, re.I)
        if m:
            qc.title = _unquote(m.group(1))
            continue
        m = re.match(r"^([xy])-axis\s+(.+?)(?:\s*-->\s*(.+))?$", line, re.I)
        if m:
            low, high = _unquote(m.group(2)), _unquote(m.group(3) or "")
            if m.group(1).lower() == "x":
                qc.x_low, qc.x_high = low, high
            else:
                qc.y_low, qc.y_high = low, high
            continue
        m = re.match(r"^quadrant-([1-4])\s+(.+)$", line, re.I)
        if m:
            qc.quadrants[int(m.group(1)) - 1] = _unquote(m.group(2))
            continue
        m = re.match(r"^classDef\s+(\S+)\s+(.+)$", line)
        if m:
            classes[m.group(1)] = _parse_css(m.group(2).replace(" :", ":"))
            continue
        m = re.match(
            r"^(.+?)(?::::(\w+))?\s*:\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]\s*(.*)$", line
        )
        if m:
            style = dict(classes.get(m.group(2) or "", {}))
            style.update(_parse_css(m.group(5)))
            qc.points.append(
                (
                    _unquote(m.group(1)),
                    float(m.group(3)),
                    float(m.group(4)),
                    style,
                    m.group(2) or "",
                )
            )
    # classDefs may follow the points that use them
    qc.points = [
        (name, x, y, {**classes.get(cls, {}), **style} if cls else style, cls)
        for name, x, y, style, cls in qc.points
    ]
    return qc


def render_quadrant_svg(qc: QuadrantChart, theme: dict[str, str] | None = None) -> str:
    """Render a quadrant chart: four tinted quadrants, axis labels and labelled points."""
    t = _tokens(theme)
    conf = _config_section("quadrantChart")
    parts, top = _chart_title(qc.title, t)
    size_w = float(conf.get("chartWidth", 380))
    size_h = float(conf.get("chartHeight", 380))
    axis_pad = 26.0
    x0, y0 = axis_pad, top + 4
    hw, hh = size_w / 2, size_h / 2
    tints = [
        _tint(t["primary"], 0.8, t),  # 1: top right
        _tint(t["primary"], 0.89, t),  # 2: top left
        _tint(t["primary"], 0.95, t),  # 3: bottom left
        _tint(t["primary"], 0.89, t),  # 4: bottom right
    ]
    boxes = [(x0 + hw, y0), (x0, y0), (x0, y0 + hh), (x0 + hw, y0 + hh)]
    for (bx, by), fill in zip(boxes, tints):
        parts.append(f'<rect x="{bx:g}" y="{by:g}" width="{hw:g}" height="{hh:g}" fill="{fill}"/>')
    # Surface gap between the quadrants
    parts.append(
        f'<path d="M {x0 + hw:g},{y0:g} V {y0 + size_h:g} M {x0:g},{y0 + hh:g} H {x0 + size_w:g}" '
        f'stroke="{t["surface"]}" stroke-width="2"/>'
    )
    for (bx, by), text in zip(boxes, qc.quadrants):
        if text:
            parts.append(_svg_text(bx + hw / 2, by + 20, text, t, _FS, t["ink2"], 600, "middle"))

    # Axis labels: x under each half, y beside each half (rotated)
    for text, cx in ((qc.x_low, x0 + hw / 2), (qc.x_high, x0 + hw * 1.5)):
        if text:
            parts.append(
                _svg_text(cx, y0 + size_h + 18, text, t, _FS_SM, t["ink2"], anchor="middle")
            )
    for text, cy in ((qc.y_low, y0 + hh * 1.5), (qc.y_high, y0 + hh / 2)):
        if text:
            parts.append(
                _svg_text(
                    0,
                    0,
                    text,
                    t,
                    _FS_SM,
                    t["ink2"],
                    anchor="middle",
                    extra=f' transform="translate({axis_pad - 10:g},{cy:g}) rotate(-90)"',
                )
            )

    placed: list[tuple[float, float, float, float]] = []

    def clear(box: tuple[float, float, float, float]) -> bool:
        bx0, by0, bx1, by1 = box
        inside = bx0 >= x0 and bx1 <= x0 + size_w and by0 >= y0 and by1 <= y0 + size_h
        return inside and all(
            bx1 <= c0 or bx0 >= c1 or by1 <= d0 or by0 >= d1 for c0, d0, c1, d1 in placed
        )

    marks = []
    for name, px, py, style, _cls in qc.points:
        cx = x0 + max(0.0, min(1.0, px)) * size_w
        cy = y0 + (1 - max(0.0, min(1.0, py))) * size_h
        r = float(re.sub(r"[^\d.]", "", str(style.get("radius", "5"))) or 5)
        marks.append((name, cx, cy, r, style))
        placed.append((cx - r, cy - r, cx + r, cy + r))  # labels avoid every dot
    for name, cx, cy, r, style in marks:
        fill = style.get("color", t["term_fill"])
        if fill and not fill.startswith("#") and re.fullmatch(r"[0-9a-fA-F]{6}", fill):
            fill = "#" + fill
        ring = style.get("stroke-color", t["surface"])
        ring_w = re.sub(r"[^\d.]", "", str(style.get("stroke-width", "2"))) or "2"
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:g}" fill="{fill}" stroke="{ring}" '
            f'stroke-width="{ring_w}"/>'
        )
        w = _text_w(name, 11)
        candidates = [
            (cx + r + 5, cy + 4, "start", (cx + r + 3, cy - 8, cx + r + 7 + w, cy + 6)),
            (cx - r - 5, cy + 4, "end", (cx - r - 7 - w, cy - 8, cx - r - 3, cy + 6)),
            (cx, cy - r - 6, "middle", (cx - w / 2 - 2, cy - r - 18, cx + w / 2 + 2, cy - r - 3)),
            (cx, cy + r + 14, "middle", (cx - w / 2 - 2, cy + r + 2, cx + w / 2 + 2, cy + r + 17)),
        ]
        choice = next((c for c in candidates if clear(c[3])), candidates[0])
        placed.append(choice[3])
        parts.append(_svg_text(choice[0], choice[1], name, t, 11, t["ink"], anchor=choice[2]))
    return _svg_root(x0 + size_w + 6, y0 + size_h + 28, parts, t["font"])


# ---------------------------------------------------------------------------
# Sankey
# ---------------------------------------------------------------------------


def parse_sankey(source: str) -> Sankey:
    """Parse ``sankey`` CSV rows (source,target,value; RFC 4180 quoting)."""
    import csv

    sk = Sankey()
    rows = [
        line
        for line in source.strip().splitlines()
        if line.strip()
        and not line.strip().startswith("%%")
        and not re.match(r"^\s*sankey(-beta)?\s*$", line, re.I)
    ]
    for rec in csv.reader(rows):
        if len(rec) < 3:
            continue
        try:
            value = float(rec[2])
        except ValueError:
            continue
        sk.links.append((rec[0].strip(), rec[1].strip(), value))
    return sk


def render_sankey_svg(sk: Sankey, theme: dict[str, str] | None = None) -> str:
    """Render a sankey: proportional nodes in columns joined by flow bands."""
    t = _tokens(theme)
    conf = _config_section("sankey")
    if not sk.links:
        return _svg_root(120, 40, _svg_text(0, 20, "No flows", t, color=t["ink2"]), t["font"])
    nodes: list[str] = []
    for a, b, _ in sk.links:
        for n in (a, b):
            if n not in nodes:
                nodes.append(n)
    outs: dict[str, list[tuple[str, float]]] = defaultdict(list)
    ins: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for a, b, v in sk.links:
        outs[a].append((b, v))
        ins[b].append((a, v))
    # Columns by longest path from a source
    layer: dict[str, int] = {n: 0 for n in nodes}
    for _ in range(len(nodes)):
        changed = False
        for a, b, _v in sk.links:
            if layer[b] < layer[a] + 1:
                layer[b] = layer[a] + 1
                changed = True
        if not changed:
            break
    last = max(layer.values())
    align = str(conf.get("nodeAlignment", "justify"))
    if align in ("justify", "right"):
        for n in nodes:
            if not outs[n]:
                layer[n] = last  # sinks line up on the right
    value = {n: max(sum(v for _, v in outs[n]), sum(v for _, v in ins[n])) for n in nodes}
    columns: dict[int, list[str]] = defaultdict(list)
    for n in nodes:
        columns[layer[n]].append(n)

    node_w = float(conf.get("nodeWidth", 10))
    pad = float(conf.get("nodePadding", 12))
    height = 340.0
    show_values = conf.get("showValues", True) is not False
    ky = min(
        (height - pad * (len(col) - 1)) / max(sum(value[n] for n in col), 1e-9)
        for col in columns.values()
    )
    label_w = max(_text_w(n, 11.5) for n in nodes) + 12
    col_gap = max(110.0, min(220.0, (600 - label_w) / max(last, 1)))
    x_of = {c: c * col_gap for c in columns}

    pos: dict[str, list[float]] = {}  # node -> [x, y, h]
    for c in sorted(columns):
        col = columns[c]
        if c > 0:  # order by the weighted centre of incoming flows

            def centre(n: str) -> float:
                srcs = [(pos[a][1] + pos[a][2] / 2, v) for a, v in ins[n] if a in pos]
                return (
                    sum(y * v for y, v in srcs) / max(sum(v for _, v in srcs), 1e-9)
                    if srcs
                    else 0.0
                )

            col.sort(key=centre)
        total = sum(value[n] * ky for n in col) + pad * (len(col) - 1)
        y = (height - total) / 2
        for n in col:
            h = max(value[n] * ky, 2.0)
            pos[n] = [x_of[c], y, h]
            y += h + pad

    palette = _palette(t)
    node_colors = conf.get("nodeColors")
    custom: dict = node_colors if isinstance(node_colors, dict) else {}
    color = {n: str(custom.get(n) or palette[i % len(palette)]) for i, n in enumerate(nodes)}
    link_mode = str(conf.get("linkColor", "source"))

    parts: list[str] = []
    out_off = {n: 0.0 for n in nodes}
    in_off = {n: 0.0 for n in nodes}
    order = sorted(sk.links, key=lambda link: (pos[link[0]][1], pos[link[1]][1]))
    for a, b, v in order:
        w = v * ky
        x0 = pos[a][0] + node_w
        x1 = pos[b][0]
        y0 = pos[a][1] + out_off[a]
        y1 = pos[b][1] + in_off[b]
        out_off[a] += w
        in_off[b] += w
        xm = (x0 + x1) / 2
        fill = (
            color[b]
            if link_mode == "target"
            else link_mode if link_mode.startswith("#") else color[a]
        )
        parts.append(
            f'<path d="M {x0:.1f},{y0:.1f} C {xm:.1f},{y0:.1f} {xm:.1f},{y1:.1f} {x1:.1f},{y1:.1f} '
            f'L {x1:.1f},{y1 + w:.1f} C {xm:.1f},{y1 + w:.1f} {xm:.1f},{y0 + w:.1f} {x0:.1f},{y0 + w:.1f} Z" '
            f'fill="{fill}" fill-opacity="0.32"/>'
        )
    for n in nodes:
        x, y, h = pos[n]
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{node_w:g}" height="{h:.1f}" rx="2" fill="{color[n]}"/>'
        )
        on_right = layer[n] < last
        tx = x + node_w + 6 if on_right else x - 6
        anchor = "start" if on_right else "end"
        parts.append(
            _svg_text(tx, y + h / 2 + (0 if show_values else 4), n, t, 11.5, anchor=anchor)
        )
        if show_values:
            parts.append(
                _svg_text(
                    tx, y + h / 2 + 13, _fmt_num(value[n]), t, _FS_SM, t["ink2"], anchor=anchor
                )
            )
    # Labels sit right of their node, except the last column's, which sit to its left
    width = x_of[last] + node_w
    for n in nodes:
        if layer[n] < last:
            width = max(width, pos[n][0] + node_w + 6 + _text_w(n, 11.5))
    return _svg_root(width + 6, height + 8, parts, t["font"])


# ---------------------------------------------------------------------------
# Radar
# ---------------------------------------------------------------------------


def _ids_with_labels(text: str) -> list[tuple[str, str]]:
    return [
        (m.group(1), m.group(2) or m.group(1))
        for m in re.finditer(r'(\w+)(?:\s*\[\s*"([^"]*)"\s*\])?', text)
    ]


def parse_radar(source: str) -> Radar:
    """Parse a Mermaid radar-beta chart."""
    rd = Radar()
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^radar(-beta)?\s*$", line, re.I):
            continue
        m = re.match(r"^title\s+(.+)$", line, re.I)
        if m:
            rd.title = _unquote(m.group(1))
            continue
        m = re.match(r"^axis\s+(.+)$", line, re.I)
        if m:
            rd.axes += _ids_with_labels(m.group(1))
            continue
        m = re.match(r"^curve\s+(.+)$", line, re.I)
        if m:
            for cm in re.finditer(r'(\w+)(?:\s*\[\s*"([^"]*)"\s*\])?\s*\{([^}]*)\}', m.group(1)):
                body = cm.group(3)
                if ":" in body:
                    pairs = dict(
                        (k.strip(), float(v))
                        for k, v in (p.split(":", 1) for p in body.split(",") if ":" in p)
                    )
                    values = [pairs.get(aid, 0.0) for aid, _ in rd.axes]
                else:
                    values = [float(v) for v in body.split(",") if v.strip()]
                rd.curves.append((cm.group(2) or cm.group(1), values))
            continue
        m = re.match(r"^(max|min|ticks)\s+(-?[\d.]+)$", line, re.I)
        if m:
            key, num = m.group(1).lower(), float(m.group(2))
            if key == "max":
                rd.max_val = num
            elif key == "min":
                rd.min_val = num
            else:
                rd.ticks = max(1, int(num))
            continue
        m = re.match(r"^graticule\s+(circle|polygon)$", line, re.I)
        if m:
            rd.graticule = m.group(1).lower()
            continue
        m = re.match(r"^showLegend\s+(true|false)$", line, re.I)
        if m:
            rd.show_legend = m.group(1).lower() == "true"
    return rd


def render_radar_svg(rd: Radar, theme: dict[str, str] | None = None) -> str:
    """Render a radar chart: graticule, axes, translucent curves and a legend."""
    t = _tokens(theme)
    n = len(rd.axes)
    if n < 3 or not rd.curves:
        return _svg_root(
            160, 40, _svg_text(0, 20, "Needs 3+ axes and a curve", t, color=t["ink2"]), t["font"]
        )
    parts, top = _chart_title(rd.title, t)
    hi = rd.max_val if rd.max_val is not None else max(max(v) for _, v in rd.curves if v)
    lo = rd.min_val
    r = 120.0
    label_w = max(_text_w(lbl, 11.5) for _, lbl in rd.axes)
    cx, cy = r + label_w + 14, top + r + 22

    def point(i: int, value: float) -> tuple[float, float]:
        a = -math.pi / 2 + 2 * math.pi * i / n
        f = (value - lo) / ((hi - lo) or 1)
        return cx + r * f * math.cos(a), cy + r * f * math.sin(a)

    for k in range(1, rd.ticks + 1):
        level = lo + (hi - lo) * k / rd.ticks
        if rd.graticule == "circle":
            parts.append(
                f'<circle cx="{cx:g}" cy="{cy:g}" r="{r * k / rd.ticks:.1f}" fill="none" '
                f'stroke="{t["grid"]}" stroke-width="1"/>'
            )
        else:
            ring = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(i, level) for i in range(n)))
            parts.append(
                f'<polygon points="{ring}" fill="none" stroke="{t["grid"]}" stroke-width="1"/>'
            )
        tx, ty = point(0, level)
        parts.append(_svg_text(tx + 4, ty + 3, _fmt_num(level), t, 9, t["chrome"]))
    for i, (_aid, label) in enumerate(rd.axes):
        ex, ey = point(i, hi)
        parts.append(
            f'<line x1="{cx:g}" y1="{cy:g}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{t["grid"]}" stroke-width="1"/>'
        )
        lx, ly = point(i, hi + (hi - lo) * 0.1)
        anchor = "middle" if abs(lx - cx) < 4 else "start" if lx > cx else "end"
        parts.append(_svg_text(lx, ly + 4, label, t, 11.5, t["ink2"], anchor=anchor))
    palette = _palette(t)
    for k, (_label, values) in enumerate(rd.curves):
        color = palette[k % len(palette)]
        pts = [point(i, values[i] if i < len(values) else lo) for i in range(n)]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        parts.append(
            f'<polygon points="{poly}" fill="{color}" fill-opacity="0.12" stroke="{color}" '
            f'stroke-width="2" stroke-linejoin="round"/>'
        )
        for x, y in pts:
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}" stroke="{t["surface"]}" stroke-width="1.5"/>'
            )
    width = cx + r + label_w + 14
    height = cy + r + 26
    if rd.show_legend and len(rd.curves) > 1:
        lx, ly = 0.0, height + 4
        for k, (label, _v) in enumerate(rd.curves):
            color = palette[k % len(palette)]
            parts.append(
                f'<rect x="{lx:g}" y="{ly - 9:g}" width="10" height="10" rx="2.5" fill="{color}"/>'
            )
            parts.append(_svg_text(lx + 16, ly, label, t, _FS_SM, t["ink2"]))
            lx += 16 + _text_w(label, _FS_SM) + 18
        height += 22
    return _svg_root(width, height, parts, t["font"])


# ---------------------------------------------------------------------------
# Treemap
# ---------------------------------------------------------------------------


def parse_treemap(source: str) -> TreeItem:
    """Parse a treemap-beta hierarchy (indentation; leaves carry ``: value``)."""
    root = TreeItem("")
    stack: list[tuple[int, TreeItem]] = [(-1, root)]
    for raw_line in source.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("%%"):
            continue
        stripped = raw_line.strip()
        if re.match(r"^treemap(-beta)?\s*$", stripped, re.I) or stripped.startswith("classDef "):
            continue
        indent = len(raw_line.expandtabs(4)) - len(raw_line.expandtabs(4).lstrip())
        m = re.match(r'^"([^"]*)"(?::::\w+)?\s*(?::\s*(-?[\d.]+))?(?::::\w+)?\s*$', stripped)
        if not m:
            continue
        item = TreeItem(m.group(1), float(m.group(2)) if m.group(2) else None)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack[-1][1].children.append(item)
        stack.append((indent, item))
    return root


def _tree_total(item: TreeItem) -> float:
    if item.children:
        return sum(_tree_total(c) for c in item.children)
    return max(item.value or 0.0, 0.0)


def _squarify(
    values: list[float], x: float, y: float, w: float, h: float
) -> list[tuple[float, float, float, float]]:
    """Squarified treemap layout of ``values`` (already sorted descending) in a rectangle."""
    rects: list[tuple[float, float, float, float]] = []
    total = sum(values)
    if total <= 0 or w <= 0 or h <= 0:
        return [(x, y, 0.0, 0.0) for _ in values]
    scale = w * h / total
    areas = [v * scale for v in values]

    def worst(row: list[float], side: float) -> float:
        s = sum(row)
        return (
            max(max(side * side * a / (s * s), (s * s) / (side * side * a)) for a in row)
            if s
            else 1e9
        )

    i = 0
    while i < len(areas):
        side = min(w, h)
        row = [areas[i]]
        i += 1
        while i < len(areas) and worst(row + [areas[i]], side) <= worst(row, side):
            row.append(areas[i])
            i += 1
        s = sum(row)
        if w >= h:  # lay the row as a column on the left
            cw = s / h
            yy = y
            for a in row:
                rects.append((x, yy, cw, a / cw))
                yy += a / cw
            x, w = x + cw, w - cw
        else:
            rh = s / w
            xx = x
            for a in row:
                rects.append((xx, y, a / rh, rh))
                xx += a / rh
            y, h = y + rh, h - rh
    return rects


def render_treemap_svg(root: TreeItem, theme: dict[str, str] | None = None) -> str:
    """Render a squarified treemap: groups by colour, leaves sized by value."""
    t = _tokens(theme)
    conf = _config_section("treemap")
    if not root.children or _tree_total(root) <= 0:
        return _svg_root(120, 40, _svg_text(0, 20, "No values", t, color=t["ink2"]), t["font"])
    width, height = 600.0, 360.0
    palette = _palette(t)
    fmt = str(conf.get("valueFormat", ","))
    parts: list[str] = []

    def fmt_value(v: float) -> str:
        if "%" in fmt:
            return f"{v * 100:.1f}%" if ".1" in fmt else f"{v * 100:.0f}%"
        prefix = "$" if "$" in fmt else ""
        if ".2f" in fmt:
            return f"{prefix}{v:,.2f}"
        return f"{prefix}{v:,.0f}" if float(v).is_integer() or "," in fmt else f"{prefix}{v:g}"

    def draw(
        items: list[TreeItem], x: float, y: float, w: float, h: float, depth: int, color: str | None
    ) -> None:
        items = sorted((it for it in items if _tree_total(it) > 0), key=_tree_total, reverse=True)
        rects = _squarify([_tree_total(it) for it in items], x, y, w, h)
        for k, (item, (rx, ry, rw, rh)) in enumerate(zip(items, rects)):
            base = color or palette[k % len(palette)]
            gap = 1.5
            bx, by, bw, bh = rx + gap, ry + gap, max(rw - 2 * gap, 0), max(rh - 2 * gap, 0)
            if item.children:
                head = 20.0 if bh > 34 else 0.0
                parts.append(
                    f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="4" '
                    f'fill="{_tint(base, 0.86 if depth == 0 else 0.78, t)}"/>'
                )
                if head and bw > _text_w(item.name, 11, 600) + 12:
                    parts.append(_svg_text(bx + 7, by + 14, item.name, t, 11, t["ink"], 600))
                draw(item.children, bx + 3, by + head + 1, bw - 6, bh - head - 4, depth + 1, base)
            else:
                fill = _tint(base, 0.55 if depth == 0 else 0.62, t)
                parts.append(
                    f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" fill="{fill}"/>'
                )
                ink = _text_on(fill, t)
                name_fits = bw > _text_w(item.name, 11) + 12 and bh > 20
                if name_fits:
                    parts.append(_svg_text(bx + 7, by + 16, item.name, t, 11, ink, 600))
                    if bh > 36:
                        parts.append(
                            _svg_text(bx + 7, by + 31, fmt_value(item.value or 0.0), t, _FS_SM, ink)
                        )

    draw(root.children, 0, 0, width, height, 0, None)
    return _svg_root(width, height, parts, t["font"])


# ---------------------------------------------------------------------------
# Packet
# ---------------------------------------------------------------------------


def parse_packet(source: str) -> Packet:
    """Parse a packet diagram: ``start-end: "label"``, ``start: "label"`` or ``+bits: "label"``."""
    pk = Packet()
    nxt = 0
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^packet(-beta)?\s*$", line, re.I):
            continue
        m = re.match(r"^title\s+(.+)$", line, re.I)
        if m:
            pk.title = _unquote(m.group(1))
            continue
        m = re.match(r'^(?:(\d+)(?:\s*-\s*(\d+))?|\+(\d+))\s*:\s*"([^"]*)"', line)
        if m:
            if m.group(3):
                start = nxt
                end = start + int(m.group(3)) - 1
            else:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else start
            pk.fields.append((start, end, m.group(4)))
            nxt = end + 1
    return pk


def render_packet_svg(pk: Packet, theme: dict[str, str] | None = None) -> str:
    """Render a packet layout: fixed-width bit rows with labelled fields."""
    t = _tokens(theme)
    conf = _config_section("packet")
    if not pk.fields:
        return _svg_root(120, 40, _svg_text(0, 20, "No fields", t, color=t["ink2"]), t["font"])
    per_row = int(conf.get("bitsPerRow", 32))
    show_bits = conf.get("showBits", True) is not False
    descending = str(conf.get("bitOrder", "ascending")).lower() == "descending"
    bit_w = min(18.0, 600.0 / per_row)
    row_h = 34.0
    bits_h = 14.0 if show_bits else 0.0
    parts, top = _chart_title(pk.title, t)
    last_bit = max(end for _, end, _ in pk.fields)
    rows = last_bit // per_row + 1

    def bx(bit: int) -> float:
        col = bit % per_row
        if descending:
            col = per_row - 1 - col
        return col * bit_w

    for start, end, label in pk.fields:
        bit = start
        while bit <= end:
            row = bit // per_row
            seg_end = min(end, (row + 1) * per_row - 1)
            a, b = bx(bit), bx(seg_end)
            x0, x1 = min(a, b), max(a, b) + bit_w
            y = top + row * (row_h + bits_h) + bits_h
            parts.append(
                f'<rect x="{x0 + 1:g}" y="{y:g}" width="{x1 - x0 - 2:g}" height="{row_h:g}" rx="3" '
                f'fill="{t["node_fill"]}" stroke="{t["node_stroke"]}" stroke-width="1"/>'
            )
            text = label if bit == start else f"{label} (cont.)"
            room = x1 - x0 - 8
            if _text_w(text, 11) > room and _text_w(text, 9.5) <= row_h - 6:
                # Narrow field: run the label up the field instead of clipping it
                mx, my = (x0 + x1) / 2 + 3.5, y + row_h / 2
                rotate = f' transform="translate({mx:g},{my:g}) rotate(-90)"'
                parts.append(_svg_text(0, 0, text, t, 9.5, anchor="middle", extra=rotate))
                text = ""
            while text and _text_w(text, 11) > room:
                text = text[:-2] + "…" if len(text) > 2 else ""
            if text:
                parts.append(
                    _svg_text((x0 + x1) / 2, y + row_h / 2 + 4, text, t, 11, anchor="middle")
                )
            if show_bits:
                parts.append(
                    _svg_text(
                        min(a, b) + 2 if not descending else max(a, b) + bit_w - 2,
                        y - 3,
                        str(bit),
                        t,
                        8.5,
                        t["chrome"],
                        anchor="start" if not descending else "end",
                    )
                )
                if seg_end != bit:
                    parts.append(
                        _svg_text(
                            max(a, b) + bit_w - 2 if not descending else min(a, b) + 2,
                            y - 3,
                            str(seg_end),
                            t,
                            8.5,
                            t["chrome"],
                            anchor="end" if not descending else "start",
                        )
                    )
            bit = seg_end + 1
    return _svg_root(per_row * bit_w, top + rows * (row_h + bits_h) + 2, parts, t["font"])


_BLOCK_ARROW_DIRS = {"right", "left", "up", "down", "x", "y"}


def _split_tokens(line: str) -> list[str]:
    """Split a block line on whitespace outside brackets and quotes."""
    masked = _mask(line)
    tokens, start = [], None
    for i, ch in enumerate(masked):
        if ch.isspace():
            if start is not None:
                tokens.append(line[start:i])
                start = None
        elif start is None:
            start = i
    if start is not None:
        tokens.append(line[start:])
    return tokens


def parse_block(source: str) -> BlockDiagram:
    """Parse a Mermaid block diagram into nested grid containers."""
    bd = BlockDiagram()
    stack = [bd.root]
    styles: dict[str, dict[str, str]] = defaultdict(dict)
    class_defs: dict[str, dict[str, str]] = {}
    class_assign: list[tuple[list[str], list[str]]] = []
    seen: dict[str, BlockItem] = {}

    def node_item(token: str) -> BlockItem | None:
        span = 1
        m = re.match(r"^(.*?):(\d+)$", token)
        if m and not token.endswith("]") and not token.endswith(")") and not token.endswith("}"):
            token, span = m.group(1), int(m.group(2))
        am = re.match(r'^(\w[\w-]*)(?:<\[\s*"?([^"\]]*)"?\s*\]>)?\(\s*([a-z, ]+)\s*\)$', token)
        if am and all(d.strip() in _BLOCK_ARROW_DIRS for d in am.group(3).split(",")):
            dirs = [d.strip() for d in am.group(3).split(",")]
            return BlockItem(am.group(1), (am.group(2) or "").strip(), "arrow", span, arrow=dirs)
        if token.startswith("space"):
            sm = re.match(r"^space(?::(\d+))?$", token)
            if sm:
                return BlockItem("", "", "space", int(sm.group(1) or span))
        probe = Flowchart()
        nid = _ensure_node(probe, token)
        if nid not in probe.nodes:
            return None
        n = probe.nodes[nid]
        return BlockItem(nid, n.label, "node", span, shape=n.shape, classes=list(n.classes))

    header_seen = False
    for raw_line in source.strip().splitlines():
        line = raw_line.strip().rstrip(";")
        if not line or line.startswith("%%"):
            continue
        if not header_seen:
            header_seen = True
            if re.match(r"^block(-beta)?\s*$", line, re.I):
                continue  # the diagram keyword, not an anonymous nested block
        m = re.match(r"^columns\s+(\d+|auto)$", line, re.I)
        if m:
            stack[-1].columns = 0 if m.group(1).lower() == "auto" else int(m.group(1))
            continue
        m = re.match(r'^block(?::(\w[\w-]*))?(?:\["([^"]*)"\])?(?::(\d+))?$', line)
        if m:
            group = BlockItem(m.group(1) or "", m.group(2) or "", "group", int(m.group(3) or 1))
            if group.id:
                seen[group.id] = group  # edges may target a whole group
            stack[-1].children.append(group)
            stack.append(group)
            continue
        if line == "end":
            if len(stack) > 1:
                stack.pop()
            continue
        m = re.match(r"^style\s+(\S+)\s+(.+)$", line)
        if m:
            for nid in m.group(1).split(","):
                styles[nid.strip()].update(_parse_css(m.group(2)))
            continue
        m = re.match(r"^classDef\s+(\S+)\s+(.+)$", line)
        if m:
            class_defs[m.group(1)] = _parse_css(m.group(2))
            continue
        m = re.match(r"^class\s+(\S+)\s+(\S+)$", line)
        if m:
            class_assign.append((m.group(1).split(","), m.group(2).split(",")))
            continue
        if any(True for _ in _EDGE_RE.finditer(_mask(line))):
            probe = Flowchart()
            _parse_edge_line(probe, line)
            for nid, n in probe.nodes.items():
                if nid in seen:
                    if n.label != nid and seen[nid].kind == "node":
                        seen[nid].label, seen[nid].shape = n.label, n.shape
                else:
                    item = BlockItem(nid, n.label, "node", 1, shape=n.shape)
                    seen[nid] = item
                    stack[-1].children.append(item)
            for e in probe.edges:
                bd.edges.append((e.src, e.dst, e.label, e.head))
            continue
        for token in _split_tokens(line):
            parsed = node_item(token)
            if parsed is None:
                continue
            item = parsed
            if item.kind == "node" and item.id in seen:
                prev = seen[item.id]
                if item.label != item.id:
                    prev.label, prev.shape = item.label, item.shape
                continue
            if item.id and item.kind in ("node", "arrow"):
                seen[item.id] = item
            stack[-1].children.append(item)

    assigned: dict[str, list[str]] = defaultdict(list)
    for ids, names in class_assign:
        for nid in ids:
            assigned[nid.strip()].extend(names)
    for nid, item in seen.items():
        css: dict[str, str] = {}
        for name in [*item.classes, *assigned.get(nid, [])]:
            css.update(class_defs.get(name, {}))
        css.update(styles.get(nid, {}))
        item.css = css
    return bd


def _block_min_size(item: BlockItem) -> tuple[float, float]:
    if item.kind == "space":
        return 0.0, 40.0
    if item.kind == "arrow":
        return 64.0, 44.0
    if item.kind == "group":
        return _layout_block_group(item, measure_only=True)
    lines = re.split(r"<br\s*/?>|\n", item.label)
    w = max(_text_w(x, _FS, 500) for x in lines) + 32
    h = len(lines) * _FS * 1.3 + 22
    if item.shape == "circle":
        w = h = max(w, h)
    elif item.shape == "diamond":
        w, h = w * 1.4, h * 1.4
    elif item.shape in (
        "hexagon",
        "parallelogram",
        "parallelogram_alt",
        "trapezoid",
        "trapezoid_alt",
        "flag",
    ):
        w += 28
    return max(w, 72.0), max(h, 40.0)


def _layout_block_group(group: BlockItem, measure_only: bool = False) -> tuple[float, float]:
    """Grid-place a container's children; returns its (width, height)."""
    gap, pad = 12.0, 12.0 if group.id or group.label or group.kind == "group" else 0.0
    head = 16.0 if group.label else 0.0
    kids = group.children
    columns = group.columns or max(1, sum(k.span for k in kids))
    sizes = [_block_min_size(k) for k in kids]
    cell_w = max([(w - gap * (k.span - 1)) / k.span for k, (w, _) in zip(kids, sizes)] + [40.0])
    rows: list[list[int]] = [[]]
    used = 0
    for i, k in enumerate(kids):
        span = min(k.span, columns)
        if used + span > columns:
            rows.append([])
            used = 0
        rows[-1].append(i)
        used += span
    row_h = [max([sizes[i][1] for i in r] + [0.0]) for r in rows]
    width = columns * cell_w + gap * (columns - 1) + 2 * pad
    height = sum(row_h) + gap * max(len(rows) - 1, 0) + 2 * pad + head
    if measure_only:
        return width, height
    y = pad + head
    for r, h in zip(rows, row_h):
        col = 0
        for i in r:
            k = kids[i]
            span = min(k.span, columns)
            k.x = group.x + pad + col * (cell_w + gap)
            k.w = span * cell_w + gap * (span - 1)
            k.y = group.y + y
            k.h = h
            if k.kind == "group":
                gw, gh = _layout_block_group(k, measure_only=True)
                k.h = max(h, gh)
                _layout_block_group(k)
            col += span
        y += h + gap
    return width, height


def render_block_svg(bd: BlockDiagram, theme: dict[str, str] | None = None) -> str:
    """Render a block diagram on its column grid."""
    t = _tokens(theme)
    if not bd.root.children:
        return _svg_root(120, 40, _svg_text(0, 20, "No blocks", t, color=t["ink2"]), t["font"])
    bd.root.x = bd.root.y = 0.0
    width, height = _layout_block_group(bd.root)
    by_id: dict[str, BlockItem] = {}
    frames: list[str] = []
    parts: list[str] = []

    def walk(item: BlockItem, depth: int) -> None:
        for k in item.children:
            if k.id:
                by_id[k.id] = k
            if k.kind == "group":
                frames.append(
                    f'<rect x="{k.x:g}" y="{k.y:g}" width="{k.w:g}" height="{k.h:g}" rx="8" '
                    f'fill="{_tint(t["primary"], 0.97 - depth * 0.02, t)}" stroke="{t["subgraph_stroke"]}" stroke-width="1"/>'
                )
                if k.label:
                    frames.append(_svg_text(k.x + 10, k.y + 15, k.label, t, _FS_SM, t["ink2"], 600))
                walk(k, depth + 1)
            elif k.kind == "arrow":
                parts.append(_block_arrow(k, t))
            elif k.kind == "node":
                w, h = _block_min_size(k)
                h = min(h, k.h) if k.shape != "circle" else min(k.w, k.h)
                node = Node(
                    k.id, k.label, k.shape, x=k.x, y=k.y + (k.h - h) / 2, w=k.w, h=h, css=k.css
                )
                if k.shape == "circle":
                    d = min(k.w, k.h)
                    node.x, node.w, node.h = k.x + (k.w - d) / 2, d, d
                    node.y = k.y + (k.h - d) / 2
                k.x, k.y, k.w, k.h = node.x, node.y, node.w, node.h
                parts.append(_render_node(node, t))

    walk(bd.root, 0)
    edge_parts = []
    for src, dst, label, head in bd.edges:
        a, b = by_id.get(src), by_id.get(dst)
        if a is None or b is None:
            continue
        na = Node(a.id, "", "rect", x=a.x, y=a.y, w=a.w, h=a.h)
        nb = Node(b.id, "", "rect", x=b.x, y=b.y, w=b.w, h=b.h)
        dx = (b.x + b.w / 2) - (a.x + a.w / 2)
        dy = (b.y + b.h / 2) - (a.y + a.h / 2)
        edge = Edge(src, dst, label, "solid", head)
        edge_parts.append(
            _render_edge(na, nb, label, "LR" if abs(dx) >= abs(dy) else "TD", t, edge=edge)
        )
    # Frames at the back, then edges, then blocks on top
    return _svg_root(width, height, [_make_arrow_defs(t), *frames, *edge_parts, *parts], t["font"])


def _block_arrow(k: BlockItem, t: dict[str, str]) -> str:
    """A fat block arrow (right/left/up/down, or two-headed x/y) filling its cell."""
    cx, cy = k.x + k.w / 2, k.y + k.h / 2
    horizontal = any(d in ("right", "left", "x") for d in k.arrow)
    length = (k.w if horizontal else k.h) - 8
    thick = 16.0
    head = 14.0
    dirs = set(k.arrow)
    both = "x" in dirs or "y" in dirs
    fwd = both or dirs & {"right", "down"}
    back = both or dirs & {"left", "up"}
    a, b = -length / 2, length / 2
    pts = []
    # Build along +axis, then map to the right orientation
    shaft_a = a + (head if back else 0)
    shaft_b = b - (head if fwd else 0)
    pts += [(shaft_a, -thick / 2), (shaft_b, -thick / 2)]
    if fwd:
        pts += [(shaft_b, -thick / 2 - 7), (b, 0.0), (shaft_b, thick / 2 + 7)]
    pts += [(shaft_b, thick / 2), (shaft_a, thick / 2)]
    if back:
        pts += [(shaft_a, thick / 2 + 7), (a, 0.0), (shaft_a, -thick / 2 - 7)]
    mapped = [(cx + u, cy + v) if horizontal else (cx + v, cy + u) for u, v in pts]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in mapped)
    out = (
        f'<polygon points="{poly}" fill="{t["node_fill"]}" stroke="{t["node_stroke"]}" '
        f'stroke-width="1.25" stroke-linejoin="round"/>'
    )
    if k.label:
        out += _svg_text(cx, cy + 3.5, k.label, t, 10, t["ink2"], anchor="middle")
    return out


# ---------------------------------------------------------------------------
# Kanban
# ---------------------------------------------------------------------------

_PRIORITY_COLORS = {
    "very high": "#d03b3b",
    "high": "#ec835a",
    "low": "#5cb85c",
    "very low": "#8c959f",
}


def parse_kanban(source: str) -> list[KanbanColumn]:
    """Parse a kanban board: column lines, indented task lines with optional @{ metadata }."""
    columns: list[KanbanColumn] = []
    col_indent: int | None = None
    for raw_line in source.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("%%"):
            continue
        stripped = raw_line.strip()
        if re.match(r"^kanban\s*$", stripped, re.I):
            continue
        indent = len(raw_line.expandtabs(4)) - len(raw_line.expandtabs(4).lstrip())
        meta: dict[str, str] = {}
        mm = re.search(r"@\{(.*)\}\s*$", stripped)
        if mm:
            stripped = stripped[: mm.start()].strip()
            for key, value in re.findall(r"(\w+)\s*:\s*('[^']*'|\"[^\"]*\"|[^,]+)", mm.group(1)):
                meta[key.lower()] = _unquote(value.strip())
        tm = re.match(r"^(?:[\w-]+)?\[(.*)\]$", stripped)
        text = _unquote(tm.group(1)) if tm else stripped
        if col_indent is None or indent <= col_indent:
            col_indent = indent if col_indent is None else col_indent
            columns.append(KanbanColumn(text))
        elif columns:
            columns[-1].items.append(KanbanItem(text, meta))
    return columns


def render_kanban_svg(columns: list[KanbanColumn], theme: dict[str, str] | None = None) -> str:
    """Render a kanban board: columns of cards with ticket, assignee and priority."""
    t = _tokens(theme)
    if not columns:
        return _svg_root(120, 40, _svg_text(0, 20, "No columns", t, color=t["ink2"]), t["font"])
    column_px = float(t.get("column_px") or 640)
    gap = 10.0
    col_w = max(132.0, min(196.0, (column_px - gap * (len(columns) - 1)) / len(columns)))
    parts: list[str] = []
    bottoms = []
    for c, col in enumerate(columns):
        x = c * (col_w + gap)
        y = 40.0
        cards = []
        for item in col.items:
            lines = _wrap_lines(item.text, col_w - 30, 11.5)
            footer = bool(item.meta.get("ticket") or item.meta.get("assigned"))
            h = 14 + 15 * len(lines) + (20 if footer else 0) + 2
            cards.append((item, lines, footer, y, h))
            y += h + 8
        bottom = y + 4
        bottoms.append(bottom)
        parts.append(
            f'<rect x="{x:g}" y="0" width="{col_w:g}" height="{bottom:g}" rx="8" '
            f'fill="{_tint(t["primary"], 0.965, t)}"/>'
        )
        count = str(len(col.items))
        cw = _text_w(count, 10, 600) + 12
        title = col.title
        while len(title) > 1 and _text_w(title, _FS, 600) > col_w - cw - 30:
            title = title[:-2].rstrip() + "…"
        parts.append(_svg_text(x + 12, 22, title, t, _FS, t["ink"], 600))
        parts.append(
            f'<rect x="{x + col_w - cw - 10:g}" y="11" width="{cw:g}" height="16" rx="8" '
            f'fill="{_tint(t["primary"], 0.85, t)}"/>'
        )
        parts.append(
            _svg_text(x + col_w - cw / 2 - 10, 22.5, count, t, 10, t["ink2"], 600, "middle")
        )
        for item, lines, footer, cy, h in cards:
            cx = x + 8
            w = col_w - 16
            parts.append(
                f'<rect x="{cx:g}" y="{cy + 1.5:g}" width="{w:g}" height="{h:g}" rx="6" fill="#0b1f33" '
                f'fill-opacity="{t["shadow"]}"/>'
            )
            parts.append(
                f'<rect x="{cx:g}" y="{cy:g}" width="{w:g}" height="{h:g}" rx="6" fill="{t["card"]}" '
                f'stroke="{_tint(t["primary"], 0.8, t)}" stroke-width="1"/>'
            )
            prio = _PRIORITY_COLORS.get(item.meta.get("priority", "").lower())
            if prio:
                parts.append(
                    f'<path d="M {cx + 3:g},{cy + 6:g} V {cy + h - 6:g}" stroke="{prio}" '
                    f'stroke-width="3" stroke-linecap="round"/>'
                )
            for li, text in enumerate(lines):
                parts.append(_svg_text(cx + 12, cy + 19 + li * 15, text, t, 11.5))
            if footer:
                fy = cy + h - 9
                if item.meta.get("ticket"):
                    parts.append(_svg_text(cx + 12, fy, item.meta["ticket"], t, 10, t["ink2"], 600))
                who = item.meta.get("assigned", "")
                if who:
                    initials = "".join(p[0] for p in re.split(r"[\s._-]+", who) if p)[:2].upper()
                    parts.append(
                        f'<circle cx="{cx + w - 14:g}" cy="{fy - 4:g}" r="8" fill="{_tint(t["primary"], 0.75, t)}"/>'
                    )
                    parts.append(
                        _svg_text(cx + w - 14, fy - 0.5, initials, t, 8.5, t["ink"], 700, "middle")
                    )
                    name_w = _text_w(who, 10)
                    if name_w < w - 70:
                        parts.append(
                            _svg_text(cx + w - 26, fy, who, t, 10, t["ink2"], anchor="end")
                        )
    width = len(columns) * col_w + gap * (len(columns) - 1)
    return _svg_root(width, max(bottoms), parts, t["font"])


def _wrap_lines(text: str, max_w: float, size: float) -> list[str]:
    """Word wrap without a line limit."""
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and _text_w(trial, size) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


def parse_architecture(source: str) -> Architecture:
    """Parse an architecture-beta diagram."""
    ad = Architecture()
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^architecture(-beta)?\s*$", line, re.I):
            continue
        m = re.match(
            r'^(group|service)\s+([\w-]+)\s*(?:\(([^)]*)\))?\s*(?:\[\s*"?([^\]"]*)"?\s*\])?\s*(?:in\s+([\w-]+))?$',
            line,
        )
        if m:
            item = ArchItem(
                m.group(2), m.group(4) or m.group(2), m.group(3) or "", m.group(5) or ""
            )
            (ad.groups if m.group(1) == "group" else ad.services)[item.id] = item
            continue
        m = re.match(r"^junction\s+([\w-]+)(?:\s+in\s+([\w-]+))?$", line)
        if m:
            ad.services[m.group(1)] = ArchItem(m.group(1), "", "", m.group(2) or "", junction=True)
            continue
        m = re.match(
            r"^([\w-]+)(?:\{group\})?\s*:\s*([LRTB])\s*(<)?-(?:-)?(>)?\s*([LRTB])\s*:\s*([\w-]+)(?:\{group\})?$",
            line,
        )
        if m:
            ad.edges.append(
                ArchEdge(
                    m.group(1),
                    m.group(2),
                    m.group(6),
                    m.group(5),
                    bool(m.group(3)),
                    bool(m.group(4)),
                )
            )
            continue
        m = re.match(r"^align\s+(row|column)\s+(.+)$", line)
        if m:
            ad.aligns.append((m.group(1), m.group(2).split()))
    return ad


_STEP = {"L": (-1, 0), "R": (1, 0), "T": (0, -1), "B": (0, 1)}


def _arch_grid(ad: Architecture) -> dict[str, tuple[int, int]]:
    """Integer grid positions implied by the edge sides (a:R -- L:b puts b right of a)."""
    pos: dict[str, tuple[int, int]] = {}
    taken: set[tuple[int, int]] = set()
    adj: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for e in ad.edges:
        ax, ay = _STEP[e.side_a]
        bx, by = _STEP[e.side_b]
        dx = max(-1, min(1, ax - bx))
        dy = max(-1, min(1, ay - by))
        adj[e.a].append((e.b, dx, dy))
        adj[e.b].append((e.a, -dx, -dy))

    def place(nid: str, x: int, y: int, dx: int, dy: int) -> None:
        step_x, step_y = (dx, dy) if (dx or dy) else (1, 0)
        while (x, y) in taken:
            x, y = x + step_x, y + step_y
        pos[nid] = (x, y)
        taken.add((x, y))

    next_col = 0
    for start in ad.services:
        if start in pos:
            continue
        place(start, next_col, 0, 0, 1)
        queue = [start]
        while queue:
            cur = queue.pop(0)
            cx, cy = pos[cur]
            for nb, dx, dy in adj[cur]:
                if nb in pos or nb not in ad.services:
                    continue
                place(nb, cx + dx, cy + dy, dx, dy)
                queue.append(nb)
        next_col = max(x for x, _ in pos.values()) + 1
    for kind, members in ad.aligns:
        members = [m for m in members if m in pos]
        if len(members) < 2:
            continue
        ax, ay = pos[members[0]]
        for mid in members[1:]:
            x, y = pos[mid]
            pos[mid] = (x, ay) if kind == "row" else (ax, y)
    # Resolve any overlaps introduced by alignment
    seen: set[tuple[int, int]] = set()
    for nid in list(pos):
        x, y = pos[nid]
        while (x, y) in seen:
            x += 1
        pos[nid] = (x, y)
        seen.add((x, y))
    if pos:
        mx = min(x for x, _ in pos.values())
        my = min(y for _, y in pos.values())
        pos = {k: (x - mx, y - my) for k, (x, y) in pos.items()}
    return pos


def _arch_icon(kind: str, cx: float, cy: float, t: dict[str, str]) -> str:
    """Line icons for the built-in architecture icons (unknown names get a generic tile)."""
    s, c, f = 40.0, t["term_fill"], t["node_fill"]
    x0, y0 = cx - s / 2, cy - s / 2
    tile = (
        f'<rect x="{x0:g}" y="{y0:g}" width="{s:g}" height="{s:g}" rx="9" fill="{f}" '
        f'stroke="{t["node_stroke"]}" stroke-width="1.25"/>'
    )
    stroke = f'fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
    name = kind.split(":")[-1].lower()
    if name == "cloud":
        glyph = (
            f'<path d="M {cx - 10:g},{cy + 7:g} H {cx + 10:g} A 6 6 0 0 0 {cx + 9:g},{cy - 4:g} '
            f'A 8 8 0 0 0 {cx - 5:g},{cy - 6:g} A 6.5 6.5 0 0 0 {cx - 10:g},{cy + 7:g} Z" {stroke}/>'
        )
    elif name == "database":
        glyph = (
            f'<ellipse cx="{cx:g}" cy="{cy - 8:g}" rx="10" ry="3.5" {stroke}/>'
            f'<path d="M {cx - 10:g},{cy - 8:g} V {cy + 8:g} A 10 3.5 0 0 0 {cx + 10:g},{cy + 8:g} V {cy - 8:g} '
            f'M {cx - 10:g},{cy:g} A 10 3.5 0 0 0 {cx + 10:g},{cy:g}" {stroke}/>'
        )
    elif name == "disk":
        glyph = (
            f'<rect x="{cx - 10:g}" y="{cy - 10:g}" width="20" height="20" rx="3" {stroke}/>'
            f'<circle cx="{cx:g}" cy="{cy - 1:g}" r="5" {stroke}/>'
            f'<circle cx="{cx + 6:g}" cy="{cy + 6:g}" r="1" fill="{c}"/>'
        )
    elif name == "internet":
        glyph = (
            f'<circle cx="{cx:g}" cy="{cy:g}" r="10" {stroke}/>'
            f'<path d="M {cx - 10:g},{cy:g} H {cx + 10:g} M {cx:g},{cy - 10:g} '
            f'A 5 10 0 0 0 {cx:g},{cy + 10:g} A 5 10 0 0 0 {cx:g},{cy - 10:g}" {stroke}/>'
        )
    elif name == "server":
        glyph = (
            f'<rect x="{cx - 10:g}" y="{cy - 10:g}" width="20" height="8.5" rx="2" {stroke}/>'
            f'<rect x="{cx - 10:g}" y="{cy + 1.5:g}" width="20" height="8.5" rx="2" {stroke}/>'
            f'<circle cx="{cx - 5.5:g}" cy="{cy - 5.75:g}" r="1" fill="{c}"/>'
            f'<circle cx="{cx - 5.5:g}" cy="{cy + 5.75:g}" r="1" fill="{c}"/>'
        )
    else:
        glyph = f'<rect x="{cx - 9:g}" y="{cy - 9:g}" width="18" height="18" rx="4" {stroke}/>'
    return tile + glyph


def render_architecture_svg(ad: Architecture, theme: dict[str, str] | None = None) -> str:
    """Render an architecture diagram: icon services on a grid, framed groups, sided edges."""
    t = _tokens(theme)
    if not ad.services:
        return _svg_root(120, 40, _svg_text(0, 20, "No services", t, color=t["ink2"]), t["font"])
    grid = _arch_grid(ad)
    pitch_x, pitch_y = 150.0, 118.0
    margin = 34.0
    centre = {
        nid: (margin + 40 + x * pitch_x, margin + 30 + y * pitch_y) for nid, (x, y) in grid.items()
    }

    def anchor(nid: str, side: str) -> tuple[float, float]:
        x, y = centre[nid]
        r = 4.0 if ad.services[nid].junction else 20.0
        dx, dy = _STEP[side]
        return x + dx * r, y + dy * r

    parts: list[str] = [_make_arrow_defs(t)]
    # Group frames, outer groups first
    depth: dict[str, int] = {}

    def group_depth(gid: str) -> int:
        if gid not in depth:
            parent = ad.groups[gid].parent
            depth[gid] = 0 if parent not in ad.groups else group_depth(parent) + 1
        return depth[gid]

    def members(gid: str) -> list[str]:
        out = [s for s, item in ad.services.items() if item.parent == gid and s in centre]
        for sub, item in ad.groups.items():
            if item.parent == gid:
                out += members(sub)
        return out

    for gid in sorted(ad.groups, key=group_depth):
        ms = members(gid)
        if not ms:
            continue
        inset = group_depth(gid) * 10
        xs = [centre[m][0] for m in ms]
        ys = [centre[m][1] for m in ms]
        x0, y0 = min(xs) - 62 + inset, min(ys) - 50 + inset
        x1, y1 = max(xs) + 62 - inset, max(ys) + 50 - inset
        group = ad.groups[gid]
        parts.append(
            f'<rect x="{x0:g}" y="{y0:g}" width="{x1 - x0:g}" height="{y1 - y0:g}" rx="10" '
            f'fill="{_tint(t["primary"], 0.975, t)}" stroke="{t["subgraph_stroke"]}" stroke-width="1" '
            f'stroke-dasharray="5 4"/>'
        )
        if group.icon:
            parts.append(
                f'<g transform="translate({x0 + 16:g},{y0 + 14:g}) scale(0.45)">'
                + _arch_icon(group.icon, 0, 0, t)
                + "</g>"
            )
        parts.append(_svg_text(x0 + 30, y0 + 18, group.label, t, _FS_SM, t["ink2"], 600))

    for e in ad.edges:
        if e.a not in centre or e.b not in centre:
            continue
        p0, p1 = anchor(e.a, e.side_a), anchor(e.b, e.side_b)
        horizontal_a = e.side_a in "LR"
        horizontal_b = e.side_b in "LR"
        if horizontal_a and horizontal_b:
            mx = (p0[0] + p1[0]) / 2
            pts = [p0, (mx, p0[1]), (mx, p1[1]), p1]
        elif not horizontal_a and not horizontal_b:
            my = (p0[1] + p1[1]) / 2
            pts = [p0, (p0[0], my), (p1[0], my), p1]
        elif horizontal_a:
            pts = [p0, (p1[0], p0[1]), p1]
        else:
            pts = [p0, (p0[0], p1[1]), p1]
        mk = (' marker-end="url(#arr)"' if e.arrow_b else "") + (
            ' marker-start="url(#arr-s)"' if e.arrow_a else ""
        )
        parts.append(
            f'<path d="{_round_polyline(pts)}" fill="none" stroke="{t["edge"]}" stroke-width="1.5"{mk}/>'
        )

    for nid, item in ad.services.items():
        if nid not in centre:
            continue
        cx, cy = centre[nid]
        if item.junction:
            parts.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="4" fill="{t["edge"]}"/>')
            continue
        parts.append(_arch_icon(item.icon or "server", cx, cy, t))
        for li, text in enumerate(_wrap_lines(item.label, pitch_x - 24, 11.5)[:2]):
            parts.append(_svg_text(cx, cy + 36 + li * 14, text, t, 11.5, anchor="middle"))

    width = max(x for x, _ in centre.values()) + 40 + 62 + margin
    height = max(y for _, y in centre.values()) + 50 + margin + 10
    return _svg_root(width, height, parts, t["font"])


def _call_args(text: str) -> tuple[list[str], dict[str, str]]:
    """Split ``a, "b, c", $key="v"`` into positional and ``$named`` arguments."""
    args: list[str] = []
    named: dict[str, str] = {}
    cur, quote, depth = "", False, 0
    for ch in text + ",":
        if ch == '"':
            quote = not quote
            cur += ch
        elif ch in "([" and not quote:
            depth += 1
            cur += ch
        elif ch in ")]" and not quote:
            depth -= 1
            cur += ch
        elif ch == "," and not quote and depth == 0:
            item = cur.strip()
            m = re.match(r"^\$(\w+)\s*=\s*(.*)$", item)
            if m:
                named[m.group(1).lower()] = _unquote(m.group(2))
            elif item or args:
                args.append(_unquote(item))
            cur = ""
        else:
            cur += ch
    return args, named


_C4_ELEMENT_RE = re.compile(
    r"^(Person|System|SystemDb|SystemQueue|Container|ContainerDb|ContainerQueue|Component|ComponentDb|ComponentQueue)(_Ext)?$"
)
_C4_BOUNDARY = {
    "Boundary",
    "Enterprise_Boundary",
    "System_Boundary",
    "Container_Boundary",
    "Deployment_Node",
    "Node",
    "Node_L",
    "Node_R",
}


def parse_c4(source: str) -> C4Diagram:
    """Parse C4Context / C4Container / C4Component / C4Dynamic / C4Deployment."""
    cd = C4Diagram()
    stack: list[C4Boundary] = [cd.root]
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        m = re.match(r"^(C4Context|C4Container|C4Component|C4Dynamic|C4Deployment)\b", line)
        if m:
            cd.kind = m.group(1)
            continue
        m = re.match(r"^title\s+(.+)$", line)
        if m:
            cd.title = _unquote(m.group(1))
            continue
        if line == "}":
            if len(stack) > 1:
                stack.pop()
            continue
        m = re.match(r"^(\w+)\s*\((.*)\)\s*(\{)?\s*$", line)
        if not m:
            continue
        func, (args, named) = m.group(1), _call_args(m.group(2))
        if func == "UpdateLayoutConfig":
            for key, attr in (
                ("c4shapeinrow", "shape_in_row"),
                ("c4boundaryinrow", "boundary_in_row"),
            ):
                value = named.get(key) or (args.pop(0) if args else "")
                if value.isdigit():
                    setattr(cd, attr, int(value))
            continue
        if func in _C4_BOUNDARY:
            if not args:
                continue
            kind = "deployment" if func.startswith(("Deployment", "Node")) else "boundary"
            label_type = named.get("type") or (args[2] if len(args) > 2 else "")
            if not label_type and func != "Boundary":
                label_type = {
                    "Enterprise_Boundary": "Enterprise",
                    "System_Boundary": "System",
                    "Container_Boundary": "Container",
                }.get(func, "")
            boundary = C4Boundary(args[0], args[1] if len(args) > 1 else args[0], label_type, kind)
            stack[-1].boundaries.append(boundary)
            if m.group(3):
                stack.append(boundary)
            continue
        em = _C4_ELEMENT_RE.match(func)
        if em and args:
            base = em.group(1)
            level = "person" if base == "Person" else re.sub(r"(Db|Queue)$", "", base).lower()
            shape = "db" if base.endswith("Db") else "queue" if base.endswith("Queue") else "box"
            if level in ("container", "component"):
                techn = named.get("techn") or (args[2] if len(args) > 2 else "")
                descr = named.get("descr") or (args[3] if len(args) > 3 else "")
            else:
                techn = ""
                descr = named.get("descr") or (args[2] if len(args) > 2 else "")
            element = C4Element(
                args[0],
                args[1] if len(args) > 1 else args[0],
                level,
                bool(em.group(2)),
                shape,
                techn,
                descr,
            )
            stack[-1].elements.append(element)
            cd.elements[element.alias] = element
            continue
        rm = re.match(
            r"^(BiRel|Rel|RelIndex|Rel_(?:U|Up|D|Down|L|Left|R|Right|Back|Neighbor))$", func
        )
        if rm and len(args) >= 2:
            if func == "RelIndex":
                args = args[1:]
            src, dst = args[0], args[1]
            if func == "Rel_Back":
                src, dst = dst, src
            cd.rels.append(
                C4Rel(
                    src,
                    dst,
                    args[2] if len(args) > 2 else "",
                    named.get("techn") or (args[3] if len(args) > 3 else ""),
                    func == "BiRel",
                )
            )
    return cd


def _c4_colors(level: str, ext: bool, t: dict[str, str]) -> tuple[str, str]:
    """(fill, stroke) for a C4 element: darker = closer to people, grey = external."""
    if ext:
        fill = {
            "person": "#686868",
            "system": "#8a8a8a",
            "container": "#a3a3a3",
            "component": "#b8b8b8",
        }[level]
    else:
        primary = t["primary"]
        fill = {
            "person": _mix(primary, "#000000", 0.28),
            "system": primary,
            "container": _mix(primary, "#ffffff", 0.22),
            "component": _mix(primary, "#ffffff", 0.42),
        }[level]
    return fill, _mix(fill, "#000000", 0.15)


def _c4_card_size(el: C4Element) -> tuple[float, float, list[str], list[str]]:
    w = 196.0
    label = _wrap_lines(el.label, w - 24, 12.5)
    descr = _wrap_lines(el.descr, w - 24, 10.5) if el.descr else []
    h = 14 + 16 * len(label) + 15 + 14 * len(descr) + 12
    if el.level == "person":
        h += 16
    return w, max(h, 76.0), label, descr


def _c4_point(
    p0: tuple[float, float], c: tuple[float, float] | None, p1: tuple[float, float], f: float
) -> tuple[float, float]:
    """Point at fraction *f* along a straight relation, or a quadratic one bent through *c*."""
    if c is None:
        return p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f
    g = 1 - f
    return (
        g * g * p0[0] + 2 * g * f * c[0] + f * f * p1[0],
        g * g * p0[1] + 2 * g * f * c[1] + f * f * p1[1],
    )


def _c4_detour(
    p0: tuple[float, float],
    p1: tuple[float, float],
    others: list[tuple[float, float, float, float]],
) -> tuple[float, float] | None:
    """Control point that bends a relation around cards it would cross, or None if it is clear."""

    def hits(c: tuple[float, float] | None) -> bool:
        for i in range(1, 40):
            x, y = _c4_point(p0, c, p1, i / 40)
            if any(
                bx - 4 < x < bx + bw + 4 and by - 4 < y < by + bh + 4 for bx, by, bw, bh in others
            ):
                return True
        return False

    if not hits(None):
        return None
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    for off in (60, -60, 110, -110, 170, -170, 240, -240):
        c = (mx + nx * off, my + ny * off)
        if not hits(c):
            return c
    return None


def render_c4_svg(cd: C4Diagram, theme: dict[str, str] | None = None) -> str:
    """Render a C4 diagram: role-coloured cards packed in rows inside dashed boundaries."""
    t = _tokens(theme)
    if not cd.elements:
        return _svg_root(120, 40, _svg_text(0, 20, "No elements", t, color=t["ink2"]), t["font"])
    gap, row_gap, pad, head = 34.0, 64.0, 16.0, 34.0
    boxes: dict[str, tuple[float, float, float, float]] = {}
    frames: list[tuple[C4Boundary, float, float, float, float]] = []

    def rel_lines(rel: C4Rel) -> list[str]:
        lines = _wrap_lines(rel.label, 140, _FS_SM) if rel.label else []
        if rel.techn:
            lines.append(f"[{rel.techn}]")
        return lines

    # Neighbours joined by a labelled relation sit far enough apart for the label
    pair_gap: dict[frozenset[str], float] = {}
    for rel in cd.rels:
        lines = rel_lines(rel)
        if lines:
            need = max(_text_w(x, _FS_SM) for x in lines) + 34
            key = frozenset((rel.src, rel.dst))
            pair_gap[key] = max(pair_gap.get(key, gap), need)

    def measure(b: C4Boundary) -> tuple[float, float]:
        return place(b, 0.0, 0.0, dry=True)

    def place(b: C4Boundary, x: float, y: float, dry: bool = False) -> tuple[float, float]:
        top = head if b is not cd.root else 0.0
        inner = pad if b is not cd.root else 0.0
        cy = y + top + inner
        width = 0.0
        for start in range(0, len(b.elements), cd.shape_in_row):
            row = b.elements[start : start + cd.shape_in_row]
            sizes = [_c4_card_size(el) for el in row]
            row_h = max(s[1] for s in sizes)
            cx = x + inner
            for k, (el, (w, h, _, _)) in enumerate(zip(row, sizes)):
                if k:
                    cx += pair_gap.get(frozenset((row[k - 1].alias, el.alias)), gap)
                if not dry:
                    boxes[el.alias] = (cx, cy + (row_h - h) / 2, w, h)
                cx += w
            width = max(width, cx - x - inner)
            cy += row_h + row_gap
        for start in range(0, len(b.boundaries), cd.boundary_in_row):
            row_b = b.boundaries[start : start + cd.boundary_in_row]
            sizes_b = [measure(sub) for sub in row_b]
            row_h = max(s[1] for s in sizes_b)
            cx = x + inner
            for sub, (w, h) in zip(row_b, sizes_b):
                if not dry:
                    place(sub, cx, cy)
                    frames.append((sub, cx, cy, w, h))
                cx += w + gap
            width = max(width, cx - gap - x - inner)
            cy += row_h + row_gap
        if b is not cd.root:
            width = max(width, _text_w(b.label, 12, 600) + 24)
        return width + 2 * inner, cy - row_gap - y + inner

    title_parts, title_h = _chart_title(cd.title, t)
    total_w, total_h = place(cd.root, 0.0, 0.0)
    parts: list[str] = [
        "<defs>",
        f'<marker id="c4-arr" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="7" refX="8" '
        f'refY="3.5" orient="auto"><polygon points="0 0.5, 8 3.5, 0 6.5" fill="{t["ink2"]}"/></marker>',
        f'<marker id="c4-arr-s" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="7" refX="1" '
        f'refY="3.5" orient="auto"><polygon points="9 0.5, 1 3.5, 9 6.5" fill="{t["ink2"]}"/></marker>',
        "</defs>",
        *title_parts,
        f'<g transform="translate(0,{title_h:g})">',
    ]
    for b, x, y, w, h in frames:
        dash = "6 4" if b.kind == "boundary" else "none"
        parts.append(
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="8" fill="none" '
            f'stroke="{t["chrome"]}" stroke-width="1.25" stroke-dasharray="{dash}"/>'
        )
        parts.append(_svg_text(x + 12, y + 18, b.label, t, 12, t["ink"], 600))
        if b.type:
            parts.append(_svg_text(x + 12, y + 30, f"[{b.type}]", t, 10, t["ink2"]))

    def clip(box: tuple[float, float, float, float], tx: float, ty: float) -> tuple[float, float]:
        x, y, w, h = box
        cx, cy = x + w / 2, y + h / 2
        dx, dy = tx - cx, ty - cy
        if dx == 0 and dy == 0:
            return cx, cy
        scale = min(w / 2 / abs(dx) if dx else 1e9, h / 2 / abs(dy) if dy else 1e9)
        return cx + dx * scale, cy + dy * scale

    labels: list[str] = []  # relation labels go on top of the cards
    taken_labels: list[tuple[float, float, float, float]] = []
    for rel in cd.rels:
        box_a, box_b = boxes.get(rel.src), boxes.get(rel.dst)
        if box_a is None or box_b is None:
            continue
        ac = (box_a[0] + box_a[2] / 2, box_a[1] + box_a[3] / 2)
        bc = (box_b[0] + box_b[2] / 2, box_b[1] + box_b[3] / 2)
        p0, p1 = clip(box_a, *bc), clip(box_b, *ac)
        mk = ' marker-end="url(#c4-arr)"' + (' marker-start="url(#c4-arr-s)"' if rel.bi else "")
        others = [b for k, b in boxes.items() if k not in (rel.src, rel.dst)]
        ctrl = _c4_detour(p0, p1, others)
        if ctrl is None:
            parts.append(
                f'<line x1="{p0[0]:.1f}" y1="{p0[1]:.1f}" x2="{p1[0]:.1f}" y2="{p1[1]:.1f}" '
                f'stroke="{t["ink2"]}" stroke-width="1.25" stroke-dasharray="5 3"{mk}/>'
            )
        else:
            # Re-aim the ends at the control point so arrowheads follow the curve
            p0, p1 = clip(box_a, *ctrl), clip(box_b, *ctrl)
            parts.append(
                f'<path d="M {p0[0]:.1f},{p0[1]:.1f} Q {ctrl[0]:.1f},{ctrl[1]:.1f} {p1[0]:.1f},{p1[1]:.1f}" '
                f'fill="none" stroke="{t["ink2"]}" stroke-width="1.25" stroke-dasharray="5 3"{mk}/>'
            )
        mx, my = _c4_point(p0, ctrl, p1, 0.5)
        lines = rel_lines(rel)
        if lines:
            lw = max(_text_w(x, _FS_SM) for x in lines) + 10
            lh = 14 * len(lines) + 4
            # Slide the label along its line until it clears every card (and earlier labels)
            for f in sorted((i / 40 for i in range(4, 37)), key=lambda v: abs(v - 0.5)):
                cx_, cy_ = _c4_point(p0, ctrl, p1, f)
                box = (cx_ - lw / 2, cy_ - lh / 2, cx_ + lw / 2, cy_ + lh / 2)
                hits = any(
                    box[0] < bx + bw and box[2] > bx and box[1] < by + bh and box[3] > by
                    for bx, by, bw, bh in boxes.values()
                ) or any(
                    box[0] < c2 and box[2] > c0 and box[1] < d2 and box[3] > d0
                    for c0, d0, c2, d2 in taken_labels
                )
                if not hits:
                    mx, my = cx_, cy_
                    break
            taken_labels.append((mx - lw / 2, my - lh / 2, mx + lw / 2, my + lh / 2))
            labels.append(
                f'<rect x="{mx - lw / 2:g}" y="{my - lh / 2:g}" width="{lw:g}" height="{lh:g}" rx="3" '
                f'fill="{t["surface"]}"/>'
            )
            for i, text in enumerate(lines):
                italic = (
                    ' font-style="italic"'
                    if text.startswith("[") and rel.techn and i == len(lines) - 1
                    else ""
                )
                labels.append(
                    _svg_text(
                        mx,
                        my - lh / 2 + 13 + i * 14,
                        text,
                        t,
                        _FS_SM,
                        t["ink2"],
                        anchor="middle",
                        extra=italic,
                    )
                )

    for alias, (x, y, w, h) in boxes.items():
        el = cd.elements[alias]
        fill, stroke = _c4_colors(el.level, el.ext, t)
        ink = _text_on(fill, t)
        _, _, label, descr = _c4_card_size(el)
        top = y
        if el.shape == "db":
            parts.append(
                f'<path d="M {x:g},{y + 8:g} V {y + h - 8:g} A {w / 2:g} 8 0 0 0 {x + w:g},{y + h - 8:g} '
                f'V {y + 8:g} A {w / 2:g} 8 0 0 0 {x:g},{y + 8:g} A {w / 2:g} 8 0 0 0 {x + w:g},{y + 8:g}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
            )
            top += 10
        elif el.shape == "queue":
            parts.append(
                f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{min(h / 2, 22):g}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
            )
        else:
            parts.append(
                f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="10" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="1"/>'
            )
        if el.level == "person":
            parts.append(
                f'<circle cx="{x + w / 2:g}" cy="{y + 2:g}" r="15" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
            )
            top += 16
        ty = top + 24
        for text in label:
            parts.append(_svg_text(x + w / 2, ty, text, t, 12.5, ink, 600, "middle"))
            ty += 16
        kind = {
            "person": "Person",
            "system": "Software System",
            "container": "Container",
            "component": "Component",
        }[el.level]
        if el.ext:
            kind = f"External {kind.lower()}" if el.level != "person" else "External person"
        tag = f"[{kind}: {el.techn}]" if el.techn else f"[{kind}]"
        parts.append(
            _svg_text(x + w / 2, ty, tag, t, 10, ink, anchor="middle", extra=' fill-opacity="0.85"')
        )
        ty += 17
        for text in descr:
            parts.append(_svg_text(x + w / 2, ty, text, t, 10.5, ink, anchor="middle"))
            ty += 14
    parts += labels
    parts.append("</g>")
    width = max(total_w, _text_w(cd.title, _FS_TITLE, 600)) + 4
    return _svg_root(width, total_h + title_h + 18, parts, t["font"])


# ---------------------------------------------------------------------------
# Requirement diagram
# ---------------------------------------------------------------------------

_REQ_TYPES = {
    "requirement": "Requirement",
    "functionalrequirement": "Functional Requirement",
    "interfacerequirement": "Interface Requirement",
    "performancerequirement": "Performance Requirement",
    "physicalrequirement": "Physical Requirement",
    "designconstraint": "Design Constraint",
    "element": "Element",
}


def parse_requirement(source: str) -> RequirementDiagram:
    """Parse a requirementDiagram: requirement/element blocks and typed relationships."""
    rd = RequirementDiagram()
    current: ReqNode | None = None
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^requirementDiagram\b", line, re.I):
            continue
        if current is not None:
            if line.startswith("}"):
                current = None
                continue
            m = re.match(r"^(\w+)\s*:\s*(.*)$", line)
            if m:
                current.fields.append((m.group(1).lower(), _unquote(m.group(2))))
            continue
        m = re.match(r"^direction\s+(TB|TD|BT|LR|RL)$", line, re.I)
        if m:
            rd.direction = m.group(1).upper()
            continue
        m = re.match(r'^(\w+)\s+("[^"]+"|[\w.-]+)\s*\{\s*$', line)
        if m and m.group(1).lower() in _REQ_TYPES:
            name = _unquote(m.group(2)).strip("_*")
            current = ReqNode(name, _REQ_TYPES[m.group(1).lower()])
            rd.nodes[name] = current
            continue
        m = re.match(r'^("[^"]+"|[\w.-]+)\s*-\s*(\w+)\s*->\s*("[^"]+"|[\w.-]+)$', line)
        if m:
            rd.relations.append(
                (
                    _unquote(m.group(1)).strip("_*"),
                    _unquote(m.group(3)).strip("_*"),
                    m.group(2).lower(),
                )
            )
            continue
        m = re.match(r'^("[^"]+"|[\w.-]+)\s*<-\s*(\w+)\s*-\s*("[^"]+"|[\w.-]+)$', line)
        if m:
            rd.relations.append(
                (
                    _unquote(m.group(3)).strip("_*"),
                    _unquote(m.group(1)).strip("_*"),
                    m.group(2).lower(),
                )
            )
    return rd


def render_requirement_svg(rd: RequirementDiagram, theme: dict[str, str] | None = None) -> str:
    """Render requirement and element cards with labelled relationships."""
    t = _tokens(theme)
    if not rd.nodes:
        return _svg_root(
            120, 40, _svg_text(0, 20, "No requirements", t, color=t["ink2"]), t["font"]
        )
    names = {
        "id": "ID",
        "text": "Text",
        "risk": "Risk",
        "verifymethod": "Verification",
        "type": "Type",
        "docref": "Doc ref",
    }
    cards: dict[str, tuple[float, float, list[tuple[str, list[str]]]]] = {}
    for name, node in rd.nodes.items():
        w = max(_text_w(name, _FS, 600) + 28, _text_w(f"«{node.kind}»", _FS_SM) + 28, 190.0)
        rows = []
        for key, value in node.fields:
            label = names.get(key, key.title())
            text = value.title() if key in ("risk", "verifymethod") else value
            rows.append((label, _wrap_lines(text, w - 24 - _text_w(label + ": ", 11, 600), 11)))
        h = 46.0 + sum(15 * len(v) + 3 for _, v in rows) + 8
        cards[name] = (w, h, rows)

    fc = Flowchart(direction={"TB": "TD", "BT": "TD"}.get(rd.direction, rd.direction or "TD"))
    for name, (w, h, _) in cards.items():
        fc.nodes[name] = Node(name, "", "fixed", w=w, h=h)
    for a, b, kind in rd.relations:
        if a in fc.nodes and b in fc.nodes:
            fc.edges.append(Edge(a, b, f"«{kind}»"))
    layout(fc, t)
    _fit_to_column(fc, t, wrap=False)
    ox, oy, width, height = _flow_extent(fc, pad=12.0)
    parts = [_make_arrow_defs(t), f'<g transform="translate({-ox:g},{-oy:g})">']
    ports = _assign_ports(fc)
    for i, e in enumerate(fc.edges):
        edge = Edge(e.src, e.dst, e.label, "dotted" if e.label != "«contains»" else "solid")
        parts.append(
            _render_edge(
                fc.nodes[e.src],
                fc.nodes[e.dst],
                e.label,
                fc.direction,
                t,
                edge.style,
                0.0,
                fc.waypoints.get(i),
                ports.get((i, "out")),
                ports.get((i, "in")),
                edge,
            )
        )
    for name, node in rd.nodes.items():
        n = fc.nodes[name]
        w, h, rows = cards[name]
        is_element = node.kind == "Element"
        head_fill = t["diamond_fill"] if is_element else t["node_fill"]
        stroke = t["diamond_stroke"] if is_element else t["node_stroke"]
        parts.append(
            f'<rect x="{n.x:g}" y="{n.y + 1.5:g}" width="{w:g}" height="{h:g}" rx="6" fill="#0b1f33" '
            f'fill-opacity="{t["shadow"]}"/>'
        )
        parts.append(
            f'<rect x="{n.x:g}" y="{n.y:g}" width="{w:g}" height="{h:g}" rx="6" fill="{t["card"]}" '
            f'stroke="{stroke}" stroke-width="1.25"/>'
        )
        parts.append(
            f'<path d="M {n.x:g},{n.y + 40:g} V {n.y + 6:g} Q {n.x:g},{n.y:g} {n.x + 6:g},{n.y:g} '
            f'H {n.x + w - 6:g} Q {n.x + w:g},{n.y:g} {n.x + w:g},{n.y + 6:g} V {n.y + 40:g} Z" '
            f'fill="{head_fill}" stroke="{stroke}" stroke-width="1.25"/>'
        )
        parts.append(
            _svg_text(
                n.x + w / 2, n.y + 16, f"«{node.kind}»", t, _FS_SM, t["ink2"], anchor="middle"
            )
        )
        parts.append(_svg_text(n.x + w / 2, n.y + 32, name, t, _FS, weight=600, anchor="middle"))
        ty = n.y + 58
        for label, lines in rows:
            parts.append(_svg_text(n.x + 12, ty, f"{label}:", t, 11, t["ink2"], 600))
            lx = n.x + 12 + _text_w(label + ": ", 11, 600)
            for k, text in enumerate(lines):
                parts.append(_svg_text(lx, ty + k * 15, text, t, 11))
            ty += 15 * len(lines) + 3
    parts.append("</g>")
    return _svg_root(width, height, parts, t["font"])


# ---------------------------------------------------------------------------
# ZenUML (rendered with the sequence renderer)
# ---------------------------------------------------------------------------


def parse_zenuml(source: str) -> tuple[SequenceDiagram, str]:
    """Translate ZenUML into a SequenceDiagram (plus its title)."""
    sd = SequenceDiagram()
    title = ""
    callers: list[str] = []  # call stack of the participants currently executing
    opened: list[tuple[str, str, str]] = []  # what each '{' opened: (kind, participant, reply var)
    reply_next = False
    starter = "Client"

    def add(pid: str, label: str = "", actor: bool = False) -> None:
        if pid not in sd.participants:
            sd.participants.append(pid)
        if label:
            sd.labels[pid] = label
        if actor:
            sd.actors.add(pid)

    def message(src: str, dst: str, label: str, arrow: str) -> None:
        add(src)
        add(dst)
        msg = SeqMessage(src, dst, label, arrow)
        sd.messages.append(msg)
        sd.events.append(msg)

    def current() -> str:
        if callers:
            return callers[-1]
        add(starter)
        return starter

    for raw_line in source.strip().splitlines():
        line = raw_line.strip().rstrip(";")
        if (
            not line
            or line.startswith("//")
            or line.startswith("%%")
            or re.match(r"^zenuml\s*$", line, re.I)
        ):
            continue
        m = re.match(r"^title\s+(.+)$", line)
        if m:
            title = m.group(1).strip()
            continue
        if re.match(r"^@(return|reply)\s*$", line):
            reply_next = True
            continue
        # closing braces, possibly followed by else / catch / finally
        while line.startswith("}"):
            rest = line[1:].strip()
            cont = re.match(
                r"^(?:else\s+if\s*\((.*)\)|(else)|catch(?:\s*\((.*)\))?|(finally))\s*\{$", rest
            )
            if cont and opened and opened[-1][0] in ("alt", "critical"):
                if cont.group(1) is not None:
                    label = cont.group(1)
                elif cont.group(2):
                    label = ""
                elif cont.group(4):
                    label = "finally"
                else:
                    label = f"catch ({cont.group(3)})" if cont.group(3) else "catch"
                sd.events.append(SeqBlock("else", label))
                line = ""
                break
            if opened:
                kind, who, var = opened.pop()
                if kind == "call":
                    callee = callers.pop() if callers else who
                    if var:
                        message(callee, current(), var, "-->>")
                else:
                    sd.events.append(SeqBlock("end"))
            line = rest
        if not line:
            continue
        m = re.match(r"^@(\w+)\s+(\w+)(?:\s+as\s+(.+))?$", line)
        if m:
            add(m.group(2), (m.group(3) or "").strip(), m.group(1).lower() == "actor")
            continue
        m = re.match(r"^(\w+)\s+as\s+(.+)$", line)
        if m:
            add(m.group(1), m.group(2).strip())
            continue
        if re.match(r"^\w+$", line) and line not in ("opt", "par", "try"):
            add(line)
            continue
        m = re.match(r"^(if|while|for|forEach|foreach|loop)\s*\((.*)\)\s*\{$", line)
        if m:
            kind = "alt" if m.group(1) == "if" else "loop"
            sd.events.append(SeqBlock(kind, m.group(2).strip()))
            opened.append((kind, "", ""))
            continue
        m = re.match(r"^(opt|par|try)\s*\{$", line)
        if m:
            kind = {"opt": "opt", "par": "par", "try": "critical"}[m.group(1)]
            sd.events.append(SeqBlock(kind, "try" if m.group(1) == "try" else ""))
            opened.append((kind, "", ""))
            continue
        m = re.match(r"^return\s+(.+)$", line)
        if m and callers:
            target = callers[-2] if len(callers) > 1 else starter
            add(target)
            message(callers[-1], target, m.group(1).strip(), "-->>")
            continue
        m = re.match(r"^(\w+)\s*->\s*(\w+)\s*:\s*(.*)$", line)
        if m:
            message(m.group(1), m.group(2), m.group(3).strip(), "-->>" if reply_next else "-)")
            reply_next = False
            continue
        m = re.match(r"^new\s+(\w+)\s*(\(.*\))?\s*(\{)?$", line)
        if m:
            message(current(), m.group(1), f"«create»{m.group(2) or ''}", "->>")
            if m.group(3):
                callers.append(m.group(1))
                opened.append(("call", m.group(1), ""))
            continue
        m = re.match(
            r"^(?:(?:\w+\s+)?(\w+)\s*=\s*)?(?:(\w+)\s*->\s*)?(\w+)\.(\w+)\s*(\(.*?\))?\s*(\{)?$",
            line,
        )
        if m:
            var, caller, target, method, params, block = m.groups()
            src = caller or current()
            message(src, target, f"{method}{params or '()'}", "->>")
            if block:
                callers.append(target)
                opened.append(("call", target, var or ""))
            elif var:
                message(target, src, var, "-->>")
    while opened:
        kind, _, _ = opened.pop()
        if kind != "call":
            sd.events.append(SeqBlock("end"))
    return sd, title


def render_zenuml_svg(source: str, theme: dict[str, str] | None = None) -> str:
    sd, title = parse_zenuml(source)
    svg = render_sequence_svg(sd, theme)
    return _with_title(svg, title, _tokens(theme)) if title else svg


def render_state_svg(sd: StateDiagram, theme: dict[str, str] | None = None) -> str:
    """Render a state diagram to SVG via the flowchart layout engine."""
    if not sd.states:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    fc = Flowchart(direction=sd.direction if sd.direction in ("LR", "TB", "TD") else "LR")
    for tr in sd.transitions:
        ends: list[str] = []
        for name, marker in ((tr.src, "__start"), (tr.dst, "__end")):
            if name == "[*]":
                fc.nodes.setdefault(
                    marker, Node(marker, "", "start" if marker == "__start" else "end")
                )
                ends.append(marker)
            else:
                fc.nodes.setdefault(name, Node(name, name, "rounded"))
                ends.append(name)
        fc.edges.append(Edge(ends[0], ends[1], tr.label))
    return render_svg(fc, theme)


# ---------------------------------------------------------------------------
# HTML integration
# ---------------------------------------------------------------------------

_MERMAID_BLOCK_RE = re.compile(
    r'<pre><code\s+class="language-mermaid">(.*?)</code></pre>',
    re.DOTALL,
)


class UnsupportedDiagramError(ValueError):
    """Raised for Mermaid diagram types this renderer cannot draw."""


# Mermaid diagram keywords with no renderer here; the original code block is kept.
# Every current Mermaid type renders, so this is empty until Mermaid adds another.
_UNSUPPORTED_TYPES: tuple[str, ...] = ()


_NAMED_THEMES: dict[str, dict[str, str]] = {
    "default": {},
    "dark": {"mode": "dark"},
    "neutral": {"primary": "#4b5563", "accent": "#6b7280"},
    "forest": {"primary": "#2f6f3e", "accent": "#5a9e4b"},
    "base": {},
}


def _diagram_config(source: str) -> dict:
    """Mermaid config from a front-matter ``config:`` block and ``%%{init: …}%%`` directives."""
    import yaml

    text = source.strip()
    config: dict = {}

    def merge(into: dict, new: dict) -> None:
        for key, value in new.items():
            if isinstance(value, dict) and isinstance(into.get(key), dict):
                merge(into[key], value)
            else:
                into[key] = value

    fm = re.match(r"^---\s*\n(.*?)\n---[ \t]*\n", text + "\n", re.DOTALL)
    if fm:
        try:
            data = yaml.safe_load(fm.group(1)) or {}
        except yaml.YAMLError:
            data = {}
        if isinstance(data, dict):
            if isinstance(data.get("config"), dict):
                merge(config, data["config"])
            if data.get("title"):
                config["title"] = str(data["title"])
    for m in re.finditer(r"%%\{\s*(?:init|initialize)\s*:\s*(\{.*?\})\s*\}%%", text, re.DOTALL):
        raw = m.group(1)
        for candidate in (raw, raw.replace("'", '"')):
            try:
                data = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(data, dict):
                merge(config, data)
            break
    return config


def _config_theme(config: dict) -> dict[str, str]:
    """Theme overrides from a Mermaid config (named theme, themeVariables, autoFit)."""
    out: dict[str, str] = dict(_NAMED_THEMES.get(str(config.get("theme", "")).lower(), {}))
    variables = config.get("themeVariables") or {}
    if isinstance(variables, dict):
        mapping = {
            "primaryColor": "primary",
            "secondaryColor": "accent",
            "primaryBorderColor": "node_stroke",
            "primaryTextColor": "body",
            "textColor": "body",
            "lineColor": "edge",
            "fontFamily": "font",
            "background": "surface",
        }
        for key, target in mapping.items():
            value = variables.get(key)
            if isinstance(value, str) and value.strip():
                out[target] = value.strip()
        if variables.get("darkMode") is True:
            out["mode"] = "dark"
    flow = config.get("flowchart")
    if isinstance(flow, dict) and flow.get("autoFit") is False:
        out["auto_fit"] = "0"
    return out


def _with_title(svg: str, title: str, t: dict[str, str]) -> str:
    """Prepend a front-matter title above a diagram that has none of its own."""
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if not m:
        return svg
    width, height = float(m.group(1)), float(m.group(2))
    width = max(width, _text_w(title, _FS_TITLE, 600) + 4)
    body = svg[svg.index(">") + 1 : svg.rindex("</svg>")]
    head = _svg_text(0, _FS_TITLE, title, t, _FS_TITLE, weight=600)
    return _svg_root(
        width,
        height + _FS_TITLE + 12,
        [head, f'<g transform="translate(0,{_FS_TITLE + 12:g})">', body, "</g>"],
        t["font"],
    )


def _strip_preamble(source: str) -> str:
    """Drop a YAML front-matter block and ``%%{init: ...}%%`` directives before the diagram."""
    text = source.strip()
    fm = re.match(r"^---\s*\n.*?\n---[ \t]*\n", text + "\n", re.DOTALL)
    if fm:
        text = text[fm.end() :]
    return re.sub(r"^\s*%%\{.*?\}%%[ \t]*\n?", "", text, flags=re.DOTALL).strip()


def parse_usecase(source: str) -> Flowchart:
    """Translate a use case diagram onto the flowchart model."""
    fc = Flowchart(direction="LR")
    boundary: Subgraph | None = None
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^usecase(-beta)?\s*$", line, re.I):
            continue
        line = re.sub(r"\s*>\s*(:::[\w-]+)?$", r"\1", line)  # visible stereotype marker
        m = re.match(r"^direction\s+(TB|TD|BT|LR|RL)$", line, re.I)
        if m:
            fc.direction = {"TB": "TD", "BT": "TD"}.get(m.group(1).upper(), m.group(1).upper())
            continue
        m = re.match(
            r'^systemBoundary\s+(?:"([^"]+)"|([\w-]+)\s*(?:[\[(]"?([^"\])]*)"?[\])])?)', line
        )
        if m:
            label = m.group(1) or m.group(3) or m.group(2)
            sid = _slug(m.group(1)) if m.group(1) else m.group(2)
            boundary = Subgraph(id=sid, label=label)
            fc.subgraphs.append(boundary)
            continue
        if line == "end":
            boundary = None
            continue
        if (
            line.startswith(("classDef ", "class ", "style ", "linkStyle ", "click "))
            or re.match(r"^[\w-]+@\{", line)
            and "-" not in line.split("@", 1)[0]
        ):
            continue
        before = set(fc.nodes)
        m = re.match(r"^(\S+)\s+\.\.>\s*:\s*(include|extend)\s+(\S+)$", line)
        if m:
            a, b = _ensure_node(fc, m.group(1)), _ensure_node(fc, m.group(3))
            fc.edges.append(Edge(a, b, f"«{m.group(2)}»", "dotted", "arrow"))
        elif "--|>" in line:
            a, _, b = line.partition("--|>")
            fc.edges.append(
                Edge(
                    _ensure_node(fc, a.strip()),
                    _ensure_node(fc, b.strip()),
                    "",
                    "solid",
                    "triangle",
                )
            )
        elif any(
            True for _ in _EDGE_RE.finditer(_mask(re.sub(r"\b[\w-]+@(?=[-.<o x])", "", line)))
        ):
            _parse_edge_line(fc, re.sub(r"\b[\w-]+@(?=[-.<ox])", "", line))
        else:
            am = re.match(r"^actor\s+(.+)$", line)
            token = am.group(1) if am else line
            qm = re.match(r'^"([^"]+)"$', token)
            if qm:
                token = f'{_slug(qm.group(1))}("{qm.group(1)}")'
            nid = _ensure_node(fc, token)
            if nid in fc.nodes:
                node = fc.nodes[nid]
                if am:
                    node.shape = "actor"
                elif node.shape == "rounded":
                    node.shape = "ellipse"
        for nid in fc.nodes:
            if nid not in before:
                node = fc.nodes[nid]
                if node.shape == "rounded":
                    node.shape = "ellipse"
                if boundary is not None:
                    boundary.node_ids.append(nid)
    # Undeclared bare ids used only in relations are use cases, except known actors
    for e in fc.edges:
        for nid in (e.src, e.dst):
            used = fc.nodes.get(nid)
            if used is not None and used.shape == "rect" and used.label == nid:
                used.shape = "ellipse"
    return fc


def render_usecase_svg(fc: Flowchart, theme: dict[str, str] | None = None) -> str:
    return render_svg(fc, theme)


def parse_agentflow(source: str) -> Flowchart:
    """Translate an agentflow diagram (flows, typed shapes, three edge kinds) onto the flowchart model."""
    lines_out: list[str] = []
    global_lines: list[str] = []
    collapsed: set[str] = set()
    in_global = 0
    depth_stack: list[str] = []
    direction = "TB"
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        m = re.match(r"^agentflow(?:-beta)?(?:\s+(TB|TD|BT|LR|RL))?\s*$", line, re.I)
        if m:
            direction = (m.group(1) or "TB").upper()
            continue
        m = re.match(r"^([\w-]+)@\{\s*view\s*:\s*\"?collapsed\"?\s*\}$", line)
        if m:
            collapsed.add(m.group(1))
            continue
        if line == "global":
            in_global += 1
            depth_stack.append("global")
            continue
        m = re.match(r'^flow\s+([\w-]+)\s*(?:\[\s*"?([^"\]]*)"?\s*\])?(?:@\{.*\})?$', line)
        if m:
            depth_stack.append("flow")
            target = global_lines if in_global else lines_out
            target.append(f'subgraph {m.group(1)} ["{m.group(2) or m.group(1)}"]')
            continue
        if line == "end" and depth_stack:
            kind = depth_stack.pop()
            if kind == "global":
                in_global -= 1
            else:
                (global_lines if in_global else lines_out).append("end")
            continue
        (global_lines if in_global else lines_out).append(line)
    fc = parse(
        "flowchart "
        + ("TD" if direction == "TB" else direction)
        + "\n"
        + "\n".join(global_lines + lines_out)
    )
    for e in fc.edges:
        if e.head == "cross":  # failure path
            e.css.setdefault("stroke", _CRITICAL)
    for gid in collapsed:
        sg = next((g for g in fc.subgraphs if g.id == gid), None)
        if sg is None:
            continue
        members = set(_subgraph_members(fc, sg))
        fc.nodes[gid] = Node(gid, sg.label, "subroutine")
        for e in fc.edges:
            if e.src in members:
                e.src = gid
            if e.dst in members:
                e.dst = gid
        for nid in members:
            fc.nodes.pop(nid, None)
        fc.edges = [e for e in fc.edges if e.src != e.dst]
        drop = {gid} | set(sg.children)
        fc.subgraphs = [g for g in fc.subgraphs if g.id not in drop]
        for g in fc.subgraphs:
            g.node_ids = [n for n in g.node_ids if n in fc.nodes]
            if gid in g.children:
                g.children.remove(gid)
                g.node_ids.append(gid)
    return fc


def parse_swimlanes(source: str) -> Flowchart:
    """Swimlanes are flowcharts whose top-level subgraphs are lanes."""
    lines = source.strip().splitlines()
    head = lines[0].strip() if lines else ""
    m = re.match(r"^swimlanes?(?:-beta)?(?:\s+(TB|TD|BT|LR|RL))?\s*$", head, re.I)
    direction = (m.group(1) if m and m.group(1) else "TB").upper()
    return parse(
        "flowchart "
        + ("TD" if direction in ("TB", "BT") else direction)
        + "\n"
        + "\n".join(lines[1:])
    )


def render_swimlanes_svg(fc: Flowchart, theme: dict[str, str] | None = None) -> str:
    """Render lanes as bands; columns (or rows) follow the flow's ranks."""
    t = _tokens(theme)
    if not fc.nodes:
        return _svg_root(120, 40, _svg_text(0, 20, "No steps", t, color=t["ink2"]), t["font"])
    horizontal = fc.direction in ("LR", "RL")
    # Size nodes the way the flowchart layout does
    probe = Flowchart(direction=fc.direction, nodes=dict(fc.nodes), edges=fc.edges)
    layout(probe, t)
    levels = _compute_levels(fc)
    child_ids = {c for sg in fc.subgraphs for c in sg.children}
    lanes = [sg for sg in fc.subgraphs if sg.id not in child_ids]
    lane_of: dict[str, int] = {}
    for i, sg in enumerate(lanes):
        for nid in _subgraph_members(fc, sg):
            lane_of.setdefault(nid, i)
    loose = [n for n in fc.nodes if n not in lane_of]
    if loose:
        lanes.append(Subgraph(id="__other", label=""))
        for n in loose:
            lane_of[n] = len(lanes) - 1

    n_levels = max(levels.values()) + 1
    major_size = [0.0] * n_levels  # column width (LR) or row height (TD)
    for nid, node in fc.nodes.items():
        lvl = levels[nid]
        major_size[lvl] = max(major_size[lvl], node.w if horizontal else node.h)
    # A label sits on its edge's last segment, in the gap just before the target
    gap_need: dict[int, float] = defaultdict(lambda: 56.0)
    for e in fc.edges:
        if e.label:
            ls, ld = levels[e.src], levels[e.dst]
            gap = ld - 1 if ld > ls else ld
            gap_need[gap] = max(gap_need[gap], _text_w(e.label, _FS_SM) + 30)
    header = max(_text_w(sg.label, _FS, 600) for sg in lanes) + 28 if horizontal else 36.0
    major_pos = []
    acc = header + 20
    for lvl, size in enumerate(major_size):
        major_pos.append(acc)
        acc += size + (gap_need[lvl] if lvl < n_levels - 1 else 0.0)
    major_end = acc + 20

    gap_minor, pad = 14.0, 16.0
    lane_start, lane_extent = [], []
    acc = 0.0
    for i in range(len(lanes)):
        stacks: dict[int, float] = defaultdict(float)
        counts: dict[int, int] = defaultdict(int)
        for nid, lane in lane_of.items():
            if lane == i:
                node = fc.nodes[nid]
                stacks[levels[nid]] += (node.h if horizontal else node.w) + gap_minor
                counts[levels[nid]] += 1
        extent = max(stacks.values(), default=40.0) - gap_minor + 2 * pad
        extent = max(extent, 64.0 if horizontal else _text_w(lanes[i].label, _FS, 600) + 2 * pad)
        lane_start.append(acc)
        lane_extent.append(extent)
        acc += extent
    lane_total = acc

    # Place nodes: centred in their rank, stacked inside their lane
    for i in range(len(lanes)):
        by_level: dict[int, list[str]] = defaultdict(list)
        for nid in fc.nodes:
            if lane_of[nid] == i:
                by_level[levels[nid]].append(nid)
        for lvl, nids in by_level.items():
            total = sum(
                (fc.nodes[n].h if horizontal else fc.nodes[n].w) for n in nids
            ) + gap_minor * (len(nids) - 1)
            cursor = lane_start[i] + (lane_extent[i] - total) / 2
            for n in nids:
                node = fc.nodes[n]
                minor_size = node.h if horizontal else node.w
                major = major_pos[lvl] + (major_size[lvl] - (node.w if horizontal else node.h)) / 2
                if horizontal:
                    node.x, node.y = major, cursor
                else:
                    node.x, node.y = cursor, major
                cursor += minor_size + gap_minor

    parts: list[str] = []
    for i, sg in enumerate(lanes):
        fill = _tint(t["primary"], 0.965 if i % 2 == 0 else 0.985, t)
        if horizontal:
            parts.append(
                f'<rect x="0" y="{lane_start[i]:g}" width="{major_end:g}" height="{lane_extent[i]:g}" fill="{fill}"/>'
            )
            parts.append(
                f'<rect x="0" y="{lane_start[i]:g}" width="{header:g}" height="{lane_extent[i]:g}" '
                f'fill="{_tint(t["primary"], 0.9, t)}"/>'
            )
            parts.append(
                _svg_text(
                    12, lane_start[i] + lane_extent[i] / 2 + 4, sg.label, t, _FS, t["ink"], 600
                )
            )
        else:
            parts.append(
                f'<rect x="{lane_start[i]:g}" y="0" width="{lane_extent[i]:g}" height="{major_end:g}" fill="{fill}"/>'
            )
            parts.append(
                f'<rect x="{lane_start[i]:g}" y="0" width="{lane_extent[i]:g}" height="{header:g}" '
                f'fill="{_tint(t["primary"], 0.9, t)}"/>'
            )
            parts.append(
                _svg_text(
                    lane_start[i] + lane_extent[i] / 2,
                    23,
                    sg.label,
                    t,
                    _FS,
                    t["ink"],
                    600,
                    "middle",
                )
            )
        if i:
            if horizontal:
                parts.append(
                    f'<line x1="0" y1="{lane_start[i]:g}" x2="{major_end:g}" y2="{lane_start[i]:g}" stroke="{t["subgraph_stroke"]}" stroke-width="1"/>'
                )
            else:
                parts.append(
                    f'<line x1="{lane_start[i]:g}" y1="0" x2="{lane_start[i]:g}" y2="{major_end:g}" stroke="{t["subgraph_stroke"]}" stroke-width="1"/>'
                )
    parts.insert(0, _make_arrow_defs(t))
    for e in fc.edges:
        parts.append(
            _render_edge(
                fc.nodes[e.src], fc.nodes[e.dst], e.label, fc.direction, t, e.style, edge=e
            )
        )
    for node in fc.nodes.values():
        parts.append(_render_node(node, t))
    width, height = (major_end, lane_total) if horizontal else (lane_total, major_end)
    column = float(t.get("column_px") or 640)
    if horizontal and width > column and t.get("auto_fit") != "0":
        # Too wide for the page: lanes become columns and the flow runs downwards
        fc.direction = "TD"
        return render_swimlanes_svg(fc, theme)
    return _svg_root(width, height, parts, t["font"])


# ---------------------------------------------------------------------------
# Tree view
# ---------------------------------------------------------------------------


def parse_treeview(source: str) -> list[TreeRow]:
    """Parse a treeView (indentation or box-drawing input) into rows with depths."""
    rows: list[TreeRow] = []
    raw = [
        line for line in source.splitlines() if line.strip() and not line.strip().startswith("%%")
    ]
    if raw and re.match(r"^\s*treeView(-beta)?\s*$", raw[0], re.I):
        raw = raw[1:]
    box = any(re.search(r"[├└┣┗]", line) for line in raw)
    indents: list[int] = []
    for line in raw:
        if box:
            m = re.search(r"[├└┣┗][─━]+\s*", line)
            if m:
                depth = m.start() // 4 + 1
                text = line[m.end() :]
            else:
                depth, text = 0, line.strip()
        else:
            indent = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())
            while indents and indents[-1] > indent:
                indents.pop()
            if not indents or indents[-1] < indent:
                indents.append(indent)
            depth = len(indents) - 1
            text = line.strip()
        desc = ""
        if "##" in text:
            text, desc = text.split("##", 1)
        classes = re.findall(r":::([\w-]+)", text)
        icon_m = re.search(r"icon\(([^)]*)\)", text)
        text = re.sub(r":::[\w-]+|icon\([^)]*\)", "", text).strip()
        rows.append(
            TreeRow(
                _unquote(text),
                depth,
                _unquote(text).endswith("/"),
                desc.strip(),
                "highlight" in classes,
                icon_m.group(1) if icon_m else None,
            )
        )
    return rows


def render_treeview_svg(rows: list[TreeRow], theme: dict[str, str] | None = None) -> str:
    """Render a directory-style tree with connector lines."""
    t = _tokens(theme)
    if not rows:
        return _svg_root(120, 40, _svg_text(0, 20, "Empty tree", t, color=t["ink2"]), t["font"])
    conf = _config_section("treeView")
    show_icons = conf.get("showIcons") is True
    row_h, indent = 24.0, 20.0
    parts: list[str] = []
    width = 0.0
    line_color = t["baseline"]
    for i, row in enumerate(rows):
        y = 12 + i * row_h
        x = 6 + row.depth * indent
        # Connector: from the parent's column down to this row
        if row.depth > 0:
            px = 6 + (row.depth - 1) * indent + 5
            parent_i = (
                max(j for j in range(i) if rows[j].depth == row.depth - 1)
                if any(rows[j].depth == row.depth - 1 for j in range(i))
                else 0
            )
            py = 12 + parent_i * row_h + 8
            parts.append(
                f'<path d="M {px:g},{py:g} V {y - 4:g} Q {px:g},{y:g} {px + 4:g},{y:g} H {x - 3:g}" '
                f'fill="none" stroke="{line_color}" stroke-width="1"/>'
            )
        tx = x + 2
        show = show_icons and row.icon not in ("", "none")
        if show or row.icon not in (None, "", "none"):
            if row.is_dir:
                parts.append(
                    f'<path d="M {tx:g},{y - 5:g} h 5 l 2,2 h 7 v 9 h -14 Z" fill="{_tint(t["accent"], 0.6, t)}" '
                    f'stroke="{t["accent"]}" stroke-width="1"/>'
                )
            else:
                parts.append(
                    f'<path d="M {tx + 1:g},{y - 6:g} h 8 l 4,4 v 10 h -12 Z" fill="{t["card"]}" '
                    f'stroke="{t["chrome"]}" stroke-width="1"/>'
                )
            tx += 20
        label = row.label
        weight = 600 if row.is_dir else 400
        lw = _text_w(label, _FS, weight)
        if row.highlight:
            parts.append(
                f'<rect x="{tx - 4:g}" y="{y - 10:g}" width="{lw + 8:g}" height="19" rx="4" '
                f'fill="{_tint(t["accent"], 0.82, t)}"/>'
            )
        parts.append(_svg_text(tx, y + 4, label, t, _FS, t["ink"], weight))
        end = tx + lw
        if row.desc:
            parts.append(
                _svg_text(
                    end + 10, y + 4, row.desc, t, _FS_SM, t["ink2"], extra=' font-style="italic"'
                )
            )
            end += 10 + _text_w(row.desc, _FS_SM)
        width = max(width, end)
    return _svg_root(width + 8, 12 + len(rows) * row_h - 4, parts, t["font"])


# ---------------------------------------------------------------------------
# Ishikawa (fishbone)
# ---------------------------------------------------------------------------


def parse_ishikawa(source: str) -> tuple[str, list[MindNode]]:
    """First line is the effect; indented lines are categories and their causes."""
    lines = [
        line for line in source.splitlines() if line.strip() and not line.strip().startswith("%%")
    ]
    if lines and re.match(r"^\s*ishikawa(-beta)?\s*$", lines[0], re.I):
        lines = lines[1:]
    if not lines:
        return "", []
    effect = lines[0].strip()
    root = MindNode(effect)
    stack: list[tuple[int, MindNode]] = []
    base = None
    for line in lines[1:]:
        indent = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())
        if base is None:
            base = indent
        node = MindNode(line.strip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        (stack[-1][1].children if stack else root.children).append(node)
        stack.append((indent, node))
    return effect, root.children


def render_ishikawa_svg(
    effect: str, categories: list[MindNode], theme: dict[str, str] | None = None
) -> str:
    """Render a fishbone: effect at the head, categories as bones above and below the spine."""
    t = _tokens(theme)
    if not effect:
        return _svg_root(120, 40, _svg_text(0, 20, "No effect", t, color=t["ink2"]), t["font"])
    top = categories[0::2]
    bottom = categories[1::2]

    def cause_lines(cat: MindNode) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []

        def walk(node: MindNode, depth: int) -> None:
            out.append((node.label, depth))
            for c in node.children:
                walk(c, depth + 1)

        for c in cat.children:
            walk(c, 0)
        return out

    row = 17.0
    col_w = max(
        [_text_w(c.label, _FS, 600) + 30 for c in categories]
        + [
            _text_w(text, 11 if d == 0 else 10) + 16 * d + 40
            for c in categories
            for text, d in cause_lines(c)
        ]
        + [150.0]
    )
    half_h = max([len(cause_lines(c)) * row + 46 for c in categories] + [90.0])
    n_cols = max(len(top), len(bottom), 1)
    head_w = min(max(_text_w(effect, 12.5, 600) + 28, 120.0), 200.0)
    head_lines = _wrap_lines(effect, head_w - 20, 12.5)
    spine_y = half_h + 8
    spine_x1 = 20 + n_cols * col_w + 10
    parts: list[str] = []
    parts.append(
        f'<line x1="10" y1="{spine_y:g}" x2="{spine_x1:g}" y2="{spine_y:g}" stroke="{t["ink2"]}" '
        f'stroke-width="2.5" stroke-linecap="round"/>'
    )
    head_h = max(44.0, 16 * len(head_lines) + 18)
    parts.append(
        f'<path d="M {spine_x1:g},{spine_y - head_h / 2:g} H {spine_x1 + head_w - 16:g} '
        f"Q {spine_x1 + head_w:g},{spine_y:g} {spine_x1 + head_w - 16:g},{spine_y + head_h / 2:g} "
        f'H {spine_x1:g} Z" fill="{t["term_fill"]}"/>'
    )
    for i, text in enumerate(head_lines):
        parts.append(
            _svg_text(
                spine_x1 + 12,
                spine_y - (len(head_lines) - 1) * 8 + 4.5 + i * 16,
                text,
                t,
                12.5,
                t["term_text"],
                600,
            )
        )
    palette = _palette(t)
    for side, cats in ((-1, top), (1, bottom)):
        for k, cat in enumerate(cats):
            color = palette[(2 * k + (0 if side < 0 else 1)) % len(palette)]
            joint_x = 20 + (k + 1) * col_w - 10
            end_y = spine_y + side * (half_h - 24)
            end_x = joint_x - (half_h - 24) * 0.45
            parts.append(
                f'<line x1="{end_x:.1f}" y1="{end_y:.1f}" x2="{joint_x:.1f}" y2="{spine_y:g}" '
                f'stroke="{_tint(color, 0.25, t)}" stroke-width="2" stroke-linecap="round"/>'
            )
            label_y = end_y - 8 if side < 0 else end_y + 18
            lw = _text_w(cat.label, _FS, 600) + 16
            parts.append(
                f'<rect x="{end_x - lw / 2:.1f}" y="{label_y - 14:.1f}" width="{lw:.1f}" height="20" rx="10" '
                f'fill="{_tint(color, 0.85, t)}" stroke="{_tint(color, 0.4, t)}" stroke-width="1"/>'
            )
            parts.append(_svg_text(end_x, label_y, cat.label, t, _FS, t["ink"], 600, "middle"))
            lines = cause_lines(cat)
            for j, (text, depth) in enumerate(lines):
                # Walk along the bone so causes read top to bottom: from the label
                # toward the spine above it, from the spine toward the label below
                f = (j + 1) / (len(lines) + 1)
                if side > 0:
                    f = 1 - f
                by = end_y + (spine_y - end_y) * f
                bx = end_x + (joint_x - end_x) * f
                size = 11.0 if depth == 0 else 10.0
                tx = bx - 6 - depth * 14
                if depth == 0:
                    parts.append(
                        f'<line x1="{tx - _text_w(text, size) - 2:.1f}" y1="{by + 3:.1f}" x2="{bx:.1f}" y2="{by + 3:.1f}" '
                        f'stroke="{_tint(color, 0.55, t)}" stroke-width="1"/>'
                    )
                parts.append(
                    _svg_text(
                        tx, by, text, t, size, t["ink"] if depth == 0 else t["ink2"], anchor="end"
                    )
                )
    width = spine_x1 + head_w + 6
    return _svg_root(width, spine_y * 2 + 8, parts, t["font"])


def parse_venn(source: str) -> dict:
    """Sets, unions (with labels, sizes and text children) and style overrides."""
    title = ""
    sets: list[dict] = []
    unions: list[dict] = []
    styles: dict[str, dict[str, str]] = {}
    last: dict | None = None
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^venn(-beta)?$", line, re.I):
            continue
        if line.startswith(("accTitle", "accDescr")):
            continue
        m = re.match(r"^title\s+(.+)$", line)
        if m:
            title = _unquote(m.group(1).strip())
            continue
        m = re.match(
            r'^(set|union|text)\s+(.+?)(?:\[\s*"?([^"\]]*)"?\s*\])?\s*(?::\s*([\d.]+))?$', line
        )
        if m:
            kind, ident, label, size = m.groups()
            if kind == "text":
                item = {
                    "id": ident.strip(),
                    "label": label if label is not None else _unquote(ident.strip()),
                }
                if last is not None:
                    last["texts"].append(item)
                continue
            ids = [_unquote(p.strip()) for p in ident.split(",") if p.strip()]
            entry = {
                "id": ",".join(ids),
                "ids": ids,
                "label": label if label is not None else ("" if kind == "union" else ids[0]),
                "size": float(size) if size else None,
                "texts": [],
            }
            (sets if kind == "set" else unions).append(entry)
            last = entry
            continue
        m = re.match(r"^style\s+(\S+)\s+(.+)$", line)
        if m:
            key = ",".join(_unquote(p.strip()) for p in m.group(1).split(","))
            css = styles.setdefault(key, {})
            for decl in m.group(2).split(","):
                if ":" in decl:
                    k, v = decl.split(":", 1)
                    css[k.strip()] = v.strip()
    return {"title": title, "sets": sets, "unions": unions, "styles": styles}


def render_venn_svg(data: dict, theme: dict[str, str] | None = None) -> str:
    """Overlapping translucent circles; radius follows the optional set size."""
    t = _tokens(theme)
    sets = data["sets"]
    if not sets:
        return _svg_root(120, 40, _svg_text(0, 20, "No sets", t, color=t["ink2"]), t["font"])
    n = len(sets)
    sizes = [s["size"] or 10.0 for s in sets]
    big = max(sizes)
    base = 104.0 if n <= 3 else 86.0
    radii = [base * max(0.55, math.sqrt(sz / big)) for sz in sizes]
    centres: list[tuple[float, float]] = []
    if n == 1:
        centres = [(0.0, 0.0)]
    elif n == 2:
        pair = next((u for u in data["unions"] if len(u["ids"]) == 2), None)
        frac = 0.32
        if pair and pair["size"] and min(sizes):
            frac = min(0.85, max(0.12, pair["size"] / min(sizes) * 1.3))
        d = radii[0] + radii[1] - 2 * min(radii) * frac
        centres = [(-d / 2, 0.0), (d / 2, 0.0)]
    else:
        ring = (base * 0.62) / math.sin(math.pi / n) if n > 3 else base * 0.66
        for i in range(n):
            ang = -math.pi / 2 + 2 * math.pi * i / n + (math.pi / n if n == 3 else 0)
            if n == 3:
                ang = [-math.pi * 5 / 6, -math.pi / 6, math.pi / 2][i]
            centres.append((ring * math.cos(ang), ring * math.sin(ang)))
    index = {s["ids"][0]: i for i, s in enumerate(sets)}
    gx = sum(c[0] for c in centres) / n
    gy = sum(c[1] for c in centres) / n
    palette = _palette(t)
    styles = data["styles"]

    shapes: list[str] = []
    labels: list[str] = []
    for i, s in enumerate(sets):
        cx, cy = centres[i]
        css = styles.get(s["id"], {})
        color = css.get("fill", palette[i % len(palette)])
        stroke = css.get("stroke", color)
        opacity = css.get("fill-opacity", "0.2")
        shapes.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radii[i]:.1f}" fill="{color}" fill-opacity="{opacity}" '
            f'stroke="{stroke}" stroke-width="{css.get("stroke-width", "1.5")}"/>'
        )
        # Label in the part of the circle furthest from the group's centre
        dx, dy = cx - gx, cy - gy
        dist = math.hypot(dx, dy)
        ux, uy = (dx / dist, dy / dist) if dist > 1 else (0.0, -1.0)
        if n == 1:
            ux, uy = 0.0, 0.0
        reach = radii[i] * (0.52 if n > 1 else 0.0)
        lx, ly = cx + ux * reach, cy + uy * reach
        lines = [(s["label"], _FS + 1, 600, css.get("color", t["ink"]))]
        lines += [
            (x["label"], _FS_SM, 400, styles.get(x["id"], {}).get("color", t["ink2"]))
            for x in s["texts"]
        ]
        labels += _venn_label_block(lx, ly, lines, t)
    for u in data["unions"]:
        members = [index[i] for i in u["ids"] if i in index]
        if len(members) < 2:
            continue
        ux = sum(centres[k][0] for k in members) / len(members)
        uy = sum(centres[k][1] for k in members) / len(members)
        if 2 <= len(members) < n:
            # push a partial overlap away from the sets it leaves out
            ox = sum(centres[k][0] for k in range(n) if k not in members) / (n - len(members))
            oy = sum(centres[k][1] for k in range(n) if k not in members) / (n - len(members))
            vx, vy = ux - ox, uy - oy
            d = math.hypot(vx, vy) or 1.0
            push = min(radii) * (0.4 if n == 3 else 0.12)
            ux, uy = ux + vx / d * push, uy + vy / d * push
        css = styles.get(u["id"], {})
        lines = [(u["label"], _FS, 600, css.get("color", t["ink"]))] if u["label"] else []
        lines += [
            (x["label"], _FS_SM, 400, styles.get(x["id"], {}).get("color", t["ink2"]))
            for x in u["texts"]
        ]
        labels += _venn_label_block(ux, uy, lines, t)

    x0 = min(c[0] - r for c, r in zip(centres, radii)) - 8
    x1 = max(c[0] + r for c, r in zip(centres, radii)) + 8
    y0 = min(c[1] - r for c, r in zip(centres, radii)) - 8
    y1 = max(c[1] + r for c, r in zip(centres, radii)) + 8
    title_parts, title_h = _chart_title(data["title"], t)
    body = [f'<g transform="translate({-x0:.1f},{title_h - y0:.1f})">', *shapes, *labels, "</g>"]
    return _svg_root(x1 - x0, y1 - y0 + title_h, title_parts + body, t["font"])


def _venn_label_block(
    x: float, y: float, lines: list[tuple[str, float, int, str]], t: dict[str, str]
) -> list[str]:
    """Centre a stack of text lines on (x, y)."""
    if not lines:
        return []
    heights = [size * 1.35 for _, size, _, _ in lines]
    cursor = y - sum(heights) / 2
    out = []
    for (text, size, weight, color), h in zip(lines, heights):
        cursor += h
        out.append(_svg_text(x, cursor - h * 0.28, text, t, size, color, weight, "middle"))
    return out


# ---------------------------------------------------------------------------
# Cynefin
# ---------------------------------------------------------------------------

_CYNEFIN_DOMAINS = {
    "complex": ("Complex", "Probe → Sense → Respond", "Emergent practice"),
    "complicated": ("Complicated", "Sense → Analyse → Respond", "Good practice"),
    "chaotic": ("Chaotic", "Act → Sense → Respond", "Novel practice"),
    "clear": ("Clear", "Sense → Categorise → Respond", "Best practice"),
    "confusion": ("Confusion", "", ""),
}


def parse_cynefin(source: str) -> dict:
    title = ""
    items: dict[str, list[str]] = {k: [] for k in _CYNEFIN_DOMAINS}
    transitions: list[tuple[str, str, str]] = []
    current: str | None = None
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or re.match(r"^cynefin(-beta)?$", line, re.I):
            continue
        if line.startswith(("accTitle", "accDescr")):
            continue
        m = re.match(r"^title\s+(.+)$", line)
        if m:
            title = _unquote(m.group(1).strip())
            continue
        m = re.match(r"^(\w+)\s*-->\s*(\w+)\s*(?::\s*(.+))?$", line)
        if m:
            a, b = m.group(1).lower(), m.group(2).lower()
            if a in _CYNEFIN_DOMAINS and b in _CYNEFIN_DOMAINS and a != b:
                transitions.append((a, b, _unquote((m.group(3) or "").strip())))
            continue
        if line.lower() in _CYNEFIN_DOMAINS:
            current = line.lower()
            continue
        if current:
            items[current].append(_unquote(line))
    return {"title": title, "items": items, "transitions": transitions}


def render_cynefin_svg(data: dict, theme: dict[str, str] | None = None) -> str:
    """Four domains split by wavy boundaries, the cliff, confusion at the centre."""
    t = _tokens(theme)
    conf = _config_section("cynefin")
    show_desc = conf.get("showDomainDescriptions", True) is not False
    amp = float(conf.get("boundaryAmplitude", 6))
    items = data["items"]
    pal = _palette(t)
    tones = {"complex": pal[0], "complicated": pal[1], "chaotic": pal[3], "clear": pal[2]}

    def badge_w(text: str) -> float:
        return _text_w(text, _FS_SM) + 18

    widest = max(
        [badge_w(x) for k in tones for x in items[k]]
        + [_text_w(_CYNEFIN_DOMAINS[k][1], _FS_SM) for k in tones]
        + [150.0]
    )
    qw = max(widest + 70, 250.0)
    tallest = max(len(items[k]) for k in tones)
    qh = max(170.0, 64 + (24 if show_desc else 0) + tallest * 26 + 70)
    W, H = 2 * qw, 2 * qh
    title_parts, title_h = _chart_title(data["title"], t)

    def wave(x0: float, y0: float, x1: float, y1: float, seed: float) -> str:
        steps = 24
        pts = []
        length = math.hypot(x1 - x0, y1 - y0)
        nx, ny = -(y1 - y0) / length, (x1 - x0) / length
        for i in range(steps + 1):
            f = i / steps
            w = amp * math.sin(f * math.pi * 3 + seed) * math.sin(f * math.pi)
            pts.append((x0 + (x1 - x0) * f + nx * w, y0 + (y1 - y0) * f + ny * w))
        return "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

    parts: list[str] = [f'<g transform="translate(0,{title_h:g})">']
    cells = {"complex": (0, 0), "complicated": (qw, 0), "chaotic": (0, qh), "clear": (qw, qh)}
    for key, (x, y) in cells.items():
        parts.append(
            f'<rect x="{x:g}" y="{y:g}" width="{qw:g}" height="{qh:g}" fill="{_tint(tones[key], 0.9, t)}"/>'
        )
    border = t["chrome"]
    parts.append(
        f'<rect x="0.5" y="0.5" width="{W - 1:g}" height="{H - 1:g}" rx="10" fill="none" stroke="{border}"/>'
    )
    parts.append(
        f'<path d="{wave(0, qh, W, qh, 0.7)}" fill="none" stroke="{t["ink2"]}" stroke-width="1.5"/>'
    )
    parts.append(
        f'<path d="{wave(qw, 0, qw, qh + 30, 2.1)}" fill="none" stroke="{t["ink2"]}" stroke-width="1.5"/>'
    )
    # The cliff between Clear and Chaotic: a heavier fold at the foot of the divide
    parts.append(
        f'<path d="M {qw:g},{qh + 30:g} C {qw + 4:g},{H - 50:g} {qw + 18:g},{H - 22:g} {qw - 8:g},{H - 6:g}" '
        f'fill="none" stroke="{t["ink"]}" stroke-width="2.6" stroke-linecap="round"/>'
    )

    for key, (x, y) in cells.items():
        name, model, practice = _CYNEFIN_DOMAINS[key]
        right = key in ("complicated", "clear")
        top = key in ("complex", "complicated")
        tx = x + qw - 20 if right else x + 20
        anchor = "end" if right else "start"
        ty = y + 32 if top else y + qh - (58 if show_desc else 22)
        color = (
            _mix(tones[key], t["ink"], 0.45)
            if t.get("mode") != "dark"
            else _tint(tones[key], 0.4, t)
        )
        parts.append(_svg_text(tx, ty, name, t, 15, color, 700, anchor))
        if show_desc:
            parts.append(_svg_text(tx, ty + 18, model, t, _FS_SM, t["ink2"], 400, anchor))
            parts.append(
                _svg_text(
                    tx, ty + 33, practice, t, _FS_SM, t["ink2"], 400, anchor, ' font-style="italic"'
                )
            )
        cursor = (ty + (46 if show_desc else 20)) if top else y + 22
        for text in items[key]:
            bw = badge_w(text)
            bx = tx - bw if right else tx
            parts.append(
                f'<rect x="{bx:.1f}" y="{cursor:.1f}" width="{bw:.1f}" height="20" rx="10" fill="{t["card"]}" '
                f'stroke="{_tint(tones[key], 0.45, t)}" stroke-width="1"/>'
            )
            parts.append(
                _svg_text(bx + bw / 2, cursor + 13.8, text, t, _FS_SM, t["ink"], 400, "middle")
            )
            cursor += 26

    centres = {
        "complex": (qw * 0.55, qh * 0.62),
        "complicated": (qw * 1.45, qh * 0.62),
        "chaotic": (qw * 0.55, qh * 1.38),
        "clear": (qw * 1.45, qh * 1.38),
        "confusion": (qw, qh),
    }
    conf_items = items["confusion"]
    if conf_items or any("confusion" in tr[:2] for tr in data["transitions"]):
        shown = conf_items[:3]
        extra = len(conf_items) - len(shown)
        rows = ["Confusion", *shown] + ([f"+{extra} more"] if extra else [])
        ew = max([_text_w(r, _FS_SM) for r in rows] + [70.0]) / 2 + 26
        eh = 18 + len(rows) * 8
        parts.append(
            f'<ellipse cx="{qw:g}" cy="{qh:g}" rx="{ew:.1f}" ry="{eh:.1f}" fill="{t["card"]}" '
            f'stroke="{t["ink2"]}" stroke-width="1.2" stroke-dasharray="4 3"/>'
        )
        top_y = qh - len(rows) * 7.5 + 10
        for i, r in enumerate(rows):
            parts.append(
                _svg_text(
                    qw,
                    top_y + i * 15,
                    r,
                    t,
                    _FS_SM if i else _FS,
                    t["ink"] if i else t["ink2"],
                    600 if i == 0 else 400,
                    "middle",
                )
            )

    if data["transitions"]:
        parts.insert(0, _make_arrow_defs(t))
        for a, b, label in data["transitions"]:
            (x0, y0), (x1, y1) = centres[a], centres[b]
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            # bow the arrow away from the middle of the framework
            vx, vy = mx - qw, my - qh
            d = math.hypot(vx, vy)
            if d < 1:
                vx, vy, d = -(y1 - y0), x1 - x0, math.hypot(x1 - x0, y1 - y0) or 1.0
            cx, cy = mx + vx / d * 40, my + vy / d * 40
            # trim the ends so arrows start and stop clear of the centres
            parts.append(
                f'<path d="M {x0:.1f},{y0:.1f} Q {cx:.1f},{cy:.1f} {x1:.1f},{y1:.1f}" fill="none" '
                f'stroke="{t["ink2"]}" stroke-width="1.5" marker-end="url(#arr)"/>'
            )
            if label:
                lx, ly = 0.25 * x0 + 0.5 * cx + 0.25 * x1, 0.25 * y0 + 0.5 * cy + 0.25 * y1
                lw = _text_w(label, _FS_SM) + 12
                parts.append(
                    f'<rect x="{lx - lw / 2:.1f}" y="{ly - 9:.1f}" width="{lw:.1f}" height="17" rx="4" '
                    f'fill="{t["surface"]}" fill-opacity="0.92"/>'
                )
                parts.append(_svg_text(lx, ly + 3.8, label, t, _FS_SM, t["ink"], 500, "middle"))
    parts.append("</g>")
    return _svg_root(W, H + title_h, title_parts + parts, t["font"])


def parse_wardley(source: str) -> dict:
    """Wardley map in the OnlineWardleyMaps dialect Mermaid uses: ``[visibility, evolution]``."""
    data: dict = {
        "title": "",
        "size": (1100.0, 600.0),
        "stages": [("Genesis", 0.25), ("Custom", 0.5), ("Product", 0.75), ("Commodity", 1.0)],
        "components": {},
        "links": [],
        "evolve": [],
        "notes": [],
        "annotations": [],
        "annotation_box": None,
        "forces": [],
        "pipelines": [],
    }
    comps: dict[str, dict] = data["components"]
    pipeline: dict | None = None

    def name_of(text: str) -> str:
        return _unquote(text.strip())

    for raw_line in source.splitlines():
        line = re.sub(r"\s+%%.*$", "", raw_line).strip()
        if not line or line.startswith("%%") or re.match(r"^wardley(-beta)?$", line, re.I):
            continue
        if line.startswith(("accTitle", "accDescr")):
            continue
        if pipeline is not None:
            if line == "}":
                pipeline = None
                continue
            m = re.match(r"^component\s+(.+?)\s*\[\s*([\d.]+)\s*\]", line)
            if m:
                pipeline["items"].append((name_of(m.group(1)), float(m.group(2))))
            continue
        m = re.match(r"^title\s+(.+)$", line)
        if m:
            data["title"] = _unquote(m.group(1).strip())
            continue
        m = re.match(r"^size\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]", line)
        if m:
            data["size"] = (float(m.group(1)), float(m.group(2)))
            continue
        m = re.match(r"^evolution\s+(.+)$", line)
        if m:
            names = [p.strip() for p in m.group(1).split("->")]
            stages = []
            for i, p in enumerate(names):
                at = re.match(r"^(.*?)@([\d.]+)$", p)
                stages.append(
                    (at.group(1).strip(), float(at.group(2))) if at else (p, (i + 1) / len(names))
                )
            data["stages"] = stages
            continue
        m = re.match(r"^(component|anchor)\s+(.+?)\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\](.*)$", line)
        if m:
            kind, name, vis, evo, rest = m.groups()
            off = re.search(r"label\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]", rest)
            comps[name_of(name)] = {
                "kind": kind,
                "vis": float(vis),
                "evo": float(evo),
                "label": (float(off.group(1)), float(off.group(2))) if off else None,
                "decorators": re.findall(r"\((\w+)\)", rest),
            }
            continue
        m = re.match(r"^pipeline\s+(.+?)\s*\{$", line)
        if m:
            pipeline = {"parent": name_of(m.group(1)), "items": []}
            data["pipelines"].append(pipeline)
            continue
        m = re.match(r"^evolve\s+(.+?)\s+([\d.]+)$", line)
        if m:
            data["evolve"].append((name_of(m.group(1)), float(m.group(2))))
            continue
        m = re.match(r'^note\s+(".*?"|\S+)\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]', line)
        if m:
            data["notes"].append((_unquote(m.group(1)), float(m.group(2)), float(m.group(3))))
            continue
        m = re.match(r"^annotations\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]", line)
        if m:
            data["annotation_box"] = (float(m.group(1)), float(m.group(2)))
            continue
        m = re.match(
            r'^annotation\s+(\d+)\s*,\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]\s*(".*?"|.*)$', line
        )
        if m:
            data["annotations"].append(
                (
                    int(m.group(1)),
                    float(m.group(2)),
                    float(m.group(3)),
                    _unquote(m.group(4).strip()),
                )
            )
            continue
        m = re.match(
            r'^(accelerator|deaccelerator)\s+(".*?"|.+?)\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]', line
        )
        if m:
            data["forces"].append(
                (m.group(1), _unquote(m.group(2)), float(m.group(3)), float(m.group(4)))
            )
            continue
        m = re.match(
            r"^(.+?)\s*(\+'[^']*'>|\+<>|\+<|\+>|-\.->|-->|->)\s*(.+?)(?:\s*;\s*(.+))?$", line
        )
        if m:
            a, op, b, label = m.groups()
            flow = op.startswith("+")
            if op.startswith("+'"):
                label = op[2:-2]
            data["links"].append(
                {
                    "src": name_of(a),
                    "dst": name_of(b),
                    "label": (label or "").strip(),
                    "dashed": op == "-.->",
                    "flow": flow,
                    "fwd": op != "+<",
                    "back": op in ("+<", "+<>"),
                }
            )
    return data


def render_wardley_svg(data: dict, theme: dict[str, str] | None = None) -> str:
    """Value chain against evolution: components, links, movement and annotations."""
    t = _tokens(theme)
    sw, sh = data["size"]
    pw = 660.0
    ph = max(300.0, min(760.0, pw * sh / sw))
    left, top = 40.0, 10.0
    title_parts, title_h = _chart_title(data["title"], t)
    top += title_h
    comps: dict[str, dict] = data["components"]

    def pos(vis: float, evo: float) -> tuple[float, float]:
        return left + evo * pw, top + (1 - vis) * ph

    ink, ink2, grid = t["ink"], t["ink2"], t["grid"]
    red = _CRITICAL
    parts: list[str] = [
        "<defs>"
        f'<marker id="wm-arr" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto" markerUnits="userSpaceOnUse">'
        f'<polygon points="0 0.5, 8 3.5, 0 6.5" fill="{ink2}"/></marker>'
        f'<marker id="wm-arr-s" markerWidth="9" markerHeight="7" refX="1" refY="3.5" orient="auto" markerUnits="userSpaceOnUse">'
        f'<polygon points="9 0.5, 1 3.5, 9 6.5" fill="{ink2}"/></marker>'
        f'<marker id="wm-evo" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto" markerUnits="userSpaceOnUse">'
        f'<polygon points="0 0.5, 8 3.5, 0 6.5" fill="{red}"/></marker>'
        "</defs>"
    ]
    # Frame: stage bands, axes and labels
    prev = 0.0
    for i, (name, edge) in enumerate(data["stages"]):
        x0, x1 = left + prev * pw, left + edge * pw
        if i % 2 == 0:
            parts.append(
                f'<rect x="{x0:.1f}" y="{top:g}" width="{x1 - x0:.1f}" height="{ph:g}" fill="{t["subgraph_fill"]}"/>'
            )
        if i:
            parts.append(
                f'<line x1="{x0:.1f}" y1="{top:g}" x2="{x0:.1f}" y2="{top + ph:g}" stroke="{grid}" stroke-dasharray="4 4"/>'
            )
        for k, piece in enumerate(name.split(" / ")):
            parts.append(
                _svg_text(
                    (x0 + x1) / 2,
                    top + ph + 17 + k * 13,
                    piece,
                    t,
                    _FS_SM if k == 0 else 9.5,
                    ink if k == 0 else ink2,
                    600 if k == 0 else 400,
                    "middle",
                )
            )
        prev = edge
    parts.append(
        f'<path d="M {left:g},{top + ph:g} H {left + pw + 6:g}" stroke="{ink2}" stroke-width="1.2" marker-end="url(#wm-arr)"/>'
    )
    parts.append(
        f'<path d="M {left:g},{top + ph:g} V {top - 6:g}" stroke="{ink2}" stroke-width="1.2" marker-end="url(#wm-arr)"/>'
    )
    stage_rows = max(len(n.split(" / ")) for n, _ in data["stages"])
    parts.append(
        _svg_text(
            left + pw,
            top + ph + 17 + stage_rows * 13 + 4,
            "Evolution →",
            t,
            _FS_SM,
            ink2,
            400,
            "end",
        )
    )
    cy = top + ph / 2
    parts.append(
        _svg_text(
            14,
            cy,
            "Value chain",
            t,
            _FS_SM,
            ink2,
            600,
            "middle",
            f' transform="rotate(-90 14 {cy:g})"',
        )
    )
    parts.append(
        _svg_text(
            left - 6,
            top + 10,
            "Visible",
            t,
            9.5,
            ink2,
            400,
            "end",
            f' transform="rotate(-90 {left - 6:g} {top + 10:g})"',
        )
    )
    parts.append(
        _svg_text(
            left - 6,
            top + ph - 4,
            "Invisible",
            t,
            9.5,
            ink2,
            400,
            "start",
            f' transform="rotate(-90 {left - 6:g} {top + ph - 4:g})"',
        )
    )

    # Pipelines: a frame at the parent's visibility spanning its variants
    for pl in data["pipelines"]:
        parent = comps.get(pl["parent"])
        if not parent or not pl["items"]:
            continue
        evos = [e for _, e in pl["items"]]
        x0, _ = pos(parent["vis"], min(evos))
        x1, y = pos(parent["vis"], max(evos))
        parts.append(
            f'<rect x="{x0 - 14:.1f}" y="{y + 8:.1f}" width="{x1 - x0 + 28:.1f}" height="26" rx="3" '
            f'fill="{t["card"]}" stroke="{ink2}" stroke-width="1"/>'
        )
        for name, evo in pl["items"]:
            px, _ = pos(parent["vis"], evo)
            comps.setdefault(
                name,
                {
                    "kind": "pipeline",
                    "vis": parent["vis"],
                    "evo": evo,
                    "label": None,
                    "decorators": [],
                    "y": y + 21,
                },
            )

    def centre(name: str) -> tuple[float, float] | None:
        c = comps.get(name)
        if not c:
            return None
        x, y = pos(c["vis"], c["evo"])
        return (x, c.get("y", y))

    def trim(
        a: tuple[float, float], b: tuple[float, float], ra: float, rb: float
    ) -> tuple[float, float, float, float]:
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy) or 1.0
        return a[0] + dx / d * ra, a[1] + dy / d * ra, b[0] - dx / d * rb, b[1] - dy / d * rb

    def radius(name: str) -> float:
        c = comps.get(name, {})
        return 12.0 if c.get("kind") == "anchor" else 7.0

    for link in data["links"]:
        a, b = centre(link["src"]), centre(link["dst"])
        if not a or not b:
            continue
        x0, y0, x1, y1 = trim(
            a, b, radius(link["src"]), radius(link["dst"]) + (2 if link["flow"] else 0)
        )
        attrs = f'stroke="{ink2 if link["flow"] else _mix(ink2, t["surface"], 0.25)}" stroke-width="{1.6 if link["flow"] else 1}"'
        if link["dashed"]:
            attrs += ' stroke-dasharray="5 4"'
        if link["flow"] and link["fwd"]:
            attrs += ' marker-end="url(#wm-arr)"'
        if link["back"]:
            attrs += ' marker-start="url(#wm-arr-s)"'
        parts.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" {attrs}/>')
        if link["label"]:
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            lw = _text_w(link["label"], 9.5) + 8
            parts.append(
                f'<rect x="{mx - lw / 2:.1f}" y="{my - 8:.1f}" width="{lw:.1f}" height="14" rx="3" fill="{t["surface"]}" fill-opacity="0.9"/>'
            )
            parts.append(_svg_text(mx, my + 3, link["label"], t, 9.5, ink2, 400, "middle"))

    for name, target in data["evolve"]:
        c = comps.get(name)
        if not c:
            continue
        a = centre(name)
        assert a is not None
        b = pos(c["vis"], target)
        x0, y0, x1, y1 = trim(a, (b[0], a[1]), 8, 9)
        parts.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{red}" stroke-width="1.4" '
            f'stroke-dasharray="5 4" marker-end="url(#wm-evo)"/>'
        )
        parts.append(
            f'<circle cx="{b[0]:.1f}" cy="{a[1]:.1f}" r="6" fill="{t["surface"]}" stroke="{red}" stroke-width="1.5"/>'
        )
        parts.append(_svg_text(b[0] + 10, a[1] - 8, name, t, _FS_SM, red, 500))

    for name, c in comps.items():
        x, y = centre(name) or (0.0, 0.0)
        decs = c["decorators"]
        shade = _tint(ink2, 0.75, t)
        for d in decs:
            if d == "build":
                parts.append(
                    f'<polygon points="{x:.1f},{y - 15:.1f} {x + 14:.1f},{y + 10:.1f} {x - 14:.1f},{y + 10:.1f}" fill="{shade}"/>'
                )
            elif d == "buy":
                parts.append(
                    f'<polygon points="{x:.1f},{y - 15:.1f} {x + 15:.1f},{y:.1f} {x:.1f},{y + 15:.1f} {x - 15:.1f},{y:.1f}" fill="{shade}"/>'
                )
            elif d == "outsource":
                parts.append(
                    f'<rect x="{x - 12:.1f}" y="{y - 12:.1f}" width="24" height="24" fill="{shade}"/>'
                )
            elif d == "market":
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="{shade}"/>')
            elif d == "inertia":
                parts.append(
                    f'<rect x="{x + 16:.1f}" y="{y - 12:.1f}" width="5" height="24" fill="{ink}"/>'
                )
        if c["kind"] == "anchor":
            lw = _text_w(name, _FS, 700)
            parts.append(_svg_text(x, y + 4, name, t, _FS, ink, 700, "middle"))
            continue
        dot = 4.5 if c["kind"] == "pipeline" else 6.0
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{dot:g}" fill="{t["surface"]}" stroke="{ink}" stroke-width="1.5"/>'
        )
        if c["kind"] == "pipeline":
            parts.append(_svg_text(x, y + 22, name, t, 9.5, ink2, 400, "middle"))
            continue
        dx, dy = c["label"] if c["label"] else (10.0, -9.0)
        parts.append(
            _svg_text(x + dx, y + dy + 4 if c["label"] else y + dy, name, t, _FS_SM, ink, 500)
        )

    for text, vis, evo in data["notes"]:
        x, y = pos(vis, evo)
        parts.append(_svg_text(x, y, text, t, _FS_SM, ink, 600))

    for num, vis, evo, _text in data["annotations"]:
        x, y = pos(vis, evo)
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{t["surface"]}" stroke="{ink2}" stroke-width="1"/>'
        )
        parts.append(_svg_text(x, y + 3.5, str(num), t, 9.5, ink, 600, "middle"))
    if data["annotations"]:
        bvis, bevo = data["annotation_box"] or (0.95, 0.02)
        bx, by = pos(bvis, bevo)
        rows = [f"{n}. {txt}" for n, _, _, txt in sorted(data["annotations"])]
        bw = max(_text_w(r, _FS_SM) for r in rows + ["Annotations"]) + 20
        bh = 26 + 15 * len(rows)
        bx = min(bx, left + pw - bw)
        by = min(by, top + ph - bh)
        parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:g}" rx="4" fill="{t["card"]}" stroke="{grid}"/>'
        )
        parts.append(_svg_text(bx + 10, by + 16, "Annotations", t, _FS_SM, ink, 600))
        for i, row in enumerate(rows):
            parts.append(_svg_text(bx + 10, by + 32 + i * 15, row, t, _FS_SM, ink2))

    for kind, text, vis, evo in data["forces"]:
        x, y = pos(vis, evo)
        s = 1 if kind == "accelerator" else -1
        fill = _tint(t["accent"], 0.55, t) if s > 0 else _tint(red, 0.6, t)
        x0, x1 = x - 26 * s, x + 26 * s
        parts.append(
            f'<polygon points="{x0:.1f},{y - 7:.1f} {x + 8 * s:.1f},{y - 7:.1f} {x + 8 * s:.1f},{y - 14:.1f} '
            f'{x1:.1f},{y:.1f} {x + 8 * s:.1f},{y + 14:.1f} {x + 8 * s:.1f},{y + 7:.1f} {x0:.1f},{y + 7:.1f}" fill="{fill}"/>'
        )
        parts.append(_svg_text(x, y + 28, text, t, _FS_SM, ink, 600, "middle"))

    height = top + ph + 17 + stage_rows * 13 + 12
    # Labels to the right of points near commodity can run past the plot
    right = left + pw + 20
    for name, c in comps.items():
        if c["kind"] in ("component", "anchor"):
            x = (centre(name) or (0.0, 0.0))[0]
            dx = c["label"][0] if c["label"] else 10.0
            right = max(
                right, x + (dx if c["kind"] == "component" else 0) + _text_w(name, _FS_SM, 500) + 6
            )
    for name, target in data["evolve"]:
        if name in comps:
            right = max(right, pos(0, target)[0] + 16 + _text_w(name, _FS_SM, 500))
    for text, vis, evo in data["notes"]:
        right = max(right, pos(vis, evo)[0] + _text_w(text, _FS_SM, 600) + 6)
    return _svg_root(right, height, title_parts + parts, t["font"])


def _rr_tokens(text: str, notation: str) -> list[str]:
    """Split a grammar definition into tokens for the railroad parser."""
    tokens: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "\"'":
            j = text.find(ch, i + 1)
            j = len(text) - 1 if j < 0 else j
            tokens.append(text[i : j + 1])
            i = j + 1
            continue
        m = re.match(r"%[xdb][0-9A-Fa-f]+(?:[-.][0-9A-Fa-f]+)*", text[i:])
        if m:
            tokens.append(m.group(0))
            i += m.end()
            continue
        if notation == "abnf":
            m = re.match(r"\d*\*\d*|\d+(?=[\"'(\[%A-Za-z])", text[i:])
            if m:
                tokens.append("#rep:" + m.group(0))
                i += m.end()
                continue
        m = re.match(r"[A-Za-z_][\w]*(?:-[A-Za-z_]\w*)*", text[i:])
        if m:
            tokens.append(m.group(0))
            i += m.end()
            continue
        if notation == "ebnf" and ch == "?":
            # ISO special sequence `? text ?` where an operand is expected
            prev = tokens[-1] if tokens else "("
            j = text.find("?", i + 1)
            if prev in ("(", "[", "{", "|", ",", "=") and j > 0:
                tokens.append("#special:" + text[i + 1 : j].strip())
                i = j + 1
                continue
        tokens.append(ch)
        i += 1
    return tokens


def _rr_parse_expr(tokens: list[str], notation: str) -> tuple:
    """Recursive descent over the token list; returns a railroad AST tuple."""
    pos = 0
    alt_ops = ("|", "/") if notation != "ebnf" else ("|",)

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def expr() -> tuple:
        options = [seq()]
        while peek() in alt_ops:
            take()
            options.append(seq())
        return options[0] if len(options) == 1 else ("choice", options)

    def seq() -> tuple:
        items: list[tuple] = []
        while peek() is not None and peek() not in (")", "]", "}", *alt_ops):
            if peek() == ",":
                take()
                continue
            item = term()
            if peek() == "-" and notation == "ebnf":
                take()
                excluded = term()
                item = ("group", f"except {_rr_label(excluded)}", item)
            items.append(item)
        if not items:
            return ("skip",)
        return items[0] if len(items) == 1 else ("seq", items)

    def term() -> tuple:
        tok = peek()
        if tok in ("&", "!") and notation == "peg":
            take()
            return ("group", "followed by" if tok == "&" else "not followed by", term())
        if tok and tok.startswith("#rep:"):
            spec = take()[5:]
            node = primary()
            if "*" in spec:
                lo, _, hi = spec.partition("*")
                lo_n = int(lo) if lo else 0
                label = f"{lo or 0}–{hi}" if hi else (f"≥{lo_n}" if lo_n > 1 else "")
                return ("more", node, label) if lo_n >= 1 else ("opt", ("more", node, label))
            return ("more", node, f"×{spec}")
        node = primary()
        while peek() in ("?", "*", "+"):
            op = take()
            node = (
                ("opt", node)
                if op == "?"
                else ("more", node, "") if op == "+" else ("opt", ("more", node, ""))
            )
        return node

    def primary() -> tuple:
        tok = take() if peek() is not None else ""
        if tok in ("(", "[", "{"):
            inner = expr()
            if peek() in (")", "]", "}"):
                take()
            if tok == "[":
                return ("opt", inner)
            if tok == "{":
                return ("opt", ("more", inner, ""))
            return inner
        if tok.startswith("#special:"):
            return ("special", tok[9:])
        if tok[:1] in ("'", '"'):
            return ("term", tok[1:-1] if len(tok) > 1 else tok)
        if tok.startswith("%"):
            return ("term", tok)
        if tok == ".":
            return ("special", "any character")
        if tok:
            return ("nonterm", tok)
        return ("skip",)

    return expr()


def _rr_label(node: tuple) -> str:
    if node[0] in ("term", "nonterm", "special"):
        return node[1]
    return "…"


def _rr_parse_ir(text: str) -> tuple:
    """Parse ``sequence(terminal("a"), …)`` constructor syntax."""
    pos = 0

    def ws() -> None:
        nonlocal pos
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1

    def node() -> tuple:
        nonlocal pos
        ws()
        m = re.match(r"(\w+)\s*\(", text[pos:])
        if not m:
            m2 = re.match(r"\"([^\"]*)\"|'([^']*)'|(\w+)", text[pos:])
            pos += m2.end() if m2 else 1
            return (
                ("term", (m2.group(1) or m2.group(2) or ""))
                if m2 and m2.group(3) is None
                else ("nonterm", m2.group(3) if m2 else "?")
            )
        name = m.group(1)
        pos += m.end()
        args: list[tuple] = []
        strings: list[str] = []
        while True:
            ws()
            if pos >= len(text) or text[pos] == ")":
                pos += 1
                break
            sm = re.match(r"\"([^\"]*)\"|'([^']*)'", text[pos:])
            if sm:
                strings.append(sm.group(1) if sm.group(1) is not None else sm.group(2))
                pos += sm.end()
            else:
                args.append(node())
        label = strings[0] if strings else ""
        lname = name.lower()
        if lname == "terminal":
            return ("term", label)
        if lname == "nonterminal":
            return ("nonterm", label)
        if lname in ("special", "comment"):
            return ("special", label)
        if lname == "sequence":
            return ("seq", args) if len(args) != 1 else args[0]
        if lname == "choice":
            return ("choice", args)
        if lname == "optional":
            return ("opt", args[0] if args else ("skip",))
        if lname == "oneormore":
            return ("more", args[0] if args else ("skip",), "")
        if lname == "zeroormore":
            return ("opt", ("more", args[0] if args else ("skip",), ""))
        return ("seq", args)

    return node()


def parse_railroad(source: str) -> dict:
    """Rules from any of Mermaid's railroad notations, as one AST."""
    lines = source.strip().splitlines()
    head = lines[0].strip().lower() if lines else ""
    notation = "ebnf"
    for key in ("abnf", "peg", "ebnf"):
        if f"-{key}" in head:
            notation = key
            break
    else:
        if head.startswith("railroad"):
            notation = "ir"
    title = ""
    body_lines = []
    for line in lines[1:]:
        s = line.strip()
        m = re.match(r"^title\s+(.+)$", s)
        if m:
            title = _unquote(m.group(1).strip())
            continue
        if s.startswith(("accTitle", "accDescr", "%%")):
            continue
        body_lines.append(line)
    body = "\n".join(body_lines)
    body = re.sub(r"/\*.*?\*/|\(\*.*?\*\)", " ", body, flags=re.S)
    if notation == "peg":
        body = re.sub(r"#[^\n]*", " ", body)
    if notation == "abnf":
        # `;` ends a rule at the end of a line; anything after it is a comment
        body = re.sub(r";[^\n]*", ";", body)
    assign = {"ebnf": r"::=|=", "abnf": r"=/|=", "peg": r"<-|←|=", "ir": r"="}[notation]
    rules: list[tuple[str, tuple]] = []
    for stmt in _split_rules(body):
        m = re.match(rf"^\s*<?([A-Za-z_][\w-]*)>?\s*(?:{assign})\s*(.*)$", stmt, re.S)
        if not m:
            continue
        name, definition = m.group(1), m.group(2).strip()
        if notation == "ir":
            ast = _rr_parse_ir(definition)
        else:
            ast = _rr_parse_expr(_rr_tokens(definition, notation), notation)
        rules.append((name, ast))
    return {"title": title, "rules": rules}


def _split_rules(body: str) -> list[str]:
    """Split on `;` outside quotes."""
    out, buf, quote = [], [], ""
    for ch in body:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        if ch == ";":
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf))
    return [s for s in out if s.strip()]


_RR_ARC = 10.0
_RR_H = 24.0  # box height


_RR_ARC = 10.0
_RR_H = 24.0  # box height


def _rr_measure(node: tuple) -> tuple[float, float, float]:
    """(width, extent above the track, extent below)."""
    kind = node[0]
    half = _RR_H / 2
    if kind == "skip":
        return 0.0, 0.0, 0.0
    if kind in ("term", "nonterm", "special"):
        size = _FS_SM if kind == "special" else _FS
        return _text_w(node[1], size, 500) + 22, half, half
    if kind == "seq":
        ms = [_rr_measure(c) for c in node[1]]
        return (
            sum(m[0] for m in ms) + 12 * (len(ms) - 1),
            max(m[1] for m in ms),
            max(m[2] for m in ms),
        )
    if kind == "choice":
        ms = [_rr_measure(c) for c in node[1]]
        w = max(m[0] for m in ms) + 4 * _RR_ARC
        down = 0.0
        prev_down = ms[0][2]
        for m in ms[1:]:
            down += max(prev_down + 10 + m[1], 2 * _RR_ARC)
            prev_down = m[2]
        return w, max(ms[0][1], half), down + prev_down
    if kind == "opt":
        w, up, down = _rr_measure(node[1])
        return w + 4 * _RR_ARC, max(up + 10, 2 * _RR_ARC), down
    if kind == "more":
        w, up, down = _rr_measure(node[1])
        extra = 10.0 if node[2] else 0.0
        return w + 4 * _RR_ARC, up, max(down + 10, 2 * _RR_ARC) + extra
    if kind == "group":
        w, up, down = _rr_measure(node[2])
        return w + 16, up + 22, down + 8
    return 0.0, 0.0, 0.0


def _rr_draw(
    node: tuple, x: float, y: float, t: dict[str, str], out: list[str], width: float | None = None
) -> None:
    """Draw *node* entering at (x, y); pads the track to *width* if given."""
    kind = node[0]
    w, up, down = _rr_measure(node)
    line = t["ink2"]
    track = f'fill="none" stroke="{line}" stroke-width="1.5"'
    if width is not None and width > w:
        pad = (width - w) / 2
        out.append(
            f'<path d="M {x:.1f},{y:.1f} h {pad:.1f} M {x + pad + w:.1f},{y:.1f} h {pad:.1f}" {track}/>'
        )
        x += pad
    a = _RR_ARC
    if kind == "skip":
        return
    if kind in ("term", "nonterm", "special"):
        h = _RR_H
        if kind == "term":
            out.append(
                f'<rect x="{x:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:g}" rx="{h / 2:g}" '
                f'fill="{_tint(t["primary"], 0.88, t)}" stroke="{_tint(t["primary"], 0.3, t)}" stroke-width="1.2"/>'
            )
            out.append(_svg_text(x + w / 2, y + 4.2, node[1], t, _FS, t["ink"], 500, "middle"))
        elif kind == "nonterm":
            out.append(
                f'<rect x="{x:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:g}" rx="3" '
                f'fill="{t["card"]}" stroke="{t["node_stroke"]}" stroke-width="1.2"/>'
            )
            out.append(_svg_text(x + w / 2, y + 4.2, node[1], t, _FS, t["ink"], 500, "middle"))
        else:
            inset = 8
            out.append(
                f'<polygon points="{x:.1f},{y:.1f} {x + inset:.1f},{y - h / 2:.1f} {x + w - inset:.1f},{y - h / 2:.1f} '
                f'{x + w:.1f},{y:.1f} {x + w - inset:.1f},{y + h / 2:.1f} {x + inset:.1f},{y + h / 2:.1f}" '
                f'fill="{t["subgraph_fill"]}" stroke="{t["chrome"]}" stroke-width="1.2"/>'
            )
            out.append(
                _svg_text(
                    x + w / 2,
                    y + 3.8,
                    node[1],
                    t,
                    _FS_SM,
                    t["ink2"],
                    400,
                    "middle",
                    ' font-style="italic"',
                )
            )
        return
    if kind == "seq":
        cx = x
        for i, child in enumerate(node[1]):
            if i:
                out.append(f'<path d="M {cx:.1f},{y:.1f} h 12" {track}/>')
                cx += 12
            _rr_draw(child, cx, y, t, out)
            cx += _rr_measure(child)[0]
        return
    if kind == "choice":
        inner = w - 4 * a
        ms = [_rr_measure(c) for c in node[1]]
        out.append(f'<path d="M {x:.1f},{y:.1f} h {2 * a:g}" {track}/>')
        out.append(f'<path d="M {x + w - 2 * a:.1f},{y:.1f} h {2 * a:g}" {track}/>')
        _rr_draw(node[1][0], x + 2 * a, y, t, out, inner)
        cy = y
        prev_down = ms[0][2]
        for child, m in zip(node[1][1:], ms[1:]):
            cy += max(prev_down + 10 + m[1], 2 * a)
            prev_down = m[2]
            dy = cy - y
            out.append(
                f'<path d="M {x:.1f},{y:.1f} a {a:g} {a:g} 0 0 1 {a:g} {a:g} v {dy - 2 * a:.1f} '
                f'a {a:g} {a:g} 0 0 0 {a:g} {a:g}" {track}/>'
            )
            out.append(
                f'<path d="M {x + w - 2 * a:.1f},{cy:.1f} a {a:g} {a:g} 0 0 0 {a:g} {-a:g} v {-(dy - 2 * a):.1f} '
                f'a {a:g} {a:g} 0 0 1 {a:g} {-a:g}" {track}/>'
            )
            _rr_draw(child, x + 2 * a, cy, t, out, inner)
        return
    if kind == "opt":
        child = node[1]
        cw, cup, _ = _rr_measure(child)
        sy = y - up
        out.append(f'<path d="M {x:.1f},{y:.1f} h {2 * a:g}" {track}/>')
        out.append(f'<path d="M {x + w - 2 * a:.1f},{y:.1f} h {2 * a:g}" {track}/>')
        out.append(
            f'<path d="M {x:.1f},{y:.1f} a {a:g} {a:g} 0 0 0 {a:g} {-a:g} v {-(y - sy - 2 * a):.1f} '
            f"a {a:g} {a:g} 0 0 1 {a:g} {-a:g} H {x + w - 2 * a:.1f} a {a:g} {a:g} 0 0 1 {a:g} {a:g} "
            f'v {y - sy - 2 * a:.1f} a {a:g} {a:g} 0 0 0 {a:g} {a:g}" {track}/>'
        )
        _rr_draw(child, x + 2 * a, y, t, out, w - 4 * a)
        return
    if kind == "more":
        child = node[1]
        _, _, cdown = _rr_measure(child)
        ly = y + max(cdown + 10, 2 * a)
        out.append(f'<path d="M {x:.1f},{y:.1f} h {2 * a:g}" {track}/>')
        out.append(f'<path d="M {x + w - 2 * a:.1f},{y:.1f} h {2 * a:g}" {track}/>')
        mid = x + w / 2
        out.append(
            f'<path d="M {x + w - 2 * a:.1f},{y:.1f} a {a:g} {a:g} 0 0 1 {a:g} {a:g} v {ly - y - 2 * a:.1f} '
            f"a {a:g} {a:g} 0 0 1 {-a:g} {a:g} H {x + 2 * a:.1f} a {a:g} {a:g} 0 0 1 {-a:g} {-a:g} "
            f'v {-(ly - y - 2 * a):.1f} a {a:g} {a:g} 0 0 1 {a:g} {-a:g}" {track}/>'
        )
        # direction cue on the return loop
        out.append(
            f'<path d="M {mid + 3:.1f},{ly - 4:.1f} L {mid - 3:.1f},{ly:.1f} L {mid + 3:.1f},{ly + 4:.1f}" {track}/>'
        )
        if node[2]:
            out.append(_svg_text(mid, ly + 13, node[2], t, 9.5, t["ink2"], 400, "middle"))
        _rr_draw(child, x + 2 * a, y, t, out, w - 4 * a)
        return
    if kind == "group":
        child = node[2]
        cw, cup, cdown = _rr_measure(child)
        out.append(
            f'<rect x="{x + 2:.1f}" y="{y - cup - 8:.1f}" width="{w - 4:.1f}" height="{cup + cdown + 16:.1f}" rx="6" '
            f'fill="none" stroke="{t["chrome"]}" stroke-dasharray="4 3"/>'
        )
        out.append(
            _svg_text(
                x + 6,
                y - cup - 12,
                node[1],
                t,
                9.5,
                t["ink2"],
                400,
                "start",
                ' font-style="italic"',
            )
        )
        out.append(f'<path d="M {x:.1f},{y:.1f} h 8 M {x + w - 8:.1f},{y:.1f} h 8" {track}/>')
        _rr_draw(child, x + 8, y, t, out)
        return


def _rr_rows(node: tuple, limit: float) -> list[tuple]:
    """Break a long top-level sequence into rows that fit *limit*."""
    if node[0] != "seq" or _rr_measure(node)[0] <= limit:
        return [node]
    rows: list[list[tuple]] = [[]]
    width = 0.0
    for child in node[1]:
        cw = _rr_measure(child)[0] + 12
        if rows[-1] and width + cw > limit:
            rows.append([])
            width = 0.0
        rows[-1].append(child)
        width += cw
    return [r[0] if len(r) == 1 else ("seq", r) for r in rows]


def render_railroad_svg(data: dict, theme: dict[str, str] | None = None) -> str:
    """One track per rule: terminals are pills, rule references are boxes."""
    t = _tokens(theme)
    if not data["rules"]:
        return _svg_root(120, 40, _svg_text(0, 20, "No rules", t, color=t["ink2"]), t["font"])
    limit = float(t.get("column_px") or 680) - 60
    parts: list[str] = []
    title_parts, title_h = _chart_title(data["title"], t)
    parts += title_parts
    y = title_h + 4
    width = 0.0
    line = t["ink2"]
    track = f'fill="none" stroke="{line}" stroke-width="1.5"'
    for name, ast in data["rules"]:
        parts.append(_svg_text(0, y + 13, name, t, _FS, t["ink"], 600))
        y += 22
        rows = _rr_rows(ast, limit)
        x0 = 14.0
        for i, row in enumerate(rows):
            w, up, down = _rr_measure(row)
            ty = y + up + 4
            if i == 0:
                parts.append(f'<path d="M 2,{ty - 7:.1f} v 14 M 6,{ty - 7:.1f} v 14" {track}/>')
                parts.append(f'<path d="M 6,{ty:.1f} H {x0:.1f}" {track}/>')
            _rr_draw(row, x0, ty, t, parts)
            end = x0 + w
            if i == len(rows) - 1:
                parts.append(
                    f'<path d="M {end:.1f},{ty:.1f} h 8 M {end + 8:.1f},{ty - 7:.1f} v 14 M {end + 12:.1f},{ty - 7:.1f} v 14" {track}/>'
                )
                width = max(width, end + 14)
                y = ty + down + 18
            else:
                # carry the track back to the left edge for the next row
                nxt_up = _rr_measure(rows[i + 1])[1]
                ny = ty + down + 14 + nxt_up + 4
                mid = ty + down + 7
                a = _RR_ARC
                parts.append(
                    f'<path d="M {end:.1f},{ty:.1f} h 4 a {a:g} {a:g} 0 0 1 {a:g} {a:g} V {mid - a:.1f} '
                    f"a {a:g} {a:g} 0 0 1 {-a:g} {a:g} H {a:.1f} a {a:g} {a:g} 0 0 0 {-a + 2:g} {a:g} "
                    f'V {ny - a:.1f} a {a:g} {a:g} 0 0 0 {a:g} {a:g} H {x0:.1f}" {track}/>'
                )
                width = max(width, end + 4 + a)
                y = ny - nxt_up - 4
        y += 6
    return _svg_root(width + 4, y - 14, parts, t["font"])


_EM_KINDS = {
    "ui": "ui",
    "pcr": "pcr",
    "processor": "pcr",
    "cmd": "cmd",
    "command": "cmd",
    "rmo": "rmo",
    "readmodel": "rmo",
    "evt": "evt",
    "event": "evt",
}
_EM_GROUP = {"ui": 0, "pcr": 0, "cmd": 1, "rmo": 1, "evt": 2}
_EM_GROUP_NAMES = ("UI / Automation", "Command / Read model", "Events")
_EM_CAPTION = {
    "ui": "UI",
    "pcr": "Processor",
    "cmd": "Command",
    "rmo": "Read model",
    "evt": "Event",
}
_EM_COLORS = {
    "cmd": "#3b6fd4",
    "evt": "#e08a2c",
    "rmo": "#3f9a52",
    "pcr": "#6b7280",
    "ui": "#8a94a6",
}


def _fit_label(text: str, max_w: float, size: float) -> str:
    """Shorten *text* with an ellipsis so it fits *max_w*."""
    if _text_w(text, size) <= max_w:
        return text
    while text and _text_w(text + "…", size) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _em_data_lines(text: str) -> list[str]:
    body = text.strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    parts = re.split(r"\n|,(?![^{\[]*[}\]])", body)
    return [p.strip().rstrip(",") for p in parts if p.strip()]


def parse_eventmodeling(source: str) -> dict:
    """Time frames (with inline or referenced data), reset frames and explicit ``->>`` links."""
    frames: list[dict] = []
    data_blocks: dict[str, list[str]] = {}
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("%%") or line.lower() == "eventmodeling":
            continue
        m = re.match(r"^data\s+([\w.]+)\s*(?:`\w+`)?\s*(\{.*)$", line)
        if m:
            buf = m.group(2)
            depth = buf.count("{") - buf.count("}")
            while depth > 0 and i < len(lines):
                buf += "\n" + lines[i]
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            data_blocks[m.group(1)] = _em_data_lines(buf)
            continue
        m = re.match(r"^(tf|timeframe|rf|resetframe)\s+(\d+)\s+(\w+)\s+([\w.-]+)\s*(.*)$", line)
        if not m:
            continue
        kw, num, kind, ident, rest = m.groups()
        refs = re.findall(r"->>\s*(\d+)", rest)
        rest = re.sub(r"->>\s*\d+", "", rest)
        ref = re.search(r"\[\[([\w.]+)\]\]", rest)
        inline = re.search(r"\{.*\}", rest)
        ns, _, name = ident.rpartition(".")
        frames.append(
            {
                "num": num,
                "kind": _EM_KINDS.get(kind.lower(), "ui"),
                "name": name,
                "ns": ns,
                "reset": kw in ("rf", "resetframe"),
                "refs": refs,
                "data_ref": ref.group(1) if ref else None,
                "data": _em_data_lines(inline.group(0)) if inline else [],
            }
        )
    for f in frames:
        if f["data_ref"] and not f["data"]:
            f["data"] = data_blocks.get(f["data_ref"], [])
    return {"frames": frames}


def render_eventmodeling_svg(data: dict, theme: dict[str, str] | None = None) -> str:
    """Swimlanes of UI, commands/read models and events along a timeline of frames."""
    t = _tokens(theme)
    frames = data["frames"]
    if not frames:
        return _svg_root(120, 40, _svg_text(0, 20, "No frames", t, color=t["ink2"]), t["font"])
    # Lanes: one per (group, namespace), groups in canonical order
    lane_keys: list[tuple[int, str]] = []
    for f in frames:
        key = (_EM_GROUP[f["kind"]], f["ns"])
        if key not in lane_keys:
            lane_keys.append(key)
    lane_keys.sort(key=lambda k: k[0])  # stable: namespaces keep their order
    lane_of = {i: lane_keys.index((_EM_GROUP[f["kind"]], f["ns"])) for i, f in enumerate(frames)}

    # Box sizes
    shown_data = [f["data"][:5] for f in frames]
    boxes = []
    for f, rows in zip(frames, shown_data):
        title_lines = _wrap_lines(f["name"], 150, _FS)
        w = max(
            [118.0]
            + [_text_w(x, _FS, 600) + 20 for x in title_lines]
            + [_text_w(r, 9.5) + 20 for r in rows]
        )
        w = min(w, 210.0)
        h = (
            24
            + 15 * len(title_lines)
            + (8 + 12.5 * len(rows) if rows else 4)
            + (12.5 if len(f["data"]) > 5 else 0)
        )
        boxes.append((w, max(h, 54.0), title_lines))

    header = 116.0
    gap = 26.0
    # Frames advance along the timeline; a lane only needs room for its own
    # boxes, so frames in different lanes overlap in time instead of queueing.
    xs: list[float] = []
    lane_right: dict[int, float] = {}
    for i, (w, _, _) in enumerate(boxes):
        x = header + 16
        if xs:
            x = max(x, xs[-1] + max(56.0, boxes[i - 1][0] * 0.55))
        x = max(x, lane_right.get(lane_of[i], 0.0) + gap)
        xs.append(x)
        lane_right[lane_of[i]] = x + w
    width = max(xs[i] + boxes[i][0] for i in range(len(boxes))) + 16
    lane_h = [0.0] * len(lane_keys)
    for i, (_, h, _) in enumerate(boxes):
        lane_h[lane_of[i]] = max(lane_h[lane_of[i]], h + 24)
    lane_h = [max(h, 64.0) for h in lane_h]
    lane_y = []
    acc = 0.0
    for h in lane_h:
        lane_y.append(acc)
        acc += h
    height = acc

    parts: list[str] = [_make_arrow_defs(t)]
    for k, (group, ns) in enumerate(lane_keys):
        y = lane_y[k]
        fill = t["subgraph_fill"] if k % 2 == 0 else t["surface"]
        parts.append(
            f'<rect x="0" y="{y:g}" width="{width:g}" height="{lane_h[k]:g}" fill="{fill}"/>'
        )
        parts.append(
            f'<rect x="0" y="{y:g}" width="{header:g}" height="{lane_h[k]:g}" fill="{_tint(t["primary"], 0.9, t)}"/>'
        )
        label_lines = ([ns] if ns else []) + _wrap_lines(
            _EM_GROUP_NAMES[group], header - 20, _FS_SM
        )
        ly = y + lane_h[k] / 2 - (len(label_lines) - 1) * 7 + 4
        for j, text in enumerate(label_lines):
            bold = j == 0 and bool(ns)
            parts.append(
                _svg_text(
                    10,
                    ly + j * 14,
                    text,
                    t,
                    _FS if bold else _FS_SM,
                    t["ink"],
                    600 if bold or not ns else 400,
                )
            )
        if k:
            parts.append(
                f'<line x1="0" y1="{y:g}" x2="{width:g}" y2="{y:g}" stroke="{t["subgraph_stroke"]}"/>'
            )

    def rect(i: int) -> tuple[float, float, float, float]:
        w, h, _ = boxes[i]
        k = lane_of[i]
        return xs[i], lane_y[k] + (lane_h[k] - h) / 2, w, h

    index = {f["num"]: i for i, f in enumerate(frames)}
    links: list[tuple[int, int]] = []
    for i, f in enumerate(frames):
        if i and not f["reset"]:
            links.append((i - 1, i))
        for r in f["refs"]:
            if r in index and index[r] != i:
                links.append((index[r], i))
    unique = list(dict.fromkeys(links))
    # Several arrows into one box arrive side by side, ordered by where they come from
    arrival: dict[tuple[int, int], float] = {}
    for b in {b for _, b in unique}:
        srcs = sorted(
            (a for a, bb in unique if bb == b and lane_of[a] != lane_of[b]), key=lambda a: xs[a]
        )
        for k, a in enumerate(srcs):
            arrival[(a, b)] = 0.5 if len(srcs) == 1 else 0.2 + 0.6 * k / (len(srcs) - 1)
    for a, b in unique:
        ax, ay, aw, ah = rect(a)
        bx, by, bw, bh = rect(b)
        if lane_of[a] == lane_of[b]:
            x0, y0 = (ax + aw, ay + ah / 2) if ax < bx else (ax, ay + ah / 2)
            x1, y1 = (bx, by + bh / 2) if ax < bx else (bx + bw, by + bh / 2)
            d = f"M {x0:.1f},{y0:.1f} L {x1:.1f},{y1:.1f}"
        else:
            down = lane_of[b] > lane_of[a]
            x0 = ax + aw * (0.62 if ax < bx else 0.38)
            y0 = ay + ah if down else ay
            x1 = bx + bw * arrival.get((a, b), 0.38 if ax < bx else 0.62)
            y1 = by if down else by + bh
            mid = (y0 + y1) / 2
            d = f"M {x0:.1f},{y0:.1f} C {x0:.1f},{mid:.1f} {x1:.1f},{mid:.1f} {x1:.1f},{y1:.1f}"
        parts.append(
            f'<path d="{d}" fill="none" stroke="{t["edge"]}" stroke-width="1.3" marker-end="url(#arr)"/>'
        )

    for i, f in enumerate(frames):
        x, y, w, h = rect(i)
        _, _, title_lines = boxes[i]
        base = _EM_COLORS[f["kind"]]
        fill = t["card"] if f["kind"] == "ui" else _tint(base, 0.84, t)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{8 if f["kind"] == "ui" else 3}" '
            f'fill="{fill}" stroke="{_tint(base, 0.15, t)}" stroke-width="1.2"/>'
        )
        parts.append(
            _svg_text(
                x + 10,
                y + 15,
                _EM_CAPTION[f["kind"]].upper(),
                t,
                8.5,
                _mix(base, t["ink"], 0.35),
                600,
                extra=' letter-spacing="0.6"',
            )
        )
        parts.append(_svg_text(x + w - 8, y + 15, f["num"], t, 8.5, t["ink2"], 400, "end"))
        cy = y + 31
        for text in title_lines:
            parts.append(_svg_text(x + 10, cy, text, t, _FS, t["ink"], 600))
            cy += 15
        rows = shown_data[i]
        if rows:
            parts.append(
                f'<line x1="{x + 8:.1f}" y1="{cy - 6:.1f}" x2="{x + w - 8:.1f}" y2="{cy - 6:.1f}" stroke="{_tint(base, 0.5, t)}"/>'
            )
            cy += 6
            for r in rows:
                parts.append(_svg_text(x + 10, cy, _fit_label(r, w - 18, 9.5), t, 9.5, t["ink2"]))
                cy += 12.5
            if len(f["data"]) > 5:
                parts.append(
                    _svg_text(
                        x + 10,
                        cy,
                        f"+{len(f['data']) - 5} more",
                        t,
                        9.5,
                        t["ink2"],
                        extra=' font-style="italic"',
                    )
                )
    return _svg_root(width, height, parts, t["font"])


def _detect_diagram_type(source: str) -> str:
    """Detect the diagram type from Mermaid source."""
    source = _strip_preamble(source)
    for line in source.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^(?:flowchart|graph)\s", line, re.IGNORECASE):
            return "flowchart"
        if line.lower() == "sequencediagram" or line.lower().startswith("sequencediagram"):
            return "sequence"
        if re.match(r"^pie\b", line, re.IGNORECASE):
            return "pie"
        if re.match(r"^donut\b", line, re.IGNORECASE):
            return "donut"
        if re.match(r"^(?:bar|xychart-beta)\b", line, re.IGNORECASE):
            return "bar"
        if re.match(r"^gauge\b", line, re.IGNORECASE):
            return "gauge"
        if re.match(r"^timeline\b", line, re.IGNORECASE):
            return "timeline"
        if re.match(r"^mindmap\b", line, re.IGNORECASE):
            return "mindmap"
        if re.match(r"^classDiagram(?:-v2)?\b", line, re.IGNORECASE):
            return "class"
        if re.match(r"^journey\b", line, re.IGNORECASE):
            return "journey"
        if re.match(r"^gitGraph\b", line, re.IGNORECASE):
            return "git"
        if re.match(r"^quadrantChart\b", line, re.IGNORECASE):
            return "quadrant"
        if re.match(r"^sankey(-beta)?\b", line, re.IGNORECASE):
            return "sankey"
        if re.match(r"^radar(-beta)?\b", line, re.IGNORECASE):
            return "radar"
        if re.match(r"^treemap(-beta)?\b", line, re.IGNORECASE):
            return "treemap"
        if re.match(r"^packet(-beta)?\b", line, re.IGNORECASE):
            return "packet"
        if re.match(r"^block(-beta)?\b", line, re.IGNORECASE):
            return "block"
        if re.match(r"^kanban\b", line, re.IGNORECASE):
            return "kanban"
        if re.match(r"^architecture(-beta)?\b", line, re.IGNORECASE):
            return "architecture"
        if re.match(r"^C4(Context|Container|Component|Dynamic|Deployment)\b", line):
            return "c4"
        if re.match(r"^requirementDiagram\b", line, re.IGNORECASE):
            return "requirement"
        if re.match(r"^zenuml\b", line, re.IGNORECASE):
            return "zenuml"
        if re.match(r"^usecase(-beta)?\b", line, re.IGNORECASE):
            return "usecase"
        if re.match(r"^swimlanes?(-beta)?\b", line, re.IGNORECASE):
            return "swimlanes"
        if re.match(r"^agentflow(-beta)?\b", line, re.IGNORECASE):
            return "agentflow"
        if re.match(r"^treeView(-beta)?\b", line, re.IGNORECASE):
            return "treeview"
        if re.match(r"^venn(-beta)?\b", line, re.IGNORECASE):
            return "venn"
        if re.match(r"^cynefin(-beta)?\b", line, re.IGNORECASE):
            return "cynefin"
        if re.match(r"^wardley(-beta)?\b", line, re.IGNORECASE):
            return "wardley"
        if re.match(r"^railroad(-(?:ebnf|abnf|peg))?(-beta)?\b", line, re.IGNORECASE):
            return "railroad"
        if re.match(r"^eventmodeling\b", line, re.IGNORECASE):
            return "eventmodeling"
        if re.match(r"^ishikawa(-beta)?\b", line, re.IGNORECASE):
            return "ishikawa"
        if _UNSUPPORTED_TYPES and re.match(
            rf"^(?:{'|'.join(_UNSUPPORTED_TYPES)})\b", line, re.IGNORECASE
        ):
            return "unsupported"
        if re.match(r"^stateDiagram", line, re.IGNORECASE):
            return "state"
        if re.match(r"^erDiagram\b", line, re.IGNORECASE):
            return "er"
        if re.match(r"^gantt\b", line, re.IGNORECASE):
            return "gantt"
        break
    return "flowchart"  # default


def render_to_svg(source: str, theme: dict[str, str] | None = None) -> str:
    """Render a single Mermaid diagram *source* string to an SVG string.

    Dispatches on the detected diagram type. Used by both the HTML pipeline
    (PDF) and the docx builder (which rasterizes the SVG for embedding).
    """
    config = _diagram_config(source)
    _ACTIVE_CONFIG.set(config)
    theme = {**(theme or {}), **_config_theme(config)}
    source = _strip_preamble(source)
    diagram_type = _detect_diagram_type(source)
    svg = _render_by_type(diagram_type, source, theme)
    if config.get("title"):
        svg = _with_title(svg, config["title"], _tokens(theme))
    return svg


def _render_by_type(diagram_type: str, source: str, theme: dict[str, str]) -> str:

    if diagram_type == "unsupported":
        kind = source.split(None, 1)[0] if source else "diagram"
        raise UnsupportedDiagramError(f"'{kind}' diagrams are not supported")
    if diagram_type == "pie":
        return render_pie_svg(parse_pie(source), theme)
    elif diagram_type == "donut":
        return render_donut_svg(parse_pie(source), theme)
    elif diagram_type == "sequence":
        return render_sequence_svg(parse_sequence(source), theme)
    elif diagram_type == "bar":
        return render_bar_svg(parse_bar(source), theme)
    elif diagram_type == "gauge":
        return render_gauge_svg(parse_gauge(source), theme)
    elif diagram_type == "timeline":
        return render_timeline_svg(parse_timeline(source), theme)
    elif diagram_type == "gantt":
        return render_gantt_svg(parse_gantt(source), theme)
    elif diagram_type == "mindmap":
        return render_mindmap_svg(parse_mindmap(source), theme)
    elif diagram_type == "er":
        return render_er_svg(parse_er(source), theme)
    elif diagram_type == "state":
        return render_state_svg(parse_state(source), theme)
    elif diagram_type == "class":
        return render_class_svg(parse_class(source), theme)
    elif diagram_type == "journey":
        return render_journey_svg(parse_journey(source), theme)
    elif diagram_type == "git":
        return render_git_svg(parse_git(source), theme)
    elif diagram_type == "quadrant":
        return render_quadrant_svg(parse_quadrant(source), theme)
    elif diagram_type == "sankey":
        return render_sankey_svg(parse_sankey(source), theme)
    elif diagram_type == "radar":
        return render_radar_svg(parse_radar(source), theme)
    elif diagram_type == "treemap":
        return render_treemap_svg(parse_treemap(source), theme)
    elif diagram_type == "packet":
        return render_packet_svg(parse_packet(source), theme)
    elif diagram_type == "block":
        return render_block_svg(parse_block(source), theme)
    elif diagram_type == "kanban":
        return render_kanban_svg(parse_kanban(source), theme)
    elif diagram_type == "architecture":
        return render_architecture_svg(parse_architecture(source), theme)
    elif diagram_type == "c4":
        return render_c4_svg(parse_c4(source), theme)
    elif diagram_type == "requirement":
        return render_requirement_svg(parse_requirement(source), theme)
    elif diagram_type == "zenuml":
        return render_zenuml_svg(source, theme)
    elif diagram_type == "usecase":
        return render_usecase_svg(parse_usecase(source), theme)
    elif diagram_type == "swimlanes":
        return render_swimlanes_svg(parse_swimlanes(source), theme)
    elif diagram_type == "agentflow":
        return render_svg(parse_agentflow(source), theme)
    elif diagram_type == "treeview":
        return render_treeview_svg(parse_treeview(source), theme)
    elif diagram_type == "venn":
        return render_venn_svg(parse_venn(source), theme)
    elif diagram_type == "cynefin":
        return render_cynefin_svg(parse_cynefin(source), theme)
    elif diagram_type == "wardley":
        return render_wardley_svg(parse_wardley(source), theme)
    elif diagram_type == "railroad":
        return render_railroad_svg(parse_railroad(source), theme)
    elif diagram_type == "eventmodeling":
        return render_eventmodeling_svg(parse_eventmodeling(source), theme)
    elif diagram_type == "ishikawa":
        return render_ishikawa_svg(*parse_ishikawa(source), theme)
    else:
        # flowchart (default for unrecognized types too)
        return render_svg(parse(source), theme)


def _unescape_mermaid_source(source: str) -> str:
    """Reverse the HTML entity escaping the markdown converter applies."""
    return (
        source.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )


def diagram_theme(
    css_text: str | None,
    config: dict | None = None,
    resolve: object = None,
    column_px: float | None = None,
) -> dict[str, str]:
    """Everything a builder passes to the renderers for one document.

    Brand colours and font from the theme CSS, the text-column width from its
    ``@page`` (so wide diagrams can be fitted), and the ``fonts`` config key
    registered for measurement and rasterising.
    """
    theme: dict[str, str] = {}
    if css_text:
        try:
            theme = extract_theme_from_css(css_text)
        except Exception:  # pragma: no cover - malformed CSS falls back to defaults
            theme = {}
    if column_px is None:
        try:
            from .builders._assets import _page_geometry

            geom = _page_geometry(css_text)
            column_px = (geom["w"] - geom["left"] - geom["right"]) / 25.4 * 96
        except Exception:
            column_px = None
    if column_px:
        theme["column_px"] = f"{column_px:.0f}"
    if config and callable(resolve):
        try:
            from .pdf_features import font_faces

            register_fonts(
                (family, path, weight)
                for family, path, weight, style in font_faces(config, resolve)  # type: ignore[arg-type]
                if style == "normal"
            )
        except Exception as exc:  # pragma: no cover - fonts are best effort
            logger.debug("diagram fonts not registered: %s", exc)
    return theme


def _wrap_diagram(svg: str) -> str:
    """Block wrapper that keeps a diagram at its natural size, shrinking to fit."""
    width = svg_natural_width(svg)
    size = f"width:{width:.0f}px;max-width:100%;" if width else ""
    return f'<div class="mermaid-diagram" style="{size}margin:10pt auto 14pt auto;">{svg}</div>'


def process_html(html: str, theme: dict[str, str] | None = None) -> str:
    """Replace all Mermaid code blocks in HTML with rendered SVGs.

    Call this after Markdown->HTML conversion but before WeasyPrint rendering.
    """

    def _replace(m: re.Match) -> str:
        source = _unescape_mermaid_source(m.group(1))
        try:
            svg = render_to_svg(source, theme)
        except UnsupportedDiagramError as exc:
            logger.warning("Mermaid: %s; leaving the source as a code block", exc)
            return m.group(0)
        return _wrap_diagram(svg)

    return _MERMAID_BLOCK_RE.sub(_replace, html)
