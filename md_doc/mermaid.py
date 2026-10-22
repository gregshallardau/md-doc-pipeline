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


@dataclass
class PieChart:
    title: str = ""
    slices: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class SeqMessage:
    src: str
    dst: str
    label: str = ""
    arrow: str = "->"  # -> | ->> | --> | -->>


@dataclass
class SequenceDiagram:
    participants: list[str] = field(default_factory=list)
    messages: list[SeqMessage] = field(default_factory=list)


@dataclass
class BarChart:
    title: str = ""
    labels: list[str] = field(default_factory=list)
    datasets: list[tuple[str, list[float]]] = field(default_factory=list)  # (name, values)
    horizontal: bool = False


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
    attributes: list[str] = field(default_factory=list)


@dataclass
class ERRelation:
    entity_a: str = ""
    entity_b: str = ""
    card_a: str = ""  # ||, |{, o{, }|, }o
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
    "body": "#1a1a2e",
    "muted": "#5d6d7e",
    "node_fill": "#d6eaf8",
    "node_stroke": "#1b4f72",
    "diamond_fill": "#fef5e7",
    "diamond_stroke": "#e67e22",
    "subgraph_fill": "#f8f9fa",
    "subgraph_stroke": "#dee2e6",
    "subgraph_label": "#495057",
    "font": "Segoe UI, Helvetica Neue, Arial, sans-serif",
}

# Palette for pie chart slices
_PIE_COLORS = [
    "#2e86c1",
    "#e67e22",
    "#27ae60",
    "#c0392b",
    "#8e44ad",
    "#16a085",
    "#d35400",
    "#2980b9",
    "#f39c12",
    "#1abc9c",
]

# Palette for sequence diagram participants
_SEQ_COLORS = [
    "#d6eaf8",
    "#fef5e7",
    "#eaf5ea",
    "#fce4ec",
    "#e8f0fe",
    "#e0f2f1",
    "#fff3e0",
    "#f3e5f5",
]


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
        theme["node_stroke"] = primary

    # Accent colour — from h2 color or a color or .cover-label color
    accent = (
        _find(r"\bh2\b[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})")
        or _find(r"\ba\b[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})")
        or _find(r"\.cover-label[^{]*\{[^}]*color\s*:\s*(#[0-9a-fA-F]{3,8})")
    )
    if accent:
        theme["accent"] = accent
        theme["diamond_stroke"] = accent

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
        theme["subgraph_label"] = muted

    # Node fill — lighten primary if we have one
    if primary:
        theme["node_fill"] = _lighten(primary, 0.85)
    if accent:
        theme["diamond_fill"] = _lighten(accent, 0.88)

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
    """Parse a Mermaid pie chart definition."""
    pc = PieChart()
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if line.lower().startswith("pie"):
            continue

        # title line
        title_m = re.match(r"^title\s+(.+)$", line, re.IGNORECASE)
        if title_m:
            pc.title = title_m.group(1).strip()
            continue

        # slice: "Label" : value
        slice_m = re.match(r'^"([^"]+)"\s*:\s*([\d.]+)\s*$', line)
        if slice_m:
            pc.slices.append((slice_m.group(1), float(slice_m.group(2))))

    return pc


# ---------------------------------------------------------------------------
# Sequence diagram parser
# ---------------------------------------------------------------------------

_SEQ_MSG_RE = re.compile(r"^(\S+?)\s*(-->>|->>|-->|->)\s*(\S+)\s*:\s*(.*)$")

_SEQ_NOTE_RE = re.compile(r"^Note\s+(left|right|over)\s+(?:of\s+)?(.+?):\s*(.+)$", re.IGNORECASE)


def parse_sequence(source: str) -> SequenceDiagram:
    """Parse a Mermaid sequence diagram definition."""
    sd = SequenceDiagram()
    seen_participants: set[str] = set()

    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or line.lower() == "sequencediagram":
            continue

        # participant declaration
        p_m = re.match(r"^participant\s+(\S+)(?:\s+as\s+(.+))?$", line, re.IGNORECASE)
        if p_m:
            name = p_m.group(1)
            if name not in seen_participants:
                sd.participants.append(name)
                seen_participants.add(name)
            continue

        # actor declaration (same as participant visually)
        a_m = re.match(r"^actor\s+(\S+)(?:\s+as\s+(.+))?$", line, re.IGNORECASE)
        if a_m:
            name = a_m.group(1)
            if name not in seen_participants:
                sd.participants.append(name)
                seen_participants.add(name)
            continue

        # message line
        msg_m = _SEQ_MSG_RE.match(line)
        if msg_m:
            src, arrow, dst, label = msg_m.groups()
            # Auto-register participants
            for p in (src, dst):
                if p not in seen_participants:
                    sd.participants.append(p)
                    seen_participants.add(p)
            sd.messages.append(SeqMessage(src=src, dst=dst, label=label.strip(), arrow=arrow))

    return sd


# ---------------------------------------------------------------------------
# Bar chart parser (xychart-beta or custom "bar" keyword)
# ---------------------------------------------------------------------------


def parse_bar(source: str) -> BarChart:
    """Parse a bar chart definition."""
    bc = BarChart()
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^(xychart-beta|bar)\b", line, re.IGNORECASE) and "[" not in line:
            if "horizontal" in line.lower():
                bc.horizontal = True
            continue

        title_m = re.match(r'^title\s+"?([^"]+)"?\s*$', line, re.IGNORECASE)
        if title_m:
            bc.title = title_m.group(1).strip()
            continue

        # x-axis ["Q1", "Q2", ...]
        xaxis_m = re.match(r"^x-axis\s+\[(.+)\]\s*$", line, re.IGNORECASE)
        if xaxis_m:
            bc.labels = [s.strip().strip('"').strip("'") for s in xaxis_m.group(1).split(",")]
            continue

        # bar [120, 150, ...]  or  line [100, 130, ...]
        data_m = re.match(r"^(bar|line)\s+\[(.+)\]\s*$", line, re.IGNORECASE)
        if data_m:
            name = data_m.group(1)
            vals = [float(v.strip()) for v in data_m.group(2).split(",") if v.strip()]
            bc.datasets.append((name, vals))
            continue

        # Simple format: "Label": value
        simple_m = re.match(r'^"([^"]+)"\s*:\s*([\d.]+)\s*$', line)
        if simple_m:
            bc.labels.append(simple_m.group(1))
            if not bc.datasets:
                bc.datasets.append(("", []))
            bc.datasets[0][1].append(float(simple_m.group(2)))

    return bc


# ---------------------------------------------------------------------------
# Gauge chart parser (custom syntax)
# ---------------------------------------------------------------------------


def parse_gauge(source: str) -> GaugeChart:
    """Parse a gauge chart definition."""
    gc = GaugeChart()
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^gauge\b", line, re.IGNORECASE):
            continue

        title_m = re.match(r"^title\s+(.+)$", line, re.IGNORECASE)
        if title_m:
            gc.title = title_m.group(1).strip()
            continue

        val_m = re.match(r"^value\s+([\d.]+)\s*$", line, re.IGNORECASE)
        if val_m:
            gc.value = float(val_m.group(1))
            continue

        max_m = re.match(r"^max\s+([\d.]+)\s*$", line, re.IGNORECASE)
        if max_m:
            gc.max_val = float(max_m.group(1))
            continue

        min_m = re.match(r"^min\s+([\d.]+)\s*$", line, re.IGNORECASE)
        if min_m:
            gc.min_val = float(min_m.group(1))
            continue

        label_m = re.match(r"^label\s+(.+)$", line, re.IGNORECASE)
        if label_m:
            gc.label = label_m.group(1).strip()

    return gc


# ---------------------------------------------------------------------------
# Timeline parser
# ---------------------------------------------------------------------------


def parse_timeline(source: str) -> Timeline:
    """Parse a Mermaid timeline definition."""
    tl = Timeline()
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

        # "period : event1 : event2"
        if ":" in line:
            parts = [p.strip() for p in line.split(":")]
            period = parts[0]
            events = [e for e in parts[1:] if e]
            tl.entries.append(TimelineEntry(period=period, events=events))

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

        if line.lower().startswith("axisformat"):
            continue

        sec_m = re.match(r"^section\s+(.+)$", line, re.IGNORECASE)
        if sec_m:
            current_section = sec_m.group(1).strip()
            continue

        # Task line: "Task name :id, start, duration" or "Task name :start, duration"
        task_m = re.match(r"^(.+?)\s*:\s*(.+)$", line)
        if task_m:
            name = task_m.group(1).strip()
            params = [p.strip() for p in task_m.group(2).split(",")]
            task = GanttTask(name=name, section=current_section)
            # Parse params — could be: id,start,dur or start,dur or after id,dur
            for p in params:
                if p.lower() in _GANTT_TAGS:
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

        # Calculate indent level (count leading spaces / 4 or tabs)
        stripped = raw_line.lstrip()
        indent = len(raw_line) - len(stripped)

        # Extract label — remove shape markers
        label = stripped.strip()
        # root((label)) or ((label)) or (label) or [label] or {{label}} or )label(
        for pattern in [
            r"^root\(\((.+)\)\)$",
            r"^\(\((.+)\)\)$",
            r"^\((.+)\)$",
            r"^\[(.+)\]$",
            r"^\{\{(.+)\}\}$",
            r"^\)(.+)\($",
        ]:
            m = re.match(pattern, label)
            if m:
                label = m.group(1)
                break

        node = MindNode(label=label)

        if not stack:
            root = node
            stack.append((indent, node))
        else:
            # Find parent: walk back up the stack to find a node with lower indent
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

_ER_REL_RE = re.compile(
    r"^(\S+)\s+(\|\|--|\|\|\.\.|\|o--|}o--|}\|--|\|\{--|o\|--|o\{--"
    r"|--\|\||--\.\.\||--o\||--o\{|--\|\{|--\|o"
    r"|\|\|--o\{|\|\|--\|\{|o\|--\|\{|\}o--o\{"
    r"|\|\|--o\||o\{--\|\||\}\|--o\{|\|\|\.\.o\{"
    r")\s+(\S+)\s*:\s*(.+)$"
)

# Simpler regex that catches the common patterns
_ER_REL_SIMPLE = re.compile(r"^(\S+)\s+([|o}{]+[-.][-.]?[|o}{]+)\s+(\S+)\s*:\s*(.+)$")


def parse_er(source: str) -> ERDiagram:
    """Parse a Mermaid ER diagram."""
    erd = ERDiagram()
    current_entity: str | None = None
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^erDiagram\b", line, re.IGNORECASE):
            continue

        # End of an attribute block
        if line == "}":
            current_entity = None
            continue

        # Attribute line inside an entity block ("type name" pairs)
        if current_entity is not None:
            attr_m = re.match(r"^(\w+)\s+(\w+)", line)
            if attr_m:
                erd.entities[current_entity].attributes.append(
                    f"{attr_m.group(1)} {attr_m.group(2)}"
                )
            continue

        # Try relationship line
        m = _ER_REL_SIMPLE.match(line)
        if m:
            a, cardinality, b, label = m.groups()
            is_dotted = ".." in cardinality
            # Parse cardinality markers from the full string
            card_a = ""
            card_b = ""
            if "||" in cardinality:
                card_a = "||"
            elif "|o" in cardinality or "o|" in cardinality:
                card_a = "o|"
            if "|{" in cardinality or "{|" in cardinality:
                card_b = "|{"
            elif "o{" in cardinality:
                card_b = "o{"

            erd.relations.append(
                ERRelation(
                    entity_a=a,
                    entity_b=b,
                    card_a=card_a,
                    card_b=card_b,
                    label=label.strip(),
                    style="dotted" if is_dotted else "solid",
                )
            )
            # Auto-register entities
            for name in (a, b):
                if name not in erd.entities:
                    erd.entities[name] = EREntity(name=name)
            continue

        # Entity block opener: "NAME {"
        ent_m = re.match(r"^(\S+)\s*\{", line)
        if ent_m:
            name = ent_m.group(1)
            if name not in erd.entities:
                erd.entities[name] = EREntity(name=name)
            current_entity = name
            continue

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
        if horizontal:
            node.x, node.y = major_pos[levels[n]], pos
        else:
            node.x, node.y = pos, major_pos[levels[n]]
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
        lines = re.split(r"<br\s*/?>|\n", node.label)
        max_chars = max(len(line) for line in lines)
        num_lines = len(lines)

        node.w = max(max_chars * font_size * 0.55 + 32, 90)
        node.h = max(num_lines * (font_size + 6) + 20, 44)

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
        longest_label = max((len(e.label) for e in fc.edges), default=0)
        gap_major = max(gap_major, longest_label * 5.5 + 56)

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
            cursor += max(fc.nodes[n].w for n in level_groups[lvl]) + gap_major
    else:
        for lvl in sorted(level_groups):
            major_pos[lvl] = cursor
            cursor += max(fc.nodes[n].h for n in level_groups[lvl]) + gap_major

    baseline = _total_crossings(level_groups, children_map)
    fc.crossings = _layout_layered(
        fc, levels, level_groups, children_map, major_pos, is_horizontal, padding, gap_minor
    )
    fc.crossings_unordered = baseline

    # Hand the lane positions to the edge router and drop the helper nodes
    fc.waypoints = {
        i: [(fc.nodes[n].x + fc.nodes[n].w / 2, fc.nodes[n].y + fc.nodes[n].h / 2) for n in ids]
        for i, ids in lanes.items()
    }
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
    muted = t.get("muted", "#5d6d7e")
    out = ["<defs>"]
    for color in (None, *colors):
        c = color or muted
        sfx = _color_suffix(color)
        common = 'markerUnits="userSpaceOnUse" orient="auto"'
        out += [
            f'<marker id="{prefix}arr{sfx}" markerWidth="10" markerHeight="8" refX="9" refY="4" {common}>'
            f'<polygon points="0 0.5, 9 4, 0 7.5" fill="{c}"/></marker>',
            f'<marker id="{prefix}arr-thick{sfx}" markerWidth="13" markerHeight="10" refX="12" refY="5" {common}>'
            f'<polygon points="0 0.5, 12 5, 0 9.5" fill="{c}"/></marker>',
            f'<marker id="{prefix}arr-s{sfx}" markerWidth="10" markerHeight="8" refX="1" refY="4" {common}>'
            f'<polygon points="10 0.5, 1 4, 10 7.5" fill="{c}"/></marker>',
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
    t = {**DEFAULT_THEME, **(theme or {})}
    layout(fc, t)

    if not fc.nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    parts: list[str] = []

    # Calculate canvas size
    max_x = max(n.x + n.w for n in fc.nodes.values()) + 30
    max_y = max(n.y + n.h for n in fc.nodes.values()) + 30

    # Account for subgraph bounding boxes
    for sg in fc.subgraphs:
        if sg.w > 0:
            max_x = max(max_x, sg.x + sg.w + 30)
            max_y = max(max_y, sg.y + sg.h + 30)

    for pts in fc.waypoints.values():
        for px, py in pts:
            max_x = max(max_x, px + 30)
            max_y = max(max_y, py + 30)

    width = max(max_x, 200)
    height = max(max_y, 100)

    edge_colors = tuple(sorted({e.css["stroke"] for e in fc.edges if "stroke" in e.css}))
    parts.append(_make_arrow_defs(t, colors=edge_colors))
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

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

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


def _render_subgraph(sg: Subgraph, t: dict[str, str]) -> str:
    """Render a subgraph frame: a softly tinted panel with its title."""
    if sg.w <= 0 or sg.h <= 0:
        return ""
    font = t.get("font", DEFAULT_THEME["font"])
    fill = t.get("subgraph_fill", "#f8f9fa")
    stroke = t.get("subgraph_stroke", "#dee2e6")
    label_color = t.get("subgraph_label", "#495057")

    return "\n".join(
        [
            f'<rect x="{sg.x}" y="{sg.y}" width="{sg.w}" height="{sg.h}" '
            f'rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1"/>',
            f'<text x="{sg.x + 10}" y="{sg.y + 15}" '
            f'font-family="{font}" font-size="10" font-weight="700" '
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
    sw = 1.5

    if node.shape in ("start", "end"):
        primary = t.get("primary", "#1b4f72")
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{node.w / 2}" fill="{primary}"/>')
        if node.shape == "end":
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{node.w / 2 - 3}" fill="#ffffff"/>')
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{node.w / 2 - 5}" fill="{primary}"/>')
        return "\n".join(parts)

    if node.shape == "diamond":
        fill, stroke = t["diamond_fill"], t["diamond_stroke"]
    else:
        fill, stroke = t["node_fill"], t["node_stroke"]
    style = f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"'

    corner = {"rect": 6, "rounded": 12, "subroutine": 4, "stadium": node.h / 2}.get(node.shape)
    if node.shape in _SHADOW_SHAPES:
        parts.append(
            f'<rect x="{node.x + 1.2}" y="{node.y + 2}" width="{node.w}" height="{node.h}" '
            f'rx="{corner}" fill="#000000" fill-opacity="0.07"/>'
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
    line_height = 14
    start_y = cy - (len(lines) - 1) * line_height / 2

    for i, line_text in enumerate(lines):
        text_y = start_y + i * line_height + 4
        parts.append(
            f'<text x="{cx}" y="{text_y}" text-anchor="middle" '
            f'font-family="{font}" font-size="11" font-weight="600" '
            f'fill="{t.get("body", "#1a1a2e")}">{_escape(line_text.strip())}</text>'
        )

    if node.css:
        parts = _apply_node_css(parts, node.css)
    return "\n".join(parts)


_PORT_SHAPES = ("rect", "rounded", "stadium", "subroutine")
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
    straight_only = True
    for k, (p, q) in enumerate(zip(pts, pts[1:])):
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
        label_xy = ((mid + end[0]) / 2, end[1] - 5)
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
    muted = t.get("muted", "#5d6d7e")
    parts: list[str] = []
    css = edge.css if edge else {}
    head = "none" if style == "none" else (edge.head if edge else "arrow")
    tail = edge.tail if edge else "none"

    stroke = css.get("stroke", muted)
    width = css.get("stroke-width", "3" if style == "thick" else "1.5")
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
            ly += lane * 2.2 if lane else -8
        else:
            lx += lane * 2.2 if lane else 10
        # Background for readability
        est_w = len(label) * 5.5 + 8
        parts.append(
            f'<rect x="{lx - est_w / 2}" y="{ly - 10}" width="{est_w}" height="14" '
            f'rx="3" fill="#ffffff" fill-opacity="0.85"/>'
        )
        parts.append(
            f'<text x="{lx}" y="{ly}" text-anchor="middle" '
            f'font-family="{font}" font-size="9" fill="{muted}">'
            f"{_escape(label)}</text>"
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# SVG renderer — pie chart
# ---------------------------------------------------------------------------


def render_pie_svg(pc: PieChart, theme: dict[str, str] | None = None) -> str:
    """Render a PieChart to an SVG string."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])

    if not pc.slices:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    total = sum(v for _, v in pc.slices)
    if total <= 0:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    # Layout
    cx, cy, r = 160, 140, 110
    legend_x = cx + r + 40
    width = legend_x + 180
    height = max(cy + r + 40, len(pc.slices) * 22 + 80)

    parts: list[str] = []
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    # Title
    if pc.title:
        parts.append(
            f'<text x="{width / 2}" y="28" text-anchor="middle" '
            f'font-family="{font}" font-size="14" font-weight="700" '
            f'fill="{t.get("body", "#1a1a2e")}">{_escape(pc.title)}</text>'
        )

    # Draw slices
    angle = -math.pi / 2  # start at top
    for i, (label, value) in enumerate(pc.slices):
        fraction = value / total
        sweep = fraction * 2 * math.pi
        color = _PIE_COLORS[i % len(_PIE_COLORS)]

        x1 = cx + r * math.cos(angle)
        y1 = cy + r * math.sin(angle)
        x2 = cx + r * math.cos(angle + sweep)
        y2 = cy + r * math.sin(angle + sweep)

        large_arc = 1 if sweep > math.pi else 0

        if sweep >= 2 * math.pi - 1e-9:
            # A single full-circle slice: an arc with coincident endpoints draws
            # nothing, so emit a circle instead.
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" '
                f'stroke="#ffffff" stroke-width="2"/>'
            )
        else:
            path = (
                f"M {cx},{cy} L {x1:.1f},{y1:.1f} " f"A {r},{r} 0 {large_arc} 1 {x2:.1f},{y2:.1f} Z"
            )
            parts.append(f'<path d="{path}" fill="{color}" stroke="#ffffff" stroke-width="2"/>')

        # Percentage label on slice (if big enough)
        if fraction > 0.05:
            mid_angle = angle + sweep / 2
            label_r = r * 0.65
            lx = cx + label_r * math.cos(mid_angle)
            ly = cy + label_r * math.sin(mid_angle)
            pct = f"{fraction * 100:.0f}%"
            parts.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" '
                f'font-family="{font}" font-size="10" font-weight="700" '
                f'fill="#ffffff">{pct}</text>'
            )

        angle += sweep

    # Legend
    ly_start = 60
    for i, (label, value) in enumerate(pc.slices):
        color = _PIE_COLORS[i % len(_PIE_COLORS)]
        ly = ly_start + i * 22
        parts.append(
            f'<rect x="{legend_x}" y="{ly}" width="12" height="12" rx="2" fill="{color}"/>'
        )
        pct = f"{value / total * 100:.1f}%"
        parts.append(
            f'<text x="{legend_x + 18}" y="{ly + 10}" '
            f'font-family="{font}" font-size="10" fill="{t.get("body", "#1a1a2e")}">'
            f"{_escape(label)} ({pct})</text>"
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


# ---------------------------------------------------------------------------
# SVG renderer — sequence diagram
# ---------------------------------------------------------------------------


def render_sequence_svg(sd: SequenceDiagram, theme: dict[str, str] | None = None) -> str:
    """Render a SequenceDiagram to an SVG string."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])
    body_color = t.get("body", "#1a1a2e")
    muted = t.get("muted", "#5d6d7e")

    if not sd.participants:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    # Layout constants
    col_width = 160
    row_height = 40
    box_h = 32
    box_pad = 16
    top_margin = 20
    left_margin = 30

    n_cols = len(sd.participants)
    n_rows = len(sd.messages)

    width = left_margin * 2 + n_cols * col_width
    height = top_margin + box_h + 20 + n_rows * row_height + box_h + 40

    # Participant x positions (center of each column)
    px: dict[str, float] = {}
    for i, p in enumerate(sd.participants):
        px[p] = left_margin + i * col_width + col_width / 2

    parts: list[str] = []
    parts.append(_make_arrow_defs(t, "seq-"))
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    # Draw participant boxes (top)
    box_y = top_margin
    for i, p in enumerate(sd.participants):
        x = px[p]
        fill = _SEQ_COLORS[i % len(_SEQ_COLORS)]
        bw = max(len(p) * 8 + box_pad * 2, 80)
        bx = x - bw / 2
        parts.append(
            f'<rect x="{bx}" y="{box_y}" width="{bw}" height="{box_h}" '
            f'rx="4" fill="{fill}" stroke="{muted}" stroke-width="1.2"/>'
        )
        parts.append(
            f'<text x="{x}" y="{box_y + box_h / 2 + 4}" text-anchor="middle" '
            f'font-family="{font}" font-size="11" font-weight="600" '
            f'fill="{body_color}">{_escape(p)}</text>'
        )

    # Draw lifelines
    lifeline_top = box_y + box_h
    lifeline_bottom = height - box_h - 30
    for p in sd.participants:
        x = px[p]
        parts.append(
            f'<line x1="{x}" y1="{lifeline_top}" x2="{x}" y2="{lifeline_bottom}" '
            f'stroke="{muted}" stroke-width="1" stroke-dasharray="4 3"/>'
        )

    # Draw messages
    msg_y_start = lifeline_top + 25
    for i, msg in enumerate(sd.messages):
        y = msg_y_start + i * row_height
        x1 = px.get(msg.src, left_margin)
        x2 = px.get(msg.dst, left_margin + col_width)

        # Determine arrow style
        is_dashed = msg.arrow.startswith("--")
        stroke_style = 'stroke-dasharray="5 3"' if is_dashed else ""

        # Self-message
        if msg.src == msg.dst:
            loop_w = 30
            parts.append(
                f'<path d="M {x1},{y} L {x1 + loop_w},{y} '
                f'L {x1 + loop_w},{y + 20} L {x1},{y + 20}" '
                f'stroke="{muted}" stroke-width="1.5" fill="none" {stroke_style} '
                f'marker-end="url(#seq-arr)"/>'
            )
            parts.append(
                f'<text x="{x1 + loop_w + 5}" y="{y + 12}" '
                f'font-family="{font}" font-size="10" fill="{body_color}">'
                f"{_escape(msg.label)}</text>"
            )
        else:
            parts.append(
                f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" '
                f'stroke="{muted}" stroke-width="1.5" {stroke_style} '
                f'marker-end="url(#seq-arr)"/>'
            )
            # Label above the line
            lx = (x1 + x2) / 2
            parts.append(
                f'<text x="{lx}" y="{y - 6}" text-anchor="middle" '
                f'font-family="{font}" font-size="10" fill="{body_color}">'
                f"{_escape(msg.label)}</text>"
            )

    # Draw participant boxes (bottom)
    bottom_box_y = lifeline_bottom
    for i, p in enumerate(sd.participants):
        x = px[p]
        fill = _SEQ_COLORS[i % len(_SEQ_COLORS)]
        bw = max(len(p) * 8 + box_pad * 2, 80)
        bx = x - bw / 2
        parts.append(
            f'<rect x="{bx}" y="{bottom_box_y}" width="{bw}" height="{box_h}" '
            f'rx="4" fill="{fill}" stroke="{muted}" stroke-width="1.2"/>'
        )
        parts.append(
            f'<text x="{x}" y="{bottom_box_y + box_h / 2 + 4}" text-anchor="middle" '
            f'font-family="{font}" font-size="11" font-weight="600" '
            f'fill="{body_color}">{_escape(p)}</text>'
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


# ---------------------------------------------------------------------------
# SVG renderer — bar chart
# ---------------------------------------------------------------------------


def render_bar_svg(bc: BarChart, theme: dict[str, str] | None = None) -> str:
    """Render a BarChart to an SVG string."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])
    body_color = t.get("body", "#1a1a2e")
    muted = t.get("muted", "#5d6d7e")

    if not bc.labels or not bc.datasets:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    all_vals = [v for _, vals in bc.datasets for v in vals]
    max_val = max(all_vals) if all_vals else 1
    n_bars = len(bc.labels)
    n_datasets = len(bc.datasets)

    # Layout
    left_margin = 60
    right_margin = 30
    top_margin = 50
    bottom_margin = 60
    chart_w = max(n_bars * 60 * n_datasets, 200)
    chart_h = 200
    bar_gap = 8
    group_gap = 20

    width = left_margin + chart_w + right_margin
    height = top_margin + chart_h + bottom_margin

    group_w = (chart_w - group_gap * (n_bars - 1)) / n_bars
    bar_w = max((group_w - bar_gap * (n_datasets - 1)) / n_datasets, 12)

    parts: list[str] = []
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    # Title
    if bc.title:
        parts.append(
            f'<text x="{width / 2}" y="28" text-anchor="middle" '
            f'font-family="{font}" font-size="14" font-weight="700" '
            f'fill="{body_color}">{_escape(bc.title)}</text>'
        )

    # Y-axis grid lines and labels
    n_ticks = 5
    for i in range(n_ticks + 1):
        val = max_val * i / n_ticks
        y = top_margin + chart_h - (chart_h * i / n_ticks)
        parts.append(
            f'<line x1="{left_margin}" y1="{y}" x2="{left_margin + chart_w}" y2="{y}" '
            f'stroke="#e9ecef" stroke-width="0.8"/>'
        )
        parts.append(
            f'<text x="{left_margin - 8}" y="{y + 4}" text-anchor="end" '
            f'font-family="{font}" font-size="9" fill="{muted}">'
            f"{val:.0f}</text>"
        )

    # Bars
    for gi, label in enumerate(bc.labels):
        group_x = left_margin + gi * (group_w + group_gap)
        for di, (ds_name, vals) in enumerate(bc.datasets):
            if gi >= len(vals):
                continue
            val = vals[gi]
            color = _PIE_COLORS[di % len(_PIE_COLORS)]
            bh = (val / max_val) * chart_h if max_val > 0 else 0
            bx = group_x + di * (bar_w + bar_gap)
            by = top_margin + chart_h - bh
            parts.append(
                f'<rect x="{bx}" y="{by}" width="{bar_w}" height="{bh}" ' f'rx="2" fill="{color}"/>'
            )
            # Value label on top
            parts.append(
                f'<text x="{bx + bar_w / 2}" y="{by - 4}" text-anchor="middle" '
                f'font-family="{font}" font-size="8" fill="{muted}">'
                f"{val:.0f}</text>"
            )

        # X-axis label
        label_x = group_x + group_w / 2
        parts.append(
            f'<text x="{label_x}" y="{top_margin + chart_h + 16}" text-anchor="middle" '
            f'font-family="{font}" font-size="9" fill="{body_color}">'
            f"{_escape(label)}</text>"
        )

    # Axis lines
    parts.append(
        f'<line x1="{left_margin}" y1="{top_margin}" x2="{left_margin}" y2="{top_margin + chart_h}" '
        f'stroke="{muted}" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{left_margin}" y1="{top_margin + chart_h}" x2="{left_margin + chart_w}" y2="{top_margin + chart_h}" '
        f'stroke="{muted}" stroke-width="1"/>'
    )

    # Legend (if multiple datasets)
    if n_datasets > 1:
        for di, (ds_name, _) in enumerate(bc.datasets):
            lx = left_margin + di * 100
            ly = height - 20
            color = _PIE_COLORS[di % len(_PIE_COLORS)]
            parts.append(f'<rect x="{lx}" y="{ly}" width="10" height="10" rx="2" fill="{color}"/>')
            parts.append(
                f'<text x="{lx + 14}" y="{ly + 9}" '
                f'font-family="{font}" font-size="9" fill="{body_color}">'
                f"{_escape(ds_name)}</text>"
            )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


# ---------------------------------------------------------------------------
# SVG renderer — donut chart (pie variant)
# ---------------------------------------------------------------------------


def render_donut_svg(pc: PieChart, theme: dict[str, str] | None = None) -> str:
    """Render a PieChart as a donut (ring) chart."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])
    body_color = t.get("body", "#1a1a2e")

    if not pc.slices:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    total = sum(v for _, v in pc.slices)
    if total <= 0:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    cx, cy, r_outer, r_inner = 160, 140, 110, 60
    legend_x = cx + r_outer + 40
    width = legend_x + 180
    height = max(cy + r_outer + 40, len(pc.slices) * 22 + 80)

    parts: list[str] = []
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    if pc.title:
        parts.append(
            f'<text x="{width / 2}" y="28" text-anchor="middle" '
            f'font-family="{font}" font-size="14" font-weight="700" '
            f'fill="{body_color}">{_escape(pc.title)}</text>'
        )

    angle = -math.pi / 2
    for i, (label, value) in enumerate(pc.slices):
        fraction = value / total
        sweep = fraction * 2 * math.pi
        color = _PIE_COLORS[i % len(_PIE_COLORS)]

        # Outer arc
        ox1 = cx + r_outer * math.cos(angle)
        oy1 = cy + r_outer * math.sin(angle)
        ox2 = cx + r_outer * math.cos(angle + sweep)
        oy2 = cy + r_outer * math.sin(angle + sweep)
        # Inner arc (reverse direction)
        ix1 = cx + r_inner * math.cos(angle + sweep)
        iy1 = cy + r_inner * math.sin(angle + sweep)
        ix2 = cx + r_inner * math.cos(angle)
        iy2 = cy + r_inner * math.sin(angle)

        large_arc = 1 if sweep > math.pi else 0

        if sweep >= 2 * math.pi - 1e-9:
            # A single full-circle slice: draw the ring as an outer disc with a
            # punched-out white inner disc (a single annular arc draws nothing).
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="{color}" '
                f'stroke="#ffffff" stroke-width="2"/>'
            )
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r_inner}" fill="#ffffff"/>')
        else:
            path = (
                f"M {ox1:.1f},{oy1:.1f} "
                f"A {r_outer},{r_outer} 0 {large_arc} 1 {ox2:.1f},{oy2:.1f} "
                f"L {ix1:.1f},{iy1:.1f} "
                f"A {r_inner},{r_inner} 0 {large_arc} 0 {ix2:.1f},{iy2:.1f} Z"
            )
            parts.append(f'<path d="{path}" fill="{color}" stroke="#ffffff" stroke-width="2"/>')

        # Label on ring
        if fraction > 0.06:
            mid_angle = angle + sweep / 2
            label_r = (r_outer + r_inner) / 2
            lx = cx + label_r * math.cos(mid_angle)
            ly = cy + label_r * math.sin(mid_angle)
            pct = f"{fraction * 100:.0f}%"
            parts.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" '
                f'font-family="{font}" font-size="10" font-weight="700" '
                f'fill="#ffffff">{pct}</text>'
            )
        angle += sweep

    # Center label (total)
    parts.append(
        f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" '
        f'font-family="{font}" font-size="10" fill="{t.get("muted", "#5d6d7e")}">'
        f"Total</text>"
    )
    parts.append(
        f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" '
        f'font-family="{font}" font-size="16" font-weight="700" '
        f'fill="{body_color}">{total:.0f}</text>'
    )

    # Legend
    ly_start = 60
    for i, (label, value) in enumerate(pc.slices):
        color = _PIE_COLORS[i % len(_PIE_COLORS)]
        ly = ly_start + i * 22
        parts.append(
            f'<rect x="{legend_x}" y="{ly}" width="12" height="12" rx="2" fill="{color}"/>'
        )
        pct = f"{value / total * 100:.1f}%"
        parts.append(
            f'<text x="{legend_x + 18}" y="{ly + 10}" '
            f'font-family="{font}" font-size="10" fill="{body_color}">'
            f"{_escape(label)} ({pct})</text>"
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


# ---------------------------------------------------------------------------
# SVG renderer — gauge chart
# ---------------------------------------------------------------------------


def render_gauge_svg(gc: GaugeChart, theme: dict[str, str] | None = None) -> str:
    """Render a GaugeChart as a semicircular gauge."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])
    body_color = t.get("body", "#1a1a2e")
    muted = t.get("muted", "#5d6d7e")

    stroke_w = 22
    half_stroke = stroke_w / 2
    r = 100  # arc radius
    pad_top = 15  # breathing room above title
    title_h = 25 if gc.title else 0
    arc_gap = 15  # gap between title baseline and arc top
    pad_x = 30  # horizontal padding beyond arc endpoints
    pad_bottom = 30  # space below arc for min/max labels

    # Centre of the arc — everything aligns to this
    cx = r + pad_x + half_stroke
    cy = pad_top + title_h + arc_gap + r + half_stroke
    width = cx * 2
    height = cy + pad_bottom

    # Arc endpoints (horizontal baseline of the semicircle)
    sx = cx - r
    ex = cx + r

    parts: list[str] = []

    # Background arc (light grey track) — semicircle from left to right
    parts.append(
        f'<path d="M {sx},{cy} A {r},{r} 0 1 1 {ex},{cy}" '
        f'stroke="#e9ecef" stroke-width="{stroke_w}" fill="none" '
        f'stroke-linecap="butt"/>'
    )

    # Value fraction
    range_val = gc.max_val - gc.min_val
    fraction = (gc.value - gc.min_val) / range_val if range_val > 0 else 0
    fraction = max(0.0, min(1.0, fraction))

    # Value arc — sweep from left to proportional position along upper semicircle
    color = t.get("accent", t.get("primary", "#2563eb"))
    if fraction > 0.005:
        angle = math.pi - fraction * math.pi  # pi (left) → 0 (right)
        vx = cx + r * math.cos(angle)
        vy = cy - r * math.sin(angle)  # minus because SVG y-axis is inverted
        # Value arc is always ≤ 180° (within one semicircle), so always short arc
        parts.append(
            f'<path d="M {sx},{cy} A {r},{r} 0 0 1 {vx:.1f},{vy:.1f}" '
            f'stroke="{color}" stroke-width="{stroke_w}" fill="none" '
            f'stroke-linecap="butt"/>'
        )

    # Title — drawn AFTER arcs so text renders on top (SVG z-order)
    if gc.title:
        title_y = pad_top + title_h  # baseline of title text
        parts.append(
            f'<text x="{cx}" y="{title_y}" text-anchor="middle" '
            f'font-family="{font}" font-size="16" font-weight="700" '
            f'fill="{body_color}">{_escape(gc.title)}</text>'
        )

    # Value text — centred in the arc bowl
    parts.append(
        f'<text x="{cx}" y="{cy - 12}" text-anchor="middle" '
        f'font-family="{font}" font-size="36" font-weight="700" '
        f'fill="{body_color}">{gc.value:.0f}</text>'
    )

    # Subtitle — just below the value
    label_text = gc.label or f"of {gc.max_val:.0f}"
    parts.append(
        f'<text x="{cx}" y="{cy + 12}" text-anchor="middle" '
        f'font-family="{font}" font-size="12" fill="{muted}">'
        f"{_escape(label_text)}</text>"
    )

    # Min / max labels — directly below arc endpoints, tight
    label_y = cy + 22
    parts.append(
        f'<text x="{sx}" y="{label_y}" text-anchor="middle" '
        f'font-family="{font}" font-size="11" fill="{muted}">'
        f"{gc.min_val:.0f}</text>"
    )
    parts.append(
        f'<text x="{ex}" y="{label_y}" text-anchor="middle" '
        f'font-family="{font}" font-size="11" fill="{muted}">'
        f"{gc.max_val:.0f}</text>"
    )

    svg_inner = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    # Constrain gauge to a reasonable size — it's a compact widget, not a full-width chart
    return f'<div style="max-width:280px;margin:0 auto;">{svg_inner}</div>'


# ---------------------------------------------------------------------------
# SVG renderer — timeline
# ---------------------------------------------------------------------------


def render_timeline_svg(tl: Timeline, theme: dict[str, str] | None = None) -> str:
    """Render a Timeline to an SVG string."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])
    body_color = t.get("body", "#1a1a2e")
    accent = t.get("accent", "#2e86c1")

    if not tl.entries:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    # Layout
    left_margin = 30
    top_margin = 50
    row_height = 60
    period_w = 100
    event_w = 180

    n_entries = len(tl.entries)
    max_events = max(len(e.events) for e in tl.entries)

    width = left_margin + period_w + event_w * max(max_events, 1) + 40
    height = top_margin + n_entries * row_height + 20

    parts: list[str] = []
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    if tl.title:
        parts.append(
            f'<text x="{width / 2}" y="28" text-anchor="middle" '
            f'font-family="{font}" font-size="14" font-weight="700" '
            f'fill="{body_color}">{_escape(tl.title)}</text>'
        )

    # Vertical timeline line
    line_x = left_margin + period_w
    parts.append(
        f'<line x1="{line_x}" y1="{top_margin}" '
        f'x2="{line_x}" y2="{top_margin + n_entries * row_height - 20}" '
        f'stroke="{accent}" stroke-width="2"/>'
    )

    for i, entry in enumerate(tl.entries):
        y = top_margin + i * row_height + row_height / 2

        # Period label (left of line)
        parts.append(
            f'<text x="{line_x - 14}" y="{y + 4}" text-anchor="end" '
            f'font-family="{font}" font-size="11" font-weight="700" '
            f'fill="{body_color}">{_escape(entry.period)}</text>'
        )

        # Dot on timeline
        parts.append(
            f'<circle cx="{line_x}" cy="{y}" r="5" '
            f'fill="{accent}" stroke="#ffffff" stroke-width="2"/>'
        )

        # Events (right of line)
        for j, event in enumerate(entry.events):
            ex = line_x + 18 + j * event_w
            color = _PIE_COLORS[(i + j) % len(_PIE_COLORS)]
            ew = max(len(event) * 6.5 + 16, 60)
            parts.append(
                f'<rect x="{ex}" y="{y - 14}" width="{ew}" height="28" '
                f'rx="6" fill="{_lighten(color, 0.85)}" stroke="{color}" stroke-width="1"/>'
            )
            parts.append(
                f'<text x="{ex + ew / 2}" y="{y + 4}" text-anchor="middle" '
                f'font-family="{font}" font-size="9" fill="{body_color}">'
                f"{_escape(event)}</text>"
            )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


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
    """Render a GanttChart to an SVG string."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])
    body_color = t.get("body", "#1a1a2e")

    if not gc.tasks:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    # Layout
    left_margin = 30
    label_w = 140
    top_margin = 62
    row_h = 28
    bar_h = 18
    chart_w = 400

    # Group tasks by section
    sections: list[tuple[str, list[GanttTask]]] = []
    current_sec = ""
    current_tasks: list[GanttTask] = []
    for task in gc.tasks:
        if task.section != current_sec:
            if current_tasks:
                sections.append((current_sec, current_tasks))
            current_sec = task.section
            current_tasks = []
        current_tasks.append(task)
    if current_tasks:
        sections.append((current_sec, current_tasks))

    total_rows = sum(len(tasks) + (1 if sec else 0) for sec, tasks in sections)
    height = top_margin + total_rows * row_h + 30
    width = left_margin + label_w + chart_w + 40

    origin, timeline = _resolve_gantt(gc)
    min_day = min(a for a, _ in timeline)
    max_day = max(b for _, b in timeline)
    px_per_day = chart_w / max(max_day - min_day, 1.0)

    parts: list[str] = []
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    if gc.title:
        parts.append(
            f'<text x="{width / 2}" y="28" text-anchor="middle" '
            f'font-family="{font}" font-size="14" font-weight="700" '
            f'fill="{body_color}">{_escape(gc.title)}</text>'
        )

    # Date axis with gridlines
    span = max_day - min_day
    ticks = 5
    label_fmt = "%b %Y" if span > 150 else "%d %b"
    for i in range(ticks + 1):
        day = min_day + span * i / ticks
        gx = left_margin + label_w + (day - min_day) * px_per_day
        parts.append(
            f'<line x1="{gx:.1f}" y1="{top_margin - 6}" x2="{gx:.1f}" '
            f'y2="{top_margin + total_rows * row_h}" stroke="#d5dbe1" stroke-width="0.6"/>'
        )
        anchor = "start" if i == 0 else ("end" if i == ticks else "middle")
        parts.append(
            f'<text x="{gx:.1f}" y="{top_margin - 10}" text-anchor="{anchor}" '
            f'font-family="{font}" font-size="8" fill="#5d6d7e">'
            f"{(origin + timedelta(days=round(day))).strftime(label_fmt)}</text>"
        )

    # Draw tasks
    y_cursor = top_margin
    task_idx = 0
    for sec_name, tasks in sections:
        if sec_name:
            # Section header
            parts.append(
                f'<rect x="{left_margin}" y="{y_cursor}" '
                f'width="{label_w + chart_w}" height="{row_h}" '
                f'fill="{_lighten(t.get("primary", "#1b4f72"), 0.9)}"/>'
            )
            parts.append(
                f'<text x="{left_margin + 8}" y="{y_cursor + row_h / 2 + 4}" '
                f'font-family="{font}" font-size="10" font-weight="700" '
                f'fill="{body_color}">{_escape(sec_name)}</text>'
            )
            y_cursor += row_h

        for i, task in enumerate(tasks):
            y = y_cursor
            color = _PIE_COLORS[task_idx % len(_PIE_COLORS)]

            # Alternating row background
            if task_idx % 2 == 0:
                parts.append(
                    f'<rect x="{left_margin}" y="{y}" width="{label_w + chart_w}" '
                    f'height="{row_h}" fill="#000000" fill-opacity="0.025"/>'
                )

            # Task label
            parts.append(
                f'<text x="{left_margin + 8}" y="{y + row_h / 2 + 4}" '
                f'font-family="{font}" font-size="9" fill="{body_color}">'
                f"{_escape(task.name)}</text>"
            )

            t_start, t_end = timeline[task_idx]
            bar_x = left_margin + label_w + (t_start - min_day) * px_per_day
            bar_w = max(4.0, (t_end - t_start) * px_per_day)
            bar_y = y + (row_h - bar_h) / 2

            parts.append(
                f'<rect x="{bar_x:.1f}" y="{bar_y}" width="{bar_w:.1f}" height="{bar_h}" '
                f'rx="4" fill="{color}"/>'
            )
            bar_label = task.duration if _gantt_days(task.duration) else f"{t_end - t_start:g}d"
            if bar_w >= len(bar_label) * 5 + 8:
                parts.append(
                    f'<text x="{bar_x + bar_w / 2:.1f}" y="{bar_y + bar_h / 2 + 3}" '
                    f'text-anchor="middle" '
                    f'font-family="{font}" font-size="8" font-weight="600" '
                    f'fill="#ffffff">{_escape(bar_label)}</text>'
                )

            y_cursor += row_h
            task_idx += 1

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


# ---------------------------------------------------------------------------
# SVG renderer — mind map
# ---------------------------------------------------------------------------


def _layout_mindmap(
    node: MindNode, x: float, y: float, level: int = 0, y_offset: list[float] | None = None
) -> float:
    """Recursively position mindmap nodes. Returns total height used."""
    if y_offset is None:
        y_offset = [y]

    node.x = x
    node.y = y_offset[0]

    h_spacing = 140
    v_spacing = 20
    node_h = 28

    if not node.children:
        y_offset[0] += node_h + v_spacing
        return node_h + v_spacing

    total_h: float = 0
    child_start_y = y_offset[0]
    y_offset[0] = child_start_y

    for child in node.children:
        ch = _layout_mindmap(child, x + h_spacing, 0, level + 1, y_offset)
        total_h += ch

    # Center this node vertically among its children
    if node.children:
        first_child_y = node.children[0].y
        last_child_y = node.children[-1].y
        node.y = (first_child_y + last_child_y) / 2

    return max(total_h, node_h + v_spacing)


def render_mindmap_svg(root: MindNode, theme: dict[str, str] | None = None) -> str:
    """Render a mind map from a root MindNode."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])
    body_color = t.get("body", "#1a1a2e")
    muted = t.get("muted", "#5d6d7e")

    # Layout
    _layout_mindmap(root, 40, 40)

    # Collect all nodes for bounds
    all_nodes: list[MindNode] = []

    def _collect(n: MindNode) -> None:
        all_nodes.append(n)
        for c in n.children:
            _collect(c)

    _collect(root)

    if not all_nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    # Calculate sizes
    def _node_w(n: MindNode) -> float:
        return max(len(n.label) * 7 + 24, 60)

    max_x = max(n.x + _node_w(n) for n in all_nodes) + 30
    max_y = max(n.y + 30 for n in all_nodes) + 30
    width = max(max_x, 200)
    height = max(max_y, 100)

    parts: list[str] = []
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    # Draw edges first
    def _draw_edges(node: MindNode, depth: int = 0) -> None:
        nw = _node_w(node)
        for child in node.children:
            x1 = node.x + nw
            y1 = node.y + 15
            x2 = child.x
            y2 = child.y + 15
            mid_x = (x1 + x2) / 2
            parts.append(
                f'<path d="M {x1},{y1} C {mid_x},{y1} {mid_x},{y2} {x2},{y2}" '
                f'stroke="{muted}" stroke-width="1.5" fill="none"/>'
            )
            _draw_edges(child, depth + 1)

    _draw_edges(root)

    # Draw nodes
    def _draw_nodes(node: MindNode, depth: int = 0) -> None:
        nw = _node_w(node)
        nh = 30
        color = _PIE_COLORS[depth % len(_PIE_COLORS)] if depth > 0 else t.get("primary", "#1b4f72")
        fill = _lighten(color, 0.85) if depth > 0 else color
        text_color = body_color if depth > 0 else "#ffffff"
        rx = "15" if depth == 0 else "8"

        parts.append(
            f'<rect x="{node.x}" y="{node.y}" width="{nw}" height="{nh}" '
            f'rx="{rx}" fill="{fill}" stroke="{color}" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{node.x + nw / 2}" y="{node.y + nh / 2 + 4}" '
            f'text-anchor="middle" '
            f'font-family="{font}" font-size="10" font-weight="{700 if depth == 0 else 500}" '
            f'fill="{text_color}">{_escape(node.label)}</text>'
        )
        for child in node.children:
            _draw_nodes(child, depth + 1)

    _draw_nodes(root)

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


# ---------------------------------------------------------------------------
# SVG renderer — ER diagram
# ---------------------------------------------------------------------------


def render_er_svg(erd: ERDiagram, theme: dict[str, str] | None = None) -> str:
    """Render an ER diagram to SVG."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])
    body_color = t.get("body", "#1a1a2e")
    muted = t.get("muted", "#5d6d7e")
    primary = t.get("primary", "#1b4f72")
    accent = t.get("accent", "#2e86c1")

    entities = list(erd.entities.values())
    if not entities:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    # Layout entities in a grid
    padding = 30
    entity_w = 160
    entity_gap_x = 80
    entity_gap_y = 60
    cols = min(len(entities), 3)
    rows = math.ceil(len(entities) / cols)

    # Calculate entity heights based on attributes. Use a uniform row height
    # (the tallest entity) so entities in the same row align and the canvas is
    # tall enough for entities with many attributes.
    header_h = 28
    ent_heights: list[float] = [
        header_h + max(len(ent.attributes) * 18, 18) + 8 for ent in entities
    ]
    row_h = max([80.0, *ent_heights])

    entity_positions: dict[str, tuple[float, float, float, float]] = {}
    for i, ent in enumerate(entities):
        col = i % cols
        row = i // cols
        x: float = padding + col * (entity_w + entity_gap_x)
        y: float = padding + row * (row_h + entity_gap_y)
        entity_positions[ent.name] = (x, y, entity_w, ent_heights[i])

    width = padding * 2 + cols * (entity_w + entity_gap_x) - entity_gap_x
    height = padding * 2 + rows * row_h + max(rows - 1, 0) * entity_gap_y

    parts: list[str] = []
    parts.append(_make_arrow_defs(t, "er-"))
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    # Draw relationships (behind entities)
    for rel in erd.relations:
        pos_a = entity_positions.get(rel.entity_a)
        pos_b = entity_positions.get(rel.entity_b)
        if not pos_a or not pos_b:
            continue
        ax, ay, aw, ah = pos_a
        bx, by, bw, bh = pos_b
        # Connect from right side of A to left side of B
        x1 = ax + aw
        y1 = ay + ah / 2
        x2 = bx
        y2 = by + bh / 2

        stroke_style = 'stroke-dasharray="5 3"' if rel.style == "dotted" else ""
        mid_x = (x1 + x2) / 2
        parts.append(
            f'<path d="M {x1},{y1} L {mid_x},{y1} L {mid_x},{y2} L {x2},{y2}" '
            f'stroke="{muted}" stroke-width="1.5" fill="none" {stroke_style}/>'
        )

        # Cardinality markers
        if rel.card_a:
            parts.append(
                f'<text x="{x1 + 6}" y="{y1 - 6}" '
                f'font-family="{font}" font-size="9" fill="{accent}">'
                f"{_escape(rel.card_a)}</text>"
            )
        if rel.card_b:
            parts.append(
                f'<text x="{x2 - 6}" y="{y2 - 6}" text-anchor="end" '
                f'font-family="{font}" font-size="9" fill="{accent}">'
                f"{_escape(rel.card_b)}</text>"
            )

        # Relationship label
        if rel.label:
            lx = (x1 + x2) / 2
            ly = (y1 + y2) / 2 - 8
            parts.append(
                f'<text x="{lx}" y="{ly}" text-anchor="middle" '
                f'font-family="{font}" font-size="9" font-style="italic" '
                f'fill="{muted}">{_escape(rel.label)}</text>'
            )

    # Draw entities
    for ent in entities:
        pos = entity_positions[ent.name]
        x, y, w, h = pos

        # Entity box
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'rx="4" fill="#ffffff" stroke="{primary}" stroke-width="1.5"/>'
        )

        # Header bar
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="28" ' f'rx="4" fill="{primary}"/>')
        # Fix bottom corners of header
        parts.append(f'<rect x="{x}" y="{y + 14}" width="{w}" height="14" fill="{primary}"/>')

        parts.append(
            f'<text x="{x + w / 2}" y="{y + 18}" text-anchor="middle" '
            f'font-family="{font}" font-size="11" font-weight="700" '
            f'fill="#ffffff">{_escape(ent.name)}</text>'
        )

        # Attributes
        for j, attr in enumerate(ent.attributes):
            ay = y + 28 + j * 18 + 14
            parts.append(
                f'<text x="{x + 10}" y="{ay}" '
                f'font-family="{font}" font-size="9" fill="{body_color}">'
                f"{_escape(attr)}</text>"
            )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


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
        return f'<div class="mermaid-diagram" style="text-align:center;margin:8pt 0 12pt 0;">{svg}</div>'

    return _MERMAID_BLOCK_RE.sub(_replace, html)
