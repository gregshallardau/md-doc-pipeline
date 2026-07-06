"""Header logos render at the same size in PDF and Word.

Regression: the PDF drew margin-box logos at raw pixel size (a hi-res logo
blew out the header) while Word forced every logo to 6mm — too small and
inconsistent. Shared rule now: min(intrinsic @96dpi, 8mm) tall, never
upscaled; `header_logo_height` forces an exact height in both formats.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest

from md_doc.builders.docx import _logo_height_mm, _parse_mm_cfg


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def _png(path: Path, w: int, h: int) -> None:
    from PIL import Image

    Image.new("RGB", (w, h), "navy").save(path)


class TestLogoHeightRule:
    def test_big_logo_capped(self, tmp_repo):
        _png(tmp_repo / "big.png", 400, 100)  # 26.5mm intrinsic
        assert _logo_height_mm(tmp_repo / "big.png", 8.0) == pytest.approx(8.0)

    def test_small_logo_keeps_natural_size(self, tmp_repo):
        _png(tmp_repo / "small.png", 120, 30)  # 7.94mm intrinsic
        h = _logo_height_mm(tmp_repo / "small.png", 8.0)
        assert h == pytest.approx(30 / 96 * 25.4)  # not upscaled to the cap

    def test_forced_height_wins(self, tmp_repo):
        _png(tmp_repo / "small.png", 120, 30)
        assert _logo_height_mm(tmp_repo / "small.png", 8.0, 12.0) == 12.0

    def test_parse_mm_cfg(self):
        assert _parse_mm_cfg("12mm") == 12.0
        assert _parse_mm_cfg(10) == 10.0
        assert _parse_mm_cfg(None) is None


class TestPdfLogoResolution:
    def test_big_logo_gets_dpi(self, tmp_repo):
        from md_doc.builders.pdf import _logo_resolution_dpi

        _png(tmp_repo / "big.png", 400, 100)
        dpi = _logo_resolution_dpi(tmp_repo / "big.png", 8.0)
        assert dpi == pytest.approx(100 / 8.0 * 25.4)

    def test_small_logo_untouched(self, tmp_repo):
        from md_doc.builders.pdf import _logo_resolution_dpi

        _png(tmp_repo / "small.png", 120, 30)
        assert _logo_resolution_dpi(tmp_repo / "small.png", 8.0) is None

    def test_forced_always_scales(self, tmp_repo):
        from md_doc.builders.pdf import _logo_resolution_dpi

        _png(tmp_repo / "small.png", 120, 30)
        dpi = _logo_resolution_dpi(tmp_repo / "small.png", 12.0, forced=True)
        assert dpi == pytest.approx(30 / 12.0 * 25.4)

    def test_image_resolution_reaches_html(self, tmp_repo):
        pytest.importorskip("weasyprint")
        from unittest.mock import MagicMock, patch

        from md_doc.builders.pdf import build

        _png(tmp_repo / "logo.png", 400, 100)
        doc = tmp_repo / "d.md"
        doc.write_text("# T\n\nBody.\n", encoding="utf-8")
        with patch("md_doc.builders.pdf.weasyprint") as wp:
            wp.HTML.return_value = MagicMock()
            build(
                "# T\n\nBody.\n",
                {"title": "T", "header_logo": "logo.png"},
                tmp_repo / "d.pdf",
                doc_path=doc,
                repo_root=tmp_repo,
            )
            html = wp.HTML.call_args.kwargs["string"]
        assert "image-resolution:" in html


class TestDocxHeaderLogoSize:
    def _header_extent_mm(self, out: Path) -> tuple[float, float]:
        with zipfile.ZipFile(out) as z:
            for name in z.namelist():
                if "header" in name and name.endswith(".xml"):
                    m = re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"', z.read(name).decode())
                    if m:
                        return int(m.group(1)) / 36000, int(m.group(2)) / 36000
        raise AssertionError("no header logo found")

    def _build(self, tmp_repo: Path, config: dict) -> Path:
        from md_doc.builders.docx import build

        doc = tmp_repo / "d.md"
        md = "---\ntitle: T\n---\n\n# T\n\nBody.\n"
        doc.write_text(md, encoding="utf-8")
        out = tmp_repo / "d.docx"
        build(
            md,
            {"title": "T", "cover_page": False, **config},
            out,
            output_format="docx",
            doc_path=doc,
            repo_root=tmp_repo,
        )
        return out

    def test_big_logo_capped_at_8mm(self, tmp_repo):
        _png(tmp_repo / "logo.png", 400, 100)
        _, h = self._header_extent_mm(self._build(tmp_repo, {"header_logo": "logo.png"}))
        assert h == pytest.approx(8.0, abs=0.1)

    def test_forced_height(self, tmp_repo):
        _png(tmp_repo / "logo.png", 400, 100)
        _, h = self._header_extent_mm(
            self._build(tmp_repo, {"header_logo": "logo.png", "header_logo_height": "12mm"})
        )
        assert h == pytest.approx(12.0, abs=0.1)

    def test_small_logo_natural(self, tmp_repo):
        _png(tmp_repo / "logo.png", 120, 30)
        _, h = self._header_extent_mm(self._build(tmp_repo, {"header_logo": "logo.png"}))
        assert h == pytest.approx(30 / 96 * 25.4, abs=0.1)


class TestHeaderBarLogoScalesWithBar:
    """Bar logos default to 70% of the bar height in BOTH formats.

    Regression: a hard 8mm ceiling left the logo looking lost inside tall
    header bars (e.g. an 18mm brand band). ``header_logo_height`` still
    forces an exact size.
    """

    def _build_docx(self, tmp_repo: Path, config: dict) -> Path:
        from md_doc.builders.docx import build

        doc = tmp_repo / "d.md"
        md = "---\ntitle: T\n---\n\n# T\n\nBody.\n"
        doc.write_text(md, encoding="utf-8")
        out = tmp_repo / "d.docx"
        build(
            md,
            {"title": "T", "cover_page": False, **config},
            out,
            output_format="docx",
            doc_path=doc,
            repo_root=tmp_repo,
        )
        return out

    def _header_extent_mm(self, out: Path) -> tuple[float, float]:
        with zipfile.ZipFile(out) as z:
            for name in z.namelist():
                if "header" in name and name.endswith(".xml"):
                    m = re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"', z.read(name).decode())
                    if m:
                        return int(m.group(1)) / 36000, int(m.group(2)) / 36000
        raise AssertionError("no header logo found")

    def test_docx_bar_logo_is_70pct_of_bar(self, tmp_repo):
        _png(tmp_repo / "logo.png", 400, 400)  # intrinsic 105mm — always capped
        out = self._build_docx(
            tmp_repo,
            {
                "page_header_bar": True,
                "page_header_bar_height": "18mm",
                "page_header_bar_logo": "logo.png",
            },
        )
        _, h = self._header_extent_mm(out)
        assert h == pytest.approx(18.0 * 0.7, abs=0.1)

    def test_docx_bar_logo_forced_height_wins(self, tmp_repo):
        _png(tmp_repo / "logo.png", 400, 400)
        out = self._build_docx(
            tmp_repo,
            {
                "page_header_bar": True,
                "page_header_bar_height": "18mm",
                "page_header_bar_logo": "logo.png",
                "header_logo_height": "10mm",
            },
        )
        _, h = self._header_extent_mm(out)
        assert h == pytest.approx(10.0, abs=0.1)

    def _pdf_html(self, tmp_repo: Path, config: dict) -> str:
        pytest.importorskip("weasyprint")
        from unittest.mock import MagicMock, patch

        from md_doc.builders.pdf import build

        doc = tmp_repo / "d.md"
        doc.write_text("# T\n\nBody.\n", encoding="utf-8")
        with patch("md_doc.builders.pdf.weasyprint") as wp:
            wp.HTML.return_value = MagicMock()
            build(
                "# T\n\nBody.\n",
                {"title": "T", **config},
                tmp_repo / "d.pdf",
                doc_path=doc,
                repo_root=tmp_repo,
            )
            return wp.HTML.call_args.kwargs["string"]

    def test_pdf_bar_logo_cap_scales_with_bar(self, tmp_repo):
        _png(tmp_repo / "logo.png", 400, 400)
        html = self._pdf_html(
            tmp_repo,
            {
                "page_header_bar": True,
                "page_header_bar_height": "18mm",
                "page_header_bar_logo": "logo.png",
            },
        )
        assert f"max-height: {18.0 * 0.7}mm" in html

    def test_pdf_bar_logo_forced_height_wins(self, tmp_repo):
        _png(tmp_repo / "logo.png", 400, 400)
        html = self._pdf_html(
            tmp_repo,
            {
                "page_header_bar": True,
                "page_header_bar_height": "18mm",
                "page_header_bar_logo": "logo.png",
                "header_logo_height": "10mm",
            },
        )
        assert "max-height: 10.0mm" in html

    def test_pdf_bar_uses_table_slots_not_flex(self, tmp_repo):
        # WeasyPrint 68.x drops flex children inside position:fixed boxes —
        # the bar text vanished and the logo ignored its position. The bar
        # must lay out with table-cell slots and honour the logo position.
        _png(tmp_repo / "logo.png", 400, 400)
        html = self._pdf_html(
            tmp_repo,
            {
                "page_header_bar": True,
                "page_header_bar_logo": "logo.png",
                "page_header_bar_logo_position": "right",
                "header_text": "Affinity",
            },
        )
        assert "display: flex" not in html
        assert 'class="phb-row"' in html
        right_slot = html.split('class="phb-slot phb-slot-right"')[1].split("</div>")[0]
        assert "phb-logo" in right_slot
        left_slot = html.split('class="phb-slot phb-slot-left"')[1].split("</div>")[0]
        assert "Affinity" in left_slot
