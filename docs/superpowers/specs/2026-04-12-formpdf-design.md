# Fillable PDF Forms Design

**Date:** 2026-04-12
**Status:** Approved

---

## Summary

Add support for interactive fillable PDFs by introducing a `pdf_forms: true` config key.
When set, `pdf.build()` passes `pdf_forms=True` to WeasyPrint, producing a PDF with real
AcroForm fields. The output file gets a `-form` suffix to distinguish it from regular
PDF output (`onboarding.md` → `onboarding-form.pdf`).

No new builder, no new output type, no linter changes.

---

## Architecture

### 1. `md_doc/builders/pdf.py`

One change: check `config.get("pdf_forms", False)` and pass `pdf_forms=True` to
`write_pdf()` when set.

```python
weasyprint.HTML(string=html, base_url=str(out_path.parent)).write_pdf(
    str(out_path),
    **({"pdf_forms": True} if config.get("pdf_forms") else {}),
)
```

### 2. `md_doc/cli.py`

`_resolve_output_path` appends `-form` to the stem when `pdf_forms` is set in config:

```python
# e.g. onboarding.md + pdf_forms: true → onboarding-form.pdf
stem = doc_path.stem + ("-form" if config.get("pdf_forms") else "")
```

Note: `output_pdf` is a documented config key but is not yet wired up in `cli.py` — filename
override is out of scope for this feature.

### 3. `md_doc/theme.py`

Add a form-field CSS block to `generate_base_theme()`. Key requirement: every interactive
element must have `appearance: auto` or WeasyPrint will not promote it to an AcroForm field.

```css
/* ── Form fields ─────────────────────────────────────────── */
input[type="text"],
input[type="date"],
input[type="number"],
input[type="email"],
textarea,
select {
  appearance: auto;
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

### 4. `workspace/CLAUDE.md`

New "PDF Forms" authoring section covering:
- `pdf_forms: true` config key
- Requirement to wrap fields in explicit `<form>` tags (WeasyPrint does not auto-wrap)
- Supported field types and their PDF equivalents
- `name` attribute convention (snake_case, becomes the AcroForm field name)
- Recommendation to set `cover_page: false` for forms

---

## Authoring syntax

```markdown
---
title: Staff Onboarding Form
pdf_forms: true
cover_page: false
---

# Staff Onboarding Form

<form>

**Full name** <input type="text" name="full_name" required>

**Department**
<select name="department">
  <option value="">— Select —</option>
  <option value="engineering">Engineering</option>
</select>

**Notes**
<textarea name="notes" rows="4"></textarea>

**I confirm the above is correct**
<input type="checkbox" name="confirmed"> Yes

</form>
```

### Supported field types

| HTML element | PDF field type |
|---|---|
| `<input type="text">` | Text field |
| `<input type="date">` | Text field (date hint) |
| `<input type="number">` | Text field (numeric hint) |
| `<input type="checkbox">` | Checkbox |
| `<input type="radio" name="x" value="y">` | Radio group |
| `<select>` | Dropdown |
| `<textarea>` | Multiline text |
| `<input type="submit">` | Submit button |

`name` attribute → PDF field name. Use `snake_case`.

---

## Data flow

```
.md source
  → config.load_config()           # picks up pdf_forms: true
  → renderer.render()              # Jinja2 pass, HTML form elements pass through untouched
  → builders/pdf.build()           # pdf_forms flag checked here
      → _resolve_css()             # same CSS cascade as regular PDF
      → _build_html()              # same HTML assembly
      → weasyprint.write_pdf(pdf_forms=True)
  → onboarding-form.pdf
```

---

## Error handling

No new error cases. WeasyPrint silently ignores form elements that lack `name` attributes
or `appearance: auto` — they render as static content. No validation of form markup is
performed by the pipeline; authors are responsible for correct HTML form syntax.

---

## Testing (TDD order)

### `tests/test_pdf_builder.py` additions

| Test | What it verifies |
|---|---|
| `test_pdf_forms_flag_passed_to_weasyprint` | `write_pdf` called with `pdf_forms=True` when config has `pdf_forms: true` |
| `test_pdf_forms_not_passed_when_false` | `write_pdf` called without `pdf_forms` kwarg when flag absent |
| `test_pdf_forms_output_is_valid_pdf` | File starts with `%PDF-` magic bytes |

### `tests/test_cli.py` / `tests/test_cli_new.py` additions

| Test | What it verifies |
|---|---|
| `test_formpdf_output_has_form_suffix` | Output path is `stem-form.pdf` when `pdf_forms: true` |

### `tests/test_theme.py` additions

| Test | What it verifies |
|---|---|
| `test_generated_theme_includes_form_field_css` | `generate_base_theme()` output contains `appearance: auto` |

---

## Implementation order

1. **Theme** — add form CSS block to `generate_base_theme()` (1 test)
2. **Builder** — add `pdf_forms` flag check to `pdf.build()` (2 tests)
3. **CLI** — add `-form` suffix logic to `_resolve_output_path` (2 tests)
4. **Docs** — add PDF Forms section to `workspace/CLAUDE.md`

---

## Files to modify

| File | Change |
|---|---|
| `md_doc/builders/pdf.py` | Add `pdf_forms` flag to `write_pdf()` call |
| `md_doc/cli.py` | Add `-form` suffix to output path when `pdf_forms: true` |
| `md_doc/theme.py` | Add form field CSS block to `generate_base_theme()` |
| `workspace/CLAUDE.md` | Add PDF Forms authoring section |
| `tests/test_pdf_builder.py` | Add `pdf_forms` flag tests |
| `tests/test_theme.py` | Add form CSS presence test |

---

## Out of scope

- Form submission endpoint wiring (`<form action="...">`) — document concern, not pipeline
- Pre-filling fields from data — use `.dotx` mail merge for that
- Field validation beyond HTML attributes — WeasyPrint honours `required` and `maxlength` natively
- Flattening a filled form back to static PDF — handled externally
- `formpdf` as a separate output type — superseded by this design
