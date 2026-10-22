"""Smoke + regression tests for the pure-Python Mermaid renderer."""

from __future__ import annotations

import pytest

from md_doc import mermaid as m

_SAMPLES = {
    "flowchart": "flowchart LR\n  A --> B\n  B --> C",
    "pie": 'pie\n"A" : 30\n"B" : 70',
    "donut": 'donut\n"A" : 30\n"B" : 70',
    "bar": 'bar\n"Jan" : 10\n"Feb" : 20',
    "gauge": "gauge\n  value: 42\n  min: 0\n  max: 100",
    "sequence": "sequenceDiagram\n  Alice->>Bob: Hi\n  Bob-->>Alice: Hello",
    "timeline": "timeline\n  2021 : Founded\n  2022 : Launched",
    "gantt": "gantt\n  section S\n  Task A : a1, 2024-01-01, 3d",
    "mindmap": "mindmap\n  root\n    branch1\n    branch2",
    "er": "erDiagram\n  CUSTOMER ||--o{ ORDER : places",
    "state": "stateDiagram-v2\n  [*] --> Idle\n  Idle --> Running\n  Running --> [*]",
}


@pytest.mark.parametrize("name,source", list(_SAMPLES.items()))
def test_render_to_svg_smoke(name, source):
    svg = m.render_to_svg(source)  # some types wrap the <svg> in a sizing <div>
    assert "<svg" in svg and "</svg>" in svg
    assert len(svg) > 100  # produced real content, not an empty shell


def test_detect_diagram_type():
    assert m._detect_diagram_type('pie\n"x": 1') == "pie"
    assert m._detect_diagram_type("erDiagram\n A ||--|| B : x") == "er"
    assert m._detect_diagram_type("flowchart TD\n A-->B") == "flowchart"


# ── regression tests for the code-review fixes ──────────────────────────────


def test_er_attributes_are_parsed():
    erd = m.parse_er(
        "erDiagram\n"
        "  CUSTOMER {\n    string name\n    int age\n  }\n"
        "  CUSTOMER ||--o{ ORDER : places\n"
    )
    assert erd.entities["CUSTOMER"].attributes == ["string name", "int age"]


def test_full_circle_pie_renders_a_circle():
    svg = m.render_pie_svg(m.parse_pie('pie\n"Done" : 100'))
    assert "<circle" in svg


def test_full_circle_donut_punches_hole():
    svg = m.render_donut_svg(m.parse_pie('pie\n"Done" : 100'))
    assert svg.count("<circle") >= 2


def test_flowchart_unquoted_labels_register_nodes():
    # Unquoted labels (A[Plan]) are the common Mermaid form and must register
    # nodes with the right shape, not fall through to raw tokens (which crashed
    # layout with a KeyError).
    fc = m.parse("flowchart LR\n  A[Plan] --> B[Build]\n  B --> C[Ship]")
    assert set(fc.nodes) == {"A", "B", "C"}
    assert {(e.src, e.dst) for e in fc.edges} == {("A", "B"), ("B", "C")}
    assert m.render_to_svg("flowchart LR\n  A[Plan] --> B[Build]\n  B --> C[Ship]")


def test_flowchart_all_unquoted_shapes():
    src = (
        "flowchart TD\n R[rect]\n D{diamond}\n S([stadium])\n Rn(rounded)\n"
        " Ci((circle))\n Cy[(cyl)]\n Hx{{hex}}\n Sr[[sub]]\n R-->D"
    )
    fc = m.parse(src)
    shapes = {fc.nodes[n].shape for n in fc.nodes}
    assert shapes == {
        "rect",
        "diamond",
        "stadium",
        "rounded",
        "circle",
        "cylinder",
        "hexagon",
        "subroutine",
    }


def test_subgraph_edge_members_assigned():
    fc = m.parse("flowchart LR\n  subgraph G1\n    A --> B\n  end")
    assert set(fc.subgraphs[0].node_ids) == {"A", "B"}


def test_escape_helper():
    assert m._escape("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_labels_are_xml_escaped_in_output():
    # A slice label with special chars must be escaped in the rendered SVG.
    svg = m.render_pie_svg(m.parse_pie('pie\n"A & B" : 100'))
    assert "A &amp; B" in svg
    assert "A & B" not in svg


def test_sequence_arrows_do_not_become_participant_names():
    diagram = m.parse_sequence("sequenceDiagram\nAlice->>Bob: Request\nBob-->>Alice: Reply")
    assert diagram.participants == ["Alice", "Bob"]
    assert [(message.src, message.dst, message.arrow) for message in diagram.messages] == [
        ("Alice", "Bob", "->>"),
        ("Bob", "Alice", "-->>"),
    ]


def test_gauge_wrapper_rasterizes_for_word():
    pytest.importorskip("cairosvg")
    from md_doc.builders._assets import _svg_to_png

    result = _svg_to_png(m.render_to_svg("gauge\nvalue 42\nmax 100"))
    assert result is not None and result[0].startswith(b"\x89PNG")


def test_office_diagram_preserves_pdf_sizing():
    from md_doc.builders._assets import _render_mermaid_to_images

    full, images = _render_mermaid_to_images(
        '<pre><code class="language-mermaid">flowchart LR\n A --&gt; B</code></pre>', None
    )
    assert images and 'width="100%"' in full
    gauge, images = _render_mermaid_to_images(
        '<pre><code class="language-mermaid">gauge\n value 42</code></pre>', None
    )
    assert images and 'width="280"' in gauge


def _overlaps(fc: m.Flowchart) -> list[tuple[str, str]]:
    nodes = list(fc.nodes.values())
    return [
        (a.id, b.id)
        for i, a in enumerate(nodes)
        for b in nodes[i + 1 :]
        if a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h
    ]


def test_td_flowchart_siblings_do_not_overlap():
    fc = m.parse("flowchart TD\n A --> B\n B -->|Yes| C\n B -->|No| D\n C --> E\n D --> E")
    m.layout(fc)
    assert _overlaps(fc) == []
    assert fc.nodes["C"].x != fc.nodes["D"].x
    # the shared child sits between its parents, and the root is centred over B
    c, d, e = fc.nodes["C"], fc.nodes["D"], fc.nodes["E"]
    assert c.x < e.x + e.w / 2 < d.x + d.w
    assert fc.nodes["A"].x + fc.nodes["A"].w / 2 == fc.nodes["B"].x + fc.nodes["B"].w / 2


def test_cycle_does_not_push_node_past_descendant():
    fc = m.parse("flowchart LR\n A --> B\n B --> C\n C --> B")
    levels = m._compute_levels(fc)
    assert levels["A"] < levels["B"] < levels["C"]


def test_gantt_bars_follow_dates_and_dependencies():
    gc = m.parse_gantt(
        "gantt\n section S\n A : a1, 2026-01-01, 10d\n B : after a1, 20d\n C : 2026-01-31, 10d"
    )
    _, spans = m._resolve_gantt(gc)
    assert spans == [(0.0, 10.0), (10.0, 30.0), (30.0, 40.0)]
    svg = m.render_gantt_svg(gc)
    assert svg.count("<rect") >= 4 and "01 Jan" in svg


def test_gantt_status_tags_are_not_task_ids():
    gc = m.parse_gantt("gantt\n Build : done, b1, 2026-01-01, 5d")
    assert gc.tasks[0].task_id == "b1" and gc.tasks[0].duration == "5d"


def test_state_diagram_markers_and_reciprocal_edges_do_not_collide():
    sd = m.parse_state(
        "stateDiagram-v2\n [*] --> Idle\n Idle --> Run : go\n Run --> Idle : stop\n Run --> [*]"
    )
    svg = m.render_state_svg(sd)
    assert svg.count("<circle") == 4  # filled start dot + end marker (3 circles)
    paths = [line for line in svg.splitlines() if line.startswith("<path") and "arr" in line]
    assert len(paths) == len(set(paths)) == 4  # go/stop edges take separate lanes


@pytest.mark.parametrize("direction", ["TD", "LR"])
def test_long_and_back_edges_route_around_nodes(direction):
    fc = m.parse(
        f"flowchart {direction}\n A --> B\n B --> C\n C --> D\n A --> D\n"
        " B --> E\n E --> D\n C --> B"
    )
    m.layout(fc)
    assert _overlaps(fc) == []
    assert fc.waypoints, "multi-level edges should reserve lanes"
    for pts in fc.waypoints.values():
        for px, py in pts:
            for n in fc.nodes.values():
                inside = n.x <= px <= n.x + n.w and n.y <= py <= n.y + n.h
                assert not inside, f"lane point ({px}, {py}) crosses node {n.id}"
    assert not any(n.shape == "dummy" for n in fc.nodes.values())
    svg = m.render_svg(fc)
    assert "__lane" not in svg


def test_lr_branches_are_ordered_without_overlap():
    fc = m.parse(
        "flowchart LR\n A --> B\n A --> C\n B --> D\n C --> D\n B --> E\n D --> F\n E --> F\n A --> F"
    )
    m.layout(fc)
    assert _overlaps(fc) == []


_DENSE = """flowchart TD
    A[Request] --> B{Auth?}
    B -->|ok| C[Load profile]
    B -->|fail| D[Reject]
    C --> E[Fetch orders]
    C --> F[Fetch prefs]
    C --> G[Fetch billing]
    E --> H[Merge]
    F --> H
    G --> H
    E --> I[Recommend]
    F --> I
    H --> J{Valid?}
    I --> J
    J -->|yes| K[Render]
    J -->|no| L[Fallback]
    L --> K
    K --> M[Respond]
    D --> M
    A --> M
    G --> K
    L --> C
"""


def test_dense_chart_ordering_reduces_crossings():
    fc = m.parse(_DENSE)
    m.layout(fc)
    assert fc.crossings <= 3
    assert fc.crossings < fc.crossings_unordered
    assert _overlaps(fc) == []


def test_edges_leaving_one_node_use_separate_ports():
    svg = m.render_to_svg("flowchart TD\n A --> B\n A --> C\n A --> D\n A --> E")
    starts = {
        line.split('d="M ')[1].split(" L")[0]
        for line in svg.splitlines()
        if line.startswith("<path") and "arr" in line
    }
    assert len(starts) == 4  # each edge leaves from its own point on the node


def test_branch_turns_are_staggered():
    svg = m.render_to_svg("flowchart TD\n A --> B\n A --> C\n A --> D\n A --> E")
    turns = {
        line.split(" L ")[1].split(",")[1]
        for line in svg.splitlines()
        if line.startswith("<path") and "arr" in line
    }
    assert len(turns) >= 3  # horizontal runs sit at different heights, not one trunk
