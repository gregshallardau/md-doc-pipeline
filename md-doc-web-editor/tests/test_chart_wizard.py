"""The chart wizard (static/chart-wizard.js) and the endpoints and assets behind it."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from md_doc_web_editor.server import create_app

STATIC = Path(__file__).resolve().parent.parent / "md_doc_web_editor" / "static"
WIZARD = STATIC / "chart-wizard.js"
VEGA = STATIC / "vendor" / "vega-6.2.0"


def test_wizard_is_byte_identical_to_the_presentation_framework_copy():
    recorded = (Path(__file__).parent / "chart-wizard.sha256").read_text().strip()
    assert hashlib.sha256(WIZARD.read_bytes()).hexdigest() == recorded, (
        "chart-wizard.js changed: copy it from presentation-framework/editor/static/ "
        "(the canonical copy) and update chart-wizard.sha256 in BOTH repos"
    )


def test_vega_is_vendored_with_matching_manifest_hashes():
    manifest = json.loads((STATIC / "vendor" / "manifest.json").read_text())
    entry = next(e for e in manifest if e["package"] == "vega-6.2.0")
    assert {"vega.min.js", "vega-lite.min.js", "vega-embed.min.js"} <= set(entry["files"])
    for name, digest in entry["files"].items():
        assert hashlib.sha256((VEGA / name).read_bytes()).hexdigest() == digest, name


def test_vega_assets_and_wizard_are_served_locally(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        page = client.get("/")
        assert "/static/chart-wizard.js" in page.text
        for asset in (
            "chart-wizard.js",
            *(f"vendor/vega-6.2.0/{n}.min.js" for n in ("vega", "vega-lite", "vega-embed")),
        ):
            result = client.get("/static/" + asset)
            assert result.status_code == 200, asset
            assert result.headers["content-type"].startswith("text/javascript"), asset


def test_chart_config_endpoint_uses_the_documents_theme(tmp_path):
    (tmp_path / "doc.md").write_text("# Doc\n")
    (tmp_path / "_pdf-theme.css").write_text("h1 { color: #0b6e4f; }\nh2 { color: #e07a1f; }\n")
    with TestClient(create_app(tmp_path)) as client:
        plain = client.get("/api/charts/config").json()
        themed = client.get("/api/charts/config", params={"path": "doc.md"}).json()
    assert plain["range"]["category"][0] != themed["range"]["category"][0]
    assert themed["range"]["category"][0].lower() == "#0b6e4f"
    assert themed["axis"]["labelAngle"] == 0


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the wizard")
def test_every_wizard_chart_renders_with_md_docs_renderer():
    """Wizard output (YAML in a ```chart fence) is what md-doc builds, for every chart type."""
    from md_doc import charts

    if not charts.available():
        pytest.skip("needs the charts extra")
    script = """
      const vm = require('vm'), fs = require('fs');
      const ctx = {}; ctx.window = ctx; vm.createContext(ctx);
      vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
      const W = ctx.ChartWizard, out = [];
      for (const c of W.CHART_TYPES) {
        const table = W.parseTable(W.SAMPLES[c.sample]);
        const types = Object.fromEntries(table.columns.map((n, i) => [n, W.inferType(table.rows.map((r) => r[i]))]));
        const map = W.autoMap(c, table, types, {});
        const opts = { agg: 'none', sort: 'data', stack: 'stacked', legend: true, points: true, title: 'A: title' };
        out.push({ id: c.id, code: W.codeFor('yaml-fence', W.buildSpec({ type: c.id, table, types, map, opts })) });
      }
      console.log(JSON.stringify(out));
    """
    result = subprocess.run(
        ["node", "-e", script, str(WIZARD)], capture_output=True, text=True, check=True
    )
    outputs = json.loads(result.stdout)
    assert len(outputs) >= 9
    for item in outputs:
        code = item["code"]
        assert code.startswith("```chart\n") and code.endswith("\n```\n"), item["id"]
        svg = charts.render_svg(code[len("```chart\n") : -len("\n```\n")])
        assert svg.startswith("<svg"), item["id"]
