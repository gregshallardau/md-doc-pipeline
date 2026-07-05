---
title: PDF Forms Guide
author: md-doc-pipeline
date: April 2026
outputs: [pdf]
cover_page: true
cover_label: Guide
cover_bar: true
cover_bar_position: top
cover_stripe: false
cover_text_align: left
cover_divider: true
---

# PDF Forms Guide

A complete guide to building interactive fillable PDF forms with md-doc-pipeline. Covers every field type, layout pattern, and best practice.

## Getting Started

### Minimum setup

Add `pdf_forms: true` to your document frontmatter. That's it — the pipeline handles the rest.

```yaml
---
title: My Form
outputs: [pdf]
pdf_forms: true
cover_page: false
---
```

The output file gets an automatic `-form` suffix: `my-form.md` becomes `my-form-form.pdf`.

### The golden rule

**Every form field must be inside a `<form>` tag.** Fields outside `<form>` render as static, non-interactive content. Open the form tag early, close it at the end.

```markdown
# My Form

<form markdown="1">

## Section One

... fields here ...

## Section Two

... more fields here ...

</form>
```

The `markdown="1"` attribute tells the Markdown processor to keep rendering headings, bold text, lists, and other Markdown syntax inside the HTML block. Without it, everything inside `<form>` becomes raw text.

---

## Field Types

### Text input

A single-line text field. The most common field type.

```html
<strong>Full name</strong> *
<input type="text" name="full_name" required maxlength="100">
```

Attributes:
- `name` — field name in the PDF (required, use snake_case)
- `required` — field must be filled before submission
- `maxlength` — maximum character count

### Email input

Identical to text, but hints at email format in some PDF readers.

```html
<strong>Email</strong>
<input type="email" name="email" required>
```

### Date input

Some PDF readers show a date picker; others treat it as a text field.

```html
<strong>Start date</strong>
<input type="date" name="start_date">
```

### Number input

Hints at numeric input. `min` and `max` may be honoured by some readers.

```html
<strong>Years of experience</strong>
<input type="number" name="years" min="0" max="50">
```

### Dropdown (select)

A dropdown menu with predefined options.

```html
<strong>Department</strong>
<select name="department">
  <option value="">— Select —</option>
  <option value="engineering">Engineering</option>
  <option value="sales">Sales</option>
  <option value="marketing">Marketing</option>
</select>
```

Always include a blank/placeholder option as the first choice.

### Textarea (multiline text)

A multi-line text area. `rows` controls the visible height.

```html
<strong>Comments</strong>
<textarea name="comments" rows="4"></textarea>
```

### Checkbox

A single checkbox for yes/no or agreement fields.

```html
<div>
<label><input type="checkbox" name="agree_terms" required> I agree to the terms and conditions</label>
</div>
```

### Radio buttons (single choice)

A group of mutually exclusive options. All radios with the same `name` form one group — selecting one deselects the others.

**Vertical layout** (one per line):

```html
<div>
<label><input type="radio" name="priority" value="high"> High</label><br>
<label><input type="radio" name="priority" value="medium"> Medium</label><br>
<label><input type="radio" name="priority" value="low"> Low</label>
</div>
```

**Horizontal layout** (all on one row):

```html
<div>
<label style="display: inline; margin-right: 12pt;"><input type="radio" name="priority" value="high"> High</label>
<label style="display: inline; margin-right: 12pt;"><input type="radio" name="priority" value="medium"> Medium</label>
<label style="display: inline;"><input type="radio" name="priority" value="low"> Low</label>
</div>
```

### Submit button

Optional — adds a submit action to the form.

```html
<input type="submit" value="Submit Form">
```

---

## Layout Patterns

### Single column (default)

Fields stack vertically, each taking the full width. This is the default and works for most forms.

```html
<strong>First name</strong>
<input type="text" name="first_name">

<strong>Last name</strong>
<input type="text" name="last_name">

<strong>Email</strong>
<input type="email" name="email">
```

### Two columns

Use an HTML table with invisible borders to place fields side by side.

```html
<table style="border: none; width: 100%;">
<tr style="background: none;">
<td style="border: none; width: 50%; padding: 0 8pt 0 0; vertical-align: top;">
<strong>First name</strong><br>
<input type="text" name="first_name">
</td>
<td style="border: none; width: 50%; padding: 0 0 0 8pt; vertical-align: top;">
<strong>Last name</strong><br>
<input type="text" name="last_name">
</td>
</tr>
</table>
```

### Three columns

Same pattern, with `width: 33%` on each cell.

```html
<table style="border: none; width: 100%;">
<tr style="background: none;">
<td style="border: none; width: 33%; padding: 0 8pt 0 0; vertical-align: top;">
<strong>Account name</strong><br>
<input type="text" name="account_name">
</td>
<td style="border: none; width: 33%; padding: 0 8pt; vertical-align: top;">
<strong>BSB</strong><br>
<input type="text" name="bsb" maxlength="7">
</td>
<td style="border: none; width: 33%; padding: 0 0 0 8pt; vertical-align: top;">
<strong>Account number</strong><br>
<input type="text" name="account_number" maxlength="12">
</td>
</tr>
</table>
```

### Mixed widths

Vary the `width` percentages for unequal columns.

```html
<table style="border: none; width: 100%;">
<tr style="background: none;">
<td style="border: none; width: 70%; padding: 0 8pt 0 0; vertical-align: top;">
<strong>Street address</strong><br>
<input type="text" name="street">
</td>
<td style="border: none; width: 30%; padding: 0 0 0 8pt; vertical-align: top;">
<strong>Postcode</strong><br>
<input type="text" name="postcode" maxlength="4">
</td>
</tr>
</table>
```

### Multiple rows in a grid

Add more `<tr>` rows for a full grid of fields.

```html
<table style="border: none; width: 100%;">
<tr style="background: none;">
<td style="border: none; width: 50%; padding: 0 8pt 4pt 0; vertical-align: top;">
<strong>First name</strong><br>
<input type="text" name="first_name">
</td>
<td style="border: none; width: 50%; padding: 0 0 4pt 8pt; vertical-align: top;">
<strong>Last name</strong><br>
<input type="text" name="last_name">
</td>
</tr>
<tr style="background: none;">
<td style="border: none; width: 50%; padding: 4pt 8pt 0 0; vertical-align: top;">
<strong>Email</strong><br>
<input type="email" name="email">
</td>
<td style="border: none; width: 50%; padding: 4pt 0 0 8pt; vertical-align: top;">
<strong>Phone</strong><br>
<input type="text" name="phone">
</td>
</tr>
</table>
```

### Horizontal checkboxes

Same inline pattern as horizontal radios.

```html
<div>
<label style="display: inline; margin-right: 12pt;"><input type="checkbox" name="skill_python"> Python</label>
<label style="display: inline; margin-right: 12pt;"><input type="checkbox" name="skill_js"> JavaScript</label>
<label style="display: inline; margin-right: 12pt;"><input type="checkbox" name="skill_go"> Go</label>
<label style="display: inline;"><input type="checkbox" name="skill_rust"> Rust</label>
</div>
```

---

## Sections and Visual Structure

### Section headings

Use standard Markdown headings — they render normally inside `<form markdown="1">`.

```markdown
<form markdown="1">

## Personal Details

... fields ...

## Employment Details

... fields ...

</form>
```

### Horizontal rules

Use `---` between sections for visual separation.

```markdown
## Personal Details

... fields ...

---

## Employment Details

... fields ...
```

### Field labels

Use `<strong>` tags for field labels. Add `*` to indicate required fields.

```html
<strong>Full name</strong> *
<input type="text" name="full_name" required>
```

### Help text

Add small explanatory text below a label using a paragraph or `<small>` tag.

```html
<strong>Tax File Number</strong>
<small style="display: block; color: #7f8c9a; font-size: 8pt;">Optional — provide if you want tax withheld at the standard rate</small>
<input type="text" name="tfn" maxlength="11">
```

---

## Best Practices

1. **Always open `<form markdown="1">` early** — right after any intro text, before the first field.
2. **Every field needs a `name` attribute** — it becomes the PDF field name. Use `snake_case`.
3. **Set `cover_page: false`** for most forms — forms rarely need a cover page.
4. **Use `required` on mandatory fields** — PDF readers will flag unfilled required fields.
5. **Wrap radio and checkbox groups in `<div>`** — prevents Markdown from wrapping them in `<p>` tags which can break rendering.
6. **Use `<label>` tags around radio/checkbox options** — improves clickability in PDF readers.
7. **Include a blank first option in dropdowns** — `<option value="">— Select —</option>` prevents accidental pre-selection.
8. **Test in multiple PDF readers** — Adobe Acrobat, Preview (macOS), Chrome's built-in viewer, and Firefox all handle forms slightly differently.
9. **Use tables for multi-column layouts** — `display: flex` and `display: grid` are not reliable in WeasyPrint. Tables with invisible borders are the safest approach.
10. **Keep forms on one page when possible** — if the form is long, WeasyPrint handles page breaks well, but test the output to make sure fields aren't split awkwardly.

---

## Common Issues

### Fields aren't interactive

- Check that all fields are inside `<form>` tags
- Check that `pdf_forms: true` is in the frontmatter
- Check that every field has a `name` attribute

### Markdown not rendering inside form

- Add `markdown="1"` to the `<form>` tag: `<form markdown="1">`
- For inline elements (bold, italic), use HTML tags (`<strong>`, `<em>`) as a fallback

### Radio buttons rendering as text fields

- Wrap in `<div>` and `<label>` tags
- Ensure the CSS has explicit sizing for radio/checkbox:
  ```css
  input[type="radio"], input[type="checkbox"] {
    appearance: auto;
    width: 12pt;
    height: 12pt;
    display: inline-block;
  }
  ```

### Fields stretching to full width

- For radio/checkbox: ensure the CSS sets `width: 12pt` not `width: auto` or `width: 100%`
- For text fields in multi-column layouts: the `width: 100%` is correct — it fills the table cell

### Multi-column layout not working

- Use `<table>` with inline styles, not CSS flex/grid
- Set `style="border: none;"` on the table, tr, and each td
- Set `style="background: none;"` on `<tr>` to prevent zebra striping from the theme

---

## Field Reference

| HTML | PDF Field | Key Attributes |
|------|-----------|----------------|
| `<input type="text">` | Text field | `name`, `required`, `maxlength`, `readonly` |
| `<input type="email">` | Text field | `name`, `required` |
| `<input type="date">` | Date field | `name`, `required` |
| `<input type="number">` | Numeric field | `name`, `min`, `max`, `required` |
| `<input type="checkbox">` | Checkbox | `name`, `required` |
| `<input type="radio">` | Radio group | `name`, `value`, `required` (same name = one group) |
| `<select>` | Dropdown | `name`, `required` |
| `<textarea>` | Multiline text | `name`, `rows`, `required` |
| `<input type="submit">` | Submit button | `value` (button text) |

---

## The `?[...]` shorthand (recommended)

Instead of raw HTML you can write fields with a compact marker. The shorthand
produces the same interactive fields, adds insurance-form layout constructs,
gets linted (`md-doc lint` catches typo'd types, duplicate names, and a
missing `pdf_forms: true`), **and maps to fillable Word form fields in
`.dotx` output** — one source, fillable PDF *and* fillable Word template.

### Field types

```markdown
?[text: full_name, required]            text input (also: email, date, number, tel, url)
?[text: abn, maxlength=14]              maxlength carries into the PDF
?[text: quote_ref, readonly, value=Q-1024]   prefilled + locked
?[text: email, title=Where documents are sent]   title= becomes the hover tooltip
?[textarea: notes, rows=4]              multiline text
?[checkbox: agree, label=I agree]       single checkbox (+ checked to pre-tick)
?[yesno: cover_required]                Yes/No checkbox pair (fields <name>_yes / <name>_no)
?[select: region | -- Select -- | North | South]   dropdown
?[radio-inline: priority | Low | Medium | High]    radio group
?[signature: signed_by]                 signature line
?[submit Send]                          submit button
```

### Layout constructs

**Bordered field grid** (`?[box]`) — the insurance-application look: every
line is a row, cells split on `|`, labels and `*hints*` live inside the
bordered cells, and inputs fill the remaining space:

```markdown
?[box]
**Insured Name** *Including any registered business name* ?[text: insured_name]
**City** ?[text: city] | **State** ?[text: state] | **Post Code** ?[text: post_code]
?[/box]

?[box: widths=72,28]
Do you require cover for agistment? *If No, go to Section 8.* | ?[yesno: agistment]
What is the maximum value horse on agistment? | $ ?[number: max_value]
?[textarea: further_details, rows=3]
?[/box]
```

`widths=` fixes column proportions; rows with fewer cells span the full grid.

**Side-by-side fields without borders** (`?[row]`):

```markdown
?[row]
?[signature: applicant] | **Date** ?[date: signed_on]
?[/row]
```

**Fillable cells in ordinary markdown tables** — put a field in a cell and it
renders borderless, filling the cell:

```markdown
| Activity | % of turnover | $ amount |
|:---------|:--------------|:---------|
| Agistment | ?[number: agistment_pct] | ?[number: agistment_amt] |
```

### What actually reaches the PDF (verified on WeasyPrint 68.x)

| Attribute | Carried by WeasyPrint | md-doc adds it |
|-----------|----------------------|----------------|
| `name`, `value`, `checked`, `maxlength` | ✅ native | — |
| `required` | ❌ dropped | ✅ `/Ff` Required flag |
| `readonly` | ❌ dropped | ✅ `/Ff` ReadOnly flag |
| `title` (tooltip) | ❌ dropped | ✅ `/TU` (hover text + screen readers) |
| `<option selected>` default | ❌ dropped | ✅ `/V` on the dropdown |

md-doc patches the missing ones into the PDF automatically (for both the
shorthand and raw-HTML forms), so `required`/`readonly`/`title` behave as
documented in any AcroForm viewer.

### Word output

- **`.dotx`** — `?[...]` fields become real Word form fields: text-ish types →
  Text Form Fields, `checkbox`/`yesno` → legacy checkboxes (FORMCHECKBOX),
  `select`/`radio` → dropdowns (FORMDROPDOWN). Protect the template for
  filling in Word (Review → Restrict Editing → Filling in forms).
- **`.docx`** — fields render as `________` fill-in lines for print-and-write.
