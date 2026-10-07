"""Equation rendering survives Markdown parsing and reaches both output formats."""

from zipfile import ZipFile
import base64
import re
from xml.etree import ElementTree as ET

import pytest

from md_doc.math import markdown_html, render_math
from md_doc.builders.docx import build as build_word
from md_doc.builders.pdf import build as build_pdf

SOURCE = r"Before $x^2 + \alpha$ after." + "\n\n" + r"$$\frac{a}{b}$$"


def test_pdf_math_is_static_svg():
    html, _ = render_math(markdown_html(SOURCE, ["fenced_code"]))
    images = re.findall(r"data:image/svg\+xml;base64,([^\"]+)", html)
    assert len(images) == 2
    for image in images:
        svg = ET.fromstring(base64.b64decode(image))
        assert svg.tag.endswith("svg")
        assert any(node.tag.endswith("path") for node in svg.iter())
    assert "arithmatex" not in html
    assert "md-doc-math-display" in html


@pytest.mark.parametrize("word", [False, True])
def test_code_currency_and_escaped_dollars_stay_literal(word):
    source = r"`$x$` and \$literal\$ and $5 and $10." + "\n\n```tex\n$$x^2$$\n```"
    html, equations = render_math(markdown_html(source, ["fenced_code"]), word=word)
    assert "math://" not in html
    assert "data:image/svg" not in html
    assert not equations
    assert "$x$" in html and "$$x^2$$" in html


@pytest.mark.parametrize("output_format", ["docx", "dotx"])
def test_word_equations_are_editable_and_keep_text_order(tmp_path, output_format):
    path = tmp_path / f"math.{output_format}"
    build_word(
        SOURCE + "\n\n| Equation |\n|---|\n| $\\sqrt{x}$ |\n", {}, path, output_format=output_format
    )
    with ZipFile(path) as archive:
        xml = ET.fromstring(archive.read("word/document.xml"))
    ns = {
        "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    }
    assert len(xml.findall(".//m:oMath", ns)) == 3
    assert len(xml.findall(".//m:oMathPara", ns)) == 1
    assert xml.find(".//m:f", ns) is not None
    assert xml.find(".//w:tc//m:rad", ns) is not None
    paragraph = xml.find(".//w:body/w:p", ns)
    children = list(paragraph)
    equation_index = next(i for i, e in enumerate(children) if e.tag.endswith("oMath"))
    assert "Before" in "".join(children[equation_index - 1].itertext())
    assert "after" in "".join(children[equation_index + 1].itertext())


def test_math_pdf_build(tmp_path):
    path = tmp_path / "math.pdf"
    build_pdf(SOURCE, {}, path)
    assert path.read_bytes().startswith(b"%PDF")


def test_conversion_failure_is_actionable(monkeypatch):
    import ziamath

    def fail(*args, **kwargs):
        raise ValueError("bad equation")

    monkeypatch.setattr(ziamath, "Latex", fail)
    with pytest.raises(ValueError, match="Could not render LaTeX equation"):
        render_math(markdown_html("$x$", []))


def test_inline_pdf_math_overrides_generic_block_image_style():
    html, _ = render_math(markdown_html("Before $x$ after", []))
    assert "display: inline-block; margin: 0" in html
