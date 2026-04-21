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
| `outputs` | list | `[pdf]` | Output formats to generate. Values: `pdf`, `docx`, `dotx`. |
| `output_pdf` | string | `<filename>.pdf` | Override the output PDF filename. |
| `output_dir` | string | *(alongside source)* | Directory to write built outputs into. Set at any `_meta.yml` level — cascades down, overridden by deeper levels or document frontmatter. CLI `--output` always takes precedence. Supports `~` expansion. |
| `pdf_theme` | string | Auto-resolved | Path to a custom `_pdf-theme.css` (absolute or relative to repo root). |
| `pdf_forms` | boolean | `false` | Enable interactive form fields in PDF output. Output gets a `-form` suffix. |
| `dotx_field_type` | string | `"form"` | `.dotx` field type: `"form"` (Word Text Form Fields, directly fillable in Word) or `"merge"` (classic MERGEFIELDs, require a mail merge data source). |

---

## Cover Page

### Turning the cover on/off

```yaml
cover_page: true
```

> **What it does:** When `true` (default), a full-bleed cover page is generated as page 1 of the PDF. The first `# H1` heading in your Markdown becomes the cover title and is removed from the body. Set to `false` to skip the cover entirely — the document starts directly with your content.

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
