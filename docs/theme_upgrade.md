# Upgrade an existing theme

Use this procedure only when theme maintenance is requested. Preserve existing brand values
and compare builds before and after. The commands use `workspace/acme/` as an example;
substitute the actual project path.

## Hard rules

1. **Brand values are untouched.** Never change a colour, font family, font size, page size or
   margin value. Move or restructure them; do not "improve" them. Never invent a colour.
2. **Only edit** `_theme.css`, `_pdf-theme.css`, `_docx-theme.css`, `_meta.yml` (visual keys only)
   and theme assets inside `workspace/acme/`. Never edit document `.md` bodies, `md_doc/`,
   `tests/` or `pyproject.toml`.
3. Keep changes reviewable. Create a branch or commits when requested; do not push or
   open a pull request without instruction.
4. If two rules conflict or a change would alter appearance, **stop and ask** rather than guess.
5. Keep comments that explain brand decisions. Delete only rules you can prove are dead.

## Step 0 — Recon

1. List every theme file under the project and the resolution order each builder uses:
   - PDF: at each folder from the document up to the repo root, `_pdf-theme.css` then `_theme.css`.
   - Word (docx/dotx): `_docx-theme.css`, then `_theme.css`, then `_pdf-theme.css`.
   - `@import` chains inside any of these are followed.
2. List every `_meta.yml` / frontmatter key that is purely visual: `cover_*`, `header_*`,
   `footer_*`, `page_header_bar*`, `section_bar*`, `css_vars`, `pdf_theme`, `body_text_align`.
3. Note which documents set `pdf_forms: true`, which use covers, header bars or `section_bar`.
4. Run `uv run md-doc doctor` and `uv run md-doc lint workspace/acme/`. Record the output.

## Step 1 — Baseline (do not skip)

```bash
uv run md-doc build workspace/acme/ --force -o /tmp/css-before
```

Keep `/tmp/css-before`. Render a PNG of every PDF page (for example with `pypdfium2`) so you
can compare later. If LibreOffice is installed, also convert each `.docx` to PDF with
`soffice --headless --convert-to pdf` for a Word comparison.

## Step 2 — Upgrade checklist

Work through these in order. For each item: detect, fix, rebuild that file and confirm the
intended appearance is preserved.

### 2.1 Structure: one shared base, thin format files

- Shared look (colours, fonts, headings, tables, code, form field styling) belongs in
  `_theme.css`.
- `_pdf-theme.css` should be `@import '_theme.css';` plus only PDF-specific rules (cover, header
  and footer boxes, `@page` margin boxes).
- Create `_docx-theme.css` **only** if Word must genuinely differ; otherwise delete duplicated
  rules instead of copying them.
- Remove rules that are identical in more than one file.

### 2.2 Brand look values → `--mddoc-*` custom properties

These pure look values can live in the theme at the global level; any YAML key still wins:

```css
:root {
  --mddoc-header-bar-color: #002a5b;       /* page_header_bar_color */
  --mddoc-header-bar-text-color: #ffffff;  /* page_header_bar_text_color */
  --mddoc-header-bar-height: 24mm;         /* page_header_bar_height */
  --mddoc-header-bar-padding: 8mm;         /* page_header_bar_padding */
  --mddoc-header-logo-height: 10mm;        /* header_logo_height */
  --mddoc-cover-bar-height: 132mm;         /* cover_bar_height (+ -top-/-bottom-) */
  --mddoc-cover-stripe-height: 120mm;      /* cover_stripe_height (+ -width) */
  --mddoc-cover-footer-color: "#ffffff";   /* cover_footer_color */
  --mddoc-section-bar-color: #2563eb;      /* section_bar_color (+ -text-color) */
}
```

If the same look key is repeated unchanged in many `_meta.yml` files, move the value into
`:root` and delete the repeats. Feature toggles (`page_header_bar`, `cover_page`, `section_bar`)
and content (texts, logo file choices) stay in YAML. Put these in `_theme.css` unless the
formats should differ.

### 2.3 Units: Word only reads absolute lengths

The Word builder converts `pt`, `px`, `mm`, `cm` and `in`. `em`, `rem`, `%` and `calc()` are
**ignored** for the properties Word consumes, and Word silently falls back to defaults. In rules
Word reads, convert relative units to the absolute equivalent at the rule's own font size:

`body`/`h1`–`h4`/`code` `font-size`; `table`/`th`/`td` `font-size` and `padding`; `li` `margin`;
`pre` and `blockquote` `margin`/`padding`/`border`; `hr` `margin`; `label` `font-size` and
`margin-bottom`; text-input `padding`, `border`, `margin`, `font-size`; `textarea{min-height}`;
`.class{display:flex; gap}`; the `@page` block.

Unitless `line-height` is fine. Relative units are fine in PDF-only rules Word never reads.

### 2.4 Selectors Word can read

Word reads **simple selectors**: `body`, `h1`–`h4`, `table`, `th`, `td`, `tr:nth-child(even) td`,
`tr:last-child td`, `code`, `pre`, `blockquote`, `hr`, `li`, `label`, single-class flex rows
(`.form-row { display: flex; gap: …; flex-wrap: … }`), `@page`, and for form inputs the first of
`input[type="text"]`, `input[type="email"]`, `input[type="date"]`, `textarea`, `select` that
exists. Descendant chains such as `.report-body table td` or `main > h1` are PDF-only; if a Word
value matters, state it with a simple selector in the shared `_theme.css`.

### 2.5 Primary colour must be discoverable

Mermaid diagrams and PDF form grids take their primary colour from the theme using a hex literal
only (`#rgb`, `#rrggbb` or `#rrggbbaa`), looked up in this order: `.cover-title { color }`,
`h1 { color }`, `th { background }`. A `var(--brand)`, `rgb()` or named colour is not found and
the form grids fall back to neutral slate. Make sure one of those rules holds the brand colour as
a hex literal. Accent comes from `h2`/`a`/`.cover-label` colour, muted from `h3`/`em`.

### 2.6 Forms (`pdf_forms: true` documents)

For these documents md-doc now injects form CSS **after** the theme, so theme rules that fight it
produce inconsistent output. It sets: tinted `?[box]` grids (outer rule 45 % toward white from the
primary, inner rules 70 %), uppercase primary-coloured grid labels, em-based control sizes
(checkbox/radio `1.1em`, `.form-group` inputs and selects `2em`, signature field `2.6em`), option
and Yes/No spacing, signature rule and caption, and report styling for ordinary tables.

- **Delete** theme rules that only re-create that: black table-grid overrides for forms,
  `.field-box`, `.field-row`, `.signature-*`, `.option-item`, `.yesno`, fixed-size checkbox
  rules (`width: 4mm` and similar), fixed point heights on `.form-group input`/`select`.
- **Keep** the project's own form layout and typography: `.form-section`, `.form-row`,
  `.form-group`, `.form-group label`, and the text-input appearance rule (border, background,
  padding, `font-size`, `margin`, `border-radius`). Word reads that input rule to size its field
  boxes, so use absolute units and make sure the selector list covers
  `text, email, tel, url, date, number`, plus `select` and `textarea { min-height }`.
- If the project must override the injected CSS, use a more specific selector or `!important`;
  an equal-specificity theme rule will lose because it loads first.
- Remove nothing that carries a brand decision (colour, radius, label case/tracking).

### 2.7 Page furniture

- Footers: the PDF `@page { @bottom-left|center|right { content: … } }` boxes are mirrored into
  Word, including `counter(page)`, `counter(pages)` and `string(running-date)`. Keep them in the
  shared theme with absolute font sizes. Form documents intentionally hide `.running-date`.
- Optional Word header/footer distance: `--docx-header-distance` / `--docx-footer-distance` inside
  `@page`, in `_docx-theme.css` or the shared theme.
- Per-document assets: replace hard-coded `url()` logos that vary per document with
  `css_vars` plus `var(--name)` (image values resolve through the doc → ancestors → repo-root
  cascade).

### 2.8 Dead and legacy

Remove rules for selectors that no document or generated element uses (verify with a search of
the built HTML or the document sources before deleting). Do **not** remove `.cover-*`,
`.report-body`, `.md-doc-*` or `.running-date`; the builders emit them.

## Step 3 — Verify

```bash
uv run md-doc lint workspace/acme/
uv run md-doc build workspace/acme/ --force -o /tmp/css-after
```

Compare against `/tmp/css-before`:

- Every PDF has the same page count. Where it does not, explain why (usually a form-grid or
  keep-with-next change) and show the page.
- Page images match within normal anti-aliasing for documents that do not use forms. For form
  documents, differences are expected only where 2.6 describes them; review each one visually.
- Brand values (colours, fonts, sizes, page geometry) are byte-identical in meaning before and
  after. Diff the declarations, not just the files.
- Word output: no `____` stand-ins in grid cells, no black table borders in forms, footer
  present, page count within one page of before.

If anything differs and you cannot explain it, revert that step and report it.

## Step 4 — Report

Finish with a short report:

1. A table of every change: file, rule, reason, and the checklist item (2.1–2.8) it came from.
2. Before/after page counts per document.
3. Anything you left alone on purpose, and anything that needs a human decision.
4. Files changed and validation performed; include branch/commit details if applicable.
