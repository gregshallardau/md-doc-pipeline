"""Authoring components expanded from ``::: name`` fenced blocks.

A block looks like::

    ::: must
    Providers must identify and manage risks.
    :::

    ::: rings
    title: Framework
    caption: Figure 1 The framework
    rings:
      - {label: Context, fill: "#e5e7eb", text: "#1f2937"}
      - {label: Management, fill: "#1f4e79", text: "#ffffff"}
    centre: {label: People}
    :::

Both builders call :func:`expand_components` on the Markdown body before the
Markdown is converted to HTML. Callouts become ``<blockquote>`` elements (which
the Word builder already shades and rules from inline colours); figures become
an inline SVG in PDF and a ``mddocsvg:`` image reference that the Word builder
rasterises.
"""

from __future__ import annotations

import base64
import html
import logging
import re
from typing import Any

import yaml

from .literal import transform_outside_code

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Callouts
# ---------------------------------------------------------------------------

#: kind -> (label, background, left rule, label colour). Every text/background
#: pair meets WCAG AA (>= 4.5:1).
CALLOUTS: dict[str, tuple[str, str, str, str]] = {
    "must": ("MUST", "#fdeceb", "#c0392b", "#a8201a"),
    "should": ("SHOULD", "#fff1e0", "#e07b00", "#8a4300"),
    "may": ("MAY", "#e7f4ec", "#2e9e5b", "#1d6a3a"),
}

_FENCE_OPEN_RE = re.compile(r"^:::[ \t]+([A-Za-z][\w-]*)[ \t]*$")
_FENCE_CLOSE_RE = re.compile(r"^:::[ \t]*$")

#: Default CSS for components. Emitted before the theme stylesheet so a theme
#: can restyle anything here.
COMPONENT_CSS = """\
.callout { page-break-inside: avoid; break-inside: avoid; }
.callout p.callout-label { font-size: 7.5pt; font-weight: 700; letter-spacing: 1pt; margin: 0 0 2pt 0; }
.callout p { margin: 0 0 4pt 0; }
figure.mddoc-figure { margin: 10pt 0 14pt 0; text-align: center; page-break-inside: avoid; break-inside: avoid; }
figure.mddoc-figure svg { width: 100%; max-width: 135mm; height: auto; }
p.figure-caption { font-size: 8.5pt; font-style: italic; text-align: center; margin: 2pt 0 12pt 0; }
p.table-caption { font-size: 8.5pt; font-style: italic; margin: 10pt 0 3pt 0; page-break-after: avoid; break-after: avoid; }
.list-of ul { list-style: none; padding-left: 0; margin: 0 0 8pt 0; }
.list-of li { margin: 0 0 3pt 0; }
.list-of a { text-decoration: none; display: block; color: inherit; }
.list-of a[href^="#"]::after { content: leader('.') target-counter(attr(href url), page); }
"""


def _callout_html(kind: str, body: str) -> str:
    label, bg, rule, label_color = CALLOUTS[kind]
    return (
        f'<blockquote class="callout callout-{kind}" '
        f'style="background:{bg};border-left-color:{rule}" markdown="1">\n'
        f'<p class="callout-label" style="color:{label_color}"><strong>{label}</strong></p>\n\n'
        f"{body.strip()}\n\n"
        "</blockquote>"
    )


# ---------------------------------------------------------------------------
# Concentric rings figure
# ---------------------------------------------------------------------------

_RINGS_DEFAULTS: dict[str, Any] = {
    "title": "",
    "caption": "",
    # Outer to inner. Each ring: label, fill, text colour.
    "rings": [
        {"label": "Outer", "fill": "#e5e7eb", "text": "#1f2937"},
        {"label": "Middle", "fill": "#1f4e79", "text": "#ffffff"},
        {"label": "Inner", "fill": "#9dbbd8", "text": "#1f2937"},
        {"label": "Core", "fill": "#dbe7f3", "text": "#1f2937"},
    ],
    "interior": "#f3f6fa",
    "centre": {"label": "Centre", "fill": "#1f2937", "text": "#ffffff"},
    "satellites": [],
    "satellite_text": "#1f2937",
    "font": "Arial, Helvetica, sans-serif",
}


FIGURES: dict[str, Any] = {}  # filled below, after the generators are defined


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and len(trial) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _svg_text(x: float, y: float, lines: list[str], size: float, fill: str, weight: int) -> str:
    leading = size * 1.2
    top = y - (len(lines) - 1) * leading / 2
    spans = "".join(
        f'<tspan x="{x:.1f}" y="{top + i * leading:.1f}">{html.escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<text text-anchor="middle" dominant-baseline="central" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}">{spans}</text>'
    )


def framework_rings_svg(options: dict[str, Any] | None = None) -> str:
    """Concentric-ring diagram as a standalone SVG string.

    Rings are listed outer to inner; the interior disc, centre circle and up to
    three satellite labels are drawn inside the last ring.
    """
    opts: dict[str, Any] = {**_RINGS_DEFAULTS, **(options or {})}
    rings: list[dict[str, str]] = opts["rings"]
    centre: dict[str, str] = {**_RINGS_DEFAULTS["centre"], **(opts.get("centre") or {})}
    satellites: list[str] = list(opts.get("satellites") or [])
    font = html.escape(str(opts["font"]), quote=True)

    size = 480
    cx = size / 2
    title_h = 34
    cy = title_h + 240
    outer = 238.0
    # Bands: slimmer outer ring, equal thereafter, interior disc inside the last.
    widths = [28.0] + [36.0] * (len(rings) - 1)
    radii: list[tuple[float, float]] = []
    r = outer
    for w in widths:
        radii.append((r, r - w))
        r -= w
    interior_r = r

    parts: list[str] = []
    for ring, (r_out, _r_in) in zip(rings, radii):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r_out}" fill="{ring["fill"]}"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{interior_r}" fill="{opts["interior"]}"/>')

    for ring, (r_out, r_in) in zip(rings, radii):
        y = cy - (r_out + r_in) / 2
        parts.append(_svg_text(cx, y, [ring["label"]], 11.5, ring["text"], 700))

    centre_r = interior_r * 0.44
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{centre_r:.1f}" fill="{centre["fill"]}"/>')
    parts.append(_svg_text(cx, cy, _wrap(centre["label"], 12), 11.5, centre["text"], 700))

    if satellites:
        import math

        # Spread satellites over the lower arc, clear of the centre circle.
        angles = {1: [90], 2: [145, 35], 3: [150, 30, 90]}.get(len(satellites), [])
        sat_r = interior_r * 0.76
        for label, angle in zip(satellites, angles):
            x = cx + sat_r * math.cos(math.radians(angle)) * (1.12 if angle != 90 else 1)
            y = cy + sat_r * math.sin(math.radians(angle))
            parts.append(_svg_text(x, y, _wrap(label, 14), 9.5, opts["satellite_text"], 600))

    title = str(opts.get("title") or "")
    title_svg = _svg_text(cx, 14, [title], 13, "#254440", 700) if title else ""
    height = cy + outer + 6
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {height:.0f}" '
        f'role="img" aria-label="{html.escape(title or "Ring diagram", quote=True)}" '
        f'font-family="{font}">{title_svg}{"".join(parts)}</svg>'
    )


_CAPTION_RE = re.compile(r"^(Figure|Table)\s+([A-Za-z]?\.?\d[\d.]*)\s*[:.]\s*(.+?)\s*$")


def caption_id(kind: str, label: str) -> str:
    return f"cap-{kind.lower()}-" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def _caption_p(caption: str, kind_class: str) -> str:
    match = _CAPTION_RE.match(caption)
    anchor = f' id="{caption_id(match.group(1), match.group(2))}"' if match else ""
    return f'<p class="{kind_class}"{anchor} style="text-align:center">{html.escape(caption)}</p>'


def _figure_html(svg: str, caption: str, fmt: str) -> str:
    cap = _caption_p(caption, "figure-caption") if caption else ""
    if fmt == "docx":
        token = base64.urlsafe_b64encode(svg.encode("utf-8")).decode("ascii")
        return f'<p style="text-align:center"><img src="mddocsvg:{token}" width="100%"></p>\n{cap}'
    return f'<figure class="mddoc-figure">{svg}</figure>\n{cap}'


def decode_svg_ref(src: str) -> str | None:
    """Return the SVG source for a ``mddocsvg:`` image reference, else None."""
    if not src.startswith("mddocsvg:"):
        return None
    return base64.urlsafe_b64decode(src[len("mddocsvg:") :].encode("ascii")).decode("utf-8")


def _parse_options(body: str) -> dict[str, Any]:
    if not body.strip():
        return {}
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        logger.warning("Component options are not valid YAML: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


from .diagrams import cards_svg, flow_svg, matrix_svg, process_svg, tiers_svg  # noqa: E402

FIGURES.update(
    {
        "rings": framework_rings_svg,
        "tiers": tiers_svg,
        "cards": cards_svg,
        "matrix": matrix_svg,
        "process": process_svg,
        "flow": flow_svg,
    }
)

# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


LIST_OF = {"figures": "Figure", "tables": "Table"}
WORD_LIST_MARKER = "@@MDDOC_LIST_{}@@"


def _collect_captions(text: str) -> dict[str, list[tuple[str, str, str]]]:
    """Captions in document order: kind -> [(id, label, caption text)]."""
    found: dict[str, list[tuple[str, str, str]]] = {"Figure": [], "Table": []}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        opened = _FENCE_OPEN_RE.match(lines[i])
        if opened and opened.group(1).lower() in FIGURES:
            end = next(
                (j for j in range(i + 1, len(lines)) if _FENCE_CLOSE_RE.match(lines[j])), len(lines)
            )
            caption = str(_parse_options("\n".join(lines[i + 1 : end])).get("caption", ""))
            m = _CAPTION_RE.match(caption)
            if m:
                found["Figure"].append((caption_id("Figure", m.group(2)), m.group(2), caption))
            i = end + 1
            continue
        m = _CAPTION_RE.match(lines[i].strip())
        if m and m.group(1) == "Table" and not lines[i].startswith(("|", "    ")):
            found["Table"].append((caption_id("Table", m.group(2)), m.group(2), lines[i].strip()))
        i += 1
    return found


def _list_of_html(kind: str, captions: dict[str, list[tuple[str, str, str]]], fmt: str) -> str:
    if fmt == "docx":
        return f"<p>{WORD_LIST_MARKER.format(kind.upper())}</p>"
    items = "".join(
        f'<li><a href="#{cid}">{html.escape(text)}</a></li>' for cid, _label, text in captions[kind]
    )
    return f'<div class="list-of"><ul>{items}</ul></div>' if items else ""


def _expand(text: str, fmt: str) -> str:
    captions = _collect_captions(text)
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        opened = _FENCE_OPEN_RE.match(lines[i])
        if not opened:
            m = _CAPTION_RE.match(lines[i].strip())
            if m and m.group(1) == "Table" and not lines[i].startswith(("|", "    ")):
                out.append("")
                out.append(
                    _caption_p(lines[i].strip(), "table-caption").replace(
                        ' style="text-align:center"', ""
                    )
                )
                out.append("")
            else:
                out.append(lines[i])
            i += 1
            continue
        name = opened.group(1).lower()
        end = next((j for j in range(i + 1, len(lines)) if _FENCE_CLOSE_RE.match(lines[j])), None)
        if end is None:
            logger.warning(
                "Unclosed '::: %s' block; treating the rest of the file as its body", name
            )
            end = len(lines)
        body = "\n".join(lines[i + 1 : end])
        consumed = end - i + 1
        if name in CALLOUTS:
            block = _callout_html(name, body)
        elif name == "list-of":
            kind = LIST_OF.get(body.strip().lower())
            if kind is None:
                logger.warning("'::: list-of' needs 'figures' or 'tables'; got %r", body.strip())
                out.extend(lines[i : min(end + 1, len(lines))])
                i = end + 1
                continue
            block = _list_of_html(kind, captions, fmt)
        elif name in FIGURES:
            opts = _parse_options(body)
            block = _figure_html(FIGURES[name](opts), str(opts.get("caption", "")), fmt)
        else:
            logger.warning("Unknown component '::: %s'; leaving it as written", name)
            out.extend(lines[i : min(end + 1, len(lines))])
            i = end + 1
            continue
        # Keep line numbers stable for diagnostics.
        out.append("")
        out.append(block)
        out.append("")
        out.extend([""] * (consumed - 1))
        i = end + 1
    return "\n".join(out)


def expand_components(markdown: str, fmt: str = "pdf") -> str:
    """Expand ``::: name`` blocks outside code fences. *fmt* is ``pdf`` or ``docx``."""
    if ":::" not in markdown:
        return markdown
    return transform_outside_code(markdown, lambda body: _expand(body, fmt))
