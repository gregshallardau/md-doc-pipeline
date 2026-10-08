"""
WeasyPrint PDF builder.

Converts rendered Markdown to a professional PDF report.

Public API
----------
    build(rendered_md, config, out_path, *, repo_root=None)

The ``rendered_md`` string is the Jinja2-processed Markdown body (including
frontmatter). Config comes from the cascading _meta.yml + frontmatter merge
performed by :func:`md_doc.config.load_config`.

Config keys consumed
--------------------
  title        — document title (falls back to first H1 in body)
  author       — author name shown on cover/footer  (default: "Document Producer")
  date         — date string for cover page          (default: today)
  pdf_theme    — path to CSS file, relative to repo root or absolute
                  (default: auto-generated _pdf-theme.css at repo root on first build)
"""

from __future__ import annotations

import datetime
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fonttools").setLevel(logging.ERROR)

import weasyprint  # noqa: E402

from ..config import coerce_bool  # noqa: E402
from ._cover import footer_band_geometry  # noqa: E402
from ..forms import collapse_select_markup  # noqa: E402
from ._assets import _drop_empty_table_headers, apply_theme_config_defaults  # noqa: E402


def _reject_external(url: str) -> None:
    """Raise unless *url* is embedded data or a local file (no host, no UNC path)."""
    parsed = urlsplit(url)
    path = unquote(parsed.path).replace("\\", "/")
    if parsed.scheme not in {"file", "data"} or parsed.netloc or path.startswith("//"):
        raise ValueError(f"External resource blocked: {parsed.scheme or 'relative'} URL")


def _local_url_fetcher(url: str, *args: Any, **kwargs: Any) -> Any:
    """Allow embedded data and local files only, before any network I/O.

    WeasyPrint applies this to images, stylesheets, fonts and nested SVG assets.
    Remote and UNC resources are omitted rather than fetched. Used with
    WeasyPrint before 70, where a ``url_fetcher`` is a plain function.
    """
    _reject_external(url)
    return weasyprint.default_url_fetcher(url, *args, **kwargs)


def _make_url_fetcher() -> Any:
    """The offline fetcher in the form the installed WeasyPrint expects.

    WeasyPrint 70 replaced ``default_url_fetcher`` and function fetchers with a
    ``URLFetcher`` class, whose instances carry state WeasyPrint reads.
    """
    fetcher_cls = getattr(weasyprint, "URLFetcher", None)
    if fetcher_cls is None:
        return _local_url_fetcher

    class _LocalURLFetcher(fetcher_cls):  # type: ignore[misc, valid-type]
        def fetch(self, url: str, headers: Any = None) -> Any:
            _reject_external(url)
            return super().fetch(url, headers)

    return _LocalURLFetcher(allowed_protocols={"file", "data"})


# Markdown extensions to enable
_MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    "footnotes",
    "def_list",
    "abbr",
    "attr_list",
    "md_in_html",
    "toc",
]


# ---------------------------------------------------------------------------
# Internal helpers (ported from document-designer/generate-pdf.py)
# ---------------------------------------------------------------------------


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


_CSS_COLOR_NAME_RE = re.compile(r"^[a-zA-Z]+$")


def _safe_css_color(value: Any, default: str) -> str:
    """Return *value* if it is a safe CSS colour, else *default*.

    Accepts ``#rgb``/``#rrggbb`` hex (normalised) and bare colour keywords
    (``red``, ``white``). Anything else — notably values containing CSS-control
    characters like ``;`` or ``}`` — is rejected to prevent style-block injection
    via author-supplied config.
    """
    if value is None:
        return default
    from ..theme import validate_hex_color

    s = str(value).strip()
    try:
        return validate_hex_color(s)
    except ValueError:
        if _CSS_COLOR_NAME_RE.match(s):
            return s.lower()
        logging.getLogger(__name__).warning(
            "Ignoring unsafe colour value %r — using %r.", value, default
        )
        return default


def _extract_title(md_content: str) -> str | None:
    """Return the first H1 heading from markdown, stripped of inline markup."""
    match = re.search(r"^#\s+(.+)$", md_content, re.MULTILINE)
    if not match:
        return None
    title = match.group(1).strip()
    title = re.sub(r"\*\*(.+?)\*\*", r"\1", title)
    title = re.sub(r"\*(.+?)\*", r"\1", title)
    title = re.sub(r"`(.+?)`", r"\1", title)
    return title


def _strip_leading_h1(md_content: str) -> str:
    """Remove the first H1 line (it becomes the cover title)."""
    return re.sub(r"^#\s+.+\n?", "", md_content, count=1, flags=re.MULTILINE)


def _inject_appendix_breaks(md_content: str) -> str:
    """Insert page-break markers before each H2 inside an APPENDIX section."""
    lines = md_content.split("\n")
    result: list[str] = []
    in_appendix = False

    for line in lines:
        if re.match(r"^#\s+APPENDIX\b", line, re.IGNORECASE):
            in_appendix = True
        elif re.match(r"^#\s+", line):
            in_appendix = False

        if in_appendix and re.match(r"^##\s+", line):
            result.extend(["", '<div class="appendix-template-break"></div>', ""])

        result.append(line)

    return "\n".join(result)


_PAGEBREAK_COMMENT_RE = re.compile(r"<!--\s*pagebreak\s*-->", re.IGNORECASE)


def _inject_page_breaks(md_content: str) -> str:
    """Convert ``<!-- pagebreak -->`` comments into a page-break div.

    The resulting div is recognised by the PDF theme CSS
    (``.md-doc-page-break``) and by the DOCX HTML walker, which emits a real
    Word page break. Surrounded by blank lines so the markdown parser treats
    it as a block-level element.
    """
    return _PAGEBREAK_COMMENT_RE.sub(
        '\n\n<div class="md-doc-page-break"></div>\n\n',
        md_content,
    )


_FORM_FIELD_RE = re.compile(r"\?\[(.+?)\]")
_ROW_OPEN_RE = re.compile(r"^\?\[row\]\s*$", re.MULTILINE)
_ROW_CLOSE_RE = re.compile(r"^\?\[/row\]\s*$", re.MULTILINE)
# ?[box] … ?[/box] — bordered field-grid (insurance-application style): every
# line is a row, cells split on |, labels/hints live INSIDE the bordered cell.
_BOX_OPEN_RE = re.compile(r"^\?\[box(?::\s*([^\]]*))?\]\s*$", re.MULTILINE)
_BOX_BLOCK_RE = re.compile(
    r"^\?\[box(?::\s*([^\]]*))?\]\s*\n(.*?)\n\?\[/box\]\s*$",
    re.MULTILINE | re.DOTALL,
)


def _parse_field_attrs(attr_str: str) -> dict[str, str | bool]:
    """Parse comma-separated key=value or bare flag attributes."""
    attrs: dict[str, str | bool] = {}
    for part in attr_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            attrs[k.strip()] = v.strip()
        else:
            attrs[part] = True
    return attrs


# Input types the ?[...] shorthand passes through verbatim; anything else
# falls back to a plain text input.
_INPUT_TYPES = ("text", "email", "date", "number", "tel", "url")


def _extra_attrs_html(attrs: dict[str, str | bool], skip: tuple[str, ...] = ()) -> str:
    """Render parsed field attrs as HTML attributes (safe names only)."""
    extra = ""
    for k, v in attrs.items():
        if k in skip:
            continue
        # Only emit attributes whose name is a safe HTML identifier, and never
        # event handlers — a crafted key like ``onfocus=alert(1)`` must not
        # become active markup.
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", k) or k.lower().startswith("on"):
            continue
        if v is True:
            extra += f" {k}"
        else:
            extra += f' {k}="{_escape_html(str(v))}"'
    return extra


def _field_to_html(field_spec: str) -> str:
    """Convert a single ?[type: name, ...] spec to HTML."""
    field_spec = field_spec.strip()

    submit = re.fullmatch(r"submit(?:(?:\s*:\s*|\s+)(.*))?", field_spec, re.IGNORECASE)
    if submit:
        label = (submit.group(1) or "").strip() or "Submit"
        return f'<input type="submit" value="{_escape_html(label)}">'
    if ":" not in field_spec:
        return f"<!-- unknown form field: {_escape_html(field_spec)} -->"

    type_part, rest = field_spec.split(":", 1)
    ftype = type_part.strip().lower()

    if ftype in ("select", "radio", "radio-inline", "checkbox-inline"):
        parts = [p.strip() for p in rest.split("|")]
        name = parts[0].split(",")[0].strip() if parts else "field"
        name_attrs = _parse_field_attrs(parts[0]) if parts else {}
        name = list(name_attrs.keys())[0] if name_attrs else "field"
        options = parts[1:] if len(parts) > 1 else []

        if ftype == "select":
            # One line: a multi-line <select> is split by the Markdown step and
            # leaves the surrounding keep-together container unclosed.
            opts_html = "".join(
                (
                    f'  <option value="{_escape_html(o.lower().replace(" ", "_"))}">{_escape_html(o)}</option>'
                    if not o.startswith("--")
                    else f'  <option value="">{_escape_html(o)}</option>'
                )
                for o in options
            )
            req = " required" if name_attrs.get("required") else ""
            return f'<select name="{_escape_html(name)}"{req}>{opts_html}</select>'

        elif ftype in ("radio", "radio-inline"):
            # Span-level markup: block-level <div>s inside generated table
            # cells get restructured by md_in_html, merging adjacent cells.
            inline = ftype == "radio-inline"
            sep = "\n" if inline else "<br>\n"
            items = []
            for o in options:
                val = o.lower().replace(" ", "_").replace("-", "_")
                items.append(
                    f'<label class="option-item"><input type="radio" '
                    f'name="{_escape_html(name)}" '
                    f'value="{_escape_html(val)}"> {_escape_html(o)}</label>'
                )
            return f'<span class="option-group">{sep.join(items)}</span>'

        elif ftype == "checkbox-inline":
            items = []
            for o in options:
                field_name = f"{name}_{o.lower().replace(' ', '_').replace('-', '_')}"
                items.append(
                    f'<label class="option-item">'
                    f'<input type="checkbox" name="{_escape_html(field_name)}"> '
                    f"{_escape_html(o)}</label>"
                )
            joined = "\n".join(items)
            return f'<span class="option-group">{joined}</span>'

        return f"<!-- unknown form field: {_escape_html(field_spec)} -->"

    else:
        parts = rest.split(",")
        name = parts[0].strip()
        attrs = _parse_field_attrs(",".join(parts[1:])) if len(parts) > 1 else {}

        req = " required" if attrs.get("required") else ""
        extra = _extra_attrs_html(attrs, skip=("required", "label", "rows"))

        if ftype == "textarea":
            rows = _escape_html(str(attrs.get("rows", "4")))
            return f'<textarea name="{_escape_html(name)}" rows="{rows}"{req}{extra}></textarea>'
        elif ftype == "checkbox":
            label_text = attrs.get("label", "")
            label_html = (
                f" {_escape_html(str(label_text))}" if label_text and label_text is not True else ""
            )
            return (
                f'<label class="option-item">'
                f'<input type="checkbox" name="{_escape_html(name)}"{req}{extra}>'
                f"{label_html}</label>"
            )
        elif ftype == "yesno":
            # Insurance-style Yes/No checkbox pair (fields <name>_yes / <name>_no).
            n = _escape_html(name)
            return (
                f'<span class="yesno">'
                f'<label><input type="checkbox" name="{n}_yes"> Yes</label>'
                f'<label><input type="checkbox" name="{n}_no"> No</label>'
                f"</span>"
            )
        elif ftype == "signature":
            return (
                f'<div class="signature-field">'
                f'<textarea name="{_escape_html(name)}" class="signature-input"{req}></textarea>'
                f'<div class="signature-line"></div>'
                f'<div class="signature-label">Signature</div>'
                f"</div>"
            )
        else:
            input_type = ftype if ftype in _INPUT_TYPES else "text"
            return f'<input type="{input_type}" name="{_escape_html(name)}"{req}{extra}>'


_BOLD_SPAN_RE = re.compile(r"\*\*(.+?)\*\*")
_EM_SPAN_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def _cell_to_html(cell: str) -> str:
    """Expand fields + inline ``**bold**``/``*italic*`` spans in a grid cell.

    Generated tables are raw HTML blocks, which python-markdown leaves
    untouched — so inline label markup must be converted here.
    """
    html = _FORM_FIELD_RE.sub(lambda m: _field_to_html(m.group(1)), cell)
    html = _BOLD_SPAN_RE.sub(r"<strong>\1</strong>", html)
    html = _EM_SPAN_RE.sub(r"<em>\1</em>", html)
    return html


_ROW_LABELLED_FIELD_RE = re.compile(r"^\*\*([^*]+)\*\*\s*(\?\[[^\]]*\])$")


def _row_cell_to_html(cell: str, captions: bool) -> str:
    """A ``**Label** ?[field]`` row cell becomes field + caption beneath the rule.

    Only in rows holding a signature: it matches the signature caption, so
    side-by-side signature and date cells line up instead of one label above and one below.
    """
    m = _ROW_LABELLED_FIELD_RE.match(cell) if captions else None
    if not m:
        return _cell_to_html(cell)
    return (
        f"{_cell_to_html(m.group(2))}"
        f'<div class="signature-label">{_escape_html(m.group(1))}</div>'
    )


def _expand_row_block(row_content: str) -> str:
    """Expand a ?[row]...?[/row] block into a borderless table.

    Cells may carry inline labels (``**City** ?[text: city]``) — bold/italic
    spans are converted here since the block is raw HTML to markdown.
    """
    lines = row_content.strip().split("\n")
    rows_html: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c]
        if not cells:
            continue

        captions = any(c.startswith("?[signature") for c in cells)
        n = len(cells)
        width = f"{100 // n}%"
        tds = []
        for i, cell in enumerate(cells):
            padding = (
                "0 8pt 4pt 0" if i == 0 else ("0 0 4pt 8pt" if i == n - 1 else "0 8pt 4pt 8pt")
            )
            tds.append(
                f'<td style="border: none; width: {width}; '
                f'padding: {padding}; vertical-align: top;">'
                f"{_row_cell_to_html(cell, captions)}</td>"
            )
        rows_html.append(f'<tr style="background: none;">{"".join(tds)}</tr>')

    return (
        f'<table class="field-row" style="border: none; width: 100%;">\n'
        f'{"".join(rows_html)}\n'
        f"</table>"
    )


_PREFIXED_FIELD_RE = re.compile(r"^([^\w\s*?\[]{1,3})\s*(\?\[[^\]]*\])$")


def _box_cell_to_html(cell: str) -> str:
    """``$ ?[number: x]`` keeps its currency prefix on the field's own line."""
    m = _PREFIXED_FIELD_RE.match(cell)
    if not m:
        return _cell_to_html(cell)
    return (
        f'<div class="prefixed-field"><span>{_escape_html(m.group(1))}</span>'
        f"{_cell_to_html(m.group(2))}</div>"
    )


def _expand_box_block(args: str | None, box_content: str) -> str:
    """Expand a ?[box]...?[/box] block into a bordered field-grid table.

    The insurance-application construct: every content line is a grid row,
    cells split on ``|``, and labels/hints live *inside* the bordered cell with
    the input filling the remaining space. ``?[box: widths=70,30]`` fixes the
    column proportions (otherwise cells share the row evenly).

    ```
    ?[box: widths=72,28]
    Do you require cover? *If No, go to Section 8* | ?[yesno: cover]
    How many horses do you agist at any one time? | ?[text: horse_count]
    ?[textarea: details, rows=4]
    ?[/box]
    ```
    """
    widths: list[float] = []
    if args:
        m = re.search(r"widths\s*=\s*([\d.,\s]+)", args)
        if m:
            try:
                widths = [float(w) for w in m.group(1).split(",") if w.strip()]
            except ValueError:
                widths = []
    total = sum(widths) if widths else 0.0

    # Parse rows first so short rows can span the full grid width (colspan).
    rows: list[list[str]] = []
    for line in box_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)

    rows_html: list[str] = []
    for cells in rows:
        n = len(cells)
        tds = []
        for i, cell in enumerate(cells):
            is_last = i == n - 1
            span = max_cols - n + 1 if is_last and n < max_cols else 1
            colspan = f' colspan="{span}"' if span > 1 else ""
            if widths and len(widths) == max_cols and total > 0 and span == 1:
                width_style = f' style="width: {widths[i] / total * 100:.2f}%;"'
            elif n == max_cols:
                width_style = f' style="width: {100 // max_cols}%;"'
            else:
                width_style = ""
            tds.append(f"<td{colspan}{width_style}>{_box_cell_to_html(cell)}</td>")
        # Question/answer rows (no **label** in any cell) centre vertically so a
        # Yes/No pair or a $ field lines up with its question; labelled rows
        # keep the label pinned to the top of the cell.
        qa = "" if any("**" in c for c in cells) else ' class="qa"'
        rows_html.append(f"<tr{qa}>{''.join(tds)}</tr>")

    body = "".join(rows_html)
    return f'<table class="field-box">\n{body}\n</table>'


# `?[checkbox: x] Label text` — the text trails the generated <label>, which
# leaves it outside the label (wide gap, not click-associated). Pull it in.
_SOLO_CHECKBOX_RE = re.compile(
    r'(<label class="option-item")(><input type="checkbox"[^>]*>)</label>[ \t]+([^<\s][^\n]*)$',
    re.MULTILINE,
)


def _fold_checkbox_label(m: re.Match[str]) -> str:
    return f'{m.group(1)[:-1]} option-solo"{m.group(2)} {m.group(3)}</label>'


def _expand_form_fields(md_content: str, is_form: bool) -> str:
    """Expand ?[...] form field markers into HTML.

    When is_form is True, also wraps the entire content in <form markdown="1">
    tags if not already present.
    """
    if not _FORM_FIELD_RE.search(md_content):
        return md_content

    def expand_rows(text: str) -> str:
        while _ROW_OPEN_RE.search(text):
            pattern = re.compile(
                r"^\?\[row\]\s*\n(.*?)\n\?\[/row\]\s*$",
                re.MULTILINE | re.DOTALL,
            )
            text = pattern.sub(lambda m: _expand_row_block(m.group(1)), text)
        return text

    def expand_boxes(text: str) -> str:
        while _BOX_OPEN_RE.search(text):
            new = _BOX_BLOCK_RE.sub(lambda m: _expand_box_block(m.group(1), m.group(2)), text)
            if new == text:  # unmatched ?[box] without ?[/box] — stop looping
                break
            text = new
        return text

    result = expand_boxes(md_content)
    result = expand_rows(result)
    result = _FORM_FIELD_RE.sub(lambda m: _field_to_html(m.group(1)), result)
    result = _SOLO_CHECKBOX_RE.sub(_fold_checkbox_label, result)

    if is_form and "<form" not in result.lower():
        result = '<form markdown="1">\n\n' + result + "\n\n</form>"

    return result


_BLOCK_TAG = r"(?:p|pre|ul|ol|table|blockquote|div|dl)"
_BLOCK_RE = re.compile(rf"(<{_BLOCK_TAG}[^>]*>.*?</{_BLOCK_TAG}>)", re.DOTALL)

# Forced page-break markers must never be pulled into a keep-together
# container: a forced break inside break-inside:avoid makes WeasyPrint push
# the whole container to a fresh page (stranding the heading alone) and can
# emit an entirely blank page.
_BREAK_DIV_MARKERS = ("md-doc-page-break", "appendix-template-break")


_LABEL_TEXTAREA_RE = re.compile(
    r"(<p>(?:(?!</p>).)*</p>)(\s*)(<textarea\b.*?</textarea>)", re.DOTALL
)


def _group_label_with_textarea(html_body: str) -> str:
    """Wrap ``<p>label</p><textarea>`` pairs so a label is never stranded.

    Python-Markdown emits a ``<textarea>`` as its own block after the label's
    paragraph, so nothing ties the two together across a page break.
    """
    return _LABEL_TEXTAREA_RE.sub(
        lambda m: f'<div class="field-group">{m.group(1)}{m.group(2)}{m.group(3)}</div>',
        html_body,
    )


_PAIRED_TAGS = ("div", "select", "textarea", "form", "table", "ul", "ol", "blockquote", "pre", "dl")


def _balanced_html(fragment: str) -> bool:
    """True when every paired tag in *fragment* is opened and closed equally often.

    A keep-together wrapper around a fragment that opens a tag it never closes
    (a ``<select>`` split by the Markdown step, say) would be unable to close
    its own ``</div>`` and would swallow the rest of the document.
    """
    lowered = fragment.lower()
    return all(
        len(re.findall(rf"<{tag}\b", lowered)) == len(re.findall(rf"</{tag}\s*>", lowered))
        for tag in _PAIRED_TAGS
    )


def _keep_heading_with_next(html_body: str) -> str:
    """Wrap each heading + up to two following block elements in a keep-together div.

    WeasyPrint can ignore CSS break-after:avoid on headings when the next
    element is large.  Wrapping both in a container with break-inside:avoid
    forces them onto the same page.  We grab up to two siblings to handle
    the common pattern: heading → short intro paragraph → code/table block.

    Everything between the heading and the last grouped block stays inside the
    container in document order. A horizontal rule ends a section, so grouping
    stops there rather than binding a heading to the next section's content.
    """
    heading_re = re.compile(r"(<h[2-4][^>]*>.*?</h[2-4]>)", re.DOTALL)
    parts = heading_re.split(html_body)
    result: list[str] = []

    i = 0
    while i < len(parts):
        if heading_re.fullmatch(parts[i]):
            heading = parts[i]
            tail = parts[i + 1] if i + 1 < len(parts) else ""
            grouped: list[re.Match[str]] = []
            previous_end = 0
            for match in _BLOCK_RE.finditer(tail):
                if "<hr" in tail[previous_end : match.start()]:
                    break
                grouped.append(match)
                previous_end = match.end()
                if len(grouped) == 2:
                    break
            while grouped and not _balanced_html("".join(m.group(0) for m in grouped)):
                grouped.pop()
            # Stop collecting at the first forced page-break div.
            cut = next(
                (
                    idx
                    for idx, m in enumerate(grouped)
                    if any(marker in m.group(0) for marker in _BREAK_DIV_MARKERS)
                ),
                None,
            )
            if cut is not None:
                grouped = grouped[:cut]
            if grouped:
                end = grouped[-1].end()
                result.append(f'<div class="keep-with-next">{heading}{tail[:end]}</div>')
                result.append(tail[end:])
            else:
                result.append(heading)
                result.append(tail)
            i += 2
        else:
            result.append(parts[i])
            i += 1

    return "".join(result)


def _resolve_logo(
    logo_val: str | None, repo_root: Path | None, doc_path: Path | None
) -> Path | None:
    """Resolve header_logo to an absolute path, searching doc dir → ancestors → repo root.

    Absolute paths and traversal components (``..``) are rejected to prevent
    reading arbitrary files from the filesystem via frontmatter config.
    """
    if not logo_val:
        return None
    # Security: reject absolute paths and traversal components
    if Path(logo_val).is_absolute() or ".." in Path(logo_val).parts:
        logging.getLogger(__name__).warning(
            "Ignoring logo path %r — absolute paths and '..' components are not allowed.",
            logo_val,
        )
        return None
    search_dirs: list[Path] = []
    if doc_path is not None:
        doc_dir = doc_path.parent if doc_path.is_file() else doc_path
        search_dirs.append(doc_dir)
        if repo_root:
            try:
                rel = doc_dir.relative_to(repo_root)
                for i in range(len(rel.parts) - 1, 0, -1):
                    search_dirs.append(repo_root / Path(*rel.parts[:i]))
            except ValueError:
                pass
    if repo_root:
        search_dirs.append(repo_root)
    for d in search_dirs:
        candidate = (d / logo_val).resolve()
        # Security: ensure resolved path stays within repo_root or doc directory
        if repo_root and not candidate.is_relative_to(repo_root.resolve()):
            continue
        if candidate.exists():
            return candidate
    return None


def _build_cover(
    title: str,
    author: str,
    date_str: str,
    cover_cfg: dict[str, Any],
    logo_uri: str | None,
    bar_logo_uri: str | None = None,
    primary_color: str | None = None,
) -> str:
    """Build a composable cover page from individual element config keys."""
    label = cover_cfg.get("cover_label", "Report")
    text_align = cover_cfg.get("cover_text_align", "left")
    bg = cover_cfg.get("cover_background", "white")
    meta_label = cover_cfg.get("cover_meta_label", "Prepared by")
    meta_author = cover_cfg.get("cover_meta_author", author)
    footer_text = cover_cfg.get("cover_footer_text") or f"{author}  ·  Confidential"
    show_footer = cover_cfg.get("cover_footer", True)
    show_footer_line = cover_cfg.get("cover_footer_line", True)
    footer_color = cover_cfg.get("cover_footer_color")
    show_divider = cover_cfg.get("cover_divider", True)
    text_on_bar = cover_cfg.get("cover_text_on_bar", False)
    show_bar = cover_cfg.get("cover_bar", True)
    bar_pos = cover_cfg.get("cover_bar_position", "top")
    bar_height = cover_cfg.get("cover_bar_height", "10mm")
    bar_top_height = cover_cfg.get("cover_bar_top_height", bar_height)
    bar_bottom_height = cover_cfg.get("cover_bar_bottom_height", bar_height)
    show_stripe = cover_cfg.get("cover_stripe", False)
    stripe_height = cover_cfg.get("cover_stripe_height", "120mm")
    stripe_width = cover_cfg.get("cover_stripe_width", "6mm")

    align_class = f"cover-align-{text_align}"

    bg_style = ""
    if bg not in ("white", "#ffffff", "#fff"):
        bg_style = f' style="background: {bg};"'

    bar_top = ""
    bar_bottom = ""
    if show_bar:
        if bar_pos == "both":
            bar_top = f'<div class="cover-bar" style="height: {bar_top_height};"></div>'
            bar_bottom = f'<div class="cover-bar cover-bar-bottom" style="height: {bar_bottom_height};"></div>'
        elif bar_pos == "bottom":
            bar_bottom = f'<div class="cover-bar cover-bar-bottom" style="height: {bar_bottom_height};"></div>'
        else:
            bar_top = f'<div class="cover-bar" style="height: {bar_top_height};"></div>'

    stripe_html = ""
    if show_stripe:
        stripe_html = f'<div class="cover-stripe" style="height: {stripe_height}; width: {stripe_width};"></div>'

    logo_html = f'<img class="cover-logo" src="{logo_uri}">' if logo_uri else ""

    divider_html = '<hr class="cover-divider">' if show_divider else ""

    text_on_bar_class = " cover-text-on-bar" if text_on_bar else ""
    footer_line_class = " cover-footer-no-line" if not show_footer_line else ""
    footer_styles = [f"color: {footer_color};"] if footer_color else []
    band_footer = footer_band_geometry(cover_cfg, _parse_mm(bar_bottom_height, 10.0))
    if band_footer:
        footer_styles.append(f"bottom: {band_footer[0]}mm; line-height: 13.2pt;")
    footer_color_style = ' style="' + " ".join(footer_styles) + '"' if footer_styles else ""
    footer_inner = (
        f'<div class="cover-footer{footer_line_class}"{footer_color_style}>{_escape_html(footer_text)}</div>'
        if show_footer
        else ""
    )

    content_block = f"""\
    <div class="cover-content">
      {logo_html}
      <p class="cover-label">{_escape_html(label)}</p>
      <h1 class="cover-title">{_escape_html(title)}</h1>
      {divider_html}
      <p class="cover-meta">
        <strong>{_escape_html(meta_label)}</strong> {_escape_html(meta_author)}<br>
        <strong>Date</strong> {_escape_html(date_str)}
      </p>
    </div>"""

    if text_on_bar and show_bar and bar_pos in ("top", "both"):
        wrapper_bg = _safe_css_color(primary_color, "#2563eb")
        body_inner = f"""\
    <div class="cover-bar-wrapper" style="background: {wrapper_bg}; min-height: {bar_top_height};">
{content_block}
    </div>"""
    else:
        body_inner = f"""\
    {bar_top}
    {stripe_html}
{content_block}"""

    bar_logo_html = f'<img class="cover-bar-logo" src="{bar_logo_uri}">' if bar_logo_uri else ""

    has_bottom_bar = show_bar and bar_pos in ("bottom", "both")
    if has_bottom_bar and show_footer:
        bottom_section = f"""\
    <div class="cover-bar cover-bar-bottom cover-bar-footer" style="height: {bar_bottom_height};">
      <div class="cover-bar-decor"></div>
      {bar_logo_html}
    </div>
    {footer_inner}"""
    elif has_bottom_bar and bar_logo_html:
        bottom_section = f"""\
    <div class="cover-bar cover-bar-bottom" style="height: {bar_bottom_height};">
      <div class="cover-bar-decor"></div>
      {bar_logo_html}
    </div>"""
    else:
        bottom_section = f"    {bar_bottom}\n    {footer_inner}"

    return f"""
  <div class="cover {align_class}{text_on_bar_class}"{bg_style}>
{body_inner}
{bottom_section}
  </div>
"""


def _parse_mm(value: Any, default: float) -> float:
    """Parse a '10mm'-style config value to mm (bare numbers are mm)."""
    from ._assets import _length_to_mm

    parsed = _length_to_mm(str(value)) if value is not None else None
    return parsed if parsed is not None else default


def _logo_resolution_dpi(path: Path, target_mm: float, *, forced: bool = False) -> float | None:
    """DPI that makes the image at *path* render *target_mm* tall.

    WeasyPrint renders margin-box logos (``content: url(…)``) at intrinsic
    pixel size (96dpi) and CSS height/max-height cannot constrain them — a
    high-resolution logo blows out the page header. CSS ``image-resolution``
    *is* honoured, so a computed DPI scales the logo exactly, at full quality.

    Returns ``None`` when no scaling is needed (image already fits and no
    explicit height was configured) or the image can't be read.
    """
    try:
        from PIL import Image

        with Image.open(path) as im:
            intrinsic_mm = im.height / 96 * 25.4
            if not forced and intrinsic_mm <= target_mm:
                return None
            return im.height / target_mm * 25.4
    except Exception:
        return None


def _collect_form_field_meta(html_body: str) -> dict[str, dict[str, Any]]:
    """Collect per-field metadata WeasyPrint drops from the generated PDF.

    WeasyPrint 68.x carries ``value``/``checked``/``maxlength`` into the
    AcroForm, but silently ignores ``required``, ``readonly``, ``title``
    (tooltip) and a ``<select>``'s ``selected`` option. We collect those from
    the final HTML (works for both raw-HTML forms and ``?[...]`` shorthand)
    and patch them into the PDF via the ``finisher`` hook.
    """
    from html.parser import HTMLParser

    meta: dict[str, dict[str, Any]] = {}

    class _P(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self._select: str | None = None

        def handle_starttag(self, tag: str, attrs: list) -> None:
            a = dict(attrs)
            name = a.get("name")
            if tag in ("input", "textarea", "select") and name:
                entry = meta.setdefault(name, {})
                if "required" in a:
                    entry["required"] = True
                if "readonly" in a:
                    entry["readonly"] = True
                if a.get("title"):
                    entry["tooltip"] = a["title"]
                if tag == "select":
                    self._select = name
            elif tag == "option" and self._select and "selected" in a:
                value = a.get("value")
                if value is None:
                    self._pending_option = True  # value = option text
                else:
                    meta.setdefault(self._select, {})["default"] = value

        def handle_data(self, data: str) -> None:
            if getattr(self, "_pending_option", False) and self._select:
                meta.setdefault(self._select, {})["default"] = data.strip()
                self._pending_option = False

        def handle_endtag(self, tag: str) -> None:
            if tag == "select":
                self._select = None

    _P().feed(html_body)
    return {k: v for k, v in meta.items() if v}


def _make_forms_finisher(field_meta: dict[str, dict[str, Any]]):
    """Build a WeasyPrint ``finisher`` that patches AcroForm field dicts.

    Sets ``/Ff`` bit 1 (ReadOnly) and bit 2 (Required), ``/TU`` (tooltip,
    shown by viewers on hover and read by screen readers) and ``/V`` for a
    select's default option — none of which WeasyPrint 68.x writes itself.
    """

    def finisher(document: Any, pdf: Any) -> None:
        import pydyf

        for obj in pdf.objects:
            try:
                if not isinstance(obj, pydyf.Dictionary) or "FT" not in obj:
                    continue
                t = obj.get("T")
                name = t.string if hasattr(t, "string") else None
                if not name or name not in field_meta:
                    continue
                entry = field_meta[name]
                flags = int(obj.get("Ff", 0) or 0)
                if entry.get("readonly"):
                    flags |= 1  # bit 1 — ReadOnly
                if entry.get("required"):
                    flags |= 2  # bit 2 — Required
                if flags:
                    obj["Ff"] = flags
                if entry.get("tooltip"):
                    obj["TU"] = pydyf.String(entry["tooltip"])
                if entry.get("default") and obj.get("FT") == "/Ch":
                    obj["V"] = pydyf.String(entry["default"])
            except Exception:  # never let metadata patching break the build
                logging.getLogger(__name__).warning(
                    "pdf forms: could not patch field metadata", exc_info=True
                )

    return finisher


# Always-on layout fixes, independent of the theme file's age:
# the FIRST H1 of the body must not force a page break — with a letterhead
# include before it, the theme's `h1 { page-break-before: always }` would
# otherwise strand the letterhead alone on a near-blank page 1.
# - adjacent tables must never render flush: with a theme that sets no
#   `table { margin }`, two separate tables looked like one merged grid.
#   Vertical margins collapse, so themes that already space tables are not
#   double-spaced.
_BASE_FIXES_CSS = (
    "<style>\n"
    ".report-body > h1:first-of-type { page-break-before: auto; }\n"
    ".report-body h1[data-md-doc-first-heading] { page-break-before: auto; break-before: auto; }\n"
    ".running-date { display: block; position: absolute; visibility: hidden; width: 0; height: 0; overflow: hidden; }\n"
    ".report-body table + table { margin-top: 10pt; }\n"
    # WeasyPrint does not reliably carry break-inside:avoid from a keep-together
    # wrapper down to a list inside it, and then splits a heading's short list
    # across pages. Say it on the lists themselves.
    ".report-body .keep-with-next > ul, .report-body .keep-with-next > ol, "
    ".report-body .keep-with-next > dl { break-inside: avoid; page-break-inside: avoid; }\n"
    ".report-body .md-doc-page-break + h1, .report-body .md-doc-page-break + .keep-with-next h1 { page-break-before: auto; break-before: auto; }\n"
    "</style>"
)

# Injected only for pdf_forms documents. Provides the insurance-form
# constructs (?[box] field grids, ?[yesno:] pairs) and fixes the signature
# block. Rules and labels take the theme's primary colour (__RULE__ etc. are
# filled in by _form_support_css); ordinary tables keep the report styling.
_FORM_SUPPORT_CSS = """<style>
/* Forms don't show the running date used by report footers */
.running-date { display: none; }
/* A label and its separate textarea block never split across pages */
.report-body .field-group { page-break-inside: avoid; break-inside: avoid; }
/* Bordered field-grid (?[box] … ?[/box]) — crisp black rules, labels inside
   the cells, deterministic row heights so the grid has an even rhythm */
table.field-box { width: 100%; border-collapse: collapse; border: 1pt solid __RULE__; border-radius: 0; margin: 3pt 0 10pt 0; page-break-inside: auto; }
table.field-box td { border: 0.5pt solid __RULE_SOFT__; background: none; vertical-align: top; line-height: 1.3; }
table.field-box tr:nth-child(even) td { background: none; }
table.field-box tr { page-break-inside: avoid; }
table.field-box tr.qa td { vertical-align: middle; }
table.field-box .prefixed-field { display: flex; align-items: center; }
table.field-box .prefixed-field > span { margin-right: 0.3em; }
table.field-box .prefixed-field > input { flex: 1; width: auto; }
table.field-box strong { font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.04em; color: __PRIMARY__; }
table.field-box em { font-size: 0.8em; }
table.field-box input[type="text"], table.field-box input[type="email"],
table.field-box input[type="date"], table.field-box input[type="number"],
table.field-box input[type="tel"], table.field-box input[type="url"],
table.field-box select {
  appearance: auto; border: none; background: transparent; border-radius: 0;
  width: 100%; height: 1.5em; margin: 0; padding: 0 0.1em; font-size: inherit;
}
/* A bare write-in row (input with no label in the cell) gets a taller band */
table.field-box td > input:only-child { height: 2.3em; }
table.field-box textarea {
  appearance: auto; border: none; background: transparent; border-radius: 0;
  width: 100%; margin: 0; padding: 0.1em; font-size: inherit; resize: none;
}
/* Borderless side-by-side cells (?[row]) — bare inputs show a writing rule */
table.field-row td > input[type="text"], table.field-row td > input[type="email"],
table.field-row td > input[type="date"], table.field-row td > input[type="number"],
table.field-row td > input[type="tel"], table.field-row td > input[type="url"] {
  border: none; border-bottom: 1pt solid __PRIMARY__; box-sizing: border-box; max-width: 100%;
}
/* Fillable cells inside those tables */
table td > input[type="text"], table td > input[type="email"],
table td > input[type="date"], table td > input[type="number"],
table td > input[type="tel"], table td > input[type="url"],
table td > textarea, table td > select {
  appearance: auto; border: none; background: transparent; border-radius: 0;
  width: 100%; height: 1.4em; margin: 0; padding: 0 0.1em; font-size: inherit;
}
/* Controls sharing a row (labelled form-groups) take one fixed height, so a
   <select> never makes its row taller than the text-input rows around it */
.form-group input[type="text"], .form-group input[type="email"],
.form-group input[type="date"], .form-group input[type="number"],
.form-group input[type="tel"], .form-group input[type="url"],
.form-group select {
  box-sizing: border-box; height: 2em; margin: 0; padding: 0 0.6em;
}
/* Checkboxes sit inline beside their label (the UA form stylesheet makes
   inputs block-level, which strands the label on the next line) */
input[type="checkbox"], input[type="radio"] {
  display: inline-block; font-size: inherit; width: 1.1em; height: 1.1em;
  margin: 0.1em 0.5em 0.1em 0.1em; vertical-align: middle;
  position: relative; top: -0.1em; /* box centre on the label cap-height centre, not the x-height */
}
/* Checkbox / radio items — span-level so table cells survive md_in_html */
label.option-item { display: inline-block; margin: 0.2em 1.2em 0.2em 0; }
label.option-solo { margin-right: 0; }
.option-group { line-height: 1.9; }
/* Yes/No checkbox pair (?[yesno: name]) */
.yesno { white-space: nowrap; }
.yesno label { display: inline; margin-right: 1.4em; }
/* Signature block — transparent field over a single rule, kept on one page */
.signature-field { page-break-inside: avoid; margin: 1.2em 0 1.4em 0; width: 60%; }
table.field-row .signature-field { width: 100%; margin: 0; }
table.field-row .signature-input { border-bottom: 1pt solid __PRIMARY__; }
table.field-row .signature-line { display: none; }
table.field-row { margin: 0.6em 0 1.2em 0; }
table.field-row td { vertical-align: bottom !important; }
table.field-row .signature-label { font-size: 0.7em; color: __PRIMARY__; font-weight: 700; letter-spacing: 0.07em; }
input[type="checkbox"], input[type="radio"] { border: 0.75pt solid __RULE__; }
.signature-input {
  appearance: auto; display: block; width: 100%; height: 2.6em; min-height: 2.6em; font-size: inherit;
  border: none; border-bottom: 1pt solid #555555; border-radius: 0;
  background: transparent; margin: 0; padding: 0.2em 0; resize: none;
}
.signature-line { display: none; }
.signature-label { font-size: 0.75em; letter-spacing: 0.2em; text-transform: uppercase; color: #7f8c9a; margin-top: 0.4em; }
</style>"""


def form_rule_colors(primary: str | None) -> tuple[str, str, str]:
    """``(label/primary, outer rule, inner rule)`` colours of the form grids.

    Shared with the Word builder so both formats draw the same tints.
    """
    from ..mermaid import _lighten

    try:
        base = primary or "#2c3e50"
        return base, _lighten(base, 0.45), _lighten(base, 0.7)
    except ValueError:
        return "#2c3e50", "#8a97a3", "#c5ccd3"


def _form_support_css(primary: str | None) -> str:
    base, rule, soft = form_rule_colors(primary)
    return (
        _FORM_SUPPORT_CSS.replace("__RULE_SOFT__", soft)
        .replace("__RULE__", rule)
        .replace("__PRIMARY__", base)
    )


def _build_html(
    title: str,
    date_str: str,
    author: str,
    html_body: str,
    css_path: Path,
    *,
    cover_page: bool = False,
    cover_cfg: dict[str, Any] | None = None,
    cover_logo_uri: str | None = None,
    cover_bar_logo_uri: str | None = None,
    header_logo_uri: str | None = None,
    header_logo_position: str = "right",
    header_text: str | None = None,
    header_text_position: str = "left",
    page_header_bar: dict[str, Any] | None = None,
    full_config: dict[str, Any] | None = None,
    footer_left: str | None = None,
    footer_center: str | None = None,
    footer_right: str | None = None,
    primary_color: str | None = None,
    css_vars_style: str = "",
    is_form: bool = False,
    header_logo_dpi: float | None = None,
    header_logo_max_mm: float | None = None,
    page_margins_mm: tuple[float, float] = (25.0, 20.0),
    page_size_mm: tuple[float, float] = (210.0, 297.0),
    theme_body_justify: bool = False,
) -> str:
    css_uri = css_path.as_uri()

    header_style = _build_header_style(
        header_logo_uri,
        header_logo_position,
        header_text,
        header_text_position,
        page_header_bar=page_header_bar,
        logo_dpi=header_logo_dpi,
    )

    section_bar_style = _build_section_bar_style(full_config or {})
    body_align_style = _build_body_align_style(full_config or {}, theme_body_justify)
    page_bar_html, page_bar_css = _build_page_header_bar_elements(
        page_header_bar,
        header_text=header_text,
        header_text_position=header_text_position,
        header_logo_uri=header_logo_uri,
        header_logo_position=header_logo_position,
        logo_max_mm=header_logo_max_mm,
        margin_left_mm=page_margins_mm[0],
        margin_right_mm=page_margins_mm[1],
    )

    footer_style = _build_footer_style(footer_left, footer_center, footer_right)

    cover_html = ""
    cover_support_style = ""
    cover_base_style = ""
    if cover_page:
        from ..theme import generate_default_theme

        defaults = generate_default_theme()
        cover_rules = defaults[
            defaults.index(".cover {") : defaults.index(
                "/* ============================================\n   HEADINGS"
            )
        ]
        cover_page_rules = defaults[
            defaults.index("@page cover {") : defaults.index(
                "/* ============================================\n   BASE"
            )
        ]
        cover_base_style = (
            f"<style>html, body {{ margin: 0; padding: 0; }}{cover_page_rules}{cover_rules}</style>"
        )
        cover_html = f"  <!-- COVER PAGE -->\n{_build_cover(title, author, date_str, cover_cfg or {}, cover_logo_uri, bar_logo_uri=cover_bar_logo_uri, primary_color=primary_color)}"
        # Behaviour classes the cover HTML emits (cover_text_align,
        # cover_footer_line) — injected here rather than relying on the theme
        # file so pre-existing generated themes honour these config keys too.
        cover_support_style = (
            "<style>\n"
            ".cover-label { line-height: 1.2; }\n"
            ".cover-text-on-bar .cover-label, .cover-text-on-bar .cover-title, .cover-text-on-bar .cover-meta, .cover-text-on-bar .cover-meta strong { color: white; }\n"
            ".cover-text-on-bar .cover-divider { border-top-color: white; }\n"
            ".cover-logo { display: inline-block; max-width: 50mm; max-height: 20mm; margin: 0 0 4mm; }\n"
            ".cover-bar-logo { position: absolute; right: 30mm; top: 50%; transform: translateY(-50%); max-height: 70%; max-width: 50mm; }\n"
            ".cover-bar-bottom { position: absolute; bottom: 0; left: 0; }\n"
            f".cover {{ width: {page_size_mm[0]}mm; height: {page_size_mm[1]}mm; }}\n"
            ".cover-align-right { text-align: right; }\n"
            ".cover-align-right .cover-divider { margin-left: auto; }\n"
            ".cover-align-center { text-align: center; }\n"
            ".cover-align-center .cover-divider { margin-left: auto; margin-right: auto; }\n"
            ".cover-footer-no-line { border-top: none !important; padding-top: 0; }\n"
            "</style>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{_escape_html(title)}</title>
  {cover_base_style}
  <link rel="stylesheet" href="{css_uri}">
  {_BASE_FIXES_CSS}
  {header_style}
  {footer_style}
  {section_bar_style}
  {body_align_style}
  {cover_support_style}
  {_form_support_css(primary_color) if is_form else ""}
  {css_vars_style}
  {page_bar_css}
</head>
<body>
{cover_html}
  {page_bar_html}
  <!-- REPORT BODY -->
  <div class="report-body">
    <span class="running-date">{_escape_html(date_str)}</span>
    {html_body}
  </div>

</body>
</html>"""


_HEADER_POSITIONS = {"left": "@top-left", "center": "@top-center", "right": "@top-right"}

_FOOTER_POSITIONS = {
    "left": "@bottom-left",
    "center": "@bottom-center",
    "right": "@bottom-right",
}


_PAGE_TOKEN_RE = re.compile(r"(\{pages?\})")


def _css_string(text: str) -> str:
    """Escape *text* for use inside a single-quoted CSS string.

    HTML-escapes first (so ``&``/``<``/``>``/``"`` are safe), then escapes
    backslash and single-quote — which would otherwise break out of the
    ``content: '...'`` string — and converts newlines to the CSS ``\\A`` escape.
    """
    return _escape_html(text).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\A ")


def _css_content_value(text: str) -> str:
    """Build a CSS ``content`` value, expanding ``{page}``/``{pages}`` tokens.

    Literal segments become quoted strings; ``{page}``/``{pages}`` become
    ``counter(page)``/``counter(pages)`` so PDF page numbers work with the same
    tokens the docx footer understands.
    """
    out: list[str] = []
    for part in _PAGE_TOKEN_RE.split(text):
        if part == "{page}":
            out.append("counter(page)")
        elif part == "{pages}":
            out.append("counter(pages)")
        elif part:
            out.append(f"'{_css_string(part)}'")
    return " ".join(out) if out else "''"


def _build_footer_style(
    left: str | None,
    center: str | None,
    right: str | None,
) -> str:
    """Generate an inline <style> block for page footer margin boxes.

    Each slot (left, center, right) is optional. Slots not provided are omitted
    so that _theme.css retains control of them. Empty string suppresses the
    theme's default for that slot. The cover page always suppresses any slot
    that has content.

    Newlines in text are converted to CSS \\A (line break in generated content).
    """
    slots = [
        ("@bottom-left", left),
        ("@bottom-center", center),
        ("@bottom-right", right),
    ]
    active = [(pos, text) for pos, text in slots if text is not None]

    if not active:
        return ""

    rules: list[str] = []
    cover_overrides: list[str] = []
    for pos, text in active:
        if text:
            rules.append(
                f"  {pos} {{ content: {_css_content_value(text)}; "
                f"white-space: pre; font-size: 6pt; line-height: 1.3; color: #7f8c9a; }}"
            )
        else:
            rules.append(f"  {pos} {{ content: none; }}")
        cover_overrides.append(f"  {pos} {{ content: none; }}")

    lines = ["<style>", "@page {"]
    lines.extend(rules)
    lines.append("}")
    lines.append("@page cover {")
    lines.extend(cover_overrides)
    lines.append("}")
    lines.append("</style>")
    return "\n".join(lines)


def _build_header_style(
    logo_uri: str | None,
    logo_position: str,
    text: str | None,
    text_position: str,
    page_header_bar: dict[str, Any] | None = None,
    logo_dpi: float | None = None,
) -> str:
    """Generate an inline <style> block for page header margin boxes."""
    rules: list[str] = []
    cover_overrides: list[str] = []

    bar = page_header_bar or {}
    bar_enabled = bar.get("enabled", False)

    if bar_enabled:
        for pos_name in ("@top-left", "@top-center", "@top-right"):
            rules.append(f"  {pos_name} {{ content: none; border-bottom: none; }}")
        for pos_name in ("@top-left", "@top-center", "@top-right"):
            cover_overrides.append(f"  {pos_name} {{ content: none; border: none; }}")
    else:
        if logo_uri:
            pos = _HEADER_POSITIONS.get(logo_position, "@top-right")
            # image-resolution scales the logo to the target height — CSS
            # height/max-height cannot constrain margin-box content images.
            res = f" image-resolution: {logo_dpi:.1f}dpi;" if logo_dpi else ""
            rules.append(f"  {pos} {{ content: url('{logo_uri}'); vertical-align: middle;{res} }}")
            cover_overrides.append(f"  {pos} {{ content: none; }}")

        if text:
            pos = _HEADER_POSITIONS.get(text_position, "@top-left")
            rules.append(
                f"  {pos} {{ content: '{_css_string(text)}'; "
                f"font-size: 8pt; color: #5d6d7e; vertical-align: middle; }}"
            )
            cover_overrides.append(f"  {pos} {{ content: none; }}")

    if not rules:
        return ""

    lines = ["<style>", "@page {"]
    lines.extend(rules)
    lines.append("}")
    if cover_overrides:
        lines.append("@page cover {")
        lines.extend(cover_overrides)
        lines.append("}")
    lines.append("</style>")
    return "\n".join(lines)


def _build_section_bar_style(config: dict[str, Any]) -> str:
    """Generate inline CSS for section heading bars if enabled."""
    if not config.get("section_bar"):
        return ""

    color = _safe_css_color(config.get("section_bar_color"), "#2563eb")
    text_color = _safe_css_color(config.get("section_bar_text_color"), "#ffffff")
    text_on_bar = config.get("section_bar_text_on_bar", True)
    headings = config.get("section_bar_headings", "h1,h2")
    # Only accept simple tag tokens (h1..h6) — these become CSS selectors.
    heading_list = [
        h.strip() for h in str(headings).split(",") if re.fullmatch(r"h[1-6]", h.strip())
    ]
    if not heading_list:
        return ""

    lines = ["<style>"]

    if text_on_bar:
        selectors = ", ".join(f".report-body {h}" for h in heading_list)
        lines.append(f"{selectors} {{")
        lines.append(f"  background: {color};")
        lines.append(f"  color: {text_color};")
        lines.append("  padding: 6pt 12pt;")
        lines.append("  border-bottom: none;")
        lines.append("  margin-left: 0; margin-right: 0;")
        lines.append("}")
        strong_selectors = ", ".join(f".report-body {h} strong" for h in heading_list)
        lines.append(f"{strong_selectors} {{ color: {text_color}; }}")
    else:
        selectors = ", ".join(f".report-body {h}" for h in heading_list)
        lines.append(f"{selectors} {{")
        lines.append(f"  border-top: 4pt solid {color};")
        lines.append("  padding-top: 6pt;")
        lines.append("  border-bottom: none;")
        lines.append("}")

    lines.append("</style>")
    return "\n".join(lines)


_COL_WIDTHS_COMMENT_RE = re.compile(r"<!--\s*col-widths:\s*([\d.,\s]+?)\s*-->", re.IGNORECASE)


def _apply_table_col_widths(html: str, config_weights: list[float] | None = None) -> str:
    """Size table columns like the docx builder: comment > config > untouched.

    A ``<!-- col-widths: 30, 70 -->`` comment binds to the next ``<table>``
    after it (the last comment before a table wins); *config_weights* (the
    ``table_col_widths`` key) covers every other markdown table. Either source
    is ignored for a table whose column count doesn't match — same silent
    fallback as Word. Widths become inline percentage styles on the first-row
    cells under ``table-layout: fixed``. Tables the builder generates with a
    class of their own (``field-box``/``field-row`` form grids) are left alone.
    """
    targets: dict[int, list[float]] = {}
    for m in _COL_WIDTHS_COMMENT_RE.finditer(html):
        try:
            weights = [float(w) for w in m.group(1).split(",") if w.strip()]
        except ValueError:
            continue
        if not weights or sum(weights) <= 0:
            continue
        tpos = html.find("<table", m.end())
        if tpos != -1:
            targets[tpos] = weights

    if config_weights and sum(config_weights) > 0:
        for m in re.finditer(r"<table[\s>]", html):
            targets.setdefault(m.start(), list(config_weights))

    # Rewrite from the last table backwards so earlier offsets stay valid.
    for tpos in sorted(targets, reverse=True):
        weights = targets[tpos]
        open_end = html.find(">", tpos)
        table_end = html.find("</table>", tpos)
        if open_end == -1 or table_end == -1 or open_end > table_end:
            continue
        open_tag = html[tpos : open_end + 1]
        if "class=" in open_tag:
            continue  # form grids (field-box/field-row) manage their own widths
        seg = html[open_end + 1 : table_end]
        row_m = re.search(r"<tr[^>]*>.*?</tr>", seg, re.DOTALL)
        if not row_m:
            continue
        row = row_m.group(0)
        cells = list(re.finditer(r"<t[hd][^>]*>", row))
        if len(cells) != len(weights):
            continue  # count mismatch — ignored, same as the docx builder

        total = sum(weights)
        parts: list[str] = []
        last = 0
        for cell_m, w in zip(cells, weights):
            parts.append(row[last : cell_m.start()])
            tag = cell_m.group(0)
            width_decl = f"width: {w / total * 100:.4f}%;"
            if 'style="' in tag:
                tag = tag.replace('style="', f'style="{width_decl} ', 1)
            else:
                tag = tag[:-1] + f' style="{width_decl}">'
            parts.append(tag)
            last = cell_m.end()
        parts.append(row[last:])
        new_row = "".join(parts)

        layout_decl = "table-layout: fixed; width: 100%;"
        if 'style="' in open_tag:
            new_open = open_tag.replace('style="', f'style="{layout_decl} ', 1)
        else:
            new_open = open_tag[:-1] + f' style="{layout_decl}">'

        new_seg = seg[: row_m.start()] + new_row + seg[row_m.end() :]
        html = html[:tpos] + new_open + new_seg + html[table_end:]

    return html


def _build_body_align_style(config: dict[str, Any], theme_body_justify: bool = False) -> str:
    """Generate CSS for the ``body_text_align`` config key.

    Mirrors the docx builder, where the key sets the default paragraph
    alignment. Applied to the report-body container (not ``p`` directly) so
    per-section ``<div style="text-align: …">`` overrides still win through
    normal CSS inheritance — the same cascade order Word uses.

    ``theme_body_justify`` is set when the *theme CSS* justifies the body and
    no config key overrides it: cells still get the left-align guard (the docx
    builder pins cells left under a justified Normal style — same rule here).
    """
    align = str(config.get("body_text_align", "")).strip().lower()
    if align not in ("justify", "left", "center", "right"):
        if theme_body_justify:
            return "<style>.report-body th, .report-body td { text-align: left; }</style>"
        return ""
    if align == "justify":
        # Justify never reaches into table cells — wrapped text in a narrow
        # column stretches into rivers of whitespace (same rule as the docx
        # builder). Markdown column alignment (inline style) still wins.
        return (
            "<style>.report-body { text-align: justify; }\n"
            ".report-body th, .report-body td { text-align: left; }</style>"
        )
    return f"<style>.report-body {{ text-align: {align}; }}</style>"


_CSS_VAR_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CSS_VAR_IMG_EXT = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")


def _build_css_vars_style(
    config: dict[str, Any], repo_root: Path | None, doc_path: Path | None
) -> str:
    """Inject ``css_vars`` as CSS custom properties on ``:root``.

    Lets a theme keep its styling in CSS while the *asset* (or any value) is
    overridden per-document from YAML. A value ending in an image extension is
    resolved through the logo/asset cascade (doc dir → ancestors → repo root)
    and wrapped as ``url("file://…")`` so a theme can write, e.g.::

        .cover-bar-bottom::after { background: var(--cover-watermark) no-repeat center; }

    and the document sets ``css_vars: {cover-watermark: assets/logo.png}``.
    Non-asset values are injected literally (e.g. a colour or length).
    """
    raw = config.get("css_vars")
    if not isinstance(raw, dict) or not raw:
        return ""
    log = logging.getLogger(__name__)
    decls: list[str] = []
    for name, value in raw.items():
        key = str(name).lstrip("-")
        if not _CSS_VAR_NAME_RE.match(key):
            log.warning("css_vars: ignoring invalid custom-property name %r", name)
            continue
        sval = str(value).strip()
        if sval.lower().endswith(_CSS_VAR_IMG_EXT):
            asset = _resolve_logo(sval, repo_root, doc_path)
            if asset is None:
                log.warning("css_vars: could not resolve asset %r for --%s", sval, key)
                continue
            decls.append(f'  --{key}: url("{asset.as_uri()}");')
        else:
            # Literal CSS value — strip characters that could break out of the
            # declaration block (defensive; config is author-controlled).
            safe = sval.replace("}", "").replace("<", "").replace(">", "").replace(";", "")
            decls.append(f"  --{key}: {safe};")
    if not decls:
        return ""
    return "<style>\n:root {\n" + "\n".join(decls) + "\n}\n</style>"


def _build_page_header_bar_elements(
    bar_cfg: dict[str, Any] | None,
    header_text: str | None = None,
    header_text_position: str = "left",
    header_logo_uri: str | None = None,
    header_logo_position: str = "right",
    logo_max_mm: float | None = None,
    margin_left_mm: float = 25.0,
    margin_right_mm: float = 20.0,
) -> tuple[str, str]:
    """Return (bar_html, bar_css) for the fixed page header bar.

    Uses position:fixed to repeat on every content page. Positioned with
    negative offsets to extend into the page margins for a full-bleed bar.
    Text and logo are rendered inside the bar div itself.
    """
    if not bar_cfg or not bar_cfg.get("enabled"):
        return "", ""

    color = _safe_css_color(bar_cfg.get("color"), "#2563eb")
    text_color = _safe_css_color(bar_cfg.get("text_color"), "#ffffff")
    height = bar_cfg.get("height", "12mm")

    # Default logo cap scales with the bar: 70% of its height (matches the
    # docx builder). ``header_logo_height`` passes an explicit value instead.
    if logo_max_mm is None:
        logo_max_mm = _parse_mm(height, 12.0) * 0.7

    padding_after = bar_cfg.get("padding", "6mm")
    offset_mm = max(0.0, _parse_mm(bar_cfg.get("offset", "0mm"), 0.0))

    show_footer_line = bar_cfg.get("footer_line", False)
    footer_border_css = ""
    if not show_footer_line:
        footer_border_css = """
  @bottom-left { border-top: none; }
  @bottom-center { border-top: none; }
  @bottom-right { border-top: none; }"""

    css = f"""<style>
@page {{
  margin-top: calc({offset_mm:g}mm + {height} + {padding_after});{footer_border_css}
}}
@page cover {{
  margin-top: 0;
}}
.page-header-bar-fixed {{
  position: fixed;
  top: calc(-1 * ({height} + {padding_after}));
  left: -{margin_left_mm}mm;
  right: -{margin_right_mm}mm;
  height: {height};
  background: {color};
  z-index: 1000;
  padding: 0 {margin_right_mm}mm 0 {margin_left_mm}mm;
  box-sizing: border-box;
}}
/* WeasyPrint 68.x drops flex children inside position:fixed boxes, so the
   left/center/right slots use a table row instead (same 35/30/35 grid as the
   docx builder's header table). */
.page-header-bar-fixed .phb-row {{
  display: table;
  table-layout: fixed;
  width: 100%;
  height: {height};
}}
.page-header-bar-fixed .phb-slot {{
  display: table-cell;
  height: {height};
  font-size: 8pt;
  line-height: 1;
  vertical-align: middle;
}}
.page-header-bar-fixed .phb-slot-left {{ text-align: left; width: 35%; }}
.page-header-bar-fixed .phb-slot-center {{ text-align: center; width: 30%; }}
.page-header-bar-fixed .phb-slot-right {{ text-align: right; width: 35%; }}
.page-header-bar-fixed .phb-text {{
  font-size: 8pt;
  color: {text_color};
  font-family: inherit;
}}
.page-header-bar-fixed .phb-logo {{
  max-height: {logo_max_mm}mm;
  vertical-align: middle;
}}
</style>"""

    left_parts: list[str] = []
    center_parts: list[str] = []
    right_parts: list[str] = []

    slots = {"left": left_parts, "center": center_parts, "right": right_parts}

    if header_text:
        slots.get(header_text_position, left_parts).append(
            f'<span class="phb-text">{_escape_html(header_text)}</span>'
        )

    if header_logo_uri:
        slots.get(header_logo_position, right_parts).append(
            f'<img class="phb-logo" src="{header_logo_uri}">'
        )

    logos = bar_cfg.get("logos", [])
    for logo_entry in logos:
        if isinstance(logo_entry, dict):
            uri = logo_entry.get("uri", "")
            pos = logo_entry.get("position", "center")
        else:
            uri = str(logo_entry)
            pos = "center"
        if uri:
            slots.get(pos, center_parts).append(f'<img class="phb-logo" src="{uri}">')

    html = (
        '<div class="page-header-bar-fixed"><div class="phb-row">'
        f'<div class="phb-slot phb-slot-left">{"".join(left_parts)}</div>'
        f'<div class="phb-slot phb-slot-center">{"".join(center_parts)}</div>'
        f'<div class="phb-slot phb-slot-right">{"".join(right_parts)}</div>'
        "</div></div>"
    )

    return html, css


def _resolve_css(
    config: dict[str, Any],
    repo_root: Path | None,
    doc_path: Path | None = None,
) -> Path:
    """Resolve the CSS theme path, auto-generating a default if none exists.

    Resolution order:
    1. ``pdf_theme`` config key (absolute path or relative to repo_root)
    2. ``_pdf-theme.css`` in each directory from doc_path up to repo_root (deepest wins)
    3. Auto-generate ``_pdf-theme.css`` at repo root on first build

    This mirrors the cascading behaviour of ``_meta.yml`` — a CSS file placed
    next to (or near) a document overrides the repo-level default.
    Run ``md-doc theme init`` to replace the generated default with a branded theme.
    """
    theme_val = config.get("pdf_theme")
    if theme_val:
        p = Path(theme_val)
        # Security: reject traversal components in user-provided theme paths
        if ".." in p.parts:
            logging.getLogger(__name__).warning(
                "Ignoring pdf_theme path %r — '..' components are not allowed.",
                theme_val,
            )
        elif p.is_absolute() and p.exists():
            # Absolute paths from CLI --theme flag are trusted (user invoked directly)
            return p
        elif repo_root and (repo_root / p).exists():
            resolved = (repo_root / p).resolve()
            if resolved.is_relative_to(repo_root.resolve()):
                return resolved

    # Walk from doc_path up to repo_root looking for _pdf-theme.css. Deepest wins.
    if doc_path is not None and repo_root is not None:
        doc_dir = doc_path.parent if doc_path.is_file() else doc_path
        try:
            rel = doc_dir.relative_to(repo_root)
            # All dirs from doc_dir up to repo_root (INCLUSIVE), deepest first.
            # The root itself must be a candidate: a hand-written _theme.css at
            # the project root was previously skipped, silently shadowed by an
            # auto-generated default _pdf-theme.css.
            candidate_dirs = [
                repo_root / Path(*rel.parts[:i]) for i in range(len(rel.parts), 0, -1)
            ]
            candidate_dirs.append(repo_root)
        except ValueError:
            candidate_dirs = [doc_dir]
        for directory in candidate_dirs:
            for name in ("_pdf-theme.css", "_theme.css"):
                candidate = directory / name
                if candidate.exists():
                    return candidate.resolve()

    # Nothing found — generate a default _pdf-theme.css at the repo root
    # (or alongside the document if there is no repo root) and inform the user.
    generate_at = repo_root if repo_root else (doc_path.parent if doc_path else Path.cwd())
    default_path = generate_at / "_pdf-theme.css"

    if not default_path.exists():
        from ..theme import generate_default_theme  # avoid circular import at module level

        default_path.write_text(generate_default_theme(), encoding="utf-8")
        logging.getLogger(__name__).warning(
            "No _pdf-theme.css found — created default theme at %s. "
            "Run 'md-doc theme init' to customise it.",
            default_path,
        )
    return default_path.resolve()


def _find_repo_root(start: Path) -> Path:
    """Walk up from start looking for .git or pyproject.toml."""
    current = start.resolve()
    while True:
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            return start.resolve()
        current = parent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build(
    rendered_md: str,
    config: dict[str, Any],
    out_path: Path,
    *,
    repo_root: Path | None = None,
    doc_path: Path | None = None,
) -> None:
    """
    Convert rendered Markdown to a PDF file using WeasyPrint.

    Parameters
    ----------
    rendered_md:
        Jinja2-rendered Markdown string (may include frontmatter).
    config:
        Merged config dict from load_config().
    out_path:
        Destination path for the generated PDF.
    repo_root:
        Optional repo root for resolving the CSS theme path. Auto-detected
        from out_path if not provided.
    doc_path:
        Optional path to the source .md file. When provided, enables nested
        CSS resolution — a ``_pdf-theme.css`` placed in any ancestor directory
        between the document and the repo root will be used (deepest wins).
    """
    out_path = Path(out_path).resolve()

    if repo_root is None:
        repo_root = _find_repo_root(out_path.parent)

    # Resolve the theme up front: --mddoc-* custom properties in it provide
    # brand defaults for the look-related config keys (YAML always wins).
    css_path = _resolve_css(config, repo_root, doc_path=doc_path)
    css_text: str | None = None
    if css_path and css_path.exists():
        try:
            css_text = css_path.read_text(encoding="utf-8")
        except OSError:
            css_text = None
    config = apply_theme_config_defaults(config, css_text)

    # Strip frontmatter (already processed by renderer)
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", rendered_md, count=1, flags=re.DOTALL)

    title: str = config.get("title") or _extract_title(body) or out_path.stem
    author: str = config.get("author", "Document Producer")
    date_str: str = config.get("date") or datetime.date.today().strftime("%-d %B %Y")

    cover_page: bool = coerce_bool(config.get("cover_page"), False)

    cover_logo_path = _resolve_logo(config.get("cover_logo"), repo_root, doc_path)
    cover_logo_uri = cover_logo_path.as_uri() if cover_logo_path else None

    cover_bar_logo_path = _resolve_logo(config.get("cover_bar_logo"), repo_root, doc_path)
    cover_bar_logo_uri = cover_bar_logo_path.as_uri() if cover_bar_logo_path else None

    header_logo_path = _resolve_logo(config.get("header_logo"), repo_root, doc_path)
    header_logo_uri = header_logo_path.as_uri() if header_logo_path else None
    header_logo_position: str = config.get("header_logo_position", "right")
    # Header logos render at min(intrinsic, 8mm) tall by default;
    # header_logo_height forces an exact height. Same rule as the docx builder.
    header_logo_height_cfg = config.get("header_logo_height")
    header_logo_max_mm = _parse_mm(header_logo_height_cfg, 8.0)
    header_logo_dpi: float | None = None
    if header_logo_path:
        header_logo_dpi = _logo_resolution_dpi(
            header_logo_path, header_logo_max_mm, forced=header_logo_height_cfg is not None
        )
    header_text: str | None = config.get("header_text")
    header_text_position: str = config.get("header_text_position", "left")

    footer_left: str | None = config.get("footer_left")
    footer_center: str | None = config.get("footer_center")
    footer_right: str | None = config.get("footer_right")

    page_header_bar: dict[str, Any] | None = None
    if config.get("page_header_bar"):
        phb_logo_path = _resolve_logo(config.get("page_header_bar_logo"), repo_root, doc_path)
        phb_logos: list[dict[str, str]] = []
        raw_logos = config.get("page_header_bar_logos", [])
        for entry in raw_logos:
            if isinstance(entry, dict):
                lpath = _resolve_logo(entry.get("path"), repo_root, doc_path)
                if lpath:
                    phb_logos.append(
                        {"uri": lpath.as_uri(), "position": entry.get("position", "center")}
                    )
            elif isinstance(entry, str):
                lpath = _resolve_logo(entry, repo_root, doc_path)
                if lpath:
                    phb_logos.append({"uri": lpath.as_uri(), "position": "center"})

        page_header_bar = {
            "enabled": True,
            "color": config.get("page_header_bar_color", "#2563eb"),
            "text_color": config.get("page_header_bar_text_color", "#ffffff"),
            "height": config.get("page_header_bar_height", "12mm"),
            "padding": config.get("page_header_bar_padding", "6mm"),
            "offset": config.get("page_header_bar_offset", "0mm"),
            "logos": phb_logos,
        }
        # The more-specific page_header_bar_logo wins over header_logo inside
        # the bar (same precedence as the docx builder).
        if phb_logo_path:
            header_logo_uri = phb_logo_path.as_uri()
            header_logo_position = config.get(
                "page_header_bar_logo_position", config.get("header_logo_position", "right")
            )

    if cover_page:
        body = _strip_leading_h1(body)
    body = _inject_appendix_breaks(body)
    body = _inject_page_breaks(body)

    is_form = bool(config.get("pdf_forms"))
    body = _expand_form_fields(collapse_select_markup(body), is_form)

    from ..math import markdown_html, render_math

    html_body, _ = render_math(markdown_html(body, _MD_EXTENSIONS))
    html_body = _drop_empty_table_headers(html_body)
    # Mark before keep-with-next wrappers are inserted; direct-child selectors
    # otherwise miss a leading heading after an included letterhead.
    html_body = re.sub(r"<h1\b", '<h1 data-md-doc-first-heading="true"', html_body, count=1)

    # Column widths: <!-- col-widths --> comments and the table_col_widths
    # config key, applied per table with the same precedence as the docx
    # builder (comment > config; ignored on column-count mismatch).
    raw_col_widths = config.get("table_col_widths")
    config_col_weights: list[float] | None = None
    if isinstance(raw_col_widths, list) and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in raw_col_widths
    ):
        config_col_weights = [float(v) for v in raw_col_widths]
    html_body = _apply_table_col_widths(html_body, config_col_weights)

    # Render Mermaid diagram blocks to inline SVGs, themed from the CSS
    from ..mermaid import process_html as _process_mermaid, extract_theme_from_css

    mermaid_theme = None
    if css_text:
        try:
            mermaid_theme = extract_theme_from_css(css_text)
        except Exception:
            pass  # fall back to default theme
    html_body = _process_mermaid(html_body, theme=mermaid_theme)

    primary_color = mermaid_theme.get("primary") if mermaid_theme else None

    # Theme-derived layout facts shared with the docx builder: the @page side
    # margins (the header bar's full-bleed offsets must match them) and
    # whether the theme justifies body text (cells get the left-align guard).
    from ._assets import _page_geometry

    page_margins_mm = (25.0, 20.0)
    page_size_mm = (210.0, 297.0)
    theme_body_justify = False
    if css_text:
        try:
            geom = _page_geometry(css_text)
            page_margins_mm = (geom["left"], geom["right"])
            page_size_mm = (geom["w"], geom["h"])
        except Exception:
            pass
        if not str(config.get("body_text_align", "")).strip():
            try:
                from ..docx_theme import parse_css_for_word

                theme_body_justify = (
                    parse_css_for_word(css_path).get("text_align_body") == "justify"
                )
            except Exception:
                theme_body_justify = False

    html_body = _keep_heading_with_next(_group_label_with_textarea(html_body))
    html = _build_html(
        title,
        date_str,
        author,
        html_body,
        css_path,
        cover_page=cover_page,
        cover_cfg=config,
        cover_logo_uri=cover_logo_uri,
        cover_bar_logo_uri=cover_bar_logo_uri,
        header_logo_uri=header_logo_uri,
        header_logo_position=header_logo_position,
        header_text=header_text,
        header_text_position=header_text_position,
        page_header_bar=page_header_bar,
        full_config=config,
        footer_left=footer_left,
        footer_center=footer_center,
        footer_right=footer_right,
        primary_color=primary_color,
        css_vars_style=_build_css_vars_style(config, repo_root, doc_path),
        is_form=is_form,
        header_logo_dpi=header_logo_dpi,
        # None = auto (70% of the bar height) unless header_logo_height is set.
        header_logo_max_mm=(header_logo_max_mm if header_logo_height_cfg is not None else None),
        page_margins_mm=page_margins_mm,
        page_size_mm=page_size_mm,
        theme_body_justify=theme_body_justify,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wp_kwargs: dict[str, Any] = {}
    if is_form:
        wp_kwargs["pdf_forms"] = True
        # Patch metadata WeasyPrint drops (required/readonly/tooltip/defaults).
        field_meta = _collect_form_field_meta(html_body)
        if field_meta:
            wp_kwargs["finisher"] = _make_forms_finisher(field_meta)
    weasyprint.HTML(
        string=html,
        base_url=str(doc_path.resolve().parent if doc_path is not None else out_path.parent),
        url_fetcher=_make_url_fetcher(),
    ).write_pdf(str(out_path), **wp_kwargs)
