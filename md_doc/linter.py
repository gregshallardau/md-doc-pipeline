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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, TemplateSyntaxError, meta

from .config import _find_repo_root, load_config, load_merge_fields
from .renderer import _build_search_dirs, _MarkdownLoader, _strip_frontmatter


_VALID_FORMATS: frozenset[str] = frozenset({"pdf", "docx", "dotx"})
_FIELD_RE = re.compile(r"\[\[(\w+)\]\]")


@dataclass
class LintIssue:
    path: Path
    message: str
    severity: str  # "error" or "warning"

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.path.name}: {self.message}"


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
            issues.append(LintIssue(
                path=doc_path,
                message=f"Frontmatter YAML is invalid: {exc}",
                severity="error",
            ))
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
                issues.append(LintIssue(
                    path=doc_path,
                    message=f"Unknown output format '{fmt}'",
                    severity="error",
                ))

    # ------------------------------------------------------------------
    # 3. Jinja2 body syntax + undeclared variable scan
    # ------------------------------------------------------------------
    search_dirs = _build_search_dirs(doc_path, repo_root)
    loader = _MarkdownLoader(search_dirs)
    env = Environment(loader=loader, autoescape=False, keep_trailing_newline=True)

    try:
        ast = env.parse(body)
    except TemplateSyntaxError as exc:
        issues.append(LintIssue(
            path=doc_path,
            message=f"Jinja2 syntax error: {exc}",
            severity="error",
        ))
        # Can't check variables or includes if template doesn't parse
        return issues

    # Undefined variables
    undeclared = meta.find_undeclared_variables(ast)
    known_vars = set(config.keys())
    for var in sorted(undeclared - known_vars):
        issues.append(LintIssue(
            path=doc_path,
            message=f"Undefined variable '{{{{ {var} }}}}' — not found in config cascade",
            severity="warning",
        ))

    # ------------------------------------------------------------------
    # 4. {% include %} resolution
    # ------------------------------------------------------------------
    referenced_templates = meta.find_referenced_templates(ast)
    for tmpl_name in sorted(referenced_templates):
        resolved = False
        for directory in search_dirs:
            if (directory / tmpl_name).is_file():
                resolved = True
                break
        if not resolved:
            issues.append(LintIssue(
                path=doc_path,
                message=f"Include not found: '{tmpl_name}'",
                severity="error",
            ))

    # ------------------------------------------------------------------
    # 5. [[field]] references
    # ------------------------------------------------------------------
    merge_fields = load_merge_fields(doc_path, repo_root=repo_root)
    if merge_fields:
        used_fields = _FIELD_RE.findall(body)
        for field_name in sorted(set(used_fields)):
            if field_name not in merge_fields:
                issues.append(LintIssue(
                    path=doc_path,
                    message=f"Undefined merge field '[[{field_name}]]' — not in _merge_fields.yml cascade",
                    severity="warning",
                ))

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

    return results
