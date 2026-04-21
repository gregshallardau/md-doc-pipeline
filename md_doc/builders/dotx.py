"""
Word merge-template (.dotx) builder — thin shim over docx.build().

All field logic, cover page handling, and .dotx content-type patching
live in ``docx.py``.  This module exists solely so the output format
dispatch in the CLI (``outputs: [dotx]``) has a ``build()`` entry-point
to call without needing to know about ``output_format``.

See ``docx.py`` for full documentation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .docx import build as _build_docx


def build(
    rendered_md: str,
    config: dict[str, Any],
    out_path: Path,
    *,
    doc_path: Path | None = None,
    repo_root: Path | None = None,
) -> None:
    """Convert rendered Markdown to a .dotx Word merge template.

    Delegates entirely to ``docx.build(..., output_format="dotx")``.
    """
    _build_docx(
        rendered_md,
        config,
        out_path,
        doc_path=doc_path,
        repo_root=repo_root,
        output_format="dotx",
    )
