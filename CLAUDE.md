# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (uses uv package manager)
uv sync --group dev

# CLI usage
uv run md-doc build [PATH]       # Build PDFs/DOCX from Markdown
uv run md-doc sync [PATH]        # Push outputs to remote storage
uv run md-doc register [PATH]    # Generate document registry

# Tests
uv run pytest                    # All tests
uv run pytest tests/test_renderer.py -v  # Single file

# Linting / formatting
uv run ruff check .
uv run black --check .
uv run mypy md_doc/
```

## Architecture

md-doc-pipeline converts Markdown files into PDF/DOCX documents with cascading configuration, Jinja2 template composition, and pluggable cloud sync.

### Merge field syntax

`[[field_name]]` in Markdown source becomes a Word `«MERGEFIELD»` in `.dotx` output. This is intentionally distinct from Jinja2 `{{ }}` so both can coexist:

```markdown
Dear [[contact_name]],          ← Word MERGEFIELD in .dotx
This is version {{ version }}.  ← resolved from _meta.yml at build time
```

### Cover page config

```yaml
cover_page: true   # default — applies to pdf and dotx; set false to omit
```

### Core pipeline (per document)

1. **Config resolution** (`config.py`) — walks filesystem from repo root to document directory, shallow-merging each `_meta.yml` encountered; document YAML frontmatter has highest precedence. Repo root is auto-detected via `.git/` or `pyproject.toml`.

2. **Rendering** (`renderer.py`) — strips frontmatter (preserved verbatim), processes Markdown body through Jinja2. Template fragment search order: doc dir → `doc/templates/` → ancestor `templates/` dirs (deepest first) → repo-root `templates/`. A custom `_MarkdownLoader` handles `{% include %}` resolution.

3. **Building** (`builders/`):
   - `pdf.py` — Markdown → HTML → PDF via WeasyPrint. Resolves CSS theme with same cascading search (doc dir → ancestors → repo → bundled `themes/default/_pdf-theme.css`). Extracts first H1 as cover page title when `cover_page: true`.
   - `docx.py` — Markdown → HTML → python-docx Document via a custom `_DocxBuilder` HTML walker. For copy-to-email use.
   - `dotx.py` — Extends `_DocxBuilder`; converts `[[field_name]]` markers to Word MERGEFIELD XML. Patches the saved file's ZIP content type from `.docx` → `.dotx`. For downstream mail merge use.

4. **Syncing** (`sync/`) — discovers `*.pdf`, `*.docx` (optionally `*.md`) outputs and uploads via the configured backend: `azure_files.py` (Azure File Share), `s3.py` (AWS S3), or `local.py`. Directory structure is preserved relative to the search root.

5. **Registering** (`register.py`) — scans build outputs, resolves metadata from config cascade, writes `register.json` / `register.md` / `register.csv`.

### Configuration keys (in `_meta.yml` or document frontmatter)

```yaml
title, product, document_type, version, status, author
outputs: [pdf, docx]          # default: [pdf]
output_pdf: Custom-Name.pdf   # override output filename
css_theme: themes/custom/theme.css
include_md_in_share: false
sync_target: azure | s3 | local
sync_config: { ... }          # backend-specific connection params
```

### Output placement

- Default: alongside the source `.md` file
- With `--output DIR`: mirrors the source tree under `DIR`

### WeasyPrint system dependencies

PDF generation requires system libraries (`libpango`, `libgdk-pixbuf`, Cairo). On Linux install via `apt install weasyprint` or the equivalent for your distro.

### Optional package extras

```bash
pip install "md-doc-pipeline[azure]"   # azure-storage-file-share
pip install "md-doc-pipeline[s3]"      # boto3
```
