"""One cancellable output process, using the CLI's shared build function."""

from __future__ import annotations

import json
import hashlib
import io
import logging
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
            settings.update(inputs=digest.hexdigest(), visible_page=request.get("visible_page", 1))
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
