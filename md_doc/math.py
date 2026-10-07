"""Shared LaTeX math parsing and static PDF / native Word rendering."""

from __future__ import annotations

import base64
from html import escape, unescape
import re
from typing import Any

import markdown

# Arithmatex runs inside Markdown, so code and escaped delimiters stay literal.
_EXTENSION = "pymdownx.arithmatex"
_MATH_RE = re.compile(r'<(?P<tag>span|div) class="arithmatex">(?P<body>.*?)</(?P=tag)>', re.DOTALL)


def markdown_html(body: str, extensions: list[str]) -> str:
    return markdown.Markdown(
        extensions=[*extensions, _EXTENSION],
        extension_configs={_EXTENSION: {"generic": True}},
    ).convert(body)


def render_math(html: str, *, word: bool = False) -> tuple[str, list[Any]]:
    """Replace parsed equations with SVG images or references to OMML elements.

    Fail explicitly on conversion errors rather than silently dropping math.
    Word callers insert each returned OMML element at its math://N marker.
    """
    equations: list[Any] = []

    def replace(match: re.Match[str]) -> str:
        display = match.group("tag") == "div"
        # Generic arithmatex wraps its escaped source in \\(…\\) or \\[…\\].
        source = unescape(match.group("body"))[2:-2].strip()
        try:
            if word:
                from latex2mathml.converter import convert
                import mathml2omml
                from docx.oxml import parse_xml, OxmlElement
                from docx.oxml.ns import nsdecls

                omml = mathml2omml.convert(
                    convert(source, display="block" if display else "inline")
                )
                equation = parse_xml(f'<root {nsdecls("m", "w")}>{omml}</root>')[0]
                if display:
                    block = OxmlElement("m:oMathPara")
                    block.append(equation)
                    equation = block
                equations.append(equation)
                image = (
                    f'<img src="math://{len(equations) - 1}" alt="{escape(source, quote=True)}" />'
                )
            else:
                import ziamath

                svg = ziamath.Latex(source, size=16, inline=not display).svg()
                encoded = base64.b64encode(svg.encode()).decode("ascii")
                image = (
                    '<img class="md-doc-math" style="display: inline-block; margin: 0; vertical-align: middle" '
                    f'src="data:image/svg+xml;base64,{encoded}" alt="{escape(source, quote=True)}" />'
                )
        except Exception as exc:
            raise ValueError(f"Could not render LaTeX equation {source!r}: {exc}") from exc
        if display:
            return f'<div class="md-doc-math-display" style="text-align: center">{image}</div>'
        return image

    return _MATH_RE.sub(replace, html), equations
