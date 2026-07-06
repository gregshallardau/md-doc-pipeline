# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **PDF forms build-out** (insurance-application grade; full guide in
  `docs/pdf-forms-guide.md`):
  - `?[box] … ?[/box]` — bordered field-grid construct (labels + `*hints*`
    inside cells, `|` column splits, `widths=72,28`, colspan for short rows)
    and `?[yesno: name]` Yes/No checkbox pairs.
  - `**bold**`/`*italic*` labels now render inside `?[row]`/`?[box]` cells;
    fields inside ordinary markdown tables render borderless, filling the cell.
  - `required`, `readonly`, `title` (tooltip) and `<option selected>` now
    **actually reach the PDF** — WeasyPrint drops them; md-doc patches the
    AcroForm via a `finisher` hook. `checked`, `value`, `maxlength` verified
    native. New input types `tel`/`url`; event-handler attributes rejected.
  - **`.dotx` gets real Word form fields from the same source**: text-ish
    `?[...]` → Text Form Fields, `checkbox`/`yesno` → FORMCHECKBOX,
    `select`/`radio` → FORMDROPDOWN (options included). Plain docx renders
    escaped `________` fill-ins (previously mangled by markdown bold parsing).
  - **Form linting**: unknown field types, duplicate field names (AcroForm
    links same-named fields), and `?[…]` without `pdf_forms: true`.
  - Signature fields render as a clean rule (was a dark filled bar) and stay
    on one page. Example: `examples/blueshift/clients/stormfront-inc/liability-application.md`.
- **Headerless tables.** An all-empty markdown header row (`| | |`) now
  renders as a table without a header band in every format — markdown
  requires a header row syntactically, so this is the opt-out idiom
  (previously the empty row still rendered as a theme-shaded band).
- **List spacing from CSS in Word.** `li { margin / line-height }` in the
  theme now sets Word's *List Bullet*/*List Number* style spacing — the same
  rules the PDF already reads, so tight lists can be tuned once for both
  formats (previously bullets inherited Normal's paragraph spacing and line
  height and couldn't be tightened).
- **Brand defaults from theme CSS (`--mddoc-*` custom properties).** The
  look-related config keys (header-bar colour/height/padding, cover bar and
  stripe sizes, cover footer colour, section bar colours, header logo height)
  can now be set once in the theme CSS — `:root { --mddoc-header-bar-color:
  #002a5b; … }` — instead of the base `_meta.yml`. YAML keys still win at any
  cascade level, so per-folder/per-document overrides work unchanged. Feature
  toggles and content stay YAML-only by design.
- **Word header/footer distance from CSS.** `@page { --docx-header-distance:
  8mm; --docx-footer-distance: 6mm; }` in the Word theme cascade sets Word's
  header/footer-from-edge (python-docx defaulted both to 12.7mm). Custom
  properties, so WeasyPrint ignores them and the PDF is unaffected.

### Fixed
- **The PDF header bar now follows the theme's side margins.** The full-bleed
  bar hardcoded the default 25/20mm left/right margins for its edge offsets
  and content padding — a theme with different `@page` side margins got a bar
  that overhung or fell short of the page edges and misaligned bar content.
- **Theme-level justify no longer fissures PDF table cells.** The
  justify-in-cells guard covered the `body_text_align` config key but not a
  theme's `body { text-align: justify }` — PDF cells still inherited justify
  while Word pinned them left. Both formats now agree for both sources.
- **Word now reads `@page` margins declared after nested margin boxes.**
  WeasyPrint themes nest `@top-*`/`@bottom-*` boxes inside `@page`; a
  `margin`/`size` declared *after* a nested box was silently dropped by the
  Word geometry parser (it truncated at the first inner brace) and Word fell
  back to the default 25/20/22/25mm margins while the PDF honoured the theme.
- **Word header/footer containers no longer inherit body typography.** The
  header/footer paragraphs picked up the theme's body line-height and
  paragraph spacing from the Normal style — a 1.6 line height + 10pt
  space-after turned a 6pt footer line into a ~30pt-tall container. Both are
  pinned to single spacing with zero before/after.
- **`<!-- col-widths -->` comments now work in PDF output.** The per-table
  column-width comment was honoured by the Word builders only; the PDF now
  applies it to the next table with the same precedence as Word (comment >
  `table_col_widths` config > untouched). The config key is also applied
  per table with a column-count check — previously its CSS hit every table
  regardless of shape, crushing the extra columns of a wider table.
  `md-doc lint` warns when a comment's width count doesn't match the next
  table's column count (both were silently ignored before).
- **Page-level justify no longer reaches into table cells.** With
  `body_text_align: justify` (or a theme's `body { text-align: justify }`),
  wrapped cell text in narrow columns stretched into rivers of whitespace.
  Table cells now default to left in both PDF and Word when the page-level
  alignment is justify; a column's own markdown alignment (`:--:` / `--:`),
  a `<div style="text-align: …">` wrapper, and left/center/right
  `body_text_align` values still cascade into cells as before.
- **Word footers/headers no longer inherit justified body text.** A theme
  with `body { text-align: justify }` sets Word's *Normal* style to justify,
  and the footer/header paragraphs (positioned by left/centre/right tab
  stops) inherited it — Word stretched the slots across the page width
  instead of centring the middle slot. Both paragraphs are now explicitly
  left-aligned. Multiline footer slots also re-tab after each soft line
  break, so the second line of a centred/right slot stays under the first
  instead of falling back to the left margin.
- **Adjacent tables no longer merge in Word.** OOXML treats consecutive
  `w:tbl` elements as a single table, so two tables authored with a blank
  line between them (e.g. an endorsement table followed by a sign/date table
  from a separate `{% include %}`) fused into one block in docx/dotx output.
  The builder now inserts a tiny spacer paragraph (2pt mark + 8pt after,
  mirroring the PDF's `table + table` 10pt gap) between consecutive tables.
- **Header-bar logos scale with the bar.** Page-header-bar logos were
  hard-capped at 8mm in both formats, looking lost inside taller brand bands.
  The default cap is now 70% of the bar height in PDF and Word alike;
  `header_logo_height` still forces an exact size.
- **PDF header-bar text no longer disappears, and the logo honours its
  position.** WeasyPrint 68.x drops flex children inside `position: fixed`
  boxes — `header_text` in a `page_header_bar` vanished and the logo ignored
  `page_header_bar_logo_position`, landing centred. The bar now lays out with
  table-cell slots (the same 35/30/35 grid as the Word header table).
- **Upgrading md-doc now invalidates existing outputs.** The incremental
  build's freshness check covered the document's inputs (source, `_meta.yml`
  cascade, theme, templates) but not the pipeline itself — so after an
  upgrade, `md-doc build` kept reporting "up to date" and fixes never reached
  the documents without `--force`. The installed package's newest mtime is now
  a build input. The Neovim plugin's *build workspace* (`<leader>mB`) also
  passes `--force` — an explicit workspace build always regenerates everything.
- **Header logos now render at the same size in PDF and Word.** The PDF drew
  margin-box logos at raw pixel size (a high-resolution logo blew out the page
  header) while Word forced every logo to 6mm — too small and inconsistent
  across contexts. Shared rule everywhere now: natural size capped at **8mm**
  tall, never upscaled; the new **`header_logo_height`** key forces an exact
  height in both formats (PDF via computed `image-resolution`, Word via
  matching picture extents). Bar and cover-bar logos follow the same
  no-upscale rule.
- **Tables from adjacent `{% include %}` templates no longer merge into one.**
  The renderer's `trim_blocks` joins fragments tightly, so two templates each
  containing a table butted together with no blank line — and markdown parsed
  the run as ONE table. The renderer now detects a second header-separator row
  inside a contiguous table run (unambiguous — a real table has exactly one)
  and re-inserts the blank line, fixing all output formats.
- **Two adjacent tables no longer render merged into one grid.** With a theme
  that sets no `table { margin }`, consecutive tables rendered flush and looked
  like a single table. A theme-independent separation rule now guarantees a gap
  (margins collapse, so themed spacing isn't doubled). `md-doc lint` also warns
  when two tables are jammed together with **no blank line** between them —
  markdown genuinely merges those into one table.
- **A `_theme.css` at the repo root now applies to documents at the root.**
  The theme resolver's directory walk excluded the repo root itself, so a
  hand-written root theme was skipped and a default `_pdf-theme.css` was
  auto-generated next to it — silently shadowing the brand theme from then on.
- **The first body H1 no longer forces a page break** (PDF + Word). With a
  letterhead include before the H1, the theme's `h1 { page-break-before:
  always }` used to strand the letterhead alone on a near-blank page 1 —
  common in forms and letters. Later H1s still start new pages.
- **`css_vars` config key (PDF)** — inject CSS custom properties on `:root` so a
  theme can keep its styling in CSS while the *asset* (or any value) is
  overridden per-document from YAML. A value ending in an image extension is
  resolved through the asset cascade and wrapped as `url("file://…")`; other
  values are injected literally. Lets you swap, e.g., a cover-bar watermark
  (`.cover-bar-bottom::after { background: var(--cover-watermark) … }`) per
  document with `css_vars: {cover-watermark: assets/logo.png}`.

### Fixed
- **Boolean config keys now accept string / templated values.** A quoted YAML
  value (`cover_page: "false"`) or one rendered from a Jinja variable
  (`cover_page: "{{ want_cover }}"`) arrives as a *string*, and Python's
  `bool("false")` is `True` — so the cover (or any boolean-gated feature) turned
  on when it should have been off, and `md-doc lint` errored with
  "must be true or false, got str". Booleans are now coerced correctly
  (`true/false/yes/no/on/off/1/0`, case-insensitive) after Jinja rendering, the
  linter accepts bool-like and still-templated values, and only a genuinely
  non-boolean string (e.g. `maybe`) is flagged. Applies to every boolean key
  (`cover_page`, `pdf_forms`, `section_bar`, `page_header_bar`, `cover_*`, …).

### Changed
- **`cover_page` now defaults to `false`.** Previously a cover page was added
  unless you set `cover_page: false`; now the document starts with your content
  unless you opt in with `cover_page: true` (in the document's frontmatter or a
  parent `_meta.yml`). **Migration:** add `cover_page: true` at the folder or
  document level wherever you want the branded cover — the example projects do
  this at their `_meta.yml` root. Applies to PDF and DOCX/DOTX; `pptx` is
  unaffected.

### Fixed
- **Single-file builds no longer abort on an unrelated file's lint error.**
  Building one document (e.g. the Neovim plugin's *build this file*) ran the
  lint pre-flight over the document's whole parent directory, so a lint error
  in a *sibling* (a WIP draft, a broken template) aborted the build and the
  file you asked for never built — while a whole-directory "workspace" build of
  a clean subtree worked. A single-file build now lints only that file; its own
  lint errors still abort as before.
- **Single-file builds in non-git projects now resolve the full config
  cascade.** `_find_repo_root` recognised only `.git` / `pyproject.toml`; in a
  project rooted by `_meta.yml` alone, building a single file (e.g. from the
  Neovim plugin's *build this file*) fell back to the document's own directory
  and silently dropped every parent `_meta.yml` — so `author`/theme/`outputs`
  went missing and `_pdf-theme.css` was written next to the doc instead of at
  the project root. It now falls back to the **topmost `_meta.yml`**, matching
  what a whole-directory build resolves.

### Added
- **Deck-first slide authoring schema** for `pptx` output. New layout
  directives extend the existing marker style: `<!-- slide: section -->`
  (forced divider), `<!-- slide: columns -->` with `<!-- col -->` dividers
  (2–4 columns of text/bullets/code/tables/images), `<!-- slide: stat -->`
  (big-number tiles from bullets — the bold text is the number),
  `<!-- slide: quote -->` (centred pull-quote with `— Name` attribution),
  `<!-- slide: image -->` (pictures/Mermaid fill the body, text becomes the
  caption), and `<!-- slide: center -->` (vertically centred statement).
  `background=#hex` on any directive gives the slide a solid fill, and dark
  fills flip the text to white automatically. A directive starts a new slide
  and the next heading titles it; unknown layout names degrade to the default
  content layout with a warning. Overlong slides now **shrink text to fit**
  instead of spilling off the canvas. New guide: `docs/slides-guide.md`;
  worked example: `examples/blueshift/decks/quarterly-review.md`.

### Fixed
- **Word content-fidelity gaps found by the full parity review.**
  - *Loose lists* (blank lines between items) no longer lose their bullets in
    docx — the first paragraph of a list item reuses the bullet paragraph, and
    later paragraphs render as indented continuations.
  - *Footnotes and internal/TOC links* now work in Word: `#anchor` hyperlinks
    become real bookmark jumps (headings, footnote definitions and references
    are bookmarked) with no literal `(#fn:1)` suffix, and footnote markers
    render superscript.
  - *`<sup>`/`<sub>`/`<del>`* render as superscript/subscript/strikethrough
    runs in docx instead of plain text.
  - *Markdown column alignment* (`:--:` / `--:`) is honoured in docx table
    cells, and hyperlinks inside cells are clickable instead of losing their
    URL.
  - *Tables and code blocks stay on one page* in Word (`cantSplit` rows,
    `keepLines` code paragraphs), matching the PDF theme's
    `page-break-inside: avoid`.
- **Config keys that only one format honoured.**
  - `--theme` / `pdf_theme` now restyles Word and PowerPoint typography too
    (previously only the PDF and Word's page geometry), so one override drives
    all formats.
  - `body_text_align` now applies to the PDF (previously Word-only).
  - `cover_text_align` and `cover_footer_line: false` now work in the PDF
    (the cover classes previously had no CSS behind them); `center` is now a
    supported cover alignment in both formats.
  - `page_header_bar_logo` now beats `header_logo` inside the page header bar
    in both formats (PDF previously preferred `header_logo`, Word the
    opposite).
  - `cover_background` is documented as PDF-only (Word has no per-page fill).

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
