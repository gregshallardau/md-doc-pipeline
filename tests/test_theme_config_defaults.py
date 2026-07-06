"""--mddoc-* theme custom properties provide brand defaults for config keys.

The brand's look values (bar colours/heights, cover bar sizes) can live in the
theme CSS at the global level; YAML keys override per folder/document.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from md_doc.builders._assets import apply_theme_config_defaults, theme_config_defaults

THEME = """
@page { size: A4; margin: 25mm 20mm 22mm 25mm; }
:root {
  --mddoc-header-bar-color: #002a5b;
  --mddoc-header-bar-height: 24mm;
  --mddoc-header-bar-padding: 8mm;
  --mddoc-cover-bar-height: 132mm;
}
body { font-size: 10pt; }
"""


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


class TestHelper:
    def test_extracts_known_props_only(self):
        d = theme_config_defaults(THEME + ":root { --mddoc-unknown: x; }")
        assert d == {
            "page_header_bar_color": "#002a5b",
            "page_header_bar_height": "24mm",
            "page_header_bar_padding": "8mm",
            "cover_bar_height": "132mm",
        }

    def test_yaml_always_wins(self):
        merged = apply_theme_config_defaults({"page_header_bar_color": "#ff0000"}, THEME)
        assert merged["page_header_bar_color"] == "#ff0000"
        assert merged["page_header_bar_height"] == "24mm"

    def test_no_css_is_noop(self):
        cfg = {"a": 1}
        assert apply_theme_config_defaults(cfg, None) is cfg


class TestPdf:
    def _html(self, tmp_repo: Path, config: dict) -> str:
        pytest.importorskip("weasyprint")
        from md_doc.builders.pdf import build

        (tmp_repo / "_pdf-theme.css").write_text(THEME, encoding="utf-8")
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

    def test_bar_brand_from_theme(self, tmp_repo):
        html = self._html(tmp_repo, {"page_header_bar": True})
        assert "background: #002a5b" in html
        assert "height: 24mm" in html
        assert "margin-top: calc(24mm + 8mm)" in html

    def test_yaml_override_wins(self, tmp_repo):
        html = self._html(tmp_repo, {"page_header_bar": True, "page_header_bar_color": "#ff0000"})
        assert "background: #ff0000" in html


class TestDocx:
    def test_bar_brand_from_theme(self, tmp_repo):
        from md_doc.builders.docx import build

        (tmp_repo / "_theme.css").write_text(THEME, encoding="utf-8")
        doc = tmp_repo / "d.md"
        md = "---\ntitle: T\n---\n\n# T\n\nBody.\n"
        doc.write_text(md, encoding="utf-8")
        out = tmp_repo / "d.docx"
        build(
            md,
            {"title": "T", "cover_page": False, "page_header_bar": True},
            out,
            output_format="docx",
            doc_path=doc,
            repo_root=tmp_repo,
        )
        with zipfile.ZipFile(out) as z:
            hdr = z.read("word/header1.xml").decode()
            body = z.read("word/document.xml").decode()
        assert 'w:fill="002A5B"' in hdr or 'w:fill="002a5b"' in hdr
        top = int(re.search(r'w:top="(\d+)"', body).group(1))
        assert round(top / 56.7) == 32  # 24mm bar + 8mm padding from the theme
