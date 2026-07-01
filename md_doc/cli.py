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

import os
import sys
from pathlib import Path
from typing import Any

import click
import yaml

from .config import _find_repo_root, get_output_formats, load_config, load_merge_fields
from .renderer import render

# ─── Output styling helpers ──────────────────────────────────────────────────
# Click's colour output auto-disables when stdout is piped, so these are safe
# to use everywhere.  Set MD_DOC_NO_COLOR=1 to force colour off.

_NO_COLOR = bool(os.environ.get("MD_DOC_NO_COLOR"))


def _style(text: str, **kw: Any) -> str:
    """``click.style`` wrapper that respects the MD_DOC_NO_COLOR env var."""
    if _NO_COLOR:
        return text
    return click.style(text, **kw)


def _err(text: str) -> str:
    """Red, bold — for errors."""
    return _style(text, fg="red", bold=True)


def _warn(text: str) -> str:
    """Yellow — for warnings."""
    return _style(text, fg="yellow")


def _ok(text: str) -> str:
    """Green, bold — for success."""
    return _style(text, fg="green", bold=True)


def _info(text: str) -> str:
    """Cyan — for paths and identifiers."""
    return _style(text, fg="cyan")


def _dim(text: str) -> str:
    """Dim — for muted / secondary text."""
    return _style(text, dim=True)


def _bold(text: str) -> str:
    return _style(text, bold=True)


def _short_path(p: Path, *, verbose: bool = False) -> str:
    """Return a short, cwd-relative path string when sensible.

    Default: use ``os.path.relpath`` so paths under cwd come out as
    ``workspace/acme/proposal.md`` and paths outside cwd come out as
    ``../../shared/x``.  Falls back to the absolute path on Windows
    cross-drive errors.

    With ``verbose=True``, always returns the absolute path.
    """
    if verbose:
        return str(p)
    try:
        return os.path.relpath(Path(p), Path.cwd())
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Directories never containing buildable documents
_SKIP_DIRS = {
    ".git",
    ".github",
    ".gitlab",
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


_BUILD_DEP_NAMES = (
    "_meta.yml",
    "_pdf-theme.css",
    "_theme.css",
    "_docx-theme.css",
    "_merge_fields.yml",
)


def _newest_dep_mtime(doc_path: Path, repo_root: Path, extra: list[Path] | None = None) -> float:
    """Return the newest mtime among a document's build inputs.

    Inputs are the source ``.md`` plus, at every directory from *repo_root* down
    to the document, any ``_meta.yml``/theme/``_merge_fields.yml`` file and every
    file under a ``templates/`` subdir (include fragments). Used to decide
    whether an existing output is stale. Returns ``inf`` if nothing is found so
    the caller always rebuilds.
    """
    deps: list[Path] = [doc_path]
    doc_dir = doc_path.parent
    dirs: list[Path]
    try:
        rel = doc_dir.relative_to(repo_root)
        dirs = [repo_root] + [
            repo_root / Path(*rel.parts[:i]) for i in range(1, len(rel.parts) + 1)
        ]
    except ValueError:
        dirs = [doc_dir]
    for d in dirs:
        for name in _BUILD_DEP_NAMES:
            deps.append(d / name)
        tdir = d / "templates"
        if tdir.is_dir():
            deps.extend(p for p in tdir.rglob("*") if p.is_file())
    if extra:
        deps.extend(extra)
    mtimes = [p.stat().st_mtime for p in deps if p.exists()]
    return max(mtimes) if mtimes else float("inf")


def _build_document(
    doc_path: Path,
    *,
    root: Path,
    cascade_root: Path,
    output: Path | None,
    theme: Path | None,
    fmt: str,
    strict: bool,
    force: bool,
    verbose: bool,
) -> dict[str, Any]:
    """Build one document to all its formats. Pure/worker-safe: returns a result
    dict (no console I/O) so it can run in a process pool.

    Result keys: ``rel`` (str), ``formats`` (list[str]), ``events``
    (list of ``(level, text)`` where level is wrote|skip|error|warn),
    ``built`` (int), ``skipped`` (int), ``errored`` (bool).
    """
    events: list[tuple[str, str]] = []
    built = 0
    skipped = 0
    errored = False

    config = load_config(doc_path, repo_root=cascade_root)
    config = _render_config_strings(config)
    if theme is not None:
        config["pdf_theme"] = str(theme.resolve())

    formats = get_output_formats(config) if fmt == "all" else [fmt]

    effective_output = output
    if effective_output is None:
        cfg_out = config.get("output_dir")
        if cfg_out:
            cfg_out_path = Path(str(cfg_out)).expanduser()
            effective_output = (
                (root / cfg_out_path).resolve()
                if not cfg_out_path.is_absolute()
                else cfg_out_path.resolve()
            )

    theme_dep = [theme.resolve()] if theme is not None else None
    dep_mtime = _newest_dep_mtime(doc_path, cascade_root, extra=theme_dep)

    stale: list[tuple[str, Path]] = []
    for format_name in formats:
        ext = (
            "-form.pdf" if (format_name == "pdf" and config.get("pdf_forms")) else f".{format_name}"
        )
        out_path = _resolve_output_path(doc_path, root, effective_output, ext)
        try:
            out_path = _apply_filename_override(out_path, config, format_name)
        except Exception as exc:
            events.append(("error", f"output_filename render failed: {type(exc).__name__}: {exc}"))
            errored = True
            continue
        if not force and out_path.exists() and out_path.stat().st_mtime >= dep_mtime:
            events.append(("skip", f"up to date {out_path.name}"))
            skipped += 1
        else:
            stale.append((format_name, out_path))

    if not stale:
        return {
            "rel": _rel(doc_path, root),
            "formats": formats,
            "events": events,
            "built": built,
            "skipped": skipped,
            "errored": errored,
        }

    try:
        rendered_md = render(doc_path, repo_root=cascade_root, strict=strict)
    except Exception as exc:
        msg = f"render failed: {type(exc).__name__}: {exc}"
        if verbose:
            import traceback

            msg += "\n" + traceback.format_exc()
        events.append(("error", msg))
        return {
            "rel": _rel(doc_path, root),
            "formats": formats,
            "events": events,
            "built": built,
            "skipped": skipped,
            "errored": True,
        }

    for format_name, out_path in stale:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if format_name == "pdf":
                from .builders.pdf import build as build_pdf  # type: ignore[import]

                build_pdf(rendered_md, config, out_path, doc_path=doc_path, repo_root=cascade_root)
            elif format_name == "docx":
                from .builders.docx import build as build_docx  # type: ignore[import]

                build_docx(rendered_md, config, out_path, doc_path=doc_path, repo_root=cascade_root)
            elif format_name == "dotx":
                from .builders.dotx import build as build_dotx  # type: ignore[import]

                build_dotx(rendered_md, config, out_path, doc_path=doc_path, repo_root=cascade_root)
            else:
                events.append(("warn", f"unknown format '{format_name}' — skipped"))
                continue
            built += 1
            if out_path.is_relative_to(root):
                rel_out = str(out_path.relative_to(root))
            else:
                rel_out = _short_path(out_path, verbose=verbose)
            events.append(("wrote", rel_out))
        except ImportError as exc:
            events.append(("error", f"builder not available for '{format_name}': {exc}"))
            errored = True
        except Exception as exc:
            msg = f"build failed ({format_name}): {type(exc).__name__}: {exc}"
            if verbose:
                import traceback

                msg += "\n" + traceback.format_exc()
            events.append(("error", msg))
            errored = True

    return {
        "rel": _rel(doc_path, root),
        "formats": formats,
        "events": events,
        "built": built,
        "skipped": skipped,
        "errored": errored,
    }


def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _print_doc_result(res: dict[str, Any]) -> None:
    """Render a :func:`_build_document` result to the console."""
    click.echo(f"  {_info(res['rel'])}  →  {_bold(', '.join(res['formats']))}")
    for level, text in res["events"]:
        if level == "wrote":
            click.echo(f"    {_ok('✓')} wrote {_info(text)}")
        elif level == "skip":
            click.echo(f"    {_dim('·')} {_dim(text)}")
        elif level == "warn":
            click.echo(f"    {_warn('WARN')} {text}", err=True)
        else:  # error
            click.echo(f"    {_err('ERROR')} {text}", err=True)


def _render_config_strings(config: dict[str, Any]) -> dict[str, Any]:
    """Render Jinja2 expressions in string config values against the config itself.

    Frontmatter values like ``title: "{{ product_name | title }} Guidelines"``
    are stored as raw strings by load_config().  This function resolves them so
    builders receive the final text rather than the template expression.

    Uses DebugUndefined so that references to genuinely missing variables are
    kept as ``{{ var }}`` rather than silently becoming empty strings.
    """
    from jinja2 import DebugUndefined
    from jinja2.sandbox import SandboxedEnvironment

    env = SandboxedEnvironment(undefined=DebugUndefined, trim_blocks=True, lstrip_blocks=True)
    result = dict(config)
    for key, value in config.items():
        if isinstance(value, str) and "{{" in value:
            try:
                result[key] = env.from_string(value).render(**config)
            except Exception:
                pass  # leave unrendered on any error
    return result


def _apply_filename_override(out_path: Path, config: dict[str, Any], format_name: str) -> Path:
    """Apply output_filename override from config, with Jinja2 variable support.

    The value is rendered against the config dict so ``{{ version }}`` etc. work.
    Any extension the user included is stripped; the correct one for *format_name*
    is always appended automatically.

    Uses StrictUndefined so that an undefined variable in ``output_filename``
    raises ``UndefinedError`` rather than silently rendering as an empty
    string (which produced filenames like ``"-proposal.pdf"``).
    """
    raw = config.get("output_filename")
    if not raw:
        return out_path

    from jinja2 import StrictUndefined
    from jinja2.sandbox import SandboxedEnvironment

    rendered = (
        SandboxedEnvironment(undefined=StrictUndefined).from_string(str(raw)).render(**config)
    )
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


def _resolve_workspace_root(workspace: str, root: Path, repo_root: Path) -> Path:
    """Resolve ``-w workspace`` + optional ``ROOT`` subdir into a single path.

    When the user runs e.g. ``md-doc build -w acme products/nova``, the
    positional ``ROOT`` is interpreted as a path *relative to the workspace*
    rather than relative to the current directory.  This avoids forcing users
    to type out absolute paths or ``cd`` into the workspace just to operate
    on a sub-tree.

    Prints the standard "Workspace: ..." confirmation line so users see
    exactly where the operation is happening.

    Rejects subdirs that escape the workspace root (``..`` traversal etc.)
    and subdirs that don't exist.
    """
    workspace_root = _resolve_workspace(workspace, repo_root)

    # ``Path(".")`` is the Click default — user didn't provide a positional arg.
    if str(root) == ".":
        click.echo(
            f"{_bold('Workspace:')} {_info(workspace)}  →  " f"{_info(_short_path(workspace_root))}"
        )
        return workspace_root

    candidate = (workspace_root / root).resolve()
    workspace_root_resolved = workspace_root.resolve()

    # Block path traversal: a sub-arg like "../other-workspace" must not escape.
    try:
        candidate.relative_to(workspace_root_resolved)
    except ValueError as exc:
        raise click.UsageError(
            f"Subpath '{root}' escapes workspace '{workspace}': {candidate}"
        ) from exc

    if not candidate.exists():
        raise click.UsageError(
            f"Subpath '{root}' not found in workspace '{workspace}': {candidate}"
        )

    rel = candidate.relative_to(workspace_root_resolved)
    click.echo(
        f"{_bold('Workspace:')} {_info(workspace)}/{_info(str(rel))}  →  "
        f"{_info(_short_path(candidate))}"
    )
    return candidate


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
@click.argument("root", default=".", type=click.Path(path_type=Path))
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
    "--no-lint",
    is_flag=True,
    default=False,
    help=(
        "Skip the pre-flight lint check that runs before build. "
        "Lint errors normally abort the build with a clear list of issues; "
        "use this flag to build anyway (e.g. while iterating)."
    ),
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Print what would be built without building."
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help=(
        "Rebuild every document even if its output is newer than the source, "
        "config, theme and templates. By default up-to-date outputs are skipped."
    ),
)
@click.option(
    "--jobs",
    "-j",
    default=1,
    type=click.IntRange(min=1),
    help="Build this many documents in parallel (process pool). Default: 1 (sequential).",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Print full tracebacks on errors."
)
def build(
    root: Path,
    output: Path | None,
    workspace: str | None,
    fmt: str,
    theme: Path | None,
    strict: bool,
    no_lint: bool,
    dry_run: bool,
    force: bool,
    jobs: int,
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
      md-doc build --workspace acme
      md-doc build -w acme --format dotx
    """
    repo_root = _find_repo_root(Path.cwd())

    if workspace is not None:
        root = _resolve_workspace_root(workspace, root, repo_root)
    else:
        root = root.resolve()
        if not root.exists():
            raise click.UsageError(f"Path does not exist: {root}")

    if output is not None:
        output = output.resolve()

    # Accept a single .md file as ROOT — build only that file
    single_file: Path | None = None
    if root.is_file():
        if root.suffix != ".md":
            raise click.UsageError(f"Not a Markdown file: {root}")
        single_file = root
        root = root.parent

    docs = [single_file] if single_file else _discover_markdown(root)
    if not docs:
        click.echo(
            _dim(f"No Markdown documents found under {_short_path(root, verbose=verbose)}"),
            err=True,
        )
        sys.exit(0)

    click.echo(
        f"{_bold(f'Found {len(docs)} document(s)')} under "
        f"{_info(_short_path(root, verbose=verbose))}"
    )

    # Walk *up* from the build target to find the actual git repo root.  The
    # config / theme / template cascade walks UP from each doc to this root,
    # so building a sub-tree (e.g. ``md-doc build workspace/acme/``) still
    # picks up _meta.yml files defined higher up the directory tree.
    cascade_root = _find_repo_root(root)

    # Pre-flight lint — abort on errors so users see all issues in one pass
    # rather than having the build halt-and-resume on the first broken doc.
    # Warnings are printed but don't abort.
    if not no_lint:
        from .linter import lint_directory as _lint_dir

        lint_results = _lint_dir(root, repo_root=cascade_root)
        lint_errors: list[str] = []
        lint_warnings: list[str] = []
        for path, issues in sorted(lint_results.items()):
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = path
            for issue in issues:
                line = f"  {_info(str(rel))}: {issue.message}"
                if issue.severity == "error":
                    lint_errors.append(f"  {_err('ERROR')}{line}")
                else:
                    lint_warnings.append(f"  {_warn('warn ')}{line}")

        if lint_warnings:
            click.echo(_dim("Lint warnings:"))
            for w in lint_warnings:
                click.echo(w)

        if lint_errors:
            click.echo(_err("Lint errors — aborting build (use --no-lint to skip):"), err=True)
            for e in lint_errors:
                click.echo(e, err=True)
            sys.exit(1)

    errors: list[str] = []
    skipped = 0

    # Dry-run: just list what would be built (per-document config/formats).
    if dry_run:
        for doc_path in docs:
            config = _render_config_strings(load_config(doc_path, repo_root=cascade_root))
            formats = get_output_formats(config) if fmt == "all" else [fmt]
            click.echo(f"  {_info(_rel(doc_path, root))}  →  {_bold(', '.join(formats))}")
        click.echo(_dim("Dry run — nothing built."))
        return

    def _build_one(d: Path) -> dict[str, Any]:
        # _build_document must be called by reference (module-level, picklable)
        # in the pool path; keyword args below are all picklable.
        return _build_document(
            d,
            root=root,
            cascade_root=cascade_root,
            output=output,
            theme=theme,
            fmt=fmt,
            strict=strict,
            force=force,
            verbose=verbose,
        )

    def _tally(res: dict[str, Any]) -> None:
        nonlocal skipped
        skipped += res["skipped"]
        if res["errored"]:
            errors.append(res["rel"])

    if jobs > 1 and len(docs) > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = [
                pool.submit(
                    _build_document,
                    d,
                    root=root,
                    cascade_root=cascade_root,
                    output=output,
                    theme=theme,
                    fmt=fmt,
                    strict=strict,
                    force=force,
                    verbose=verbose,
                )
                for d in docs
            ]
            for fut in futures:  # submission order → deterministic output
                res = fut.result()
                _print_doc_result(res)
                _tally(res)
    else:
        for doc_path in docs:
            res = _build_one(doc_path)
            _print_doc_result(res)
            _tally(res)

    if errors:
        click.echo("\n" + _err(f"{len(errors)} error(s)") + " — check output above.", err=True)
        sys.exit(1)

    if not dry_run:
        suffix = f" ({skipped} up to date, skipped)" if skipped else ""
        click.echo(_ok("✓ Build complete.") + _dim(suffix))


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
        click.echo(_dim(f"No remote workspaces defined in {rw_file}"))
        click.echo(_dim("Create workspace/remote-workspaces.yml to define named remote paths."))
        return

    click.echo(_bold(f"Remote workspaces ({rw_file}):") + "\n")
    for name, entry in data.items():
        if isinstance(entry, dict):
            path = entry.get("path", "")
            description = entry.get("description", "")
        else:
            path = str(entry)
            description = ""
        resolved = Path(str(path)).expanduser().resolve()
        if resolved.exists():
            status = _ok("✓")
        else:
            status = _err("✗") + _dim(" (not mounted)")
        desc_str = f"  {_dim(description)}" if description else ""
        click.echo(f"  {_bold(f'{name:<20}')} {status}  {_info(str(resolved))}{desc_str}")

    click.echo("\n" + _dim("Usage: md-doc build --workspace <name>"))


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
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Print full tracebacks on errors."
)
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
      md-doc export -w acme
      md-doc export -w acme --output /mnt/NAS/Exports
      md-doc export /mnt/NAS/Obsidian/MyVault --tag cheatsheet
      md-doc export . --format pdf --dry-run
    """
    from .exporter import find_exportable, stage_files

    repo_root = _find_repo_root(Path.cwd())

    if workspace is not None:
        # When -w is given, treat the (default-or-given) source positional as
        # a sub-path within the workspace.
        source = _resolve_workspace_root(
            workspace, source if source is not None else Path("."), repo_root
        )
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
            dest = (
                (source / cfg_path).resolve() if not cfg_path.is_absolute() else cfg_path.resolve()
            )
        else:
            dest = (source / "Exports").resolve()

    click.echo(f"{_bold('Exporting to:')} {_info(str(dest))}")

    # Scan for exportable notes
    tag_list = list(tags) if tags else None
    exportable = find_exportable(source, tags=tag_list, repo_root=repo_root)
    if not exportable:
        click.echo(_dim(f"No Markdown files with 'export: true' found under {source}"))
        sys.exit(0)

    click.echo(_bold(f"Found {len(exportable)} exportable note(s):"))
    for f, fm in exportable:
        try:
            rel = f.relative_to(source)
        except ValueError:
            rel = f
        export_path = fm.get("export_path")
        suffix = f"  → {_info(str(export_path))}/" if export_path else ""
        click.echo(f"  {_info(str(rel))}{suffix}")

    if dry_run:
        click.echo("\n" + _dim(f"Would export to: {dest}"))
        return

    # Stage into a unique per-invocation directory so concurrent exports (e.g. a
    # local run overlapping a CI job) can't clobber each other's staging area.
    import shutil
    import tempfile

    staging_dir = Path(tempfile.mkdtemp(prefix="md-doc-export-"))
    try:
        staged = stage_files(
            exportable, staging_dir, use_symlinks=not no_symlinks, source_dir=source
        )
        _run_export_build(staged, staging_dir, source, dest, fmt, verbose)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
    return


def _run_export_build(
    staged: list,
    staging_dir: Path,
    source: Path,
    dest: Path,
    fmt: str,
    verbose: bool,
) -> None:
    from .exporter import collect_outputs

    click.echo("\n" + _dim(f"Staged {len(staged)} file(s) for build."))

    # Build using the same logic as the build command. Track each produced
    # output alongside its original source note and frontmatter so outputs are
    # placed correctly even when output_filename renames them.
    built_outputs: list[tuple[Path, Path | None, dict]] = []
    errors: list[str] = []
    for doc_path, orig_path, fm in staged:
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

        click.echo(f"  {_info(doc_path.name)}  →  {_bold(', '.join(formats))}")

        try:
            rendered_md = render(doc_path, repo_root=source, strict=False)
        except Exception as exc:
            click.echo(f"    {_err('ERROR')} render failed: {type(exc).__name__}: {exc}", err=True)
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
            try:
                out_path = _apply_filename_override(out_path, config, format_name)
            except Exception as exc:
                click.echo(
                    f"    {_err('ERROR')} bad output_filename: {type(exc).__name__}: {exc}",
                    err=True,
                )
                errors.append(str(doc_path))
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                if format_name == "pdf":
                    from .builders.pdf import build as build_pdf

                    build_pdf(rendered_md, config, out_path, doc_path=doc_path)
                elif format_name == "docx":
                    from .builders.docx import build as build_docx

                    build_docx(rendered_md, config, out_path, doc_path=doc_path, repo_root=source)
                elif format_name == "dotx":
                    from .builders.dotx import build as build_dotx

                    build_dotx(rendered_md, config, out_path, doc_path=doc_path, repo_root=source)
                else:
                    click.echo(
                        f"    {_warn('WARN')} unknown format '{format_name}' — skipped",
                        err=True,
                    )
                    continue
                built_outputs.append((out_path, orig_path, fm))
                click.echo(f"    {_ok('✓')} built {_info(out_path.name)}")
            except ImportError as exc:
                click.echo(
                    f"    {_err('ERROR')} builder not available for '{format_name}': {exc}",
                    err=True,
                )
                errors.append(str(doc_path))
            except Exception as exc:
                click.echo(
                    f"    {_err('ERROR')} build failed ({format_name}): "
                    f"{type(exc).__name__}: {exc}",
                    err=True,
                )
                if verbose:
                    import traceback

                    traceback.print_exc()
                errors.append(str(doc_path))

    # Collect outputs to destination, preserving folder structure
    copied = collect_outputs(built_outputs, dest, source)
    click.echo("\n" + _ok(f"✓ {len(copied)} output(s) exported to ") + _info(str(dest)))
    for p in copied:
        try:
            click.echo(f"  {_info(str(p.relative_to(dest)))}")
        except ValueError:
            click.echo(f"  {_info(str(p))}")

    if errors:
        click.echo(_err(f"{len(errors)} error(s)") + " — check output above.", err=True)
        sys.exit(1)

    click.echo(_ok("✓ Export complete."))


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------


@main.command()
@click.argument("root", default=".", type=click.Path(path_type=Path))
@click.option(
    "--workspace",
    "-w",
    default=None,
    help="Lint a named remote workspace defined in workspace/remote-workspaces.yml.",
)
@click.option(
    "--render",
    is_flag=True,
    default=False,
    help=(
        "Also dry-run a strict Jinja2 render of every doc (body + frontmatter "
        "values) so any missing variable surfaces as an error, not silently as "
        "an empty string."
    ),
)
@click.option(
    "--fix",
    is_flag=True,
    default=False,
    help="Auto-fix repairable issues in-place (currently: CRLF → LF line endings).",
)
def lint(root: Path, workspace: str | None, render: bool, fix: bool) -> None:
    """Lint all Markdown documents under ROOT for build errors.

    Checks:
      - Frontmatter YAML is valid
      - outputs: values are recognised formats
      - Jinja2 syntax is valid
      - {{ variables }} in the body exist in the config cascade (warning)
      - {{ variables }} in frontmatter string values exist in the config cascade (warning)
      - {% include %} targets resolve (error)
      - [[fields]] exist in _merge_fields.yml cascade (warning, if schema present)

    With --render, additionally runs a full strict render of every document.
    This catches variables used in conditionals, loops, or filters that escape
    the static AST scan. Any UndefinedError is reported as an error.

    Use -w / --workspace to lint a named remote workspace defined in
    workspace/remote-workspaces.yml.

    Exits non-zero if any errors are found. Warnings are displayed but
    do not affect the exit code.

    \b
    Examples:
      md-doc lint
      md-doc lint workspace/acme/
      md-doc lint -w acme
      md-doc lint --render workspace/   # full dry-run of every doc
    """
    from jinja2 import UndefinedError

    from .linter import LintIssue, lint_directory
    from .renderer import render as _render_doc

    if workspace is not None:
        repo_root = _find_repo_root(Path.cwd())
        root = _resolve_workspace_root(workspace, root, repo_root)
    else:
        root = Path(root).resolve()
        if not root.exists():
            raise click.UsageError(f"Path does not exist: {root}")

    # Walk *up* from the lint target to find the actual repo root so the
    # config / merge-fields cascade picks up _meta.yml files defined above
    # the user's chosen subdirectory.
    cascade_root = _find_repo_root(root)

    # Accept a single .md file as ROOT — lint only that file
    if root.is_file():
        if root.suffix != ".md":
            raise click.UsageError(f"Not a Markdown file: {root}")
        from .linter import lint_file as _lint_file, lint_template_file as _lint_tmpl_file

        single_file = root
        root = root.parent  # needed so _discover_markdown checks below work
        is_template = any(part in {"templates", "themes"} for part in single_file.parts)
        file_issues = (
            _lint_tmpl_file(single_file, repo_root=cascade_root)
            if is_template
            else _lint_file(single_file, repo_root=cascade_root)
        )
        results = {single_file: file_issues} if file_issues else {}
    else:
        results = lint_directory(root, repo_root=cascade_root)

    # --fix: rewrite CRLF files to LF before reporting
    if fix:
        fixed: list[Path] = []
        # Fix documents that the linter flagged
        for path, issues in results.items():
            if any("CRLF" in issue.message or "^Z" in issue.message for issue in issues):
                # Files flagged for line-ending problems may contain non-UTF-8
                # bytes; tolerate them so one bad file doesn't abort the run.
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    click.echo(_err("ERROR") + f"  could not read {path}: {exc}", err=True)
                    continue
                text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x1a", "")
                path.write_text(text, encoding="utf-8")
                fixed.append(path)
        if fixed:
            for p in fixed:
                click.echo(_ok("fixed") + f"  {p.relative_to(root)}  (CRLF → LF)")
            # Re-lint so the CRLF warnings are cleared from the report
            results = lint_directory(root, repo_root=cascade_root)

    error_count = 0
    warning_count = 0

    # --render: do a strict render of every doc and capture undefined-variable
    # errors that the static AST scan can't see (vars hidden behind filters,
    # conditionals, loops, etc.).
    if render:
        for doc_path in _discover_markdown(root):
            try:
                _render_doc(doc_path, repo_root=cascade_root, strict=True)
            except UndefinedError as exc:
                results.setdefault(doc_path, []).append(
                    LintIssue(
                        path=doc_path,
                        message=f"Strict render: {exc}",
                        severity="error",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                # Other render errors (template syntax, missing include, etc.)
                # are also surfaced so users see the full picture in one pass.
                results.setdefault(doc_path, []).append(
                    LintIssue(
                        path=doc_path,
                        message=f"Strict render failed: {exc}",
                        severity="error",
                    )
                )

    if not results:
        if list(_discover_markdown(root)):
            click.echo(_ok("✓ All documents OK."))
        else:
            click.echo(_dim("No documents found."))
        return

    for doc_path, issues in sorted(results.items()):
        try:
            rel = doc_path.relative_to(root)
        except ValueError:
            rel = doc_path
        for issue in issues:
            if issue.severity == "error":
                marker = _err("ERROR")
                error_count += 1
            else:
                marker = _warn("warn ")
                warning_count += 1
            click.echo(f"  {marker}  {_info(str(rel))}: {issue.message}")

    parts = []
    if error_count:
        parts.append(_err(f"{error_count} error(s)"))
    if warning_count:
        parts.append(_warn(f"{warning_count} warning(s)"))
    if not parts:
        parts.append(_ok("clean"))
    click.echo("\n" + ", ".join(parts))

    if error_count:
        sys.exit(1)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


@main.command()
@click.argument("root", default=".", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--workspace",
    "-w",
    default=None,
    help="Register a named remote workspace defined in workspace/remote-workspaces.yml.",
)
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
def register(root: Path, workspace: str | None, output: Path | None, write_md: bool) -> None:
    """Generate a document register (register.json + register.md) for ROOT.

    Scans ROOT for built documents and config metadata, then writes a
    machine-readable register.

    \b
    Examples:
      md-doc register
      md-doc register products/
      md-doc register -w acme
      md-doc register products/ --output products/register.json
    """
    if workspace is not None:
        repo_root = _find_repo_root(Path.cwd())
        root = _resolve_workspace_root(workspace, root, repo_root)
    else:
        root = root.resolve()
        if not root.exists():
            raise click.UsageError(f"Path does not exist: {root}")
    json_path = (output or root / "register.json").resolve()

    try:
        from .register import generate  # type: ignore[import]
    except ImportError as exc:
        click.echo(_err("ERROR") + f" register module not available: {exc}", err=True)
        sys.exit(1)

    click.echo(f"{_dim('Scanning')} {_info(str(root))} …")
    try:
        generate(root, json_path=json_path, write_md=write_md)
    except Exception as exc:
        click.echo(f"{_err('ERROR')} {exc}", err=True)
        sys.exit(1)

    click.echo(_ok("✓") + f" Register written to {_info(str(json_path))}")
    if write_md:
        click.echo(
            _ok("✓") + f" Markdown register written to {_info(str(json_path.with_suffix('.md')))}"
        )


# ---------------------------------------------------------------------------
# fields
# ---------------------------------------------------------------------------


@main.command()
@click.argument(
    "directory", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option(
    "--workspace",
    "-w",
    default=None,
    help="List fields for a named remote workspace from workspace/remote-workspaces.yml.",
)
def fields(directory: Path, workspace: str | None) -> None:
    """List available [[merge fields]] at DIRECTORY level.

    Shows all fields from the _merge_fields.yml cascade at this location,
    grouped by the file they come from (shallowest to deepest).

    \b
    Examples:
      md-doc fields
      md-doc fields workspace/acme/
      md-doc fields workspace/acme/clients/stormfront/
      md-doc fields -w acme
    """
    from .config import _find_repo_root as _local_find_repo_root
    from .config import _load_yaml_file

    if workspace is not None:
        repo_root_outer = _find_repo_root(Path.cwd())
        directory = _resolve_workspace_root(workspace, directory, repo_root_outer)
    else:
        directory = Path(directory).resolve()
    repo_root = _local_find_repo_root(directory)

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
        click.echo("\n" + _bold(str(label)))
        click.echo(_dim("-" * len(str(label))))
        for name, description in layer.items():
            click.echo(f"  {_info(f'[[{name}]]')}  —  {description}")

    if not found_any:
        click.echo(_dim("No merge fields defined at this level or above."))
        click.echo(_dim("Create a _merge_fields.yml file to define available [[fields]]."))


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

    click.echo(f"  {_ok('✓')} created  {_info(str(target))}/")
    click.echo(f"  {_ok('✓')} created  {_info(str(meta_path))}")
    if inherited_keys:
        click.echo(
            "\n" + _dim(f"Inherited from parent config: {', '.join(sorted(inherited_keys))}")
        )
    click.echo("\n" + _dim("Edit _meta.yml to add keys specific to this level."))


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

    click.echo("\n" + _bold(f"Creating {doc_path.name}") + "\n")
    if config:
        click.echo(
            _dim("Inherited config: ")
            + _dim(", ".join(f"{k}={v!r}" for k, v in sorted(config.items())))
        )
    if available_fields:
        click.echo(
            _dim("Available [[fields]]: ")
            + ", ".join(_info(f"[[{k}]]") for k in sorted(available_fields))
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
    click.echo("\n" + f"  {_ok('✓')} created  {_info(str(doc_path))}")
    click.echo("\n" + _dim("Edit the file to add your content."))


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


@main.command()
@click.argument("root", default=".", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--workspace",
    "-w",
    default=None,
    help="Sync a named remote workspace defined in workspace/remote-workspaces.yml.",
)
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
def sync(root: Path, workspace: str | None, backend: str | None, dry_run: bool) -> None:
    """Sync built documents under ROOT to remote storage.

    Backend configuration (connection strings, share names, bucket names, etc.)
    is read from environment variables and/or _meta.yml config.

    \b
    Examples:
      md-doc sync
      md-doc sync products/
      md-doc sync -w acme
      md-doc sync products/ --backend azure
      md-doc sync products/ --dry-run
    """
    if workspace is not None:
        repo_root = _find_repo_root(Path.cwd())
        root = _resolve_workspace_root(workspace, root, repo_root)
    else:
        root = root.resolve()
        if not root.exists():
            raise click.UsageError(f"Path does not exist: {root}")

    try:
        from .sync import run as run_sync  # type: ignore[import]
    except ImportError as exc:
        click.echo(f"{_err('ERROR')} sync module not available: {exc}", err=True)
        sys.exit(1)

    click.echo(f"{_dim('Syncing')} {_info(str(root))} …")
    try:
        run_sync(root, backend=backend, dry_run=dry_run)
    except Exception as exc:
        click.echo(f"{_err('ERROR')} {exc}", err=True)
        sys.exit(1)

    if dry_run:
        click.echo(_dim("Dry run complete — nothing uploaded."))
    else:
        click.echo(_ok("✓ Sync complete."))


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
            click.echo(f"  {_warn(str(exc))} — try again.", err=True)


@main.group()
def theme() -> None:
    """Create and manage PDF themes."""


@theme.command("init")
@click.argument(
    "directory",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--force", is_flag=True, default=False, help="Overwrite an existing _pdf-theme.css.")
def theme_init(directory: Path, force: bool) -> None:
    """Generate a full _pdf-theme.css for a project or company root.

    \b
    Examples:
      md-doc theme init
      md-doc theme init examples/blueshift/
    """
    from .theme import generate_base_theme, generate_meta_yml

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    css_path = directory / "_pdf-theme.css"
    if css_path.exists() and not force:
        raise click.ClickException(f"{css_path} already exists. Use --force to overwrite.")

    click.echo(
        _bold("Creating a new PDF theme.") + " " + _dim("Press Enter to accept defaults.") + "\n"
    )

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
    click.echo(f"\n  {_ok('✓')} wrote {_info(str(css_path))}")

    meta_path = directory / "_meta.yml"
    if meta_path.exists():
        click.echo(f"  {_dim('·')} skipped {_dim(str(meta_path))}  {_dim('(already exists)')}")
    else:
        meta_path.write_text(generate_meta_yml(org_name, cover_page), encoding="utf-8")
        click.echo(f"  {_ok('✓')} wrote {_info(str(meta_path))}")

    click.echo("\n" + _ok("✓ Theme created.") + " " + _dim("Edit _pdf-theme.css to fine-tune."))


@theme.command("override")
@click.argument(
    "directory",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--force", is_flag=True, default=False, help="Overwrite an existing _pdf-theme.css.")
def theme_override(directory: Path, force: bool) -> None:
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

    css_path = directory / "_pdf-theme.css"
    if css_path.exists() and not force:
        raise click.ClickException(f"{css_path} already exists. Use --force to overwrite.")

    # Find parent theme
    parent = find_parent_theme(directory)
    if parent:
        import_path = relative_import_path(directory, parent)
        click.echo(f"  {_dim('Found parent theme:')} {_info(str(parent))}")
        click.echo(f"  {_dim('Will import as:    ')} {_info(import_path)}\n")
    else:
        click.echo(_warn("  No parent _pdf-theme.css found in ancestor directories."))
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
    click.echo(f"\n  {_ok('✓')} wrote {_info(str(css_path))}")


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

        click.echo(f"{_ok('✓')} Extracted: {_info(source_path.name)} → {_info(str(output_file))}")

    except FileNotFoundError as e:
        click.echo(f"{_err('ERROR')} {e}", err=True)
        sys.exit(1)
    except ValueError as e:
        click.echo(f"{_err('ERROR')} {e}", err=True)
        sys.exit(1)
