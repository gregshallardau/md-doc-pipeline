"""Vega-Lite / Vega charts from fenced ``chart`` blocks.

A fenced block whose language is ``chart``, ``vega-lite`` or ``vega`` holds a
Vega-Lite (or Vega) specification written as YAML or JSON.  It is rendered with
``vl-convert`` -- the same Vega engine the presentation framework runs in the
browser -- so one spec gives the same chart in both places.

The spec carries data and encodings only.  Colours, fonts and axis styling come
from the document theme (the same tokens Mermaid diagrams use), merged under any
``config`` the spec sets itself.  Needs the ``charts`` extra
(``uv sync --extra charts``); without it the block stays a code block.
"""

from __future__ import annotations

import csv
import copy
import json
import logging
import re
import struct
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CHART_BLOCK_RE = re.compile(
    r'<pre><code\s+class="language-(?:chart|vega-lite|vega)">(.*?)</code></pre>',
    re.DOTALL,
)

# The Vega-Lite release the presentation framework's ``vega-lite`` package matches,
# pinned so a spec renders the same in documents and on slides.
VEGALITE_VERSION = "6.4"
COMPOUND_KEYS = ("repeat", "facet", "concat", "hconcat", "vconcat")
DEFAULT_WIDTH = 560
DEFAULT_HEIGHT = 320
_RASTER_SCALE = 2.0
_warned_missing = False


class ChartError(ValueError):
    """The chart spec could not be parsed or rendered."""


def available() -> bool:
    try:
        import vl_convert  # noqa: F401
    except Exception:
        return False
    return True


def _unescape(source: str) -> str:
    return (
        source.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )


def parse_spec(source: str) -> dict[str, Any]:
    """Parse the block body (YAML, of which JSON is a subset) into a spec dict."""
    try:
        spec = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise ChartError(f"invalid chart spec: {exc}") from exc
    if not isinstance(spec, dict):
        raise ChartError("a chart spec must be a mapping (Vega-Lite or Vega)")
    return spec


def is_vega(spec: dict[str, Any]) -> bool:
    """True for a full Vega spec, False for Vega-Lite (the default)."""
    schema = str(spec.get("$schema", ""))
    if schema:
        return "/vega/" in schema
    return "marks" in spec and "mark" not in spec


def vega_config(theme: dict[str, str] | None = None) -> dict[str, Any]:
    """Vega ``config`` from the diagram theme tokens (brand colours, font, ink)."""
    from .mermaid import _CATEGORICAL, _CATEGORICAL_DARK, _palette, _series_palette, _tokens

    t = _tokens(theme)
    given = theme or {}
    palette = _palette(t)
    if given.get("brand") == "1" and not given.get("palette"):
        # Lead with the brand primary only; a quiet accent (charcoal, grey) makes a poor second series.
        fallback = _CATEGORICAL_DARK if t.get("mode") == "dark" else _CATEGORICAL
        palette = _series_palette([t["primary"]], fallback)
    font = t["font"]
    ink, ink2, grid, baseline = t["ink"], t["ink2"], t["grid"], t["baseline"]
    return {
        "background": None,
        "font": font,
        "view": {"stroke": None},
        "range": {"category": palette, "ordinal": palette},
        "title": {"font": font, "color": ink, "fontSize": 14, "fontWeight": 600, "anchor": "start"},
        "axis": {
            "labelFont": font,
            "titleFont": font,
            "labelColor": ink2,
            "titleColor": ink2,
            "labelFontSize": 11,
            "titleFontSize": 11,
            "titleFontWeight": 500,
            "domainColor": baseline,
            "tickColor": baseline,
            "gridColor": grid,
            "tickSize": 5,
            "labelPadding": 2,
            "labelAngle": 0,
            "labelOverlap": True,
            "labelSeparation": 6,
        },
        "legend": {
            "labelFont": font,
            "titleFont": font,
            "labelColor": ink2,
            "titleColor": ink2,
            "labelFontSize": 11,
            "titleFontSize": 11,
            "symbolSize": 100,
        },
        "text": {"font": font, "color": ink, "fontSize": 11},
        "mark": {"color": palette[0]},
        "line": {"strokeWidth": 2},
        "point": {"size": 30},
        "circle": {"size": 30},
        "square": {"size": 30},
    }


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


DATASET_SCHEME = "vega-datasets:"
_DATA_DIR = Path(__file__).parent / "data"


def _builtin_dataset(name: str) -> Any:
    """A basemap shipped with md-doc (``vega-datasets:world-110m``), read from the package."""
    path = _DATA_DIR / f"{name}.json"
    if not re.fullmatch(r"[\w.-]+", name) or not path.is_file():
        known = ", ".join(sorted(p.stem for p in _DATA_DIR.glob("*.json")))
        raise ChartError(f"unknown built-in dataset {name!r} (available: {known})")
    return json.loads(path.read_text(encoding="utf-8"))


def _bundled_name(url: str, base_dir: Path | None) -> str | None:
    """The bundled basemap a url names: ``vega-datasets:us-10m``, or upstream's own ``data/us-10m.json``
    (unless the document has a file of that name, which wins)."""
    if url.startswith(DATASET_SCHEME):
        return url[len(DATASET_SCHEME) :]
    match = re.fullmatch(r"data/([\w.-]+)\.json", url)
    if match and (_DATA_DIR / f"{match.group(1)}.json").is_file():
        if base_dir is not None and (base_dir / url).is_file():
            return None
        return match.group(1)
    return None


def _inline_data(spec: Any, base_dir: Path | None) -> None:
    """Replace local ``data: {url: file.csv|json}`` with inline ``values``.

    The renderer is not given file access; reading the file here keeps builds
    offline and lets the path resolve relative to the document.
    """
    if isinstance(spec, list):
        for item in spec:
            _inline_data(item, base_dir)
        return
    if not isinstance(spec, dict):
        return
    data = spec.get("data")
    datasets = data if isinstance(data, list) else [data]
    for data in datasets:
        if not isinstance(data, dict) or not isinstance(data.get("url"), str):
            continue
        url = data["url"]
        bundled = _bundled_name(url, base_dir)
        if bundled:
            data["values"] = _builtin_dataset(bundled)
            del data["url"]
        elif not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
            path = Path(url)
            if not path.is_absolute() and base_dir is not None:
                path = base_dir / path
            if not path.is_file():
                raise ChartError(f"chart data file not found: {url}")
            suffix = path.suffix.lower()
            try:
                text = path.read_text(encoding="utf-8-sig")
                if suffix == ".json":
                    values = json.loads(text)
                elif suffix in (".csv", ".tsv"):
                    delim = "\t" if suffix == ".tsv" else ","
                    values = [
                        {k: _coerce(v) for k, v in row.items()}
                        for row in csv.DictReader(text.splitlines(), delimiter=delim)
                    ]
                else:
                    raise ChartError(f"unsupported chart data file type: {url}")
            except (OSError, UnicodeError, ValueError, csv.Error) as exc:
                raise ChartError(f"could not read chart data file {url}: {exc}") from exc
            data["values"] = values
            del data["url"]
    for key, value in spec.items():
        if key != "values" and isinstance(value, (dict, list)):  # inline rows are data, not spec
            _inline_data(value, base_dir)


def _coerce(value: str | None) -> Any:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def prepare_spec(
    source: str,
    theme: dict[str, str] | None = None,
    base_dir: Path | None = None,
    background: str | None = None,
) -> dict[str, Any]:
    """Parse *source* and apply theme config, default size and local data."""
    spec = parse_spec(source)
    column = int(float((theme or {}).get("column_px", DEFAULT_WIDTH)))
    width = min(column, 720) if column else DEFAULT_WIDTH
    # Repeats, facets and concatenations size their inner views; a top-level width would be invalid.
    if not any(key in spec for key in COMPOUND_KEYS):
        spec.setdefault("width", width)
        if spec.get("width") == "container":
            spec["width"] = width
        # width/height size the whole chart (axes and legend included), not just the plot
        spec.setdefault("autosize", {"type": "fit", "contains": "padding"})
        spec.setdefault("height", DEFAULT_HEIGHT)
        if spec.get("height") == "container":
            spec["height"] = DEFAULT_HEIGHT
    config = vega_config(theme)
    if background:
        config["background"] = background
    spec["config"] = _deep_merge(config, spec.get("config") or {})
    _inline_data(spec, base_dir)
    return spec


# Vega transforms that measure text or draw density grids on a canvas. vl-convert's Vega runtime has none: it logs the
# error and returns a chart with the layer missing (a blank word cloud), and the next render then fails once.
_CANVAS_TRANSFORMS = {"wordcloud": "its word layout", "kde2d": "its density grid"}


def _needs_canvas(node: Any) -> str | None:
    """The first canvas-only transform used anywhere in the spec, if any."""
    if isinstance(node, list):
        for item in node:
            found = _needs_canvas(item)
            if found:
                return found
    elif isinstance(node, dict):
        kind = node.get("type")
        if isinstance(kind, str) and kind in _CANVAS_TRANSFORMS:
            return kind
        for key, value in node.items():
            if key != "values":
                found = _needs_canvas(value)
                if found:
                    return found
    return None


def _check_renderable(spec: dict[str, Any]) -> None:
    kind = _needs_canvas(spec)
    if kind:
        raise ChartError(
            f"{_CANVAS_TRANSFORMS.get(kind, kind)} (Vega's {kind} transform) needs a canvas that the PDF/Word "
            "renderer does not have; this chart draws in the browser and on slides"
        )


def _recover(vlc: Any) -> None:
    """After a failed render the next one can fail once; a trivial render absorbs that."""
    for _ in range(2):
        try:
            vlc.vegalite_to_svg(
                {"data": {"values": [{"a": 1}]}, "mark": "point"}, vl_version=VEGALITE_VERSION
            )
            return
        except Exception:
            continue


def render_svg(
    source: str,
    theme: dict[str, str] | None = None,
    base_dir: Path | None = None,
) -> str:
    spec = prepare_spec(source, theme, base_dir)
    _check_renderable(spec)
    try:
        import vl_convert as vlc
    except Exception as exc:
        raise ChartError("charts need the 'charts' extra (uv sync --extra charts)") from exc
    try:
        if is_vega(spec):
            return vlc.vega_to_svg(spec)
        return vlc.vegalite_to_svg(spec, vl_version=VEGALITE_VERSION)
    except Exception as exc:
        _recover(vlc)
        raise ChartError(str(exc).splitlines()[0] if str(exc) else "render failed") from exc


def render_png(
    source: str,
    theme: dict[str, str] | None = None,
    base_dir: Path | None = None,
) -> tuple[bytes, int, int]:
    """PNG bytes plus the natural size in px, for Word and PowerPoint."""
    surface = (theme or {}).get("surface") or "#ffffff"
    spec = prepare_spec(source, theme, base_dir, background=surface)
    _check_renderable(spec)
    try:
        import vl_convert as vlc
    except Exception as exc:
        raise ChartError("charts need the 'charts' extra (uv sync --extra charts)") from exc
    try:
        if is_vega(spec):
            png = vlc.vega_to_png(spec, scale=_RASTER_SCALE)
        else:
            png = vlc.vegalite_to_png(spec, vl_version=VEGALITE_VERSION, scale=_RASTER_SCALE)
    except Exception as exc:
        _recover(vlc)
        raise ChartError(str(exc).splitlines()[0] if str(exc) else "render failed") from exc
    w, h = struct.unpack(">II", png[16:24])
    return png, int(w / _RASTER_SCALE), int(h / _RASTER_SCALE)


def _warn_missing_once() -> None:
    global _warned_missing
    if not _warned_missing:
        _warned_missing = True
        logger.warning("chart blocks need the 'charts' extra (uv sync --extra charts)")


def _wrap(svg: str) -> str:
    m = re.search(r'\bwidth="([\d.]+)"', svg)
    size = f"width:{float(m.group(1)):.0f}px;max-width:100%;" if m else ""
    return f'<div class="chart-figure" style="{size}margin:10pt auto 14pt auto;">{svg}</div>'


def process_html(
    html: str,
    theme: dict[str, str] | None = None,
    base_dir: Path | None = None,
) -> str:
    """Replace chart code blocks in HTML with rendered SVG (PDF builder)."""
    if not _CHART_BLOCK_RE.search(html):
        return html
    if not available():
        _warn_missing_once()
        return html

    def _replace(m: re.Match) -> str:
        try:
            return _wrap(render_svg(_unescape(m.group(1)), theme, base_dir))
        except ChartError as exc:
            logger.warning("Chart: %s; leaving the source as a code block", exc)
            return m.group(0)

    return _CHART_BLOCK_RE.sub(_replace, html)


def render_to_images(
    html: str,
    theme: dict[str, str] | None,
    images: list[tuple[bytes, int, int]],
    base_dir: Path | None = None,
) -> str:
    """Swap chart blocks for ``<img src="mermaid://N">`` references.

    Appends PNGs to *images* (the list Mermaid rasterisation already filled), so
    the docx and pptx builders embed them through the same picture path.
    """
    if not _CHART_BLOCK_RE.search(html):
        return html
    if not available():
        _warn_missing_once()
        return html

    def _replace(m: re.Match) -> str:
        try:
            png = render_png(_unescape(m.group(1)), theme, base_dir)
        except ChartError as exc:
            logger.warning("Chart: %s; leaving the source as a code block", exc)
            return m.group(0)
        images.append(png)
        return f'<p><img src="mermaid://{len(images) - 1}" width="{png[1]}"></p>'

    return _CHART_BLOCK_RE.sub(_replace, html)
