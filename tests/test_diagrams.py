"""Tests for the diagram components: tiers, cards, matrix, process, flow, lists."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from md_doc import diagrams
from md_doc.components import expand_components


def _contrast(fg: str, bg: str) -> float:
    def lum(h: str) -> float:
        h = h.lstrip("#")
        chans = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        chans = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
        return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]

    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


GENERATORS = {
    "tiers": diagrams.tiers_svg,
    "cards": diagrams.cards_svg,
    "matrix": diagrams.matrix_svg,
    "process": diagrams.process_svg,
    "flow": diagrams.flow_svg,
}


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_defaults_render_valid_svg(name: str) -> None:
    svg = GENERATORS[name]()
    root = ET.fromstring(svg)  # well-formed XML
    assert root.tag.endswith("svg") and root.get("viewBox")
    assert root.get("role") == "img" and root.get("aria-label")


def test_tiers_use_supplied_text_and_escape_markup() -> None:
    svg = diagrams.tiers_svg(
        {"tiers": [{"title": "A & B", "subtitle": "<sub>", "description": "Desc"}], "title": "T"}
    )
    assert "A &amp; B" in svg.upper().replace("&AMP;", "&amp;") or "A &amp; B" in svg
    assert "&lt;sub&gt;" in svg and "<sub>" not in svg


def test_cards_and_banner() -> None:
    svg = diagrams.cards_svg(
        {
            "cards": [{"title": "One", "items": ["x", "y"]}, {"title": "Two", "items": ["z"]}],
            "banner": {"title": "Result", "subtitle": "Sub"},
        }
    )
    for text in ("One", "Two", "RESULT", "Sub", "x", "z"):
        assert text in svg


def test_matrix_colours_each_cell_by_rating() -> None:
    svg = diagrams.matrix_svg(
        {
            "columns": ["a", "b"],
            "rows": ["r1"],
            "grid": [["Low", "Extreme"]],
            "levels": {"Low": {"fill": "#00ff00", "text": "#000000"}},
        }
    )
    assert "#00ff00" in svg and "Extreme" in svg


def test_process_shows_steps_and_side_panels() -> None:
    svg = diagrams.process_svg(
        {"steps": ["One", "Two"], "left": "Left panel", "right": "Right panel", "footer": "Foot"}
    )
    for text in ("One", "Two", "Left", "Right", "Foot"):
        assert text in svg


def test_flow_routes_edges_and_loops() -> None:
    svg = diagrams.flow_svg(
        {
            "nodes": [
                {"id": "a", "label": "Start", "at": [0, 0]},
                {"id": "b", "label": "Decide", "shape": "diamond", "at": [0, 1]},
                {"id": "c", "label": "Stop", "shape": "pill", "at": [1, 2]},
            ],
            "edges": [
                ["a", "b"],
                {"from": "b", "to": "c", "label": "No", "exit": "right"},
                {"from": "c", "to": "a", "via": "right"},
            ],
        }
    )
    ET.fromstring(svg)
    assert svg.count("<path") >= 6  # three edges, each a line plus an arrowhead
    assert "No" in svg and "<polygon" in svg


def test_flow_ignores_edges_to_unknown_nodes() -> None:
    svg = diagrams.flow_svg(
        {"nodes": [{"id": "a", "label": "Only", "at": [0, 0]}], "edges": [["a", "ghost"]]}
    )
    ET.fromstring(svg)


def test_default_palettes_meet_wcag_aa() -> None:
    cards = diagrams.CARDS_DEFAULTS
    for colors in cards["card_colors"]:
        assert _contrast(cards["text"], colors["fill"]) >= 4.5
        assert _contrast(colors["accent"], colors["fill"]) >= 4.5
    assert _contrast(cards["banner"]["text"], cards["banner"]["fill"]) >= 4.5
    for tier in diagrams.TIERS_DEFAULTS["tiers"]:
        assert _contrast(diagrams.TIERS_DEFAULTS["text"], tier["fill"]) >= 4.5
        assert _contrast(diagrams.TIERS_DEFAULTS["muted"], tier["fill"]) >= 4.5
        assert _contrast("#ffffff", tier["badge"]) >= 4.5
        assert _contrast(tier["accent"], tier["fill"]) >= 4.5
    for level in diagrams.MATRIX_DEFAULTS["levels"].values():
        assert _contrast(level["text"], level["fill"]) >= 4.5
    flow = diagrams.FLOW_DEFAULTS
    assert _contrast(flow["text"], flow["fill"]) >= 4.5
    assert _contrast(flow["text"], flow["decision_fill"]) >= 4.5


def test_components_expand_all_figure_kinds() -> None:
    for name in GENERATORS:
        out = expand_components(f"::: {name}\ncaption: 'Figure 1.1: Test'\n:::\n")
        assert "<svg" in out and "Figure 1.1: Test" in out and 'id="cap-figure-1-1"' in out


def test_table_captions_and_lists() -> None:
    source = (
        "::: list-of\nfigures\n:::\n\n::: list-of\ntables\n:::\n\n"
        "::: tiers\ncaption: 'Figure 1.1: Structure'\n:::\n\n"
        "Table 8.1: Support levels\n\n| A |\n|---|\n| 1 |\n"
    )
    out = expand_components(source)
    assert 'href="#cap-figure-1-1"' in out and 'href="#cap-table-8-1"' in out
    assert 'class="table-caption" id="cap-table-8-1"' in out
    assert out.count('class="list-of"') == 2


def test_list_of_needs_a_valid_kind() -> None:
    source = "::: list-of\nwidgets\n:::\n"
    assert expand_components(source) == source


def test_table_caption_inside_a_table_or_code_is_left_alone() -> None:
    source = "```\nTable 1: not a caption\n```\n"
    assert expand_components(source) == source


def test_flow_groups_draw_labelled_frames_behind_nodes_and_edges() -> None:
    svg = diagrams.flow_svg(
        {
            "nodes": [
                {"id": "g1", "label": "Policy", "at": [0, 0]},
                {"id": "g2", "label": "Regulation", "at": [0, 1]},
                {"id": "i1", "label": "Compliance", "at": [1, 1]},
            ],
            "edges": [["g1", "g2"], ["g2", "i1", "regulates"]],
            "groups": [
                {
                    "label": "Government",
                    "nodes": ["g1", "g2"],
                    "fill": "#dbeafe",
                    "stroke": "#1d4ed8",
                    "text": "#1e3a8a",
                },
                {"label": "Industry", "nodes": ["i1", "missing"]},
            ],
        }
    )
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    rects = root.findall(f"{ns}rect")
    gov = next(r for r in rects if r.get("fill") == "#dbeafe")
    assert gov.get("stroke") == "#1d4ed8" and gov.get("rx") == "10"
    # The frame encloses both of its nodes, with room for the label above them
    x0, y0 = float(gov.get("x")), float(gov.get("y"))
    x1, y1 = x0 + float(gov.get("width")), y0 + float(gov.get("height"))
    nodes = [r for r in rects if r.get("fill") == diagrams.FLOW_DEFAULTS["fill"]]
    assert len(nodes) == 3
    for node in nodes[:2]:
        nx, ny = float(node.get("x")), float(node.get("y"))
        assert x0 < nx and y0 + 18 < ny
        assert nx + float(node.get("width")) < x1 and ny + float(node.get("height")) < y1
    labels = [t for t in root.iter(f"{ns}text") if "".join(t.itertext()) == "Government"]
    assert labels and labels[0].get("fill") == "#1e3a8a"
    # Frames first: nodes and arrows are drawn over them, never hidden
    assert svg.index('fill="#dbeafe"') < svg.index(diagrams.FLOW_DEFAULTS["fill"])
    assert svg.index('fill="#dbeafe"') < svg.index("<path")
    # Unknown node ids are skipped; the default group colours apply
    assert diagrams.GROUP_DEFAULTS["fill"] in svg
    # Everything fits in the viewBox
    vb = [float(v) for v in root.get("viewBox").split()]
    assert y0 >= 0 and y1 <= vb[3] and x1 <= vb[2]


def test_flow_without_groups_is_unchanged() -> None:
    opts = {"nodes": [{"id": "a", "label": "A", "at": [0, 0]}], "edges": []}
    assert diagrams.flow_svg(opts) == diagrams.flow_svg({**opts, "groups": []})


def _text_rows(svg: str) -> dict[str, float]:
    """First y of each text line (tspan) in the SVG, keyed by its text."""
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    return {(t.text or ""): float(t.get("y")) for t in root.iter(f"{ns}tspan")}


def test_card_title_that_wraps_pushes_the_subtitle_down() -> None:
    opts = {
        "cards": [
            {
                "title": "Untraceable knowledge",
                "subtitle": "Decisions live in inboxes",
                "items": ["Lost context"],
            },
            {"title": "Disconnected systems", "subtitle": "Own records", "items": ["Re-keying"]},
            {"title": "Handling a complaint", "subtitle": "Weeks", "items": ["Delays"]},
            {"title": "Short", "subtitle": "Sub", "items": ["One"]},
        ]
    }
    svg = diagrams.cards_svg(opts)
    ys = _text_rows(svg)
    lead = 11 * 1.25
    assert ys["knowledge"] > ys["Untraceable"]  # the title wrapped
    # The subtitle starts below the last title line, never on top of it
    subtitle = next(y for text, y in ys.items() if text.startswith("Decisions"))
    assert subtitle - ys["knowledge"] >= lead
    assert ys["Lost context"] > subtitle
    # The cards grew to fit the longest
    root = ET.fromstring(svg)
    heights = {
        float(r.get("height"))
        for r in root.iter("{http://www.w3.org/2000/svg}rect")
        if r.get("rx") == "10"
    }
    single = diagrams.cards_svg(
        {"cards": [{"title": "A", "subtitle": "Decisions live in inboxes", "items": ["x"]}]}
    )
    single_h = {
        float(r.get("height"))
        for r in ET.fromstring(single).iter("{http://www.w3.org/2000/svg}rect")
        if r.get("rx") == "10"
    }
    assert len(heights) == 1 and heights.pop() > single_h.pop()


def test_six_tiers_keep_a_minimum_font_and_grow_instead() -> None:
    tiers = [
        {"title": f"Tier {i}", "subtitle": f"Level {i}", "description": "Short text."}
        for i in range(6)
    ]
    tiers[2]["description"] = " ".join(["A long description that wraps over several lines."] * 3)
    tiers[4]["subtitle"] = ""
    svg = diagrams.tiers_svg({"tiers": tiers})
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    sizes = [float(t.get("font-size")) for t in root.iter(f"{ns}text")]
    assert min(sizes) >= diagrams.TIERS_MIN_FONT
    bands = [r for r in root.iter(f"{ns}rect") if r.get("rx") == "14"]
    assert len(bands) == 6
    heights = [float(r.get("height")) for r in bands]
    assert heights[2] > heights[0]  # the long description made its tier taller
    # Every description line sits inside its tier
    band = bands[2]
    top, bottom = float(band.get("y")), float(band.get("y")) + float(band.get("height"))
    desc = [t for t in root.iter(f"{ns}text") if "wraps" in "".join(t.itertext())]
    for span in desc[0].iter(f"{ns}tspan"):
        assert top < float(span.get("y")) < bottom
    # The last tier keeps a usable width
    assert float(bands[-1].get("width")) > 500
    # No subtitle: the title is centred on its tier
    t4 = bands[4]
    centre = float(t4.get("y")) + float(t4.get("height")) / 2
    assert abs(_text_rows(svg)["TIER 4"] - centre) < 1
