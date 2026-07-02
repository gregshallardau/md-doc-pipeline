"""Shared helpers for the docx and pptx builders.

Image asset resolution and Mermaid-diagram rasterization are identical across
the Office builders, so they live here to be imported by both without coupling
one builder to the other.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# EMU per pixel at 96 DPI — used to size embedded raster images.
_EMU_PER_PX = 9525

_MERMAID_IMG_RE = re.compile(r"mermaid://(\d+)")


def _svg_to_png(svg: str, scale: float = 2.0) -> tuple[bytes, int, int] | None:
    """Rasterize an SVG string to PNG bytes via cairosvg.

    Returns ``(png_bytes, viewbox_w_px, viewbox_h_px)`` or ``None`` if cairosvg
    is unavailable. The viewBox dimensions are used to size the embedded image
    so diagrams keep their aspect ratio.
    """
    try:
        import cairosvg  # type: ignore
    except Exception:
        return None

    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if m:
        vb_w, vb_h = float(m.group(1)), float(m.group(2))
    else:
        vb_w, vb_h = 800.0, 600.0

    try:
        png = cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            output_width=int(vb_w * scale),
            output_height=int(vb_h * scale),
        )
    except Exception as exc:  # pragma: no cover - depends on system cairo
        logger.warning("Mermaid SVG rasterization failed: %s", exc)
        return None
    return png, int(vb_w), int(vb_h)


def _render_mermaid_to_images(
    html: str, theme: dict[str, str] | None
) -> tuple[str, list[tuple[bytes, int, int]]]:
    """Replace mermaid code blocks in *html* with ``<img src="mermaid://N">``.

    Returns the rewritten HTML and a list of ``(png_bytes, w_px, h_px)`` tuples
    indexed by N. Diagrams that can't be rasterized (cairosvg missing or a parse
    error) are left as-is so they still render as a code block.
    """
    from ..mermaid import _MERMAID_BLOCK_RE, _unescape_mermaid_source, render_to_svg

    images: list[tuple[bytes, int, int]] = []

    def _replace(m: re.Match) -> str:
        source = _unescape_mermaid_source(m.group(1))
        try:
            svg = render_to_svg(source, theme)
            png = _svg_to_png(svg)
        except Exception as exc:
            logger.warning("Mermaid render failed: %s", exc)
            png = None
        if png is None:
            return m.group(0)  # leave original code block
        images.append(png)
        idx = len(images) - 1
        return f'<p><img src="mermaid://{idx}"></p>'

    return _MERMAID_BLOCK_RE.sub(_replace, html), images


def _resolve_asset(filename: str, doc_path: Path | None, repo_root: Path | None) -> Path | None:
    """Resolve an asset (image) path: doc dir → ancestors → repo root."""
    p = Path(filename)
    if p.is_absolute():
        return p if p.exists() else None
    search_dirs: list[Path] = []
    if doc_path:
        d = doc_path.parent if doc_path.is_file() else doc_path
        search_dirs.append(d)
        if repo_root:
            try:
                rel = d.relative_to(repo_root)
                for i in range(len(rel.parts) - 1, 0, -1):
                    search_dirs.append(repo_root / Path(*rel.parts[:i]))
            except ValueError:
                pass
            search_dirs.append(repo_root)
    for d in search_dirs:
        candidate = d / filename
        if candidate.exists():
            return candidate
    return None
