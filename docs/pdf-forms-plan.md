# PDF Forms Implementation Plan

## What we're building

A new `formpdf` output type that produces interactive, fillable PDF forms from Markdown documents. Authors embed HTML form elements directly in their Markdown — WeasyPrint 68.x converts them into real AcroForm fields that recipients can fill in Adobe Reader, Preview, or any standards-compliant PDF viewer.

---

## How WeasyPrint handles this

WeasyPrint 68.x supports AcroForms natively. The only change to the render call is one flag:

```python
weasyprint.HTML(string=html, base_url=...).write_pdf(path, pdf_forms=True)
```

With `pdf_forms=True`, any HTML form element with a `name` attribute and `appearance: auto` in CSS becomes a real interactive PDF field. No extra libraries needed.

---

## Authoring syntax

Authors write standard HTML form elements inside their Markdown. Python-Markdown passes raw HTML through untouched.

```markdown
---
title: Staff Onboarding Form
outputs: [formpdf]
cover_page: false
---

# Staff Onboarding Form

## Personal Details

<form>

**Full name** <input type="text" name="full_name" required>

**Start date** <input type="date" name="start_date">

**Department**
<select name="department">
  <option value="">— Select —</option>
  <option value="engineering">Engineering</option>
  <option value="sales">Sales</option>
  <option value="marketing">Marketing</option>
</select>

**Notes**
<textarea name="notes" rows="4"></textarea>

**I confirm the above is correct**
<input type="checkbox" name="confirmed"> Yes

</form>
```

### Supported field types

| HTML element | PDF field type | Notes |
|---|---|---|
| `<input type="text">` | Text field | `maxlength`, `required` honoured |
| `<input type="date">` | Text field | Visual date hint |
| `<input type="number">` | Text field | Numeric hint |
| `<input type="checkbox">` | Checkbox | Checked state preserved |
| `<input type="radio" name="x" value="y">` | Radio group | All same `name` = one group |
| `<select>` | Dropdown | `multiple` = list box |
| `<textarea>` | Multiline text | `rows` controls height visually |
| `<input type="submit">` | Submit button | `form action` sets endpoint |

### Naming convention

The `name` attribute becomes the PDF field name. Use `snake_case` — it appears in the AcroForm dictionary and may be consumed by form processing systems.

---

## Architecture changes

### 1. New builder: `md_doc/builders/formpdf.py`

Thin wrapper around `pdf.py`. Identical pipeline except:
- Passes `pdf_forms=True` to `write_pdf()`
- Does **not** strip leading H1 even when `cover_page: true` (forms rarely want covers — default `cover_page: false` for `formpdf`)
- Adds a `<form>` wrapper around the body HTML if no `<form>` tags are present, so WeasyPrint activates field processing

```python
# Minimal sketch — implement with TDD
def build(rendered_md, config, out_path, *, repo_root=None, doc_path=None):
    # Same as pdf.build() but:
    weasyprint.HTML(string=html, base_url=...).write_pdf(
        str(out_path),
        pdf_forms=True,
    )
```

### 2. CLI: add `formpdf` to valid formats

`md_doc/cli.py` — two places:

```python
# --format option choices
type=click.Choice(["pdf", "docx", "dotx", "formpdf", "all"], ...)

# build dispatch
elif format_name == "formpdf":
    from .builders.formpdf import build as build_formpdf
    build_formpdf(rendered_md, config, out_path, doc_path=doc_path)
```

### 3. Config key: `output_formpdf`

Follows the same pattern as `output_pdf`:

```yaml
output_formpdf: Staff-Onboarding-Form.pdf
```

Handled in `_resolve_output_path()` — no changes needed there; the `.formpdf` extension maps to the file.

### 4. CSS theme additions: form field styles

Add a `_form-fields` section to `md_doc/theme.py`'s CSS template. These styles control the visual appearance of form fields in both the browser preview and the rendered PDF.

```css
/* ── Form fields ─────────────────────────────────────────── */
form {
  display: block;
}

input[type="text"],
input[type="date"],
input[type="number"],
input[type="email"],
textarea,
select {
  appearance: auto;           /* required — tells WeasyPrint to make interactive */
  display: inline-block;
  width: 100%;
  padding: 4pt 6pt;
  margin: 2pt 0 8pt 0;
  border: 1pt solid $muted;
  border-radius: 2pt;
  font-family: $body_font;
  font-size: 10pt;
  color: $body_text;
  background: #fafafa;
}

input[type="checkbox"],
input[type="radio"] {
  appearance: auto;
  width: auto;
  margin-right: 4pt;
}

textarea {
  resize: vertical;
  min-height: 48pt;
}

select {
  background: #fafafa;
}

input[type="submit"],
button[type="submit"] {
  appearance: auto;
  display: inline-block;
  padding: 6pt 18pt;
  background: $primary;
  color: white;
  border: none;
  border-radius: 2pt;
  font-size: 10pt;
  cursor: pointer;
}
```

These styles live in `generate_base_theme()` in `md_doc/theme.py`. Override theme files inherit them via `@import` and can redefine colours using the same `$primary` / `$muted` variables.

### 5. Linter update: accept `formpdf` as valid output format

`md_doc/linter.py`:

```python
_VALID_FORMATS: frozenset[str] = frozenset({"pdf", "docx", "dotx", "formpdf"})
```

### 6. `workspace/CLAUDE.md` additions

Add a "PDF forms" section explaining the authoring syntax, the `outputs: [formpdf]` key, and the `name` attribute convention.

---

## Test plan (TDD order)

All tests written before production code. Follow red-green-refactor strictly.

### `tests/test_formpdf_builder.py`

| Test | What it verifies |
|---|---|
| `test_produces_pdf_file` | `build()` writes a `.pdf` file at `out_path` |
| `test_output_is_valid_pdf` | File starts with `%PDF-` magic bytes |
| `test_cover_page_false_by_default` | `cover_page` defaults to `False` for `formpdf` (unlike regular `pdf`) |
| `test_cover_page_true_when_set` | Respects explicit `cover_page: true` in config |
| `test_uses_css_theme` | `_resolve_css` called; `_pdf-theme.css` path resolved |
| `test_inherits_pdf_builder_css_cascade` | CSS theme resolved from ancestor dirs same as `pdf.py` |

### `tests/test_formpdf_cli.py`

| Test | What it verifies |
|---|---|
| `test_formpdf_format_accepted` | `--format formpdf` doesn't raise an error |
| `test_formpdf_in_outputs_config_builds` | `outputs: [formpdf]` in config triggers `formpdf` builder |
| `test_output_file_has_pdf_extension` | Output file is `.pdf`, not `.formpdf` |

### `tests/test_linter.py` additions

| Test | What it verifies |
|---|---|
| `test_formpdf_is_valid_output_format` | `outputs: [formpdf]` produces no linter errors |

### `tests/test_theme.py` additions

| Test | What it verifies |
|---|---|
| `test_generated_theme_includes_form_field_css` | `generate_base_theme()` output contains `appearance: auto` |

---

## Implementation order

1. **Linter** — add `formpdf` to `_VALID_FORMATS` (1 line, 1 test)
2. **Theme** — add form field CSS block to `generate_base_theme()` template
3. **Builder** — `builders/formpdf.py` as a thin wrapper
4. **CLI** — add `formpdf` to choices, dispatch to new builder
5. **Docs** — update `workspace/CLAUDE.md` authoring section
6. **README** — add `formpdf` to output types table and CLI reference

---

## Files to create / modify

| File | Action |
|---|---|
| `md_doc/builders/formpdf.py` | **Create** |
| `md_doc/cli.py` | Modify — add `formpdf` to `--format` choices and `build` dispatch |
| `md_doc/linter.py` | Modify — add `formpdf` to `_VALID_FORMATS` |
| `md_doc/theme.py` | Modify — add form field CSS block to `generate_base_theme()` |
| `tests/test_formpdf_builder.py` | **Create** |
| `tests/test_formpdf_cli.py` | **Create** |
| `workspace/CLAUDE.md` | Modify — add PDF forms authoring section |
| `README.md` | Modify — add `formpdf` to output types and CLI reference |
| `CLAUDE.md` | Already updated |

---

## Out of scope (not in this plan)

- Form submission endpoint wiring (POST to a URL via `<form action="...">`) — WeasyPrint supports it but it's a document concern, not pipeline concern
- Pre-filling form fields from data — that's what `.dotx` mail merge is for; forms are blank-at-delivery
- Form field validation rules beyond HTML attributes — WeasyPrint honours `required` and `maxlength` natively
- Flattening a filled form back to a static PDF — out of scope, handled externally
