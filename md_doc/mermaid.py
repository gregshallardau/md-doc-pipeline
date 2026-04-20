"""Mermaid flowchart parser and branded SVG renderer.

Parses a subset of Mermaid flowchart syntax and renders to SVG using
colours from the active PDF theme.  No external dependencies — pure Python.

Supported syntax
----------------
    flowchart LR|TD|TB
      A["label"]                    rectangle node
      B{"label"}                    diamond (decision) node
      C(["label"])                  stadium (rounded) node
      A --> B                       edge
      A -- "label" --> B            labelled edge
      A --> B --> C                 chained edges
      style A fill:#abc,stroke:#def inline style (parsed but uses theme)
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Node:
    id: str
    label: str
    shape: str = "rect"  # rect | diamond | stadium
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""


@dataclass
class Flowchart:
    direction: str = "LR"  # LR | TD | TB
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)


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
    "font": "Segoe UI, Helvetica Neue, Arial, sans-serif",
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Patterns for node shapes in definitions and inline in edges
_NODE_PATTERNS = [
    # A(["label"]) — stadium
    (re.compile(r'^([A-Za-z_]\w*)\(\["([^"]+)"\]\)$'), "stadium"),
    # A{"label"} — diamond
    (re.compile(r'^([A-Za-z_]\w*)\{"([^"]+)"\}$'), "diamond"),
    # A["label"] — rect
    (re.compile(r'^([A-Za-z_]\w*)\["([^"]+)"\]$'), "rect"),
    # A(["label"]) with single quotes
    (re.compile(r"^([A-Za-z_]\w*)\(\['([^']+)'\]\)$"), "stadium"),
    # A{'label'} — diamond
    (re.compile(r"^([A-Za-z_]\w*)\{'([^']+)'\}$"), "diamond"),
    # A['label'] — rect
    (re.compile(r"^([A-Za-z_]\w*)\['([^']+)'\]$"), "rect"),
]

# Edge patterns: --> or -- "label" -->
_EDGE_RE = re.compile(r'-->\s*|--\s*"([^"]*)"\s*-->\s*|--\s*([^\s"]+)\s*-->\s*')


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
    if re.match(r'^[A-Za-z_]\w*$', nid) and nid not in fc.nodes:
        fc.nodes[nid] = Node(id=nid, label=nid, shape="rect")
    return nid


def parse(source: str) -> Flowchart:
    """Parse Mermaid flowchart source into a Flowchart model."""
    fc = Flowchart()
    lines = source.strip().splitlines()

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue

        # Direction line
        dir_m = re.match(r'^flowchart\s+(LR|TD|TB|RL|BT)\s*$', line, re.IGNORECASE)
        if dir_m:
            fc.direction = dir_m.group(1).upper()
            continue

        # Skip style lines (we use our own theme)
        if line.startswith("style ") or line.startswith("classDef "):
            continue

        # Skip subgraph/end
        if line.startswith("subgraph ") or line == "end":
            continue

        # Try to parse as edge chain: A --> B --> C or A -- "label" --> B
        if "-->" in line:
            _parse_edge_line(fc, line)
            continue

        # Standalone node definition
        for pattern, shape in _NODE_PATTERNS:
            m = pattern.match(line)
            if m:
                nid, label = m.group(1), m.group(2)
                fc.nodes[nid] = Node(id=nid, label=label, shape=shape)
                break

    return fc


def _parse_edge_line(fc: Flowchart, line: str) -> None:
    """Parse a line containing one or more chained edges."""
    # Split the line by edge operators, preserving labels
    # Strategy: find all --> and -- "label" --> patterns, extract segments between them
    parts: list[str] = []
    labels: list[str] = []

    remaining = line
    while True:
        m = _EDGE_RE.search(remaining)
        if not m:
            parts.append(remaining.strip())
            break
        parts.append(remaining[:m.start()].strip())
        label = m.group(1) or m.group(2) or ""
        labels.append(label)
        remaining = remaining[m.end():]

    # Register nodes and create edges
    node_ids: list[str] = []
    for part in parts:
        if part:
            nid = _ensure_node(fc, part)
            if nid:
                node_ids.append(nid)

    for i in range(len(node_ids) - 1):
        label = labels[i] if i < len(labels) else ""
        fc.edges.append(Edge(src=node_ids[i], dst=node_ids[i + 1], label=label))


# ---------------------------------------------------------------------------
# Layout engine
# ---------------------------------------------------------------------------

def _compute_levels(fc: Flowchart) -> dict[str, int]:
    """Assign each node a level (column for LR, row for TD) via BFS."""
    # Build adjacency
    children: dict[str, list[str]] = defaultdict(list)
    has_parent: set[str] = set()
    for e in fc.edges:
        children[e.src].append(e.dst)
        has_parent.add(e.dst)

    # Find roots (nodes with no incoming edges)
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

    # Assign any unvisited nodes
    for nid in fc.nodes:
        if nid not in levels:
            levels[nid] = 0

    return levels


def layout(fc: Flowchart, theme: dict[str, str] | None = None) -> None:
    """Position all nodes in the flowchart."""
    if not fc.nodes:
        return

    t = theme or DEFAULT_THEME
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

    # Assign levels
    levels = _compute_levels(fc)

    # Group nodes by level
    level_groups: dict[int, list[str]] = defaultdict(list)
    for nid, lvl in levels.items():
        level_groups[lvl].append(nid)

    # Build parent→children map for centering
    children_map: dict[str, list[str]] = defaultdict(list)
    for e in fc.edges:
        if e.dst not in children_map[e.src]:
            children_map[e.src].append(e.dst)

    is_horizontal = fc.direction in ("LR", "RL")
    gap_major = 60  # gap between levels
    gap_minor = 30  # gap between nodes in same level
    padding = 30     # edge padding

    if is_horizontal:
        # LR: levels are columns, nodes stack vertically within each column
        # Normalize widths: all rect nodes in a column share the widest width
        for lvl, nids in level_groups.items():
            rect_nodes = [fc.nodes[n] for n in nids if fc.nodes[n].shape == "rect"]
            if len(rect_nodes) > 1:
                max_w = max(n.w for n in rect_nodes)
                for n in rect_nodes:
                    n.w = max_w

        # First pass: position each level's x based on column widths
        col_x: dict[int, float] = {}
        x_cursor = padding
        for lvl in sorted(level_groups.keys()):
            col_x[lvl] = x_cursor
            max_w = max(fc.nodes[n].w for n in level_groups[lvl])
            x_cursor += max_w + gap_major

        # Calculate total height needed per column, then center each
        # column's node group around the overall max height
        col_total_h: dict[int, float] = {}
        for lvl, nids in level_groups.items():
            total = sum(fc.nodes[n].h for n in nids) + gap_minor * (len(nids) - 1)
            col_total_h[lvl] = total
        max_total_h = max(col_total_h.values())

        # Position nodes: x from column, y centered around the diagram midpoint
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
        # TD/TB: levels are rows, nodes spread horizontally
        # First pass: position each level's y based on row heights
        row_y: dict[int, float] = {}
        y_cursor = padding
        for lvl in sorted(level_groups.keys()):
            row_y[lvl] = y_cursor
            max_h = max(fc.nodes[n].h for n in level_groups[lvl])
            y_cursor += max_h + gap_major

        # Position children first (bottom-up), then center parents
        max_lvl = max(level_groups.keys()) if level_groups else 0

        # Bottom-up: position the widest (deepest) level first, then center parents
        for lvl in sorted(level_groups.keys(), reverse=True):
            nids = level_groups[lvl]
            if lvl == max_lvl or not any(children_map.get(n) for n in nids):
                # Leaf level or deepest: spread evenly from left
                x_cursor = padding
                for nid in nids:
                    node = fc.nodes[nid]
                    node.x = x_cursor
                    node.y = row_y[lvl]
                    x_cursor += node.w + gap_minor
            else:
                # Parent level: center each node over its children
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


# ---------------------------------------------------------------------------
# SVG renderer
# ---------------------------------------------------------------------------

def _escape(text: str) -> str:
    """Escape text for SVG/XML."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_svg(fc: Flowchart, theme: dict[str, str] | None = None) -> str:
    """Render a laid-out Flowchart to an SVG string."""
    t = {**DEFAULT_THEME, **(theme or {})}
    layout(fc, t)

    if not fc.nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>'

    font = t["font"]
    parts: list[str] = []

    # Calculate canvas size
    max_x = max(n.x + n.w for n in fc.nodes.values()) + 30
    max_y = max(n.y + n.h for n in fc.nodes.values()) + 30
    width = max(max_x, 200)
    height = max(max_y, 100)

    # Arrow marker
    parts.append(f'''<defs>
  <marker id="arr" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
    <polygon points="0 0, 8 3, 0 6" fill="{t['muted']}"/>
  </marker>
</defs>''')

    # Background
    parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff" rx="4"/>')

    # Draw edges first (behind nodes)
    for edge in fc.edges:
        src = fc.nodes.get(edge.src)
        dst = fc.nodes.get(edge.dst)
        if not src or not dst:
            continue
        parts.append(_render_edge(src, dst, edge.label, fc.direction, t))

    # Draw nodes
    for node in fc.nodes.values():
        parts.append(_render_node(node, t))

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
           f'viewBox="0 0 {width} {height}" '
           f'preserveAspectRatio="xMidYMid meet">\n'
           + "\n".join(parts) +
           '\n</svg>')
    return svg


def _render_node(node: Node, t: dict[str, str]) -> str:
    """Render a single node to SVG elements."""
    font = t["font"]
    cx = node.x + node.w / 2
    cy = node.y + node.h / 2
    parts: list[str] = []

    if node.shape == "diamond":
        fill = t["diamond_fill"]
        stroke = t["diamond_stroke"]
        rx = node.w / 2
        ry = node.h / 2
        points = f"{cx},{node.y} {node.x + node.w},{cy} {cx},{node.y + node.h} {node.x},{cy}"
        parts.append(f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>')
    elif node.shape == "stadium":
        fill = t["stadium_fill"]
        stroke = t["stadium_stroke"]
        r = node.h / 2
        parts.append(f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" '
                      f'rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>')
    else:  # rect
        fill = t["node_fill"]
        stroke = t["node_stroke"]
        parts.append(f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" '
                      f'rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>')

    # Label (support multi-line via \n or <br>)
    label = node.label.replace("<br>", "\n")
    lines = label.split("\n")
    line_height = 14
    start_y = cy - (len(lines) - 1) * line_height / 2

    for i, line in enumerate(lines):
        text_y = start_y + i * line_height + 4
        parts.append(f'<text x="{cx}" y="{text_y}" text-anchor="middle" '
                      f'font-family="{font}" font-size="11" font-weight="600" '
                      f'fill="{t["body"]}">{_escape(line.strip())}</text>')

    return "\n".join(parts)


def _render_edge(src: Node, dst: Node, label: str, direction: str, t: dict[str, str]) -> str:
    """Render an edge between two nodes."""
    font = t["font"]
    parts: list[str] = []

    # Calculate connection points
    is_h = direction in ("LR", "RL")

    if is_h:
        # Horizontal layout: connect right side of src to left side of dst
        if src.x + src.w / 2 < dst.x + dst.w / 2:
            # src is left of dst
            x1 = src.x + src.w
            y1 = src.y + src.h / 2
            x2 = dst.x
            y2 = dst.y + dst.h / 2

            if dst.shape == "diamond":
                x2 = dst.x  # left point of diamond
        else:
            x1 = src.x
            y1 = src.y + src.h / 2
            x2 = dst.x + dst.w
            y2 = dst.y + dst.h / 2

        if abs(y1 - y2) < 2:
            # Straight horizontal arrow
            parts.append(f'<path d="M {x1},{y1} L {x2},{y2}" '
                          f'stroke="{t["muted"]}" stroke-width="1.5" fill="none" '
                          f'marker-end="url(#arr)"/>')
        else:
            # L-shaped routing
            mid_x = (x1 + x2) / 2
            parts.append(f'<path d="M {x1},{y1} L {mid_x},{y1} L {mid_x},{y2} L {x2},{y2}" '
                          f'stroke="{t["muted"]}" stroke-width="1.5" fill="none" '
                          f'marker-end="url(#arr)"/>')
    else:
        # Vertical layout: connect bottom of src to top of dst
        if src.y + src.h / 2 < dst.y + dst.h / 2:
            x1 = src.x + src.w / 2
            y1 = src.y + src.h
            x2 = dst.x + dst.w / 2
            y2 = dst.y

            if dst.shape == "diamond":
                y2 = dst.y  # top point of diamond
        else:
            x1 = src.x + src.w / 2
            y1 = src.y
            x2 = dst.x + dst.w / 2
            y2 = dst.y + dst.h

        if abs(x1 - x2) < 2:
            parts.append(f'<path d="M {x1},{y1} L {x2},{y2}" '
                          f'stroke="{t["muted"]}" stroke-width="1.5" fill="none" '
                          f'marker-end="url(#arr)"/>')
        else:
            mid_y = (y1 + y2) / 2
            parts.append(f'<path d="M {x1},{y1} L {x1},{mid_y} L {x2},{mid_y} L {x2},{y2}" '
                          f'stroke="{t["muted"]}" stroke-width="1.5" fill="none" '
                          f'marker-end="url(#arr)"/>')

    # Edge label
    if label:
        lx = (src.x + src.w / 2 + dst.x + dst.w / 2) / 2
        ly = (src.y + src.h / 2 + dst.y + dst.h / 2) / 2
        if is_h:
            ly -= 8
        else:
            lx += 10
        parts.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" '
                      f'font-family="{font}" font-size="9" fill="{t["muted"]}">'
                      f'{_escape(label)}</text>')

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# HTML integration
# ---------------------------------------------------------------------------

_MERMAID_BLOCK_RE = re.compile(
    r'<pre><code\s+class="language-mermaid">(.*?)</code></pre>',
    re.DOTALL,
)


def process_html(html: str, theme: dict[str, str] | None = None) -> str:
    """Replace all Mermaid code blocks in HTML with rendered SVGs.

    Call this after Markdown→HTML conversion but before WeasyPrint rendering.
    """
    def _replace(m: re.Match) -> str:
        source = m.group(1)
        # Unescape HTML entities that the markdown converter may have added
        source = (source
                  .replace("&amp;", "&")
                  .replace("&lt;", "<")
                  .replace("&gt;", ">")
                  .replace("&quot;", '"')
                  .replace("&#39;", "'"))
        fc = parse(source)
        svg = render_svg(fc, theme)
        return f'<div class="mermaid-diagram" style="text-align:center;margin:8pt 0 12pt 0;">{svg}</div>'

    return _MERMAID_BLOCK_RE.sub(_replace, html)
