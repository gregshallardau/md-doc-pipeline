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
