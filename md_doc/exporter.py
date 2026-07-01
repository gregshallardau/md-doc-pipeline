"""
Vault export module.

Scans a directory tree for Markdown files with ``export: true`` in their
YAML frontmatter or inherited from a parent ``_meta.yml``, stages them into
a workspace directory, and returns the list of staged paths ready for the
build pipeline.

Frontmatter / _meta.yml keys:
  export: true              — marks this note for export (inheritable from _meta.yml)
  export_format: pdf        — output format (pdf, docx, dotx). Default: pdf
  export_path: Cheat Sheets — relative path inside the output dir. Default: mirrors source structure
  export_filename: My Doc   — override output filename (extension added automatically)
  draft: true               — skip this note even if export: true. Default: false
  tags: [cheatsheet, cli]   — metadata tags; use --tag flag to filter exports
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .config import load_config

logger = logging.getLogger(__name__)


def find_exportable(
    source_dir: Path,
    *,
    tags: list[str] | None = None,
    repo_root: Path | None = None,
) -> list[tuple[Path, dict]]:
    """Return all .md files under *source_dir* with ``export: true``.

    Checks the fully merged config (document frontmatter + all ancestor
    ``_meta.yml`` files) so ``export: true`` set in a parent directory's
    ``_meta.yml`` is inherited by all documents beneath it.

    Skips notes with ``draft: true``.
    If *tags* is provided, only includes notes whose ``tags`` list contains
    at least one of the requested tags.

    Returns a list of (path, merged_config_dict) tuples so callers can access
    export_path, export_format, and output_filename without re-reading the file.
    """
    results: list[tuple[Path, dict]] = []
    for md_file in sorted(source_dir.rglob("*.md")):
        # Only inspect path components *below* source_dir so a vault that itself
        # lives under a dotted directory (e.g. ``/home/user/.vault``) is not
        # entirely skipped.
        try:
            rel_parts = md_file.relative_to(source_dir).parts
        except ValueError:
            rel_parts = md_file.parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        config = load_config(md_file, repo_root=repo_root)
        # ``export: true`` is required (it may be inherited from a parent
        # _meta.yml). A missing or non-True value means "do not export".
        if config.get("export") is not True:
            continue
        if config.get("draft") is True:
            continue
        if tags:
            doc_tags = config.get("tags", [])
            if isinstance(doc_tags, str):
                doc_tags = [doc_tags]
            if not any(t in doc_tags for t in tags):
                continue
        results.append((md_file, config))
    return results


def stage_files(
    files: list[tuple[Path, dict]],
    staging_dir: Path,
    *,
    use_symlinks: bool = True,
    source_dir: Path | None = None,
) -> list[tuple[Path, Path, dict]]:
    """Copy or symlink exportable files into *staging_dir*, returning staged paths.

    Cleans any existing .md symlinks/files in the staging dir first.
    Returns list of (staged_path, original_source_path, frontmatter_dict) tuples
    so callers can map each build output back to the note it came from regardless
    of any output-filename override.

    When *source_dir* is given, a source that is itself a symlink resolving
    *outside* the source tree is skipped (prevents staging out-of-tree targets).
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    root = Path(source_dir).resolve() if source_dir is not None else None

    # Clean previous staged .md sources and any build outputs left from a prior
    # run so deleted/renamed notes don't leave phantom outputs behind.
    _stale_suffixes = {".md", ".pdf", ".docx", ".dotx"}
    for existing in staging_dir.iterdir():
        if (existing.is_symlink() or existing.is_file()) and existing.suffix in _stale_suffixes:
            existing.unlink()

    staged: list[tuple[Path, Path, dict]] = []
    seen_names: set[str] = set()

    for src, fm in files:
        real_src = src.resolve()
        # Security: skip a source that is a symlink pointing outside the tree.
        if root is not None and src.is_symlink():
            try:
                real_src.relative_to(root)
            except ValueError:
                logger.warning("Skipping %s — symlink resolves outside source tree.", src)
                continue

        name = src.name
        if name in seen_names:
            parent_name = src.parent.name.replace(" ", "-").lower()
            name = f"{parent_name}--{name}"
        seen_names.add(name)

        dest = staging_dir / name

        if use_symlinks:
            dest.symlink_to(real_src)
        else:
            shutil.copy2(real_src, dest)

        staged.append((dest, src, fm))

    return staged


def collect_outputs(
    built: list[tuple[Path, Path | None, dict]],
    dest_dir: Path,
    source_dir: Path,
) -> list[Path]:
    """Copy *built* outputs to *dest_dir*, preserving structure.

    *built* is a list of ``(output_path, original_source_path, frontmatter)``
    tuples produced by the build loop. Matching each output to its source
    explicitly (rather than by filename-stem guessing) keeps placement correct
    even when ``output_filename``/``export_filename`` renames the output.

    Output placement logic:
    1. If the note has ``export_path`` in frontmatter → dest_dir / export_path /
    2. Otherwise → mirrors the source directory structure relative to source_dir

    Filename logic:
    1. If the note has ``export_filename`` in frontmatter → use that (extension added)
    2. Otherwise → use the built output's filename verbatim

    Returns list of copied output paths.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()

    copied: list[Path] = []
    for output, orig_path, fm in built:
        if not output.exists():
            continue

        # Determine target directory
        export_path = fm.get("export_path")
        if export_path:
            target_dir = (dest_dir / export_path).resolve()
        elif orig_path is not None:
            try:
                rel = orig_path.relative_to(source_dir)
                target_dir = (dest_dir / rel.parent).resolve()
            except ValueError:
                target_dir = dest_root
        else:
            target_dir = dest_root

        # Security: ensure target stays within dest_dir
        if not target_dir.is_relative_to(dest_root):
            logger.warning(
                "Skipping output %s — export_path %r resolves outside destination directory.",
                output.name,
                export_path,
            )
            continue

        target_dir.mkdir(parents=True, exist_ok=True)

        # Determine filename
        export_filename = fm.get("export_filename")
        if export_filename:
            # Strip any extension and path components — only use the stem as a filename
            clean_name = Path(Path(export_filename).name).stem
            target = target_dir / (clean_name + output.suffix)
        else:
            target = target_dir / output.name

        # Security: final check that resolved target is within dest_dir
        if not target.resolve().is_relative_to(dest_root):
            logger.warning(
                "Skipping output %s — resolved path escapes destination directory.",
                output.name,
            )
            continue

        shutil.copy2(output, target)
        copied.append(target)

    return copied
