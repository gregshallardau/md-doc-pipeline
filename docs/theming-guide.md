# Theming guide

How md-doc looks is controlled by plain CSS files that cascade down your folder tree, plus a
small set of config keys. This guide covers the theme files, how they are found, brand custom
properties, what Word reads from them, and how forms are styled. For the config keys themselves
see the [config reference](config-reference.md).

## Theme files

| File | Used by | Purpose |
|------|---------|---------|
| `_pdf-theme.css` | PDF | The PDF theme. `md-doc theme init` writes a complete one. |
| `_theme.css` | PDF and Word | Optional shared base. A typical project keeps the brand here and makes `_pdf-theme.css` start with `@import '_theme.css';`. |
| `_docx-theme.css` | Word (docx, dotx, pptx colours and fonts) | Optional Word-only overrides. Only create it where Word must differ. |

Commit these files; they are configuration, not build output.

### How a theme is found

For each document the pipeline looks at every folder from the document up to the repo root. The
deepest folder that has a match wins.

- **PDF:** `_pdf-theme.css`, then `_theme.css`.
- **Word:** `_docx-theme.css`, then `_theme.css`, then `_pdf-theme.css`.
- A `pdf_theme: path/to/file.css` config key, or the `--theme` command-line flag, overrides the
  search for **all** formats (a path relative to the repo root, or absolute; `..` is refused).
- If no theme exists anywhere, `_pdf-theme.css` is generated at the repo root on the first
  build (it is git-ignored there).

`@import 'file.css';` is followed in every theme file (relative to the importing file), with
the importing file's rules winning. This is how a sub-folder inherits a parent theme.

### Creating themes

```bash
md-doc theme init workspace/acme/                       # full brand theme (interactive)
md-doc theme override workspace/acme/products/pulse/    # colour-only override of the nearest parent
```

`init` asks for organisation name, primary, accent, body-text and muted colours, body and
monospace fonts, page size and whether covers are on by default. `override` writes a small file
that `@import`s the parent and changes colours only.

## Brand defaults in CSS: `--mddoc-*`

The pure *look* values of covers, header bars and section bars can live in the theme as CSS
custom properties on `:root`. They become defaults for the matching config keys; **any YAML key
at any level still wins**. Feature switches (`page_header_bar`, `cover_page`, `section_bar`) and
content (texts, logo files) stay in YAML.

```css
:root {
  --mddoc-header-bar-color: #002a5b;        /* page_header_bar_color */
  --mddoc-header-bar-text-color: #ffffff;   /* page_header_bar_text_color */
  --mddoc-header-bar-height: 24mm;          /* page_header_bar_height */
  --mddoc-header-bar-padding: 8mm;          /* page_header_bar_padding */
  --mddoc-header-logo-height: 10mm;         /* header_logo_height */
  --mddoc-cover-bar-height: 132mm;          /* cover_bar_height */
  --mddoc-cover-bar-top-height: 20mm;       /* cover_bar_top_height */
  --mddoc-cover-bar-bottom-height: 132mm;   /* cover_bar_bottom_height */
  --mddoc-cover-stripe-height: 120mm;       /* cover_stripe_height */
  --mddoc-cover-stripe-width: 6mm;          /* cover_stripe_width */
  --mddoc-cover-footer-color: "#ffffff";    /* cover_footer_color */
  --mddoc-section-bar-color: #2563eb;       /* section_bar_color */
  --mddoc-section-bar-text-color: #ffffff;  /* section_bar_text_color */
}
```

They are read from whichever theme file the builder resolves (PDF and Word each use their own
order above), so put them in the shared `_theme.css` unless the formats should differ.

## Per-document assets and values: `css_vars`

`css_vars` (PDF only) injects `:root { --name: value }` per document, so one theme can serve
documents that differ in an image or colour:

```css
/* theme */
.cover-bar-bottom::after { background: var(--cover-watermark) no-repeat center; }
```

```yaml
# frontmatter or any _meta.yml
css_vars:
  cover-watermark: assets/client-logo.png   # an image path: resolved doc folder, ancestors, repo root
  accent: "#e67e22"                          # anything else is inserted as written
```

A value ending in `.png`, `.jpg`, `.jpeg`, `.svg`, `.webp` or `.gif` is resolved through the
asset cascade and becomes `url("file://…")`.

## What the theme colours also drive

- **Mermaid diagrams** take their colours from the theme as hex literals: primary from
  `.cover-title { color }`, else `h1 { color }`, else `th { background }`; accent from `h2`,
  `a` or `.cover-label`; muted from `h3` or `em`; text from `body`.
- **PDF form grids** use the same primary colour (see [Forms](#forms)).

`var(--x)`, `rgb()` and named colours are not read for these. Use hex literals.

## Page setup

An `@page` rule sets paper size and margins for PDF **and** Word. Footer boxes
(`@bottom-left`, `@bottom-center`, `@bottom-right`) with `content: "…"`, `counter(page)`,
`counter(pages)` or `string(running-date)` are mirrored into the Word footer with live page
fields. `footer_left`, `footer_center` and `footer_right` config keys override those boxes
(and an empty string hides one).

Word-only header and footer distances go in the same `@page` block as custom properties, which
WeasyPrint ignores:

```css
@page {
  margin: 24mm 20mm 20mm 25mm;
  --docx-header-distance: 8mm;   /* header text 8mm from the top edge */
  --docx-footer-distance: 6mm;   /* footer 6mm from the bottom edge */
}
```

Header and footer paragraphs never inherit the body line-height or paragraph spacing.

## What Word reads

Word output is built with python-docx, not a browser, so it reads a defined subset of the CSS:

- **Absolute lengths only.** `pt`, `px`, `mm`, `cm` and `in` are converted. `em`, `rem`, `%`
  and `calc()` are ignored in the rules below and Word falls back to its defaults. Unitless
  `line-height` is fine.
- **Simple selectors.** `body`, `h1`–`h4`, `a`, `strong`, `em`, `code`, `pre`, `blockquote`
  (and `blockquote p`), `hr`, `li` (also `ul li`, `ol li`), `table`, `th`, `td`,
  `tr:nth-child(even) td`, `tr:last-child td`, `label`, text inputs, `textarea`, `select`,
  single-class `display: flex` rows, and `@page`. Descendant chains such as `.report-body td`
  are PDF-only.
- **Properties:** fonts and sizes, heading colours and sizes, table header colours,
  cell padding and borders, zebra and last-row rules, code and `pre` box model, blockquote
  border and background, `hr` margins, list spacing (`li { margin; line-height }`), body
  `line-height`, and the form-input box (below).

Cell and list spacing example, applied to both formats:

```css
li { margin: 0 0 2pt 0; line-height: 1.2; }
td { padding: 5pt 9pt; }
```

`body_text_align: justify` (config) justifies Word body text; wrap a section in
`<div style="text-align: left">…</div>` to override it for that section. PDF uses native CSS.

### PDF to Word parity

Both builders insert the same page breaks (`<!-- pagebreak -->`, APPENDIX sections and the
theme's `h1 { page-break-before: always }`), the same cover geometry, header bars, section bars
and footers, and a spacer between adjacent tables. Exact line-for-line pagination is not
guaranteed because WeasyPrint and Word lay text out differently. The
[sample parity audit](sample-parity-audit.md) lists the known differences.

## Forms

For documents with `pdf_forms: true` the PDF builder adds form CSS **after** your theme. It is
sized in `em`, so it follows your font size, and tinted from your primary colour:

- `?[box]` grids: outer rule 45 % toward white from the primary, inner rules 70 %, uppercase
  primary-coloured labels, cell padding from your `td` rule.
- Checkboxes and radios `1.1em`, centred on the label's cap height; `.form-group` inputs and
  selects `2em`; signature field `2.6em` with a ruled caption.
- Ordinary Markdown tables keep your normal table styling.

What you control in your theme: the layout classes of raw HTML forms (`.form-section`,
`.form-row`, `.form-group`, `.form-group label`), and the appearance of text inputs, selects and
textareas (border, background, padding, `font-size`, `margin`, `border-radius`). Word reads the
text-input rule (first of `input[type="text"]`, `input[type="email"]`, `input[type="date"]`,
`textarea`, `select`) to size its field boxes, so use absolute units there. Include `tel` and
`url` in the selector list if you use them.

Because the built-in form CSS loads after the theme, an equal-specificity theme rule loses; use
a more specific selector or `!important` to override it. Form documents hide `.running-date`.

To modernise an older theme with an AI agent, use `prompts/upgrade-css.md`.

## Quick recipes

- **Different colour for one product:** `md-doc theme override workspace/acme/products/pulse/`.
- **Tight bullets everywhere:** `li { margin: 0 0 2pt 0; line-height: 1.2; }` in `_theme.css`.
- **Word needs a different font:** put `body { font-family: …; }` in `_docx-theme.css` only.
- **Brand bar colours once:** set `--mddoc-header-bar-color` and friends in `_theme.css`.
- **One-off look:** `md-doc build doc/ --theme path/to/_pdf-theme.css`.
