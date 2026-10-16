"""Tests for ::: component blocks (callouts and the framework rings figure)."""

from __future__ import annotations

from md_doc.components import (
    CALLOUTS,
    decode_svg_ref,
    expand_components,
    framework_rings_svg,
)


def test_callouts_expand_with_label_and_colours() -> None:
    for kind, (label, bg, rule, _label_colour) in CALLOUTS.items():
        out = expand_components(f"::: {kind}\nProviders {kind} act.\n:::\n")
        assert f"callout-{kind}" in out
        assert f"background:{bg}" in out and f"border-left-color:{rule}" in out
        assert f"<strong>{label}</strong>" in out
        assert f"Providers {kind} act." in out
        assert ":::" not in out


def test_components_are_left_alone_inside_code_fences() -> None:
    source = "```markdown\n::: must\nexample\n:::\n```\n"
    assert expand_components(source) == source


def test_unknown_component_is_left_as_written() -> None:
    source = "::: nonsense\nhello\n:::\n"
    assert expand_components(source) == source


def test_unclosed_block_takes_the_rest_of_the_file() -> None:
    out = expand_components("::: must\nlast words\n")
    assert "callout-must" in out and "last words" in out


def test_line_count_is_preserved() -> None:
    source = "a\n\n::: may\nx\ny\n:::\n\nb\n"
    # The block collapses into HTML but trailing newlines keep later lines near
    # their original positions for diagnostics.
    assert expand_components(source).count("\n") >= source.count("\n") - 1


def test_rings_svg_uses_supplied_labels() -> None:
    svg = framework_rings_svg(
        {
            "rings": [{"label": "One", "fill": "#eeeeee", "text": "#111111"}],
            "centre": {"label": "Hub"},
            "satellites": ["Alpha", "Beta", "Gamma"],
        }
    )
    for text in ("One", "Hub", "Alpha", "Beta", "Gamma"):
        assert text in svg
    assert svg.startswith("<svg") and "viewBox" in svg


def test_rings_defaults_are_neutral() -> None:
    svg = framework_rings_svg()
    assert "Outer" in svg and "Centre" in svg and "Equipment" not in svg


def test_framework_svg_accepts_overrides_and_escapes_text() -> None:
    svg = framework_rings_svg({"title": "<b>Hi</b>", "satellites": ["Keep"]})
    assert "&lt;b&gt;" in svg and "<b>" not in svg
    assert "Keep" in svg


def test_figure_is_inline_svg_for_pdf_and_reference_for_docx() -> None:
    pdf = expand_components("::: rings\ncaption: Figure X\n:::\n", "pdf")
    assert "<figure" in pdf and "<svg" in pdf and "Figure X" in pdf
    docx = expand_components("::: rings\n:::\n", "docx")
    assert "<svg" not in docx
    import re

    src = re.search(r'src="([^"]+)"', docx).group(1)
    assert (decode_svg_ref(src) or "").startswith("<svg")
    assert decode_svg_ref("other.png") is None


def test_bullet_css_and_png() -> None:
    from md_doc.bullets import bullet_css, bullet_png

    assert bullet_css({}) == "" and bullet_png({}) is None
    assert bullet_css({"bullet_style": "bogus"}) == ""
    css = bullet_css({"bullet_style": "leaf", "bullet_color": "#5ab379"})
    assert "list-style-image" in css and "5ab379" in css.lower().replace("%23", "")
    png = bullet_png({"bullet_style": "dot", "bullet_color": "#5ab379"})
    assert png is None or png.startswith(b"\x89PNG")
    # Unsafe colours fall back to the default rather than reaching the CSS.
    assert "expression" not in bullet_css(
        {"bullet_style": "dot", "bullet_color": "red;expression(1)"}
    )


def test_toc_config_options() -> None:
    from md_doc.math import markdown_html
    from md_doc.toc import page_number_css, toc_extension_config

    opts = toc_extension_config({"toc_title": "Contents", "toc_depth": "3"})
    html = markdown_html("[TOC]\n\n## A\n\n### B\n\n#### C\n", ["toc"], toc_options=opts)
    assert "toctitle" in html and "Contents" in html
    assert 'href="#b"' in html and 'href="#c"' not in html
    assert page_number_css({}) and not page_number_css({"toc_page_numbers": False})
