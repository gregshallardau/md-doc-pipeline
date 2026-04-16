# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

```
workspace/          ← all live client/company projects go here
  acme/
  blueshift/
examples/           ← reference examples, not production documents
md_doc/             ← pipeline source code
tests/
```

Build a specific company: `md-doc build workspace/acme/`
Build everything: `md-doc build workspace/`

`md-doc build` without a path defaults to `.` (current directory) — run from a project folder or pass the path explicitly.

## Commands

```bash
# Install dependencies (uses uv package manager)
uv sync --group dev

# Lint (fast pre-build check)
uv run md-doc lint workspace/acme/           # lint one company
uv run md-doc lint workspace/                # lint everything

# Build
uv run md-doc build workspace/acme/          # one company
uv run md-doc build workspace/               # all workspace projects
uv run md-doc build workspace/acme/ --format dotx  # merge templates only

# Scaffold
uv run md-doc new folder clients/acme --in workspace/blueshift/  # new folder + _meta.yml
uv run md-doc new doc proposal --in workspace/blueshift/clients/acme/  # new .md

# Fields
uv run md-doc fields workspace/blueshift/clients/acme/  # show available [[fields]]

# Theme
uv run md-doc theme init workspace/acme/     # full branded theme
uv run md-doc theme override workspace/acme/clients/stormfront/  # colour override

# Other
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
   - `pdf.py` — Markdown → HTML → PDF via WeasyPrint. Resolves CSS theme with same cascading search (doc dir → ancestors → repo root). If no `_pdf-theme.css` found anywhere, auto-generates one at repo root from built-in defaults. Extracts first H1 as cover page title when `cover_page: true`. Key call: `weasyprint.HTML(...).write_pdf(path)`.
   - PDF forms — Add `pdf_forms: true` to any document's frontmatter or parent `_meta.yml` to produce interactive fillable PDFs. The standard `pdf.py` builder passes `pdf_forms=True` to WeasyPrint 68.x, which natively supports AcroForm fields. HTML `<input>`, `<select>`, `<textarea>` elements become real interactive fields. Output file gets a `-form` suffix: `onboarding.md` → `onboarding-form.pdf`. See `workspace/CLAUDE.md` for authoring guidance.
   - `docx.py` — Markdown → HTML → python-docx Document via a custom `_DocxBuilder` HTML walker. For copy-to-email use.
   - `dotx.py` — Extends `_DocxBuilder`; converts `[[field_name]]` markers to Word MERGEFIELD XML. Patches the saved file's ZIP content type from `.docx` → `.dotx`. For downstream mail merge use.

4. **Syncing** (`sync/`) — discovers `*.pdf`, `*.docx` (optionally `*.md`) outputs and uploads via the configured backend: `azure_files.py` (Azure File Share), `s3.py` (AWS S3), or `local.py`. Directory structure is preserved relative to the search root.

5. **Registering** (`register.py`) — scans build outputs, resolves metadata from config cascade, writes `register.json` / `register.md` / `register.csv`.

### Merge field schema (`_merge_fields.yml`)

Place `_merge_fields.yml` at any directory level to document available `[[fields]]`. Files cascade additively — deeper levels add to parent fields. Shallower definitions are overridden by deeper ones for the same key.

```yaml
# workspace/acme/_merge_fields.yml
contact_name: Full name of the primary contact
company: Client company name

# workspace/acme/clients/stormfront/_merge_fields.yml
account_manager: Assigned account manager for this client
```

Use `md-doc fields [DIR]` to see all resolved fields at a given level. `config.load_merge_fields(doc_path)` returns the full merged dict.

### Configuration keys (in `_meta.yml` or document frontmatter)

```yaml
title, product, document_type, version, status, author
outputs: [pdf, docx]          # default: [pdf]
                               # valid values: pdf | docx | dotx
output_pdf: Custom-Name.pdf   # override output filename
pdf_forms: true               # enable interactive form fields in PDF (uses -form.pdf suffix)
pdf_theme: path/to/custom/_pdf-theme.css
cover_page: true              # default true — set false to omit cover
cover_label: Report           # text above the title on cover page (default: "Report")
header_logo: assets/logo.png  # logo image in page header (resolved doc dir → ancestors → repo root)
header_logo_position: right   # left | center | right (default: right)
header_text: "Company Name"   # text in page header
header_text_position: left    # left | center | right (default: left)
include_md_in_share: false
sync_target: azure | s3 | local
sync_config: { ... }          # backend-specific connection params
```

### Output placement

- Default: alongside the source `.md` file
- With `--output DIR`: mirrors the source tree under `DIR`

### WeasyPrint PDF forms — key facts for implementation

WeasyPrint 68.x supports interactive AcroForm PDF fields natively. No extra libraries needed.

- Pass `pdf_forms=True` to `write_pdf()`: `weasyprint.HTML(...).write_pdf(path, pdf_forms=True)`
- HTML `<input type="text" name="x">` → `/Tx` text field
- HTML `<input type="checkbox" name="x">` → `/Btn` checkbox
- HTML `<input type="radio" name="x" value="y">` → `/Btn` radio group
- HTML `<select name="x"><option>…</option></select>` → `/Ch` dropdown
- HTML `<textarea name="x">` → `/Tx` multiline text field
- HTML `<button type="submit">` / `<input type="submit">` → submit action field
- The `name` attribute becomes the PDF field name (use snake_case)
- `required`, `maxlength`, `readonly` HTML attributes are honoured
- CSS `appearance: auto` must be set on form elements for WeasyPrint to render them as interactive fields
- CSS controls visual appearance — form field styles should live in `_pdf-theme.css`

### WeasyPrint system dependencies

PDF generation requires system libraries (`libpango`, `libgdk-pixbuf`, Cairo). On Linux install via `apt install weasyprint` or the equivalent for your distro.

### Optional package extras

```bash
pip install "md-doc-pipeline[azure]"   # azure-storage-file-share
pip install "md-doc-pipeline[s3]"      # boto3
```
