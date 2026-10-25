"""Vega-Lite / Vega ``chart`` blocks."""

from __future__ import annotations

import pytest

from md_doc import charts

pytestmark = pytest.mark.skipif(not charts.available(), reason="vl-convert not installed")

LINE = """
data:
  values:
    - {m: Jan, v: 12}
    - {m: Feb, v: 19}
mark: line
encoding:
  x: {field: m, type: ordinal}
  y: {field: v, type: quantitative}
"""


def _block(source: str, lang: str = "chart") -> str:
    escaped = source.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<pre><code class="language-{lang}">{escaped}</code></pre>'


def test_render_svg():
    svg = charts.render_svg(LINE)
    assert svg.startswith("<svg")


def test_theme_palette_is_applied():
    theme = {"primary": "#0b6e4f", "accent": "#e07a1f", "brand": "1"}
    svg = charts.render_svg(LINE, theme)
    assert "#0b6e4f" in svg.lower()


def test_user_config_wins_over_theme():
    spec = charts.prepare_spec(LINE + "config: {font: Courier}\n")
    assert spec["config"]["font"] == "Courier"
    assert spec["config"]["axis"]["labelAngle"] == 0


def test_default_size_follows_column_and_container_means_default():
    spec = charts.prepare_spec(LINE, {"column_px": "500"})
    assert spec["width"] == 500
    spec = charts.prepare_spec(LINE + "width: container\n", {"column_px": "500"})
    assert spec["width"] == 500
    spec = charts.prepare_spec(LINE + "width: 300\n", {"column_px": "500"})
    assert spec["width"] == 300


def test_csv_data_is_inlined(tmp_path):
    (tmp_path / "d.csv").write_text("m,v\nJan,1\nFeb,2.5\n")
    spec = charts.prepare_spec(
        "data: {url: d.csv}\nmark: bar\nencoding: {x: {field: m}, y: {field: v}}",
        base_dir=tmp_path,
    )
    assert spec["data"]["values"] == [{"m": "Jan", "v": 1}, {"m": "Feb", "v": 2.5}]


def test_missing_data_file_is_an_error(tmp_path):
    with pytest.raises(charts.ChartError):
        charts.prepare_spec("data: {url: nope.csv}\nmark: bar", base_dir=tmp_path)


def test_vega_detection():
    assert not charts.is_vega({"mark": "bar"})
    assert charts.is_vega({"$schema": "https://vega.github.io/schema/vega/v5.json"})
    assert charts.is_vega({"marks": []})


def test_png_has_natural_size():
    png, w, h = charts.render_png(LINE)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert w > 100 and h > 100


def test_process_html_replaces_all_languages_and_keeps_bad_blocks():
    html = _block(LINE) + _block(LINE, "vega-lite") + _block("not: [valid")
    out = charts.process_html(html)
    assert out.count('class="chart-figure"') == 2
    assert out.count("language-chart") == 1  # the invalid block is left as code


def test_render_to_images_extends_the_shared_image_list():
    images = [(b"existing", 1, 1)]
    out = charts.render_to_images(_block(LINE), None, images)
    assert len(images) == 2
    assert 'src="mermaid://1"' in out


def _key_paths(obj, prefix=""):
    out = []
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        out += _key_paths(value, path) if isinstance(value, dict) else [path]
    return sorted(out)


def test_config_keys_match_the_presentation_framework():
    """``vega_config`` and the deck's ``vegaConfig`` (src/lib/vega.js) set the same keys.

    The same JSON lives in presentation-framework at src/lib/fixtures/chart-config-keys.json;
    change both files together when a key is added or removed.
    """
    import json
    from pathlib import Path

    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "chart_config_keys.json").read_text()
    )
    assert _key_paths(charts.vega_config({"primary": "#2563eb", "accent": "#374151"})) == expected


def test_builtin_basemaps_resolve_locally_and_unknown_ones_fail():
    spec = charts.prepare_spec(
        "data: {url: 'vega-datasets:world-110m', format: {type: topojson, feature: countries}}\n"
        "mark: geoshape\nprojection: {type: equalEarth}"
    )
    assert "url" not in spec["data"] and spec["data"]["values"]["type"] == "Topology"
    assert spec["data"]["format"]["feature"] == "countries"
    with pytest.raises(charts.ChartError, match="unknown built-in dataset"):
        charts.prepare_spec("data: {url: 'vega-datasets:nope'}\nmark: bar")
    with pytest.raises(charts.ChartError):
        charts.prepare_spec("data: {url: 'vega-datasets:../../etc/passwd'}\nmark: bar")


def test_compound_specs_are_not_given_a_top_level_size():
    spec = charts.prepare_spec(
        "data: {values: [{a: 1}]}\nrepeat: {column: [a]}\nspec: {mark: point, encoding: {x: {field: {repeat: column}, type: quantitative}}}"
    )
    assert "width" not in spec and "height" not in spec and "autosize" not in spec
    assert "width" in charts.prepare_spec(
        "data: {values: [{a: 1}]}\nmark: point\nencoding: {x: {field: a, type: quantitative}}"
    )


def test_a_full_vega_spec_renders():
    svg = charts.render_svg(
        "$schema: https://vega.github.io/schema/vega/v6.json\nwidth: 80\nheight: 40\n"
        'marks: [{type: rect, encode: {enter: {x: {value: 0}, y: {value: 0}, width: {value: 40}, height: {value: 20}, fill: {value: "#2563eb"}}}}]'
    )
    assert "<svg" in svg and "#2563eb" in svg.lower()


def test_upstream_basemap_urls_resolve_to_the_bundled_files(tmp_path):
    """Upstream examples say `data/us-10m.json`; a pasted block loads the bundled basemap without edits."""
    src = "data: {url: data/us-10m.json, format: {type: topojson, feature: states}}\nmark: geoshape"
    spec = charts.prepare_spec(src, base_dir=tmp_path)
    assert "url" not in spec["data"] and spec["data"]["values"]["type"] == "Topology"
    assert spec["data"]["format"]["feature"] == "states"
    # a file of that name beside the document wins
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "us-10m.json").write_text('[{"id": 1}]')
    assert charts.prepare_spec(src, base_dir=tmp_path)["data"]["values"] == [{"id": 1}]
    # other upstream file names are not guessed at
    with pytest.raises(charts.ChartError):
        charts.prepare_spec("data: {url: data/cars.json}\nmark: bar", base_dir=tmp_path)


_WORDCLOUD = (
    "$schema: https://vega.github.io/schema/vega/v6.json\nwidth: 200\nheight: 100\n"
    "data: [{name: t, values: [{text: hello world hello}], transform: [{type: wordcloud, size: [200, 100], text: {field: text}}]}]\n"
    "marks: [{type: text, from: {data: t}, encode: {enter: {text: {field: text}, x: {field: x}, y: {field: y}}}}]"
)


def test_canvas_only_transforms_fail_clearly_instead_of_drawing_a_blank_chart():
    """vl-convert has no canvas: a word cloud used to come back empty with no error."""
    with pytest.raises(charts.ChartError, match="canvas"):
        charts.render_svg(_WORDCLOUD)
    with pytest.raises(charts.ChartError, match="canvas"):
        charts.render_png(_WORDCLOUD)
    # the build leaves the source in place and says why, and the chart after it still renders
    html = (
        f'<pre><code class="language-chart">{_WORDCLOUD}</code></pre>'
        '<pre><code class="language-chart">mark: bar\ndata: {values: [{a: 1}]}\nencoding: {x: {field: a, type: nominal}}</code></pre>'
    )
    out = charts.process_html(html)
    assert "wordcloud" in out and "<svg" in out


def test_a_failed_render_does_not_break_the_next_chart():
    bad = (
        "$schema: https://vega.github.io/schema/vega/v6.json\nwidth: 50\nheight: 50\n"
        "data: [{name: t, values: [{a: 1}], transform: [{type: nosuchtransform}]}]"
    )
    good = "mark: bar\ndata: {values: [{a: 1}]}\nencoding: {x: {field: a, type: nominal}}"
    with pytest.raises(charts.ChartError):
        charts.render_svg(bad)
    for _ in range(3):
        assert charts.render_svg(good).startswith("<svg")


def test_full_vega_inlines_multiple_datasets_and_keeps_transforms(tmp_path):
    (tmp_path / "d.csv").write_text("x,v\na,2\n")
    spec = charts.prepare_spec(
        "marks: []\ndata:\n"
        "  - {name: local, url: d.csv, transform: [{type: filter, expr: 'datum.v > 0'}]}\n"
        "  - {name: map, url: 'vega-datasets:us-10m', format: {type: topojson, feature: states}}\n"
        "  - {name: remote, url: 'https://example.com/data.json'}\n",
        base_dir=tmp_path,
    )
    local, basemap, remote = spec["data"]
    assert local == {
        "name": "local",
        "values": [{"x": "a", "v": 2}],
        "transform": [{"type": "filter", "expr": "datum.v > 0"}],
    }
    assert basemap["values"]["type"] == "Topology" and "url" not in basemap
    assert basemap["format"] == {"type": "topojson", "feature": "states"}
    assert remote["url"] == "https://example.com/data.json"


@pytest.mark.parametrize(
    "format_options,contents",
    [
        ({"property": "rows"}, '{"rows": [{"x": 1}]}'),
        ({"type": "topojson", "feature": "countries"}, '{"type": "Topology", "objects": {}}'),
    ],
)
def test_local_json_preserves_format(tmp_path, format_options, contents):
    import json

    (tmp_path / "d.json").write_text(contents)
    source = json.dumps({"data": {"url": "d.json", "format": format_options}, "mark": "point"})
    spec = charts.prepare_spec(source, base_dir=tmp_path)
    assert spec["data"] == {"values": json.loads(contents), "format": format_options}


@pytest.mark.parametrize("contents", [b"{broken", b"\xff"])
def test_bad_local_data_uses_source_fallback(tmp_path, contents):
    (tmp_path / "bad.json").write_bytes(contents)
    source = "data: {url: bad.json}\nmark: point"
    with pytest.raises(charts.ChartError, match="could not read chart data file"):
        charts.prepare_spec(source, base_dir=tmp_path)
    html = _block(source)
    assert charts.process_html(html, base_dir=tmp_path) == html
    images = []
    assert charts.render_to_images(html, None, images, base_dir=tmp_path) == html
    assert images == []


def test_unreadable_local_data_uses_chart_error(tmp_path, monkeypatch):
    from pathlib import Path

    path = tmp_path / "d.json"
    path.write_text("[]")
    read_text = Path.read_text

    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("denied")
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(charts.ChartError, match="denied"):
        charts.prepare_spec("data: {url: d.json}\nmark: point", base_dir=tmp_path)
