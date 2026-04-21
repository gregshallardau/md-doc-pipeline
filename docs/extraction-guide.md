# Document Extraction Guide

The `md-doc extract` command converts PDF and DOCX files to Markdown snippets, perfect for:
- Extracting reusable content from external documents
- Converting proposals into template fragments
- Breaking down multi-page contracts into manageable sections
- Building a library of common text blocks

---

## Basic Usage

```bash
md-doc extract <FILE> [OPTIONS]
```

### Minimal example

```bash
md-doc extract my-proposal.docx
```

Output: `templates/my-proposal.md` (default destination)

### Custom destination

```bash
md-doc extract integration-guide.pdf --dest snippets/
```

Output: `snippets/integration-guide.md`

---

## Examples

### Extract a DOCX proposal into templates

```bash
md-doc extract workspace/acme/proposals/vendor-proposal.docx --dest workspace/acme/templates/
```

Result: `workspace/acme/templates/vendor-proposal.md` is created with all the proposal content extracted and ready to include in other documents.

Use it in other documents with the include directive in your Markdown.

### Extract PDF form into snippets folder

```bash
md-doc extract /downloads/intake-form.pdf --dest workspace/acme/snippets/
```

Result: `workspace/acme/snippets/intake-form.md` — reusable form content.

### Extract contract and customize

```bash
md-doc extract contract-template.docx --dest workspace/acme/legal/
# Edit workspace/acme/legal/contract-template.md as needed
# Include in DOTX merge templates with an include directive
```

---

## Workflow: Build a reusable template library

1. Collect source documents (PDFs, Word docs from clients, vendors, etc.)
2. Extract each one to a destination folder:
   ```bash
   md-doc extract client-proposal.docx --dest workspace/acme/clients/stormfront/snippets/
   md-doc extract legal-disclaimer.pdf --dest workspace/acme/templates/legal/
   ```
3. Edit the extracted Markdown as needed (clean up formatting, fix lists, etc.)
4. Use the include directive to compose larger documents. Create a Markdown file with include statements to reference:
   - `clients/stormfront/snippets/client-proposal.md`
   - `templates/legal/legal-disclaimer.md`
5. Build the final document:
   ```bash
   md-doc build workspace/acme/
   ```

---

## Supported Formats

| Format | Supported | Notes |
|---|---|---|
| **PDF** | ✅ Yes | Text extraction; images and complex layouts convert to text descriptions |
| **DOCX** | ✅ Yes | Full content including tables, lists, formatting |
| **Other** | ❌ No | Only PDF and DOCX are supported |

---

## Output Behavior

### Filename

Source file name is preserved with `.md` extension:

| Source | Destination | Output file |
|---|---|---|
| `proposal.docx` | `templates/` | `templates/proposal.md` |
| `form.pdf` | `snippets/` | `snippets/form.md` |
| `contract.docx` | `.` (current dir) | `contract.md` |

### Folder creation

If the destination folder doesn't exist, it is created automatically:

```bash
md-doc extract report.pdf --dest workspace/acme/reports/
# Creates workspace/acme/reports/ if missing, then saves to workspace/acme/reports/report.md
```

---

## Tips

- **Extract in bulk:** Run multiple extracts in a loop:
  ```bash
  for file in downloads/*.pdf; do
    md-doc extract "$file" --dest workspace/acme/snippets/
  done
  ```

- **Clean up extracted content:** Extraction converts PDFs and Word docs to Markdown, but you may need to:
  - Fix table formatting (WeasyPrint may render tables differently)
  - Remove extraneous whitespace
  - Add frontmatter metadata if intended for `_meta.yml` cascade
  - Adjust heading levels to match your hierarchy

- **Use in Jinja2 templates:** Extracted Markdown can include Jinja2 variables like `{{ product }}` or `{{ version }}` that resolve from your config cascade.

---

## Future: Interactive Extraction UI

A Phase 2 feature will add an interactive extraction tool with:
- Point-and-click file picker
- Real-time Markdown preview
- Destination folder browser
- Snippet management (save, edit, organize)

For now, use the CLI command.

---

## Troubleshooting

**"File not found"**
- Check that the file path is correct and the file exists
- Use absolute paths if relative paths don't work

**"Unsupported file type"**
- Only `.pdf` and `.docx` files are supported
- Convert other formats (RTF, ODT, etc.) to one of these first

**Extracted Markdown looks wrong**
- Some formatting is lost in PDF→Markdown conversion (images, complex layout, embedded fonts)
- Edit the extracted Markdown as needed before using it in documents
- This is expected; the extract feature aims for usability, not pixel-perfect conversion

---

## Help

For issues or feature requests, see the main project README or file an issue on GitHub.
