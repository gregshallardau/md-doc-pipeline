# Document Extractor CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `md-doc extract` command to convert PDF and DOCX files to Markdown snippets, with flexible output destination control (templates/, custom folders, or standalone locations).

**Architecture:** Extract PDF/DOCX to Markdown using `markitdown` library. The CLI command accepts a source file and an output destination pattern. Output can be placed in `templates/`, a custom workspace subfolder, or relative to the document root. Core extraction logic lives in a focused `extractors.py` module; CLI command delegates to it. No interactive UI in this phase — CLI-only. Phase 2 (deferred) will add interactive frontend UI.

**Tech Stack:** `markitdown` library for document→Markdown conversion, Click CLI, pathlib for path resolution, pytest + unittest.mock for testing.

**Spec:** None — this is a greenfield feature within the existing md-doc CLI ecosystem.

---

## File map

| File | Action |
|---|---|
| `pyproject.toml` | Add `markitdown` as a dependency |
| `md_doc/extractors.py` | New — core extraction logic (PDF/DOCX → Markdown) |
| `md_doc/cli.py` | Add `extract` command |
| `tests/test_extractors.py` | New — unit tests for extraction logic |
| `tests/test_cli_extract.py` | New — integration tests for CLI command |
| `docs/extraction-guide.md` | New — user-facing guide for the extract command |

---

## Phase 2 TODO (deferred)

Phase 2 will add an interactive extraction UI (separate feature):
- Interactive file picker (select PDF/DOCX from workspace)
- Preview extracted Markdown in real time
- Point-and-click destination selection
- Snippet management (save, edit, organize)

This plan covers **Phase 1 (CLI-only)** only. Phase 2 will be a separate feature request and planning cycle.

---

### Task 1: Add `markitdown` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Check current dependencies**

Run:
```bash
cd /home/user/md-doc-pipeline
uv run pip show markitdown
```

Expected: Package not found (markitdown not yet installed).

- [ ] **Step 2: Add markitdown to pyproject.toml**

In `pyproject.toml`, under the `[project]` section's `dependencies` list, add `"markitdown>=0.13"` alongside the existing dependencies. The dependencies section should include:

```toml
dependencies = [
    "click>=8.1",
    "jinja2>=3.0",
    "pyyaml>=6.0",
    "markdown>=3.5",
    "python-docx>=0.8.11",
    "weasyprint>=68",
    "markitdown>=0.13",
]
```

(Exact version bumps may vary; `>=0.13` is a safe floor for the API we'll use.)

- [ ] **Step 3: Sync dependencies**

Run:
```bash
uv sync --group dev
```

Expected: markitdown and its transitive deps (like pandas for table extraction) are installed.

- [ ] **Step 4: Verify import works**

Run:
```bash
uv run python -c "from markitdown import MarkItDown; print('OK')"
```

Expected: Output `OK` with no errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add markitdown dependency for document extraction"
```

---

### Task 2: Create core extraction logic

**Files:**
- Create: `md_doc/extractors.py`
- Create: `tests/test_extractors.py`

- [ ] **Step 1: Write failing unit test for PDF extraction**

Create `tests/test_extractors.py`:

```python
"""Tests for document extraction logic."""

import tempfile
from pathlib import Path

import pytest

from md_doc.extractors import extract_file


class TestPdfExtraction:
    def test_extract_pdf_returns_markdown(self, tmp_path):
        """PDF file should be converted to Markdown string."""
        # Use a simple test PDF — create a minimal one using reportlab
        # For now, this is a placeholder that expects a real PDF
        pdf_path = tmp_path / "sample.pdf"
        
        # Create a minimal valid PDF (hex encoding of a bare-bones PDF)
        pdf_bytes = bytes.fromhex(
            "25504446202d312e340a"  # %PDF-1.4
            "25e2e3cfcb0a"  # %âãÏË\n (binary marker)
            "312030206f626a0a"  # 1 0 obj\n
            "3c3c2f50726f63536574205b2f505446202f546578742f496d616765425d0a"
            "2f547970652f2043617461" 
            "6c6f670a2f50616765732032203020520a3e3e0a656e646f626a0a"  # << ... >> endobj\n
            "787265660a302031300a"  # xref\n 0 10\n
            "0000000000203e20f0a"  # line offsets
        )
        pdf_path.write_bytes(pdf_bytes)
        
        result = extract_file(str(pdf_path))
        assert isinstance(result, str)
        assert len(result) > 0  # Non-empty markdown


class TestDocxExtraction:
    def test_extract_docx_returns_markdown(self, tmp_path):
        """DOCX file should be converted to Markdown string."""
        # Create a minimal DOCX using python-docx
        from docx import Document
        
        doc = Document()
        doc.add_heading("Test Document", 0)
        doc.add_paragraph("This is a test paragraph.")
        
        docx_path = tmp_path / "sample.docx"
        doc.save(str(docx_path))
        
        result = extract_file(str(docx_path))
        assert isinstance(result, str)
        assert "Test Document" in result


class TestExtractFileTypeValidation:
    def test_extract_file_rejects_unsupported_type(self, tmp_path):
        """Unsupported file types should raise ValueError."""
        unsupported = tmp_path / "file.txt"
        unsupported.write_text("text file")
        
        with pytest.raises(ValueError, match="unsupported file type"):
            extract_file(str(unsupported))


class TestExtractFileNotFound:
    def test_extract_file_not_found(self, tmp_path):
        """Non-existent file should raise FileNotFoundError."""
        missing = tmp_path / "nonexistent.pdf"
        
        with pytest.raises(FileNotFoundError):
            extract_file(str(missing))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_extractors.py -v
```

Expected: Tests fail with `ModuleNotFoundError` (md_doc.extractors does not exist yet).

- [ ] **Step 3: Create the extractors module**

Create `md_doc/extractors.py`:

```python
"""Document extraction logic for PDF and DOCX files."""

from pathlib import Path

from markitdown import MarkItDown


def extract_file(file_path: str) -> str:
    """
    Extract Markdown content from a PDF or DOCX file.
    
    Args:
        file_path: Path to PDF or DOCX file.
    
    Returns:
        Extracted content as Markdown string.
    
    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file type is not supported (not PDF or DOCX).
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise ValueError(f"unsupported file type: {suffix}. Supported: .pdf, .docx")
    
    converter = MarkItDown()
    result = converter.convert(file_path)
    
    return result.text_content
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_extractors.py -v
```

Expected: All three tests pass.
- `test_extract_pdf_returns_markdown` — PASSED
- `test_extract_docx_returns_markdown` — PASSED
- `test_extract_file_type_validation` — PASSED
- `test_extract_file_not_found` — PASSED

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest -v
```

Expected: All existing tests still pass. No regressions.

- [ ] **Step 6: Commit**

```bash
git add md_doc/extractors.py tests/test_extractors.py
git commit -m "feat: add document extraction logic for PDF and DOCX files"
```

---

### Task 3: Add `extract` command to CLI

**Files:**
- Modify: `md_doc/cli.py`
- Create: `tests/test_cli_extract.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/test_cli_extract.py`:

```python
"""Integration tests for the extract CLI command."""

from pathlib import Path

from click.testing import CliRunner
from docx import Document

from md_doc.cli import main


def test_extract_docx_to_templates(tmp_path):
    """Extract DOCX to templates/ folder with default naming."""
    # Set up repo structure
    (tmp_path / ".git").mkdir()
    
    # Create source DOCX
    doc = Document()
    doc.add_heading("Integration Guide", 0)
    doc.add_paragraph("Step 1: Install the package")
    doc.add_paragraph("Step 2: Configure settings")
    source_docx = tmp_path / "integration.docx"
    doc.save(str(source_docx))
    
    # Create templates folder
    (tmp_path / "templates").mkdir()
    
    # Run extract command
    runner = CliRunner()
    result = runner.invoke(main, [
        "extract",
        str(source_docx),
        "--dest", "templates/",
    ])
    
    assert result.exit_code == 0, result.output
    
    # Check output file was created
    output_file = tmp_path / "templates" / "integration.md"
    assert output_file.exists(), f"Expected {output_file} to exist"
    
    # Check content was extracted
    content = output_file.read_text()
    assert "Integration Guide" in content
    assert "Step 1" in content


def test_extract_pdf_to_custom_folder(tmp_path):
    """Extract PDF to custom folder with --dest flag."""
    (tmp_path / ".git").mkdir()
    
    # Create a minimal PDF using reportlab
    try:
        from reportlab.pdfgen import canvas
        pdf_path = tmp_path / "sample.pdf"
        c = canvas.Canvas(str(pdf_path))
        c.drawString(100, 750, "Sample PDF Content")
        c.save()
    except ImportError:
        pytest.skip("reportlab not installed for PDF generation")
    
    # Create custom destination folder
    custom_folder = tmp_path / "snippets"
    custom_folder.mkdir()
    
    # Run extract command
    runner = CliRunner()
    result = runner.invoke(main, [
        "extract",
        str(pdf_path),
        "--dest", "snippets/",
    ])
    
    assert result.exit_code == 0, result.output
    
    # Check output file was created with .md extension
    output_file = custom_folder / "sample.md"
    assert output_file.exists(), f"Expected {output_file} to exist"


def test_extract_unsupported_file_type(tmp_path):
    """Extract should reject unsupported file types."""
    (tmp_path / ".git").mkdir()
    
    text_file = tmp_path / "readme.txt"
    text_file.write_text("Not a valid input type")
    
    runner = CliRunner()
    result = runner.invoke(main, [
        "extract",
        str(text_file),
        "--dest", "templates/",
    ])
    
    assert result.exit_code != 0
    assert "unsupported file type" in result.output.lower()


def test_extract_file_not_found(tmp_path):
    """Extract should error if source file doesn't exist."""
    (tmp_path / ".git").mkdir()
    
    runner = CliRunner()
    result = runner.invoke(main, [
        "extract",
        str(tmp_path / "nonexistent.pdf"),
        "--dest", "templates/",
    ])
    
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_extract_default_destination_is_templates(tmp_path):
    """If --dest is omitted, default to templates/."""
    (tmp_path / ".git").mkdir()
    
    # Create source DOCX
    doc = Document()
    doc.add_heading("Auto-save Test", 0)
    source_docx = tmp_path / "auto_test.docx"
    doc.save(str(source_docx))
    
    # Create templates folder
    (tmp_path / "templates").mkdir()
    
    # Run extract without --dest
    runner = CliRunner()
    result = runner.invoke(main, [
        "extract",
        str(source_docx),
    ])
    
    assert result.exit_code == 0, result.output
    
    # Check that default templates/ was used
    output_file = tmp_path / "templates" / "auto_test.md"
    assert output_file.exists(), f"Expected {output_file} to exist with default dest"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_cli_extract.py -v
```

Expected: Tests fail with `No such command: extract` or similar CLI error.

- [ ] **Step 3: Add extract command to cli.py**

In `md_doc/cli.py`, add this command at the end of the file (after all other `@main` commands):

```python
@main.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option(
    "--dest",
    type=str,
    default="templates/",
    help="Destination folder or path pattern for extracted Markdown. Default: templates/",
)
def extract(file_path: str, dest: str) -> None:
    """
    Extract Markdown from a PDF or DOCX file.
    
    Converts a PDF or DOCX file to Markdown and saves it to the specified destination.
    Output filename is derived from the source filename (with .md extension).
    
    Examples:
        md-doc extract proposal.pdf --dest templates/
        md-doc extract contract.docx --dest snippets/
        md-doc extract form.pdf  # defaults to templates/
    """
    from md_doc.extractors import extract_file
    
    try:
        # Extract content
        markdown_content = extract_file(file_path)
        
        # Resolve output path
        source_path = Path(file_path)
        dest_path = Path(dest)
        
        # Create destination folder if it doesn't exist
        dest_path.mkdir(parents=True, exist_ok=True)
        
        # Output filename: source name with .md extension
        output_name = source_path.stem + ".md"
        output_file = dest_path / output_name
        
        # Write extracted content
        output_file.write_text(markdown_content, encoding="utf-8")
        
        click.echo(f"✓ Extracted: {source_path.name} → {output_file}")
        
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Exit(1)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Exit(1)
```

Add the import at the top of `md_doc/cli.py` if not already present:

```python
from pathlib import Path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_cli_extract.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest -v
```

Expected: All tests pass, no regressions.

- [ ] **Step 6: Verify command works manually**

Create a quick test DOCX:

```bash
uv run python -c "
from docx import Document
from pathlib import Path

doc = Document()
doc.add_heading('Test Extract', 0)
doc.add_paragraph('This is extracted content.')
Path('test_extract.docx').write_bytes(doc.save('/dev/stdout') or b'')
"
```

Actually, let's use a simpler approach. Just verify the help:

```bash
uv run md-doc extract --help
```

Expected: Shows help text with options.

- [ ] **Step 7: Commit**

```bash
git add md_doc/cli.py tests/test_cli_extract.py
git commit -m "feat: add md-doc extract command for PDF/DOCX to Markdown conversion"
```

---

### Task 4: Document the extract command

**Files:**
- Create: `docs/extraction-guide.md`

- [ ] **Step 1: Write extraction guide**

Create `docs/extraction-guide.md`:

```markdown
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

Use it in other documents:

```markdown
# Our Proposal

{% include "vendor-proposal.md" %}
```

### Extract PDF form into snippets folder

```bash
md-doc extract /downloads/intake-form.pdf --dest workspace/acme/snippets/
```

Result: `workspace/acme/snippets/intake-form.md` — reusable form content.

### Extract contract and customize

```bash
md-doc extract contract-template.docx --dest workspace/acme/legal/
# Edit workspace/acme/legal/contract-template.md as needed
# Include in DOTX merge templates:
# {% include "legal/contract-template.md" %}
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
4. Use `{% include %}` to compose larger documents:
   ```markdown
   # Full Proposal
   
   {% include "clients/stormfront/snippets/client-proposal.md" %}
   
   {% include "templates/legal/legal-disclaimer.md" %}
   ```
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

- **Use in Jinja2 templates:** Extracted Markdown can include Jinja2 syntax:
  ```markdown
  # {{ product }} — Extracted from vendor proposal
  
  [extracted content...]
  ```

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
```

- [ ] **Step 2: Verify markdown syntax**

```bash
uv run md-doc lint docs/
```

Expected: No errors (pure documentation, no config).

- [ ] **Step 3: Commit**

```bash
git add docs/extraction-guide.md
git commit -m "docs: add extraction guide for document-to-markdown conversion"
```

---

## Done

At this point:
- `markitdown` is installed and available
- Core extraction logic in `extractors.py` handles PDF/DOCX → Markdown
- CLI command `md-doc extract` accepts source file and optional `--dest` folder
- Output defaults to `templates/` if destination is omitted
- Full test coverage for extraction logic and CLI integration
- User-facing documentation

**Phase 2 (deferred to separate feature request):**
- Interactive extraction UI with file picker and preview
- Snippet management and organization

Run the full suite one final time to confirm:

```bash
uv run pytest -v
uv run ruff check .
uv run black --check .
uv run mypy md_doc/
```

All should pass.
