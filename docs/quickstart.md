# md-doc-pipeline Quickstart Guide

Get up and running with your first document in 10 minutes.

---

## Installation

**Prerequisites:**
- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- For PDF output: WeasyPrint system libraries. [Installation guide →](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation)

```bash
git clone https://github.com/blackdog308/md-doc-pipeline
cd md-doc-pipeline

# Create and activate virtual environment
uv venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate

# Install dependencies
uv sync --group dev
```

---

## Your First Document (5 minutes)

### 1. Set up a project

```bash
# Create a company folder and branded theme
md-doc theme init workspace/acme/
```

This creates:
- `workspace/acme/_meta.yml` — company defaults (author, logo, etc.)
- `workspace/acme/_pdf-theme.css` — branded PDF styling

### 2. Create a document

```bash
md-doc new doc proposal --in workspace/acme/
```

This creates `workspace/acme/proposal.md`:

```markdown
---
title: Q1 Project Proposal
outputs: [pdf]
cover_page: true
---

# Q1 Project Proposal

## Overview

This is the proposal content...

## Timeline

- Week 1: Planning
- Week 2: Execution
```

### 3. Build it

```bash
cd workspace/acme/
md-doc build
```

Output: `proposal.pdf` — a branded, professional PDF with:
- Cover page with your company name and theme colours
- Automatic page numbering
- Inherited styling from `_pdf-theme.css`

### 4. Customize the theme

Edit `workspace/acme/_pdf-theme.css` to change:
- Colours (`#primary`, `#accent`, etc.)
- Fonts
- Spacing and sizing

Run `md-doc build` again — changes apply automatically.

---

## Output Types

The pipeline supports four output formats:

### 1. **PDF** — Professional Reports

Best for: Reports, proposals, final documents that need professional formatting.

```yaml
---
title: My Report
outputs: [pdf]
---
```

Features:
- Branded cover pages
- Custom PDF themes (colors, fonts)
- Headers, footers, page numbers
- Automatic pagination
- Print-ready output

**Example:** `md-doc build workspace/acme/ --format pdf`

### 2. **DOCX** — Copy-to-Email

Best for: Documents you want to email or edit in Word.

```yaml
---
title: My Document
outputs: [docx]
---
```

Features:
- Editable Word format
- Preserves tables, lists, formatting
- No cover page (starts with H1 heading)
- Good for: drafts, contracts to be redlined

**Example:** `md-doc build workspace/acme/ --format docx`

### 3. **DOTX** — Mail Merge Templates

Best for: Personalized letters, contracts, or bulk-generated documents.

```yaml
---
title: Contract Template
outputs: [dotx]
cover_page: false
---

Dear [[contact_name]],

This agreement is between [[company]] and [[client]]...
```

Features:
- `[[field_name]]` becomes a Word MERGEFIELD
- Open in Word > Mailings > Start Mail Merge
- Fill the fields, generate bulk documents
- Requires `_merge_fields.yml` to document available fields

**Example:** `md-doc build workspace/acme/ --format dotx`

### 4. **PDF Forms** — Interactive Fillable PDFs

Best for: Surveys, intake forms, applications that recipients fill in and return.

```yaml
---
title: Staff Onboarding Form
outputs: [pdf]
pdf_forms: true
cover_page: false
---

# Staff Onboarding Form

<form>

**Full Name** <input type="text" name="full_name" required>

**Start Date** <input type="date" name="start_date">

**Department**
<select name="department">
  <option value="">— Select —</option>
  <option value="engineering">Engineering</option>
  <option value="sales">Sales</option>
</select>

**Notes**
<textarea name="notes" rows="4"></textarea>

**I confirm the above is correct**
<input type="checkbox" name="confirmed"> Yes

</form>
```

Features:
- Interactive fields in PDF (no additional software needed)
- Recipients fill forms in Adobe Reader, Preview, or any PDF viewer
- Output filename: `form-form.pdf` (automatic `-form` suffix)
- Supported fields: text, date, number, dropdown, textarea, checkbox, radio, submit button

**Requirements:**
- Wrap all fields in explicit `<form>` tags
- Every field needs a `name` attribute (becomes the PDF field name)
- Set `cover_page: false` (forms don't need covers)

**Example:** `md-doc build workspace/acme/ --format pdf` (with `pdf_forms: true` in frontmatter)

---

## Cascading Configuration

Documents inherit settings from parent folders. You can override at any level.

### Example folder structure

```
workspace/acme/
  _meta.yml                  ← company defaults
  _pdf-theme.css             ← company branding
  clients/
    stormfront/
      _meta.yml              ← client overrides
      proposals/
        q1-proposal.md       ← inherits from all above + its own frontmatter
```

### `workspace/acme/_meta.yml` (company level)

```yaml
author: Acme Corp
outputs: [pdf, dotx]
cover_page: true
```

### `workspace/acme/clients/stormfront/_meta.yml` (client level)

```yaml
client: Stormfront Inc
account_manager: Jane Smith
# inherits: author, outputs, cover_page from parent
```

### `workspace/acme/clients/stormfront/proposals/q1-proposal.md` (document level)

```yaml
---
title: Q1 Proposal for Stormfront
# All inherited values apply:
# author = "Acme Corp"
# outputs = [pdf, dotx]
# cover_page = true
# client = "Stormfront Inc"
# account_manager = "Jane Smith"
---
```

Run `md-doc lint workspace/` to verify the config cascade is correct.

---

## Common Tasks

### Build all documents under a project

```bash
md-doc build workspace/acme/
```

### Build only PDFs (skip DOCX/DOTX)

```bash
md-doc build workspace/acme/ --format pdf
```

### Build to a separate output directory

```bash
md-doc build workspace/acme/ --output build/
```

This mirrors the source tree under `build/` — useful for CI/CD pipelines.

### Check documents before building (linting)

```bash
md-doc lint workspace/acme/
```

Catches:
- Invalid YAML frontmatter
- Undefined Jinja2 variables
- Missing template includes
- Undefined merge fields

### Create a branded theme

```bash
md-doc theme init workspace/acme/
```

Prompts for:
- Organization name
- Primary, accent, and body text colours
- Font families
- Page size (A4 or Letter)

### Create a theme override for a sub-folder

```bash
md-doc theme override workspace/acme/clients/stormfront/
```

Generates a minimal CSS file that imports the parent theme and overrides only colours.

### Use Jinja2 variables in documents

In `workspace/acme/_meta.yml`:

```yaml
author: Acme Corp
product: Widget Pro
version: "2.5"
```

In your Markdown:

```markdown
# {{ product }} v{{ version }}

Prepared by {{ author }}
```

Output: `# Widget Pro v2.5` — resolved at build time.

### Use merge fields in DOTX documents

In `workspace/acme/_merge_fields.yml`:

```yaml
contact_name: Full name of contact
company: Company name
invoice_total: Total invoice amount
```

In your `contract.md`:

```yaml
---
outputs: [dotx]
---

Dear [[contact_name]],

This invoice is for [[company]].

Total: $[[invoice_total]]
```

List available fields:

```bash
md-doc fields workspace/acme/
```

### Sync outputs to cloud storage

```bash
# Sync to Azure File Share
md-doc sync workspace/acme/ --backend azure

# Sync to AWS S3
md-doc sync workspace/acme/ --backend s3

# Dry run (see what would be synced, without uploading)
md-doc sync workspace/acme/ --dry-run
```

---

## PDF Forms Deep Dive

### When to use PDF forms

✅ **Good for:**
- Intake forms (applicants fill and submit)
- Surveys (respondents return via email)
- Applications (candidates complete and upload)
- Internal checklists (staff fill out and sign)

❌ **Not ideal for:**
- Documents meant for printing and scanning (use regular PDF)
- Documents with complex validation (PDF forms support `required` and `maxlength` only)
- Forms needing submission logic (you'll need a backend; PDF forms can't POST data)

### Form field types

| HTML | PDF field | Notes |
|---|---|---|
| `<input type="text">` | Text | `maxlength`, `required` work |
| `<input type="email">` | Text | Visual hint only |
| `<input type="date">` | Text | Date picker in some readers |
| `<input type="number">` | Text | Numeric hint only |
| `<textarea>` | Multiline text | `rows` controls height |
| `<input type="checkbox">` | Checkbox | Single box |
| `<input type="radio">` | Radio group | All same `name` = one group |
| `<select>` | Dropdown | Standard select menu |
| `<input type="submit">` | Submit button | Sets `<form action>` endpoint |

### Example form with all field types

```markdown
---
title: Complete Intake Form
outputs: [pdf]
pdf_forms: true
cover_page: false
---

# Intake Form

<form>

**Name** <input type="text" name="full_name" required maxlength="100">

**Email** <input type="email" name="email" required>

**Date of Birth** <input type="date" name="dob">

**Preferred Contact Method**
<select name="contact_method">
  <option value="">— Select —</option>
  <option value="email">Email</option>
  <option value="phone">Phone</option>
  <option value="sms">SMS</option>
</select>

**Years of Experience** <input type="number" name="years_experience" min="0">

**Comments**
<textarea name="comments" rows="5"></textarea>

**Preferred Schedule**
<input type="radio" name="schedule" value="fulltime"> Full-time
<input type="radio" name="schedule" value="parttime"> Part-time
<input type="radio" name="schedule" value="contract"> Contract

**I agree to the terms**
<input type="checkbox" name="agree_terms" required>

<input type="submit" value="Submit">

</form>
```

### Best practices

1. **Use explicit `<form>` tags** — fields outside `<form>` won't be interactive
2. **Use `snake_case` for field names** — becomes the PDF field name, used in data processing
3. **Set `cover_page: false`** — forms don't need cover pages
4. **Use `required` attribute** — enforces that fields must be filled
5. **Label fields clearly** — use bold or heading text above each field
6. **Test in multiple readers** — Adobe Reader, Preview, web browsers all support PDF forms

---

## Next Steps

- **Read more:** Check out `workspace/CLAUDE.md` for detailed authoring guidance
- **Theming:** See root `CLAUDE.md` for CSS variables and advanced theme customization
- **CI/CD:** The GitHub Actions template shows how to integrate into your workflow
- **Cloud sync:** Configure Azure, S3, or local sync targets in `_meta.yml`

---

## Troubleshooting

**"No Markdown documents found"**
- Check that your `.md` files are not in a `templates/` directory (those are skipped)
- Check that filenames don't start with `_` (those are config files)

**PDF looks wrong**
- Run `md-doc theme init` to regenerate the default theme (you may have corrupted CSS)
- Check `_pdf-theme.css` for syntax errors
- Check that image paths are absolute or relative to the document

**Linting fails on undefined variables**
- Check that `{{ variable }}` names match keys in `_meta.yml`
- Remember: `{{ var }}` (Jinja2) is for config values; `[[field]]` (merge fields) is for Word

**Form fields aren't interactive**
- Ensure fields are wrapped in `<form>` tags
- Ensure each field has a `name` attribute
- Check that `pdf_forms: true` is in the document frontmatter
- Verify the output file has the `-form.pdf` suffix

---

## Help & Feedback

- **Issues:** [GitHub Issues](https://github.com/blackdog308/md-doc-pipeline/issues)
- **Docs:** Check `CLAUDE.md` and `workspace/CLAUDE.md` in the repo
- **Examples:** See `examples/` folder for sample projects
