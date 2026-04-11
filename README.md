# md-doc-pipeline

A lightweight Markdown → PDF/DOCX document pipeline with cascading config, Jinja2 template composition, and pluggable cloud sync.

Built for document-heavy workflows — proposals, project reports, compliance documents, contracts — where content is structured in Markdown, assembled from reusable fragments, and published to PDF and/or DOCX.

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
md-doc build docs/projects/2026/alpha-project-report.md

# Build all documents in a directory (recursive)
md-doc build docs/projects/2026/

# Sync built outputs to Azure
md-doc sync docs/projects/2026/

# Generate document register
md-doc register
```

---

## Project layout

```
my-docs/
├── _meta.yml                      # Repo-level defaults (org name, outputs, sync config)
├── templates/                     # Shared reusable fragments
│   ├── org-header.md
│   ├── confidentiality-footer.md
│   └── section-intro.md
├── themes/
│   └── default/
│       └── _pdf-theme.css          # WeasyPrint CSS theme
├── docs/
│   └── projects/
│       ├── _meta.yml              # Project-specific defaults (product, status)
│       └── 2026/
│           ├── _meta.yml          # Year-level overrides (version, date)
│           └── project-report.md  # Individual document with frontmatter
└── build/                         # Generated outputs (PDF, DOCX) — git-ignored
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
product: Alpha Initiative — Phase 2
document_type: project_report
version: "2.0"
status: final                    # draft | final | superseded

author: Acme Corp
outputs: [pdf, docx]             # Which formats to build
output_pdf: Alpha-Report-2026.pdf  # Output filename (optional, defaults to doc stem)
output_docx: Alpha-Report-2026.docx

# Sync config
sync_target: azure               # azure | s3 | local
include_md_in_share: false       # Never sync source .md files

sync_config:
  # Azure
  connection_string_env: AZURE_STORAGE_CONNECTION_STRING
  share_name: report-docs
  remote_dir: projects/2026

  # S3
  bucket: my-docs-bucket
  prefix: projects/2026/

  # Local
  path: /mnt/shared/docs/projects/2026/
```

---

## Jinja2 template composition

Document bodies are processed through Jinja2 before building. All config variables are available as template context.

### Variable substitution

```markdown
---
title: Project Report — {{ product }}
client: Beta Systems Ltd
report_date: 1 May 2026
---

Dear {{ client }},

Please find attached the project report for **{{ product }}** as at {{ report_date }}.
```

### Including shared fragments

```markdown
{% include "templates/org-header.md" %}

# {{ title }}

{% include "templates/section-intro.md" %}

## Deliverables

...

{% include "templates/confidentiality-footer.md" %}
```

Fragment search order:
1. Document's own directory
2. `templates/` next to the document
3. `templates/` at the repo root
4. Any extra paths passed via `--search-dir`

---

## Worked example: project reports

See [`examples/project-reports/`](examples/project-reports/) for a full working example including:

- Repo `_meta.yml` with org defaults
- Project-level `_meta.yml`
- Individual project report with frontmatter
- Shared header/footer fragments
- Expected build output

### Directory structure

```
examples/project-reports/
├── _meta.yml
├── templates/
│   ├── org-header.md
│   └── confidentiality-footer.md
└── docs/
    └── projects/
        └── 2026/
            ├── _meta.yml
            └── alpha-project-report.md
```

### Build it

```bash
cd examples/project-reports
md-doc build docs/projects/2026/alpha-project-report.md
# → build/docs/projects/2026/Alpha-Project-Report-2026.pdf
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

Place a custom CSS file at `themes/default/_pdf-theme.css` in your repo root, or specify via `css_theme` in `_meta.yml`:

```yaml
css_theme: themes/my-company/_pdf-theme.css
```

---

## Development

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/blackdog308/md-doc-pipeline
cd md-doc-pipeline

# Create venv, install all deps (including dev group) and the package itself
uv sync --group dev

# Run a command inside the venv
uv run md-doc --help
```

### Running tests

```bash
uv run pytest                        # all tests
uv run pytest tests/test_renderer.py -v
```

### Linting / formatting

```bash
uv run ruff check .
uv run black --check .
uv run mypy md_doc/
```

---

## Contributing

Small, working increments preferred. Run `pytest` before committing. Follow existing code style (ruff, black, line-length 100).
