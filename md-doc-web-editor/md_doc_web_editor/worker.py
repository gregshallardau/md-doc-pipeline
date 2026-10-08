"""One cancellable output process, using the CLI's shared build function."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


def main() -> int:
    document, root, output, format_name = sys.argv[1:]
    project = Path(root).resolve()
    from md_doc.builders import pdf

    fetch = pdf._local_url_fetcher

    def scoped_fetch(url, *args, **kwargs):
        parsed = urlsplit(url)
        if parsed.scheme == "file" and not Path(unquote(parsed.path)).resolve().is_relative_to(
            project
        ):
            raise ValueError("Asset is outside the project snapshot")
        return fetch(url, *args, **kwargs)

    pdf._local_url_fetcher = scoped_fetch
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


if __name__ == "__main__":
    sys.exit(main())
