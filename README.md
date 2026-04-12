# md-doc-pipeline

A Markdown → PDF / DOCX / DOTX document pipeline with cascading config, Jinja2 template composition, merge field support, and pluggable cloud sync.

Built for document-heavy workflows — proposals, project reports, compliance documents, contracts — where content lives in Markdown, is assembled from reusable fragments, and is published to multiple formats.

---

## Features

- **Cascading `_meta.yml` config** — inherit settings from parent directories, override at any folder or document level
- **Jinja2 renderer** — compose documents from reusable fragments with `{% include %}` and `{{ variable }}` substitution
- **Merge field support** — `[[field_name]]` in Markdown becomes a Word `«MERGEFIELD»` in `.dotx` output for downstream mail merge
- **PDF output** — WeasyPrint builder with branded cover page, headers, footers, and pagination
- **DOCX output** — python-docx builder for copy-to-email Word documents
- **DOTX output** — Word merge template builder; your other application fills the fields
- **Cascading PDF themes** — `_pdf-theme.css` at any folder level; deepest wins. Run `md-doc theme init` to generate a full theme or `md-doc theme override` for a minimal colour override
- **Merge field schema** — `_merge_fields.yml` at any level defines and documents available `[[fields]]`, cascading upward
- **Document register** — JSON + Markdown index of all built outputs for audit trails
- **Pluggable sync** — push outputs to Azure File Share, AWS S3, or a local path
- **CI-ready** — reusable GitHub Actions workflow template

---

## Installation

**Prerequisites:**
- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- PDF generation requires WeasyPrint system libraries — see the [WeasyPrint docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation) for platform setup.

**Setup:**

```bash
git clone https://github.com/blackdog308/md-doc-pipeline
cd md-doc-pipeline

# Create and activate virtual environment
uv venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate

# Install dependencies (like npm install / composer install)
uv sync --group dev

# Run commands
uv run md-doc --help
uv run md-doc build workspace/acme/
```

---

## Repo layout

```
workspace/                  ← all live client/company projects
  acme/
    _meta.yml
    _pdf-theme.css
    _merge_fields.yml
    templates/
    clients/
      stormfront-inc/
        _meta.yml
        _merge_fields.yml
        proposals/
          q1-proposal.md
examples/                   ← reference examples
md_doc/                     ← pipeline source code
tests/
```

All `_` prefixed files (`_meta.yml`, `_pdf-theme.css`, `_merge_fields.yml`) are pipeline config — **commit them**. Built outputs (`*.pdf`, `*.docx`, `*.dotx`) are gitignored.

---

## Getting Started

### 1. Set up your first project

```bash
# Create a branded project folder and theme
md-doc theme init workspace/acme/

# Create your first document
md-doc new doc proposal --in workspace/acme/

# Build it
cd workspace/acme/
md-doc build
```

This generates `proposal.pdf` — a branded, professional document with cover page, headers, footers, and pagination.

### 2. Choose your output format

| Format | Best for | Features |
|---|---|---|
| **PDF** | Reports, proposals, final documents | Branded cover pages, custom themes, professional formatting |
| **DOCX** | Documents to email or edit in Word | Editable format, preserves formatting, good for drafts |
| **DOTX** | Mail merge templates, personalized letters | `[[field_name]]` becomes Word MERGEFIELD for bulk generation |
| **PDF Forms** | Interactive surveys, intake forms, applications | `<input>`, `<select>`, `<textarea>` become fillable form fields |

See the [Output Types Guide](docs/quickstart.md#output-types) for detailed examples of each format.

### 3. Common commands

```bash
# Build all documents
md-doc build workspace/acme/

# Build only PDFs
md-doc build workspace/acme/ --format pdf

# Check documents before building
md-doc lint workspace/acme/

# Sync to cloud storage
md-doc sync workspace/acme/ --backend azure

# Generate a document register
md-doc register workspace/acme/
```

**→ [Full Quickstart Guide](docs/quickstart.md)** — Installation, all output types, cascading config, Jinja2 variables, merge fields, PDF forms, troubleshooting, and more.

---

## Configuration cascade

Every `_meta.yml` from the repo root down to the document is merged — deeper files override shallower ones. Document YAML frontmatter overrides everything.

```
workspace/acme/_meta.yml              author, outputs, sync_target
  clients/stormfront/_meta.yml        client, account_manager
    projects/website/_meta.yml        project, version, status
      q1-report.md  (frontmatter)     title, document_type
```

All merged keys are available as `{{ variable }}` in document bodies.

### Common config keys

```yaml
title: My Document
product: Alpha Initiative
document_type: project_report     # informational — used in register
version: "2.0"
status: draft                     # draft | final | superseded
author: Acme Corp
date: 1 May 2026

outputs: [pdf, dotx]              # pdf | docx | dotx — default: [pdf]
output_pdf: Alpha-Report.pdf      # override output filename
output_dotx: Alpha-Template.dotx
cover_page: true                  # default true — set false to omit cover

pdf_theme: path/to/_pdf-theme.css # explicit theme override (optional)
include_md_in_share: false        # sync source .md files too?

sync_target: azure                # azure | s3 | local
sync_config:
  # Azure
  connection_string_env: AZURE_STORAGE_CONNECTION_STRING
  share_name: report-docs
  remote_dir: projects/2026

  # S3
  bucket: my-docs-bucket
  prefix: projects/2026/

  # Local
  path: /mnt/shared/docs/
```

---

## Document authoring

### Build-time variables (Jinja2)

Resolved from `_meta.yml` cascade + frontmatter at build time:

```markdown
---
title: Project Report — {{ product }}
client: Stormfront Inc
report_date: 1 May 2026
---

Dear {{ client }},

Please find the report for **{{ product }}** as at {{ report_date }}.
```

### Merge fields (for `.dotx` output)

`[[field_name]]` passes through Jinja2 untouched and becomes a Word `«MERGEFIELD»` in the `.dotx` file. Your downstream application supplies the values at merge time.

```markdown
Dear [[contact_name]],

Thank you for choosing [[company]] for your [[project]] needs.
We have prepared this proposal specifically for [[client]].
```

Both syntaxes can coexist in the same document:

```markdown
This is version {{ version }} of our proposal for [[client]].
```

- `{{ version }}` — resolved from `_meta.yml` at build time
- `[[client]]` — becomes a Word merge field in the `.dotx`

### Including shared fragments

```markdown
{% include "templates/org-header.md" %}

# {{ title }}

Body content here...

{% include "templates/confidentiality-footer.md" %}
```

Fragment search order (deepest match wins):
1. Document's own directory
2. `templates/` next to the document
3. `templates/` in each ancestor directory (deepest first)
4. `templates/` at the repo root

---

## Merge field schema

Define available `[[fields]]` at any directory level in `_merge_fields.yml`. Files cascade upward — deeper levels add to the parent's fields.

```yaml
# workspace/acme/_merge_fields.yml
contact_name: Full name of the primary contact
company: Client company name
sign_off: Closing signatory name

# workspace/acme/clients/stormfront/_merge_fields.yml
account_manager: Assigned account manager
client_ref: Client's internal reference number

# workspace/acme/projects/website/_merge_fields.yml
item_1: First line item description
item_1_price: First line item price
delivery_date: Agreed delivery date
```

A document at the `website` level has all fields from all three files available.

---

## PDF themes

`_pdf-theme.css` controls the visual output for PDF. Place one at any directory level — the deepest one wins, mirroring `_meta.yml` cascade.

### Create a full brand theme

```bash
md-doc theme init workspace/acme/
```

Asks for org name, primary colour, accent colour, fonts, and page size. Writes a complete `_pdf-theme.css` and a starter `_meta.yml`.

### Create a sub-brand override

```bash
md-doc theme override workspace/acme/products/pulse/
```

Finds the nearest parent `_pdf-theme.css` automatically, asks only for the colours that differ, and writes a minimal file using CSS `@import`:

```css
/* Pulse Monitor — brand colour overrides */
@import "../../_pdf-theme.css";

.cover-bar    { background: #7d3c00; }
.cover-stripe { background: #e67e22; }
h1            { color: #7d3c00; }
h2            { color: #e67e22; }
/* ... */
```

### Cover page

Controlled per document or folder:

```yaml
cover_page: true   # default — branded cover with title, author, date
cover_page: false  # body only, no cover
```

---

## DOTX merge templates

When `outputs` includes `dotx`, the builder produces a `.dotx` Word Template file with proper `«MERGEFIELD»` fields that your mail merge application can fill.

```yaml
# _meta.yml
outputs: [dotx]
```

```markdown
---
title: [[client]] Proposal
outputs: [dotx]
cover_page: false
---

Dear [[contact_name]],

| Service | Description | Price |
|---------|-------------|-------|
| [[item_1]] | [[item_1_desc]] | [[item_1_price]] |

Regards,
[[sign_off]]
[[sign_off_title]]
```

The `.dotx` file is ready to open in Word or pass to your merge system — all `[[field]]` markers become native Word merge fields.

---

## CLI reference

```
md-doc lint [ROOT]
  ROOT                  Directory to lint (default: current directory)

md-doc build [ROOT] [OPTIONS]
  ROOT                  Directory to build (default: current directory)
  -o, --output DIR      Mirror source tree under DIR instead of alongside source
  -f, --format          pdf | docx | dotx | all  (default: from outputs config)
  --strict              Fail on undefined Jinja2 variables
  --dry-run             Show what would be built without building

md-doc new folder NAME [--in DIR]
  NAME                  Relative path for the new folder (e.g. clients/acme)
  --in DIR              Parent directory (default: current directory)

md-doc new doc NAME [--in DIR]
  NAME                  Document stem — creates NAME.md
  --in DIR              Directory to create document in (default: current directory)

md-doc fields [DIRECTORY]
  DIRECTORY             Show all [[fields]] available at this level (default: current directory)

md-doc theme init [DIR]
  DIR                   Directory to create _pdf-theme.css and _meta.yml in

md-doc theme override [DIR]
  DIR                   Directory to create a minimal colour-override _pdf-theme.css in

md-doc sync [ROOT] [OPTIONS]
  ROOT                  Directory to sync (default: current directory)
  -b, --backend         azure | s3 | local  (default: from sync_target config)
  --dry-run             Show what would be synced without uploading

md-doc register [ROOT] [OPTIONS]
  ROOT                  Directory to scan (default: current directory)
  -o, --output FILE     Output path for register.json
  --no-md               Skip writing register.md
```

---

## Multi-level example

The [`examples/blueshift/`](examples/blueshift/) example demonstrates the full cascade:

```
blueshift/
├── _meta.yml                    # author, outputs, sync
├── _pdf-theme.css               # Blueshift navy/blue base theme
├── templates/
│   ├── company-header.md
│   └── legal-footer.md
├── products/
│   ├── _meta.yml                # document_type, status
│   ├── pulse/
│   │   ├── _meta.yml            # product: Pulse Monitor, version
│   │   ├── _pdf-theme.css       # amber/orange override — @import ../../_pdf-theme.css
│   │   └── on-call-handbook.md
│   └── nova/
│       ├── _meta.yml            # product: Nova Analytics, version
│       └── integration-guide.md
└── clients/
    └── stormfront-inc/
        ├── _meta.yml            # client, account_manager
        ├── templates/
        │   └── company-header.md  # client-branded, overrides root
        └── onboarding-proposal.md
```

A Pulse document resolves:
- Config: `blueshift/_meta.yml` → `products/_meta.yml` → `products/pulse/_meta.yml` → frontmatter
- Theme: `products/pulse/_pdf-theme.css` (amber) → imports `blueshift/_pdf-theme.css` (navy base)
- Templates: `products/pulse/templates/` → `products/templates/` → `blueshift/templates/`

---

## Development

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/blackdog308/md-doc-pipeline
cd md-doc-pipeline
uv sync --group dev
uv run md-doc --help
```

```bash
uv run pytest                         # all tests
uv run pytest tests/test_renderer.py -v  # single file
uv run ruff check .
uv run black --check .
uv run mypy md_doc/
```
