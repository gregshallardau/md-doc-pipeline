# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **DOCX cover page now mirrors the PDF cover.** The Word cover previously used
  the built-in serif *Title*/*Subtitle* styles (nothing like the PDF), a
  full-width divider, colon'd metadata, and an inline footer. It now renders an
  explicit large bold title in the theme's `$primary` colour and body font, an
  accent uppercase "REPORT" label, a short accent divider rule, colon-free
  metadata (`Prepared by {author}` / `Date {date}` with a bold body-coloured
  label + muted value), and a confidentiality footer anchored to the bottom of
  the page — matching the PDF's `_build_cover` layout.
- **PDF↔DOCX page-break & structural parity.** The docx builder now injects the
  same page breaks as the PDF builder (APPENDIX-section H2s and explicit
  `<!-- pagebreak -->`), sets *keep-with-next* on headings so they don't strand
  at a page bottom, and reads the paper **size and margins from the theme's
  `@page`** rule (A4/Letter/Legal/A3, incl. landscape) instead of hardcoding A4 —
  so both formats share the same text width and break at the same points.
  Definition lists (`term`/`:`)
  now render in docx too (bold term + indented definition). Note: exact
  page-for-page identity isn't guaranteed (WeasyPrint and Word are different
  layout engines), but declared breaks and structure now line up.

## [0.3.0] — 2026-07-02

### Added
- **PPTX (PowerPoint) output** via a new `python-pptx` builder. `outputs: [pptx]`
  or `md-doc build --format pptx` segments Markdown into slides — first H1 (or
  `title`) → title slide, later H1s → section slides, each H2 → a content slide;
  `<!-- slide -->` forces a break and `<!-- notes: … -->` adds speaker notes.
  Bullets (with nesting), tables, images, code, blockquotes, and Mermaid
  diagrams (as PNGs) are supported. New keys: `slide_split`, `slide_size`,
  `pptx_template`.
- **Theming parity** across PDF / docx / pptx: slides apply the full CSS theme
  palette — heading colours (H1/H2), body colour + font family, strong/em/code
  colours, blockquote styling, and table header + alternating-row colours —
  from the same `_pdf-theme.css`/`_theme.css` cascade the other builders use.
  (Font *sizes* stay slide-appropriate rather than inheriting print pt sizes.)
- `md-doc doctor` now also checks `python-pptx`.

### Changed
- Shared image/Mermaid helpers extracted to `md_doc/builders/_assets.py` and
  reused by the docx and pptx builders.
- Sync and register now include `.pptx` (and `.dotx`) outputs.

### Fixed
- Mermaid flowchart nodes with **unquoted** labels (`A[Plan]`, `A(Go)`, `A{Q}`,
  etc.) now parse and render — previously only quoted labels (`A["Plan"]`) were
  recognised, so unquoted nodes were dropped and layout crashed with a
  `KeyError`. Affects all builders (PDF/docx/pptx).

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

[Unreleased]: https://github.com/gregshallardau/md-doc-pipeline/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/gregshallardau/md-doc-pipeline/releases/tag/v0.3.0
[0.2.0]: https://github.com/gregshallardau/md-doc-pipeline/releases/tag/v0.2.0
