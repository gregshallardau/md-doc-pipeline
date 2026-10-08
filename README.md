# md-doc-pipeline

A Markdown → PDF / DOCX / DOTX / PPTX document pipeline with cascading config, Jinja2 template composition, merge field support, and pluggable cloud sync.

Built for document-heavy workflows — proposals, project reports, compliance documents, contracts, and slide decks — where content lives in Markdown, is assembled from reusable fragments, and is published to multiple formats.

---

## Features

- **Cascading `_meta.yml` config** — inherit settings from parent directories, override at any folder or document level
- **Jinja2 renderer** — compose documents from reusable fragments with `{% include %}` and `{{ variable }}` substitution
- **Merge field support** — `[[field_name]]` in Markdown becomes a Word `«MERGEFIELD»` in `.dotx` output for downstream mail merge
- **PDF output** — WeasyPrint builder with branded cover page, headers, footers, and pagination
- **DOCX output** — python-docx builder for copy-to-email Word documents
- **DOTX output** — Word merge template builder; your other application fills the fields
- **PPTX output** — python-pptx slide builder with a deck-first authoring schema: headings segment into slides, plus layout directives for section dividers, multi-column bodies, big-number stat tiles, pull-quotes, image showcases, per-slide backgrounds, and speaker notes ([slides guide](docs/slides-guide.md))
- **Cascading themes** — `_pdf-theme.css`, shared `_theme.css` and Word-only `_docx-theme.css` at any folder level; deepest wins. `md-doc theme init` generates a full theme, `md-doc theme override` a colour-only override, and `--mddoc-*` custom properties set brand defaults in CSS ([theming guide](docs/theming-guide.md))
- **Fillable PDF forms** — `pdf_forms: true` with a `?[text: name]` shorthand, bordered `?[box]` grids, signatures and Yes/No pairs; the same source gives real Word form fields in `.dotx` ([forms guide](docs/pdf-forms-guide.md))
- **Diagrams and maths** — Mermaid flowcharts, charts, Gantt, sequence, mind map, ER and state diagrams, plus LaTeX equations, in PDF and Word ([Markdown reference](docs/markdown-reference.md))
- **Export and extract** — `md-doc export` builds only the notes marked `export: true` ([export guide](docs/export-guide.md)); `md-doc extract` turns a PDF or DOCX back into Markdown ([extraction guide](docs/extraction-guide.md))
- **Editors** — a browser editor with live preview ([md-doc-web-editor](md-doc-web-editor/README.md), [Filament plugin](filament-md-doc/README.md)) and a [Neovim plugin](nvim-plugin/README.md) that resolves includes and variables inline
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
git clone https://github.com/gregshallardau/md-doc-pipeline
cd md-doc-pipeline

# Linux / macOS
./init.sh
source .venv/bin/activate

# Windows
init.bat
.venv\Scripts\activate
```

The init script checks prerequisites, creates the virtual environment, and installs all dependencies. Or do it manually:

```bash
uv venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate
uv sync --group dev
```

### Browser editor

From the repository root, install the editor in the same `.venv`:

```bash
uv venv  # skip if .venv already exists
uv sync --group editor
uv run --offline --no-sync md-doc-edit serve workspace/ --no-browser
```

Open http://127.0.0.1:8765/. `--offline --no-sync` launches the installed
environment without dependency downloads or syncing. If you choose to sync
again, include `--group editor` to retain the editor. Activation is optional. For activated commands: `source .venv/bin/activate`
(Linux/macOS), `.\.venv\Scripts\Activate.ps1` (PowerShell), or
`.venv\Scripts\activate.bat` (Command Prompt), then run
`md-doc-edit serve workspace/`. See the [editor guide](md-doc-web-editor/README.md) for details.


---

## Repo layout

```
workspace/                  ← all live client/company projects
  acme/
    _meta.yml
    _theme.css
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

All `_` prefixed files (`_meta.yml`, `_theme.css`, `_merge_fields.yml`) are pipeline config — **commit them**. Built outputs (`*.pdf`, `*.docx`, `*.dotx`) are gitignored.

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
| **DOTX** | Fillable templates, mail merge | `[[field_name]]` becomes Word Text Form Field (default) or MERGEFIELD |
| **PPTX** | Slide decks, quarterly reviews, pitches | Deck-first schema: section/columns/stat/quote/image/center layouts, per-slide backgrounds, speaker notes ([guide](docs/slides-guide.md)) |
| **PDF Forms** | Interactive surveys, intake forms, applications | `<input>`, `<select>`, `<textarea>` become fillable form fields |

See the [Output Types Guide](docs/quickstart.md#output-types) for detailed examples of each format, and the [Slides Guide](docs/slides-guide.md) for authoring decks.

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

outputs: [pdf, dotx]              # pdf | docx | dotx | pptx — default: [pdf]
output_filename: "Alpha-Report"  # override output filename (all formats; extension is added)
output_dotx: Alpha-Template.dotx
output_dir: /path/to/output/      # route built files here (cascades from _meta.yml; CLI --output overrides)
cover_page: false                 # default false — set true to add a branded cover
cover_label: Report               # text above cover title (default: "Report")

header_logo: assets/logo.png      # logo in page header (resolved doc dir → repo root)
header_logo_position: right       # left | center | right (default: right)
header_text: "Acme Corp"          # text in page header
header_text_position: left        # left | center | right (default: left)

pdf_theme: path/to/_theme.css # explicit theme override (optional)
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

### Word template fields (for `.dotx` output)

`[[field_name]]` passes through Jinja2 untouched and becomes a Word field in the `.dotx` file. The field type is controlled by `dotx_field_type`:

- **`form`** (default) — Word Text Form Field with Bookmark = field name. Open the `.dotx` in Word, tab through fields, fill in values, save. No mail merge required.
- **`merge`** — Classic Word `«MERGEFIELD»`. Supply a data source via Word → Mailings → Start Mail Merge.

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

`_theme.css` controls the visual output for PDF. Place one at any directory level — the deepest one wins, mirroring `_meta.yml` cascade.

### Create a full brand theme

```bash
md-doc theme init workspace/acme/
```

Asks for org name, primary colour, accent colour, fonts, and page size. Writes a complete `_theme.css` and a starter `_meta.yml`.

### Create a sub-brand override

```bash
md-doc theme override workspace/acme/products/pulse/
```

Finds the nearest parent `_theme.css` automatically, asks only for the colours that differ, and writes a minimal file using CSS `@import`:

```css
/* Pulse Monitor — brand colour overrides */
@import "../../_theme.css";

.cover-bar    { background: #7d3c00; }
.cover-stripe { background: #e67e22; }
h1            { color: #7d3c00; }
h2            { color: #e67e22; }
/* ... */
```

### Cover page

Controlled per document or folder:

```yaml
cover_page: true   # branded cover with title, author, date
cover_page: false  # default — body only, no cover
```

---

## DOTX Word templates

When `outputs` includes `dotx`, the builder produces a `.dotx` Word Template file. By default, `[[field]]` markers become Word Text Form Fields with Bookmark = field name — directly fillable in Word without a mail merge. Set `dotx_field_type: merge` for classic MERGEFIELDs.

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

The `.dotx` file is ready to open in Word — tab through the Text Form Fields and fill in values directly. Add `dotx_field_type: merge` to your `_meta.yml` if you need classic MERGEFIELDs for a mail merge data source instead.

---

## CLI reference

| Command | Purpose |
|---------|---------|
| `md-doc build [ROOT]` | Build to PDF / DOCX / DOTX / PPTX (`-o`, `-f`, `-t`, `-j`, `--force`, `--strict`, `--dry-run`, `-w`) |
| `md-doc lint [ROOT]` | Check documents without rendering (`--render`, `--fix`, `-w`) |
| `md-doc fields [DIR]` | List the `[[merge fields]]` available at a folder |
| `md-doc new folder NAME` / `new doc NAME` | Scaffold a folder (with `_meta.yml`) or a document (`--in DIR`) |
| `md-doc theme init [DIR]` / `theme override [DIR]` | Write a full `_pdf-theme.css`, or a colour-only override of the parent theme |
| `md-doc export [SOURCE]` | Build only notes marked `export: true` (`--tag`, `-o`, `-f`, `-w`) |
| `md-doc extract FILE` | Convert a PDF or DOCX to Markdown |
| `md-doc sync [ROOT]` | Upload built files to Azure, S3 or a folder (`-b`, `--dry-run`, `-w`) |
| `md-doc register [ROOT]` | Write `register.json`, `.md` and `.csv` |
| `md-doc workspaces` | List named remote workspaces |
| `md-doc doctor` | Check Python, dependencies, WeasyPrint libraries and optional extras |

Global options go before the subcommand: `--debug`, `--quiet`, `--log-level LEVEL`, `--version`.
Every command and option, the remote-workspaces file and the environment variables are in the
[CLI reference](docs/cli-reference.md).

---

## Documentation

- [Quickstart](docs/quickstart.md) — install, output types, config, Jinja2, forms
- [CLI reference](docs/cli-reference.md) — every command, option, environment variable and the remote-workspaces file
- [Config reference](docs/config-reference.md) — every `_meta.yml` / frontmatter key, with a complete key index
- [Theming guide](docs/theming-guide.md) — theme files and cascade, `--mddoc-*` brand properties, `css_vars`, what Word reads, form styling
- [Markdown reference](docs/markdown-reference.md) — extensions, tables, images, page breaks, Mermaid, differences between formats
- [Export guide](docs/export-guide.md) — `md-doc export` and its frontmatter keys
- [Extraction guide](docs/extraction-guide.md) — `md-doc extract`
- [Authoring guide](docs/authoring-guide.md) — Markdown authoring conventions
- [Slides guide](docs/slides-guide.md) — deck-first PPTX authoring: layouts, backgrounds, columns, stats, quotes
- [LLM deck prompt](docs/llm-deck-prompt.md) — turn raw content into a valid deck file with any LLM
- [Prompts](prompts/) — `document-author.md` (write a document from a description), `document-converter-standalone.md` (convert an existing document), `new-workspace.md` (agent prompt to onboard a new company workspace), `upgrade-css.md` (agent prompt to bring an older theme up to date)
- [PDF forms guide](docs/pdf-forms-guide.md) — interactive fillable PDFs
- [Troubleshooting](docs/troubleshooting.md) — system libs, Mermaid-in-Word, sync
- [Python API](docs/python-api.md) — using the pipeline as a library

---

## Multi-level example

The [`examples/blueshift/`](examples/blueshift/) example demonstrates the full cascade:

```
blueshift/
├── _meta.yml                    # author, outputs, sync
├── _theme.css               # Blueshift navy/blue base theme
├── templates/
│   ├── company-header.md
│   └── legal-footer.md
├── decks/
│   ├── _meta.yml                # outputs: [pptx], slide_size: 16:9
│   └── quarterly-review.md      # deck-first example — every slide layout
├── products/
│   ├── _meta.yml                # document_type, status
│   ├── pulse/
│   │   ├── _meta.yml            # product: Pulse Monitor, version
│   │   ├── _theme.css       # amber/orange override — @import ../../_theme.css
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
- Theme: `products/pulse/_theme.css` (amber) → imports `blueshift/_theme.css` (navy base)
- Templates: `products/pulse/templates/` → `products/templates/` → `blueshift/templates/`

The [`decks/quarterly-review.md`](examples/blueshift/decks/quarterly-review.md) deck shows the PPTX
schema end to end — title slide, branded section dividers, stat tiles, two-column comparison, a
Mermaid pipeline diagram, a data table, a pull-quote, and a centred closer. Build it with
`md-doc build examples/blueshift/decks/ --format pptx`.

---

## Development

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/gregshallardau/md-doc-pipeline
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
