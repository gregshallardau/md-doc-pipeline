"""
md-doc CLI entrypoint.

Commands:
  md-doc build [ROOT] [--workspace NAME] [--output DIR] [--format pdf|docx|dotx|all]
  md-doc workspaces
  md-doc export [SOURCE] [--output DIR] [--format pdf|docx|dotx|all]
  md-doc register [ROOT]
  md-doc sync [ROOT] [--backend azure|s3|local]
  md-doc theme init [DIR]
  md-doc theme override [DIR]

Wired via pyproject.toml:
  [project.scripts]
  md-doc = "md_doc.cli:main"
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click
import yaml

from .config import load_config, get_output_formats, load_merge_fields, _find_repo_root
from .renderer import render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Directories never containing buildable documents
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".tox",
    "node_modules",
    "__pycache__",
    "site-packages",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
}

# Well-known repo infrastructure files that are not documents
_SKIP_FILES = {
    "readme.md",
    "changelog.md",
    "license.md",
    "licence.md",
    "claude.md",
    "contributing.md",
    "history.md",
    "authors.md",
    "install.md",
    "security.md",
    "code_of_conduct.md",
}


def _discover_markdown(root: Path) -> list[Path]:
    """Return all buildable .md files under root.

    Excludes:
    - Files whose name starts with ``_`` (config/meta files)
    - Files inside ``templates/`` or ``themes/`` directories
    - Files inside dependency/tooling directories (.venv, node_modules, etc.)
    - Well-known repo infrastructure files (README.md, CLAUDE.md, etc.)
    """
    return sorted(
        p
        for p in root.rglob("*.md")
        if not p.name.startswith("_")
        and p.name.lower() not in _SKIP_FILES
        and not _SKIP_DIRS.intersection(p.parts)
        and "templates" not in p.parts
        and "themes" not in p.parts
    )


def _resolve_output_path(
    doc_path: Path, root: Path, output_dir: Path | None, ext: str, *, flat: bool = False
) -> Path:
    """
    Compute output file path.

    If output_dir is given and flat=False (CLI --output), mirror the source tree under it.
    If output_dir is given and flat=True (config output_dir), place the file directly in
    output_dir without mirroring the source tree.
    Otherwise, write output alongside the source file.

    ext can be ".pdf", ".docx", etc., or "-form.pdf" for PDF forms.
    """
    # Handle "-form.pdf" style extensions that don't start with a dot
    if ext.startswith("-") and "." in ext:
        stem_addition, file_ext = ext.rsplit(".", 1)
        file_ext = "." + file_ext
        new_stem = doc_path.stem + stem_addition
        if output_dir is not None:
            if flat:
                return output_dir / (new_stem + file_ext)
            rel = doc_path.relative_to(root)
            return output_dir / rel.parent / (new_stem + file_ext)
        return doc_path.parent / (new_stem + file_ext)
    else:
        # Standard suffix (e.g., ".pdf", ".docx")
        if output_dir is not None:
            if flat:
                return output_dir / (doc_path.stem + ext)
            rel = doc_path.relative_to(root)
            return output_dir / rel.with_suffix(ext)
        return doc_path.with_suffix(ext)


def _apply_filename_override(out_path: Path, config: dict[str, Any], format_name: str) -> Path:
    """Apply output_filename override from config, with Jinja2 variable support.

    The value is rendered against the config dict so ``{{ version }}`` etc. work.
    Any extension the user included is stripped; the correct one for *format_name*
    is always appended automatically.
    """
    raw = config.get("output_filename")
    if not raw:
        return out_path

    from jinja2 import Environment, Undefined

    rendered = Environment(undefined=Undefined).from_string(str(raw)).render(**config)
    # Strip any extension the user may have typed
    stem = Path(rendered).stem if Path(rendered).suffix else rendered

    if format_name == "pdf" and config.get("pdf_forms"):
        filename = stem + "-form.pdf"
    else:
        filename = stem + f".{format_name}"

    return out_path.parent / filename


_REMOTE_WORKSPACES_FILE = "workspace/remote-workspaces.yml"


def _load_remote_workspaces(repo_root: Path) -> dict[str, Any]:
    """Load workspace/remote-workspaces.yml from the repo root. Returns {} if absent."""
    rw_file = repo_root / _REMOTE_WORKSPACES_FILE
    if not rw_file.exists():
        return {}
    with rw_file.open() as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _resolve_workspace(name: str, repo_root: Path) -> Path:
    """Resolve a named workspace to a Path. Raises UsageError if not found."""
    workspaces = _load_remote_workspaces(repo_root)
    if name not in workspaces:
        defined = ", ".join(workspaces.keys()) if workspaces else "(none defined)"
        raise click.UsageError(
            f"Workspace '{name}' not found in {_REMOTE_WORKSPACES_FILE}. "
            f"Defined workspaces: {defined}"
        )
    entry = workspaces[name]
    if isinstance(entry, dict):
        raw_path = entry.get("path", "")
    else:
        raw_path = str(entry)
    resolved = Path(str(raw_path)).expanduser().resolve()
    if not resolved.exists():
        raise click.UsageError(
            f"Workspace '{name}' path does not exist: {resolved}\n"
            f"Check that the share is mounted."
        )
    return resolved


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="md-doc-pipeline")
def main() -> None:
    """Markdown → PDF/DOCX/DOTX document pipeline with cascading config and sync."""


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


@main.command()
@click.argument("root", default=".", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory (mirrors source tree). Defaults to writing alongside source files.",
)
@click.option(
    "--workspace",
    "-w",
    default=None,
    type=str,
    help="Named workspace from workspace/remote-workspaces.yml. Overrides ROOT.",
)
@click.option(
    "--format",
    "-f",
    "fmt",
    default="all",
    type=click.Choice(["pdf", "docx", "dotx", "all"], case_sensitive=False),
    help="Output format(s). Overrides per-document 'outputs' config when set explicitly.",
)
@click.option(
    "--theme",
    "-t",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a _pdf-theme.css file. Overrides the normal theme cascade for this build.",
)
@click.option("--strict", is_flag=True, default=False, help="Fail on undefined Jinja2 variables.")
@click.option(
    "--dry-run", is_flag=True, default=False, help="Print what would be built without building."
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Print full tracebacks on errors.")
def build(
    root: Path,
    output: Path | None,
    workspace: str | None,
    fmt: str,
    theme: Path | None,
    strict: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Build all Markdown documents under ROOT to PDF and/or DOCX.

    ROOT defaults to the current directory. Use --workspace / -w to build a
    named remote workspace defined in workspace/remote-workspaces.yml instead.

    \b
    Examples:
      md-doc build
      md-doc build products/ --output build/
      md-doc build products/ --format pdf
      md-doc build --workspace affinity
      md-doc build -w affinity --format dotx
    """
    repo_root = _find_repo_root(Path.cwd())

    if workspace is not None:
        root = _resolve_workspace(workspace, repo_root)
    else:
        root = root.resolve()
        if not root.exists():
            raise click.UsageError(f"Path does not exist: {root}")

    if output is not None:
        output = output.resolve()

    docs = _discover_markdown(root)
    if not docs:
        click.echo(f"No Markdown documents found under {root}", err=True)
        sys.exit(0)

    click.echo(f"Found {len(docs)} document(s) under {root}")

    errors: list[str] = []

    for doc_path in docs:
        config = load_config(doc_path, repo_root=root)

        if theme is not None:
            config["pdf_theme"] = str(theme.resolve())

        # Determine formats for this document
        if fmt == "all":
            formats = get_output_formats(config)
        else:
            formats = [fmt]

        click.echo(f"  {doc_path.relative_to(root)}  →  {', '.join(formats)}")

        if dry_run:
            continue

        # Render through Jinja2
        try:
            rendered_md = render(doc_path, repo_root=repo_root, strict=strict)
        except Exception as exc:
            click.echo(f"    [ERROR] render failed: {type(exc).__name__}: {exc}", err=True)
            if verbose:
                import traceback
                traceback.print_exc()
            errors.append(str(doc_path))
            continue

        # Resolve effective output dir: CLI --output wins; config output_dir mirrors source tree
        effective_output = output
        flat = False
        if effective_output is None:
            cfg_out = config.get("output_dir")
            if cfg_out:
                cfg_out_path = Path(str(cfg_out)).expanduser()
                effective_output = (root / cfg_out_path).resolve() if not cfg_out_path.is_absolute() else cfg_out_path.resolve()

        # Build each format
        for format_name in formats:
            if format_name == "pdf" and config.get("pdf_forms"):
                ext = "-form.pdf"
            else:
                ext = f".{format_name}"
            out_path = _resolve_output_path(doc_path, root, effective_output, ext, flat=flat)
            out_path = _apply_filename_override(out_path, config, format_name)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                if format_name == "pdf":
                    from .builders.pdf import build as build_pdf  # type: ignore[import]

                    build_pdf(rendered_md, config, out_path, doc_path=doc_path, repo_root=repo_root)
                elif format_name == "docx":
                    from .builders.docx import build as build_docx  # type: ignore[import]

                    build_docx(rendered_md, config, out_path, doc_path=doc_path, repo_root=repo_root)
                elif format_name == "dotx":
                    from .builders.dotx import build as build_dotx  # type: ignore[import]

                    build_dotx(rendered_md, config, out_path, doc_path=doc_path, repo_root=repo_root)
                else:
                    click.echo(f"    [WARN] unknown format '{format_name}' — skipped", err=True)
                    continue
                click.echo(
                    f"    wrote {out_path.relative_to(root) if out_path.is_relative_to(root) else out_path}"
                )
            except ImportError as exc:
                click.echo(
                    f"    [ERROR] builder not available for '{format_name}': {exc}", err=True
                )
                errors.append(str(doc_path))
            except Exception as exc:
                click.echo(f"    [ERROR] build failed ({format_name}): {type(exc).__name__}: {exc}", err=True)
                if verbose:
                    import traceback
                    traceback.print_exc()
                errors.append(str(doc_path))

    if errors:
        click.echo(f"\n{len(errors)} error(s) — check output above.", err=True)
        sys.exit(1)

    if not dry_run:
        click.echo("Build complete.")


# ---------------------------------------------------------------------------
# workspaces
# ---------------------------------------------------------------------------


@main.command("workspaces")
def workspaces_cmd() -> None:
    """List remote workspaces defined in workspace/remote-workspaces.yml.

    \b
    Example:
      md-doc workspaces
    """
    repo_root = _find_repo_root(Path.cwd())
    data = _load_remote_workspaces(repo_root)
    rw_file = repo_root / _REMOTE_WORKSPACES_FILE

    if not data:
        click.echo(f"No remote workspaces defined in {rw_file}")
        click.echo("Create workspace/remote-workspaces.yml to define named remote paths.")
        return

    click.echo(f"Remote workspaces ({rw_file}):\n")
    for name, entry in data.items():
        if isinstance(entry, dict):
            path = entry.get("path", "")
            description = entry.get("description", "")
        else:
            path = str(entry)
            description = ""
        resolved = Path(str(path)).expanduser().resolve()
        status = "✓" if resolved.exists() else "✗ (not mounted)"
        desc_str = f"  {description}" if description else ""
        click.echo(f"  {name:<20} {status}  {resolved}{desc_str}")

    click.echo("\nUsage: md-doc build --workspace <name>")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@main.command()
@click.argument(
    "source", default=".", type=click.Path(file_okay=False, path_type=Path), required=False
)
@click.option(
    "--workspace",
    "-w",
    default=None,
    type=str,
    help="Named workspace from workspace/remote-workspaces.yml. Overrides SOURCE.",
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Destination directory for built outputs. Defaults to SOURCE/Exports/.",
)
@click.option(
    "--format",
    "-f",
    "fmt",
    default="all",
    type=click.Choice(["pdf", "docx", "dotx", "all"], case_sensitive=False),
    help="Output format(s). Defaults to per-document 'export_format' or 'pdf'.",
)
@click.option(
    "--tag", "-t", "tags", multiple=True, help="Only export notes with this tag. Repeatable."
)
@click.option(
    "--no-symlinks", is_flag=True, default=False, help="Copy files instead of symlinking."
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Show what would be exported without building."
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Print full tracebacks on errors.")
def export(
    source: Path | None,
    workspace: str | None,
    output: Path | None,
    fmt: str,
    tags: tuple[str, ...],
    no_symlinks: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Scan SOURCE for Markdown files with ``export: true`` and build them.

    Searches SOURCE recursively for any .md file with ``export: true`` in
    its YAML frontmatter. Notes with ``draft: true`` are skipped. Use --tag
    to filter by tags. Use --workspace / -w to target a named remote workspace.

    Matching files are staged into an internal workspace, built to the
    requested format(s), and outputs are copied to the destination.

    \b
    Examples:
      md-doc export /mnt/NAS/Obsidian/MyVault
      md-doc export -w affinity
      md-doc export -w affinity --output /mnt/NAS/Exports
      md-doc export /mnt/NAS/Obsidian/MyVault --tag cheatsheet
      md-doc export . --format pdf --dry-run
    """
    from .exporter import find_exportable, stage_files, collect_outputs

    repo_root = _find_repo_root(Path.cwd())

    if workspace is not None:
        source = _resolve_workspace(workspace, repo_root)
    elif source is not None:
        source = source.resolve()
        if not source.exists():
            raise click.UsageError(f"Path does not exist: {source}")
    else:
        source = Path.cwd()

    source = source.resolve()

    # Resolve destination: CLI -o > _meta.yml export_folder (walks up from source) > source/Exports/
    if output is not None:
        dest = output.resolve()
    else:
        import yaml as _yaml
        cfg_folder = None
        # Walk up from source looking for export_folder in any _meta.yml
        for candidate in [source, *source.parents]:
            _meta_file = candidate / "_meta.yml"
            if _meta_file.exists():
                _meta = _yaml.safe_load(_meta_file.read_text())
                if isinstance(_meta, dict) and _meta.get("export_folder"):
                    cfg_folder = _meta["export_folder"]
                    break
        if cfg_folder:
            cfg_path = Path(str(cfg_folder)).expanduser()
            dest = (source / cfg_path).resolve() if not cfg_path.is_absolute() else cfg_path.resolve()
        else:
            dest = (source / "exported").resolve()

    click.echo(f"Exporting to: {dest}")

    # Scan for exportable notes
    tag_list = list(tags) if tags else None
    exportable = find_exportable(source, tags=tag_list, repo_root=repo_root)
    if not exportable:
        click.echo(f"No Markdown files with 'export: true' found under {source}")
        sys.exit(0)

    click.echo(f"Found {len(exportable)} exportable note(s):")
    for f, fm in exportable:
        try:
            rel = f.relative_to(source)
        except ValueError:
            rel = f
        export_path = fm.get("export_path")
        suffix = f"  → {export_path}/" if export_path else ""
        click.echo(f"  {rel}{suffix}")

    if dry_run:
        click.echo(f"\nWould export to: {dest}")
        return

    # Stage into a temporary workspace inside the pipeline
    pipeline_root = Path(__file__).resolve().parent.parent
    staging_dir = pipeline_root / "workspace" / "obsidian-exports" / "docs"

    staged = stage_files(exportable, staging_dir, use_symlinks=not no_symlinks)
    click.echo(f"\nStaged {len(staged)} file(s) for build.")

    # Build using the same logic as the build command
    errors: list[str] = []
    for doc_path, fm in staged:
        config = load_config(doc_path, repo_root=source)

        # Determine formats: CLI flag > frontmatter export_format > outputs > pdf
        if fmt == "all":
            export_fmt = fm.get("export_format") or config.get("export_format")
            if export_fmt:
                formats = [export_fmt] if isinstance(export_fmt, str) else export_fmt
            else:
                formats = get_output_formats(config)
        else:
            formats = [fmt]

        click.echo(f"  {doc_path.name}  →  {', '.join(formats)}")

        try:
            rendered_md = render(doc_path, repo_root=source, strict=False)
        except Exception as exc:
            click.echo(f"    [ERROR] render failed: {type(exc).__name__}: {exc}", err=True)
            if verbose:
                import traceback
                traceback.print_exc()
            errors.append(str(doc_path))
            continue

        for format_name in formats:
            if format_name == "pdf" and config.get("pdf_forms"):
                ext = "-form.pdf"
            else:
                ext = f".{format_name}"
            out_path = _resolve_output_path(doc_path, staging_dir, None, ext)
            out_path = _apply_filename_override(out_path, config, format_name)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                if format_name == "pdf":
                    from .builders.pdf import build as build_pdf

                    build_pdf(rendered_md, config, out_path, doc_path=doc_path)
                elif format_name == "docx":
                    from .builders.docx import build as build_docx

                    build_docx(
                        rendered_md, config, out_path, doc_path=doc_path, repo_root=source
                    )
                elif format_name == "dotx":
                    from .builders.dotx import build as build_dotx

                    build_dotx(
                        rendered_md, config, out_path, doc_path=doc_path, repo_root=source
                    )
                else:
                    click.echo(f"    [WARN] unknown format '{format_name}' — skipped", err=True)
                    continue
                click.echo(f"    built {out_path.name}")
            except ImportError as exc:
                click.echo(
                    f"    [ERROR] builder not available for '{format_name}': {exc}", err=True
                )
                errors.append(str(doc_path))
            except Exception as exc:
                click.echo(f"    [ERROR] build failed ({format_name}): {type(exc).__name__}: {exc}", err=True)
                if verbose:
                    import traceback
                    traceback.print_exc()
                errors.append(str(doc_path))

    # Collect outputs to destination, preserving folder structure
    copied = collect_outputs(staging_dir, dest, source, staged, exportable)
    click.echo(f"\n{len(copied)} output(s) exported to {dest}")
    for p in copied:
        try:
            click.echo(f"  {p.relative_to(dest)}")
        except ValueError:
            click.echo(f"  {p}")

    if errors:
        click.echo(f"{len(errors)} error(s) — check output above.", err=True)
        sys.exit(1)

    click.echo("Export complete.")


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------


@main.command()
@click.argument("root", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
def lint(root: Path) -> None:
    """Lint all Markdown documents under ROOT for build errors.

    Checks:
      - Frontmatter YAML is valid
      - outputs: values are recognised formats
      - Jinja2 syntax is valid
      - {{ variables }} exist in the config cascade (warning)
      - {% include %} targets resolve (error)
      - [[fields]] exist in _merge_fields.yml cascade (warning, if schema present)

    Exits non-zero if any errors are found. Warnings are displayed but
    do not affect the exit code.

    \b
    Examples:
      md-doc lint
      md-doc lint workspace/acme/
    """
    from .linter import lint_directory

    root = Path(root).resolve()
    results = lint_directory(root, repo_root=root)

    if not results:
        click.echo(
            "No documents found." if not list(_discover_markdown(root)) else "All documents OK."
        )
        return

    error_count = 0
    warning_count = 0

    for doc_path, issues in sorted(results.items()):
        try:
            rel = doc_path.relative_to(root)
        except ValueError:
            rel = doc_path
        for issue in issues:
            marker = "ERROR" if issue.severity == "error" else "warn "
            click.echo(f"  {marker}  {rel}: {issue.message}")
            if issue.severity == "error":
                error_count += 1
            else:
                warning_count += 1

    parts = []
    if error_count:
        parts.append(f"{error_count} error(s)")
    if warning_count:
        parts.append(f"{warning_count} warning(s)")
    click.echo(f"\n{', '.join(parts)}")

    if error_count:
        sys.exit(1)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


@main.command()
@click.argument("root", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Output path for register.json (default: ROOT/register.json).",
)
@click.option(
    "--md/--no-md",
    "write_md",
    default=True,
    show_default=True,
    help="Also write a Markdown register alongside the JSON.",
)
def register(root: Path, output: Path | None, write_md: bool) -> None:
    """Generate a document register (register.json + register.md) for ROOT.

    Scans ROOT for built documents and config metadata, then writes a
    machine-readable register.

    \b
    Examples:
      md-doc register
      md-doc register products/
      md-doc register products/ --output products/register.json
    """
    root = root.resolve()
    json_path = (output or root / "register.json").resolve()

    try:
        from .register import generate  # type: ignore[import]
    except ImportError as exc:
        click.echo(f"[ERROR] register module not available: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Scanning {root} …")
    try:
        generate(root, json_path=json_path, write_md=write_md)
    except Exception as exc:
        click.echo(f"[ERROR] {exc}", err=True)
        sys.exit(1)

    click.echo(f"Register written to {json_path}")
    if write_md:
        click.echo(f"Markdown register written to {json_path.with_suffix('.md')}")


# ---------------------------------------------------------------------------
# fields
# ---------------------------------------------------------------------------


@main.command()
@click.argument(
    "directory", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
def fields(directory: Path) -> None:
    """List available [[merge fields]] at DIRECTORY level.

    Shows all fields from the _merge_fields.yml cascade at this location,
    grouped by the file they come from (shallowest to deepest).

    \b
    Examples:
      md-doc fields
      md-doc fields workspace/acme/
      md-doc fields workspace/acme/clients/stormfront/
    """
    from .config import _find_repo_root, _load_yaml_file

    directory = Path(directory).resolve()
    repo_root = _find_repo_root(directory)

    try:
        rel = directory.relative_to(repo_root)
        parts = [repo_root] + [
            repo_root / Path(*rel.parts[:i]) for i in range(1, len(rel.parts) + 1)
        ]
    except ValueError:
        parts = [directory]

    found_any = False
    for level_dir in parts:
        field_file = level_dir / "_merge_fields.yml"
        layer = _load_yaml_file(field_file)
        if not layer:
            continue
        found_any = True
        try:
            label = field_file.relative_to(repo_root)
        except ValueError:
            label = field_file
        click.echo(f"\n{label}")
        click.echo("-" * len(str(label)))
        for name, description in layer.items():
            click.echo(f"  [[{name}]]  —  {description}")

    if not found_any:
        click.echo("No merge fields defined at this level or above.")
        click.echo("Create a _merge_fields.yml file to define available [[fields]].")


# ---------------------------------------------------------------------------
# new
# ---------------------------------------------------------------------------


@main.group()
def new() -> None:
    """Scaffold new folders and documents."""


@new.command("folder")
@click.argument("name")
@click.option(
    "--in",
    "parent",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Parent directory to create the folder in (default: current directory).",
)
def new_folder(name: str, parent: Path) -> None:
    """Create a new project folder NAME with a starter _meta.yml.

    NAME may be a relative path (e.g. clients/acme) — intermediate
    directories are created automatically.

    \b
    Examples:
      md-doc new folder clients/acme --in workspace/blueshift/
      md-doc new folder products/pulse --in workspace/blueshift/
    """
    parent = Path(parent).resolve()
    target = parent / name

    if target.exists():
        raise click.ClickException(f"{target} already exists.")

    target.mkdir(parents=True)

    # Load inherited config so we know what keys are already resolved
    config = load_config(parent, repo_root=None)
    inherited_keys = set(config.keys())

    # Write a minimal _meta.yml — only prompt for keys not already inherited
    meta_lines = ["# Add keys specific to this level.\n"]
    meta_path = target / "_meta.yml"
    meta_path.write_text("".join(meta_lines), encoding="utf-8")

    click.echo(f"  created  {target}/")
    click.echo(f"  created  {meta_path}")
    if inherited_keys:
        click.echo(f"\nInherited from parent config: {', '.join(sorted(inherited_keys))}")
    click.echo("\nEdit _meta.yml to add keys specific to this level.")


@new.command("doc")
@click.argument("name")
@click.option(
    "--in",
    "parent",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory to create the document in (default: current directory).",
)
def new_doc(name: str, parent: Path) -> None:
    """Create a new Markdown document NAME.

    Prompts for output format and cover page preference, then writes a
    ready-to-edit .md file with correct frontmatter.

    \b
    Examples:
      md-doc new doc proposal --in workspace/blueshift/clients/acme/
      md-doc new doc q1-report --in workspace/blueshift/products/nova/
    """
    parent = Path(parent).resolve()

    # Strip .md suffix if user included it
    stem = name[:-3] if name.lower().endswith(".md") else name
    doc_path = parent / f"{stem}.md"

    if doc_path.exists():
        raise click.ClickException(f"{doc_path} already exists.")

    # Load cascade context so we can show inherited values
    config = load_config(parent, repo_root=None)
    available_fields = load_merge_fields(parent, repo_root=None)

    click.echo(f"\nCreating {doc_path.name}\n")
    if config:
        click.echo(
            "Inherited config: " + ", ".join(f"{k}={v!r}" for k, v in sorted(config.items()))
        )
    if available_fields:
        click.echo(
            "Available [[fields]]: " + ", ".join(f"[[{k}]]" for k in sorted(available_fields))
        )
    click.echo()

    fmt = click.prompt(
        "Output format",
        type=click.Choice(["pdf", "docx", "dotx"], case_sensitive=False),
        default=(
            config.get("outputs", ["pdf"])[0]
            if isinstance(config.get("outputs"), list)
            else config.get("outputs", "pdf")
        ),
    )
    cover = click.confirm("Include cover page?", default=True)

    title = stem.replace("-", " ").replace("_", " ").title()

    frontmatter = (
        f"---\n"
        f"title: {title}\n"
        f"outputs: [{fmt}]\n"
        f"cover_page: {'true' if cover else 'false'}\n"
        f"---\n"
        f"\n"
        f"# {title}\n"
        f"\n"
    )

    doc_path.write_text(frontmatter, encoding="utf-8")
    click.echo(f"\n  created  {doc_path}")
    click.echo("\nEdit the file to add your content.")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


@main.command()
@click.argument("root", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--backend",
    "-b",
    default=None,
    type=click.Choice(["azure", "s3", "local"], case_sensitive=False),
    help="Storage backend. Auto-detected from environment/config if omitted.",
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Print what would be synced without uploading."
)
def sync(root: Path, backend: str | None, dry_run: bool) -> None:
    """Sync built documents under ROOT to remote storage.

    Backend configuration (connection strings, share names, bucket names, etc.)
    is read from environment variables and/or _meta.yml config.

    \b
    Examples:
      md-doc sync
      md-doc sync products/
      md-doc sync products/ --backend azure
      md-doc sync products/ --dry-run
    """
    root = root.resolve()

    try:
        from .sync import run as run_sync  # type: ignore[import]
    except ImportError as exc:
        click.echo(f"[ERROR] sync module not available: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Syncing {root} …")
    try:
        run_sync(root, backend=backend, dry_run=dry_run)
    except Exception as exc:
        click.echo(f"[ERROR] {exc}", err=True)
        sys.exit(1)

    if dry_run:
        click.echo("Dry run complete — nothing uploaded.")
    else:
        click.echo("Sync complete.")


# ---------------------------------------------------------------------------
# theme
# ---------------------------------------------------------------------------


def _prompt_color(prompt: str, default: str) -> str:
    """Prompt for a hex colour with validation."""
    from .theme import validate_hex_color

    while True:
        raw = click.prompt(prompt, default=default)
        try:
            return validate_hex_color(raw)
        except ValueError as exc:
            click.echo(f"  {exc} — try again.", err=True)


@main.group()
def theme() -> None:
    """Create and manage PDF themes."""


@theme.command("init")
@click.argument(
    "directory",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
)
def theme_init(directory: Path) -> None:
    """Generate a full _pdf-theme.css for a project or company root.

    \b
    Examples:
      md-doc theme init
      md-doc theme init examples/blueshift/
    """
    from .theme import generate_base_theme, generate_meta_yml

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    click.echo("Creating a new PDF theme. Press Enter to accept defaults.\n")

    org_name = click.prompt("Organisation name (used in page footer)", default="My Organisation")
    primary = _prompt_color("Primary colour  (cover, headings, table headers)", "#1b4f72")
    accent = _prompt_color("Accent colour   (h2, links, code borders)        ", "#2e86c1")
    body_text = _prompt_color("Body text colour                                 ", "#1a1a2e")
    muted = _prompt_color("Muted text colour (h3, captions, footer)         ", "#5d6d7e")
    body_font = click.prompt(
        "Body font family",
        default="'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
    )
    mono_font = click.prompt(
        "Monospace font   ",
        default="'Consolas', 'Courier New', 'Liberation Mono', monospace",
    )
    page_size = click.prompt(
        "Page size", default="A4", type=click.Choice(["A4", "Letter"], case_sensitive=False)
    )
    cover_page = click.confirm("Include cover page by default?", default=True)

    css = generate_base_theme(
        org_name=org_name,
        primary=primary,
        accent=accent,
        body_text=body_text,
        muted=muted,
        body_font=body_font,
        mono_font=mono_font,
        page_size=page_size.upper(),
    )

    css_path = directory / "_pdf-theme.css"
    css_path.write_text(css, encoding="utf-8")
    click.echo(f"\n  wrote {css_path}")

    meta_path = directory / "_meta.yml"
    if meta_path.exists():
        click.echo(f"  skipped {meta_path}  (already exists)")
    else:
        meta_path.write_text(generate_meta_yml(org_name, cover_page), encoding="utf-8")
        click.echo(f"  wrote {meta_path}")

    click.echo("\nTheme created. Edit _pdf-theme.css to fine-tune.")


@theme.command("override")
@click.argument(
    "directory",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
)
def theme_override(directory: Path) -> None:
    """Generate a minimal colour-override _pdf-theme.css for a sub-folder.

    Finds the nearest parent _pdf-theme.css automatically and writes an
    @import + colour overrides only. Everything else is inherited.

    \b
    Examples:
      md-doc theme override
      md-doc theme override examples/blueshift/products/pulse/
    """
    from .theme import (
        find_parent_theme,
        generate_override_theme,
        relative_import_path,
    )

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    # Find parent theme
    parent = find_parent_theme(directory)
    if parent:
        import_path = relative_import_path(directory, parent)
        click.echo(f"  Found parent theme: {parent}")
        click.echo(f"  Will import as:     {import_path}\n")
    else:
        click.echo("  No parent _pdf-theme.css found in ancestor directories.")
        import_path = click.prompt("  Enter @import path manually", default="../_pdf-theme.css")

    sub_name = click.prompt(
        "Sub-brand name (used in page footer)", default="My Organisation — Sub Brand"
    )
    primary = _prompt_color("Primary colour  (cover, headings, table headers)", "#1b4f72")
    accent = _prompt_color("Accent colour   (h2, links, code borders)        ", "#2e86c1")

    css = generate_override_theme(
        sub_name=sub_name,
        import_path=import_path,
        primary=primary,
        accent=accent,
    )

    css_path = directory / "_pdf-theme.css"
    css_path.write_text(css, encoding="utf-8")
    click.echo(f"\n  wrote {css_path}")


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


@main.command()
@click.argument("file_path", type=click.Path())
@click.option(
    "--dest",
    type=str,
    default="templates/",
    help="Destination folder or path pattern for extracted Markdown. Default: templates/",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing output file without prompting.",
)
def extract(file_path: str, dest: str, force: bool) -> None:
    """Extract Markdown from a PDF or DOCX file.

    Converts a PDF or DOCX file to Markdown and saves it to the specified destination.
    Output filename is derived from the source filename (with .md extension).

    \b
    Examples:
        md-doc extract proposal.pdf --dest templates/
        md-doc extract contract.docx --dest snippets/
        md-doc extract form.pdf  # defaults to templates/
    """
    from md_doc.extractors import extract_file

    try:
        markdown_content = extract_file(file_path)

        source_path = Path(file_path)
        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)

        output_name = source_path.stem + ".md"
        output_file = dest_path / output_name

        if output_file.exists() and not force:
            raise click.ClickException(f"{output_file} already exists. Use --force to overwrite.")

        output_file.write_text(markdown_content or "", encoding="utf-8")

        click.echo(f"Extracted: {source_path.name} -> {output_file}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Exit(1)  # type: ignore[operator]
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Exit(1)  # type: ignore[operator]
