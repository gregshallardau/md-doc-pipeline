"""Document extraction logic for PDF and DOCX files."""

from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

from markitdown import MarkItDown

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

#: ``{--old--}{++new++}`` pairs (a tracked replacement) become one substitution.
_REPLACEMENT_RE = re.compile(
    r"\{--((?:(?!--\}).)*)--\}[ \t]*\{\+\+((?:(?!\+\+\}).)*)\+\+\}", re.DOTALL
)


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


def _marker_run(text: str):
    from lxml import etree

    run = etree.Element(_w("r"))
    node = etree.SubElement(run, _w("t"))
    node.set(_XML_SPACE, "preserve")
    node.text = text
    return run


def _mark_tracked_changes(source: Path, target: Path) -> bool:
    """Copy *source* to *target* with Word revisions written out as CriticMarkup text.

    Insertions become ``{++…++}``, deletions ``{--…--}`` and each comment is placed
    after the text it covers as ``{==text==}{>>comment<<}``. Returns False (and
    leaves *target* unwritten) when the document has no revisions or comments.
    """
    from lxml import etree

    with zipfile.ZipFile(source) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
        comments_xml = (
            archive.read("word/comments.xml") if "word/comments.xml" in archive.namelist() else None
        )
        # Paragraph-mark revisions (inside w:rPr) carry no text.
        insertions = [e for e in document.iter(_w("ins")) if e.getparent().tag != _w("rPr")]
        deletions = [e for e in document.iter(_w("del")) if e.getparent().tag != _w("rPr")]
        starts = list(document.iter(_w("commentRangeStart")))
        if not (insertions or deletions or starts):
            return False

        comments: dict[str, str] = {}
        if comments_xml:
            for comment in etree.fromstring(comments_xml).iter(_w("comment")):
                text = " ".join("".join(t.itertext()).strip() for t in comment.iter(_w("p")))
                comments[comment.get(_w("id"), "")] = " ".join(text.split())

        for element, opener, closer in [(e, "{++", "++}") for e in insertions] + [
            (e, "{--", "--}") for e in deletions
        ]:
            for node in element.iter(_w("delText")):
                node.tag = _w("t")
                node.set(_XML_SPACE, "preserve")
            # Unwrap: converters skip (w:del) or special-case (w:ins) revision
            # elements, but read plain runs, so the marked-up text must be plain.
            element.addprevious(_marker_run(opener))
            for child in list(element):
                element.addprevious(child)
            element.addprevious(_marker_run(closer))
            element.getparent().remove(element)

        for start in starts:
            ident = start.get(_w("id"), "")
            start.addprevious(_marker_run("{=="))
            for end in document.iter(_w("commentRangeEnd")):
                if end.get(_w("id")) == ident:
                    note = comments.get(ident, "")
                    end.addnext(_marker_run("==}" + (f"{{>>{note}<<}}" if note else "")))
                    break

        patched = etree.tostring(document, xml_declaration=True, encoding="UTF-8", standalone=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
            for item in archive.infolist():
                data = patched if item.filename == "word/document.xml" else archive.read(item)
                out.writestr(item, data)
    return True


def extract_file(file_path: str) -> str:
    """
    Extract Markdown content from a PDF or DOCX file.

    Word tracked changes and comments in a ``.docx`` come out as CriticMarkup
    (``{++added++}``, ``{--deleted--}``, ``{~~old~>new~~}``, ``{==text==}{>>comment<<}``),
    so a reviewed document returns to the Markdown source with its edits intact.

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
    if suffix == ".docx":
        with tempfile.TemporaryDirectory() as tmp:
            marked = Path(tmp) / path.name
            try:
                has_revisions = _mark_tracked_changes(path, marked)
            except (zipfile.BadZipFile, KeyError):
                has_revisions = False  # not a readable package: let the converter report it
            result = converter.convert(str(marked if has_revisions else path))
        text = result.text_content or ""
        return _REPLACEMENT_RE.sub(lambda m: f"{{~~{m.group(1)}~>{m.group(2)}~~}}", text)

    result = converter.convert(file_path)

    return result.text_content or ""
