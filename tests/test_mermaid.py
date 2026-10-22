"""Smoke + regression tests for the pure-Python Mermaid renderer."""

from __future__ import annotations

import re

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


def test_office_diagram_uses_natural_size_like_pdf():
    from md_doc.builders._assets import _render_mermaid_to_images

    for src in ("flowchart LR\n A --&gt; B", "gauge\n value 42"):
        html, images = _render_mermaid_to_images(
            f'<pre><code class="language-mermaid">{src}</code></pre>', None
        )
        natural = m.svg_natural_width(m.render_to_svg(src.replace("&gt;", ">")))
        assert images and f'width="{int(natural)}"' in html


def test_pdf_wrapper_keeps_natural_size_and_shrinks_to_fit():
    html = m.process_html(
        '<pre><code class="language-mermaid">flowchart LR\n A --&gt; B</code></pre>'
    )
    natural = m.svg_natural_width(html)
    assert f"width:{natural:.0f}px;max-width:100%" in html


def test_diagram_text_uses_one_type_scale():
    sizes = set()
    for src in (
        "flowchart TD\n A[One] --> B[Two]",
        "sequenceDiagram\n A->>B: hi",
        'pie\n "A" : 1\n "B" : 2',
    ):
        sizes |= set(re.findall(r'font-size="([\d.]+)"', m.render_to_svg(src)))
    assert sizes <= {"9.5", "10", "10.5", "11", "11.5", "12", "13", "13.5", "22", "30"}


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
    bars = [
        (float(x), float(w))
        for x, w in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)" height="12"', svg)
    ]
    assert len(bars) == 3
    (ax, aw), (bx, bw), (cx, _cw) = bars
    assert bw == pytest.approx(2 * aw, rel=0.02)  # 20d is twice 10d
    assert bx == pytest.approx(ax + aw, abs=0.2)  # B starts when A ends
    assert cx == pytest.approx(bx + bw, abs=0.2)
    assert ">5 Jan<" in svg and ">12 Jan<" in svg  # weekly ticks fall on Mondays


def test_gantt_status_tags_are_not_task_ids():
    gc = m.parse_gantt("gantt\n Build : done, b1, 2026-01-01, 5d")
    assert gc.tasks[0].task_id == "b1" and gc.tasks[0].duration == "5d"


def test_state_diagram_markers_and_reciprocal_edges_do_not_collide():
    sd = m.parse_state(
        "stateDiagram-v2\n [*] --> Idle\n Idle --> Run : go\n Run --> Idle : stop\n Run --> [*]"
    )
    svg = m.render_state_svg(sd)
    drawn = svg.split("</defs>")[1]
    assert drawn.count("<circle") == 4  # filled start dot + end marker (3 circles)
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


def _edges(src):
    return [(e.src, e.dst, e.label, e.style, e.head, e.tail) for e in m.parse(src).edges]


def test_text_labelled_edges_keep_their_nodes():
    assert _edges(
        "flowchart TD\n A -- some text --> B\n B -. dotted label .-> C\n C == thick ==> D"
    ) == [
        ("A", "B", "some text", "solid", "arrow", "none"),
        ("B", "C", "dotted label", "dotted", "arrow", "none"),
        ("C", "D", "thick", "thick", "arrow", "none"),
    ]


def test_circle_cross_and_bidirectional_edges():
    assert _edges("flowchart TD\n A --o B\n B --x C\n C <--> D\n D o--o E\n E --- F") == [
        ("A", "B", "", "solid", "circle", "none"),
        ("B", "C", "", "solid", "cross", "none"),
        ("C", "D", "", "solid", "arrow", "arrow"),
        ("D", "E", "", "solid", "circle", "circle"),
        ("E", "F", "", "solid", "none", "none"),
    ]


def test_operators_inside_labels_and_names_are_not_edges():
    edges = _edges('flowchart TD\n A["a --> b"] --> B\n C-->|yes (really)|D\n Box-->I')
    assert [(e[0], e[1], e[2]) for e in edges] == [
        ("A", "B", ""),
        ("C", "D", "yes (really)"),
        ("Box", "I", ""),
    ]


def test_ampersand_fans_out_and_in():
    assert [(e[0], e[1]) for e in _edges("flowchart TD\n A --> B & C\n B & C --> D")] == [
        ("A", "B"),
        ("A", "C"),
        ("B", "D"),
        ("C", "D"),
    ]


def test_classdef_style_and_linkstyle_are_applied():
    fc = m.parse(
        "flowchart TD\n A[Ok]:::good --> B[Bad]:::bad\n"
        " classDef good fill:#d4edda,stroke:#28a745\n classDef bad fill:#f8d7da\n"
        " style A stroke-width:4px\n linkStyle 0 stroke:#dc3545"
    )
    assert fc.nodes["A"].css == {"fill": "#d4edda", "stroke": "#28a745", "stroke-width": "4px"}
    assert fc.nodes["B"].css == {"fill": "#f8d7da"}
    assert fc.edges[0].css == {"stroke": "#dc3545"}
    svg = m.render_svg(fc)
    assert 'fill="#d4edda"' in svg and 'stroke="#dc3545"' in svg
    assert 'id="arr-dc3545"' in svg  # arrowhead matches the edge colour


def test_subgraph_heading_forms_and_nesting():
    fc = m.parse(
        'flowchart LR\n subgraph one [First]\n A --> B\n subgraph inner["In ner"]\n X\n end\n end\n'
        ' subgraph "Quoted Title"\n C --> D\n end\n B --> C'
    )
    by_id = {sg.id: sg for sg in fc.subgraphs}
    assert by_id["one"].label == "First" and by_id["one"].children == ["inner"]
    assert by_id["inner"].node_ids == ["X"]
    assert by_id["Quoted_Title"].label == "Quoted Title"
    m.layout(fc)
    outer, inner = by_id["one"], by_id["inner"]
    assert outer.x <= inner.x and outer.x + outer.w >= inner.x + inner.w  # frame wraps child


def test_extra_shapes_parse_and_render():
    fc = m.parse("flowchart TD\n A>Flag] --> B[/Para/]\n B --> C[\\Alt\\]\n C --> D[/Trap\\]")
    assert [fc.nodes[n].shape for n in "ABCD"] == [
        "flag",
        "parallelogram",
        "parallelogram_alt",
        "trapezoid",
    ]
    assert m.render_svg(fc).count("<polygon") >= 4


def test_front_matter_and_init_directives_are_ignored():
    for pre in ("---\ntitle: T\n---\n", "%%{init: {'theme':'forest'}}%%\n"):
        assert m._detect_diagram_type(pre + "sequenceDiagram\n A->>B: hi") == "sequence"
        assert "<svg" in m.render_to_svg(pre + "flowchart TD\n A --> B")


@pytest.mark.parametrize("kind", ["classDiagram", "journey", "gitGraph"])
def test_unsupported_diagram_types_fail_cleanly(kind):
    with pytest.raises(m.UnsupportedDiagramError):
        m.render_to_svg(f"{kind}\n  anything")
    html = f'<pre><code class="language-mermaid">{kind}\n x</code></pre>'
    assert m.process_html(html) == html  # the PDF path keeps the code block


def test_edge_corners_are_rounded():
    svg = m.render_to_svg("flowchart TD\n A --> B\n A --> C")
    assert " Q " in svg


def test_sequence_aliases_actors_notes_blocks_and_activation():
    sd = m.parse_sequence(
        "sequenceDiagram\n autonumber\n actor C as Customer\n participant W as Web app\n"
        " C->>+W: Checkout\n alt ok\n W-->>C: Done\n else failed\n W--xC: Error\n end\n"
        " Note over C,W: idempotent\n W-)C: async\n W-->>-C: bye"
    )
    assert sd.participants == ["C", "W"]
    assert sd.labels == {"C": "Customer", "W": "Web app"} and sd.actors == {"C"}
    assert sd.autonumber
    kinds = [type(e).__name__ for e in sd.events]
    assert kinds.count("SeqBlock") == 3 and "SeqNote" in kinds
    assert [(x.arrow, x.activate) for x in sd.messages] == [
        ("->>", "+"),
        ("-->>", ""),
        ("--x", ""),
        ("-)", ""),
        ("-->>", "-"),
    ]
    svg = m.render_sequence_svg(sd)
    assert "Customer" in svg and "Web app" in svg and ">alt<" in svg and "[failed]" in svg
    assert "idempotent" in svg and "url(#seq-cross)" in svg and "url(#seq-open)" in svg


def test_gauge_accepts_colon_syntax():
    gc = m.parse_gauge("gauge\n title CSAT\n value: 72\n min: 0\n max: 100")
    assert (gc.title, gc.value, gc.min_val, gc.max_val) == ("CSAT", 72, 0, 100)
    assert ">72<" in m.render_gauge_svg(gc)


def test_pie_title_and_show_data_on_header_line():
    pc = m.parse_pie('pie showData title Pets\n "Dogs" : 386\n "Cats" : 85')
    assert pc.title == "Pets" and pc.show_data
    svg = m.render_pie_svg(pc)
    assert ">Pets<" in svg and "386" in svg


def test_pie_uses_validated_palette_in_order_and_folds_tail():
    slices = "".join(f'\n "S{i}" : {20 - i}' for i in range(10))
    svg = m.render_pie_svg(m.parse_pie("pie" + slices))
    fills = re.findall(r'<path d="[^"]+" fill="(#[0-9a-f]{6})"', svg)
    assert fills[:7] == m._CATEGORICAL[:7] and fills[-1] == m._OTHER
    assert ">Other<" in svg


def test_bar_axis_uses_round_ticks():
    assert m._nice_ticks(0, 190) == [0, 50, 100, 150, 200]
    assert m._nice_ticks(0, 7.3) == [0, 2, 4, 6, 8]
    svg = m.render_bar_svg(m.parse_bar("xychart-beta\n x-axis [Q1, Q2]\n bar [120, 190]"))
    assert ">150<" in svg and ">152<" not in svg
    assert m._fmt_num(1250) == "1.3K" and m._fmt_num(2_500_000) == "2.5M"


def test_er_keys_and_cardinality():
    erd = m.parse_er(
        "erDiagram\n CUSTOMER ||--o{ ORDER : places\n ORDER }|..|| SHIP : uses\n"
        " ORDER {\n int id PK\n string customer_id FK\n }"
    )
    assert erd.entities["ORDER"].keys == ["PK", "FK"]
    a, b = erd.relations
    assert (a.card_a, a.card_b, a.style) == ("one", "zero_many", "solid")
    assert (b.card_a, b.card_b, b.style) == ("one_many", "one", "dotted")
    svg = m.render_er_svg(erd)
    assert "url(#er-zero_many)" in svg and "url(#er-one-s)" in svg and ">PK<" in svg


def test_timeline_sections_and_continuation_lines():
    tl = m.parse_timeline(
        "timeline\n section Early\n 2021 : Founded\n : Seed\n section Later\n 2023 : A"
    )
    assert [(e.period, e.events, e.section) for e in tl.entries] == [
        ("2021", ["Founded", "Seed"], "Early"),
        ("2023", ["A"], "Later"),
    ]


def test_mindmap_strips_shapes_and_balances_sides():
    root = m.parse_mindmap(
        "mindmap\n  root((Plan))\n    a[Alpha]\n    b(Beta)\n    c{{Gamma}}\n    d))Delta(("
    )
    assert root.label == "Plan"
    assert [c.label for c in root.children] == ["Alpha", "Beta", "Gamma", "Delta"]
    svg = m.render_mindmap_svg(root)
    xs = [float(x) for x in re.findall(r'<rect x="(-?[\d.]+)"', svg)]
    assert min(xs) < 0 < max(xs) or len(set(xs)) > 2  # branches on both sides of the root


def test_structural_diagrams_follow_the_brand_not_a_rainbow():
    theme = {"primary": "#7a1f5c", "accent": "#0f766e"}
    svg = m.render_to_svg("flowchart TD\n A([Start]) --> B[Step] --> C{Ok?}", theme)
    assert 'fill="#7a1f5c"' in svg  # terminal uses the brand primary
    assert not any(c in svg for c in m._CATEGORICAL)
