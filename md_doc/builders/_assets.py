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


_EMPTY_THEAD_RE = re.compile(
    r"<thead>\s*<tr>(?:\s*<th[^>]*>\s*</th>)+\s*</tr>\s*</thead>\s*",
    re.IGNORECASE,
)


def _drop_empty_table_headers(html: str) -> str:
    """Remove ``<thead>`` blocks whose header cells are all empty.

    Markdown pipe tables *require* a header row, so ``| | |`` is the authoring
    idiom for a headerless table — without this pass the empty row still
    renders as a (theme-shaded) band in every format.
    """
    return _EMPTY_THEAD_RE.sub("", html)


_PAGE_SIZES_MM = {
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
    "a5": (148.0, 210.0),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
}
# Default geometry (A4 + PDF theme margins), used when no @page is found.
_DEFAULT_GEOMETRY = {
    "w": 210.0,
    "h": 297.0,
    "top": 25.0,
    "right": 20.0,
    "bottom": 22.0,
    "left": 25.0,
}


def _length_to_mm(token: str) -> float | None:
    """Convert a CSS length (mm/cm/in/pt/px) to mm."""
    m = re.match(r"^([\d.]+)\s*(mm|cm|in|pt|px)?$", token.strip())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2) or "mm"
    return {
        "mm": val,
        "cm": val * 10,
        "in": val * 25.4,
        "pt": val * 25.4 / 72,
        "px": val * 25.4 / 96,
    }[unit]


def _page_block_body(css_text: str) -> str | None:
    """Return the declaration body of the first unnamed ``@page`` block.

    Brace-aware: WeasyPrint themes nest margin boxes (``@top-right { … }``)
    inside ``@page``, and a naive ``[^}]*`` match truncates at the first inner
    ``}`` — silently dropping any ``margin``/``size`` declared after a nested
    box (the PDF read them fine; Word fell back to defaults). Nested blocks
    are stripped from the returned body.
    """
    m = re.search(r"@page\s*\{", css_text, re.IGNORECASE)
    if not m:
        return None
    depth = 1
    i = m.end()
    while i < len(css_text) and depth:
        if css_text[i] == "{":
            depth += 1
        elif css_text[i] == "}":
            depth -= 1
        i += 1
    body = css_text[m.end() : i - 1]
    return re.sub(r"@[^{}]*\{[^{}]*\}", "", body)


def _page_geometry(css_text: str | None) -> dict[str, float]:
    """Parse the ``@page { size; margin }`` from theme CSS into mm geometry.

    Mirrors the PDF's page so docx uses the same paper size and margins (and
    therefore the same text width → consistent pagination). Falls back to A4 +
    the standard margins when absent.
    """
    geom = dict(_DEFAULT_GEOMETRY)
    if not css_text:
        return geom
    body = _page_block_body(css_text)
    if body is None:
        return geom

    size_m = re.search(r"size:\s*([^;]+);", body, re.IGNORECASE)
    if size_m:
        tokens = size_m.group(1).lower().split()
        named = next((t for t in tokens if t in _PAGE_SIZES_MM), None)
        if named:
            w, h = _PAGE_SIZES_MM[named]
            if "landscape" in tokens:
                w, h = h, w
            geom["w"], geom["h"] = w, h
        else:
            lengths: list[float] = [x for t in tokens if (x := _length_to_mm(t)) is not None]
            if len(lengths) >= 2:
                geom["w"], geom["h"] = lengths[0], lengths[1]

    margin_m = re.search(r"margin:\s*([^;]+);", body, re.IGNORECASE)
    if margin_m:
        vals: list[float] = [
            v for t in margin_m.group(1).split() if (v := _length_to_mm(t)) is not None
        ]
        if len(vals) == 1:
            geom["top"] = geom["right"] = geom["bottom"] = geom["left"] = vals[0]
        elif len(vals) == 2:
            geom["top"] = geom["bottom"] = vals[0]
            geom["right"] = geom["left"] = vals[1]
        elif len(vals) == 3:
            geom["top"], geom["right"], geom["bottom"] = vals[:3]
            geom["left"] = vals[1]
        elif len(vals) >= 4:
            geom["top"], geom["right"], geom["bottom"], geom["left"] = vals[:4]

    # Word-only knobs: how far the header/footer text sits from the page edge
    # (Word's "header/footer from edge"; python-docx defaults to 12.7mm).
    # Custom properties are valid CSS, so WeasyPrint ignores them harmlessly:
    #   @page { --docx-header-distance: 8mm; --docx-footer-distance: 8mm; }
    for prop, key in (
        ("--docx-header-distance", "header_distance"),
        ("--docx-footer-distance", "footer_distance"),
    ):
        dm = re.search(re.escape(prop) + r":\s*([^;]+);?", body, re.IGNORECASE)
        if dm:
            mm = _length_to_mm(dm.group(1).strip())
            if mm is not None:
                geom[key] = mm
    return geom


# ---------------------------------------------------------------------------
# Brand defaults from theme CSS (--mddoc-* custom properties)
# ---------------------------------------------------------------------------

# Custom property (without the --mddoc- prefix) → config key it defaults.
# Feature toggles (page_header_bar, cover_page, …) and content (texts, logos)
# stay YAML-only by design — these are the pure *look* values, so the brand
# can live in the theme CSS while YAML overrides per folder/document.
_MDDOC_PROP_TO_KEY = {
    "header-bar-color": "page_header_bar_color",
    "header-bar-text-color": "page_header_bar_text_color",
    "header-bar-height": "page_header_bar_height",
    "header-bar-padding": "page_header_bar_padding",
    "header-logo-height": "header_logo_height",
    "cover-bar-height": "cover_bar_height",
    "cover-bar-top-height": "cover_bar_top_height",
    "cover-bar-bottom-height": "cover_bar_bottom_height",
    "cover-stripe-height": "cover_stripe_height",
    "cover-stripe-width": "cover_stripe_width",
    "cover-footer-color": "cover_footer_color",
    "section-bar-color": "section_bar_color",
    "section-bar-text-color": "section_bar_text_color",
}

_MDDOC_PROP_RE = re.compile(r"--mddoc-([a-z0-9-]+)\s*:\s*([^;}]+)", re.IGNORECASE)


def theme_config_defaults(css_text: str | None) -> dict[str, str]:
    """Extract ``--mddoc-*`` custom properties from theme CSS as config defaults."""
    if not css_text:
        return {}
    out: dict[str, str] = {}
    for m in _MDDOC_PROP_RE.finditer(css_text):
        key = _MDDOC_PROP_TO_KEY.get(m.group(1).lower())
        if key:
            out[key] = m.group(2).strip().strip("'\"")
    return out


def apply_theme_config_defaults(config: dict, css_text: str | None) -> dict:
    """Overlay ``--mddoc-*`` theme defaults under *config* (YAML always wins).

    Returns a new dict; a key set anywhere in the YAML cascade (any value,
    including an explicit empty string) is never touched.
    """
    defaults = theme_config_defaults(css_text)
    if not defaults:
        return config
    merged = dict(config)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
    return merged
