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
    style A fill:#abc,stroke:#def inline style (parsed but uses theme)
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


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


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    style: str = "solid"  # solid | dotted | thick | none (no arrow)


@dataclass
class Subgraph:
    id: str
    label: str
    node_ids: list[str] = field(default_factory=list)
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
    "stadium_fill": "#eaf5ea",
    "stadium_stroke": "#27ae60",
    "rounded_fill": "#e8f0fe",
    "rounded_stroke": "#2e86c1",
    "circle_fill": "#fce4ec",
    "circle_stroke": "#c62828",
    "cylinder_fill": "#e0f2f1",
    "cylinder_stroke": "#00796b",
    "hexagon_fill": "#fff3e0",
    "hexagon_stroke": "#e65100",
    "subroutine_fill": "#f3e5f5",
    "subroutine_stroke": "#7b1fa2",
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
        theme["rounded_fill"] = _lighten(primary, 0.88)
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
]

# Edge patterns — order: longest operators first
# Matches: ==> | -.-> | --> | --- and optional pipe labels or quoted labels
_EDGE_OPERATORS = [
    # Thick arrow ==>
    (re.compile(r"==>\s*"), "thick", True),
    # Dotted arrow -.->
    (re.compile(r"-\.->\s*"), "dotted", True),
    # Solid arrow with pipe label -->|"label"|  or  -->|label|
    (re.compile(r'-->\|"([^"]+)"\|\s*'), "solid", True),
    (re.compile(r"-->\|([^|]+)\|\s*"), "solid", True),
    # Thick with label  ==>|"label"|
    (re.compile(r'==>\|"([^"]+)"\|\s*'), "thick", True),
    (re.compile(r"==>\|([^|]+)\|\s*"), "thick", True),
    # Dotted with label  -.->|"label"|
    (re.compile(r'-\.->\|"([^"]+)"\|\s*'), "dotted", True),
    (re.compile(r"-\.->\|([^|]+)\|\s*"), "dotted", True),
    # Labelled arrow -- "label" -->
    (re.compile(r'--\s*"([^"]*)"\s*-->\s*'), "solid", True),
    # Labelled arrow -- label -->  (unquoted single-word)
    (re.compile(r'--\s*([^\s"]+)\s*-->\s*'), "solid", True),
    # Labelled thick == "label" ==>
    (re.compile(r'==\s*"([^"]*)"\s*==>\s*'), "thick", True),
    # Labelled dotted -. "label" .->
    (re.compile(r'-\.\s*"([^"]*)"\s*\.->\s*'), "dotted", True),
    # Plain solid arrow -->
    (re.compile(r"-->\s*"), "solid", True),
    # No-arrow line ---
    (re.compile(r"---\s*"), "none", False),
]


def _ensure_node(fc: Flowchart, token: str) -> str:
    """Parse a node token, register it if new, return the node ID."""
    token = token.strip()
    if not token:
        return ""

    for pattern, shape in _NODE_PATTERNS:
        m = pattern.match(token)
        if m:
            nid, label = m.group(1), m.group(2)
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


def parse(source: str) -> Flowchart:
    """Parse Mermaid flowchart source into a Flowchart model."""
    fc = Flowchart()
    lines = source.strip().splitlines()
    subgraph_stack: list[Subgraph] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue

        # Direction line
        dir_m = re.match(r"^(?:flowchart|graph)\s+(LR|TD|TB|RL|BT)\s*$", line, re.IGNORECASE)
        if dir_m:
            fc.direction = dir_m.group(1).upper()
            continue

        # Skip style/classDef/class lines (we use our own theme)
        if line.startswith("style ") or line.startswith("classDef ") or line.startswith("class "):
            continue

        # Skip linkStyle lines
        if line.startswith("linkStyle "):
            continue

        # Skip direction inside subgraph
        if re.match(r"^direction\s+(LR|TD|TB|RL|BT)\s*$", line, re.IGNORECASE):
            continue

        # Subgraph open
        sg_m = re.match(r'^subgraph\s+(\w+)\["([^"]+)"\]\s*$', line)
        if not sg_m:
            sg_m = re.match(r"^subgraph\s+(\w+)\[([^\]]+)\]\s*$", line)
        if not sg_m:
            sg_m = re.match(r"^subgraph\s+(\S+)\s*$", line)
        if sg_m:
            sg_id = sg_m.group(1)
            sg_label = sg_m.group(2) if (sg_m.lastindex or 0) >= 2 else sg_id
            sg = Subgraph(id=sg_id, label=sg_label)
            subgraph_stack.append(sg)
            continue

        # Subgraph close
        if line == "end":
            if subgraph_stack:
                sg = subgraph_stack.pop()
                fc.subgraphs.append(sg)
            continue

        # Try to parse as edge chain
        has_edge = any(op_re.search(line) for op_re, _, _ in _EDGE_OPERATORS)
        if has_edge:
            _parse_edge_line(fc, line)
            # Track nodes in current subgraph
            if subgraph_stack:
                for nid in fc.nodes:
                    if nid not in subgraph_stack[-1].node_ids:
                        # Only add nodes first seen in this line
                        pass
            continue

        # Standalone node definition
        matched = False
        for pattern, shape in _NODE_PATTERNS:
            m = pattern.match(line)
            if m:
                nid, label = m.group(1), m.group(2)
                fc.nodes[nid] = Node(id=nid, label=label, shape=shape)
                if subgraph_stack:
                    subgraph_stack[-1].node_ids.append(nid)
                matched = True
                break
        if not matched and re.match(r"^[A-Za-z_]\w*$", line):
            # Plain node ID
            if line not in fc.nodes:
                fc.nodes[line] = Node(id=line, label=line, shape="rect")
            if subgraph_stack:
                subgraph_stack[-1].node_ids.append(line)

    # Assign nodes to subgraphs based on edges
    _assign_subgraph_nodes(fc)

    return fc


def _assign_subgraph_nodes(fc: Flowchart) -> None:
    """Ensure subgraph node_ids are populated from edges parsed within them."""
    # Collect all nodes already assigned to subgraphs
    assigned: set[str] = set()
    for sg in fc.subgraphs:
        assigned.update(sg.node_ids)

    # For subgraphs with no nodes, try to infer from edges
    # (This is a simplistic approach — in a real parser, we'd track
    # which lines were inside which subgraph block)


def _parse_edge_line(fc: Flowchart, line: str) -> None:
    """Parse a line containing one or more chained edges."""
    parts: list[str] = []
    labels: list[str] = []
    styles: list[str] = []
    has_arrows: list[bool] = []

    remaining = line
    while True:
        best_match = None
        best_start = len(remaining)
        best_op = None

        for op_re, style, has_arrow in _EDGE_OPERATORS:
            m = op_re.search(remaining)
            if m and m.start() < best_start:
                best_match = m
                best_start = m.start()
                best_op = (op_re, style, has_arrow)

        if best_match is None or best_op is None:
            parts.append(remaining.strip())
            break

        parts.append(remaining[: best_match.start()].strip())
        _, style, has_arrow = best_op

        # Extract label from capture groups
        label = ""
        for i in range(1, best_match.lastindex + 1 if best_match.lastindex else 1):
            try:
                g = best_match.group(i)
                if g:
                    label = g
                    break
            except IndexError:
                break

        labels.append(label)
        styles.append(style)
        has_arrows.append(has_arrow)
        remaining = remaining[best_match.end() :]

    # Register nodes and create edges
    node_ids: list[str] = []
    for part in parts:
        if part:
            nid = _ensure_node(fc, part)
            if nid:
                node_ids.append(nid)

    for i in range(len(node_ids) - 1):
        label = labels[i] if i < len(labels) else ""
        style = styles[i] if i < len(styles) else "solid"
        fc.edges.append(Edge(src=node_ids[i], dst=node_ids[i + 1], label=label, style=style))


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

_SEQ_MSG_RE = re.compile(r"^(\S+)\s*(-->>|--?>|--?>?>|->>|->)\s*(\S+)\s*:\s*(.*)$")

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
    for raw_line in source.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r"^erDiagram\b", line, re.IGNORECASE):
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

        # Entity with attributes block (simplified — we just register the name)
        ent_m = re.match(r"^(\S+)\s*\{", line)
        if ent_m:
            name = ent_m.group(1)
            if name not in erd.entities:
                erd.entities[name] = EREntity(name=name)
            continue

        # Attribute line inside entity block
        attr_m = re.match(r"^\s+(\w+)\s+(\w+)", line)
        if attr_m and erd.entities:
            # Add to last entity
            last_entity = list(erd.entities.values())[-1]
            last_entity.attributes.append(f"{attr_m.group(1)} {attr_m.group(2)}")

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
    """Assign each node a level (column for LR, row for TD) via BFS."""
    children: dict[str, list[str]] = defaultdict(list)
    has_parent: set[str] = set()
    for e in fc.edges:
        children[e.src].append(e.dst)
        has_parent.add(e.dst)

    roots = [nid for nid in fc.nodes if nid not in has_parent]
    if not roots:
        roots = [next(iter(fc.nodes))] if fc.nodes else []

    levels: dict[str, int] = {}
    queue = [(r, 0) for r in roots]
    while queue:
        nid, lvl = queue.pop(0)
        if nid in levels:
            levels[nid] = max(levels[nid], lvl)
            continue
        levels[nid] = lvl
        for child in children.get(nid, []):
            queue.append((child, lvl + 1))

    for nid in fc.nodes:
        if nid not in levels:
            levels[nid] = 0

    return levels


def layout(fc: Flowchart, theme: dict[str, str] | None = None) -> None:
    """Position all nodes in the flowchart."""
    if not fc.nodes:
        return

    font_size = 12

    # Compute text-based node sizes
    for node in fc.nodes.values():
        lines = node.label.split("\n") if "\n" in node.label else node.label.split("<br>")
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
        elif node.shape == "cylinder":
            node.h = max(node.h + 16, 56)

    # Assign levels
    levels = _compute_levels(fc)

    # Group nodes by level
    level_groups: dict[int, list[str]] = defaultdict(list)
    for nid, lvl in levels.items():
        level_groups[lvl].append(nid)

    # Build parent->children map for centering
    children_map: dict[str, list[str]] = defaultdict(list)
    for e in fc.edges:
        if e.dst not in children_map[e.src]:
            children_map[e.src].append(e.dst)

    is_horizontal = fc.direction in ("LR", "RL")
    gap_major = 60
    gap_minor = 30
    padding = 30

    if is_horizontal:
        # Normalize widths in each column
        for lvl, nids in level_groups.items():
            rect_nodes = [
                fc.nodes[n] for n in nids if fc.nodes[n].shape in ("rect", "rounded", "subroutine")
            ]
            if len(rect_nodes) > 1:
                max_w = max(n.w for n in rect_nodes)
                for n in rect_nodes:
                    n.w = max_w

        col_x: dict[int, float] = {}
        x_cursor: float = padding
        for lvl in sorted(level_groups.keys()):
            col_x[lvl] = x_cursor
            max_w = max(fc.nodes[n].w for n in level_groups[lvl])
            x_cursor += max_w + gap_major

        col_total_h: dict[int, float] = {}
        for lvl, nids in level_groups.items():
            total = sum(fc.nodes[n].h for n in nids) + gap_minor * (len(nids) - 1)
            col_total_h[lvl] = total
        max_total_h = max(col_total_h.values())

        for lvl, nids in level_groups.items():
            col_h = col_total_h[lvl]
            y_start = padding + 10 + (max_total_h - col_h) / 2
            y_cursor = y_start
            for nid in nids:
                node = fc.nodes[nid]
                node.x = col_x[lvl]
                node.y = y_cursor
                y_cursor += node.h + gap_minor
    else:
        row_y: dict[int, float] = {}
        y_cursor = padding
        for lvl in sorted(level_groups.keys()):
            row_y[lvl] = y_cursor
            max_h = max(fc.nodes[n].h for n in level_groups[lvl])
            y_cursor += max_h + gap_major

        max_lvl = max(level_groups.keys()) if level_groups else 0

        for lvl in sorted(level_groups.keys(), reverse=True):
            nids = level_groups[lvl]
            if lvl == max_lvl or not any(children_map.get(n) for n in nids):
                x_cursor = float(padding)
                for nid in nids:
                    node = fc.nodes[nid]
                    node.x = x_cursor
                    node.y = row_y[lvl]
                    x_cursor += node.w + gap_minor
            else:
                for nid in nids:
                    node = fc.nodes[nid]
                    node.y = row_y[lvl]
                    kids = children_map.get(nid, [])
                    if kids:
                        kid_nodes = [fc.nodes[k] for k in kids if k in fc.nodes]
                        if kid_nodes:
                            kids_left = min(k.x for k in kid_nodes)
                            kids_right = max(k.x + k.w for k in kid_nodes)
                            kids_center = (kids_left + kids_right) / 2
                            node.x = kids_center - node.w / 2
                        else:
                            node.x = padding
                    else:
                        node.x = padding

    # Compute subgraph bounding boxes
    for sg in fc.subgraphs:
        if not sg.node_ids:
            continue
        sg_nodes = [fc.nodes[nid] for nid in sg.node_ids if nid in fc.nodes]
        if not sg_nodes:
            continue
        sg_pad = 12
        sg.x = min(n.x for n in sg_nodes) - sg_pad
        sg.y = min(n.y for n in sg_nodes) - sg_pad - 18  # extra for label
        sg.w = max(n.x + n.w for n in sg_nodes) - sg.x + sg_pad
        sg.h = max(n.y + n.h for n in sg_nodes) - sg.y + sg_pad


# ---------------------------------------------------------------------------
# SVG renderer — shared helpers
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    """Escape text for SVG/XML."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _make_arrow_defs(t: dict[str, str], prefix: str = "") -> str:
    """Generate SVG marker definitions for arrows."""
    muted = t.get("muted", "#5d6d7e")
    return f"""<defs>
  <marker id="{prefix}arr" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
    <polygon points="0 0, 8 3, 0 6" fill="{muted}"/>
  </marker>
  <marker id="{prefix}arr-thick" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
    <polygon points="0 0, 10 3.5, 0 7" fill="{muted}"/>
  </marker>
</defs>"""


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

    width = max(max_x, 200)
    height = max(max_y, 100)

    parts.append(_make_arrow_defs(t))
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    # Draw subgraphs (behind everything)
    for sg in fc.subgraphs:
        parts.append(_render_subgraph(sg, t))

    # Draw edges (behind nodes)
    for edge in fc.edges:
        src = fc.nodes.get(edge.src)
        dst = fc.nodes.get(edge.dst)
        if not src or not dst:
            continue
        parts.append(_render_edge(src, dst, edge.label, fc.direction, t, edge.style))

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
    """Render a subgraph background rectangle with label."""
    if sg.w <= 0 or sg.h <= 0:
        return ""
    font = t.get("font", DEFAULT_THEME["font"])
    fill = t.get("subgraph_fill", "#f8f9fa")
    stroke = t.get("subgraph_stroke", "#dee2e6")
    label_color = t.get("subgraph_label", "#495057")

    parts = [
        f'<rect x="{sg.x}" y="{sg.y}" width="{sg.w}" height="{sg.h}" '
        f'rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.2" stroke-dasharray="4 2"/>',
        f'<text x="{sg.x + 8}" y="{sg.y + 14}" '
        f'font-family="{font}" font-size="10" font-weight="700" '
        f'fill="{label_color}">{_escape(sg.label)}</text>',
    ]
    return "\n".join(parts)


def _render_node(node: Node, t: dict[str, str]) -> str:
    """Render a single node to SVG elements."""
    font = t.get("font", DEFAULT_THEME["font"])
    cx = node.x + node.w / 2
    cy = node.y + node.h / 2
    parts: list[str] = []

    if node.shape == "diamond":
        fill = t.get("diamond_fill", "#fef5e7")
        stroke = t.get("diamond_stroke", "#e67e22")
        points = f"{cx},{node.y} {node.x + node.w},{cy} {cx},{node.y + node.h} {node.x},{cy}"
        parts.append(
            f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )

    elif node.shape == "stadium":
        fill = t.get("stadium_fill", "#eaf5ea")
        stroke = t.get("stadium_stroke", "#27ae60")
        r = node.h / 2
        parts.append(
            f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" '
            f'rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )

    elif node.shape == "rounded":
        fill = t.get("rounded_fill", "#e8f0fe")
        stroke = t.get("rounded_stroke", "#2e86c1")
        parts.append(
            f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" '
            f'rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )

    elif node.shape == "circle":
        fill = t.get("circle_fill", "#fce4ec")
        stroke = t.get("circle_stroke", "#c62828")
        r = min(node.w, node.h) / 2
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )

    elif node.shape == "cylinder":
        fill = t.get("cylinder_fill", "#e0f2f1")
        stroke = t.get("cylinder_stroke", "#00796b")
        ry = 8  # ellipse cap height
        body_top = node.y + ry
        body_h = node.h - 2 * ry
        # Body rectangle
        parts.append(
            f'<rect x="{node.x}" y="{body_top}" width="{node.w}" height="{body_h}" '
            f'fill="{fill}" stroke="none"/>'
        )
        # Side lines
        parts.append(
            f'<line x1="{node.x}" y1="{body_top}" x2="{node.x}" y2="{body_top + body_h}" '
            f'stroke="{stroke}" stroke-width="1.8"/>'
        )
        parts.append(
            f'<line x1="{node.x + node.w}" y1="{body_top}" x2="{node.x + node.w}" y2="{body_top + body_h}" '
            f'stroke="{stroke}" stroke-width="1.8"/>'
        )
        # Top ellipse (filled)
        parts.append(
            f'<ellipse cx="{cx}" cy="{body_top}" rx="{node.w / 2}" ry="{ry}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )
        # Bottom ellipse (half visible)
        parts.append(
            f'<ellipse cx="{cx}" cy="{body_top + body_h}" rx="{node.w / 2}" ry="{ry}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )

    elif node.shape == "hexagon":
        fill = t.get("hexagon_fill", "#fff3e0")
        stroke = t.get("hexagon_stroke", "#e65100")
        inset = 12
        points = (
            f"{node.x + inset},{node.y} "
            f"{node.x + node.w - inset},{node.y} "
            f"{node.x + node.w},{cy} "
            f"{node.x + node.w - inset},{node.y + node.h} "
            f"{node.x + inset},{node.y + node.h} "
            f"{node.x},{cy}"
        )
        parts.append(
            f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )

    elif node.shape == "subroutine":
        fill = t.get("subroutine_fill", "#f3e5f5")
        stroke = t.get("subroutine_stroke", "#7b1fa2")
        parts.append(
            f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" '
            f'rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )
        # Double vertical lines inset
        inset = 8
        parts.append(
            f'<line x1="{node.x + inset}" y1="{node.y}" '
            f'x2="{node.x + inset}" y2="{node.y + node.h}" '
            f'stroke="{stroke}" stroke-width="1"/>'
        )
        parts.append(
            f'<line x1="{node.x + node.w - inset}" y1="{node.y}" '
            f'x2="{node.x + node.w - inset}" y2="{node.y + node.h}" '
            f'stroke="{stroke}" stroke-width="1"/>'
        )

    else:  # rect (default)
        fill = t.get("node_fill", "#d6eaf8")
        stroke = t.get("node_stroke", "#1b4f72")
        parts.append(
            f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" '
            f'rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )

    # Label (support multi-line via \n or <br>)
    label = node.label.replace("<br>", "\n")
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

    return "\n".join(parts)


def _render_edge(
    src: Node, dst: Node, label: str, direction: str, t: dict[str, str], style: str = "solid"
) -> str:
    """Render an edge between two nodes."""
    font = t.get("font", DEFAULT_THEME["font"])
    muted = t.get("muted", "#5d6d7e")
    parts: list[str] = []

    # Edge styling
    stroke_attrs = f'stroke="{muted}" stroke-width="1.5" fill="none"'
    marker = ' marker-end="url(#arr)"'

    if style == "dotted":
        stroke_attrs = f'stroke="{muted}" stroke-width="1.5" fill="none" stroke-dasharray="5 3"'
    elif style == "thick":
        stroke_attrs = f'stroke="{muted}" stroke-width="3" fill="none"'
        marker = ' marker-end="url(#arr-thick)"'
    elif style == "none":
        marker = ""  # no arrowhead

    is_h = direction in ("LR", "RL")

    if is_h:
        if src.x + src.w / 2 < dst.x + dst.w / 2:
            x1, y1 = src.x + src.w, src.y + src.h / 2
            x2, y2 = dst.x, dst.y + dst.h / 2
        else:
            x1, y1 = src.x, src.y + src.h / 2
            x2, y2 = dst.x + dst.w, dst.y + dst.h / 2

        if abs(y1 - y2) < 2:
            parts.append(f'<path d="M {x1},{y1} L {x2},{y2}" {stroke_attrs}{marker}/>')
        else:
            mid_x = (x1 + x2) / 2
            parts.append(
                f'<path d="M {x1},{y1} L {mid_x},{y1} L {mid_x},{y2} L {x2},{y2}" '
                f"{stroke_attrs}{marker}/>"
            )
    else:
        if src.y + src.h / 2 < dst.y + dst.h / 2:
            x1, y1 = src.x + src.w / 2, src.y + src.h
            x2, y2 = dst.x + dst.w / 2, dst.y
        else:
            x1, y1 = src.x + src.w / 2, src.y
            x2, y2 = dst.x + dst.w / 2, dst.y + dst.h

        if abs(x1 - x2) < 2:
            parts.append(f'<path d="M {x1},{y1} L {x2},{y2}" {stroke_attrs}{marker}/>')
        else:
            mid_y = (y1 + y2) / 2
            parts.append(
                f'<path d="M {x1},{y1} L {x1},{mid_y} L {x2},{mid_y} L {x2},{y2}" '
                f"{stroke_attrs}{marker}/>"
            )

    # Edge label
    if label:
        lx = (src.x + src.w / 2 + dst.x + dst.w / 2) / 2
        ly = (src.y + src.h / 2 + dst.y + dst.h / 2) / 2
        if is_h:
            ly -= 8
        else:
            lx += 10
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

        path = f"M {cx},{cy} L {x1:.1f},{y1:.1f} " f"A {r},{r} 0 {large_arc} 1 {x2:.1f},{y2:.1f} Z"
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
    top_margin = 50
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

    parts: list[str] = []
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    if gc.title:
        parts.append(
            f'<text x="{width / 2}" y="28" text-anchor="middle" '
            f'font-family="{font}" font-size="14" font-weight="700" '
            f'fill="{body_color}">{_escape(gc.title)}</text>'
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
                    f'height="{row_h}" fill="#f8f9fa"/>'
                )

            # Task label
            parts.append(
                f'<text x="{left_margin + 8}" y="{y + row_h / 2 + 4}" '
                f'font-family="{font}" font-size="9" fill="{body_color}">'
                f"{_escape(task.name)}</text>"
            )

            # Task bar (simplified — proportional positioning)
            bar_x: float = left_margin + label_w + task_idx * 30
            bar_w = max(60, chart_w / max(len(gc.tasks), 1) * 1.5)
            bar_x = min(bar_x, left_margin + label_w + chart_w - bar_w)
            bar_y = y + (row_h - bar_h) / 2

            parts.append(
                f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" '
                f'rx="4" fill="{color}"/>'
            )
            parts.append(
                f'<text x="{bar_x + bar_w / 2}" y="{bar_y + bar_h / 2 + 3}" '
                f'text-anchor="middle" '
                f'font-family="{font}" font-size="8" font-weight="600" '
                f'fill="#ffffff">{_escape(task.duration or task.start or "")}</text>'
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

    # Calculate entity heights based on attributes
    entity_positions: dict[str, tuple[float, float, float, float]] = {}
    for i, ent in enumerate(entities):
        col = i % cols
        row = i // cols
        x: float = padding + col * (entity_w + entity_gap_x)
        header_h = 28
        attr_h = len(ent.attributes) * 18
        ent_h = header_h + max(attr_h, 18) + 8
        y: float = padding + row * (max(80, ent_h) + entity_gap_y)
        entity_positions[ent.name] = (x, y, entity_w, ent_h)

    width = padding * 2 + cols * (entity_w + entity_gap_x) - entity_gap_x
    height = padding * 2 + rows * (120 + entity_gap_y)

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
    """Render a state diagram to SVG."""
    t = {**DEFAULT_THEME, **(theme or {})}
    font = t.get("font", DEFAULT_THEME["font"])
    body_color = t.get("body", "#1a1a2e")
    muted = t.get("muted", "#5d6d7e")
    primary = t.get("primary", "#1b4f72")
    accent = t.get("accent", "#2e86c1")

    if not sd.states:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    # Layout states in a flow
    padding = 30
    state_w = 120
    state_h = 40
    gap_x = 80
    gap_y = 60
    cols = min(len(sd.states), 4)
    rows = math.ceil(len(sd.states) / cols)

    state_positions: dict[str, tuple[float, float]] = {}
    for i, state in enumerate(sd.states):
        col = i % cols
        row = i // cols
        x: float = padding + col * (state_w + gap_x)
        y: float = padding + row * (state_h + gap_y)
        state_positions[state] = (x, y)

    width = padding * 2 + cols * (state_w + gap_x) - gap_x
    height = padding * 2 + rows * (state_h + gap_y) - gap_y + 20

    parts: list[str] = []
    parts.append(_make_arrow_defs(t, "st-"))
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    # Draw transitions (behind states)
    for trans in sd.transitions:
        src_pos = state_positions.get(trans.src)
        dst_pos = state_positions.get(trans.dst)

        if trans.src == "[*]" and trans.dst in state_positions:
            # Start transition — draw from a dot above
            dx, dy = state_positions[trans.dst]
            dot_x = dx + state_w / 2
            dot_y = dy - 20
            parts.append(f'<circle cx="{dot_x}" cy="{dot_y}" r="6" fill="{primary}"/>')
            parts.append(
                f'<line x1="{dot_x}" y1="{dot_y + 6}" x2="{dot_x}" y2="{dy}" '
                f'stroke="{muted}" stroke-width="1.5" marker-end="url(#st-arr)"/>'
            )
            continue

        if trans.dst == "[*]" and trans.src in state_positions:
            # End transition — draw to a dot below
            sx, sy = state_positions[trans.src]
            dot_x = sx + state_w / 2
            dot_y = sy + state_h + 20
            parts.append(
                f'<line x1="{dot_x}" y1="{sy + state_h}" x2="{dot_x}" y2="{dot_y - 8}" '
                f'stroke="{muted}" stroke-width="1.5" marker-end="url(#st-arr)"/>'
            )
            parts.append(f'<circle cx="{dot_x}" cy="{dot_y}" r="6" fill="{primary}"/>')
            parts.append(f'<circle cx="{dot_x}" cy="{dot_y}" r="4" fill="#ffffff"/>')
            # Adjust height
            continue

        if not src_pos or not dst_pos:
            continue

        sx, sy = src_pos
        dx, dy = dst_pos

        # Connection points
        scx, scy = sx + state_w / 2, sy + state_h / 2
        dcx, dcy = dx + state_w / 2, dy + state_h / 2

        if abs(scy - dcy) < 10:
            # Same row — horizontal
            if scx < dcx:
                x1, y1 = sx + state_w, scy
                x2, y2 = dx, dcy
            else:
                x1, y1 = sx, scy
                x2, y2 = dx + state_w, dcy
            parts.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{muted}" stroke-width="1.5" marker-end="url(#st-arr)"/>'
            )
        else:
            # Different rows — L-shaped
            x1, y1 = scx, sy + state_h
            x2, y2 = dcx, dy
            mid_y = (y1 + y2) / 2
            parts.append(
                f'<path d="M {x1},{y1} L {x1},{mid_y} L {x2},{mid_y} L {x2},{y2}" '
                f'stroke="{muted}" stroke-width="1.5" fill="none" marker-end="url(#st-arr)"/>'
            )

        # Transition label
        if trans.label:
            lx = (scx + dcx) / 2
            ly = (scy + dcy) / 2 - 8
            parts.append(
                f'<text x="{lx}" y="{ly}" text-anchor="middle" '
                f'font-family="{font}" font-size="9" fill="{muted}">'
                f"{_escape(trans.label)}</text>"
            )

    # Draw states
    for state in sd.states:
        if state == "[*]":
            continue
        pos = state_positions.get(state)
        if not pos:
            continue
        x, y = pos
        fill = _lighten(accent, 0.88)
        parts.append(
            f'<rect x="{x}" y="{y}" width="{state_w}" height="{state_h}" '
            f'rx="8" fill="{fill}" stroke="{accent}" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{x + state_w / 2}" y="{y + state_h / 2 + 4}" '
            f'text-anchor="middle" '
            f'font-family="{font}" font-size="11" font-weight="600" '
            f'fill="{body_color}">{_escape(state)}</text>'
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
        f'viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet">\n' + "\n".join(parts) + "\n</svg>"
    )
    return svg


# ---------------------------------------------------------------------------
# HTML integration
# ---------------------------------------------------------------------------

_MERMAID_BLOCK_RE = re.compile(
    r'<pre><code\s+class="language-mermaid">(.*?)</code></pre>',
    re.DOTALL,
)


def _detect_diagram_type(source: str) -> str:
    """Detect the diagram type from Mermaid source."""
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
        if re.match(r"^classDiagram\b", line, re.IGNORECASE):
            return "class"
        if re.match(r"^stateDiagram", line, re.IGNORECASE):
            return "state"
        if re.match(r"^erDiagram\b", line, re.IGNORECASE):
            return "er"
        if re.match(r"^gantt\b", line, re.IGNORECASE):
            return "gantt"
        if re.match(r"^journey\b", line, re.IGNORECASE):
            return "journey"
        break
    return "flowchart"  # default


def process_html(html: str, theme: dict[str, str] | None = None) -> str:
    """Replace all Mermaid code blocks in HTML with rendered SVGs.

    Call this after Markdown->HTML conversion but before WeasyPrint rendering.
    """

    def _replace(m: re.Match) -> str:
        source = m.group(1)
        # Unescape HTML entities that the markdown converter may have added
        source = (
            source.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )

        diagram_type = _detect_diagram_type(source)

        if diagram_type == "pie":
            pc = parse_pie(source)
            svg = render_pie_svg(pc, theme)
        elif diagram_type == "donut":
            pc = parse_pie(source)  # same data model, different renderer
            svg = render_donut_svg(pc, theme)
        elif diagram_type == "sequence":
            seq = parse_sequence(source)
            svg = render_sequence_svg(seq, theme)
        elif diagram_type == "bar":
            bc = parse_bar(source)
            svg = render_bar_svg(bc, theme)
        elif diagram_type == "gauge":
            gauge = parse_gauge(source)
            svg = render_gauge_svg(gauge, theme)
        elif diagram_type == "timeline":
            tl = parse_timeline(source)
            svg = render_timeline_svg(tl, theme)
        elif diagram_type == "gantt":
            gantt = parse_gantt(source)
            svg = render_gantt_svg(gantt, theme)
        elif diagram_type == "mindmap":
            root = parse_mindmap(source)
            svg = render_mindmap_svg(root, theme)
        elif diagram_type == "er":
            erd = parse_er(source)
            svg = render_er_svg(erd, theme)
        elif diagram_type == "state":
            state = parse_state(source)
            svg = render_state_svg(state, theme)
        else:
            # flowchart (default for unrecognized types too)
            fc = parse(source)
            svg = render_svg(fc, theme)

        return f'<div class="mermaid-diagram" style="text-align:center;margin:8pt 0 12pt 0;">{svg}</div>'

    return _MERMAID_BLOCK_RE.sub(_replace, html)
