"""Diagram colours follow the brand theme: how they are read and what they drive."""

import re

import pytest

from md_doc import mermaid as m
from md_doc.docx_theme import _load_css_with_imports

PIE = 'pie\n "A" : 5\n "B" : 4\n "C" : 3\n "D" : 2'


def _fills(svg: str) -> list[str]:
    return re.findall(r'<path d="[^"]+" fill="(#[0-9a-f]{6})"', svg)


class TestColourFormats:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("#c0392b", "#c0392b"),
            ("#c03", "#cc0033"),
            ("rgb(192, 57, 43)", "#c0392b"),
            ("rgb(192 57 43 / 50%)", "#c0392b"),
            ("hsl(168, 76%, 36%)", "#16a286"),
            ("hsl(168deg 76% 36%)", "#16a286"),
            ("crimson", "#dc143c"),
            ("#c0392b !important", "#c0392b"),
        ],
    )
    def test_converts_to_hex(self, value, expected):
        assert m.css_color_to_hex(value) == expected

    @pytest.mark.parametrize("value", ["transparent", "inherit", "currentColor", "nonsense", ""])
    def test_ignores_non_colours(self, value):
        assert m.css_color_to_hex(value) is None

    def test_extracts_non_hex_declarations(self):
        theme = m.extract_theme_from_css("h1{color:crimson} h2{color:hsl(168,76%,36%)}")
        assert theme["primary"] == "#dc143c" and theme["accent"] == "#16a286"

    def test_follows_custom_properties_with_fallbacks(self):
        css = ":root{--brand:#c0392b; --alt:var(--brand)} h1{color:var(--alt)} h2{color:var(--missing, teal)}"
        theme = m.extract_theme_from_css(css)
        assert theme["primary"] == "#c0392b" and theme["accent"] == "#008080"

    def test_font_stops_at_the_end_of_the_rule(self):
        assert m.extract_theme_from_css("body{font-family:Inter}")["font"] == "Inter"


class TestLayeredThemes:
    def test_child_theme_wins_over_the_imported_parent(self, tmp_path):
        (tmp_path / "client").mkdir()
        (tmp_path / "_theme.css").write_text(
            "body{color:#1a1a2e} h1{color:#1b4f72} h2{color:#2e86c1}"
        )
        child = tmp_path / "client" / "_pdf-theme.css"
        child.write_text('@import "../_theme.css";\nh1{color:#c0392b}\nh2{color:#16a085}\n')
        theme = m.extract_theme_from_css(_load_css_with_imports(child))
        assert (theme["primary"], theme["accent"]) == ("#c0392b", "#16a085")
        assert theme["body"] == "#1a1a2e"  # inherited from the parent

    def test_later_rule_beats_an_earlier_cover_rule(self):
        css = ".cover-title{color:#111111} h1{color:#c0392b}"
        assert m.extract_theme_from_css(css)["primary"] == "#c0392b"


class TestExplicitDiagramProperties:
    CSS = (
        ":root{--mddoc-diagram-primary:#7a1fa2; --mddoc-diagram-accent:rgb(233,30,99);"
        "--mddoc-diagram-text:#222; --mddoc-diagram-muted:#667;"
        "--mddoc-diagram-font:'Inter', sans-serif} h1{color:#000} body{color:#111}"
    )

    def test_win_over_inferred_colours(self):
        theme = m.extract_theme_from_css(self.CSS)
        assert theme["primary"] == "#7a1fa2" and theme["accent"] == "#e91e63"
        assert theme["body"] == "#222222" and theme["muted"] == "#666677"
        assert theme["font"] == "'Inter', sans-serif"

    def test_surface_and_mode(self):
        dark = m.extract_theme_from_css(":root{--mddoc-diagram-surface:#101820}")
        assert dark["mode"] == "dark" and dark["surface"] == "#101820"
        light = m.extract_theme_from_css(
            "body{background:#111418} :root{--mddoc-diagram-mode:light}"
        )
        assert "mode" not in light


class TestSeriesPalette:
    def test_default_theme_keeps_the_validated_palette(self):
        assert _fills(m.render_pie_svg(m.parse_pie(PIE)))[:4] == m._CATEGORICAL[:4]

    def test_brand_leads_the_chart_series(self):
        theme = m.extract_theme_from_css("h1{color:#c0392b} h2{color:#16a085}")
        fills = _fills(m.render_pie_svg(m.parse_pie(PIE), theme))
        assert fills[:2] == ["#c0392b", "#16a085"]
        assert len(set(fills)) == len(fills)

    def test_brand_series_stay_distinguishable(self):
        theme = m.extract_theme_from_css("h1{color:#c0392b} h2{color:#c8402f}")
        series = m._tokens(theme)["series"].split(",")
        assert len(series) == 8 and series[0] == "#c0392b" and series[1] != "#c8402f"

    def test_explicit_palette_is_used_verbatim_then_padded(self):
        css = ":root{--mddoc-diagram-palette:#112233, rgb(200,10,10), teal}"
        series = m._tokens(m.extract_theme_from_css(css))["series"].split(",")
        assert series[:3] == ["#112233", "#c80a0a", "#008080"] and len(series) == 8

    def test_default_keyword_opts_out(self):
        css = "h1{color:#c0392b} :root{--mddoc-diagram-palette:default}"
        theme = m.extract_theme_from_css(css)
        assert _fills(m.render_pie_svg(m.parse_pie(PIE), theme))[:4] == m._CATEGORICAL[:4]

    def test_charts_beyond_pie_use_the_brand(self):
        theme = m.extract_theme_from_css("h1{color:#c0392b} h2{color:#16a085}")
        bar = m.render_bar_svg(m.parse_bar("xychart-beta\n x-axis [a, b]\n bar [1, 2]"), theme)
        assert "#c0392b" in bar
        gantt = m.render_to_svg("gantt\n section S\n T :a, 2024-01-01, 3d", theme)
        assert "#c0392b" in gantt

    def test_dark_theme_lifts_brand_colours_for_series(self):
        css = "body{background:#0d1117} h1{color:#1b4f72} h2{color:#2e86c1}"
        series = m._tokens(m.extract_theme_from_css(css))["series"].split(",")
        assert m._luminance(series[0]) >= 0.12


class TestWordAndSlidesFollowImports:
    def test_docx_passes_the_merged_theme(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        (tmp_path / "_theme.css").write_text("body{color:#1a1a2e} h1{color:#1b4f72}")
        (tmp_path / "doc").mkdir()
        (tmp_path / "doc" / "_pdf-theme.css").write_text(
            '@import "../_theme.css";\nh1{color:#c0392b}\n'
        )
        seen: dict[str, str] = {}
        real = m.diagram_theme

        def spy(css_text, *args, **kwargs):
            seen["css"] = css_text or ""
            return real(css_text, *args, **kwargs)

        monkeypatch.setattr(m, "diagram_theme", spy)
        from md_doc.builders.docx import build

        doc = tmp_path / "doc" / "a.md"
        doc.write_text("# T\n")
        build(
            '# T\n\n```mermaid\npie\n "A" : 1\n "B" : 2\n```\n',
            {"title": "T", "cover_page": False},
            tmp_path / "out.docx",
            doc_path=doc,
            repo_root=tmp_path,
        )
        assert "#1a1a2e" in seen["css"] and "#c0392b" in seen["css"]
        assert "@import" not in seen["css"]


def test_light_surface_property_tints_the_diagram():
    theme = m.extract_theme_from_css(":root{--mddoc-diagram-surface:#fff8e7}")
    assert theme["surface"] == "#fff8e7" and "mode" not in theme
    assert m._tokens(theme)["surface"] == "#fff8e7"
