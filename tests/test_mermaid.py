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
