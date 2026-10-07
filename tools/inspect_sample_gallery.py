from pathlib import Path
import json
import zipfile
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
import argparse

parser = argparse.ArgumentParser(
    description="Measure generated PDF/Word pages and create side-by-side visual diagnostics. Equal page counts do not prove parity."
)
parser.add_argument("--output", type=Path, default=Path("build/sample-gallery"))
ROOT = parser.parse_args().output.resolve()
records = json.loads((ROOT / "build-manifest.json").read_text())
report = []
for r in records:
    folder = ROOT / r["folder"]
    stem = Path(r["source"]).stem
    row = {k: r[k] for k in ("source", "folder", "title", "errors")}
    thumbs = []
    for label, p in [
        ("pdf", folder / f"{stem}.pdf"),
        ("word", folder / "word-render" / f"{stem}.pdf"),
    ]:
        data = {"pages": 0, "sizes_mm": [], "text": [], "page_ink": []}
        dest = folder / (label + "-pages")
        dest.mkdir(exist_ok=True)
        with pdfium.PdfDocument(p) as d:
            data["pages"] = len(d)
            for i, page in enumerate(d):
                data["sizes_mm"].append([round(x * 25.4 / 72, 2) for x in page.get_size()])
                data["text"].append(page.get_textpage().get_text_range())
                im = page.render(scale=110 / 72).to_pil().convert("RGB")
                im.save(dest / f"page-{i+1}.png")
                small = im.copy()
                small.thumbnail((280, 396))
                thumbs.append((i, label, small))
        data["words"] = len(" ".join(data["text"]).split())
        row[label] = data
        if label == "word":
            with zipfile.ZipFile(folder / f"{stem}.docx") as z:
                xml = z.read("word/document.xml").decode()
                row["docx_structures"] = {
                    "images": xml.count("<pic:pic>"),
                    "equations": xml.count("<m:oMath>"),
                    "tables": xml.count("<w:tbl>"),
                    "fields": xml.count("<w:ffData>"),
                }
    n = max(row["pdf"]["pages"], row["word"]["pages"])
    sheet = Image.new("RGB", (600, 430 * n), "#ddd")
    draw = ImageDraw.Draw(sheet)
    for i, label, im in thumbs:
        x = 10 if label == "pdf" else 310
        y = 430 * i
        draw.text((x, y + 3), f"{label.upper()} page {i+1}", fill="black")
        sheet.paste(im, (x, y + 25))
    sheet.save(folder / "comparison.png")
    row["same_page_count"] = row["pdf"]["pages"] == row["word"]["pages"]
    row["same_page_size"] = all(
        abs(a - b) < 0.15 for a, b in zip(row["pdf"]["sizes_mm"][0], row["word"]["sizes_mm"][0])
    )
    report.append(row)
    print(row["source"], row["pdf"]["pages"], row["word"]["pages"], row["docx_structures"])
(ROOT / "audit.json").write_text(json.dumps(report, indent=2))
