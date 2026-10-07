from pathlib import Path
import json
import logging
import sys
import subprocess
import traceback
from concurrent.futures import ThreadPoolExecutor
import argparse
import shutil
import tempfile

parser = argparse.ArgumentParser(
    description="Build every sample as PDF and Word and render Word with LibreOffice."
)
parser.add_argument("--output", type=Path, default=Path("build/sample-gallery"))
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
OUT = args.output.resolve()
sys.path.insert(0, str(ROOT))
from md_doc.cli import _discover_markdown, _render_config_strings  # noqa: E402
from md_doc.config import load_config  # noqa: E402
from md_doc.renderer import render  # noqa: E402
from md_doc.builders.pdf import build as pdf  # noqa: E402
from md_doc.builders.docx import build as word  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logging.disable(logging.INFO)
paths = _discover_markdown(ROOT / "examples") + _discover_markdown(ROOT / "docs/examples")

records = []
for p in paths:
    rel = p.relative_to(ROOT)
    folder = OUT / rel.with_suffix("")
    folder.mkdir(parents=True, exist_ok=True)
    cfg = _render_config_strings(load_config(p, repo_root=ROOT))
    cfg.setdefault("date", "7 October 2026")
    rec = {
        "source": str(rel),
        "folder": str(folder.relative_to(OUT)),
        "title": cfg.get("title", p.stem),
        "pdf_forms": bool(cfg.get("pdf_forms")),
        "outputs": [],
        "errors": [],
    }
    try:
        rendered = render(p, repo_root=ROOT, extra_context=cfg)
        (folder / "source.md").write_text(rendered)
        (folder / "config.json").write_text(json.dumps(cfg, default=str, indent=2))
        for fmt, fn in [("pdf", pdf), ("docx", word)]:
            try:
                fn(rendered, cfg, folder / f"{p.stem}.{fmt}", doc_path=p, repo_root=ROOT)
                rec["outputs"].append(fmt)
            except Exception as e:
                rec["errors"].append(f"{fmt}: {e}")
                traceback.print_exc()
        if cfg.get("pdf_forms") or "[[ " in rendered or "[[" in rendered:
            word(
                rendered,
                cfg,
                folder / f"{p.stem}.dotx",
                output_format="dotx",
                doc_path=p,
                repo_root=ROOT,
            )
            rec["outputs"].append("dotx")
            if "[[" in rendered:
                word(
                    rendered,
                    {**cfg, "dotx_field_type": "merge"},
                    folder / f"{p.stem}-merge.dotx",
                    output_format="dotx",
                    doc_path=p,
                    repo_root=ROOT,
                )
                rec["outputs"].append("merge.dotx")
    except Exception as e:
        rec["errors"].append(str(e))
        traceback.print_exc()
    print(json.dumps(rec), flush=True)
    records.append(rec)
(OUT / "build-manifest.json").write_text(json.dumps(records, indent=2))


def render_word(rec):
    folder = OUT / rec["folder"]
    doc = folder / (Path(rec["source"]).stem + ".docx")
    if not doc.exists():
        return
    renderer = shutil.which("soffice") or shutil.which("libreoffice")
    if not renderer:
        raise RuntimeError("Install LibreOffice Writer to render the Word exports")
    target = folder / "word-render"
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="md-doc-gallery-office-") as profile:
        cmd = [
            renderer,
            "-env:UserInstallation=" + Path(profile).as_uri(),
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(target),
            str(doc),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    (folder / "word-render.log").write_text(r.stdout + r.stderr)
    if r.returncode or not (target / (doc.stem + ".pdf")).exists():
        raise RuntimeError(f"Word rendering failed for {doc}: {r.stdout} {r.stderr}")
    print("RENDER", rec["source"], r.returncode, flush=True)


with ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(render_word, records))

if any(r["errors"] for r in records):
    raise SystemExit("One or more exports failed; inspect build-manifest.json")
