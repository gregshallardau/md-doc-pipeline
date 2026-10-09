"""Rendered document headings with source locations, including Jinja fragments."""

from __future__ import annotations

import base64
import json
import re
import secrets
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from md_doc.config import _find_repo_root
from md_doc.renderer import _strip_frontmatter, render


def document_outline(path: Path, workspace: Path) -> dict[str, Any]:
    from md_doc.builders.pdf import _MD_EXTENSIONS
    from md_doc.math import markdown_html
    from .server import _resolve_template

    root = _find_repo_root(path.parent)
    prefix = "md-doc-source-" + secrets.token_hex(12) + ":"
    links: list[dict[str, Any]] = []

    def handle(source: Path) -> str:
        if source.is_relative_to(workspace):
            return source.relative_to(workspace).as_posix()
        return "project:" + source.relative_to(root).as_posix()

    def annotate(raw: str, source: Path) -> str:
        frontmatter, body = _strip_frontmatter(raw) if source == path else ("", raw)
        offset = frontmatter.count("\n")
        lines = body.splitlines(keepends=True)
        fence = None
        for index, line in enumerate(lines):
            opening = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
            if opening:
                token = opening[1]
                if fence is None:
                    fence = token
                elif token[0] == fence[0] and len(token) >= len(fence):
                    fence = None
                continue
            if fence is not None:
                continue
            line_number = index + offset + 1
            for include in re.finditer(r"\{%[-+]?\s*include\s+['\"]([^'\"]+)['\"]", line):
                resolved = _resolve_template(include[1], path, workspace)
                if resolved:
                    links.append(
                        {
                            "parent": handle(source),
                            "path": handle(resolved),
                            "line": line_number,
                            "name": include[1],
                        }
                    )
            payload = base64.b64encode(
                json.dumps({"path": handle(source), "line": line_number}).encode()
            ).decode()
            marker = "<!--" + prefix + payload + "-->"
            heading = re.match(r"^(\s{0,3}#{1,6}\s+)(.*)", line)
            if heading:
                lines[index] = heading[1] + marker + line[len(heading[1]) :]
            elif re.search(r"<h[1-6]\b[^>]*>", line, re.IGNORECASE):
                lines[index] = re.sub(
                    r"(<h[1-6]\b[^>]*>)",
                    lambda match: match[1] + marker,
                    line,
                    flags=re.IGNORECASE,
                )
            elif (
                line.strip()
                and index + 1 < len(lines)
                and re.fullmatch(r"\s{0,3}(?:=+|-+)\s*", lines[index + 1])
                and not line.lstrip().startswith(("{%", "<!--", "|"))
            ):
                lines[index] = marker + line
        return frontmatter + "".join(lines)

    class Headings(HTMLParser):
        def __init__(self):
            super().__init__()
            self.items: list[dict[str, Any]] = []
            self.heading = None
            self.parts: list[str] = []

        def handle_starttag(self, tag, attrs):
            if re.fullmatch(r"h[1-6]", tag):
                self.heading = {"level": int(tag[1]), "path": handle(path), "line": 1}
                self.parts = []

        def handle_comment(self, data):
            if self.heading is not None and data.startswith(prefix):
                self.heading.update(json.loads(base64.b64decode(data[len(prefix) :])))

        def handle_data(self, data):
            if self.heading is not None:
                self.parts.append(data)

        def handle_endtag(self, tag):
            if self.heading is not None and tag == "h" + str(self.heading["level"]):
                self.heading["title"] = " ".join("".join(self.parts).split())
                self.items.append(self.heading)
                self.heading = None

    rendered = render(path, source_transform=annotate)
    _, body = _strip_frontmatter(rendered)
    parser = Headings()
    parser.feed(markdown_html(body, _MD_EXTENSIONS))
    return {"headings": parser.items, "includes": links}
