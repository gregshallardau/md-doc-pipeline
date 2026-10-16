"""SVG diagram generators for ``::: name`` components.

Each ``*_svg(options)`` function takes the YAML options of a component block
and returns a standalone SVG string. Every colour pair used by default meets
WCAG AA (4.5:1) and every option can be overridden from the document.
"""

from __future__ import annotations

import html
import math
from typing import Any

FONT = "Arial, Helvetica, sans-serif"


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=False)


def _attr(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _text_width(text: str, size: float, bold: bool = False) -> float:
    """Rough rendered width of *text*; good enough for wrapping."""
    return len(text) * size * (0.58 if bold else 0.52)


def wrap_px(text: str, size: float, max_width: float, bold: bool = False) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in str(text).split():
        trial = f"{current} {word}".strip()
        if current and _text_width(trial, size, bold) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]


def text_block(
    x: float,
    y: float,
    lines: list[str],
    size: float,
    fill: str,
    weight: int = 400,
    anchor: str = "start",
    italic: bool = False,
    leading: float = 1.25,
) -> str:
    """Multi-line SVG text whose first line's centre sits at *y*."""
    style = ' font-style="italic"' if italic else ""
    spans = "".join(
        f'<tspan x="{x:.1f}" y="{y + i * size * leading:.1f}">{_esc(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<text text-anchor="{anchor}" dominant-baseline="central" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}"{style}>{spans}</text>'
    )


def _svg(width: float, height: float, body: str, label: str, font: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'role="img" aria-label="{_attr(label)}" font-family="{_attr(font)}">{body}</svg>'
    )


def _arrow_down(x: float, y0: float, y1: float, color: str) -> str:
    return (
        f'<path d="M{x:.1f} {y0:.1f} L{x:.1f} {y1 - 5:.1f}" stroke="{color}" stroke-width="1.6" fill="none"/>'
        f'<path d="M{x - 5:.1f} {y1 - 6:.1f} L{x:.1f} {y1:.1f} L{x + 5:.1f} {y1 - 6:.1f} Z" fill="{color}"/>'
    )


def _arrow_h(x0: float, x1: float, y: float, color: str, both: bool = False) -> str:
    d = 1 if x1 > x0 else -1
    parts = [
        f'<path d="M{x0 + (6 * d if both else 0):.1f} {y:.1f} L{x1 - 6 * d:.1f} {y:.1f}" stroke="{color}" stroke-width="1.6"/>',
        f'<path d="M{x1 - 7 * d:.1f} {y - 4:.1f} L{x1:.1f} {y:.1f} L{x1 - 7 * d:.1f} {y + 4:.1f} Z" fill="{color}"/>',
    ]
    if both:
        parts.append(
            f'<path d="M{x0 + 7 * d:.1f} {y - 4:.1f} L{x0:.1f} {y:.1f} L{x0 + 7 * d:.1f} {y + 4:.1f} Z" fill="{color}"/>'
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Tiers: numbered stack of progressively narrower tiers
# ---------------------------------------------------------------------------

TIERS_DEFAULTS: dict[str, Any] = {
    "title": "",
    "font": FONT,
    "text": "#1f2937",
    "muted": "#374151",
    "arrow": "#6b7280",
    "tiers": [
        {
            "title": "First tier",
            "subtitle": "The foundation",
            "description": "Describe what this tier provides.",
            "fill": "#e5ecf3",
            "badge": "#1f2937",
            "accent": "#1f4e79",
        },
        {
            "title": "Second tier",
            "subtitle": "Builds on the first",
            "description": "Describe what this tier adds.",
            "fill": "#dbe6f0",
            "badge": "#374151",
            "accent": "#1f4e79",
        },
        {
            "title": "Third tier",
            "subtitle": "More specific detail",
            "description": "Describe what this tier adds.",
            "fill": "#e8eef3",
            "badge": "#4b5563",
            "accent": "#1f4e79",
        },
    ],
}


def tiers_svg(options: dict[str, Any] | None = None) -> str:
    """Numbered tiers, each indented further than the one above, joined by arrows."""
    opts = {**TIERS_DEFAULTS, **(options or {})}
    tiers: list[dict[str, Any]] = list(opts["tiers"] or TIERS_DEFAULTS["tiers"])
    width, tier_h, gap, step, margin = 640.0, 74.0, 26.0, 22.0, 12.0
    right = width - margin
    parts: list[str] = []
    y = margin
    title = str(opts.get("title") or "")
    if title:
        parts.append(text_block(width / 2, y + 8, [title], 14, opts["text"], 700, "middle"))
        y += 34
    for i, tier in enumerate(tiers):
        defaults = TIERS_DEFAULTS["tiers"][min(i, len(TIERS_DEFAULTS["tiers"]) - 1)]
        t = {**defaults, **tier}
        x = margin + i * step
        w = right - x
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{tier_h}" rx="14" fill="{t["fill"]}"/>'
        )
        cx, cy = x + 34, y + tier_h / 2
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="22" fill="{t["badge"]}"/>')
        parts.append(text_block(cx, cy, [str(i + 1)], 20, "#ffffff", 700, "middle"))
        tx = x + 68
        divider = x + w * 0.52
        parts.append(text_block(tx, y + 25, [str(t["title"]).upper()], 12.5, opts["text"], 700))
        parts.append(
            text_block(
                tx,
                y + 45,
                wrap_px(t["subtitle"], 10.5, divider - tx - 12, True),
                10.5,
                t["accent"],
                700,
            )
        )
        parts.append(
            f'<path d="M{divider:.1f} {y + 12:.1f} L{divider:.1f} {y + tier_h - 12:.1f}" stroke="{opts["arrow"]}" stroke-width="0.8"/>'
        )
        desc = wrap_px(t["description"], 9.5, right - divider - 28)
        top = y + tier_h / 2 - (len(desc) - 1) * 9.5 * 1.25 / 2
        parts.append(text_block(divider + 16, top, desc, 9.5, opts["muted"]))
        y += tier_h
        if i < len(tiers) - 1:
            parts.append(_arrow_down(x + w * 0.3, y + 3, y + gap - 3, opts["arrow"]))
            y += gap
    return _svg(width, y + margin, "".join(parts), title or "Tiers diagram", opts["font"])


# ---------------------------------------------------------------------------
# Cards: side-by-side cards feeding a banner
# ---------------------------------------------------------------------------

CARDS_DEFAULTS: dict[str, Any] = {
    "title": "",
    "subtitle": "",
    "font": FONT,
    "text": "#1f2937",
    "muted": "#374151",
    "arrow": "#6b7280",
    "cards": [
        {"title": "1 - First", "subtitle": "What it covers", "items": ["Item one", "Item two"]},
        {"title": "2 - Second", "subtitle": "What it covers", "items": ["Item one", "Item two"]},
        {"title": "3 - Third", "subtitle": "What it covers", "items": ["Item one", "Item two"]},
    ],
    "card_colors": [
        {"fill": "#e8f0f7", "border": "#1f4e79", "accent": "#1f4e79"},
        {"fill": "#e6f2ef", "border": "#2f6b62", "accent": "#2f6b62"},
        {"fill": "#eaf3e6", "border": "#2f6b3b", "accent": "#2f6b3b"},
    ],
    "banner": {"title": "Result", "subtitle": "", "fill": "#1f2937", "text": "#ffffff"},
}


def cards_svg(options: dict[str, Any] | None = None) -> str:
    """Up to four cards in a row with arrows down to a banner."""
    opts = {**CARDS_DEFAULTS, **(options or {})}
    cards: list[dict[str, Any]] = list(opts["cards"] or CARDS_DEFAULTS["cards"])[:4]
    palette = opts["card_colors"]
    banner = {**CARDS_DEFAULTS["banner"], **(opts.get("banner") or {})}
    width, margin, gap = 640.0, 14.0, 14.0
    n = len(cards)
    card_w = (width - 2 * margin - (n - 1) * gap) / n
    parts: list[str] = []
    y = margin
    title, subtitle = str(opts.get("title") or ""), str(opts.get("subtitle") or "")
    if title:
        parts.append(
            text_block(width / 2, y + 10, [title.upper()], 17, opts["text"], 700, "middle")
        )
        y += 30
    if subtitle:
        parts.append(text_block(width / 2, y + 6, [subtitle], 10, opts["muted"], 400, "middle"))
        y += 24
    if title or subtitle:
        y += 6

    prepared = []
    for card in cards:
        sub = wrap_px(card.get("subtitle", ""), 8.8, card_w - 24)
        items = [str(i) for i in (card.get("items") or [])]
        height = 34 + len(sub) * 11 + 12 + len(items) * 17 + 14
        prepared.append((card, sub, items, height))
    card_h = max(h for *_rest, h in prepared)
    for i, (card, sub, items, _h) in enumerate(prepared):
        colors = {**palette[i % len(palette)], **(card.get("colors") or {})}
        x = margin + i * (card_w + gap)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{card_w:.1f}" height="{card_h:.1f}" rx="10" '
            f'fill="{colors["fill"]}" stroke="{colors["border"]}" stroke-width="1.6"/>'
        )
        cx = x + card_w / 2
        parts.append(
            text_block(
                cx,
                y + 18,
                wrap_px(card["title"], 11, card_w - 20, True),
                11,
                colors["accent"],
                700,
                "middle",
            )
        )
        parts.append(text_block(cx, y + 36, sub, 8.8, opts["muted"], 400, "middle"))
        iy = y + 36 + len(sub) * 11 + 14
        for item in items:
            parts.append(text_block(cx, iy, [item], 10.5, opts["text"], 700, "middle"))
            iy += 17
        parts.append(_arrow_down(cx, y + card_h + 2, y + card_h + 26, opts["arrow"]))
    y += card_h + 28
    banner_h = 46 if banner.get("subtitle") else 34
    parts.append(
        f'<rect x="{margin}" y="{y:.1f}" width="{width - 2 * margin:.1f}" height="{banner_h}" rx="8" fill="{banner["fill"]}"/>'
    )
    parts.append(
        text_block(
            width / 2,
            y + (15 if banner.get("subtitle") else banner_h / 2),
            [str(banner["title"]).upper()],
            12,
            banner["text"],
            700,
            "middle",
        )
    )
    if banner.get("subtitle"):
        parts.append(
            text_block(
                width / 2, y + 32, [str(banner["subtitle"])], 9, banner["text"], 400, "middle"
            )
        )
    y += banner_h + margin
    return _svg(width, y, "".join(parts), title or "Cards diagram", opts["font"])


# ---------------------------------------------------------------------------
# Matrix: likelihood x consequence heat map
# ---------------------------------------------------------------------------

MATRIX_DEFAULTS: dict[str, Any] = {
    "title": "Risk matrix",
    "font": FONT,
    "text": "#1f2937",
    "columns": ["Insignificant", "Minor", "Moderate", "Major", "Catastrophic"],
    "rows": ["Almost certain", "Likely", "Possible", "Unlikely", "Rare"],
    "x_label": "Consequences",
    "y_label": "Likelihood",
    "grid": [
        ["High", "High", "Extreme", "Extreme", "Extreme"],
        ["Moderate", "High", "High", "Extreme", "Extreme"],
        ["Low", "Moderate", "High", "Extreme", "Extreme"],
        ["Low", "Low", "Moderate", "High", "Extreme"],
        ["Low", "Low", "Moderate", "High", "High"],
    ],
    "levels": {
        "Low": {"fill": "#d5e8d4", "text": "#14301a"},
        "Moderate": {"fill": "#fff2b3", "text": "#3d3100"},
        "High": {"fill": "#f5b87a", "text": "#3b1d00"},
        "Extreme": {"fill": "#b42318", "text": "#ffffff"},
    },
    "legend": True,
}


def matrix_svg(options: dict[str, Any] | None = None) -> str:
    """Heat-map grid: rows x columns coloured by the rating in each cell."""
    opts = {**MATRIX_DEFAULTS, **(options or {})}
    levels = {**MATRIX_DEFAULTS["levels"], **(opts.get("levels") or {})}
    columns, rows, grid = list(opts["columns"]), list(opts["rows"]), list(opts["grid"])
    width, margin = 640.0, 14.0
    label_w, cell_h = 118.0, 40.0
    left = margin + 26 + label_w
    cell_w = (width - margin - left) / max(len(columns), 1)
    parts: list[str] = []
    y = margin
    title = str(opts.get("title") or "")
    if title:
        parts.append(text_block(margin, y + 8, [title], 16, opts["text"], 700))
        y += 34
    if opts.get("x_label"):
        parts.append(
            text_block(
                left + cell_w * len(columns) / 2,
                y + 8,
                [str(opts["x_label"])],
                11,
                opts["text"],
                700,
                "middle",
            )
        )
        y += 22
    grid_top = y
    for c, name in enumerate(columns):
        parts.append(
            f'<rect x="{left + c * cell_w:.1f}" y="{y:.1f}" width="{cell_w - 2:.1f}" height="28" fill="{opts["text"]}"/>'
        )
        parts.append(
            text_block(
                left + c * cell_w + (cell_w - 2) / 2,
                y + 14,
                wrap_px(name, 9.5, cell_w - 8, True),
                9.5,
                "#ffffff",
                700,
                "middle",
            )
        )
    y += 32
    body_top = y
    for r, row_name in enumerate(rows):
        parts.append(
            f'<rect x="{margin + 26:.1f}" y="{y:.1f}" width="{label_w - 2:.1f}" height="{cell_h - 2:.1f}" fill="{opts["text"]}"/>'
        )
        parts.append(
            text_block(
                margin + 26 + (label_w - 2) / 2,
                y + (cell_h - 2) / 2,
                [str(row_name)],
                9.5,
                "#ffffff",
                700,
                "middle",
            )
        )
        for c in range(len(columns)):
            rating = str(grid[r][c]) if r < len(grid) and c < len(grid[r]) else ""
            level = levels.get(rating, {"fill": "#e5e7eb", "text": opts["text"]})
            parts.append(
                f'<rect x="{left + c * cell_w:.1f}" y="{y:.1f}" width="{cell_w - 2:.1f}" height="{cell_h - 2:.1f}" fill="{level["fill"]}"/>'
            )
            parts.append(
                text_block(
                    left + c * cell_w + (cell_w - 2) / 2,
                    y + (cell_h - 2) / 2,
                    [rating],
                    10,
                    level["text"],
                    700,
                    "middle",
                )
            )
        y += cell_h
    if opts.get("y_label"):
        ycx, ycy = margin + 8, (body_top + y) / 2
        parts.append(
            f'<g transform="rotate(-90 {ycx:.1f} {ycy:.1f})">{text_block(ycx, ycy, [str(opts["y_label"])], 11, opts["text"], 700, "middle")}</g>'
        )
    if opts.get("legend", True):
        y += 12
        lx = margin + 26
        parts.append(text_block(lx, y + 8, ["Risk ratings"], 9.5, opts["text"], 700))
        lx += 74
        for name, level in levels.items():
            parts.append(
                f'<rect x="{lx:.1f}" y="{y + 1:.1f}" width="14" height="14" fill="{level["fill"]}" stroke="{opts["text"]}" stroke-width="0.4"/>'
            )
            parts.append(text_block(lx + 20, y + 8, [str(name)], 9.5, opts["text"]))
            lx += 28 + _text_width(str(name), 9.5)
        y += 20
    del grid_top
    return _svg(width, y + margin, "".join(parts), title or "Matrix", opts["font"])


# ---------------------------------------------------------------------------
# Process: stacked steps with side panels and a dashed boundary
# ---------------------------------------------------------------------------

PROCESS_DEFAULTS: dict[str, Any] = {
    "title": "",
    "font": FONT,
    "text": "#1f2937",
    "arrow": "#374151",
    "fill": "#e8eef4",
    "stroke": "#1f4e79",
    "steps": ["Context", "Identification", "Analysis", "Evaluation", "Treatment"],
    "left": "Communication and consultation",
    "right": "Monitor and review",
    "right_box": "",
    "footer": "",
}


def process_svg(options: dict[str, Any] | None = None) -> str:
    """Vertical process: steps joined by arrows, flanked by two side panels."""
    opts = {**PROCESS_DEFAULTS, **(options or {})}
    steps = [str(s) for s in (opts["steps"] or [])]
    width, margin = 640.0, 14.0
    panel_w, step_w, step_h, gap = 130.0, 210.0, 36.0, 24.0
    title = str(opts.get("title") or "")
    parts: list[str] = []
    y = margin
    if title:
        parts.append(text_block(width / 2, y + 8, [title], 15, opts["text"], 700, "middle"))
        y += 32
    inner_top = y
    n = len(steps)
    stack_h = n * step_h + (n - 1) * gap
    footer = str(opts.get("footer") or "")
    box_h = stack_h + 40 + (30 if footer else 0)
    parts.append(
        f'<rect x="{margin}" y="{y:.1f}" width="{width - 2 * margin:.1f}" height="{box_h + 20:.1f}" rx="26" fill="none" stroke="{opts["text"]}" stroke-width="1.6"/>'
    )
    cx = width / 2
    left_x = margin + 16
    right_x = width - margin - 16 - panel_w
    parts.append(
        f'<rect x="{left_x:.1f}" y="{y + 18:.1f}" width="{panel_w}" height="{box_h - 16:.1f}" fill="#ffffff" stroke="{opts["text"]}" stroke-width="1.4"/>'
    )
    parts.append(
        text_block(
            left_x + panel_w / 2,
            y + 18 + (box_h - 16) / 2,
            wrap_px(opts["left"], 11, panel_w - 20, True),
            11,
            opts["text"],
            700,
            "middle",
        )
    )
    parts.append(
        f'<rect x="{right_x:.1f}" y="{y + 18:.1f}" width="{panel_w}" height="{box_h - 16:.1f}" fill="#ffffff" stroke="{opts["text"]}" stroke-width="1.4"/>'
    )
    right_lines = wrap_px(opts["right"], 11, panel_w - 20, True)
    right_box = str(opts.get("right_box") or "")
    ry = y + 18 + (box_h - 16) / 2 - (30 if right_box else 0)
    parts.append(
        text_block(right_x + panel_w / 2, ry, right_lines, 11, opts["text"], 700, "middle")
    )
    if right_box:
        by = ry + 28
        parts.append(
            f'<rect x="{right_x + 14:.1f}" y="{by:.1f}" width="{panel_w - 28}" height="64" fill="{opts["fill"]}" stroke="{opts["text"]}" stroke-width="1.4"/>'
        )
        parts.append(
            text_block(
                right_x + panel_w / 2,
                by + 32,
                wrap_px(right_box, 9.5, panel_w - 24, True),
                9.5,
                opts["text"],
                700,
                "middle",
            )
        )
    parts.append(
        f'<rect x="{cx - step_w / 2 - 18:.1f}" y="{y + 12:.1f}" width="{step_w + 36}" height="{box_h:.1f}" rx="14" fill="none" stroke="{opts["text"]}" stroke-width="1.2" stroke-dasharray="7 5"/>'
    )
    sy = y + 30
    for i, label in enumerate(steps):
        top = sy + i * (step_h + gap)
        parts.append(
            f'<rect x="{cx - step_w / 2:.1f}" y="{top:.1f}" width="{step_w}" height="{step_h}" fill="{opts["fill"]}" stroke="{opts["text"]}" stroke-width="1.4"/>'
        )
        parts.append(text_block(cx, top + step_h / 2, [label], 11.5, opts["text"], 700, "middle"))
        mid = top + step_h / 2
        parts.append(
            _arrow_h(left_x + panel_w, cx - step_w / 2 - 18, mid, opts["arrow"], both=True)
        )
        parts.append(_arrow_h(cx + step_w / 2 + 18, right_x, mid, opts["arrow"], both=True))
        if i < n - 1:
            parts.append(_arrow_down(cx, top + step_h, top + step_h + gap, opts["arrow"]))
    if footer:
        parts.append(
            text_block(cx, y + box_h - 8, [footer], 9.5, opts["text"], 700, "middle", italic=True)
        )
    y = inner_top + box_h + 20 + margin
    return _svg(width, y, "".join(parts), title or "Process diagram", opts["font"])


# ---------------------------------------------------------------------------
# Flow: nodes placed on a grid, arrows routed at right angles
# ---------------------------------------------------------------------------

FLOW_DEFAULTS: dict[str, Any] = {
    "title": "",
    "font": FONT,
    "text": "#1f2937",
    "fill": "#e8eef4",
    "stroke": "#1f4e79",
    "arrow": "#374151",
    "decision_fill": "#fff2b3",
    "col_width": 200,
    "row_gap": 46,
    "nodes": [
        {"id": "start", "label": "Start", "shape": "pill", "at": [0, 0]},
        {"id": "step", "label": "A step", "at": [0, 1]},
        {"id": "ok", "label": "Is it acceptable?", "shape": "diamond", "at": [0, 2]},
        {"id": "end", "label": "Finish", "shape": "pill", "at": [0, 3]},
    ],
    "edges": [["start", "step"], ["step", "ok"], ["ok", "end", "Yes"]],
}


def _flow_node_box(node: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
    col_w = float(opts["col_width"])
    span = float(node.get("span", 1))
    shape = node.get("shape", "box")
    width = float(node.get("width") or max(span * col_w - 44, 96))
    size = 10.5
    label = str(node.get("label", ""))
    inner = width - (60 if shape == "diamond" else 22)
    lines: list[str] = []
    for chunk in label.replace("\\n", "\n").split("\n"):
        lines.extend(wrap_px(chunk, size, inner, bool(node.get("bold", True))))
    height = len(lines) * size * 1.3 + (34 if shape == "diamond" else 18)
    height = max(height, 56 if shape == "diamond" else 34)
    return {"lines": lines, "w": width, "h": height, "size": size, "shape": shape, "span": span}


def flow_svg(options: dict[str, Any] | None = None) -> str:
    """Flowchart with nodes on a ``[column, row]`` grid and orthogonal arrows.

    Nodes: ``id``, ``label``, ``at: [col, row]`` (fractions allowed), optional
    ``shape`` (box, pill, diamond), ``span`` (columns wide), ``fill``, ``text``.
    Edges: ``[from, to, label?]`` or ``{from, to, label, exit, enter, via}``
    where ``exit``/``enter`` pick a side (top, bottom, left, right) and ``via``
    (left or right) sends the arrow round the outside of the diagram.
    """
    opts = {**FLOW_DEFAULTS, **(options or {})}
    nodes_in: list[dict[str, Any]] = list(opts["nodes"] or FLOW_DEFAULTS["nodes"])
    edges_in = list(opts["edges"] if "edges" in (options or {}) or options is None else [])
    if options and "nodes" not in options:
        edges_in = FLOW_DEFAULTS["edges"] if not options.get("edges") else options["edges"]
    col_w, row_gap, margin = float(opts["col_width"]), float(opts["row_gap"]), 16.0
    boxes = {str(n["id"]): {**n, **_flow_node_box(n, opts)} for n in nodes_in}
    max_col = max(b["at"][0] + b["span"] for b in boxes.values())
    lanes_l = sum(1 for e in edges_in if isinstance(e, dict) and e.get("via") == "left")
    lanes_r = sum(1 for e in edges_in if isinstance(e, dict) and e.get("via") == "right")
    left_pad = margin + 34 * lanes_l
    title = str(opts.get("title") or "")
    top = margin + (30 if title else 0)

    rows = sorted({b["at"][1] for b in boxes.values()})
    row_h = {r: max(b["h"] for b in boxes.values() if b["at"][1] == r) for r in rows}
    row_y: dict[float, float] = {}
    y = top
    for r in rows:
        row_y[r] = y
        y += row_h[r] + row_gap
    total_h = y - row_gap + margin
    width = left_pad + max_col * col_w + 34 * lanes_r + margin

    for b in boxes.values():
        b["cx"] = left_pad + (b["at"][0] + b["span"] / 2) * col_w
        b["cy"] = row_y[b["at"][1]] + row_h[b["at"][1]] / 2

    def port(b: dict[str, Any], side: str) -> tuple[float, float]:
        return {
            "top": (b["cx"], b["cy"] - b["h"] / 2),
            "bottom": (b["cx"], b["cy"] + b["h"] / 2),
            "left": (b["cx"] - b["w"] / 2, b["cy"]),
            "right": (b["cx"] + b["w"] / 2, b["cy"]),
        }[side]

    parts: list[str] = []
    if title:
        parts.append(text_block(width / 2, margin + 8, [title], 15, opts["text"], 700, "middle"))
    arrow = opts["arrow"]
    for b in boxes.values():
        x, yy, w, h = b["cx"] - b["w"] / 2, b["cy"] - b["h"] / 2, b["w"], b["h"]
        fill = b.get("fill") or (opts["decision_fill"] if b["shape"] == "diamond" else opts["fill"])
        stroke = b.get("stroke") or opts["stroke"]
        if b["shape"] == "diamond":
            pts = f'{b["cx"]},{yy} {x + w},{b["cy"]} {b["cx"]},{yy + h} {x},{b["cy"]}'
            parts.append(
                f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
            )
        else:
            rx = h / 2 if b["shape"] == "pill" else 6
            parts.append(
                f'<rect x="{x:.1f}" y="{yy:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
            )
        n_lines = len(b["lines"])
        top_line = b["cy"] - (n_lines - 1) * b["size"] * 1.3 / 2
        parts.append(
            text_block(
                b["cx"],
                top_line,
                b["lines"],
                b["size"],
                b.get("text") or opts["text"],
                700,
                "middle",
                leading=1.3,
            )
        )

    lane_l = lane_r = 0
    for edge in edges_in:
        if isinstance(edge, (list, tuple)):
            e = {"from": edge[0], "to": edge[1], "label": edge[2] if len(edge) > 2 else ""}
        else:
            e = dict(edge)
        src, dst = boxes.get(str(e["from"])), boxes.get(str(e["to"]))
        if src is None or dst is None:
            continue
        via = e.get("via")
        exit_side = e.get("exit")
        enter_side = e.get("enter")
        if via:
            exit_side = exit_side or via
            enter_side = enter_side or via
            sx, sy = port(src, exit_side)
            tx, ty = port(dst, enter_side)
            if via == "left":
                lane_x = left_pad - 18 - 34 * lane_l
                lane_l += 1
            else:
                lane_x = left_pad + max_col * col_w + 18 + 34 * lane_r
                lane_r += 1
            route = [(sx, sy), (lane_x, sy), (lane_x, ty), (tx, ty)]
        else:
            forward = dst["cy"] > src["cy"] + 1
            same_row = abs(dst["cy"] - src["cy"]) <= 1
            if same_row:
                exit_side = exit_side or ("right" if dst["cx"] > src["cx"] else "left")
                enter_side = enter_side or ("left" if dst["cx"] > src["cx"] else "right")
                (sx, sy), (tx, ty) = port(src, exit_side), port(dst, enter_side)
                route = [(sx, sy), (tx, ty)]
            else:
                exit_side = exit_side or ("bottom" if forward else "top")
                enter_side = enter_side or ("top" if forward else "bottom")
                (sx, sy), (tx, ty) = port(src, exit_side), port(dst, enter_side)
                if exit_side in ("left", "right"):
                    route = [(sx, sy), (tx, sy), (tx, ty)]
                elif abs(sx - tx) < 1:
                    route = [(sx, sy), (tx, ty)]
                else:
                    mid = (sy + ty) / 2
                    route = [(sx, sy), (sx, mid), (tx, mid), (tx, ty)]
        d = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in route)
        parts.append(f'<path d="{d}" fill="none" stroke="{arrow}" stroke-width="1.5"/>')
        (x0, y0), (x1, y1) = route[-2], route[-1]
        dx, dy = x1 - x0, y1 - y0
        norm = math.hypot(dx, dy) or 1
        ux, uy = dx / norm, dy / norm
        bx, by = x1 - ux * 8, y1 - uy * 8
        parts.append(
            f'<path d="M{x1:.1f} {y1:.1f} L{bx - uy * 4:.1f} {by + ux * 4:.1f} L{bx + uy * 4:.1f} {by - ux * 4:.1f} Z" fill="{arrow}"/>'
        )
        if e.get("label"):
            (lx0, ly0), (lx1, ly1) = route[0], route[1]
            lx, ly = (lx0 + lx1) / 2, (ly0 + ly1) / 2
            horizontal = abs(ly1 - ly0) < 1
            parts.append(
                text_block(
                    lx + (0 if horizontal else 12),
                    ly + (-9 if horizontal else 0),
                    [str(e["label"])],
                    9.5,
                    opts["text"],
                    700,
                    "middle" if horizontal else "start",
                )
            )
    return _svg(width, total_h, "".join(parts), title or "Flow diagram", opts["font"])
