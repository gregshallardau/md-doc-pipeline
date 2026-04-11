# md-doc-pipeline

A lightweight Markdown → PDF/DOCX document pipeline with cascading config, Jinja2 template composition, and pluggable cloud sync.

Built for document-heavy workflows — insurance binders, renewal letters, compliance reports — where content is structured in Markdown, assembled from reusable fragments, and published to PDF and/or DOCX.

---

## Features

- **Cascading `_meta.yml` config** — inherit shared settings from parent directories, override at the document or folder level, override again with YAML frontmatter
- **Jinja2 template renderer** — compose documents from reusable fragments (`{% include "templates/aib-header.md" %}`)
- **PDF output** — WeasyPrint-based builder with a professional A4 theme (branded cover page, headers, footers, pagination)
- **DOCX output** — python-docx builder for editable Word documents
- **Document register** — CSV + Markdown index of all built outputs, suitable for audit trails
- **Pluggable sync** — push outputs to Azure File Share, AWS S3, or a local path
- **CLI** — `md-doc build`, `md-doc sync`, `md-doc register`
- **CI-ready** — reusable GitHub Actions workflow template

---

## Installation

```bash
pip install md-doc-pipeline

# Optional: Azure File Share sync
pip install "md-doc-pipeline[azure]"

# Optional: S3 sync
pip install "md-doc-pipeline[s3]"
```

Requires Python 3.11+. WeasyPrint requires system libraries — see [WeasyPrint docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation) for platform-specific setup.

---

## Quick start

```bash
# Build PDF and DOCX from a single document
md-doc build docs/renewals/2026/binder-cover.md

# Build all documents in a directory (recursive)
md-doc build docs/renewals/2026/

# Sync built outputs to Azure
md-doc sync docs/renewals/2026/

# Generate document register
md-doc register
```

---

## Project layout

```
my-docs/
├── _meta.yml                   # Repo-level defaults (org name, outputs, sync config)
├── templates/                  # Shared reusable fragments
│   ├── aib-header.md
│   ├── confidentiality-footer.md
│   └── product-intro-binder.md
├── themes/
│   └── default/
│       └── pdf-theme.css       # WeasyPrint CSS theme
├── docs/
│   └── renewals/
│       ├── _meta.yml           # Renewal-specific defaults (product, status)
│       └── 2026/
│           ├── _meta.yml       # Year-level overrides (version, date)
│           └── binder-cover.md # Individual document with frontmatter
└── build/                      # Generated outputs (PDF, DOCX) — git-ignored
```

---

## Configuration

Configuration cascades from shallowest to deepest. Later layers override earlier ones.

**Resolution order:**
1. `_meta.yml` at repo root
2. `_meta.yml` in each directory between root and the document
3. YAML frontmatter inside the `.md` file itself

### Common config keys

```yaml
# _meta.yml or document frontmatter

title: My Document Title
product: Acme Binder — Liability
document_type: binder_cover
version: "2.0"
status: final                    # draft | final | superseded

author: Acme IB
outputs: [pdf, docx]             # Which formats to build
output_pdf: AIB-Binder-2026.pdf  # Output filename (optional, defaults to doc stem)
output_docx: AIB-Binder-2026.docx

# Sync config
sync_target: azure               # azure | s3 | local
include_md_in_share: false       # Never sync source .md files

sync_config:
  # Azure
  connection_string_env: AZURE_STORAGE_CONNECTION_STRING
  share_name: binder-docs
  remote_dir: renewals/2026

  # S3
  bucket: my-docs-bucket
  prefix: renewals/2026/

  # Local
  path: /mnt/shared/docs/renewals/2026/
```

---

## Jinja2 template composition

Document bodies are processed through Jinja2 before building. All config variables are available as template context.

### Variable substitution

```markdown
---
title: Renewal Cover Letter — {{ product }}
client: Riverside Holdings
renewal_date: 1 May 2026
---

Dear {{ client }},

We are pleased to present your renewal for **{{ product }}** effective {{ renewal_date }}.
```

### Including shared fragments

```markdown
{% include "templates/aib-header.md" %}

# {{ title }}

{% include "templates/product-intro-binder.md" %}

## Schedule of Cover

...

{% include "templates/confidentiality-footer.md" %}
```

Fragment search order:
1. Document's own directory
2. `templates/` next to the document
3. `templates/` at the repo root
4. Any extra paths passed via `--search-dir`

---

## Worked example: insurance binder renewals

See [`examples/insurance-binders/`](examples/insurance-binders/) for a full working example including:

- Repo `_meta.yml` with org defaults
- Product-level `_meta.yml`
- Individual binder cover letter with frontmatter
- Shared header/footer fragments
- Expected build output

### Directory structure

```
examples/insurance-binders/
├── _meta.yml
├── templates/
│   ├── aib-header.md
│   └── confidentiality-footer.md
└── docs/
    └── renewals/
        └── 2026/
            ├── _meta.yml
            └── riverside-holdings-binder.md
```

### Build it

```bash
cd examples/insurance-binders
md-doc build docs/renewals/2026/riverside-holdings-binder.md
# → build/docs/renewals/2026/Riverside-Holdings-Binder-2026.pdf
```

---

## CLI reference

```
md-doc build [PATH] [OPTIONS]
  PATH              .md file or directory (recursive). Defaults to cwd.
  --output-dir DIR  Override build output directory (default: build/)
  --format pdf|docx Override output format(s)
  --search-dir DIR  Extra template search directory (repeatable)

md-doc sync [PATH] [OPTIONS]
  PATH              Source directory to sync from build/. Defaults to cwd.
  --dry-run         Print what would be synced without uploading

md-doc register [OPTIONS]
  --build-dir DIR   Build output directory (default: build/)
  --out-csv FILE    CSV output path (default: document-register.csv)
  --out-md FILE     Markdown output path (default: document-register.md)
```

---

## PDF theme

The default PDF theme is a professional A4 layout with:

- Navy/blue brand palette
- Branded cover page (title, author, date)
- Running header/footer with page numbers
- Tables, code blocks, blockquotes styled for print

Place a custom CSS file at `themes/default/pdf-theme.css` in your repo root, or specify via `css_theme` in `_meta.yml`:

```yaml
css_theme: themes/my-company/pdf-theme.css
```

---

## Development

```bash
git clone <repo>
cd md-doc-pipeline
pip install -e ".[dev]"
pytest
```

### Running tests

```bash
pytest                  # all tests
pytest tests/test_renderer.py -v
```

---

## Contributing

Small, working increments preferred. Run `pytest` before committing. Follow existing code style (ruff, black, line-length 100).
