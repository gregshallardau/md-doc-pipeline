"""
Document register generator.

Scans a build output directory for produced documents (PDF, DOCX, MD) and
generates a machine-readable register in three formats:

  - ``register.json``   — structured record list (primary output)
  - ``register.md``     — human-readable Markdown table
  - ``register.csv``    — spreadsheet-compatible CSV

Each record contains:
  path, filename, product, document_type, version, status,
  size_kb, last_modified, md5

Metadata (product, document_type, version, status) is resolved by walking
up from each document to find a ``_meta.yml`` config, falling back to empty
strings when none is available.

Public API
----------
    generate(root, json_path, write_md=True)
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

# File extensions recognised as built documents
_BUILD_EXTENSIONS = {".pdf", ".docx", ".md"}

# Files to exclude from the register
_EXCLUDE_NAMES = {
    "register.md",
    "register.json",
    "register.csv",
    "README.md",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_meta_yml(directory: Path) -> dict:
    """Load _meta.yml from directory, returning {} on missing/parse error."""
    meta_file = directory / "_meta.yml"
    try:
        data = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


def _resolve_meta(file_path: Path, root: Path) -> dict:
    """
    Walk from root → file_path's directory, merging _meta.yml files.
    Returns a merged dict (shallowest first, deepest overrides).
    """
    file_dir = file_path.parent
    try:
        rel = file_dir.relative_to(root)
        parts = [root] + [root / Path(*rel.parts[:i]) for i in range(1, len(rel.parts) + 1)]
    except ValueError:
        parts = [file_dir]

    merged: dict = {}
    for directory in parts:
        layer = _load_meta_yml(directory)
        merged.update(layer)
    return merged


def _infer_document_type(path: Path) -> str:
    """Guess document type from path components or filename."""
    name_lower = path.stem.lower()
    for keyword in (
        "report",
        "summary",
        "brief",
        "policy",
        "procedure",
        "schedule",
        "register",
        "binder",
        "renewal",
    ):
        if keyword in name_lower:
            return keyword.replace("_", " ").title()
    # Fall back to extension
    ext_map = {".pdf": "PDF Document", ".docx": "Word Document", ".md": "Markdown"}
    return ext_map.get(path.suffix.lower(), "Document")


def _build_record(file_path: Path, root: Path) -> dict:
    stat = file_path.stat()
    meta = _resolve_meta(file_path, root)

    size_kb = round(stat.st_size / 1024, 2)
    last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:
        rel_path = str(file_path.relative_to(root))
    except ValueError:
        rel_path = str(file_path)

    return {
        "path": rel_path,
        "filename": file_path.name,
        "product": meta.get("product", ""),
        "document_type": meta.get("document_type") or _infer_document_type(file_path),
        "version": str(meta.get("version", "")),
        "status": str(meta.get("status", "")),
        "size_kb": size_kb,
        "last_modified": last_modified,
        "md5": _md5(file_path),
    }


# ---------------------------------------------------------------------------
# Markdown table writer
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "path",
    "filename",
    "product",
    "document_type",
    "version",
    "status",
    "size_kb",
    "last_modified",
    "md5",
]

_MD_HEADERS = [
    "Path",
    "Filename",
    "Product",
    "Type",
    "Version",
    "Status",
    "Size (KB)",
    "Last Modified",
    "MD5",
]


def _write_md(records: list[dict], md_path: Path) -> None:
    lines = [
        "# Document Register",
        "",
        f"_Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]

    if not records:
        lines.append("_No documents found._")
        md_path.write_text("\n".join(lines), encoding="utf-8")
        return

    # Header row
    header = "| " + " | ".join(_MD_HEADERS) + " |"
    sep = "| " + " | ".join("---" for _ in _MD_HEADERS) + " |"
    lines.extend([header, sep])

    for r in records:
        row_vals = [
            r["path"],
            r["filename"],
            r["product"],
            r["document_type"],
            r["version"],
            r["status"],
            str(r["size_kb"]),
            r["last_modified"],
            r["md5"][:8] + "…",  # truncate for readability
        ]
        lines.append("| " + " | ".join(v.replace("|", "\\|") for v in row_vals) + " |")

    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def _write_csv(records: list[dict], csv_path: Path) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(
    root: Path,
    json_path: Path,
    write_md: bool = True,
) -> list[dict]:
    """
    Scan root for built documents and write a register.

    Parameters
    ----------
    root:
        Directory to scan (typically the ``build/`` output directory, but
        can be any directory tree).
    json_path:
        Path for the primary JSON register output.
    write_md:
        When True (default), also write a Markdown register alongside the
        JSON, and a CSV register.

    Returns
    -------
    list[dict]
        The list of document records written to the register.
    """
    root = Path(root).resolve()
    json_path = Path(json_path).resolve()

    records: list[dict] = []

    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in _BUILD_EXTENSIONS:
            continue
        if file_path.name in _EXCLUDE_NAMES:
            continue
        if any(part.startswith("_") for part in file_path.parts):
            continue

        records.append(_build_record(file_path, root))

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    if write_md:
        _write_md(records, json_path.with_suffix(".md"))
        _write_csv(records, json_path.with_suffix(".csv"))

    return records
