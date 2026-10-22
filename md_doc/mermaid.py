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

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

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


def _text_w(text: str, size: float = _FS) -> float:
    """Estimated rendered width of ``text`` at ``size`` px."""
    return len(text) * size * _CHAR_W


def _tokens(theme: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve the full colour/typography token set for one render.

    Brand colours come from the theme (``primary``/``accent``/``body``/``font``);
    every tint is derived from them so diagrams follow the document's brand.
    Explicit keys in ``theme`` (e.g. ``node_fill``) still win.
    """
    t = {**DEFAULT_THEME, **(theme or {})}
    primary, accent = t["primary"], t["accent"]
    derived = {
        "ink": t.get("body", _INK),
        "ink2": _INK_2,
        "chrome": _MUTED,
        "grid": _GRID,
        "baseline": _BASELINE,
        "edge": _EDGE,
        "node_fill": _lighten(primary, 0.94),
        "node_stroke": _lighten(primary, 0.55),
        "term_fill": primary,
        "term_text": "#ffffff",
        "diamond_fill": _lighten(accent, 0.9),
        "diamond_stroke": _lighten(accent, 0.35),
        "subgraph_fill": _lighten(primary, 0.975),
        "subgraph_stroke": _lighten(primary, 0.82),
        "subgraph_label": _INK_2,
        "note_fill": "#fff8e6",
        "note_stroke": "#ecd9a6",
    }
    for key, value in derived.items():
        if key not in (theme or {}):
            t[key] = value
    return t


def _svg_root(width: float, height: float, body: str | list[str], font: str = "") -> str:
    """Wrap SVG content in a root element sized by its viewBox."""
    if isinstance(body, list):
        body = "\n".join(body)
    font_attr = f' font-family="{_escape(font)}"' if font else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width:g} {height:g}" preserveAspectRatio="xMidYMid meet"{font_attr}>\n'
        f"{body}\n</svg>"
    )


def svg_natural_width(svg: str) -> float | None:
    """The diagram's natural width in px (its viewBox width), if known."""
    m = re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"', svg)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# CSS theme extraction
# ---------------------------------------------------------------------------


def extract_theme_from_css(css_text: str) -> dict[str, str]:
    """Extract diagram theme colours from a _pdf-theme.css file.

    Looks for known CSS colour patterns in selectors like h1, h2, th, a,
    .cover-bar, etc. and maps them to theme keys.
    """
    theme: dict[str, str] = {}

    def _find(pattern: str) -> str | None:
        m = re.search(pattern, css_text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    # Primary colour — from h1 color or .cover-title color or th background
    primary = (
        _find(r"\.cover-title\s*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})")
        or _find(r"\bh1\b[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})")
        or _find(r"\bth\b[^{]*\{[^}]*background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,8})")
    )
    if primary:
        theme["primary"] = primary

    # Accent colour — from h2 color or a color or .cover-label color
    accent = (
        _find(r"\bh2\b[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})")
        or _find(r"\ba\b[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})")
        or _find(r"\.cover-label[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})")
    )
    if accent:
        theme["accent"] = accent

    # Body text colour
    body = _find(r"\bbody\b[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})")
    if body:
        theme["body"] = body

    # Muted colour — from h3 color or em color
    muted = _find(r"\bh3\b[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})") or _find(
        r"\bem\b[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})"
    )
    if muted:
        theme["muted"] = muted

    # Font family
    font = _find(r"\bbody\b[^{]*\{[^}]*font-family\s*:\s*([^;]+)")
    if font:
        theme["font"] = font.strip("'\"")

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
        (?P<plain>-{2,}>|-{3,}|-{2,}[ox](?=\s|$)|={2,}>|={3,}|={2,}[ox](?=\s|$)
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

    nid = _ensure_node_token(fc, token)
    if nid in fc.nodes:
        fc.nodes[nid].classes.extend(c for c in classes if c not in fc.nodes[nid].classes)
    return nid


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
    return fc


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


def _er_marker_defs(color: str) -> str:
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
            f'<circle cx="{circles[kind]:g}" cy="7" r="3.2" fill="#ffffff" stroke="{color}" '
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
        max_chars = max(len(line) for line in lines)
        num_lines = len(lines)

        node.w = max(max_chars * font_size * _CHAR_W + 32, 96)
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

    # Subgraph frames: inner ones first so an outer frame can wrap its children
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
        x0 = min(b[0] for b in boxes) - sg_pad
        y0 = min(b[1] for b in boxes) - sg_pad - 18  # room for the title
        sg.x, sg.y = x0, y0
        sg.w = max(b[2] for b in boxes) + sg_pad - x0
        sg.h = max(b[3] for b in boxes) + sg_pad - y0


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
            f'<circle cx="5" cy="5" r="3.6" fill="#ffffff" stroke="{c}" stroke-width="1.4"/></marker>',
            f'<marker id="{prefix}circle-s{sfx}" markerWidth="10" markerHeight="10" refX="1" refY="5" {common}>'
            f'<circle cx="5" cy="5" r="3.6" fill="#ffffff" stroke="{c}" stroke-width="1.4"/></marker>',
            f'<marker id="{prefix}cross{sfx}" markerWidth="10" markerHeight="10" refX="9" refY="5" {common}>'
            f'<path d="M2 2 L8 8 M8 2 L2 8" stroke="{c}" stroke-width="1.6" fill="none"/></marker>',
            f'<marker id="{prefix}cross-s{sfx}" markerWidth="10" markerHeight="10" refX="1" refY="5" {common}>'
            f'<path d="M2 2 L8 8 M8 2 L2 8" stroke="{c}" stroke-width="1.6" fill="none"/></marker>',
        ]
    out.append("</defs>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# SVG renderer — flowchart
# ---------------------------------------------------------------------------


def render_svg(fc: Flowchart, theme: dict[str, str] | None = None) -> str:
    """Render a laid-out Flowchart to an SVG string."""
    t = _tokens(theme)
    layout(fc, t)

    if not fc.nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    parts: list[str] = []

    # Tight canvas around everything drawn (nodes, frames, edge lanes)
    xs0 = [n.x for n in fc.nodes.values()] + [sg.x for sg in fc.subgraphs if sg.w > 0]
    ys0 = [n.y for n in fc.nodes.values()] + [sg.y for sg in fc.subgraphs if sg.w > 0]
    xs1 = [n.x + n.w for n in fc.nodes.values()] + [sg.x + sg.w for sg in fc.subgraphs if sg.w > 0]
    ys1 = [n.y + n.h for n in fc.nodes.values()] + [sg.y + sg.h for sg in fc.subgraphs if sg.w > 0]
    for pts in fc.waypoints.values():
        xs0 += [px for px, _ in pts]
        xs1 += [px for px, _ in pts]
        ys0 += [py for _, py in pts]
        ys1 += [py for _, py in pts]
    longest_label = max((len(e.label) for e in fc.edges), default=0)
    pad = 10.0
    right_pad = pad + (longest_label * 3.0 if fc.direction not in ("LR", "RL") else 0)
    ox, oy = min(xs0) - pad, min(ys0) - pad
    width = max(xs1) - ox + right_pad
    height = max(ys1) - oy + pad

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
        if 'fill-opacity="0.07"' in part:  # the soft shadow keeps its own look
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
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{node.w / 2 - 3}" fill="#ffffff"/>')
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
            f'rx="{corner}" fill="#0b1f33" fill-opacity="0.07"/>'
        )

    poly = _node_polygon(node)
    if poly:
        parts.append(f'<polygon points="{poly}" {style} stroke-linejoin="round"/>')
    elif node.shape == "circle":
        r = min(node.w, node.h) / 2
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" {style}/>')
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
            f'rx="3" fill="#ffffff"/>'
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
    return "#ffffff" if lum < 0.45 else t["ink"]


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


def _fold_slices(slices: list[tuple[str, float]]) -> list[tuple[str, float, str]]:
    """Assign categorical slots in source order; past eight, fold the smallest into Other."""
    data = [(label, value) for label, value in slices if value > 0]
    if len(data) > len(_CATEGORICAL):
        keep = sorted(range(len(data)), key=lambda i: -data[i][1])[: len(_CATEGORICAL) - 1]
        kept = [data[i] for i in sorted(keep)]
        other = sum(v for i, (_, v) in enumerate(data) if i not in keep)
        return [(lbl, v, _CATEGORICAL[i]) for i, (lbl, v) in enumerate(kept)] + [
            ("Other", other, _OTHER)
        ]
    return [(lbl, v, _CATEGORICAL[i]) for i, (lbl, v) in enumerate(data)]


def _render_part_to_whole(pc: PieChart, t: dict[str, str], hole: float) -> str:
    """Pie (``hole`` = 0) or donut (``hole`` = inner/outer radius ratio)."""
    slices = _fold_slices(pc.slices)
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
                parts.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{ri:g}" fill="#ffffff"/>')
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
                f'<path d="{d}" fill="{color}" stroke="#ffffff" stroke-width="2" '
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

    msg_color = "#57606a"
    life_color = "#d0d7de"
    frame_color = "#c9ced4"
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
                f'stroke="#ffffff" stroke-width="1.5"/>'
            )
            drawn.append(_svg_text(nx, line_y + 3.5, str(number), t, 9.5, "#ffffff", 600, "middle"))
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
        fill = _lighten(t["primary"], 0.97) if tag == "rect" else "none"
        parts.append(
            f'<rect x="{fx0:g}" y="{fy0:g}" width="{fx1 - fx0:g}" height="{fy1 - fy0:g}" rx="4" '
            f'fill="{fill}" stroke="{frame_color}" stroke-width="1"/>'
        )
        if tag != "rect":
            parts.append(
                f'<path d="M {fx0:g},{fy0 + 4:g} Q {fx0:g},{fy0:g} {fx0 + 4:g},{fy0:g} H {fx0 + tag_w:g} '
                f'V {fy0 + 12:g} L {fx0 + tag_w - 6:g},{fy0 + 18:g} H {fx0:g} Z" fill="#f3f4f6" '
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
                    f'<circle cx="{cx:g}" cy="{hy:g}" r="6" fill="#ffffff"/>'
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
                    f'rx="6" fill="#ffffff" stroke="{t["node_stroke"]}" stroke-width="1.25"/>'
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
    colors = [_CATEGORICAL[i % len(_CATEGORICAL)] for i in range(len(series))]
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
                f'stroke="#ffffff" stroke-width="2"/>'
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
    track = _lighten(fill, 0.85)
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
        f'stroke="#ffffff" stroke-width="2"/>'
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
    sec_color = {s: _CATEGORICAL[i % len(_CATEGORICAL)] for i, s in enumerate(sections)}

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
            color = _CATEGORICAL[i % len(_CATEGORICAL)]
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
            f'fill="none" stroke="{_lighten(color, 0.25 if depth == 1 else 0.45)}" '
            f'stroke-width="{2 if depth == 1 else 1.5}" stroke-linecap="round"/>'
        )
    parts.append(
        f'<rect x="{-rw / 2:g}" y="{root_cy - lw / 2:g}" width="{rw:g}" height="{lw:g}" '
        f'rx="{lw / 2:g}" fill="{t["term_fill"]}"/>'
    )
    parts.append(_svg_text(0, root_cy + 4.6, root.label, t, 13, "#ffffff", 600, "middle"))
    for node, depth, x, by, w, h, color in boxes:
        if depth == 1:
            fill, stroke, fs, weight = _lighten(color, 0.86), _lighten(color, 0.35), _FS, 500
        else:
            fill, stroke, fs, weight = "#ffffff", _lighten(color, 0.6), 11.5, 400
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
    ports = _assign_ports(fc)

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
    parts = [_er_marker_defs(color), f'<g transform="translate({-ox:g},{-oy:g})">']

    for i, rel in enumerate(erd.relations):
        src, dst = fc.nodes.get(rel.entity_a), fc.nodes.get(rel.entity_b)
        if not src or not dst:
            continue
        d, label_xy = _routed_path(
            src,
            dst,
            fc.waypoints.get(i, []),
            True,
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
                f'<rect x="{lx - lw / 2:g}" y="{ly - 11:g}" width="{lw:g}" height="15" rx="3" fill="#ffffff"/>'
            )
            parts.append(_svg_text(lx, ly, rel.label, t, _FS_SM, t["ink2"], anchor="middle"))

    for name, ent in erd.entities.items():
        node = fc.nodes[name]
        x, y, w, h = node.x, node.y, node.w, node.h
        _, _, type_col, _key_col = cards[name]
        r = 6.0
        parts.append(
            f'<rect x="{x:g}" y="{y + 1.5:g}" width="{w:g}" height="{h:g}" rx="{r:g}" '
            f'fill="#0b1f33" fill-opacity="0.07"/>'
        )
        parts.append(
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{r:g}" fill="#ffffff" '
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
        parts.append(_svg_text(x + w / 2, y + hb / 2 + 4.3, name, t, _FS, "#ffffff", 600, "middle"))
        for k, (attr, key) in enumerate(
            zip(ent.attributes, ent.keys or [""] * len(ent.attributes))
        ):
            ry = y + head_h + 2 + k * row_h
            typ, _, aname = attr.partition(" ")
            if k:
                parts.append(
                    f'<line x1="{x + 1:g}" y1="{ry:g}" x2="{x + w - 1:g}" y2="{ry:g}" '
                    f'stroke="#eef0f2" stroke-width="1"/>'
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
_UNSUPPORTED_TYPES = (
    "classDiagram",
    "journey",
    "gitGraph",
    "quadrantChart",
    "requirementDiagram",
    "sankey",
    "block",
    "packet",
    "kanban",
    "architecture",
    "C4Context",
    "C4Container",
    "C4Component",
    "C4Dynamic",
    "C4Deployment",
    "zenuml",
    "radar",
    "treemap",
)


def _strip_preamble(source: str) -> str:
    """Drop a YAML front-matter block and ``%%{init: ...}%%`` directives before the diagram."""
    text = source.strip()
    fm = re.match(r"^---\s*\n.*?\n---[ \t]*\n", text + "\n", re.DOTALL)
    if fm:
        text = text[fm.end() :]
    return re.sub(r"^\s*%%\{.*?\}%%[ \t]*\n?", "", text, flags=re.DOTALL).strip()


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
        if re.match(rf"^(?:{'|'.join(_UNSUPPORTED_TYPES)})\b", line, re.IGNORECASE):
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
    source = _strip_preamble(source)
    diagram_type = _detect_diagram_type(source)

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
