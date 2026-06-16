"""
Markdown document linter.

Checks documents for issues that would cause build failures or likely
indicate mistakes, without running the full build pipeline.

Checks performed:
  - YAML frontmatter parses correctly
  - outputs: values are recognised formats (pdf / docx / dotx)
  - Jinja2 body syntax is valid
  - {{ variable }} references exist in the resolved config cascade
  - {% include "path" %} targets resolve in the template search path
  - [[field]] references exist in the _merge_fields.yml cascade
    (only checked when at least one _merge_fields.yml is present)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, TemplateSyntaxError, meta

from .config import _find_repo_root, load_config, load_merge_fields
from .renderer import _build_search_dirs, _MarkdownLoader, _strip_frontmatter

_VALID_FORMATS: frozenset[str] = frozenset({"pdf", "docx", "dotx"})
_FIELD_RE = re.compile(r"\[\[(\w+)\]\]")
_PIPE_LINE_RE = re.compile(r"^\s*\|")
_SEP_ROW_RE = re.compile(r"^\s*\|[\s\-:|]*-[\s\-:|]*\|\s*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


@dataclass
class LintIssue:
    path: Path
    message: str
    severity: str  # "error" or "warning"

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.path.name}: {self.message}"


def _frontmatter_jinja_vars(
    frontmatter: dict[str, Any],
    env: Environment,
    _key_prefix: str = "",
) -> dict[str, str]:
    """Find every ``{{ var }}`` reference inside frontmatter string values.

    Walks the frontmatter dict recursively (nested dicts and lists) and
    returns a map of *variable name → first key path* where it appears.
    The key path (e.g. ``"sync_config.path"``) is used by the linter to
    point users at the offending value.

    Templates that fail to parse are skipped — the body-syntax check
    in :func:`lint_file` already reports general template errors.
    """
    found: dict[str, str] = {}

    def _walk(value: Any, key_path: str) -> None:
        if isinstance(value, str):
            try:
                ast = env.parse(value)
            except TemplateSyntaxError:
                return
            for var in meta.find_undeclared_variables(ast):
                found.setdefault(var, key_path)
        elif isinstance(value, dict):
            for k, v in value.items():
                _walk(v, f"{key_path}.{k}" if key_path else str(k))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                _walk(item, f"{key_path}[{i}]")

    for k, v in frontmatter.items():
        _walk(v, str(k))

    return found


def _check_table_separators(body: str, path: Path, issues: list[LintIssue]) -> None:
    """Warn about groups of pipe-table-like lines that have no GFM separator row.

    GFM tables require a separator as the second row (|---|---|).  Without it
    the content is not parsed as a table and renders as plain text in Word.
    """
    lines = body.split("\n")
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            i += 1
            continue
        if _PIPE_LINE_RE.match(line):
            start = i
            group: list[str] = []
            while i < len(lines) and not in_fence and _PIPE_LINE_RE.match(lines[i]):
                group.append(lines[i])
                i += 1
            if len(group) >= 2 and not any(_SEP_ROW_RE.match(ln) for ln in group):
                issues.append(
                    LintIssue(
                        path=path,
                        message=(
                            f"Table at line {start + 1} is missing a separator row "
                            f"(e.g. |---|---|) — without it the table renders as "
                            f"plain text, not a Word table"
                        ),
                        severity="warning",
                    )
                )
        else:
            i += 1


def lint_file(doc_path: Path, repo_root: Path | None = None) -> list[LintIssue]:
    """
    Lint a single Markdown document and return all found issues.

    Parameters
    ----------
    doc_path:
        Path to the ``.md`` file to lint.
    repo_root:
        Optional repo root override; auto-detected if omitted.

    Returns
    -------
    list[LintIssue]
        Empty list means the document is clean.
    """
    doc_path = Path(doc_path).resolve()
    issues: list[LintIssue] = []

    if repo_root is None:
        repo_root = _find_repo_root(doc_path.parent)
    else:
        repo_root = Path(repo_root).resolve()

    raw = doc_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # 0. Line endings
    # ------------------------------------------------------------------
    if "\r\n" in raw or raw.endswith("\r"):
        issues.append(
            LintIssue(
                path=doc_path,
                message="File has Windows (CRLF) line endings — run `md-doc lint --fix` to convert to LF",
                severity="warning",
            )
        )

    if "\x1a" in raw:
        issues.append(
            LintIssue(
                path=doc_path,
                message="File contains ^Z (Windows EOF marker, 0x1A) — run `md-doc lint --fix` to remove",
                severity="warning",
            )
        )

    frontmatter_block, body = _strip_frontmatter(raw)

    # ------------------------------------------------------------------
    # 1. Frontmatter YAML validity
    # ------------------------------------------------------------------
    frontmatter: dict[str, Any] = {}
    if frontmatter_block:
        inner = re.sub(r"^---\s*\n|---\s*\n?$", "", frontmatter_block, flags=re.DOTALL)
        try:
            parsed = yaml.safe_load(inner)
            frontmatter = parsed if isinstance(parsed, dict) else {}
        except yaml.YAMLError as exc:
            issues.append(
                LintIssue(
                    path=doc_path,
                    message=f"Frontmatter YAML is invalid: {exc}",
                    severity="error",
                )
            )
            # Can't continue without valid frontmatter
            return issues

    # ------------------------------------------------------------------
    # 2. outputs: format values
    # ------------------------------------------------------------------
    config = load_config(doc_path, repo_root=repo_root)
    doc_outputs = frontmatter.get("outputs")
    if doc_outputs is not None:
        if isinstance(doc_outputs, str):
            doc_outputs = [doc_outputs]
        for fmt in doc_outputs:
            if fmt not in _VALID_FORMATS:
                issues.append(
                    LintIssue(
                        path=doc_path,
                        message=f"Unknown output format '{fmt}'",
                        severity="error",
                    )
                )

    # ------------------------------------------------------------------
    # 3. Jinja2 body syntax + undeclared variable scan
    # ------------------------------------------------------------------
    search_dirs = _build_search_dirs(doc_path, repo_root)
    loader = _MarkdownLoader(search_dirs)
    env = Environment(loader=loader, autoescape=False, keep_trailing_newline=True)

    try:
        ast = env.parse(body)
    except TemplateSyntaxError as exc:
        issues.append(
            LintIssue(
                path=doc_path,
                message=f"Jinja2 syntax error: {exc}",
                severity="error",
            )
        )
        # Can't check variables or includes if template doesn't parse
        return issues

    # Undefined variables
    undeclared = meta.find_undeclared_variables(ast)
    known_vars = set(config.keys())
    for var in sorted(undeclared - known_vars):
        issues.append(
            LintIssue(
                path=doc_path,
                message=f"Undefined variable '{{{{ {var} }}}}' — not found in config cascade",
                severity="warning",
            )
        )

    # ------------------------------------------------------------------
    # 3b. {{ var }} references inside frontmatter string values
    # ------------------------------------------------------------------
    # Frontmatter values like ``output_filename: "{{ product }}-proposal"`` are
    # evaluated at build time but the body-only check above misses them.  Scan
    # every string value (recursively for nested dicts/lists) for {{ var }}
    # references and verify they exist in the config cascade.
    fm_undeclared = _frontmatter_jinja_vars(frontmatter, env)
    for var, key_path in sorted(fm_undeclared.items()):
        if var not in known_vars:
            issues.append(
                LintIssue(
                    path=doc_path,
                    message=(
                        f"Undefined variable '{{{{ {var} }}}}' in frontmatter "
                        f"value '{key_path}' — not found in config cascade"
                    ),
                    severity="warning",
                )
            )

    # ------------------------------------------------------------------
    # 4. {% include %} resolution
    # ------------------------------------------------------------------
    referenced_templates = meta.find_referenced_templates(ast)
    for tmpl_name in sorted(t for t in referenced_templates if t is not None):
        resolved = False
        for directory in search_dirs:
            if (directory / tmpl_name).is_file():
                resolved = True
                break
        if not resolved:
            issues.append(
                LintIssue(
                    path=doc_path,
                    message=f"Include not found: '{tmpl_name}'",
                    severity="error",
                )
            )

    # ------------------------------------------------------------------
    # 5. [[field]] references
    # ------------------------------------------------------------------
    merge_fields = load_merge_fields(doc_path, repo_root=repo_root)
    if merge_fields:
        used_fields = _FIELD_RE.findall(body)
        for field_name in sorted(set(used_fields)):
            if field_name not in merge_fields:
                issues.append(
                    LintIssue(
                        path=doc_path,
                        message=f"Undefined merge field '[[{field_name}]]' — not in _merge_fields.yml cascade",
                        severity="warning",
                    )
                )

    # ------------------------------------------------------------------
    # 6. Pipe-table content missing GFM separator row
    # ------------------------------------------------------------------
    _check_table_separators(body, doc_path, issues)

    return issues


def lint_template_file(tmpl_path: Path, repo_root: Path | None = None) -> list[LintIssue]:
    """
    Lint a template fragment (.md file inside a ``templates/`` or ``themes/``
    directory).

    Template partials have no frontmatter and receive their ``{{ variable }}``
    context from whichever document includes them, so the checks are narrower
    than :func:`lint_file`:

    Checks performed:
      - CRLF / ^Z line endings
      - Jinja2 syntax is valid
      - ``{% include %}`` targets resolve in the template search path
      - ``[[field]]`` references exist in the ``_merge_fields.yml`` cascade

    Intentionally **not** checked:
      - Frontmatter (templates have none)
      - ``outputs:`` values
      - Undefined ``{{ variable }}`` references (context comes from the caller)
    """
    tmpl_path = Path(tmpl_path).resolve()
    issues: list[LintIssue] = []

    if repo_root is None:
        repo_root = _find_repo_root(tmpl_path.parent)
    else:
        repo_root = Path(repo_root).resolve()

    raw = tmpl_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # 1. Line endings
    # ------------------------------------------------------------------
    if "\r\n" in raw or raw.endswith("\r"):
        issues.append(
            LintIssue(
                path=tmpl_path,
                message="File has Windows (CRLF) line endings — run `md-doc lint --fix` to convert to LF",
                severity="warning",
            )
        )

    if "\x1a" in raw:
        issues.append(
            LintIssue(
                path=tmpl_path,
                message="File contains ^Z (Windows EOF marker, 0x1A) — run `md-doc lint --fix` to remove",
                severity="warning",
            )
        )

    # ------------------------------------------------------------------
    # 2. Jinja2 syntax
    # ------------------------------------------------------------------
    # Build search dirs from the *document context* — the first ancestor
    # directory that isn't itself inside a templates/ or themes/ subtree.
    # At build time Jinja2 resolves includes using the including document's
    # search dirs (which include the templates/ parent), not the template's
    # own directory.  Using the template file's own dir produces false
    # "include not found" errors for siblings and cousins in the tree.
    if repo_root:
        ctx_dir = tmpl_path.parent
        while ctx_dir != repo_root and ctx_dir.parent != ctx_dir:
            try:
                parts = ctx_dir.relative_to(repo_root).parts
            except ValueError:
                break
            if not any(p in {"templates", "themes"} for p in parts):
                break
            ctx_dir = ctx_dir.parent
        # Pass ctx_dir directly — _build_search_dirs uses doc_path.parent when
        # it's a file, or doc_path as-is when it's a directory, so passing the
        # directory itself gives the right search root without needing a
        # synthetic placeholder file.
        search_dirs = _build_search_dirs(ctx_dir, repo_root)
    else:
        search_dirs = [tmpl_path.parent]
    loader = _MarkdownLoader(search_dirs)
    env = Environment(loader=loader, autoescape=False, keep_trailing_newline=True)

    try:
        ast = env.parse(raw)
    except TemplateSyntaxError as exc:
        issues.append(
            LintIssue(
                path=tmpl_path,
                message=f"Jinja2 syntax error: {exc}",
                severity="error",
            )
        )
        return issues

    # ------------------------------------------------------------------
    # 3. {% include %} resolution
    # ------------------------------------------------------------------
    referenced_templates = meta.find_referenced_templates(ast)
    for tmpl_name in sorted(t for t in referenced_templates if t is not None):
        resolved = any((directory / tmpl_name).is_file() for directory in search_dirs)
        if not resolved:
            issues.append(
                LintIssue(
                    path=tmpl_path,
                    message=f"Include not found: '{tmpl_name}'",
                    severity="error",
                )
            )

    # ------------------------------------------------------------------
    # 4. [[field]] references
    # ------------------------------------------------------------------
    merge_fields = load_merge_fields(tmpl_path, repo_root=repo_root)
    if merge_fields:
        for field_name in sorted(set(_FIELD_RE.findall(raw))):
            if field_name not in merge_fields:
                issues.append(
                    LintIssue(
                        path=tmpl_path,
                        message=f"Undefined merge field '[[{field_name}]]' — not in _merge_fields.yml cascade",
                        severity="warning",
                    )
                )

    return issues


def lint_meta_file(meta_path: Path) -> list[LintIssue]:
    """
    Lint a ``_meta.yml`` file for structural issues.

    The cascade only reads ``_meta.yml`` as a single YAML mapping. Common
    mistakes that silently lose data:

    1. **Markdown-style frontmatter delimiters** (``---`` … ``---``).  PyYAML
       reads the first document only, so anything after the second ``---`` is
       silently dropped from the cascade.
    2. **Top-level isn't a mapping** — e.g. a list, a string, or null.

    Both produce errors so they fail loudly during ``md-doc lint``.

    Parameters
    ----------
    meta_path:
        Path to a ``_meta.yml`` file.

    Returns
    -------
    list[LintIssue]
        Empty list when the file is structurally clean.
    """
    meta_path = Path(meta_path).resolve()
    issues: list[LintIssue] = []

    try:
        text = meta_path.read_text(encoding="utf-8")
    except OSError as exc:
        issues.append(LintIssue(meta_path, f"Cannot read file: {exc}", "error"))
        return issues

    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        issues.append(LintIssue(meta_path, f"Invalid YAML: {exc}", "error"))
        return issues

    # Multiple YAML documents (i.e. extra '---' separators in the file) — only
    # the first is read, so config silently goes missing.  This is the bug the
    # check exists to catch.
    if len(docs) > 1:
        issues.append(
            LintIssue(
                meta_path,
                f"_meta.yml contains {len(docs)} YAML documents (separated by "
                f"'---'); only the first is read by the cascade. Remove the "
                f"extra '---' separators and any markdown-style content — "
                f"_meta.yml should be plain key: value pairs.",
                "error",
            )
        )

    if not docs or docs[0] is None:
        # Empty file is fine — treated as no overrides
        return issues

    if not isinstance(docs[0], dict):
        issues.append(
            LintIssue(
                meta_path,
                f"_meta.yml top-level must be a YAML mapping (key: value pairs); "
                f"got {type(docs[0]).__name__}.",
                "error",
            )
        )

    return issues


def lint_directory(root: Path, repo_root: Path | None = None) -> dict[Path, list[LintIssue]]:
    """
    Lint all buildable Markdown documents under *root*.

    Uses the same discovery logic as ``md-doc build`` to find documents.

    Returns
    -------
    dict[Path, list[LintIssue]]
        Mapping of document path → issues.  Documents with no issues are
        not included in the returned dict.
    """
    from .cli import _discover_markdown

    root = Path(root).resolve()
    if repo_root is None:
        repo_root = _find_repo_root(root)

    results: dict[Path, list[LintIssue]] = {}
    for doc_path in _discover_markdown(root):
        doc_issues = lint_file(doc_path, repo_root=repo_root)
        if doc_issues:
            results[doc_path] = doc_issues

    # Lint template/theme fragments — different rule set (no frontmatter checks,
    # no undefined-variable checks; Jinja2 syntax + include resolution only).
    _TEMPLATE_DIRS = {"templates", "themes"}
    _SKIP = {".git", ".venv", "node_modules"}
    for tmpl_path in sorted(root.rglob("*.md")):
        if not any(part in _TEMPLATE_DIRS for part in tmpl_path.parts):
            continue
        if any(part in _SKIP for part in tmpl_path.parts):
            continue
        tmpl_issues = lint_template_file(tmpl_path, repo_root=repo_root)
        if tmpl_issues:
            results[tmpl_path] = tmpl_issues

    # Also lint every _meta.yml in the tree for structural issues (extra '---'
    # separators, non-mapping top-level, invalid YAML).
    for meta_path in sorted(root.rglob("_meta.yml")):
        if any(part in {".git", ".venv", "node_modules"} for part in meta_path.parts):
            continue
        meta_issues = lint_meta_file(meta_path)
        if meta_issues:
            results[meta_path] = meta_issues

    return results
