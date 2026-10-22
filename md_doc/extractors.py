"""Document extraction logic: Word, PowerPoint, Excel, HTML and PDF to Markdown."""

from __future__ import annotations

import json
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from markitdown import MarkItDown

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

#: ``{--old--}{++new++}`` pairs (a tracked replacement) become one substitution.
_REPLACEMENT_RE = re.compile(
    r"\{--((?:(?!--\}).)*)--\}[ \t]*\{\+\+((?:(?!\+\+\}).)*)\+\+\}", re.DOTALL
)


#: File types ``extract_file`` accepts. ``.dotx`` is read as a Word document.
SUPPORTED_SUFFIXES = (".pdf", ".docx", ".dotx", ".pptx", ".xlsx", ".html", ".htm")

_FIELD_REF_RE = re.compile(r"\[\[(\w+)\]\]")
_ESCAPED_FIELD_RE = re.compile(r"\\?\[\\?\[((?:\w|\\_)+)\\?\]\\?\]")
_MERGEFIELD_RE = re.compile(r'^\s*MERGEFIELD\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE)
#: Content controls that hold a choice or date rather than free text.
_NON_TEXT_CONTROLS = ("checkbox", "dropDownList", "comboBox", "date", "picture")


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


def _marker_run(text: str):
    from lxml import etree

    run = etree.Element(_w("r"))
    node = etree.SubElement(run, _w("t"))
    node.set(_XML_SPACE, "preserve")
    node.text = text
    return run


def _field_name(raw: str) -> str:
    """Make a Word field or control name a valid ``[[field]]`` identifier."""
    return re.sub(r"\W+", "_", raw.strip()).strip("_")


def _replace_fields(document) -> int:
    """Rewrite Word merge fields, text form fields and content controls as ``[[name]]``.

    This is the reverse of the ``.dotx`` builder: ``MERGEFIELD`` and ``FORMTEXT``
    (named in its form-field data) become ``[[name]]`` markers, as do plain-text
    content controls (named by their tag, else their title). Fields that carry no
    usable name, and checkbox / dropdown / date controls, are left as Word's own text.
    """
    count = 0

    for simple in list(document.iter(_w("fldSimple"))):
        match = _MERGEFIELD_RE.match(simple.get(_w("instr"), ""))
        name = _field_name(match.group(1) or match.group(2)) if match else ""
        if name:
            simple.addprevious(_marker_run(f"[[{name}]]"))
            simple.getparent().remove(simple)
            count += 1

    for paragraph in document.iter(_w("p")):
        open_fields: list[dict] = []
        for run in list(paragraph.iter(_w("r"))):
            char = run.find(_w("fldChar"))
            kind = char.get(_w("fldCharType")) if char is not None else None
            if kind == "begin":
                label = char.find(f"{_w('ffData')}/{_w('name')}")
                open_fields.append(
                    {
                        "runs": [run],
                        "instr": "",
                        "form_name": label.get(_w("val"), "") if label is not None else "",
                    }
                )
                continue
            if not open_fields:
                continue
            current = open_fields[-1]
            current["runs"].append(run)
            for node in run.findall(_w("instrText")):
                current["instr"] += node.text or ""
            if kind != "end":
                continue
            open_fields.pop()
            if open_fields:  # nested: the outer field owns these runs
                open_fields[-1]["runs"].extend(current["runs"])
                continue
            instr = current["instr"].strip()
            if instr.upper().startswith("FORMTEXT"):
                name = _field_name(current["form_name"])
            else:
                match = _MERGEFIELD_RE.match(instr)
                name = _field_name(match.group(1) or match.group(2)) if match else ""
            if not name:
                continue
            current["runs"][0].addprevious(_marker_run(f"[[{name}]]"))
            for member in current["runs"]:
                if member.getparent() is not None:
                    member.getparent().remove(member)
            count += 1

    for control in list(document.iter(_w("sdt"))):
        if control.getparent() is None or control.getparent().tag != _w("p"):
            continue  # block-level controls wrap whole paragraphs; leave them as text
        props = control.find(_w("sdtPr"))
        if props is None or any(props.find(_w(kind)) is not None for kind in _NON_TEXT_CONTROLS):
            continue
        tag, alias = props.find(_w("tag")), props.find(_w("alias"))
        name = (
            _field_name((tag if tag is not None else alias).get(_w("val"), ""))
            if (tag is not None or alias is not None)
            else ""
        )
        if name:
            control.addprevious(_marker_run(f"[[{name}]]"))
            control.getparent().remove(control)
            count += 1
    return count


def _prepare_word_document(source: Path, target: Path) -> bool:
    """Copy *source* to *target* with Word fields and revisions written out as text.

    Fields become ``[[name]]`` (see :func:`_replace_fields`). Insertions become ``{++…++}``, deletions ``{--…--}`` and each comment is placed
    after the text it covers as ``{==text==}{>>comment<<}``. Returns False (and
    leaves *target* unwritten) when the document has no fields, revisions or comments.
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
        replaced = _replace_fields(document)
        if not (insertions or deletions or starts or replaced):
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


@dataclass
class Extraction:
    """Markdown extracted from a file, plus the ``[[fields]]`` it contains."""

    markdown: str
    fields: list[str] = field(default_factory=list)


def extract_document(file_path: str, keep_images: bool = False) -> Extraction:
    """Convert *file_path* to Markdown and report the ``[[fields]]`` found in it.

    Supports Word (``.docx``, ``.dotx``), PowerPoint, Excel, HTML and PDF.
    In Word files, merge fields, text form fields and plain-text content controls
    come out as ``[[name]]`` (the syntax the ``.dotx`` builder turns back into Word
    fields), and tracked changes and comments come out as CriticMarkup
    (``{++added++}``, ``{--deleted--}``, ``{~~old~>new~~}``,
    ``{==text==}{>>comment<<}``), so a reviewed document returns to the Markdown
    source with its edits intact.

    Args:
        file_path: Path to the file to convert.
        keep_images: Keep embedded images as full ``data:`` URIs instead of the
            truncated placeholder (see :func:`split_embedded_images`).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file type is not supported.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"unsupported file type: {suffix}. Supported: {', '.join(SUPPORTED_SUFFIXES)}"
        )

    converter = MarkItDown()
    if suffix in {".docx", ".dotx"}:
        with tempfile.TemporaryDirectory() as tmp:
            # The converter keys on the extension, and a template is a document.
            prepared = Path(tmp) / "document.docx"
            try:
                changed = _prepare_word_document(path, prepared)
            except (zipfile.BadZipFile, KeyError):
                changed = False  # not a readable package: let the converter report it
            if not changed:
                prepared.write_bytes(path.read_bytes())
            result = converter.convert(str(prepared), keep_data_uris=keep_images)
        text = result.text_content or ""
        text = _REPLACEMENT_RE.sub(lambda m: f"{{~~{m.group(1)}~>{m.group(2)}~~}}", text)
        text = _ESCAPED_FIELD_RE.sub(lambda m: "[[" + m.group(1).replace("\\_", "_") + "]]", text)
    else:
        try:
            result = converter.convert(file_path, keep_data_uris=keep_images)
        except ImportError as exc:  # optional converter dependencies
            raise ValueError(f"{suffix} files need an optional extra: {exc}") from exc
        text = result.text_content or ""

    return Extraction(text, list(dict.fromkeys(_FIELD_REF_RE.findall(text))))


def extract_file(file_path: str, keep_images: bool = False) -> str:
    """Extract Markdown from a file; see :func:`extract_document`."""
    return extract_document(file_path, keep_images).markdown


def suggest_frontmatter(filename: str, fields: list[str], today: date | None = None) -> str:
    """Starter YAML frontmatter for a document imported from *filename*.

    ``output_filename`` keeps the original name, so rebuilding the imported
    document produces ``Client Proposal.dotx`` again rather than a slugged name.
    ``imported_from`` and ``imported_on`` record where the content came from (a browser
    only reports the file name, not its folder).
    """
    stem = Path(filename).stem.strip() or "Imported document"
    suffix = Path(filename).suffix.lower()
    lines = [
        f"title: {json.dumps(stem)}",
        f"output_filename: {json.dumps(stem)}",
        f"imported_from: {json.dumps(Path(filename).name)}",
        f'imported_on: "{(today or date.today()).isoformat()}"',
    ]
    if suffix == ".pptx":
        lines += ["outputs: [pptx]", "slide_split: h1"]
    elif suffix == ".dotx" or fields:
        lines.append("outputs: [dotx]")
        if fields:
            lines.append("dotx_field_type: form")
    else:
        lines.append("outputs: [pdf, docx]")
    return "---\n" + "\n".join(lines) + "\n---\n\n"


_DATA_URI_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(data:image/(png|jpe?g|gif|webp);base64,([A-Za-z0-9+/=]+)\)"
)


def split_embedded_images(markdown: str) -> tuple[str, list[dict[str, str]]]:
    """Replace inline ``data:`` image URIs with ``import-image-N.ext`` references.

    Returns the rewritten Markdown and one ``{"name", "data"}`` entry per image
    (``data`` is the original base64), so the caller can store the files wherever
    suits the destination document and point the references there.
    """
    images: list[dict[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        alt, kind, data = match.groups()
        name = f"import-image-{len(images) + 1}.{'jpg' if kind == 'jpeg' else kind}"
        images.append({"name": name, "data": data})
        return f"![{alt}]({name})"

    return _DATA_URI_IMAGE_RE.sub(replace, markdown), images
