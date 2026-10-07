"""Physical Word/PDF parity: real exports, real office rendering, measured in mm.

Run with MD_DOC_PARITY=1; CI must install LibreOffice and DejaVu fonts.
Artifacts are diagnostic outputs, never automatically accepted golden images.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

if os.environ.get("MD_DOC_PARITY") != "1":
    pytest.skip("set MD_DOC_PARITY=1 to run office-rendered parity", allow_module_level=True)

import numpy as np  # noqa: E402
import pdfplumber  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

from md_doc.builders.docx import build as build_docx  # noqa: E402
from md_doc.builders.pdf import build as build_pdf  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
DPI = 144
MM_PER_POINT = 25.4 / 72
HEADER = (17, 83, 149)
TABLE = (8, 127, 91)
MARKER = (224, 96, 32)


def color_mask(image: Image.Image, color: tuple[int, int, int]) -> np.ndarray:
    pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
    return np.max(np.abs(pixels - np.array(color)), axis=2) <= 3


def mask_box(mask: np.ndarray) -> list[float]:
    ys, xs = np.nonzero(mask)
    assert len(xs), "Expected colored layout element is missing"
    return [float(x) * 25.4 / DPI for x in (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)]


def inspect(pdf: Path) -> tuple[list[dict], list[Image.Image]]:
    pages, images = [], []
    with pdfplumber.open(pdf) as document, pdfium.PdfDocument(pdf) as raster:
        for index, page in enumerate(document.pages):
            bitmap = raster[index].render(scale=DPI / 72)
            image = bitmap.to_pil().convert("RGB").copy()
            bitmap.close()
            images.append(image)
            words = {
                word["text"]: [float(word[k]) * MM_PER_POINT for k in ("x0", "top", "x1", "bottom")]
                for word in page.extract_words()
            }
            pages.append(
                {
                    "size_mm": [
                        float(page.width) * MM_PER_POINT,
                        float(page.height) * MM_PER_POINT,
                    ],
                    "header_mm": (
                        mask_box(color_mask(image, HEADER))
                        if color_mask(image, HEADER).any()
                        else None
                    ),
                    "words_mm": words,
                }
            )
    return pages, images


def diagnostics(
    directory: Path, pdf_images: list[Image.Image], word_images: list[Image.Image]
) -> None:
    for index, (pdf, word) in enumerate(zip(pdf_images, word_images), 1):
        size = max(pdf.width, word.width), max(pdf.height, word.height)
        a, b = Image.new("RGB", size, "white"), Image.new("RGB", size, "white")
        a.paste(pdf)
        b.paste(word)
        a.save(directory / f"page-{index}-pdf.png")
        b.save(directory / f"page-{index}-word.png")
        Image.blend(a, b, 0.5).save(directory / f"page-{index}-overlay.png")
        ImageChops.invert(ImageChops.difference(a, b)).save(
            directory / f"page-{index}-difference.png"
        )


def near(actual: list[float], expected: list[float], tolerance_mm: float, label: str) -> None:
    assert len(actual) == len(expected)
    delta = max(abs(a - b) for a, b in zip(actual, expected))
    assert (
        delta <= tolerance_mm
    ), f"{label}: {actual} != {expected}; error {delta:.3f} mm > {tolerance_mm} mm"


@pytest.mark.parametrize(
    "orientation,offset,width,height",
    [
        ("portrait", 20, 210, 297),
        ("landscape", 0, 297, 210),
    ],
)
def test_rendered_word_pdf_layout(tmp_path, orientation, offset, width, height):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    assert soffice, "Parity is enabled but LibreOffice is missing (do not silently skip CI)"
    artifacts = (
        Path(os.environ.get("MD_DOC_PARITY_ARTIFACTS", str(tmp_path / "artifacts"))) / orientation
    )
    artifacts.mkdir(parents=True, exist_ok=True)
    document = tmp_path / "layout.md"
    document.write_text((FIXTURES / "layout.md").read_text())
    css = (FIXTURES / "theme.css").read_text().replace("size: A4;", f"size: A4 {orientation};")
    (tmp_path / "_theme.css").write_text(css)
    Image.new("RGB", (48, 48), MARKER).save(tmp_path / "marker.png", dpi=(96, 96))
    config = {
        "date": "2026-01-01",
        "author": "Parity fixture",
        "cover_page": False,
        "page_header_bar": True,
        "page_header_bar_color": "#115395",
        "page_header_bar_height": "10mm",
        "page_header_bar_padding": "10mm",
        "page_header_bar_offset": f"{offset}mm",
        "header_text": "PARITYHEADER",
    }
    pdf_file, word_file = artifacts / "native.pdf", artifacts / "word.docx"
    build_pdf(document.read_text(), config, pdf_file, doc_path=document, repo_root=tmp_path)
    build_docx(document.read_text(), config, word_file, doc_path=document, repo_root=tmp_path)
    profile = (tmp_path / "office-profile").as_uri()
    process = subprocess.run(
        [
            soffice,
            f"-env:UserInstallation={profile}",
            "--headless",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(artifacts),
            str(word_file),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    (artifacts / "office.log").write_text(process.stdout + process.stderr)
    assert process.returncode == 0 and (artifacts / "word.pdf").is_file(), (
        process.stdout + process.stderr
    )
    pdf_pages, pdf_images = inspect(pdf_file)
    word_pages, word_images = inspect(artifacts / "word.pdf")
    report = {
        "dpi": DPI,
        "office_version": subprocess.check_output([soffice, "--version"], text=True).strip(),
        "expected": {"page_mm": [width, height], "header_mm": [0, offset, width, offset + 10]},
        "tolerances_mm": {"page": 0.1, "colored_geometry": 0.25, "text_position": 0.8},
        "pdf": pdf_pages,
        "word": word_pages,
    }
    (artifacts / "measurements.json").write_text(json.dumps(report, indent=2))
    diagnostics(artifacts, pdf_images, word_images)
    assert (
        len(pdf_pages) == len(word_pages) == 2
    ), "Explicit page break must yield exactly two pages"
    for index, (pdf, word) in enumerate(zip(pdf_pages, word_pages)):
        for name, page in (("PDF", pdf), ("Word", word)):
            near(page["size_mm"], [width, height], 0.1, f"{name} page {index + 1} A4")
            near(
                page["header_mm"],
                [0, offset, width, offset + 10],
                0.25,
                f"{name} full-width header",
            )
        anchor = "BODYANCHOR" if index == 0 else "SECONDANCHOR"
        for text in (anchor, "PARITYHEADER"):
            assert text in pdf["words_mm"] and text in word["words_mm"], f"Missing {text}"
            near(pdf["words_mm"][text][:2], word["words_mm"][text][:2], 0.8, f"{text} position")
        for page in (pdf, word):
            near(page["words_mm"][anchor][:2], [20, offset + 21], 1.0, "Body start")
        a, b = color_mask(pdf_images[index], HEADER), color_mask(word_images[index], HEADER)
        assert a.shape == b.shape, "Raster page dimensions differ"
        intersection, union = np.logical_and(a, b).sum(), np.logical_or(a, b).sum()
        assert intersection / union >= 0.97, "Header colored-area overlap below 97%"
    # Table geometry and an actual embedded image, beyond header-only comparisons.
    for color, label in ((TABLE, "table header"), (MARKER, "image")):
        a = mask_box(color_mask(pdf_images[0], color))
        b = mask_box(color_mask(word_images[0], color))
        near(a, b, 1.0, label)


@pytest.mark.parametrize(
    "orientation,title,custom,on_bar",
    [
        ("portrait", "COVER TITLE", False, False),
        ("portrait", "COVER TITLE", False, True),
        (
            "portrait",
            "A deterministic long title that wraps across several lines on the cover",
            False,
            False,
        ),
        ("landscape", "COVER TITLE", False, False),
        (
            "landscape",
            "A deterministic long title that wraps across several lines on the cover",
            True,
            False,
        ),
    ],
)
def test_rendered_cover(tmp_path, orientation, title, custom, on_bar):
    from md_doc.theme import generate_default_theme

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    assert soffice, "Enabled cover parity requires LibreOffice"
    name = f"cover-{orientation}-{'long' if len(title) > 20 else 'short'}"
    if on_bar:
        name += "-on-bar"
    artifacts = Path(os.environ.get("MD_DOC_PARITY_ARTIFACTS", str(tmp_path / "artifacts"))) / name
    artifacts.mkdir(parents=True, exist_ok=True)
    css = (
        generate_default_theme()
        .replace("Segoe UI", "DejaVu Sans")
        .replace("size: A4;", f"size: A4 {orientation};")
    )
    if custom:
        css = f"@page {{ size: A4 {orientation}; margin: 15mm 18mm; }} body {{ font-family: DejaVu Sans; font-size: 10.5pt; line-height: 1.65; }} h1 {{ color: #1b4f72; }} h2 {{ color: #2e86c1; }}"
    (tmp_path / "_theme.css").write_text(css)
    document = tmp_path / "cover.md"
    document.write_text(f"# {title}\n\nBODYANCHOR\n")
    config = {
        "title": title,
        "author": "Fixture Author",
        "date": "2026-01-01",
        "cover_page": True,
        "page_header_bar": True,
        "header_text": "BODYHEADER",
        "page_header_bar_color": "#115395",
        "cover_bar_position": "both",
        "cover_text_on_bar": on_bar,
        "cover_bar_height": "100mm" if on_bar else "10mm",
        "cover_stripe": not on_bar,
    }
    build_pdf(
        document.read_text(),
        config,
        artifacts / "native.pdf",
        doc_path=document,
        repo_root=tmp_path,
    )
    build_docx(
        document.read_text(), config, artifacts / "word.docx", doc_path=document, repo_root=tmp_path
    )
    process = subprocess.run(
        [
            soffice,
            f"-env:UserInstallation={(tmp_path / 'office').as_uri()}",
            "--headless",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(artifacts),
            str(artifacts / "word.docx"),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    (artifacts / "office.log").write_text(process.stdout + process.stderr)
    assert process.returncode == 0 and (artifacts / "word.pdf").is_file()
    pdf_pages, pdf_images = inspect(artifacts / "native.pdf")
    word_pages, word_images = inspect(artifacts / "word.pdf")
    (artifacts / "measurements.json").write_text(
        json.dumps({"pdf": pdf_pages, "word": word_pages}, indent=2)
    )
    diagnostics(artifacts, pdf_images, word_images)
    assert len(pdf_pages) == len(word_pages) == 2, "Cover must occupy exactly one page"
    width, height = (210, 297) if orientation == "portrait" else (297, 210)
    for pages, images in ((pdf_pages, pdf_images), (word_pages, word_images)):
        near(pages[0]["size_mm"], [width, height], 0.1, "Cover page size")
        assert pages[0]["header_mm"] is None, "Body header must not appear on cover"
        assert "BODYANCHOR" not in pages[0]["words_mm"]
        assert "BODYANCHOR" in pages[1]["words_mm"]
        assert "BODYHEADER" in pages[1]["words_mm"]
        band = color_mask(images[0], (27, 79, 114))
        for start, end in ((0, 10), (height - 10, height)):
            crop = band[round(start * DPI / 25.4) : round(end * DPI / 25.4)]
            assert crop.mean() > 0.97, "Cover bands must cover the full physical page width"
        if on_bar:
            continue
        stripe = color_mask(images[0], (46, 134, 193))
        stripe[:, round(20 * DPI / 25.4) :] = False
        near(
            mask_box(stripe),
            [0, 10, 6, 130],
            0.3,
            "Cover accent stripe",
        )
        for text in ("REPORT", "Prepared", "2026-01-01"):
            box = pages[0]["words_mm"][text]
            assert 27 < box[0] < width - 20 and 50 < box[1] < height - 25
    for text in ("REPORT", title.split()[0], "Prepared", "2026-01-01"):
        near(
            pdf_pages[0]["words_mm"][text][:2],
            word_pages[0]["words_mm"][text][:2],
            1.5,
            f"Cover {text}",
        )

    if on_bar:
        # Compare the physical extent of the dark wrapper, not just its text.
        for image in (pdf_images[0], word_images[0]):
            band = color_mask(image, (27, 79, 114))
            band[round((height - 20) * DPI / 25.4) :] = False
            assert mask_box(band)[3] >= 100
        a, b = [color_mask(image, (27, 79, 114)) for image in (pdf_images[0], word_images[0])]
        a[round((height - 20) * DPI / 25.4) :] = False
        b[round((height - 20) * DPI / 25.4) :] = False
        near(mask_box(a), mask_box(b), 1.5, "Cover text bar extent")
