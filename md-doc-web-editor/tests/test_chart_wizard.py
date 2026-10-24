"""The chart wizard (static/chart-*.js) and the endpoints and assets behind it."""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from md_doc_web_editor.server import create_app

STATIC = Path(__file__).resolve().parent.parent / "md_doc_web_editor" / "static"
VEGA = STATIC / "vendor" / "vega-6.2.0"
CHART_FILES = sorted(p.name for p in STATIC.glob("chart-*.js"))


def test_shared_files_match_the_presentation_framework_copies():
    manifest = json.loads((Path(__file__).parent / "chart-wizard.sha256.json").read_text())
    assert CHART_FILES == sorted(manifest), (
        "the set of chart-*.js files changed: run `node scripts/chart-manifest.mjs --copy ...` "
        "in presentation-framework (the canonical copy) to sync both repos"
    )
    for name in CHART_FILES:
        digest = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()
        assert digest == manifest[name], (
            f"{name} changed: copy it from presentation-framework/editor/static/ "
            "(node scripts/chart-manifest.mjs --copy) and refresh chart-wizard.sha256.json in BOTH repos"
        )


def test_wizard_lists_every_catalogue_file_it_loads():
    wizard = (STATIC / "chart-wizard.js").read_text()
    listed = set(re.findall(r"'(chart-[\w-]+\.js)'", wizard))
    assert listed == {f for f in CHART_FILES if f != "chart-wizard.js"}


def test_vendored_files_match_the_manifest():
    manifest = json.loads((STATIC / "vendor" / "manifest.json").read_text())
    entry = next(e for e in manifest if e["package"] == "vega-6.2.0")
    assert {
        "vega.min.js",
        "vega-lite.min.js",
        "vega-embed.min.js",
        "datasets/world-110m.json",
        "datasets/us-10m.json",
    } <= set(entry["files"])
    for name, digest in entry["files"].items():
        assert hashlib.sha256((VEGA / name).read_bytes()).hexdigest() == digest, name


def test_wizard_vendor_and_basemaps_are_served_locally(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert "/static/chart-wizard.js" in client.get("/").text
        assets = [
            *CHART_FILES,
            *(f"vendor/vega-6.2.0/{n}.min.js" for n in ("vega", "vega-lite", "vega-embed")),
        ]
        for asset in [
            *assets,
            "vendor/vega-6.2.0/datasets/world-110m.json",
            "vendor/vega-6.2.0/datasets/us-10m.json",
        ]:
            result = client.get("/static/" + asset)
            assert result.status_code == 200, asset


def test_chart_config_endpoint_uses_the_documents_theme(tmp_path):
    (tmp_path / "doc.md").write_text("# Doc\n")
    (tmp_path / "_pdf-theme.css").write_text("h1 { color: #0b6e4f; }\nh2 { color: #e07a1f; }\n")
    with TestClient(create_app(tmp_path)) as client:
        plain = client.get("/api/charts/config").json()
        themed = client.get("/api/charts/config", params={"path": "doc.md"}).json()
    assert plain["range"]["category"][0] != themed["range"]["category"][0]
    assert themed["range"]["category"][0].lower() == "#0b6e4f"
    assert themed["axis"]["labelAngle"] == 0


NODE_DUMP = """
const vm = require('vm'), fs = require('fs'), path = require('path');
const dir = process.argv[1];
const ctx = { console }; ctx.window = ctx; ctx.globalThis = ctx; vm.createContext(ctx);
const files = fs.readdirSync(dir).filter((f) => /^chart-(core|templates|geo-data|types-.*)\\.js$/.test(f)).sort((a, b) => { const rank = (f) => (f.includes('core') ? 0 : f.includes('templates') ? 1 : f.includes('upstream') ? 3 : 2); return rank(a) - rank(b) || a.localeCompare(b); });
for (const f of files) vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx, { filename: f });
const C = ctx.ChartCatalog;
const out = C.TYPES.map((t) => { const spec = JSON.parse(JSON.stringify(C.sampleSpec(t))); return { id: t.id, spec, code: C.codeFor('yaml-fence', spec) }; });
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def wizard_charts():
    if shutil.which("node") is None:
        pytest.skip("needs node to run the wizard")
    result = subprocess.run(
        ["node", "-e", NODE_DUMP, str(STATIC)], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def test_the_catalogue_is_complete(wizard_charts):
    ids = [c["id"] for c in wizard_charts]
    assert len(ids) == len(set(ids)) and len(ids) >= 80
    for expected in (
        "bar",
        "line",
        "scatter",
        "pie",
        "heatmap",
        "box",
        "sankey",
        "treemap",
        "map-world",
        "word-cloud",
        "radar",
    ):
        assert expected in ids


def test_every_wizard_chart_survives_yaml_and_renders_with_md_docs_renderer(wizard_charts):
    """What the wizard inserts is what md-doc builds: PyYAML reads it back and vl-convert draws it."""
    from md_doc import charts

    if not charts.available():
        pytest.skip("needs the charts extra")
    for item in wizard_charts:
        code = item["code"]
        assert code.startswith("```chart\n") and code.endswith("\n```\n"), item["id"]
        source = code[len("```chart\n") : -len("\n```\n")]
        assert (
            yaml.safe_load(source) == item["spec"]
        ), f"{item['id']}: PyYAML disagrees with the wizard's YAML"
        svg = charts.render_svg(source)
        assert svg.startswith("<svg") and len(svg) > 500, item["id"]


def test_md_docs_renderer_is_deterministic_for_every_chart(wizard_charts):
    """No random layouts or bootstrapped intervals: a build gives the same chart every time."""
    from md_doc import charts

    if not charts.available():
        pytest.skip("needs the charts extra")
    ids = re.compile(r"(clip|gradient_)\d+")
    for item in wizard_charts:
        source = item["code"][len("```chart\n") : -len("\n```\n")]
        assert ids.sub(r"\1", charts.render_svg(source)) == ids.sub(
            r"\1", charts.render_svg(source)
        ), item["id"]


def test_every_chart_type_is_in_the_handbook(wizard_charts):
    handbook = (Path(__file__).resolve().parents[2] / "docs" / "handbook.md").read_text()
    missing = [c["id"] for c in wizard_charts if f"| `{c['id']}` |" not in handbook]
    assert (
        not missing
    ), f"chart types missing from docs/handbook.md#markdown-charts-catalogue: {missing}"
