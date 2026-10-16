"""Custom bullet shapes for unordered lists (``bullet_style`` / ``bullet_color``).

PDF gets ``list-style-image`` SVGs; Word gets a picture bullet on the
``List Bullet`` numbering level.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

BULLET_STYLES = ("leaf", "dot", "square", "diamond")

_SHAPES = {
    "leaf": "<path d='M1 9 C1 4 4 1 9 1 C9 6 6 9 1 9 Z' fill='{c}'/>",
    "dot": "<circle cx='5' cy='5' r='3.2' fill='{c}'/>",
    "square": "<rect x='2' y='2' width='6' height='6' fill='{c}'/>",
    "diamond": "<path d='M5 1 L9 5 L5 9 L1 5 Z' fill='{c}'/>",
}

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


def _settings(config: dict[str, Any] | None) -> tuple[str, str] | None:
    style = str((config or {}).get("bullet_style") or "").strip().lower()
    if style not in _SHAPES:
        return None
    color = str((config or {}).get("bullet_color") or "#2563eb").strip()
    return style, color if _HEX_RE.fullmatch(color) else "#2563eb"


def bullet_svg(style: str, color: str, size: int = 10) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' "
        f"width='{size}' height='{size}'>{_SHAPES[style].format(c=color)}</svg>"
    )


def bullet_css(config: dict[str, Any] | None) -> str:
    """CSS for the configured bullet, or an empty string when none is set."""
    settings = _settings(config)
    if not settings:
        return ""
    style, color = settings

    def _url(size: int) -> str:
        return (
            'url("data:image/svg+xml;utf8,'
            + urllib.parse.quote(bullet_svg(style, color, size))
            + '")'
        )

    return (
        f"ul {{ list-style-image: {_url(10)}; }}\n"
        f"ul ul {{ list-style-image: {_url(8)}; }}\n"
        "ul > li { padding-left: 3pt; }\n"
    )


def bullet_png(config: dict[str, Any] | None) -> bytes | None:
    """PNG of the configured bullet for Word picture bullets, else None."""
    settings = _settings(config)
    if not settings:
        return None
    try:
        import cairosvg  # type: ignore
    except Exception:
        return None
    return cairosvg.svg2png(bytestring=bullet_svg(*settings, size=10).encode(), output_width=64)


def apply_word_bullet(doc: Any, config: dict[str, Any] | None) -> None:
    """Make Word's ``List Bullet`` numbering use the configured picture bullet."""
    png = bullet_png(config)
    if png is None:
        return
    from io import BytesIO

    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import parse_xml
    from docx.oxml.ns import qn

    numbering_part = doc.part.numbering_part
    numbering = numbering_part.element
    style_num = doc.styles["List Bullet"].element.pPr.numPr.numId.val
    num = next(n for n in numbering.findall(qn("w:num")) if int(n.get(qn("w:numId"))) == style_num)
    abstract_id = num.find(qn("w:abstractNumId")).get(qn("w:val"))
    abstract = next(
        a
        for a in numbering.findall(qn("w:abstractNum"))
        if a.get(qn("w:abstractNumId")) == abstract_id
    )
    level = next(lv for lv in abstract.findall(qn("w:lvl")) if lv.get(qn("w:ilvl")) == "0")

    image_part = numbering_part.package.get_or_add_image_part(BytesIO(png))
    rid = numbering_part.relate_to(image_part, RT.IMAGE)
    existing = [int(p.get(qn("w:numPicBulletId"))) for p in numbering.findall(qn("w:numPicBullet"))]
    pic_id = max(existing, default=-1) + 1
    pic = parse_xml(
        f'<w:numPicBullet xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        f'xmlns:v="urn:schemas-microsoft-com:vml" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        f'w:numPicBulletId="{pic_id}"><w:pict>'
        f'<v:shape type="#_x0000_t75" style="width:9pt;height:9pt" o:bullet="t" '
        f'xmlns:o="urn:schemas-microsoft-com:office:office">'
        f'<v:imagedata r:id="{rid}" o:title=""/></v:shape></w:pict></w:numPicBullet>'
    )
    numbering.insert(0, pic)

    for tag in ("w:lvlPicBulletId", "w:numFmt", "w:lvlText"):
        for el in level.findall(qn(tag)):
            level.remove(el)
    start = level.find(qn("w:start"))
    anchor = list(level).index(start) + 1 if start is not None else 0
    for offset, xml in enumerate(
        (
            f'<w:lvlPicBulletId xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="{pic_id}"/>',
            '<w:numFmt xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="bullet"/>',
            '<w:lvlText xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="•"/>',
        )
    ):
        level.insert(anchor + offset, parse_xml(xml))
