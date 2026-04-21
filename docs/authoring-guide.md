# Document Authoring Guide

A complete guide to writing documents with md-doc-pipeline — from simple one-pagers to branded multi-section reports with custom cover pages, headers, and interactive forms.

---

## Document Structure

Every document is a Markdown file with YAML frontmatter at the top:

```markdown
---
title: My Document Title
author: Jane Smith
date: March 2026
outputs: [pdf]
---

# My Document Title

## First Section

Content goes here...
```

The `# H1` heading becomes the cover page title in PDF output. Use `## H2` for major sections and `### H3` for subsections.

---

## Frontmatter

The YAML block between `---` markers controls how your document is built. Only set keys that are new or different from what's already defined in parent `_meta.yml` files.

### Required keys

None — every key has a sensible default. But most documents should set at least:

```yaml
---
title: The Document Title
---
```

### Common keys

```yaml
---
title: Q1 Project Report
author: Acme Corp
date: April 2026
outputs: [pdf]
cover_page: true
cover_label: Report
---
```

See [config-reference.md](config-reference.md) for the full list of available keys.

---

## Configuration Cascade

Settings flow downward through the folder hierarchy:

```
workspace/acme/
  _meta.yml              ← author: "Acme Corp", outputs: [pdf]
  _pdf-theme.css         ← brand colours
  clients/
    stormfront/
      _meta.yml          ← client: "Stormfront Inc"
      proposals/
        q1-proposal.md   ← inherits everything above + its own frontmatter
```

A document at `proposals/q1-proposal.md` automatically inherits `author`, `outputs`, and theme from all parent levels. It only needs to set what's unique to it (like `title`).

### `_meta.yml`

Set defaults that apply to everything at this folder level and below:

```yaml
# workspace/acme/_meta.yml
author: Acme Corp
outputs: [pdf]
cover_page: true
```

### `_pdf-theme.css`

Brand colours, fonts, and spacing for PDF output. Created by `md-doc theme init`. The same cascading logic applies — a theme file deeper in the tree overrides the parent.

### `_merge_fields.yml`

Documents the `[[fields]]` available for mail merge at this level. Cascades additively — deeper levels add to parent fields.

```yaml
contact_name: Full name of the primary contact
company: Client company name
```

---

## Three Variable Types

These are distinct and must not be mixed:

{% raw %}
### `{{ variable }}` — Build-time values

Resolved from `_meta.yml` at build time. Use for values already known when the document is built.

```markdown
Prepared by {{ author }} on {{ date }}.
Product: {{ product }} v{{ version }}.
```

### `[[field_name]]` — Mail merge fields

Become Word MERGEFIELD elements in `.dotx` output. Use for values filled in after the document is built.

```markdown
Dear [[contact_name]],

This invoice is for [[company]].
Total: $[[invoice_total]]
```

Only use field names defined in a `_merge_fields.yml` file. Check available fields with:

```bash
md-doc fields workspace/acme/clients/stormfront/
```

### `{% include "..." %}` — Template fragments

Insert shared content blocks from `templates/` directories:

```markdown
{% include "templates/legal-footer.md" %}
```
{% endraw %}

Template search order: document directory → `templates/` in ancestor dirs → repo root `templates/`.

---

## Cover Pages

The cover page is generated automatically from your config. The `# H1` heading in your Markdown becomes the cover title.

### Turning off the cover

```yaml
---
cover_page: false
---
```

### Customising the cover

The cover page is composable — mix and match individual elements:

```yaml
---
# Label above the title
cover_label: Proposal

# Text alignment
cover_text_align: center

# Horizontal bar(s)
cover_bar: true
cover_bar_position: both
cover_bar_top_height: 130mm
cover_bar_bottom_height: 20mm

# Overlay text on the top bar (white text on blue)
cover_text_on_bar: true

# Vertical accent stripe
cover_stripe: true
cover_stripe_height: 120mm

# Divider line below title
cover_divider: true

# Full-bleed background colour
cover_background: "#2563eb"

# Logo on the cover
cover_logo: assets/logo.png

# Footer
cover_footer: true
cover_footer_text: "Custom footer text here"
cover_footer_line: false
cover_footer_color: "#ffffff"
---
```

See [config-reference.md](config-reference.md) for the full list of cover options and example layouts.

---

## Page Headers

Add a logo and/or text to every page (except the cover):

```yaml
---
header_logo: assets/company-logo.png
header_logo_position: right
header_text: "Acme Corp — Confidential"
header_text_position: left
---
```

Positions: `left`, `center`, `right`. Logo and text can occupy different positions. The logo path is resolved using the same cascade as other config (doc dir → ancestors → repo root).

---

## Page Footers

Page footers are controlled by the `_pdf-theme.css` theme file, not frontmatter. The default theme includes:

- **Bottom left:** Author name
- **Bottom center:** Document date
- **Bottom right:** Page X of Y

To customise, edit the `@page` rules in your `_pdf-theme.css`.

---

## Output Formats

### PDF — Professional reports

```yaml
outputs: [pdf]
```

Full-featured output with cover pages, headers, footers, page numbers, and professional typography. Best for final documents.

### DOCX — Editable Word documents

```yaml
outputs: [docx]
```

For documents that need to be edited in Word or pasted into emails. No cover page.

### DOTX — Mail merge templates

```yaml
outputs: [dotx]
cover_page: false
```

`[[field]]` markers become Word MERGEFIELD elements. Open in Word → Mailings → Start Mail Merge.

### PDF Forms — Interactive fillable PDFs

```yaml
outputs: [pdf]
pdf_forms: true
cover_page: false
```

Wrap fields in `<form>` tags. Every field needs a `name` attribute.

```markdown
<form>

**Full name** <input type="text" name="full_name" required>

**Department**
<select name="department">
  <option value="">— Select —</option>
  <option value="engineering">Engineering</option>
  <option value="sales">Sales</option>
</select>

**Notes**
<textarea name="notes" rows="4"></textarea>

</form>
```

Supported fields: text, email, date, number, checkbox, radio, select, textarea, submit.

---

## Theming

### Create a brand theme

```bash
md-doc theme init workspace/acme/
```

This generates `_pdf-theme.css` with your brand colours, fonts, and page setup.

### Create a sub-theme (colour override only)

```bash
md-doc theme override workspace/acme/clients/stormfront/
```

Generates a minimal CSS file that `@import`s the parent theme and overrides only colours.

### Theme structure

The CSS theme controls every visual aspect of the PDF:

- **Page setup** — margins, size (A4/Letter)
- **Headers and footers** — `@page` margin boxes
- **Cover page** — bar, stripe, title, label, footer styles
- **Typography** — headings, body text, links
- **Tables** — header row, striping, borders
- **Code blocks** — background, border, font
- **Blockquotes** — accent border, background

---

## Building

### Build one project

```bash
md-doc build workspace/acme/
```

### Build everything

```bash
md-doc build workspace/
```

### Build specific format only

```bash
md-doc build workspace/acme/ --format pdf
md-doc build workspace/acme/ --format dotx
```

### Build to a separate output directory

```bash
md-doc build workspace/acme/ --output build/
```

### Lint before building

```bash
md-doc lint workspace/acme/
```

Catches broken variables, missing includes, and undefined fields without invoking WeasyPrint.

---

## Scaffolding

### New project folder

```bash
md-doc new folder clients/newcorp --in workspace/acme/
```

Creates the folder with a starter `_meta.yml`.

### New document

```bash
md-doc new doc proposal --in workspace/acme/clients/newcorp/
```

Creates a `.md` file with starter frontmatter.

---

## Tips

1. **Keep frontmatter minimal.** Only set keys that differ from parent `_meta.yml` values.
2. **Use `md-doc lint` before `md-doc build`.** Lint is fast and catches config errors early.
3. **One H1 per document.** The first `# H1` becomes the cover title and is stripped from the body.
4. **Headings stay with content.** The pipeline automatically prevents headings from being orphaned at page breaks.
5. **Images are auto-sized.** Use standard Markdown image syntax: `![alt](path/to/image.png)`.
6. **Tables avoid page breaks.** Tables, code blocks, and blockquotes won't split across pages when possible.
7. **Test themes with a short document first.** Build a one-page sample to check colours and spacing before applying to a long report.
