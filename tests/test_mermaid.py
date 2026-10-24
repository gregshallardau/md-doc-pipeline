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


def test_unsupported_diagram_types_fail_cleanly(monkeypatch):
    kind = "futureChart"
    monkeypatch.setattr(m, "_UNSUPPORTED_TYPES", (kind,))
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


def test_class_diagram_members_and_relations():
    cd = m.parse_class(
        "classDiagram\n class Animal {\n <<abstract>>\n +String name\n -int age\n"
        " +makeSound()* void\n +count()$ int\n }\n class Pond {\n +List~Duck~ ducks\n }\n"
        ' Animal <|-- Duck\n Fish --|> Animal\n Pond "1" *-- "many" Duck : contains\n'
        ' Duck ..> Fish : eats\n Swimmer <|.. Duck\n note for Pond "one pond"'
    )
    animal = cd.classes["Animal"]
    assert animal.annotation == "abstract"
    assert [
        (mb.visibility, mb.text, mb.method, mb.static, mb.abstract) for mb in animal.members
    ] == [
        ("+", "String name", False, False, False),
        ("-", "int age", False, False, False),
        ("+", "makeSound() void", True, False, True),
        ("+", "count() int", True, True, False),
    ]
    assert cd.classes["Pond"].members[0].text == "List<Duck> ducks"
    rels = [
        (r.a, r.b, r.end_a, r.end_b, r.dashed, r.label, r.card_a, r.card_b) for r in cd.relations
    ]
    assert ("Animal", "Duck", "inherit", "none", False, "", "", "") in rels
    assert ("Animal", "Fish", "inherit", "none", False, "", "", "") in rels  # parent laid out first
    assert ("Pond", "Duck", "composition", "none", False, "contains", "1", "many") in rels
    assert ("Duck", "Fish", "none", "arrow", True, "eats", "", "") in rels
    assert ("Swimmer", "Duck", "inherit", "none", True, "", "", "") in rels
    svg = m.render_class_svg(cd)
    for marker in ("cls-inherit-s", "cls-composition-s", "cls-arrow"):
        assert f"url(#{marker})" in svg
    assert "&#171;abstract&#187;" in svg or "«abstract»" in svg
    assert "one pond" in svg and ">many<" in svg
    animal_box = re.search(r">Animal<", svg)
    assert animal_box


def test_journey_scores_use_status_colours():
    jr = m.parse_journey(
        "journey\n title Day\n section Work\n Make tea: 5: Me\n Do work: 1: Me, Cat"
    )
    assert [(x.name, x.score, x.actors, x.section) for x in jr.tasks] == [
        ("Make tea", 5, ["Me"], "Work"),
        ("Do work", 1, ["Me", "Cat"], "Work"),
    ]
    svg = m.render_journey_svg(jr)
    assert m._SCORE_COLORS[5] in svg and m._SCORE_COLORS[1] in svg
    assert ">Cat<" in svg and ">Work<" in svg


def test_git_graph_branches_merges_and_cherry_picks():
    gg = m.parse_git(
        'gitGraph\n commit id: "a"\n branch dev\n checkout dev\n commit id: "b"\n'
        ' checkout main\n merge dev tag: "v1"\n cherry-pick id: "b"\n'
        " commit type: HIGHLIGHT"
    )
    assert gg.branches == ["main", "dev"]
    kinds = [(c.branch, c.kind) for c in gg.commits]
    assert kinds == [
        ("main", "normal"),
        ("dev", "normal"),
        ("main", "merge"),
        ("main", "cherry"),
        ("main", "highlight"),
    ]
    merge = gg.commits[2]
    assert merge.parents == ["a", "b"] and merge.tag == "v1"
    assert gg.cherry_sources[3] == "b"
    svg = m.render_git_svg(gg)
    assert ">main<" in svg and ">dev<" in svg and ">v1<" in svg


def test_wide_left_to_right_charts_fit_the_column():
    src = (
        "flowchart LR\n A([Customer submits an order]) --> B[Order form is validated]\n"
        " B --> C{Is the order valid?}\n C -->|yes| D[Pick and pack the items]\n"
        " D --> E[(Update inventory system)]\n E --> F([Delivered to the customer])"
    )
    fitted = m.svg_natural_width(m.render_to_svg(src, {"column_px": "628"}))
    assert fitted is not None and fitted <= 628
    off = m.render_to_svg(
        '%%{init: {"flowchart": {"autoFit": false}}}%%\n' + src, {"column_px": "628"}
    )
    assert (m.svg_natural_width(off) or 0) > 628  # authors can keep the original layout


def test_text_is_measured_with_the_real_font():
    m._ACTIVE_FONT.set("DejaVu Sans")
    path = m._font_file("DejaVu Sans", 400)
    if path is None:
        pytest.skip("fontconfig/DejaVu not available")
    real = m._text_w("Reject and notify customer")
    m._ACTIVE_FONT.set("Liberation Sans, Arial")
    narrower = m._text_w("Reject and notify customer")
    assert real > narrower  # DejaVu is wider; boxes are sized from the face actually used


def test_registered_fonts_are_used_for_measurement(tmp_path):
    ziamath = pytest.importorskip("ziamath")
    from pathlib import Path

    font = Path(ziamath.__file__).parent / "fonts" / "STIXTwoMath-Regular.ttf"
    if not font.is_file():
        pytest.skip("test font missing")
    m.register_fonts([("Diagram Test Face", font, "400")])
    assert m._font_file("Diagram Test Face, sans-serif", 400) == font


def test_dark_mode_from_init_and_from_a_dark_theme():
    dark = m.render_to_svg("%%{init: {'theme':'dark'}}%%\npie\n \"A\" : 1\n \"B\" : 2")
    assert 'data-surface="#0d1117"' in dark and m._CATEGORICAL_DARK[0] in dark
    theme = m.extract_theme_from_css("body { background: #111418; color: #e6e6e6; }")
    assert theme["mode"] == "dark" and theme["surface"] == "#111418"
    flow = m.render_to_svg("flowchart TD\n A[One] --> B[Two]", theme)
    assert 'data-surface="#111418"' in flow and "#e6e6e6" in flow
    light = m.render_to_svg('pie\n "A" : 1')
    assert "data-surface" not in light


def test_dark_diagrams_rasterise_on_their_surface():
    from md_doc.builders._assets import _svg_to_png

    png = _svg_to_png(m.render_to_svg("%%{init: {'theme':'dark'}}%%\nflowchart LR\n A --> B"))
    if png is None:
        pytest.skip("cairosvg not installed")
    from io import BytesIO

    from PIL import Image

    assert Image.open(BytesIO(png[0])).convert("RGB").getpixel((1, 1)) == (13, 17, 23)


def test_named_themes_and_theme_variables():
    forest = m.render_to_svg("%%{init: {'theme':'forest'}}%%\nflowchart TD\n A([Go]) --> B")
    assert 'fill="#2f6f3e"' in forest
    base = m.render_to_svg(
        '---\nconfig:\n  theme: base\n  themeVariables:\n    primaryColor: "#7a1f5c"\n---\n'
        "flowchart TD\n A([Go]) --> B"
    )
    assert 'fill="#7a1f5c"' in base


def test_front_matter_title_is_drawn():
    svg = m.render_to_svg("---\ntitle: Order flow\n---\nflowchart LR\n A --> B")
    assert ">Order flow<" in svg


def test_quadrant_points_classes_and_label_placement():
    qc = m.parse_quadrant(
        "quadrantChart\n title Reach\n x-axis Low --> High\n y-axis Bad --> Good\n"
        " quadrant-1 Expand\n A: [0.4, 0.34]\n B:::hot: [0.78, 0.34] radius: 8\n"
        " classDef hot color: #d03b3b"
    )
    assert (qc.x_low, qc.x_high, qc.y_low, qc.y_high) == ("Low", "High", "Bad", "Good")
    assert qc.quadrants[0] == "Expand"
    assert qc.points[1][3] == {"color": "#d03b3b", "radius": "8"}
    svg = m.render_quadrant_svg(qc)
    assert 'fill="#d03b3b"' in svg and ">Expand<" in svg


def test_sankey_layers_and_quoted_csv():
    sk = m.parse_sankey('sankey\nWind,Grid,10\nGrid,"Heating, homes",6\nGrid,Industry,4')
    assert sk.links == [
        ("Wind", "Grid", 10.0),
        ("Grid", "Heating, homes", 6.0),
        ("Grid", "Industry", 4.0),
    ]
    svg = m.render_sankey_svg(sk)
    assert ">Heating, homes<" in svg and svg.count('fill-opacity="0.32"') == 3


def test_radar_axes_curves_and_options():
    rd = m.parse_radar(
        'radar-beta\n axis a["A"], b["B"], c["C"]\n curve x["X"]{1, 2, 3}\n'
        " curve y{ c: 3, a: 1, b: 2 }\n max 5\n graticule polygon\n ticks 4"
    )
    assert rd.axes == [("a", "A"), ("b", "B"), ("c", "C")]
    assert rd.curves == [("X", [1.0, 2.0, 3.0]), ("y", [1.0, 2.0, 3.0])]
    assert (rd.max_val, rd.graticule, rd.ticks) == (5.0, "polygon", 4)
    assert m.render_radar_svg(rd).count("<polygon") >= 4 + 2


def test_treemap_areas_follow_values():
    root = m.parse_treemap('treemap-beta\n"G"\n    "A": 30\n    "B": 10\n"H"\n    "C": 60')
    assert [c.name for c in root.children] == ["G", "H"]
    rects = m._squarify([60, 30, 10], 0, 0, 100, 100)
    areas = [w * h for _, _, w, h in rects]
    assert areas == pytest.approx([6000, 3000, 1000], rel=1e-6)
    assert ">A<" in m.render_treemap_svg(root)


def test_packet_ranges_relative_bits_and_rows():
    pk = m.parse_packet('packet\n0-15: "Src"\n+16: "Dst"\n32: "FIN"\n+31: "Rest"')
    assert pk.fields == [(0, 15, "Src"), (16, 31, "Dst"), (32, 32, "FIN"), (33, 63, "Rest")]
    svg = m.render_packet_svg(pk)
    assert ">Src<" in svg and "rotate(-90)" in svg  # one-bit field labelled vertically


def test_block_grid_spans_arrows_and_groups():
    bd = m.parse_block(
        'block\n columns 3\n a["A"] arrow<["go"]>(right) b\n space:2 c\n'
        " block:grp:3\n  d e\n end\n grp --> c\n style a fill:#fde"
    )
    kinds = [(k.kind, k.id, k.span) for k in bd.root.children]
    assert kinds == [
        ("node", "a", 1),
        ("arrow", "arrow", 1),
        ("node", "b", 1),
        ("space", "", 2),
        ("node", "c", 1),
        ("group", "grp", 3),
    ]
    assert bd.edges == [("grp", "c", "", "arrow")]
    assert bd.root.children[0].css == {"fill": "#fde"}
    svg = m.render_block_svg(bd)
    assert ">go<" in svg and 'fill="#fde"' in svg


def test_kanban_columns_and_metadata():
    cols = m.parse_kanban(
        "kanban\n  Todo\n    t1[Write docs]@{ ticket: MC-1, assigned: 'knsv', priority: 'High' }\n"
        "  [Done]\n    t2[Ship]"
    )
    assert [c.title for c in cols] == ["Todo", "Done"]
    assert cols[0].items[0].meta == {"ticket": "MC-1", "assigned": "knsv", "priority": "High"}
    svg = m.render_kanban_svg(cols)
    assert ">MC-1<" in svg and m._PRIORITY_COLORS["high"] in svg


def test_architecture_grid_from_edge_sides():
    ad = m.parse_architecture(
        "architecture-beta\n group api(cloud)[API]\n service db(database)[Database] in api\n"
        " service server(server)[Server] in api\n service disk(disk)[Disk] in api\n"
        " junction j\n db:L -- R:server\n disk:T -- B:server\n server:T --> B:j"
    )
    grid = m._arch_grid(ad)
    assert grid["db"][0] == grid["server"][0] + 1 and grid["db"][1] == grid["server"][1]
    assert grid["disk"][1] == grid["server"][1] + 1
    assert grid["j"][1] == grid["server"][1] - 1
    svg = m.render_architecture_svg(ad)
    assert ">API<" in svg and "url(#arr)" in svg


def test_c4_elements_boundaries_and_relations():
    cd = m.parse_c4(
        'C4Container\n title Banking\n Person(c, Customer, "A customer")\n'
        ' Container_Boundary(b, "Internet Banking") {\n'
        '  Container(spa, "SPA", "JavaScript, Angular", "The app")\n'
        '  ContainerDb(db, "Database", "SQL")\n }\n'
        ' System_Ext(mail, "E-mail")\n Rel(c, spa, "Uses", "HTTPS")\n'
        ' Rel_Back(db, spa, "Reads")\n BiRel(spa, mail, "Sends")\n'
        ' UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")'
    )
    spa = cd.elements["spa"]
    assert (spa.level, spa.techn, spa.descr) == ("container", "JavaScript, Angular", "The app")
    assert cd.elements["db"].shape == "db" and cd.elements["mail"].ext
    assert [b.label for b in cd.root.boundaries] == ["Internet Banking"]
    assert [(r.src, r.dst, r.bi) for r in cd.rels] == [
        ("c", "spa", False),
        ("spa", "db", False),
        ("spa", "mail", True),
    ]
    assert (cd.shape_in_row, cd.boundary_in_row) == (3, 1)
    svg = m.render_c4_svg(cd)
    assert "[Container: JavaScript, Angular]" in svg and ">Internet Banking<" in svg


def test_requirement_cards_and_both_relation_directions():
    rd = m.parse_requirement(
        "requirementDiagram\n requirement r1 {\n id: 1\n text: Must pay.\n risk: high\n"
        " verifymethod: test\n }\n element svc {\n type: service\n }\n"
        " svc - satisfies -> r1\n r1 <- traces - svc"
    )
    assert rd.nodes["r1"].fields[0] == ("id", "1")
    assert rd.relations == [("svc", "r1", "satisfies"), ("svc", "r1", "traces")]
    svg = m.render_requirement_svg(rd)
    assert "«satisfies»" in svg and ">High<" in svg and "«Element»" in svg


def test_zenuml_translates_to_a_sequence():
    sd, title = m.parse_zenuml(
        "zenuml\n title Orders\n @Actor Client\n Client->Svc.create(o) {\n"
        "  ok = Check.run(o)\n  if(ok) {\n   return id\n  } else {\n   @return\n"
        "   Svc->Client: no\n  }\n }\n par {\n  Svc->Mail: hi\n }"
    )
    assert title == "Orders" and sd.actors == {"Client"}
    msgs = [(x.src, x.dst, x.label, x.arrow) for x in sd.messages]
    assert msgs == [
        ("Client", "Svc", "create(o)", "->>"),
        ("Svc", "Check", "run(o)", "->>"),
        ("Check", "Svc", "ok", "-->>"),
        ("Svc", "Client", "id", "-->>"),
        ("Svc", "Client", "no", "-->>"),
        ("Svc", "Mail", "hi", "-)"),
    ]
    blocks = [(e.kind, e.label) for e in sd.events if isinstance(e, m.SeqBlock)]
    assert blocks == [("alt", "ok"), ("else", ""), ("end", ""), ("par", ""), ("end", "")]
    assert ">Orders<" in m.render_to_svg("zenuml\n title Orders\n A->B: hi")


@pytest.mark.parametrize(
    "source",
    [
        "quadrantChart\n A: [0.5, 0.5]",
        "sankey-beta\nA,B,1",
        "radar-beta\n axis a, b, c\n curve x{1,2,3}",
        'treemap-beta\n"A": 1',
        'packet-beta\n0-7: "A"',
        "block-beta\n a b",
        "kanban\n  Todo\n    [x]",
        "architecture-beta\n service a(server)[A]",
        "C4Context\n Person(a, A)",
        "requirementDiagram\n requirement r {\n id: 1\n }",
        "zenuml\n A->B: hi",
    ],
)
def test_every_new_type_renders(source):
    svg = m.render_to_svg(source)
    assert svg.startswith("<svg") and m.svg_natural_width(svg)


def test_fonts_registered_after_a_raster_still_apply():
    ziamath = pytest.importorskip("ziamath")
    from pathlib import Path

    from md_doc.builders._assets import _svg_to_png

    font = Path(ziamath.__file__).parent / "fonts" / "STIXTwoMath-Regular.ttf"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 300 40">'
        '<text x="4" y="28" font-family="Late Face Test" font-size="22">Late</text></svg>'
    )
    before = _svg_to_png(svg)
    if before is None or not font.is_file():
        pytest.skip("cairosvg or test font missing")
    generation = m.font_generation()
    copy = Path(str(font))  # a path not yet registered under this family
    m._FC_ADDED.discard(copy)
    m.register_fonts([("Late Face Test", copy, "400")])
    assert m.font_generation() > generation


@pytest.mark.parametrize(
    "source, kind",
    [
        ("usecase-beta\nactor U\nU --> (Login)", "usecase"),
        ("swimlane-beta LR\nsubgraph A\n x\nend", "swimlanes"),
        ("agentflow-beta\na --> b", "agentflow"),
        ("treeView-beta\nsrc/\n  a.py", "treeview"),
        ("ishikawa-beta\nEffect\n  Cause", "ishikawa"),
        ("venn-beta\nset A", "venn"),
        ("cynefin-beta\ncomplex", "cynefin"),
        ("wardley-beta\ncomponent A [0.5, 0.5]", "wardley"),
        ('railroad-ebnf-beta\na = "x" ;', "railroad"),
        ('railroad-beta\na = terminal("x") ;', "railroad"),
        ("eventmodeling\ntf 01 ui CartUI", "eventmodeling"),
    ],
)
def test_newest_diagram_types_render(source, kind):
    assert m._detect_diagram_type(source) == kind
    svg = m.render_to_svg(source)
    assert svg.startswith("<svg") and "NaN" not in svg


def test_unknown_types_still_default_to_flowchart():
    assert m._detect_diagram_type("A --> B") == "flowchart"
    assert m._detect_diagram_type("stateDiagram-v2\n [*] --> A") == "state"


def test_pipe_label_after_cross_and_circle_ends():
    fc = m.parse("flowchart TD\n a --x|no| b\n c --o|maybe| d")
    assert [(e.src, e.dst, e.label, e.head) for e in fc.edges] == [
        ("a", "b", "no", "cross"),
        ("c", "d", "maybe", "circle"),
    ]


def test_flowchart_shape_metadata_and_subgraph_edges():
    fc = m.parse(
        'flowchart LR\n a@{ shape: doc, label: "Spec" }\n subgraph G\n  x --> y\n end\n a --> G\n G --> z'
    )
    assert fc.nodes["a"].shape == "document" and fc.nodes["a"].label == "Spec"
    assert ("a", "x") in [(e.src, e.dst) for e in fc.edges]
    assert ("y", "z") in [(e.src, e.dst) for e in fc.edges]
    assert "G" not in fc.nodes


def test_sibling_subgraph_frames_do_not_overlap():
    fc = m.parse_usecase(
        'usecase-beta\nactor C\nactor S\nsystemBoundary Store\n B("Browse")\n K("Checkout")\nend\n'
        'systemBoundary Ship\n T("Track")\nend\nC --> B\nC --> K\nC --> T\nS --> T\nK ..> : include B'
    )
    m.layout(fc)
    a, b = fc.subgraphs
    assert a.y + a.h <= b.y or b.y + b.h <= a.y or a.x + a.w <= b.x or b.x + b.w <= a.x


def test_usecase_actors_ellipses_and_include():
    fc = m.parse_usecase(
        'usecase-beta\nactor Customer\nsystemBoundary Shop\n  Pay("Pay")\nend\n'
        "Customer --> Pay\nPay ..> : include Login"
    )
    assert fc.nodes["Customer"].shape == "actor"
    assert fc.nodes["Pay"].shape == "ellipse"
    assert fc.subgraphs[0].node_ids == ["Pay"]
    inc = [e for e in fc.edges if e.label == "«include»"]
    assert inc and inc[0].style == "dotted"


def test_swimlanes_flip_downwards_when_too_wide():
    src = "swimlane-beta LR\n" + "\n".join(
        f"s{i}[Step number {i}] --> s{i + 1}[Step number {i + 1}]" for i in range(8)
    )
    fc = m.parse_swimlanes(src)
    m.render_swimlanes_svg(fc, {"column_px": "600"})
    assert fc.direction == "TD"


def test_agentflow_collapsed_flow_and_failure_edge():
    fc = m.parse_agentflow(
        'agentflow-beta LR\nflow f["Agent"]\n a --> b\nend\nf@{ view: collapsed }\nstart --> a\nb --x stop'
    )
    assert fc.nodes["f"].label == "Agent" and "a" not in fc.nodes
    assert any(e.head == "cross" and e.css.get("stroke") for e in fc.edges)


def test_treeview_box_drawing_and_descriptions():
    rows = m.parse_treeview(
        "treeView-beta\nsrc/\n├── a.py ## entry\n└── lib/\n    └── b.py :::highlight"
    )
    assert [(r.label, r.depth) for r in rows] == [
        ("src/", 0),
        ("a.py", 1),
        ("lib/", 1),
        ("b.py", 2),
    ]
    assert rows[1].desc == "entry" and rows[3].highlight and rows[2].is_dir


def test_ishikawa_effect_and_categories():
    effect, cats = m.parse_ishikawa(
        "ishikawa-beta\nSlow site\n  People\n    Training\n  Tools\n    Old CI"
    )
    assert effect == "Slow site" and [c.label for c in cats] == ["People", "Tools"]
    assert "Old CI" in m.render_ishikawa_svg(effect, cats)


def test_venn_sets_unions_text_and_style():
    data = m.parse_venn(
        'venn-beta\ntitle T\nset A["Alpha"]:20\n  text A1["React"]\nset B\nunion A,B["AB"]:3\nstyle A fill:#ff6b6b'
    )
    assert [s["label"] for s in data["sets"]] == ["Alpha", "B"]
    assert data["unions"][0]["ids"] == ["A", "B"] and data["unions"][0]["size"] == 3
    svg = m.render_venn_svg(data)
    assert "#ff6b6b" in svg and "React" in svg and svg.count("<circle") == 2


def test_cynefin_domains_items_and_transitions():
    data = m.parse_cynefin(
        'cynefin-beta\ncomplex\n  "Probe"\nclear\n  "Fix"\nconfusion\n  "Huh"\ncomplex --> clear : "Learned"\nclear --> clear'
    )
    assert data["items"]["complex"] == ["Probe"] and data["transitions"] == [
        ("complex", "clear", "Learned")
    ]
    svg = m.render_cynefin_svg(data)
    for word in ("Complex", "Complicated", "Chaotic", "Clear", "Confusion", "Learned"):
        assert word in svg


def test_wardley_components_links_and_evolution():
    data = m.parse_wardley(
        "wardley-beta\ntitle Map\nevolution A@0.3 -> B -> C\nanchor User [0.9, 0.9]\n"
        "component Real-time API [0.6, 0.5] label [-20, 5] (build) (inertia)\n"
        "User -> Real-time API\nUser +'feeds'> Real-time API\nevolve Real-time API 0.8\n"
        'note "Watch" [0.3, 0.3]\nannotation 1,[0.5, 0.5] "Key"\naccelerator "AI" [0.2, 0.2]'
    )
    comp = data["components"]["Real-time API"]
    assert comp["decorators"] == ["build", "inertia"] and comp["label"] == (-20.0, 5.0)
    assert data["stages"][0] == ("A", 0.3)
    assert data["links"][1]["label"] == "feeds" and data["links"][1]["flow"]
    svg = m.render_wardley_svg(data)
    assert "Watch" in svg and "Key" in svg and "AI" in svg


@pytest.mark.parametrize(
    "source",
    [
        'railroad-ebnf-beta\nn = [ "-" ] digit { digit } ;\ndigit = "0" | "1" ;',
        'railroad-abnf-beta\nn = [ "-" ] 1*DIGIT ; comment\nDIGIT = %x30-39 ;',
        'railroad-peg-beta\nN <- "-"? !"0" D+ ;\nD <- "0" / "1" ;',
        'railroad-beta\nn = sequence(optional(terminal("-")), oneOrMore(nonterminal("digit"))) ;',
    ],
)
def test_railroad_notations_parse_to_rules(source):
    data = m.parse_railroad(source)
    assert data["rules"][0][0] in ("n", "N")
    svg = m.render_railroad_svg(data)
    for name, _ in data["rules"]:
        assert f">{name}<" in svg


def test_railroad_long_rule_wraps_to_column():
    terms = " ".join(f'"token{i}"' for i in range(20))
    svg = m.render_railroad_svg(
        m.parse_railroad(f"railroad-ebnf-beta\nr = {terms} ;"), {"column_px": "500"}
    )
    assert float(re.search(r'viewBox="0 0 ([\d.]+)', svg).group(1)) <= 500


def test_eventmodeling_lanes_data_and_links():
    data = m.parse_eventmodeling(
        "eventmodeling\ntf 01 ui CartUI\ntf 02 cmd AddItem [[Add]]\ntf 03 evt ItemAdded { id: string }\n"
        "rf 04 evt Inventory.Changed\ntf 05 rmo Cart ->> 03\ndata Add {\n  sku: string\n}"
    )
    frames = data["frames"]
    assert [f["kind"] for f in frames] == ["ui", "cmd", "evt", "evt", "rmo"]
    assert frames[1]["data"] == ["sku: string"] and frames[2]["data"] == ["id: string"]
    assert frames[3]["reset"] and frames[3]["ns"] == "Inventory" and frames[4]["refs"] == ["03"]
    svg = m.render_eventmodeling_svg(data)
    assert "Inventory" in svg and "COMMAND" in svg


def test_c4_labelled_neighbours_get_room_and_relations_avoid_cards():
    cd = m.parse_c4(
        'C4Context\nSystem(a, "A")\nSystem(b, "B")\nSystem(c, "C")\n'
        'Rel(a, b, "A rather long relationship label")\nRel(a, c, "Skips")'
    )
    svg = m.render_c4_svg(cd)
    assert " Q " in svg  # a to c bends around b
