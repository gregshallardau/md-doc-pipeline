# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-07-02

Major reliability, parity, and hardening release.

### Added
- **PDF ↔ Word parity**: the docx/dotx builders now match the PDF builder for
  section heading bars, body images, Mermaid diagrams (rasterized to PNG via the
  optional `cairosvg` / `[mermaid]` extra), three-slot footers with `{page}` /
  `{pages}` fields, standalone header text/logo, nested-list indentation, and a
  richer cover page. `table_col_widths` now also applies to PDF output.
- **`md-doc doctor`** — preflight that checks the Python version, core imports, a
  live WeasyPrint render (surfaces missing system libraries with install hints),
  and reports optional extras (s3/azure/mermaid).
- **Config schema validation** wired into `md-doc lint` and the build pre-flight:
  warns on likely typos of reserved keys and errors on wrong-typed/enum values,
  while leaving custom Jinja-variable keys alone.
- **Incremental builds** (skip outputs newer than source/config/theme/templates;
  `--force` to override) and **parallel builds** (`--jobs N`).
- `[mermaid]` optional dependency extra (`cairosvg`).

### Changed
- **Resilient sync**: each file uploads independently with bounded retry and
  backoff; a partial failure reports an uploaded/failed summary and exits
  non-zero instead of aborting silently. Local copies are atomic.
- **Concurrency-safe export** staging (unique per-run temp dir).
- Document bodies render in a Jinja2 sandbox (blocks build-time code execution).
- CI now type-checks with mypy as a gate, enforces a coverage floor, and installs
  the WeasyPrint/cairo system libraries.

### Fixed
- Numerous correctness bugs from the code review: `md-doc extract` crash,
  `export: true` no longer optional, `output_filename`/`export_filename` output
  placement, Mermaid ER attributes / full-circle pie & donut / subgraph edge
  members, frontmatter without a trailing newline, and CSS/HTML injection vectors
  in the PDF builder (colors, footer/header strings, form-field attributes).

[Unreleased]: https://github.com/gregshallardau/md-doc-pipeline/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/gregshallardau/md-doc-pipeline/releases/tag/v0.2.0
