"""
md-doc CLI entrypoint.

Commands:
  md-doc build [ROOT] [--output DIR] [--format pdf|docx|dotx|all]
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
    """Markdown → PDF/DOCX/DOTX document pipeline with cascading config and sync."""


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
    type=click.Choice(["pdf", "docx", "dotx", "all"], case_sensitive=False),
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
                elif format_name == "dotx":
                    from .builders.dotx import build as build_dotx  # type: ignore[import]
                    build_dotx(rendered_md, config, out_path, doc_path=doc_path)
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
    primary  = _prompt_color("Primary colour  (cover, headings, table headers)", "#1b4f72")
    accent   = _prompt_color("Accent colour   (h2, links, code borders)        ", "#2e86c1")
    body_text = _prompt_color("Body text colour                                 ", "#1a1a2e")
    muted    = _prompt_color("Muted text colour (h3, captions, footer)         ", "#5d6d7e")
    body_font = click.prompt(
        "Body font family",
        default="'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
    )
    mono_font = click.prompt(
        "Monospace font   ",
        default="'Consolas', 'Courier New', 'Liberation Mono', monospace",
    )
    page_size  = click.prompt("Page size", default="A4", type=click.Choice(["A4", "Letter"], case_sensitive=False))
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
        validate_hex_color,
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

    sub_name = click.prompt("Sub-brand name (used in page footer)", default="My Organisation — Sub Brand")
    primary  = _prompt_color("Primary colour  (cover, headings, table headers)", "#1b4f72")
    accent   = _prompt_color("Accent colour   (h2, links, code borders)        ", "#2e86c1")

    css = generate_override_theme(
        sub_name=sub_name,
        import_path=import_path,
        primary=primary,
        accent=accent,
    )

    css_path = directory / "_pdf-theme.css"
    css_path.write_text(css, encoding="utf-8")
    click.echo(f"\n  wrote {css_path}")
