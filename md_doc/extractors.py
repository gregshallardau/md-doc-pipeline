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

    return result.text_content or ""
