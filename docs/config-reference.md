# Configuration Reference

Complete reference for all configuration keys available in `_meta.yml` files and document YAML frontmatter.

Configuration cascades: repo root → parent folders → document frontmatter. Deeper values override shallower ones. You only need to set what's new or different at each level.

---

## General

```yaml
title: Q1 Strategy Report
author: Jane Smith
date: April 2026
outputs: [pdf]
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `title` | string | First H1 in document | Document title. Used on cover page and in metadata. |
| `author` | string | `"Document Producer"` | Author name. Shown on cover page and page footer. |
| `date` | string | Today's date | Date string for cover page (free-form, e.g. `"April 2026"`). |
| `outputs` | list | `[pdf]` | Output formats to generate. Values: `pdf`, `docx`, `dotx`, `pptx`. |
| `output_filename` | string | `<source name>` | Override the output file name for every format. Jinja2 variables are allowed (`"{{ product }}-proposal"`); the extension is added automatically. |
| `output_dir` | string | *(alongside source)* | Directory to write built outputs into. Set at any `_meta.yml` level — cascades down, overridden by deeper levels or document frontmatter. CLI `--output` always takes precedence. Supports `~` expansion. |
| `pdf_theme` | string | Auto-resolved | Path to a custom theme file (absolute or relative to repo root). Point to `_theme.css` (shared base, used for all formats) or `_pdf-theme.css` (PDF-specific overrides that `@import '_theme.css'`). For Word output, place a `_docx-theme.css` alongside `_pdf-theme.css` — the builder picks it up automatically. |
| `css_vars` | mapping | *(none)* | PDF only. Inject CSS custom properties on `:root` so a theme can keep its styling in CSS while the asset/value is overridden per-document. A value ending in an image extension is resolved via the asset cascade and wrapped as `url("file://…")`; other values are injected literally. E.g. theme has `background: var(--cover-watermark)`, document sets `css_vars: {cover-watermark: assets/logo.png}`. |
| `pdf_forms` | boolean | `false` | Enable interactive form fields in PDF output. Output gets a `-form` suffix. |
| `dotx_field_type` | string | `"form"` | `.dotx` field type: `"form"` (Word Text Form Fields, directly fillable in Word) or `"merge"` (classic MERGEFIELDs, require a mail merge data source). |
| `slide_split` | string | `"h2"` | Slide boundaries for `pptx` output: `"h2"` (each H2 → a slide), `"h1"` (only H1s), or `"marker"` (only `<!-- slide -->`). |
| `slide_size` | string | `"16:9"` | Slide aspect for `pptx`: `"16:9"` or `"4:3"`. Quote it so YAML doesn't read `16:9` as a number. |
| `pptx_template` | string | *(built-in)* | Path to a `.pptx`/`.potx` used as the base for `pptx` output (brand master slides/layouts). Resolved doc dir → ancestors → repo root. |

**Slides (`pptx`):** the first `# H1` (or `title`) becomes a title slide, later `# H1`s become section slides, and each `## H2` a content slide. Use `<!-- slide -->` to force a break and `<!-- notes: … -->` to add speaker notes. Mermaid diagrams embed as images (needs the `[mermaid]` extra / `cairosvg`).

**Slide layout directives:** `<!-- slide: LAYOUT [background=#hex] -->` starts a new slide with a layout; the next heading titles it. Layouts: `section` (forced divider), `columns` (side-by-side body, divided by `<!-- col -->`), `stat` (big-number tiles from bullets — bold text is the number), `quote` (centred pull-quote, `— Name` paragraph = attribution), `image` (pictures fill the body, text becomes the caption), `center` (vertically centred). `background=#hex` gives any slide a solid fill; dark fills flip text to white. See `docs/slides-guide.md`.

---

## Cover Page

### Turning the cover on/off

```yaml
cover_page: true
```

> **What it does:** When `true`, a full-bleed cover page is generated as page 1 of the PDF. The first `# H1` heading in your Markdown becomes the cover title and is removed from the body. The default is `false` — the document starts directly with your content; add `cover_page: true` (in the document's frontmatter or a parent `_meta.yml`) to opt into a cover.

### Cover label

```yaml
cover_label: Concept
```

> **What it does:** Renders small uppercase text above the title on the cover page. Appears in the theme's accent colour (or white when `cover_text_on_bar` is active). Use it to categorise the document — `"Report"`, `"Proposal"`, `"Draft"`, `"Concept"`, `"Strategy"`.
>
> **Default:** `"Report"`

### Text alignment

```yaml
cover_text_align: center
```

> **What it does:** Controls the horizontal alignment of all text on the cover — the label, title, divider, author/date metadata, and footer. The divider line and logo also reposition to match.
>
> **Values:** `left` (default), `center`, `right`
>
> **Visual:**
> - `left` — text starts from the left margin, divider line anchored left
> - `center` — everything centered on the page, divider centered
> - `right` — text right-aligned, divider anchored right

### Background colour

```yaml
cover_background: "#2563eb"
```

> **What it does:** Sets a full-bleed background colour on the entire cover page. When set to a dark colour, the title, label, metadata, and divider automatically appear in white (via the theme's `.cover-text-on-bar` styles if `cover_text_on_bar` is also set, or via custom CSS for the background variant).
>
> **Default:** `"white"`
>
> **Visual:** The entire A4 page fills with the specified colour. All text elements sit on top of it.

### Divider

```yaml
cover_divider: true
```

> **What it does:** Renders a short horizontal rule (3pt, theme accent colour) between the title and the author/date metadata. Helps visually separate the title block from the details.
>
> **Default:** `true`
>
> **Visual:** A 40mm-wide coloured line below the title. When centered, it's centered too. When text-on-bar is active, the line becomes semi-transparent white.

### Cover logo

```yaml
cover_logo: assets/company-logo.png
```

> **What it does:** Places a logo image above the label on the cover page. The image is sized to max 50mm wide × 20mm tall. When centered, it's centered. When right-aligned, it's right-aligned.
>
> **Path resolution:** The pipeline searches for the file starting from the document's directory, then each parent directory up to the repo root. So `assets/logo.png` placed in the project root works for all documents.

---

## Cover Bar

A coloured horizontal band at the top and/or bottom of the cover page. The bar uses the theme's primary colour (`#2563eb` by default).

### Basic bar

```yaml
cover_bar: true
cover_bar_position: top
cover_bar_height: 10mm
```

> **What it does:** Renders a solid-colour horizontal band across the full width of the page. At `10mm` height (default), it's a thin accent stripe at the top.
>
> **Visual:** A blue rectangle spanning the full 210mm page width, 10mm tall, at the very top of the cover.

### Top and bottom bars

```yaml
cover_bar: true
cover_bar_position: both
cover_bar_top_height: 130mm
cover_bar_bottom_height: 20mm
```

> **What it does:** Renders two independent bars — one at the top, one at the bottom. Each has its own height. The top bar height defines how much of the page is covered in colour from the top down. The bottom bar sits flush against the page bottom.
>
> **Visual:**
> ```
> ┌──────────────────────────┐
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← top bar (130mm of blue)
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │                          │ ← white gap
> │                          │
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← bottom bar (20mm of blue)
> └──────────────────────────┘
> ```

### Bottom bar only

```yaml
cover_bar: true
cover_bar_position: bottom
cover_bar_height: 8mm
```

> **What it does:** A thin accent bar at the very bottom of the page. Good for a subtle branded touch without a heavy visual at the top.

### Text on bar

```yaml
cover_bar: true
cover_bar_position: both
cover_bar_top_height: 130mm
cover_text_on_bar: true
```

> **What it does:** Instead of the bar being a separate band above the content, the top bar becomes a blue background wrapper around the title content. The label, title, divider, and metadata all render in white on top of the blue band.
>
> **Visual:**
> ```
> ┌──────────────────────────┐
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓▓▓▓  CONCEPT  ▓▓▓▓▓▓▓▓▓│ ← white label on blue
> │▓▓  Document Title  ▓▓▓▓▓│ ← white title on blue
> │▓▓▓▓▓  ─────────  ▓▓▓▓▓▓▓│ ← semi-transparent divider
> │▓▓▓  Author · Date  ▓▓▓▓▓│ ← white metadata on blue
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │                          │
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← bottom bar
> └──────────────────────────┘
> ```
>
> **Requires:** `cover_bar: true` and `cover_bar_position` set to `top` or `both`.

| Key | Type | Default |
|-----|------|---------|
| `cover_bar` | boolean | `true` |
| `cover_bar_position` | string | `"top"` — values: `top`, `bottom`, `both` |
| `cover_bar_height` | string | `"10mm"` — default for both bars |
| `cover_bar_top_height` | string | Falls back to `cover_bar_height` |
| `cover_bar_bottom_height` | string | Falls back to `cover_bar_height` |
| `cover_text_on_bar` | boolean | `false` |

---

## Cover Stripe

A narrow vertical accent stripe on the left edge of the cover page.

```yaml
cover_stripe: true
cover_stripe_height: 120mm
cover_stripe_width: 6mm
```

> **What it does:** Renders a narrow vertical bar in the theme's dark accent colour, starting just below the top bar (or from the top edge if there's no bar). Gives a subtle structural accent without overwhelming the page.
>
> **Visual:**
> ```
> ┌──────────────────────────┐
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← top bar
> │█                         │
> │█  REPORT                 │ ← 6mm-wide dark stripe
> │█  Document Title         │   runs 120mm down the
> │█  ─────────              │   left edge
> │█  Author · Date          │
> │█                         │
> │                          │
> │                          │
> └──────────────────────────┘
> ```

| Key | Type | Default |
|-----|------|---------|
| `cover_stripe` | boolean | `false` |
| `cover_stripe_height` | string | `"120mm"` |
| `cover_stripe_width` | string | `"6mm"` |

---

## Cover Footer

Footer text at the bottom of the cover page.

### Standard footer (above bottom bar)

```yaml
cover_footer: true
cover_footer_text: "Acme Corp  ·  Confidential"
cover_footer_line: true
```

> **What it does:** Renders a line of small text near the bottom of the cover page. By default it shows `"Author  ·  Confidential"`. A thin horizontal line separates it from the content above.
>
> **Visual:**
> ```
> │                          │
> │  ────────────────────    │ ← footer line
> │  Acme Corp · Confidential│ ← 8pt grey text
> └──────────────────────────┘
> ```

### Footer inside bottom bar

```yaml
cover_bar: true
cover_bar_position: both
cover_bar_bottom_height: 20mm
cover_footer: true
cover_footer_line: false
cover_footer_color: "#ffffff"
```

> **What it does:** When a bottom bar exists, the footer text moves inside it and is vertically centered. Set `cover_footer_color` to white so the text is visible on the blue bar. The footer line is typically turned off in this configuration since the bar itself provides visual separation.
>
> **Visual:**
> ```
> │                          │
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓  Acme Corp · Conf  ▓▓▓│ ← white text centered in blue bar
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> └──────────────────────────┘
> ```

| Key | Type | Default |
|-----|------|---------|
| `cover_footer` | boolean | `true` |
| `cover_footer_text` | string | `"<author>  ·  Confidential"` |
| `cover_footer_line` | boolean | `true` |
| `cover_footer_color` | string | `"#7f8c9a"` (grey) |

---

## Section Heading Bars

Coloured background bars on section headings within the document body.

### Text on bar (white text, coloured background)

```yaml
section_bar: true
section_bar_color: "#2563eb"
section_bar_text_on_bar: true
section_bar_text_color: "#ffffff"
```

> **What it does:** Applies a solid coloured background to H1 and H2 headings in the report body, with white text on top. Creates strong visual hierarchy and a professional, branded look.
>
> **Visual:**
> ```
> ┌──────────────────────────┐
> │▓▓ Executive Summary ▓▓▓▓▓│ ← white text on blue bar
> │                          │
> │  Content below heading...│
> ```

### Border-top mode (coloured line above heading)

```yaml
section_bar: true
section_bar_text_on_bar: false
```

> **What it does:** Instead of a full background, renders a 4pt coloured line above each H1/H2 heading. The heading text stays in its normal colour. Subtler than text-on-bar mode.
>
> **Visual:**
> ```
> ┌──────────────────────────┐
> │  ────────────────────    │ ← 4pt blue line
> │  Executive Summary       │ ← normal heading text
> │                          │
> │  Content below heading...│
> ```

### Custom heading levels

```yaml
section_bar: true
section_bar_headings: "h1,h2,h3"
```

> **What it does:** Controls which heading levels get the bar treatment. Default is `"h1,h2"`. Add `h3` for deeper visual structure, or use `"h1"` alone for top-level sections only.

| Key | Type | Default |
|-----|------|---------|
| `section_bar` | boolean | `false` |
| `section_bar_color` | string | `"#2563eb"` |
| `section_bar_text_on_bar` | boolean | `true` |
| `section_bar_text_color` | string | `"#ffffff"` |
| `section_bar_headings` | string | `"h1,h2"` — comma-separated heading tags |

---

## Page Header Bar

A solid coloured bar across the top of every content page (not the cover). Supports text and multiple logos positioned in left/center/right slots. Uses `position: fixed` for reliable full-bleed rendering.

### Basic bar with text

```yaml
page_header_bar: true
page_header_bar_color: "#2563eb"
page_header_bar_text_color: "#ffffff"
page_header_bar_height: "12mm"
header_text: "Acme Corp — Confidential"
header_text_position: left
```

> **What it does:** Renders a full-width coloured bar at the top of every content page. Text and logos from the standard `header_text` / `header_logo` keys are placed inside the bar instead of in the margin boxes.
>
> **Visual:**
> ```
> ┌──────────────────────────┐
> │▓▓ Acme Corp — Conf ▓▓▓▓▓│ ← white text on blue bar
> │                          │
> │  Page content...         │
> ```

### Bar with logos

```yaml
page_header_bar: true
page_header_bar_height: "24mm"
header_text: "Acme Corp"
header_text_position: left
header_logo: assets/logo.png
header_logo_position: right
```

> **What it does:** The standard `header_logo` and `header_text` fields are rendered inside the bar. The bar height should be increased (e.g. `24mm`) to accommodate logos comfortably.

### Multiple logos

```yaml
page_header_bar: true
page_header_bar_height: "24mm"
page_header_bar_logos:
  - path: assets/logo-left.png
    position: left
  - path: assets/logo-center.png
    position: center
  - path: assets/logo-right.png
    position: right
```

> **What it does:** Places up to three logos in left/center/right slots within the bar. Can be combined with `header_text` for text + multi-logo layouts.

### Padding after bar

```yaml
page_header_bar: true
page_header_bar_padding: "8mm"
```

> **What it does:** Controls the gap between the bottom of the header bar and the start of the page content. Default is `6mm`. Increase if content feels too close to the bar.

### Footer line removal

When `page_header_bar` is enabled, the thin grey line above the page footer is automatically removed for a cleaner look. The bar itself provides sufficient visual structure.

| Key | Type | Default |
|-----|------|---------|
| `page_header_bar` | boolean | `false` |
| `page_header_bar_color` | string | `"#2563eb"` |
| `page_header_bar_text_color` | string | `"#ffffff"` |
| `page_header_bar_height` | string | `"12mm"` |
| `page_header_bar_offset` | string | `"0mm"` — distance from the physical page top to the bar; e.g. `"2cm"` places it 20mm down in PDF and Word |
| `page_header_bar_padding` | string | `"6mm"` — gap between bar and content |
| `page_header_bar_logo` | string | — single logo path (falls back to `header_logo`) |
| `page_header_bar_logo_position` | string | `"right"` |
| `page_header_bar_logos` | list | — list of `{path, position}` objects for multi-logo |

---

## Page Headers

Headers appear on every page except the cover. Logo and text can be placed independently in the left, center, or right margin box. When `page_header_bar` is enabled, these values are rendered inside the bar instead of in margin boxes.

### Logo only

```yaml
header_logo: assets/company-logo.png
header_logo_position: right
```

> **What it does:** Places a small logo image in the specified position on every content page. The logo sits in the page margin area above the content, separated by a thin border line (defined in the theme CSS).
>
> **Visual:**
> ```
> ┌──────────────────────────┐
> │                    [LOGO]│ ← right-aligned logo
> │──────────────────────────│ ← border line
> │                          │
> │  Page content...         │
> ```

### Text only

```yaml
header_text: "Acme Corp — Confidential"
header_text_position: left
```

> **What it does:** Places small text (8pt, grey) in the specified position on every content page.
>
> **Visual:**
> ```
> ┌──────────────────────────┐
> │Acme Corp — Confidential  │ ← left-aligned text
> │──────────────────────────│
> │                          │
> │  Page content...         │
> ```

### Logo + text combined

```yaml
header_logo: assets/logo.png
header_logo_position: right
header_text: "Acme Corp — Confidential"
header_text_position: left
```

> **What it does:** Both elements on every page — text on one side, logo on the other.
>
> **Visual:**
> ```
> ┌──────────────────────────┐
> │Acme Corp — Conf    [LOGO]│
> │──────────────────────────│
> │                          │
> │  Page content...         │
> ```

| Key | Type | Default |
|-----|------|---------|
| `header_logo` | string | — (no logo) |
| `header_logo_position` | string | `"right"` — values: `left`, `center`, `right` |
| `header_logo_height` | string | *(intrinsic, ≤8mm)* | Exact header-logo height (e.g. `"10mm"`). Default renders the logo at its natural size capped at 8mm tall (inside a `page_header_bar` the cap is 70% of the bar height instead) — identical rule in PDF and Word, so the logo matches across formats. |
| `header_text` | string | — (no text) |
| `header_text_position` | string | `"left"` — values: `left`, `center`, `right` |

---

## Sync & Registry

```yaml
include_md_in_share: false
sync_target: azure
sync_config:
  connection_string: "${AZURE_CONN_STRING}"
  share_name: documents
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `include_md_in_share` | boolean | `false` | Include source `.md` files when syncing. |
| `sync_target` | string | — | Sync backend. Values: `azure`, `s3`, `local`. |
| `sync_config` | object | — | Backend-specific connection parameters. |

---

## Complete Example

A single document using every available cover option:

```yaml
---
title: Q1 Strategy Report
author: Jane Smith
date: April 2026

# Output
outputs: [pdf]
pdf_theme: assets/custom-theme.css

# Cover page
cover_page: true
cover_label: Strategy
cover_text_align: center
cover_background: white
cover_logo: assets/company-logo.png
cover_divider: true

# Cover bar — solid blue band top half, thin bar at bottom
cover_bar: true
cover_bar_position: both
cover_bar_top_height: 130mm
cover_bar_bottom_height: 20mm
cover_text_on_bar: true

# Cover stripe (off for this layout)
cover_stripe: false

# Cover footer — white text inside the bottom bar
cover_footer: true
cover_footer_text: "Jane Smith  ·  Confidential  ·  Q1 2026"
cover_footer_line: false
cover_footer_color: "#ffffff"

# Page headers — logo right, company name left
header_logo: assets/company-logo.png
header_logo_position: right
header_text: "Acme Corp — Confidential"
header_text_position: left
---

# Q1 Strategy Report

## Executive Summary

Content goes here...
```

> **What this produces:**
> ```
> COVER PAGE                    CONTENT PAGES
> ┌──────────────────────┐     ┌──────────────────────┐
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│     │Acme Corp       [LOGO]│
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│     │─────────────────────│
> │▓▓   STRATEGY   ▓▓▓▓▓│     │                      │
> │▓  Q1 Strategy  ▓▓▓▓▓│     │  Executive Summary   │
> │▓▓    Report    ▓▓▓▓▓│     │                      │
> │▓▓  ──────────  ▓▓▓▓▓│     │  Content goes here...│
> │▓▓  Jane · Apr  ▓▓▓▓▓│     │                      │
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│     │                      │
> │                      │     │─────────────────────│
> │▓▓ Jane · Conf  ▓▓▓▓▓│     │Jane Smith  Page 1│
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│     └──────────────────────┘
> └──────────────────────┘
> ```

---

## Cover Layout Recipes

### Classic (default)

Bar at top, left-aligned text, stripe accent.

```yaml
cover_bar: true
cover_bar_position: top
cover_stripe: true
cover_text_align: left
cover_divider: true
```

> ```
> ┌──────────────────────────┐
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← 10mm blue bar
> │█                         │
> │█  REPORT                 │ ← stripe + left-aligned text
> │█  Document Title         │
> │█  ─────────              │
> │█  Author · Date          │
> │█                         │
> │                          │
> │  ────────────────────    │
> │  Author · Confidential   │
> └──────────────────────────┘
> ```

### Minimal

No bar, no stripe, centered text.

```yaml
cover_bar: false
cover_stripe: false
cover_text_align: center
cover_divider: true
```

> ```
> ┌──────────────────────────┐
> │                          │
> │                          │
> │       REPORT             │
> │    Document Title        │ ← centered, clean
> │      ─────────           │
> │    Author · Date         │
> │                          │
> │                          │
> │    ────────────────      │
> │    Author · Confidential │
> └──────────────────────────┘
> ```

### Branded

Bottom bar, centered text, logo-first.

```yaml
cover_bar: true
cover_bar_position: bottom
cover_bar_height: 8mm
cover_stripe: false
cover_text_align: center
cover_divider: true
cover_logo: assets/logo.png
```

> ```
> ┌──────────────────────────┐
> │                          │
> │        [LOGO]            │
> │       REPORT             │ ← centered, logo above
> │    Document Title        │
> │      ─────────           │
> │    Author · Date         │
> │                          │
> │    ────────────────      │
> │    Author · Confidential │
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← 8mm bottom bar
> └──────────────────────────┘
> ```

### Bold

Full-bleed colour background, white text.

```yaml
cover_bar: false
cover_stripe: false
cover_background: "#2563eb"
cover_text_align: center
cover_divider: true
```

> ```
> ┌──────────────────────────┐
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓▓   REPORT   ▓▓▓▓▓▓▓▓▓│ ← entire page is blue
> │▓▓  Document Title  ▓▓▓▓▓│   all text in white
> │▓▓▓  ──────────  ▓▓▓▓▓▓▓▓│
> │▓▓▓  Author · Date  ▓▓▓▓▓│
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓  Author · Conf  ▓▓▓▓▓▓│
> └──────────────────────────┘
> ```

### Executive (dual bar, text on bar)

Solid blue band with white title text, thick bottom bar with white footer.

```yaml
cover_bar: true
cover_bar_position: both
cover_bar_top_height: 130mm
cover_bar_bottom_height: 20mm
cover_text_on_bar: true
cover_footer: true
cover_footer_line: false
cover_footer_color: "#ffffff"
```

> ```
> ┌──────────────────────────┐
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓▓  CONCEPT  ▓▓▓▓▓▓▓▓▓▓▓│ ← white text on 130mm blue band
> │▓▓  Document Title  ▓▓▓▓▓│
> │▓▓▓  ──────────  ▓▓▓▓▓▓▓▓│
> │▓▓▓  Author · Date  ▓▓▓▓▓│
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │                          │ ← white gap
> │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
> │▓▓  Author · Conf  ▓▓▓▓▓▓│ ← white footer in 20mm blue bar
> └──────────────────────────┘
> ```

### Output path base

Relative `output_dir` values are resolved against the detected project root
(`.git` / `pyproject.toml`, or the topmost `_meta.yml` in a project without Git).
Both `output_dir` and CLI `--output` mirror paths relative to that root, even
when building just one document or a subfolder. For example, `clients/acme/doc.md`
with `output_dir: build` writes `build/clients/acme/doc.pdf` in every build mode.
CLI `--output` still takes precedence; its directory is resolved relative to the
current working directory. With neither setting, outputs stay beside the source.

---

## Key index

Every recognised key in one table. Any other key you add is allowed and becomes a
`{{ variable }}`; `md-doc lint` warns only when a key is a near-miss of one below (a likely typo),
with a "did you mean …?" hint. Keys can be set in document frontmatter or any `_meta.yml`; deeper levels
override shallower ones. Lengths are CSS lengths (`mm`, `pt`, `cm`, `in`, `px`).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `title` | string | first H1 | Document title (cover page, metadata). |
| `author` | string | `"Document Producer"` | Author name for the cover and footer. |
| `date` | string | today | Date shown on the cover and as the running date. |
| `product` | string | — | Free metadata; available as `{{ product }}`. |
| `document_type` | string | — | Informational label used in the document register. |
| `version` | string | — | Free metadata; available as `{{ version }}`. |
| `status` | string | — | `draft`, `final` or `superseded`; shown in the register. |
| `outputs` | list | `[pdf]` | Formats to build: `pdf`, `docx`, `dotx`, `pptx`. |
| `output_filename` | string | source name | Output file name for every format; Jinja2 allowed; extension added. |
| `output_dir` | string | next to source | Directory for outputs, mirroring the source tree; `--output` wins. |
| `pdf_forms` | boolean | `false` | Interactive PDF form fields; output gets a `-form` suffix. |
| `include_md_in_share` | boolean | `false` | Include `.md` sources when syncing. |
| `pdf_theme` | string | cascade | Theme file overriding the normal search for all formats. |
| `dotx_field_type` | enum | `form` | `form` (fillable Word fields) or `merge` (MERGEFIELDs). |
| `body_text_align` | enum | theme | Word body alignment: `justify`, `left`, `center`, `right`. |
| `table_col_widths` | list | auto | Relative column widths for every table, e.g. `[30, 70]`; per table use `<!-- col-widths: 30, 70 -->`. |
| `css_vars` | mapping | — | PDF only: per-document CSS custom properties; image paths resolved by the asset cascade. |
| `pptx_template` | string | built-in | `.pptx`/`.potx` base for slide output. |
| `slide_size` | enum | `16:9` | `16:9` or `4:3` (quote it). |
| `slide_split` | enum | `h2` | Slide boundaries: `h1`, `h2` or `marker`. |
| `cover_page` | boolean | `false` | Add a branded cover page. |
| `cover_label` | string | `Report` | Text above the cover title. |
| `cover_text_align` | enum | `left` | Cover content alignment: `left`, `center` or `right`. |
| `cover_background` | string | `white` | Cover page background (PDF only). |
| `cover_divider` | boolean | `true` | Rule under the cover title. |
| `cover_meta_label` | string | `Prepared by` | Label before the author on the cover. |
| `cover_meta_author` | string | `author` | Author shown on the cover only. |
| `cover_footer` | boolean | `true` | Show the cover footer. |
| `cover_footer_text` | string | `{author} · Confidential` | Cover footer text; `\n` for line breaks. |
| `cover_footer_line` | boolean | `true` | Rule above the cover footer. |
| `cover_footer_color` | string | theme | Cover footer text colour. |
| `cover_logo` | path | — | Logo on the cover (resolved like `header_logo`). |
| `cover_bar` | boolean | `true` | Coloured bar(s) on the cover. |
| `cover_bar_position` | enum | `top` | `top`, `bottom` or `both`. |
| `cover_bar_height` | length | `10mm` | Bar height for both bars. |
| `cover_bar_top_height` | length | `cover_bar_height` | Top bar height. |
| `cover_bar_bottom_height` | length | `cover_bar_height` | Bottom bar height. |
| `cover_bar_logo` | path | — | Logo inside the cover bar. |
| `cover_text_on_bar` | boolean | `false` | Place the cover text inside the top bar. |
| `cover_stripe` | boolean | `false` | Vertical accent stripe on the cover. |
| `cover_stripe_height` | length | `120mm` | Stripe height. |
| `cover_stripe_width` | length | `6mm` | Stripe width. |
| `header_logo` | path | — | Logo in the page header (document folder, ancestors, repo root). |
| `header_logo_position` | enum | `right` | `left`, `center` or `right`. |
| `header_logo_height` | length | intrinsic, max 8mm | Exact logo height. |
| `header_text` | string | — | Text in the page header. |
| `header_text_position` | enum | `left` | `left`, `center` or `right`. |
| `footer_left` | string | theme | Left footer slot; `{page}` and `{pages}` insert live page numbers; empty string hides it. |
| `footer_center` | string | theme | Centre footer slot. |
| `footer_right` | string | theme | Right footer slot. |
| `page_header_bar` | boolean | `false` | Solid coloured bar on every content page. |
| `page_header_bar_color` | string | `#2563eb` | Bar colour. |
| `page_header_bar_text_color` | string | `#ffffff` | Text colour in the bar. |
| `page_header_bar_height` | length | `12mm` | Bar height. |
| `page_header_bar_padding` | length | `6mm` | Gap between bar and content. |
| `page_header_bar_offset` | length | `0mm` | Distance from the physical page top to the bar. |
| `page_header_bar_logo` | path | `header_logo` | Single logo in the bar. |
| `page_header_bar_logo_position` | enum | `right` | `left`, `center` or `right`. |
| `page_header_bar_logos` | list | — | Several logos: list of `{path, position}`. |
| `section_bar` | boolean | `false` | Coloured bars behind headings. |
| `section_bar_color` | string | `#2563eb` | Bar colour. |
| `section_bar_text_on_bar` | boolean | `true` | Text on the bar (`true`) or a rule above the heading (`false`). |
| `section_bar_text_color` | string | `#ffffff` | Text colour when on the bar. |
| `section_bar_headings` | string | `h1,h2` | Which headings get bars. |
| `sync_target` | enum | — | `azure`, `s3` or `local`. |
| `sync_config` | mapping | — | Backend settings; `${NAME}` is replaced from the environment. |
| `export` | boolean | `false` | Mark a note for `md-doc export` (inheritable from `_meta.yml`). |
| `export_format` | enum | `pdf` | Format an exported note is built to. |
| `export_path` | string | mirrors source | Sub-folder inside the export destination. |
| `export_filename` | string | source name | Output name for an exported note. |
| `export_folder` | string | `SOURCE/Exports` | Default export destination (in `_meta.yml`); relative paths resolve against the source. |
| `tags` | list | — | Tags for `md-doc export --tag`. |
| `draft` | boolean | `false` | Skip this note when exporting. |

Details and examples for each group are in the sections above, the [authoring guide](authoring-guide.md), the [theming guide](theming-guide.md), the [slides guide](slides-guide.md), the [PDF forms guide](pdf-forms-guide.md) and the [export guide](export-guide.md).
