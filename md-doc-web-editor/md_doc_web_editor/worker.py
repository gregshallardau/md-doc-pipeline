"""One cancellable output process, using the CLI's shared build function."""

from __future__ import annotations

import base64
import json
import hashlib
import io
import logging
import mimetypes
import re
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import unquote, urlsplit

_base_fetch = None


def build(document, root, output, format_name) -> int:
    global _base_fetch
    project = Path(root).resolve()
    from md_doc.builders import pdf

    if _base_fetch is None:
        _base_fetch = pdf._local_url_fetcher
    fetch = _base_fetch

    def scoped_fetch(url, *args, **kwargs):
        parsed = urlsplit(url)
        if parsed.scheme == "file" and not Path(unquote(parsed.path)).resolve().is_relative_to(
            project
        ):
            raise ValueError("Asset is outside the project snapshot")
        return fetch(url, *args, **kwargs)

    pdf._local_url_fetcher = scoped_fetch
    import weasyprint

    if hasattr(weasyprint, "URLFetcher"):

        class SnapshotFetcher(weasyprint.URLFetcher):
            def fetch(self, url, headers=None):
                pdf._reject_external(url)
                parsed = urlsplit(url)
                if parsed.scheme == "file" and not Path(
                    unquote(parsed.path)
                ).resolve().is_relative_to(project):
                    raise ValueError("Asset is outside the project snapshot")
                return super().fetch(url, headers)

        pdf._make_url_fetcher = lambda: SnapshotFetcher(allowed_protocols={"file", "data"})
    logging.getLogger("weasyprint").setLevel(logging.WARNING)
    if format_name in {"docx", "dotx", "pptx"}:
        from md_doc.builders import _assets, docx, pptx
        from md_doc import docx_theme

        resolve_asset = _assets._resolve_asset
        read_css = docx_theme._load_css_with_imports

        def scoped_asset(filename, doc_path, repo_root):
            result = resolve_asset(filename, doc_path, repo_root)
            if result and not result.resolve().is_relative_to(project):
                raise ValueError("Office asset is outside the project snapshot")
            return result

        def scoped_css(path, depth=0):
            if not Path(path).resolve().is_relative_to(project):
                raise ValueError("Word CSS import is outside the project snapshot")
            return read_css(path, depth)

        _assets._resolve_asset = scoped_asset
        docx._resolve_asset = scoped_asset
        pptx._resolve_asset = scoped_asset
        docx_theme._load_css_with_imports = scoped_css
    # Constrain Office assets and themes as well as the PDF fetcher.
    from md_doc.config import load_config

    config = load_config(Path(document), repo_root=project)
    for key in (
        "pdf_theme",
        "pptx_template",
        "cover_logo",
        "cover_bar_logo",
        "header_logo",
        "page_header_bar_logo",
    ):
        value = config.get(key)
        if (
            value
            and Path(str(value)).is_absolute()
            and not Path(str(value)).resolve().is_relative_to(project)
        ):
            raise ValueError(f"{key} references a file outside the project")

    from md_doc.cli import _build_document

    result = _build_document(
        Path(document),
        root=project,
        cascade_root=project,
        output=Path(output),
        fmt=format_name,
        theme=None,
        force=True,
        strict=True,
        verbose=True,
    )
    print(json.dumps(result, default=str))
    return 1 if result["errored"] else 0


_LOCAL_ASSET_RE = re.compile(r"""(\bsrc=|\burl\()(["']?)([^"')\s>]+)\2""")
_LINK_RE = re.compile(r"""<link rel="stylesheet" href="(file://[^"]+)">""")
_CSS_IMPORT_RE = re.compile(r"""@import\s+(?:url\(\s*)?['"]([^'"]+)['"]\s*\)?\s*;""")
_CSS_URL_RE = re.compile(r"""url\(\s*(["']?)([^"')\s]+)\1\s*\)""")
_MAX_INLINE_ASSET = 8 * 1024 * 1024
_MAX_IMPORT_DEPTH = 5
_PAPER_WIDTH_RE = re.compile(r"\.cover \{ width: ([\d.]+)mm;")
_DRAFT_CSS = """
html { background: #d9dce1; }
body { box-sizing: border-box; width: min(%(width)smm, 100%%); margin: 16px auto;
       padding: 18mm 20mm; background: #fff; box-shadow: 0 1px 6px rgba(0,0,0,.25); }
.cover { width: auto; height: auto; min-height: 60vh; }
"""


def _data_uri(path: Path, project: Path) -> str | None:
    """A data URI for a project file, or None for anything outside it or oversized."""
    try:
        resolved = path.resolve()
        if (
            not resolved.is_relative_to(project)
            or not resolved.is_file()
            or resolved.stat().st_size > _MAX_INLINE_ASSET
        ):
            return None
        kind = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        return f"data:{kind};base64,{base64.b64encode(resolved.read_bytes()).decode()}"
    except OSError:
        return None


def _inline_css(path: Path, project: Path, depth: int = 0) -> str:
    """Theme CSS with ``@import`` followed and relative ``url()`` made self-contained."""
    css = path.read_text(encoding="utf-8")

    def imported(match):
        target = (path.parent / match.group(1)).resolve()
        if depth >= _MAX_IMPORT_DEPTH or not target.is_file() or not target.is_relative_to(project):
            return ""
        return _inline_css(target, project, depth + 1) + "\n"

    def asset(match):
        ref = match.group(2)
        if ref.startswith(("data:", "#", "http:", "https:")):
            return match.group(0)
        location = unquote(urlsplit(ref).path)
        uri = _data_uri(
            Path(location) if ref.startswith("file://") else path.parent / location, project
        )
        return f'url("{uri}")' if uri else match.group(0)

    return _CSS_URL_RE.sub(asset, _CSS_IMPORT_RE.sub(imported, css))


def draft_html(markup: str, project: Path, base: Path | None = None) -> str:
    """Make the builder's HTML self-contained so a browser can show it unlayouted.

    Snapshot files vanish once the job finishes and the frame may not read the
    filesystem, so the theme and every local asset inside the project are inlined.
    Relative references resolve against *base* (the document's directory), as
    WeasyPrint's ``base_url`` does.
    """

    def stylesheet(match):
        path = Path(unquote(urlsplit(match.group(1)).path))
        try:
            if path.resolve().is_relative_to(project):
                return f"<style>{_inline_css(path.resolve(), project)}</style>"
        except OSError:
            pass
        return ""

    def inline(match):
        ref = match.group(3)
        if ref.startswith(("data:", "#", "http:", "https:", "//", "mailto:")):
            return match.group(0)
        location = Path(unquote(urlsplit(ref).path))
        uri = _data_uri(
            location if ref.startswith("file://") or base is None else base / location, project
        )
        if uri is None:
            return match.group(0)
        quote = match.group(2)
        return f"{match.group(1)}{quote}{uri}{quote}"

    markup = _LOCAL_ASSET_RE.sub(inline, _LINK_RE.sub(stylesheet, markup))
    width = _PAPER_WIDTH_RE.search(markup)
    style = f"<style>{_DRAFT_CSS % {'width': width.group(1) if width else '210'}}</style>"
    return markup.replace("</head>", style + "</head>", 1)


def persistent(root: Path) -> int:
    """JSON-lines protocol; one sequential, isolated preview session."""
    from .incremental import IncrementalPreview
    from .snapshots import TEXT_SUFFIXES
    from md_doc.builders import pdf

    preview = IncrementalPreview()
    settings = {}
    stream = sys.stdout

    def emit(event):
        print(json.dumps(event), file=stream, flush=True)

    def write_pdf(markup, base_url, output, options):
        if settings.get("draft"):
            # Draft mode stops at the HTML the PDF builder already produced:
            # no WeasyPrint layout, no PDF serialisation.
            target = Path(output).with_suffix(".html")
            target.write_text(
                draft_html(markup, project.resolve(), Path(base_url)), encoding="utf-8"
            )
            return
        preview.write_pdf(
            markup,
            base_url,
            output,
            options,
            inputs=settings["inputs"],
            visible_page=settings["visible_page"],
            emit=emit,
        )

    pdf._write_pdf = write_pdf
    previous_document = None
    project = root / "project"
    for line in sys.stdin:
        try:
            request = json.loads(line)
            source = Path(request["project"]).resolve()
            document = request["document"]
            if document != previous_document:
                preview.clear()
            previous_document = document
            shutil.rmtree(project, ignore_errors=True)
            shutil.copytree(source, project)
            digest = hashlib.sha256()
            for path in sorted(project.rglob("*")):
                if not path.is_file():
                    continue
                raw = path.read_bytes()
                if path.suffix.lower() in TEXT_SUFFIXES:
                    raw = raw.replace(str(source).encode(), str(project).encode())
                    path.write_bytes(raw)
                if path.suffix.lower() != ".md":
                    digest.update(path.relative_to(project).as_posix().encode() + raw)
            settings.update(
                inputs=digest.hexdigest(),
                visible_page=request.get("visible_page", 1),
                draft=request.get("format") == "html",
            )
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = build(str(project / document), str(project), request["output"], "pdf")
            result = json.loads(captured.getvalue().strip().splitlines()[-1])
            emit({"type": "result", "result": result, "stats": preview.stats, "code": code})
        except Exception as exc:
            preview.clear()
            emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
    return 0


def main() -> int:
    if sys.argv[1:2] == ["--persistent"]:
        return persistent(Path(sys.argv[2]).resolve())
    return build(*sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
