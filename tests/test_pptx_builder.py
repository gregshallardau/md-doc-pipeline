"""Tests for the pptx (PowerPoint) slide builder."""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from md_doc.builders.pptx import build


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def _png(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (200, 120), "teal").save(path)


def _build(repo: Path, body: str, config: dict) -> Presentation:
    from md_doc.config import load_config

    doc = repo / "talk.md"
    doc.write_text(body, encoding="utf-8")
    out = repo / "talk.pptx"
    cfg = load_config(doc, repo_root=repo)  # merge frontmatter like the real pipeline
    cfg.update(config)
    build(body, cfg, out, doc_path=doc, repo_root=repo)
    return Presentation(str(out))


def _titles(prs: Presentation) -> list[str]:
    return [(s.shapes.title.text if s.shapes.title else "") for s in prs.slides]


def _pics(slide) -> int:
    return sum(1 for sh in slide.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE)


def _tables(slide) -> int:
    return sum(1 for sh in slide.shapes if sh.has_table)


DECK = """---
title: Quarterly Review
author: Jane Doe
product: Acme
date: July 2026
---

# Quarterly Review

## Highlights

- Top level
    - Nested one

<!-- notes: speaker note here -->

## Metrics

| M | Q1 | Q2 |
|---|----|----|
| U | 10 | 14 |

## Shot

![dash](pic.png)
"""


def test_title_slide_and_h2_segmentation(repo):
    prs = _build(repo, DECK, {})
    titles = _titles(prs)
    # title slide + 3 H2 content slides
    assert titles[0] == "Quarterly Review"
    assert "Highlights" in titles
    assert "Metrics" in titles
    assert "Shot" in titles


def test_title_slide_has_metadata(repo):
    prs = _build(repo, DECK, {})
    # subtitle placeholder carries product/author/date
    text = "\n".join(
        ph.text_frame.text for ph in prs.slides[0].placeholders if ph.placeholder_format.idx != 0
    )
    assert "Acme" in text and "Jane Doe" in text and "July 2026" in text


def test_bullet_levels(repo):
    prs = _build(repo, DECK, {})
    highlights = next(
        s for s in prs.slides if s.shapes.title and s.shapes.title.text == "Highlights"
    )
    levels = {
        p.level
        for sh in highlights.shapes
        if sh.has_text_frame
        for p in sh.text_frame.paragraphs
        if p.text
    }
    assert 0 in levels and 1 in levels  # nested bullet produced a level-1 paragraph


def test_table_and_image_and_notes(repo):
    _png(repo / "pic.png")
    prs = _build(repo, DECK, {})
    assert any(_tables(s) for s in prs.slides)
    assert any(_pics(s) for s in prs.slides)
    notes = [s.notes_slide.notes_text_frame.text for s in prs.slides if s.has_notes_slide]
    assert any("speaker note here" in n for n in notes)


def test_explicit_slide_break(repo):
    body = "---\ntitle: T\n---\n\n## One\n\nalpha\n\n<!-- slide -->\n\nbeta\n"
    prs = _build(repo, body, {})
    # title slide + One + the explicit-break slide
    assert len(prs.slides._sldIdLst) == 3


def test_slide_split_marker_only(repo):
    body = "---\ntitle: T\n---\n\n## One\n\n## Two\n\n<!-- slide -->\n\nlast\n"
    prs = _build(repo, body, {"slide_split": "marker"})
    # H2 headings do NOT split in marker mode: title slide + one content + marker slide
    assert len(prs.slides._sldIdLst) == 3


def test_slide_size_widescreen(repo):
    prs = _build(repo, DECK, {"slide_size": "16:9"})
    from pptx.util import Inches

    assert prs.slide_width == Inches(13.333)


def test_picks_up_css_theme_and_yaml(repo):
    # Full theming parity: YAML frontmatter + the CSS theme cascade (heading
    # colours, body colour/font, table header + alternating-row colours).
    (repo / "_pdf-theme.css").write_text(
        ":root { --primary: #CC0066; }\n"
        'body { font-family: "Georgia"; color: #223344; }\n'
        "h1, h2 { color: #CC0066; }\n"
        "th { background: #CC0066; color: #FFFFFF; }\n"
        "tr:nth-child(even) td { background: #EEEEEE; }\n",
        encoding="utf-8",
    )
    body = (
        "---\ntitle: Themed Deck\nauthor: Ada\nproduct: Engine\n---\n\n"
        "# Themed Deck\n\n## Point\n\n- hello\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n"
    )
    prs = _build(repo, body, {})
    from pptx.dml.color import RGBColor

    # YAML → title slide
    assert prs.slides[0].shapes.title.text == "Themed Deck"
    sub = "\n".join(
        ph.text_frame.text for ph in prs.slides[0].placeholders if ph.placeholder_format.idx != 0
    )
    assert "Ada" in sub and "Engine" in sub

    content = next(s for s in prs.slides if s.shapes.title and s.shapes.title.text == "Point")
    # CSS → content-slide title colour (H2)
    assert content.shapes.title.text_frame.paragraphs[0].font.color.rgb == RGBColor(
        0xCC, 0x00, 0x66
    )

    # CSS → body font + body text colour on the bullet run
    run = next(
        r
        for sh in content.shapes
        if sh.has_text_frame
        for p in sh.text_frame.paragraphs
        for r in p.runs
        if r.text.strip() == "hello"
    )
    assert run.font.name == "Georgia"
    assert run.font.color.rgb == RGBColor(0x22, 0x33, 0x44)

    # CSS → table header fill + alternating row shading. nth-child(even) shades
    # the first body row (table index 1); the second body row is unshaded.
    table = next(sh.table for sh in content.shapes if sh.has_table)
    assert table.cell(0, 0).fill.fore_color.rgb == RGBColor(0xCC, 0x00, 0x66)  # header bg
    assert table.cell(1, 0).fill.fore_color.rgb == RGBColor(0xEE, 0xEE, 0xEE)  # shaded row
    assert table.cell(2, 0).fill.type is None  # unshaded row


def test_blockquote_renders_italic(repo):
    body = "---\ntitle: T\n---\n\n## Q\n\n> a wise quote\n"
    prs = _build(repo, body, {})
    content = next(s for s in prs.slides if s.shapes.title and s.shapes.title.text == "Q")
    italics = [
        r.font.italic
        for sh in content.shapes
        if sh.has_text_frame
        for p in sh.text_frame.paragraphs
        for r in p.runs
        if "wise quote" in r.text
    ]
    assert italics and all(italics)


def test_mermaid_diagram_embeds_as_picture(repo):
    pytest.importorskip("cairosvg")
    body = '---\ntitle: T\n---\n\n## Chart\n\n```mermaid\npie\n"A" : 60\n"B" : 40\n```\n'
    prs = _build(repo, body, {})
    assert any(_pics(s) for s in prs.slides)


# ── Deck-first layout directives ─────────────────────────────────────────────


def _boxes(slide):
    return [
        sh
        for sh in slide.shapes
        if sh.has_text_frame and sh != slide.shapes.title and sh.text_frame.text.strip()
    ]


def test_directive_slide_adopts_next_heading(repo):
    body = "---\ntitle: T\n---\n\n<!-- slide: stat -->\n\n## Numbers\n\n- **9** lives\n"
    prs = _build(repo, body, {})
    # title slide + ONE stat slide (the H2 titles the directive slide, no split)
    assert len(prs.slides._sldIdLst) == 2
    assert prs.slides[1].shapes.title.text == "Numbers"


def test_columns_layout_routes_content(repo):
    body = (
        "---\ntitle: T\n---\n\n<!-- slide: columns -->\n\n## Two Up\n\n"
        "Left text\n\n<!-- col -->\n\nRight text\n"
    )
    prs = _build(repo, body, {})
    slide = prs.slides[1]
    boxes = _boxes(slide)
    assert len(boxes) == 2
    by_x = sorted(boxes, key=lambda sh: sh.left)
    assert "Left text" in by_x[0].text_frame.text
    assert "Right text" in by_x[1].text_frame.text
    assert by_x[0].left < by_x[1].left


def test_stat_layout_renders_tiles(repo):
    body = (
        "---\ntitle: T\n---\n\n<!-- slide: stat -->\n\n## KPIs\n\n"
        "- **47%** growth\n- **12k** users\n- **3.2s** builds\n"
    )
    prs = _build(repo, body, {})
    boxes = _boxes(prs.slides[1])
    assert len(boxes) == 3
    from pptx.util import Pt

    values = [
        r for sh in boxes for p in sh.text_frame.paragraphs for r in p.runs if r.font.size == Pt(44)
    ]
    assert {r.text for r in values} == {"47%", "12k", "3.2s"}
    assert all(r.font.bold for r in values)


def test_quote_layout_with_attribution(repo):
    body = (
        "---\ntitle: T\n---\n\n<!-- slide: quote -->\n\n" "> Less is more.\n\n— Mies van der Rohe\n"
    )
    prs = _build(repo, body, {})
    box = _boxes(prs.slides[1])[0]
    from pptx.util import Pt

    runs = [r for p in box.text_frame.paragraphs for r in p.runs]
    quote = next(r for r in runs if "Less is more" in r.text)
    assert quote.font.size == Pt(28) and quote.font.italic
    attr = next(r for r in runs if "Mies" in r.text)
    assert attr.font.size == Pt(15)


def test_center_layout_anchors_middle(repo):
    from pptx.enum.text import MSO_ANCHOR

    body = "---\ntitle: T\n---\n\n<!-- slide: center -->\n\nBig statement.\n"
    prs = _build(repo, body, {})
    box = _boxes(prs.slides[1])[0]
    assert box.text_frame.vertical_anchor == MSO_ANCHOR.MIDDLE


def test_background_fill_and_dark_text_flip(repo):
    from pptx.dml.color import RGBColor

    body = "---\ntitle: T\n---\n\n<!-- slide: section background=#1b4f72 -->\n\n# Part One\n"
    prs = _build(repo, body, {})
    slide = prs.slides[1]
    assert slide.background.fill.fore_color.rgb == RGBColor(0x1B, 0x4F, 0x72)
    title_para = slide.shapes.title.text_frame.paragraphs[0]
    assert title_para.font.color.rgb == RGBColor(0xFF, 0xFF, 0xFF)  # dark bg → white


def test_unknown_layout_degrades_to_content(repo):
    body = "---\ntitle: T\n---\n\n<!-- slide: sparkle -->\n\n## Still Works\n\ntext\n"
    prs = _build(repo, body, {})
    assert any(s.shapes.title and s.shapes.title.text == "Still Works" for s in prs.slides)


def test_overlong_slide_shrinks_text(repo):
    long_para = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 8).strip()
    body = "---\ntitle: T\n---\n\n## Wall\n\n" + "\n\n".join([long_para] * 8) + "\n"
    prs = _build(repo, body, {})
    from pptx.util import Pt

    wall = next(s for s in prs.slides if s.shapes.title and s.shapes.title.text == "Wall")
    sizes = {r.font.size for sh in _boxes(wall) for p in sh.text_frame.paragraphs for r in p.runs}
    assert sizes and all(sz < Pt(18) for sz in sizes)  # shrunk below the default


def test_image_layout_centres_picture(repo):
    _png(repo / "shot.png")
    body = "---\ntitle: T\n---\n\n<!-- slide: image -->\n\n## Shot\n\n![s](shot.png)\n"
    prs = _build(repo, body, {})
    slide = next(s for s in prs.slides if s.shapes.title and s.shapes.title.text == "Shot")
    assert _pics(slide) == 1


def test_background_only_directive_on_content_slide(repo):
    # <!-- slide: background=#hex --> with no layout name must still take the
    # next heading as its title and keep the fill (regression: the heading
    # used to split to a new slide, orphaning the background).
    from pptx.dml.color import RGBColor

    body = "---\ntitle: T\n---\n\n<!-- slide: background=#1b4f72 -->\n\n## Dark\n\n- x\n"
    prs = _build(repo, body, {})
    assert len(prs.slides._sldIdLst) == 2
    slide = prs.slides[1]
    assert slide.shapes.title.text == "Dark"
    assert slide.background.fill.fore_color.rgb == RGBColor(0x1B, 0x4F, 0x72)
    title_para = slide.shapes.title.text_frame.paragraphs[0]
    assert title_para.font.color.rgb == RGBColor(0xFF, 0xFF, 0xFF)
