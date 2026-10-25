"""Render chart specs with md-doc's own renderer and tile them into contact sheets for review.

    uv run python tools/chart_contact_sheet.py SPEC_DIR OUT_DIR [--per-sheet 12] [--cols 3] [ids...]

SPEC_DIR holds <id>.json specs (written by `node scripts/chart-check.mjs --out SPEC_DIR`
in the presentation framework). Each is rendered by md_doc.charts (vl-convert) exactly as a
document build would, then drawn with its id on a sheet. Not part of the test suite - it is
for looking at the charts.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from md_doc import charts


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    opts = {a.split("=")[0]: a.split("=")[1] for a in argv if a.startswith("--") and "=" in a}
    per, cols = int(opts.get("--per-sheet", 12)), int(opts.get("--cols", 3))
    spec_dir, out_dir, only = Path(args[0]), Path(args[1]), args[2:]
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(spec_dir.glob("*.json"))
    if only:
        files = [f for f in files if f.stem in only]
    theme = {"primary": "#2563eb", "accent": "#374151", "brand": "1", "column_px": "460"}
    cells: list[tuple[str, Image.Image]] = []
    failed = []
    for f in files:
        try:
            png, _, _ = charts.render_png(f.read_text(), theme)
            cells.append((f.stem, Image.open(io.BytesIO(png)).convert("RGB")))
        except Exception as exc:  # report and keep going
            failed.append((f.stem, str(exc).splitlines()[0][:140]))
    cw, ch = 560, 400
    for n in range(0, len(cells), per):
        batch = cells[n : n + per]
        rows = (len(batch) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cw, rows * (ch + 22)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, (name, img) in enumerate(batch):
            img.thumbnail((cw - 16, ch - 8))
            x, y = (i % cols) * cw + 8, (i // cols) * (ch + 22)
            draw.text((x, y + 4), name, fill="#d03b3b")
            sheet.paste(img, (x, y + 20))
            draw.rectangle([x - 4, y + 1, x + cw - 12, y + ch + 18], outline="#dddddd")
        sheet.save(out_dir / f"sheet-{n // per + 1:02d}.png")
    for name, msg in failed:
        print(f"FAILED {name}: {msg}")
    print(f"{len(cells)} rendered, {len(failed)} failed -> {out_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
