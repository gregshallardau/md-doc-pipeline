"""WeasyPrint capabilities beyond a plain HTML → PDF call.

``builders/pdf.py`` turns Markdown into HTML and hands it to WeasyPrint. This
module holds everything else WeasyPrint can do, each switched by a config key
(see ``docs/handbook.md#configuration``):

* **PDF container** – ``pdf_variant`` (PDF/A, PDF/UA, PDF/X), ``pdf_tags``,
  ``pdf_identifier``, ``pdf_version``, metadata (``description``, ``keywords``
  and the document's own ``version``/``status``), embedded attachments, XMP,
  image/font/size options and an ICC colour profile.
* **Outline & navigation** – PDF bookmarks, cross-references that read the
  target's text and page (``target-text`` / ``target-counter``), running chapter
  and section titles for headers and footers.
* **Typography** – ``@font-face`` fonts, OpenType features, tabular figures,
  automatic hyphenation, document language, numbered headings.
* **Page layout** – real page-bottom footnotes, multi-column and grid blocks,
  duplex (left/right) pages with a binding margin, recto chapter starts,
  crop marks and bleed, ``object-fit`` images.
* **Layout checks** – a post-render inspection of the laid-out pages through the
  WeasyPrint ``Document`` API (orphaned headings, content past the margin,
  empty pages).

Everything here is opt-in or visually neutral, so existing documents render as
before unless they set one of the keys.
"""

from __future__ import annotations

import datetime
import html as _html
import io
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import coerce_bool
from .literal import transform_outside_code

logger = logging.getLogger(__name__)

#: Resolves a config path (font, attachment, profile …) to a real file, or None.
Resolver = Callable[[str | None], Path | None]

#: ``pdf_variant`` values WeasyPrint accepts (its ``debug`` variant is internal).
PDF_VARIANTS: tuple[str, ...] = (
    "pdf/a-1b",
    "pdf/a-2b",
    "pdf/a-3b",
    "pdf/a-2u",
    "pdf/a-3u",
    "pdf/a-4u",
    "pdf/a-1a",
    "pdf/a-2a",
    "pdf/a-3a",
    "pdf/a-4e",
    "pdf/a-4f",
    "pdf/ua-1",
    "pdf/ua-2",
    "pdf/x-1a",
    "pdf/x-3",
    "pdf/x-4",
    "pdf/x-5g",
)

#: ``chapter_break`` values (CSS ``break-before`` keywords).
CHAPTER_BREAKS: tuple[str, ...] = ("page", "recto", "verso", "left", "right")

#: ``heading_number_style`` values (CSS ``<counter-style-name>``).
NUMBER_STYLES: tuple[str, ...] = (
    "decimal",
    "decimal-leading-zero",
    "upper-roman",
    "lower-roman",
    "upper-alpha",
    "lower-alpha",
)

#: ``header_layout`` / ``footer_layout`` values.
BAR_LAYOUTS: tuple[str, ...] = ("box", "running")

#: ``image_fit`` values (CSS ``object-fit``).
IMAGE_FITS: tuple[str, ...] = ("contain", "cover", "fill", "scale-down", "none")

#: ``print_marks`` values (CSS ``marks``).
PRINT_MARKS: tuple[str, ...] = ("crop", "cross", "crop cross")

_LENGTH_RE = re.compile(r"^\d+(?:\.\d+)?(?:mm|cm|in|pt|pc|px|em|rem|%)?$")
_SAFE_VALUE_RE = re.compile(r"^[\w .#%(),/+-]{1,120}$")
_FAMILY_RE = re.compile(r"^[\w .-]{1,80}$")
_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_FEATURE_RE = re.compile(r"""^[\w ,'"-]{1,200}$""")


# ---------------------------------------------------------------------------
# Small config readers
# ---------------------------------------------------------------------------


def _flag(config: dict[str, Any], key: str, default: bool = False) -> bool:
    return coerce_bool(config.get(key), default)


def _length(value: Any) -> str | None:
    """A CSS length (``8mm``, ``1.5em``) or None; keeps odd input out of the CSS."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text if _LENGTH_RE.match(text) else None


def _safe_value(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text if _SAFE_VALUE_RE.match(text) else None


def _int(value: Any, low: int, high: int) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _choice(value: Any, allowed: tuple[str, ...]) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = " ".join(str(value).strip().lower().split())
    return text if text in allowed else None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def document_lang(config: dict[str, Any]) -> str:
    """The ``<html lang>`` value: ``lang`` when it is a valid BCP 47 tag, else ``en``."""
    raw = str(config.get("lang") or "").strip()
    return raw if _LANG_RE.match(raw) else "en"


# ---------------------------------------------------------------------------
# <head> metadata
# ---------------------------------------------------------------------------


def _generator() -> str:
    try:
        from importlib.metadata import version

        return f"md-doc-pipeline {version('md-doc-pipeline')}"
    except Exception:  # pragma: no cover - not installed as a distribution
        return "md-doc-pipeline"


def _created(config: dict[str, Any]) -> str:
    """ISO creation date: an ISO ``date``, else ``SOURCE_DATE_EPOCH``, else today."""
    raw = str(config.get("date") or "").strip()
    try:
        return datetime.date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        pass
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "")
    if epoch.isdigit():
        stamp = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)
        return stamp.date().isoformat()
    return datetime.date.today().isoformat()


def keywords_of(config: dict[str, Any]) -> list[str]:
    """``keywords`` (list or comma string), falling back to ``tags``."""
    raw = config.get("keywords")
    if raw in (None, "", []):
        raw = config.get("tags")
    items: list[str] = []
    for entry in _as_list(raw):
        items.extend(part.strip() for part in str(entry).split(",") if part.strip())
    return items


def head_meta(config: dict[str, Any], *, author: str) -> str:
    """``<meta>`` tags WeasyPrint copies into the PDF info dictionary and XMP.

    ``author``, ``description``, ``keywords``, ``generator`` and the creation
    date are standard PDF metadata. ``version``, ``status``, ``product`` and
    ``document_type`` become custom entries (see ``pdf_custom_metadata``).
    """
    esc = lambda text: _html.escape(str(text), quote=True)  # noqa: E731
    tags: list[tuple[str, str]] = []
    if author:
        tags.append(("author", author))
    description = str(config.get("description") or "").strip()
    if description:
        tags.append(("description", description))
    keywords = keywords_of(config)
    if keywords:
        tags.append(("keywords", ", ".join(keywords)))
    tags.append(("generator", _generator()))
    tags.append(("dcterms.created", _created(config)))
    if _flag(config, "pdf_custom_metadata", True):
        for key in ("version", "status", "product", "document_type"):
            value = config.get(key)
            if value not in (None, "") and not isinstance(value, (dict, list)):
                tags.append((key, str(value)))
    return "\n  ".join(f'<meta name="{esc(name)}" content="{esc(value)}">' for name, value in tags)


# ---------------------------------------------------------------------------
# write_pdf() / render() options
# ---------------------------------------------------------------------------


def render_options(
    config: dict[str, Any],
    *,
    resolve: Resolver,
    rendered_md: str = "",
    doc_path: Path | None = None,
) -> dict[str, Any]:
    """Keyword options for ``HTML.render()`` / ``Document.write_pdf()``.

    The same dict goes to both calls, exactly as ``HTML.write_pdf`` forwards it.
    """
    opts: dict[str, Any] = {}

    variant = _choice(config.get("pdf_variant"), PDF_VARIANTS)
    if variant:
        opts["pdf_variant"] = variant
    elif config.get("pdf_variant"):
        logger.warning("Ignoring unknown pdf_variant %r.", config.get("pdf_variant"))

    version = str(config.get("pdf_version") or "").strip()
    if re.fullmatch(r"\d\.\d", version):
        opts["pdf_version"] = version

    identifier = config.get("pdf_identifier")
    if isinstance(identifier, bool):
        if identifier:
            opts["pdf_identifier"] = True
    elif identifier not in (None, ""):
        opts["pdf_identifier"] = str(identifier)

    if _flag(config, "pdf_tags"):
        opts["pdf_tags"] = True
    opts["custom_metadata"] = _flag(config, "pdf_custom_metadata", True)
    if _flag(config, "pdf_presentational_hints"):
        opts["presentational_hints"] = True
    if _flag(config, "pdf_optimize_images"):
        opts["optimize_images"] = True
    quality = _int(config.get("pdf_jpeg_quality"), 0, 95)
    if quality is not None:
        opts["jpeg_quality"] = quality
    dpi = _int(config.get("pdf_image_dpi"), 36, 1200)
    if dpi is not None:
        opts["dpi"] = dpi
    if _flag(config, "pdf_uncompressed"):
        opts["uncompressed_pdf"] = True
    if _flag(config, "pdf_srgb"):
        opts["srgb"] = True
    if _flag(config, "pdf_full_fonts"):
        opts["full_fonts"] = True
    if _flag(config, "pdf_hinting"):
        opts["hinting"] = True

    attachments = _attachments(config, resolve, rendered_md, doc_path)
    if attachments:
        opts["attachments"] = attachments

    xmp = [path.as_uri() for raw in _as_list(config.get("pdf_xmp")) if (path := resolve(str(raw)))]
    if xmp:
        opts["xmp_metadata"] = xmp
    return opts


def _attachments(
    config: dict[str, Any], resolve: Resolver, rendered_md: str, doc_path: Path | None
) -> list[Any]:
    from weasyprint import Attachment

    found: list[Any] = []
    if _flag(config, "pdf_attach_source") and rendered_md.strip():
        name = f"{doc_path.stem if doc_path else 'document'}.md"
        found.append(
            Attachment(
                file_obj=io.BytesIO(rendered_md.encode("utf-8")),
                name=name,
                description="Markdown source (variables and includes resolved)",
                relationship="Source",
            )
        )
    for raw in _as_list(config.get("pdf_attachments")):
        path = resolve(str(raw))
        if path is None or not path.is_file():
            logger.warning("pdf_attachments: %r was not found; skipped.", raw)
            continue
        found.append(
            Attachment(
                filename=str(path),
                name=path.name,
                description=path.name,
                relationship="Supplement",
            )
        )
    return found


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

_FONT_FORMATS = {
    ".ttf": "truetype",
    ".otf": "opentype",
    ".woff": "woff",
    ".woff2": "woff2",
}

#: Shorthand keys in a ``fonts`` entry → (font-weight, font-style).
_FONT_SLOTS = {
    "regular": ("400", "normal"),
    "bold": ("700", "normal"),
    "italic": ("400", "italic"),
    "bold_italic": ("700", "italic"),
}


def _font_face(family: str, path: Path, weight: str, style: str) -> str:
    fmt = _FONT_FORMATS.get(path.suffix.lower())
    src = f'url("{path.as_uri()}")' + (f' format("{fmt}")' if fmt else "")
    return (
        f"@font-face {{ font-family: '{family}'; src: {src}; "
        f"font-weight: {weight}; font-style: {style}; }}"
    )


def font_faces(config: dict[str, Any], resolve: Resolver) -> list[tuple[str, Path, str, str]]:
    """Resolved ``(family, file, weight, style)`` faces for the ``fonts`` key.

    Each entry is ``{family, path, weight, style}`` for one file, or
    ``{family, regular, bold, italic, bold_italic}`` for a family. A bare
    string is a path whose file name is the family.
    """
    out: list[tuple[str, Path, str, str]] = []
    for entry in _as_list(config.get("fonts")):
        if isinstance(entry, str):
            entry = {"path": entry}
        if not isinstance(entry, dict):
            continue
        path_value = entry.get("path") or entry.get("src")
        family = str(entry.get("family") or "").strip()
        if not family and path_value:
            family = Path(str(path_value)).stem
        if not _FAMILY_RE.match(family):
            logger.warning("fonts: ignoring entry with invalid family %r.", family)
            continue
        faces: list[tuple[Any, str, str]] = []
        if path_value:
            weight = str(entry.get("weight") or "400")
            style = str(entry.get("style") or "normal")
            if not re.fullmatch(r"\d{3}|normal|bold", weight) or style not in {
                "normal",
                "italic",
                "oblique",
            }:
                logger.warning("fonts: invalid weight/style for %r; skipped.", family)
                continue
            faces.append((path_value, weight, style))
        for slot, (weight, style) in _FONT_SLOTS.items():
            if entry.get(slot):
                faces.append((entry[slot], weight, style))
        for raw, weight, style in faces:
            path = resolve(str(raw))
            if path is None or not path.is_file():
                logger.warning("fonts: %r was not found; skipped.", raw)
                continue
            out.append((family, path, weight, style))
    return out


def font_face_css(config: dict[str, Any], resolve: Resolver) -> str:
    """``@font-face`` rules for the ``fonts`` key, as a ``<style>`` block."""
    rules = [_font_face(*face) for face in font_faces(config, resolve)]
    if not rules:
        return ""
    return "<style>\n" + "\n".join(rules) + "\n</style>"


def color_profile_css(config: dict[str, Any], resolve: Resolver) -> str:
    """``@color-profile device-cmyk`` for ``pdf_color_profile`` (an ICC file)."""
    raw = config.get("pdf_color_profile")
    if not raw:
        return ""
    path = resolve(str(raw))
    if path is None or not path.is_file():
        logger.warning("pdf_color_profile: %r was not found; skipped.", raw)
        return ""
    return f'<style>@color-profile device-cmyk {{ src: url("{path.as_uri()}"); }}</style>'


# ---------------------------------------------------------------------------
# Markdown directives: <!-- columns: N --> and <!-- grid: N -->
# ---------------------------------------------------------------------------

_DIRECTIVE_OPEN_RE = re.compile(
    r"^[ \t]*<!--\s*(columns|grid)\s*:\s*(\d+)\s*(?:,\s*([^>]*?))?\s*-->[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_DIRECTIVE_CLOSE_RE = re.compile(r"^[ \t]*<!--\s*/\s*(columns|grid)\s*-->[ \t]*$", re.I | re.M)


def _directive_style(kind: str, count: int, options: str | None) -> str:
    count = max(1, min(count, 12 if kind == "grid" else 6))
    opts: dict[str, str] = {}
    for part in (options or "").split(","):
        key, _, value = part.partition("=")
        if key.strip() and value.strip():
            opts[key.strip().lower()] = value.strip()
    gap = _length(opts.get("gap"))
    if kind == "columns":
        css = [f"column-count: {count}"]
        css.append(f"column-gap: {gap or '8mm'}")
        rule = _safe_value(opts.get("rule"))
        if rule:
            css.append(f"column-rule: {rule}")
    else:
        css = ["display: grid", f"grid-template-columns: repeat({count}, 1fr)"]
        css.append(f"gap: {gap or '4mm'}")
    return "; ".join(css)


def expand_directives(markdown: str) -> str:
    """Turn ``<!-- columns: 2 -->`` / ``<!-- grid: 3 -->`` blocks into styled divs.

    Optional settings follow the count: ``<!-- columns: 2, gap=10mm, rule=0.5pt solid #ccc -->``
    and ``<!-- grid: 3, gap=6mm -->``. Close the block with ``<!-- /columns -->`` or
    ``<!-- /grid -->``. Word builds ignore the comments and flow the content normally.
    """

    def transform(text: str) -> str:
        def open_tag(match: re.Match[str]) -> str:
            kind = match.group(1).lower()
            style = _directive_style(kind, int(match.group(2)), match.group(3))
            return f'\n<div class="md-{kind}" markdown="1" style="{style}">\n'

        text = _DIRECTIVE_OPEN_RE.sub(open_tag, text)
        return _DIRECTIVE_CLOSE_RE.sub("\n</div>\n", text)

    return transform_outside_code(markdown, transform)


def unbalanced_directives(markdown: str) -> list[tuple[int, str]]:
    """``(line, message)`` for columns/grid blocks that are opened but not closed."""
    problems: list[tuple[int, str]] = []
    stack: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(markdown.splitlines(), start=1):
        if re.match(r"^\s{0,3}(```|~~~)", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        opened = _DIRECTIVE_OPEN_RE.match(line)
        closed = _DIRECTIVE_CLOSE_RE.match(line)
        if opened:
            stack.append((number, opened.group(1).lower()))
        elif closed:
            kind = closed.group(1).lower()
            if stack and stack[-1][1] == kind:
                stack.pop()
            else:
                problems.append((number, f"<!-- /{kind} --> has no matching <!-- {kind}: N -->"))
    for number, kind in stack:
        problems.append((number, f"<!-- {kind}: N --> is never closed with <!-- /{kind} -->"))
    return problems


# ---------------------------------------------------------------------------
# HTML post-processing
# ---------------------------------------------------------------------------

_FOOTNOTE_DIV_RE = re.compile(r'<div class="footnote">.*?</div>', re.DOTALL)
_FOOTNOTE_LI_RE = re.compile(r'<li id="(fn:[^"]+)">(.*?)</li>', re.DOTALL)
_FOOTNOTE_REF_RE = re.compile(
    r'<sup id="fnref\d*:([^"]+)"><a class="footnote-ref" href="#fn:[^"]+">[^<]*</a></sup>'
)
_BACKREF_RE = re.compile(r'\s*(?:&#160;|\xa0)?<a class="footnote-backref"[^>]*>.*?</a>', re.DOTALL)


def page_footnotes(html: str) -> str:
    """Turn Markdown footnotes into real page-bottom footnotes (``float: footnote``).

    Each reference becomes an inline ``<span class="md-footnote">`` carrying the
    note's text; WeasyPrint lifts it to the foot of the page that cites it and
    numbers it. The collected "Footnotes" list at the end is removed.
    """
    match = _FOOTNOTE_DIV_RE.search(html)
    if not match:
        return html
    notes: dict[str, str] = {}
    for key, body in _FOOTNOTE_LI_RE.findall(match.group(0)):
        text = _BACKREF_RE.sub("", body).strip()
        text = re.sub(r"\s*</p>\s*<p>\s*", "<br><br>", text)
        text = re.sub(r"^\s*<p>|</p>\s*$", "", text).strip()
        notes[key[3:]] = text
    if not notes:
        return html
    html = html.replace(match.group(0), "")

    def reference(ref: re.Match[str]) -> str:
        return f'<span class="md-footnote">{notes.get(ref.group(1), "")}</span>'

    return _FOOTNOTE_REF_RE.sub(reference, html)


_TOC_RE = re.compile(r'<div class="toc">.*?</div>', re.DOTALL)
_LISTOF_RE = re.compile(
    r'<(?:div|nav|ul|ol)\b[^>]*class="[^"]*\blist-of\b[^"]*"[^>]*>.*?</(?:div|nav|ul|ol)>',
    re.DOTALL,
)
_ANCHOR_RE = re.compile(r'<a href="#([^"]+)"(?![^>]*\bclass=)([^>]*)>')
_HEADING_RE = re.compile(r"<h([1-6])\b([^>]*)>", re.IGNORECASE)


def mark_cross_references(html: str) -> str:
    """Add ``class="md-xref"`` to internal links outside the contents and footnotes."""
    stash: list[str] = []

    def hide(match: re.Match[str]) -> str:
        stash.append(match.group(0))
        return f"\x00{len(stash) - 1}\x00"

    hidden = _TOC_RE.sub(hide, html)
    hidden = _LISTOF_RE.sub(hide, hidden)
    hidden = _ANCHOR_RE.sub(
        lambda m: f'<a href="#{m.group(1)}" class="md-xref"{m.group(2)}>', hidden
    )
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], hidden)


def number_start_level(html: str) -> int:
    """Heading level that gets number "1": 2 when a lone leading H1 is the title, else 1."""
    levels = [int(m.group(1)) for m in _HEADING_RE.finditer(html)]
    if levels and levels.count(1) == 1 and levels[0] == 1 and any(v > 1 for v in levels):
        return 2
    return 1


def mark_toc_levels(html: str, start: int, depth: int) -> str:
    """Tag contents entries with ``toc-n<level>`` so they can show heading numbers."""
    levels: dict[str, int] = {}
    for match in _HEADING_RE.finditer(html):
        ident = re.search(r'\bid="([^"]+)"', match.group(2))
        if ident:
            levels[ident.group(1)] = int(match.group(1))

    def retag(block: re.Match[str]) -> str:
        def tag(anchor: re.Match[str]) -> str:
            level = levels.get(anchor.group(1))
            if level is None or not (start <= level < start + depth):
                return anchor.group(0)
            return (
                f'<a href="#{anchor.group(1)}" class="toc-n{level - start + 1}"{anchor.group(2)}>'
            )

        return _ANCHOR_RE.sub(tag, block.group(0))

    return _TOC_RE.sub(retag, html)


def postprocess_html(html: str, config: dict[str, Any]) -> str:
    """Apply the HTML-level transforms the config asks for."""
    if 'class="critic-bar"' in html:
        from .critic import mark_changed_blocks

        html = mark_changed_blocks(html)
    if _flag(config, "page_footnotes"):
        html = page_footnotes(html)
    if _flag(config, "xref_pages"):
        html = mark_cross_references(html)
    if _flag(config, "numbered_headings"):
        depth = _int(config.get("numbered_headings_depth"), 1, 4) or 3
        html = mark_toc_levels(html, number_start_level(html), depth)
    return html


# ---------------------------------------------------------------------------
# Running headers and footers (position: running / element())
# ---------------------------------------------------------------------------

_RUN_TOKEN_RE = re.compile(r"\{(page|pages|chapter|section)\}")

_RUN_TOKEN_CSS = (
    ".rb-page::before { content: counter(page); }\n"
    ".rb-pages::before { content: counter(pages); }\n"
    ".rb-chapter::before { content: string(md-chapter, first); }\n"
    ".rb-section::before { content: string(md-section, last); }\n"
)


def bar_layout(config: dict[str, Any], key: str) -> str:
    return _choice(config.get(key), BAR_LAYOUTS) or "box"


def running_text_html(text: str) -> str:
    """HTML for header/footer text: escaped, newlines as ``<br>``, tokens as live spans."""
    parts: list[str] = []
    last = 0
    for match in _RUN_TOKEN_RE.finditer(text):
        parts.append(_html.escape(text[last : match.start()]).replace("\n", "<br>"))
        parts.append(f'<span class="rb-{match.group(1)}"></span>')
        last = match.end()
    parts.append(_html.escape(text[last:]).replace("\n", "<br>"))
    return "".join(parts)


def running_bar(
    name: str,
    edge: str,
    slots: dict[str, str],
    *,
    mirror: bool = False,
    font_size: str = "8pt",
    color: str = "#5d6d7e",
) -> tuple[str, str]:
    """A header or footer laid out as one flex row, delivered through a running element.

    *slots* maps ``left``/``center``/``right`` to HTML. Returns ``(html, css)``;
    the HTML goes at the top of ``<body>``. With *mirror*, a second element with
    left and right swapped serves left-hand pages.
    """
    border = "border-bottom" if edge == "top" else "border-top"
    padding = "padding-bottom" if edge == "top" else "padding-top"

    def element(ident: str, swap: bool) -> str:
        a, b = ("right", "left") if swap else ("left", "right")
        cells = "".join(
            f'<div class="rb-{cls}">{slots.get(src, "")}</div>'
            for cls, src in (("left", a), ("center", "center"), ("right", b))
        )
        return f'<div class="md-run" style="position: running({ident})">{cells}</div>'

    html = element(name, False) + (element(f"{name}-l", True) if mirror else "")
    box = f"@{edge}-center"
    other = [f"@{edge}-left", f"@{edge}-right"]
    css = [
        f".md-run {{ display: flex; align-items: center; width: 100%; font-size: {font_size}; "
        f"color: {color}; line-height: 1.3; }}",
        ".md-run > div { flex: 1 1 0; } .rb-left { text-align: left; } "
        ".rb-center { text-align: center; } .rb-right { text-align: right; }",
        ".md-run img { vertical-align: middle; }",
        _RUN_TOKEN_CSS,
        "@page {",
        f"  {box} {{ content: element({name}); width: 100%; {border}: 0.5pt solid #d5d8dc; "
        f"{padding}: 3pt; vertical-align: middle; }}",
        *(f"  {o} {{ content: none; border: none; }}" for o in other),
        "}",
        f"@page cover {{ {box} {{ content: none; border: none; }} }}",
    ]
    if mirror:
        css.append(f"@page :left {{ {box} {{ content: element({name}-l); }} }}")
    return html, "<style>\n" + "\n".join(css) + "\n</style>"


def header_bar(
    config: dict[str, Any],
    *,
    text: str | None,
    text_position: str,
    logo_uri: str | None,
    logo_position: str,
    logo_height_mm: float | None,
) -> tuple[str, str]:
    """The running header (``header_layout: running``); ("", "") when it has no content."""
    slots: dict[str, str] = {}
    if text:
        slots[text_position if text_position in {"left", "center", "right"} else "left"] = (
            running_text_html(text)
        )
    if logo_uri:
        pos = logo_position if logo_position in {"left", "center", "right"} else "right"
        height = f"height: {logo_height_mm:g}mm" if logo_height_mm else "max-height: 8mm"
        img = f'<img src="{_html.escape(logo_uri, quote=True)}" style="{height}">'
        slots[pos] = slots.get(pos, "") + img
    if not slots:
        return "", ""
    return running_bar("md-header", "top", slots, mirror=_flag(config, "duplex"))


def footer_bar(
    config: dict[str, Any], left: str | None, center: str | None, right: str | None
) -> tuple[str, str]:
    """The running footer (``footer_layout: running``); ("", "") when no slot is set."""
    if left is None and center is None and right is None:
        return "", ""
    slots = {
        "left": running_text_html(left or ""),
        "center": running_text_html(center or ""),
        "right": running_text_html(right or ""),
    }
    html, css = running_bar(
        "md-footer",
        "bottom",
        slots,
        mirror=_flag(config, "duplex"),
        font_size="7.5pt",
        color="#7f8c9a",
    )
    return html, css


# ---------------------------------------------------------------------------
# Margin-box mirroring for duplex pages
# ---------------------------------------------------------------------------

_BOX_RE = re.compile(r"@(top|bottom)-(left|center|right)\s*\{([^{}]*)\}", re.IGNORECASE)
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _split_declarations(body: str) -> dict[str, str]:
    """Split ``a: b; c: d`` honouring quotes and parentheses (``url(a;b)``)."""
    decls: dict[str, str] = {}
    current: list[str] = []
    quote = ""
    depth = 0
    for char in body + ";":
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == ";" and depth == 0:
            name, _, value = "".join(current).partition(":")
            if name.strip() and value.strip():
                decls[name.strip().lower()] = value.strip()
            current = []
        else:
            current.append(char)
    return decls


def _page_rule_bodies(css: str) -> list[str]:
    """Bodies of every unnamed, unfiltered ``@page { … }`` rule in *css*."""
    css = _COMMENT_RE.sub("", css)
    bodies: list[str] = []
    for start in re.finditer(r"@page\s*\{", css):
        depth, index = 1, start.end()
        while index < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[index], 0)
            index += 1
        bodies.append(css[start.end() : index - 1])
    return bodies


def _margin_boxes(*stylesheets: str) -> dict[str, dict[str, str]]:
    """Effective ``@top-*`` / ``@bottom-*`` declarations, later sheets overriding."""
    merged: dict[str, dict[str, str]] = {}
    for sheet in stylesheets:
        for body in _page_rule_bodies(sheet):
            for edge, slot, decls in _BOX_RE.findall(body):
                merged.setdefault(f"{edge}-{slot}", {}).update(_split_declarations(decls))
    return merged


def duplex_css(
    config: dict[str, Any],
    margins_mm: tuple[float, float],
    *stylesheets: str,
) -> str:
    """Facing-page CSS: mirrored margins with a binding gutter, mirrored header/footer slots.

    On left-hand pages the left and right margin boxes swap, so what you put in
    the ``right`` slot stays on the outside edge of the sheet.
    """
    if not _flag(config, "duplex"):
        return ""
    if _flag(config, "page_header_bar"):
        logger.warning(
            "duplex is ignored while page_header_bar is on: the bar's full-bleed offsets "
            "assume the same margins on every page."
        )
        return ""
    from .builders._assets import _length_to_mm

    left, right = margins_mm
    gutter_cfg = _length(config.get("binding_margin"))
    gutter = (_length_to_mm(gutter_cfg) if gutter_cfg else None) or 0.0
    inner = f"{left + gutter:g}mm"
    outer = f"{right:g}mm"
    rules = [
        f"@page :right {{ margin-left: {inner}; margin-right: {outer}; }}",
        f"@page :left {{ margin-left: {outer}; margin-right: {inner}; }}",
    ]
    boxes = _margin_boxes(*stylesheets)
    swapped: list[str] = []
    for edge in ("top", "bottom"):
        for here, there in (("left", "right"), ("right", "left")):
            source = boxes.get(f"{edge}-{there}")
            if source:
                # An explicit ``content`` is needed either way: a swapped-in box with
                # none would inherit the unswapped rule's text from the base @page.
                decls = {"content": "none", **source}
                decls["text-align"] = here
            else:
                decls = {"content": "none", "border": "none"}
            body = "; ".join(f"{name}: {value}" for name, value in decls.items())
            swapped.append(f"  @{edge}-{here} {{ {body}; }}")
    rules.append("@page :left {\n" + "\n".join(swapped) + "\n}")
    return "<style>\n" + "\n".join(rules) + "\n</style>"


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------


def uses_running_titles(*texts: str | None) -> bool:
    """True when any header/footer text uses ``{chapter}`` or ``{section}``."""
    return any(t and ("{chapter}" in t or "{section}" in t) for t in texts)


def _numbering_css(config: dict[str, Any], html_body: str) -> str:
    if not _flag(config, "numbered_headings"):
        return ""
    depth = _int(config.get("numbered_headings_depth"), 1, 4) or 3
    style = _choice(config.get("heading_number_style"), NUMBER_STYLES) or "decimal"
    start = number_start_level(html_body)
    levels = [start + i for i in range(depth) if start + i <= 6]
    names = [f"md-n{i + 1}" for i in range(len(levels))]

    def label(upto: int, target: str | None = None) -> str:
        parts: list[str] = []
        for i in range(upto + 1):
            fn = "target-counter" if target else "counter"
            where = f"{target}, " if target else ""
            if i == 0:
                parts.append(f"{fn}({where}{names[i]}, {style})")
            else:
                parts.append(f"{fn}({where}{names[i]})")
        return ' "." '.join(parts)

    rules = [f".report-body {{ counter-reset: {' '.join(names)}; }}"]
    for i, level in enumerate(levels):
        resets = " ".join(names[i + 1 :])
        reset = f" counter-reset: {resets};" if resets else ""
        rules.append(f".report-body h{level} {{ counter-increment: {names[i]};{reset} }}")
        trailing = '". "' if i == 0 else '" "'
        rules.append(f".report-body h{level}::before {{ content: {label(i)} {trailing}; }}")
        rules.append(
            f'.toc a.toc-n{i + 1}::before {{ content: {label(i, "attr(href url)")} " "; }}'
        )
    return "\n".join(rules)


def feature_css(
    config: dict[str, Any],
    *,
    html_body: str,
    cover_page: bool,
    margins_mm: tuple[float, float],
    stylesheets: tuple[str, ...] = (),
    running_titles: bool = False,
) -> str:
    """The ``<style>`` block for every CSS-level feature the config enables."""
    rules: list[str] = []
    page_rules: list[str] = []
    late_rules: list[str] = []  # must follow every other @page rule (same specificity)

    # PDF bookmarks (the outline pane). On by default; switch off to drop them.
    if _flag(config, "pdf_bookmarks", True):
        depth = _int(config.get("pdf_bookmark_depth"), 1, 6) or 3
        for level in range(1, 7):
            if level <= depth:
                rules.append(
                    f".report-body h{level} {{ bookmark-level: {level}; "
                    "bookmark-label: content(); }"
                )
            else:
                rules.append(f".report-body h{level} {{ bookmark-level: none; }}")
        if cover_page:
            rules.append(".cover-title { bookmark-level: 1; bookmark-label: content(); }")
    else:
        rules.append("h1, h2, h3, h4, h5, h6, .cover-title { bookmark-level: none; }")

    # A bar, quote or callout that splits across a page keeps its box on both halves.
    rules.append(
        ".callout, blockquote, pre, .report-body :is(h1, h2, h3, h4) "
        "{ box-decoration-break: clone; }"
    )

    # Review markup shown in the PDF (CriticMarkup ``show`` mode).
    if "critic-" in html_body:
        from .critic import CSS as critic_css

        rules.append(critic_css)

    # Typography.
    features = config.get("font_features")
    if features and _FEATURE_RE.match(str(features)):
        rules.append(f".report-body {{ font-feature-settings: {str(features).strip()}; }}")
    if _flag(config, "tabular_numbers"):
        rules.append(".report-body table :is(th, td) { font-variant-numeric: tabular-nums; }")
    if _flag(config, "hyphenate"):
        rules.append(
            ".report-body :is(p, li, dd, td, blockquote) { hyphens: auto; }\n"
            ".report-body :is(h1, h2, h3, h4, h5, h6, code, pre) { hyphens: manual; }"
        )

    # Running chapter / section titles for {chapter} / {section} header text.
    if running_titles:
        rules.append(
            ".report-body h1 { string-set: md-chapter content(text), md-section ''; }\n"
            ".report-body h2 { string-set: md-section content(text); }"
        )

    # Numbered headings (and matching contents entries).
    numbering = _numbering_css(config, html_body)
    if numbering:
        rules.append(numbering)

    # Real page-bottom footnotes.
    if _flag(config, "page_footnotes"):
        rules.append(
            ".md-footnote { float: footnote; font-size: 8pt; line-height: 1.35; }\n"
            "::footnote-call { content: counter(footnote); font-size: 70%; "
            "vertical-align: super; line-height: 0; }\n"
            "::footnote-marker { content: counter(footnote) '.'; font-size: 8pt; "
            "margin-right: 0.4em; }"
        )
        page_rules.append(
            "@footnote { border-top: 0.5pt solid #b0b7bf; padding-top: 3pt; margin-top: 6pt; }"
        )

    # Cross-references: empty links read the target's text; optionally add its page.
    rules.append(
        ".report-body a[href^='#']:empty::before "
        "{ content: target-text(attr(href url), content); }"
    )
    if _flag(config, "xref_pages"):
        rules.append(
            ".report-body a.md-xref::after "
            "{ content: ' (p. ' target-counter(attr(href url), page) ')'; }"
        )

    # Multi-column body and block directives.
    columns = _int(config.get("columns"), 2, 6)
    if columns:
        gap = _length(config.get("column_gap")) or "8mm"
        body = f"column-count: {columns}; column-gap: {gap};"
        rule = _safe_value(config.get("column_rule"))
        if rule:
            body += f" column-rule: {rule};"
        rules.append(f".report-body {{ {body} }}\n.report-body h1 {{ column-span: all; }}")
    rules.append(".md-columns { break-inside: auto; }\n.md-grid > * { margin-top: 0; }")

    # Images.
    fit = _choice(config.get("image_fit"), IMAGE_FITS)
    if fit:
        rules.append(f".report-body img {{ object-fit: {fit}; }}")
    resolution = _safe_value(config.get("image_resolution"))
    if resolution and re.fullmatch(r"\d+(?:\.\d+)?(?:dpi|dpcm|dppx|x)|from-image", resolution):
        rules.append(f".report-body img {{ image-resolution: {resolution}; }}")

    # Chapter starts.
    chapter = _choice(config.get("chapter_break"), CHAPTER_BREAKS)
    if chapter:
        rules.append(
            f".report-body h1:not([data-md-doc-first-heading]) {{ break-before: {chapter}; }}\n"
            ".report-body .md-doc-page-break + h1, "
            ".report-body .md-doc-page-break + .keep-with-next h1 { break-before: auto; }"
        )
        if chapter != "page":
            # Pages inserted to reach the requested side stay clean.
            blank = " ".join(
                f"@{edge}-{slot} {{ content: none; border: none; }}"
                for edge in ("top", "bottom")
                for slot in ("left", "center", "right")
            )
            late_rules.append(f"@page :blank {{ {blank} }}")

    # Print production.
    marks = _choice(config.get("print_marks"), PRINT_MARKS)
    bleed = _length(config.get("bleed"))
    if marks or bleed:
        parts = []
        if marks:
            parts.append(f"marks: {marks};")
        if bleed:
            parts.append(f"bleed: {bleed};")
        page_rules.append(" ".join(parts))

    # No header/footer on the first page of a cover-less document.
    if not _flag(config, "header_first_page", True) and not cover_page:
        boxes = " ".join(
            f"@{edge}-{slot} {{ content: none; border: none; }}"
            for edge in ("top", "bottom")
            for slot in ("left", "center", "right")
        )
        rules.append(f"@page :first {{ {boxes} }}")

    if page_rules:
        rules.append("@page {\n  " + "\n  ".join(page_rules) + "\n}")

    block = "<style>\n" + "\n".join(rules) + "\n</style>"
    duplex = duplex_css(config, margins_mm, *stylesheets)
    late = "<style>\n" + "\n".join(late_rules) + "\n</style>" if late_rules else ""
    return "\n".join(part for part in (block, duplex, late) if part)


# ---------------------------------------------------------------------------
# Layout inspection through the WeasyPrint Document API
# ---------------------------------------------------------------------------

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_LEAF_BOXES = {"TextBox", "InlineReplacedBox", "BlockReplacedBox"}


def _leaves(box: Any, heading: str | None = None, positioned: bool = False):
    """Yield ``(leaf_box, heading_tag_or_None, positioned)`` in document order.

    WeasyPrint boxes carry no parent pointer, so the enclosing heading and any
    absolute/fixed ancestor (header bars, the running date) are tracked on the
    way down.
    """
    tag = getattr(box, "element_tag", None)
    if tag in _HEADING_TAGS:
        heading = tag
    style = getattr(box, "style", None)
    if style is not None:
        try:
            positioned = positioned or style["position"] in {"absolute", "fixed"}
        except KeyError:  # pragma: no cover - anonymous boxes without the property
            pass
    if type(box).__name__ in _LEAF_BOXES:
        yield box, heading, positioned
    for child in getattr(box, "children", []) or []:
        yield from _leaves(child, heading, positioned)


def layout_findings(document: Any) -> list[str]:
    """Problems visible in the laid-out pages, as human-readable lines.

    Finds a heading stranded at the foot of a page, content running past the
    right margin (wide tables and images), and pages with no body content.
    """
    findings: list[str] = []
    total = len(document.pages)
    for number, page in enumerate(document.pages, start=1):
        page_box = page._page_box
        body = next((c for c in page_box.children if type(c).__name__ == "BlockBox"), None)
        if body is None:
            continue
        # Fixed/absolute boxes (header bars, the hidden running date) repeat on
        # every page and say nothing about the flowed content.
        leaves = [(box, tag) for box, tag, positioned in _leaves(body) if not positioned]
        has_content = any(
            type(box).__name__ != "TextBox" or str(getattr(box, "text", "")).strip()
            for box, _ in leaves
        )
        if not has_content:
            findings.append(f"page {number}: no body content (blank page)")
            continue
        right_edge = page_box.content_box_x() + page_box.width
        for box, _ in leaves:
            overflow = box.position_x + box.margin_width() - right_edge
            if overflow > 2:  # CSS px; ignore sub-pixel rounding
                findings.append(
                    f"page {number}: content runs {overflow * 25.4 / 96:.1f}mm past the right margin"
                )
                break
        last, heading = leaves[-1]
        if heading and number < total:
            words = [
                str(box.text).strip()
                for box, tag in leaves
                if tag == heading and type(box).__name__ == "TextBox"
            ]
            findings.append(
                f"page {number}: heading {' '.join(words[-3:])!r} is the last thing on the page"
            )
    return findings


def pdf_zoom(config: dict[str, Any]) -> float | None:
    """``pdf_zoom`` as a factor between 0.1 and 10, or None for the default of 1."""
    raw = config.get("pdf_zoom")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        zoom = float(raw)
    except (TypeError, ValueError):
        return None
    return zoom if 0.1 <= zoom <= 10 and zoom != 1 else None


def chain_finishers(*finishers: Callable[[Any, Any], None]) -> Callable[[Any, Any], None]:
    """One WeasyPrint ``finisher`` that runs each of *finishers* in order."""

    def run(document: Any, pdf: Any) -> None:
        for finisher in finishers:
            finisher(document, pdf)

    return run


def layout_check_finisher(*, strict: bool) -> Callable[[Any, Any], None]:
    """A ``finisher`` that inspects the laid-out pages before the PDF is written.

    Always logs the page count at debug level. With ``strict`` (the
    ``pdf_layout_check`` key) each finding is logged as a warning, which makes
    ``md-doc build`` print them and ``--quiet`` hide them.
    """

    def run(document: Any, pdf: Any) -> None:
        logger.debug("laid out %d page(s)", len(document.pages))
        if not strict:
            return
        try:
            findings = layout_findings(document)
        except Exception:  # pragma: no cover - never fail a build over a check
            logger.debug("layout check failed", exc_info=True)
            return
        for finding in findings:
            logger.warning("layout: %s", finding)

    return run


#: Change bar: colour, thickness and distance from the text edge, in CSS px.
_BAR_RGB = (0.812, 0.133, 0.18)
_BAR_WIDTH_PX = 3.5
_BAR_GAP_PX = 22.7  # 6 mm
_BAR_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"}
_LIST_TAGS = {"ul", "ol"}


def _changed_spans(page: Any) -> list[tuple[float, float]]:
    """Vertical ``(top, bottom)`` extents, in CSS px, of the blocks tagged ``critic-changed``."""
    spans: list[tuple[float, float]] = []

    def visit(box: Any) -> None:
        element = getattr(box, "element", None)
        if (
            element is not None
            and getattr(box, "element_tag", None) in _BAR_TAGS
            and type(box).__name__ in {"BlockBox", "TableRowBox"}
            and "critic-changed" in (element.get("class") or "")
        ):
            top = box.position_y + box.margin_top
            bottom = top + box.border_height()
            if getattr(box, "element_tag", None) == "li":
                # A list item's bar covers its own text, not a nested list under it.
                for child in getattr(box, "children", []):
                    if getattr(child, "element_tag", None) in _LIST_TAGS:
                        bottom = min(bottom, child.position_y)
                        break
            spans.append((top, bottom))
        for child in getattr(box, "children", []) or []:
            visit(child)

    visit(page._page_box)
    spans.sort()
    merged: list[tuple[float, float]] = []
    for top, bottom in spans:
        if merged and top <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], bottom))
        else:
            merged.append((top, bottom))
    return merged


def change_bars_finisher(zoom: float = 1.0) -> Callable[[Any, Any], None]:
    """A ``finisher`` that draws review change bars in the right-hand page margin.

    ``review_markup: simple`` tags every changed block ``critic-changed``. CSS cannot
    put a bar in the margin at one fixed distance whatever the nesting (lists,
    callouts, table rows), so each bar is drawn from the block's laid-out extent: a
    thin red strip a fixed distance beyond the text edge, in line from page top to
    bottom. A block split across pages gets a bar on each page.
    """
    scale = zoom * 0.75  # PDF points per CSS px, as WeasyPrint's own page streams use

    def run(document: Any, pdf: Any) -> None:
        import pydyf

        kids = list(pdf.pages["Kids"])
        page_numbers = [kids[i] for i in range(0, len(kids), 3)]  # flat "n 0 R" triples
        for page, number in zip(document.pages, page_numbers):
            spans = _changed_spans(page)
            if not spans:
                continue
            box = page._page_box
            right_edge = box.content_box_x() + box.width
            margin = max(0.0, page.width - right_edge)
            x = right_edge + min(_BAR_GAP_PX, margin * 0.6)
            red, green, blue = _BAR_RGB
            ops = ["/Artifact BMC", f"q {red} {green} {blue} rg"]
            for top, bottom in spans:
                ops.append(
                    f"{x * scale:.2f} {(page.height - bottom) * scale:.2f} "
                    f"{_BAR_WIDTH_PX * scale:.2f} {(bottom - top) * scale:.2f} re f"
                )
            ops.extend(["Q", "EMC"])  # decoration: an artifact for tagged/accessible PDFs
            stream = pydyf.Stream([" ".join(ops).encode()])
            pdf.add_object(stream)
            page_dict = pdf.objects[number]
            # Drawn first, in its own q/Q: the page's own stream keeps its graphics state.
            page_dict["Contents"] = pydyf.Array([stream.reference, page_dict["Contents"]])

    return run
