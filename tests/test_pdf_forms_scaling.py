"""Form controls must stay centred on their labels at any theme font size/weight."""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pdfium = pytest.importorskip("pypdfium2")
pdfplumber = pytest.importorskip("pdfplumber")

from md_doc.builders.pdf import build as build_pdf  # noqa: E402

_SOURCE = """---
pdf_forms: true
cover_page: false
---

# Form

?[radio-inline: urgency | Standard | Urgent]

?[checkbox-inline: channels | Email | Phone | Portal]

?[yesno: consent]
"""


def _offsets(pdf: Path, size: float) -> list[float]:
    scale = 8
    document = pdfium.PdfDocument(str(pdf))
    page = pdfplumber.open(str(pdf)).pages[0]
    dark = (
        np.array(document[0].render(scale=scale, may_draw_forms=True).to_pil().convert("L")) < 170
    )
    words = page.extract_words()

    def span(x0: float, x1: float, y0: float, y1: float) -> float | None:
        sub = dark[int(y0 * scale) : int(y1 * scale), int(x0 * scale) : int(x1 * scale)]
        rows = np.where(sub.any(axis=1))[0]
        return None if not len(rows) else y0 + (rows.min() + rows.max()) / 2 / scale

    out = []
    for annot in page.annots:
        near = [
            w
            for w in words
            if abs(w["top"] - annot["top"]) < size and 0 < w["x0"] - annot["x1"] < size * 2
        ]
        if not near:
            continue
        y0, y1 = annot["top"] - size * 0.4, annot["bottom"] + size * 0.4
        circle = span(annot["x0"] - 2, annot["x1"] + 2, y0, y1)
        text = span(near[0]["x0"], near[0]["x0"] + size * 0.35, y0, y1)
        if circle is not None and text is not None:
            out.append(text - circle)
    return out


@pytest.mark.parametrize("size,weight", [(9, 400), (12, 700), (16, 400)])
def test_option_controls_stay_centred(tmp_path: Path, size: int, weight: int) -> None:
    theme = tmp_path / "_pdf-theme.css"
    theme.write_text(
        f"body, .report-body, label, input {{ font-size: {size}pt; font-weight: {weight}; }}\n"
    )
    doc = tmp_path / "form.md"
    doc.write_text(_SOURCE)
    out = tmp_path / "form-form.pdf"
    build_pdf(
        _SOURCE, {"pdf_forms": True, "cover_page": False}, out, repo_root=tmp_path, doc_path=doc
    )
    offsets = _offsets(out, size)
    assert len(offsets) == 7
    assert max(abs(o) for o in offsets) < 0.5
