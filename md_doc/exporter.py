"""
Vault export module.

Scans a directory tree for Markdown files with ``export: true`` in their
YAML frontmatter, stages them into a workspace directory, and returns the
list of staged paths ready for the build pipeline.

Frontmatter keys:
  export: true              — marks this note for export
  export_format: pdf        — output format (pdf, docx, dotx). Default: pdf
  export_path: Cheat Sheets — relative path inside the output dir. Default: mirrors source structure
  export_filename: My Doc   — override output filename (extension added automatically)
  draft: true               — skip this note even if export: true. Default: false
  tags: [cheatsheet, cli]   — metadata tags; use --tag flag to filter exports
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import _extract_frontmatter


def find_exportable(
    source_dir: Path,
    *,
    tags: list[str] | None = None,
) -> list[tuple[Path, dict]]:
    """Return all .md files under *source_dir* with ``export: true`` in frontmatter.

    Skips notes with ``draft: true``.
    If *tags* is provided, only includes notes whose ``tags`` list contains
    at least one of the requested tags.

    Returns a list of (path, frontmatter_dict) tuples so callers can access
    export_path and export_format without re-reading the file.
    """
    results: list[tuple[Path, dict]] = []
    for md_file in sorted(source_dir.rglob("*.md")):
        if any(part.startswith(".") for part in md_file.parts):
            continue
        fm = _extract_frontmatter(md_file)
        if fm.get("export") is not True:
            continue
        if fm.get("draft") is True:
            continue
        if tags:
            doc_tags = fm.get("tags", [])
            if isinstance(doc_tags, str):
                doc_tags = [doc_tags]
            if not any(t in doc_tags for t in tags):
                continue
        results.append((md_file, fm))
    return results


def stage_files(
    files: list[tuple[Path, dict]],
    staging_dir: Path,
    *,
    use_symlinks: bool = True,
) -> list[tuple[Path, dict]]:
    """Copy or symlink exportable files into *staging_dir*, returning staged paths.

    Cleans any existing .md symlinks/files in the staging dir first.
    Returns list of (staged_path, frontmatter_dict) tuples.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Clean previous staged .md files
    for existing in staging_dir.iterdir():
        if existing.is_symlink() or existing.is_file():
            if existing.suffix == ".md":
                existing.unlink()

    staged: list[tuple[Path, dict]] = []
    seen_names: set[str] = set()

    for src, fm in files:
        name = src.name
        if name in seen_names:
            parent_name = src.parent.name.replace(" ", "-").lower()
            name = f"{parent_name}--{name}"
        seen_names.add(name)

        dest = staging_dir / name

        if use_symlinks:
            dest.symlink_to(src)
        else:
            shutil.copy2(src, dest)

        staged.append((dest, fm))

    return staged


def collect_outputs(
    staging_dir: Path,
    dest_dir: Path,
    source_dir: Path,
    staged_files: list[tuple[Path, dict]],
    original_files: list[tuple[Path, dict]],
    extensions: tuple[str, ...] = (".pdf", ".docx", ".dotx"),
) -> list[Path]:
    """Copy built outputs from *staging_dir* to *dest_dir*, preserving structure.

    Output placement logic:
    1. If the note has ``export_path`` in frontmatter → dest_dir / export_path /
    2. Otherwise → mirrors the source directory structure relative to source_dir

    Filename logic:
    1. If the note has ``export_filename`` in frontmatter → use that (extension added automatically)
    2. Otherwise → use the source filename with the output extension

    Returns list of copied output paths.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Build a map from staged filename (stem) to (original_path, frontmatter)
    stem_to_original: dict[str, tuple[Path, dict]] = {}
    for (staged_path, fm), (orig_path, _) in zip(staged_files, original_files):
        stem_to_original[staged_path.stem] = (orig_path, fm)

    copied: list[Path] = []
    for output in staging_dir.iterdir():
        if output.suffix not in extensions or output.is_symlink():
            continue

        # Match output back to its source note
        # Handle -form.pdf suffix: "doc-form.pdf" → stem is "doc-form", source stem is "doc"
        output_stem = output.stem
        if output_stem.endswith("-form"):
            lookup_stem = output_stem[:-5]
        else:
            lookup_stem = output_stem

        orig_path, fm = stem_to_original.get(lookup_stem, (None, {}))

        # Determine target directory
        export_path = fm.get("export_path")
        if export_path:
            target_dir = dest_dir / export_path
        elif orig_path:
            try:
                rel = orig_path.relative_to(source_dir)
                target_dir = dest_dir / rel.parent
            except ValueError:
                target_dir = dest_dir
        else:
            target_dir = dest_dir

        target_dir.mkdir(parents=True, exist_ok=True)

        # Determine filename
        export_filename = fm.get("export_filename")
        if export_filename:
            # Strip any extension the user may have included, use the built output's extension
            clean_name = Path(export_filename).stem
            target = target_dir / (clean_name + output.suffix)
        else:
            target = target_dir / output.name

        shutil.copy2(output, target)
        copied.append(target)

    return copied
