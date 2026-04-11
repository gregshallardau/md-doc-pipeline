"""
md-doc CLI entrypoint.

Commands:
  md-doc build [ROOT] [--output DIR] [--format pdf|docx|all]
  md-doc register [ROOT]
  md-doc sync [ROOT] [--backend azure|s3|local]

Wired via pyproject.toml:
  [project.scripts]
  md-doc = "md_doc.cli:main"
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .config import load_config, get_output_formats
from .renderer import render


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _discover_markdown(root: Path) -> list[Path]:
    """Return all .md files under root, excluding _meta files and templates."""
    return sorted(
        p for p in root.rglob("*.md")
        if not p.name.startswith("_")
        and "templates" not in p.parts
        and "themes" not in p.parts
        and ".git" not in p.parts
    )


def _resolve_output_path(doc_path: Path, root: Path, output_dir: Path | None, ext: str) -> Path:
    """
    Compute output file path.

    If output_dir is given, mirror the source tree under it.
    Otherwise, write output alongside the source file.
    """
    if output_dir is not None:
        rel = doc_path.relative_to(root)
        return output_dir / rel.with_suffix(ext)
    return doc_path.with_suffix(ext)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="md-doc-pipeline")
def main() -> None:
    """Markdown → PDF/DOCX document pipeline with cascading config and sync."""


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

@main.command()
@click.argument("root", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--output", "-o",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory (mirrors source tree). Defaults to writing alongside source files.",
)
@click.option(
    "--format", "-f", "fmt",
    default="all",
    type=click.Choice(["pdf", "docx", "all"], case_sensitive=False),
    help="Output format(s). Overrides per-document 'outputs' config when set explicitly.",
)
@click.option("--strict", is_flag=True, default=False, help="Fail on undefined Jinja2 variables.")
@click.option("--dry-run", is_flag=True, default=False, help="Print what would be built without building.")
def build(root: Path, output: Path | None, fmt: str, strict: bool, dry_run: bool) -> None:
    """Build all Markdown documents under ROOT to PDF and/or DOCX.

    ROOT defaults to the current directory.

    \b
    Examples:
      md-doc build
      md-doc build products/ --output build/
      md-doc build products/ --format pdf
    """
    root = root.resolve()
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
            rendered_md = render(doc_path, repo_root=root, strict=strict)
        except Exception as exc:
            click.echo(f"    [ERROR] render failed: {exc}", err=True)
            errors.append(str(doc_path))
            continue

        # Build each format
        for format_name in formats:
            out_path = _resolve_output_path(doc_path, root, output, f".{format_name}")
            out_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                if format_name == "pdf":
                    from .builders.pdf import build as build_pdf  # type: ignore[import]
                    build_pdf(rendered_md, config, out_path, doc_path=doc_path)
                elif format_name == "docx":
                    from .builders.docx import build as build_docx  # type: ignore[import]
                    build_docx(rendered_md, config, out_path)
                else:
                    click.echo(f"    [WARN] unknown format '{format_name}' — skipped", err=True)
                    continue
                click.echo(f"    wrote {out_path.relative_to(root) if out_path.is_relative_to(root) else out_path}")
            except ImportError as exc:
                click.echo(f"    [ERROR] builder not available for '{format_name}': {exc}", err=True)
                errors.append(str(doc_path))
            except Exception as exc:
                click.echo(f"    [ERROR] build failed ({format_name}): {exc}", err=True)
                errors.append(str(doc_path))

    if errors:
        click.echo(f"\n{len(errors)} error(s) — check output above.", err=True)
        sys.exit(1)

    if not dry_run:
        click.echo("Build complete.")


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

@main.command()
@click.argument("root", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output", "-o", default=None, type=click.Path(path_type=Path),
              help="Output path for register.json (default: ROOT/register.json).")
@click.option("--md/--no-md", "write_md", default=True, show_default=True,
              help="Also write a Markdown register alongside the JSON.")
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
# sync
# ---------------------------------------------------------------------------

@main.command()
@click.argument("root", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--backend", "-b",
    default=None,
    type=click.Choice(["azure", "s3", "local"], case_sensitive=False),
    help="Storage backend. Auto-detected from environment/config if omitted.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Print what would be synced without uploading.")
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
