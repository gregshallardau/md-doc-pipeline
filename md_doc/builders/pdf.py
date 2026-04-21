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

logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fonttools").setLevel(logging.ERROR)

import markdown  # noqa: E402
import weasyprint  # noqa: E402

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


_FORM_FIELD_RE = re.compile(r"\?\[(.+?)\]")
_ROW_OPEN_RE = re.compile(r"^\?\[row\]\s*$", re.MULTILINE)
_ROW_CLOSE_RE = re.compile(r"^\?\[/row\]\s*$", re.MULTILINE)


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


def _field_to_html(field_spec: str) -> str:
    """Convert a single ?[type: name, ...] spec to HTML."""
    field_spec = field_spec.strip()

    if ":" not in field_spec:
        if field_spec.lower().startswith("submit"):
            parts = field_spec.split(None, 1)
            label = parts[1] if len(parts) > 1 else "Submit"
            return f'<input type="submit" value="{_escape_html(label)}">'
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
            opts_html = "\n".join(
                (
                    f'  <option value="{_escape_html(o.lower().replace(" ", "_"))}">{_escape_html(o)}</option>'
                    if not o.startswith("--")
                    else f'  <option value="">{_escape_html(o)}</option>'
                )
                for o in options
            )
            req = " required" if name_attrs.get("required") else ""
            return f'<select name="{_escape_html(name)}"{req}>\n{opts_html}\n</select>'

        elif ftype in ("radio", "radio-inline"):
            inline = ftype == "radio-inline"
            style = ' style="display: inline; margin-right: 12pt;"' if inline else ""
            sep = "\n" if inline else "<br>\n"
            items = []
            for o in options:
                val = o.lower().replace(" ", "_").replace("-", "_")
                items.append(
                    f'<label{style}><input type="radio" name="{_escape_html(name)}" '
                    f'value="{_escape_html(val)}"> {_escape_html(o)}</label>'
                )
            return f"<div>\n{sep.join(items)}\n</div>"

        elif ftype == "checkbox-inline":
            items = []
            for o in options:
                field_name = f"{name}_{o.lower().replace(' ', '_').replace('-', '_')}"
                items.append(
                    f'<label style="display: inline; margin-right: 12pt;">'
                    f'<input type="checkbox" name="{_escape_html(field_name)}"> '
                    f"{_escape_html(o)}</label>"
                )
            joined = "\n".join(items)
            return f"<div>\n{joined}\n</div>"

        return f"<!-- unknown form field: {_escape_html(field_spec)} -->"

    else:
        parts = rest.split(",")
        name = parts[0].strip()
        attrs = _parse_field_attrs(",".join(parts[1:])) if len(parts) > 1 else {}

        req = " required" if attrs.get("required") else ""
        extra = ""
        for k, v in attrs.items():
            if k == "required":
                continue
            if v is True:
                extra += f" {k}"
            else:
                extra += f' {k}="{_escape_html(str(v))}"'

        if ftype == "textarea":
            rows = attrs.get("rows", "4")
            return f'<textarea name="{_escape_html(name)}" rows="{rows}"{req}></textarea>'
        elif ftype == "checkbox":
            label_text = attrs.get("label", "")
            label_html = (
                f" {_escape_html(str(label_text))}" if label_text and label_text is not True else ""
            )
            return (
                f'<div><label><input type="checkbox" name="{_escape_html(name)}"{req}>'
                f"{label_html}</label></div>"
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
            input_type = ftype if ftype in ("text", "email", "date", "number") else "text"
            return f'<input type="{input_type}" name="{_escape_html(name)}"{req}{extra}>'


def _expand_row_block(row_content: str) -> str:
    """Expand a ?[row]...?[/row] block into a borderless table."""
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

        n = len(cells)
        width = f"{100 // n}%"
        tds = []
        for i, cell in enumerate(cells):
            padding = (
                "0 8pt 4pt 0" if i == 0 else ("0 0 4pt 8pt" if i == n - 1 else "0 8pt 4pt 8pt")
            )
            cell_html = _FORM_FIELD_RE.sub(lambda m: _field_to_html(m.group(1)), cell)
            tds.append(
                f'<td style="border: none; width: {width}; padding: {padding}; vertical-align: top;">'
                f"{cell_html}</td>"
            )
        rows_html.append(f'<tr style="background: none;">{"".join(tds)}</tr>')

    return f'<table style="border: none; width: 100%;">\n' f'{"".join(rows_html)}\n' f"</table>"


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

    result = expand_rows(md_content)
    result = _FORM_FIELD_RE.sub(lambda m: _field_to_html(m.group(1)), result)

    if is_form and "<form" not in result.lower():
        result = '<form markdown="1">\n\n' + result + "\n\n</form>"

    return result


_BLOCK_TAG = r"(?:p|pre|ul|ol|table|blockquote|div|dl)"
_BLOCK_RE = re.compile(rf"(<{_BLOCK_TAG}[^>]*>.*?</{_BLOCK_TAG}>)", re.DOTALL)


def _keep_heading_with_next(html_body: str) -> str:
    """Wrap each heading + up to two following block elements in a keep-together div.

    WeasyPrint can ignore CSS break-after:avoid on headings when the next
    element is large.  Wrapping both in a container with break-inside:avoid
    forces them onto the same page.  We grab up to two siblings to handle
    the common pattern: heading → short intro paragraph → code/table block.
    """
    heading_re = re.compile(r"(<h[2-4][^>]*>.*?</h[2-4]>)", re.DOTALL)
    parts = heading_re.split(html_body)
    result: list[str] = []

    i = 0
    while i < len(parts):
        if heading_re.fullmatch(parts[i]):
            heading = parts[i]
            tail = parts[i + 1] if i + 1 < len(parts) else ""
            blocks = _BLOCK_RE.findall(tail)
            if len(blocks) >= 2:
                rest = tail[
                    tail.index(blocks[0])
                    + len(blocks[0])
                    + tail[tail.index(blocks[0]) + len(blocks[0]) :].index(blocks[1])
                    + len(blocks[1]) :
                ]
                before = tail[: tail.index(blocks[0])]
                result.append(before)
                result.append(f'<div class="keep-with-next">{heading}{blocks[0]}{blocks[1]}</div>')
                result.append(rest)
            elif len(blocks) == 1:
                before = tail[: tail.index(blocks[0])]
                after = tail[tail.index(blocks[0]) + len(blocks[0]) :]
                result.append(before)
                result.append(f'<div class="keep-with-next">{heading}{blocks[0]}</div>')
                result.append(after)
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
    footer_color_style = f' style="color: {footer_color};"' if footer_color else ""
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
        body_inner = f"""\
    <div class="cover-bar-wrapper" style="background: #2563eb; min-height: {bar_top_height};">
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
      {footer_inner}
      {bar_logo_html}
    </div>"""
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


def _build_html(
    title: str,
    date_str: str,
    author: str,
    html_body: str,
    css_path: Path,
    *,
    cover_page: bool = True,
    cover_cfg: dict[str, Any] | None = None,
    cover_logo_uri: str | None = None,
    cover_bar_logo_uri: str | None = None,
    header_logo_uri: str | None = None,
    header_logo_position: str = "right",
    header_text: str | None = None,
    header_text_position: str = "left",
    page_header_bar: dict[str, Any] | None = None,
    full_config: dict[str, Any] | None = None,
) -> str:
    css_uri = css_path.as_uri()

    header_style = _build_header_style(
        header_logo_uri,
        header_logo_position,
        header_text,
        header_text_position,
        page_header_bar=page_header_bar,
    )

    section_bar_style = _build_section_bar_style(full_config or {})
    page_bar_html, page_bar_css = _build_page_header_bar_elements(
        page_header_bar,
        header_text=header_text,
        header_text_position=header_text_position,
        header_logo_uri=header_logo_uri,
        header_logo_position=header_logo_position,
    )

    cover_html = ""
    if cover_page:
        cover_html = f"  <!-- COVER PAGE -->\n{_build_cover(title, author, date_str, cover_cfg or {}, cover_logo_uri, bar_logo_uri=cover_bar_logo_uri)}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{_escape_html(title)}</title>
  <link rel="stylesheet" href="{css_uri}">
  {header_style}
  {section_bar_style}
  {page_bar_css}
</head>
<body>
{cover_html}
  <!-- REPORT BODY -->
  <div class="report-body">
    {page_bar_html}
    <span class="running-date">{_escape_html(date_str)}</span>
    {html_body}
  </div>

</body>
</html>"""


_HEADER_POSITIONS = {"left": "@top-left", "center": "@top-center", "right": "@top-right"}


def _build_header_style(
    logo_uri: str | None,
    logo_position: str,
    text: str | None,
    text_position: str,
    page_header_bar: dict[str, Any] | None = None,
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
            rules.append(f"  {pos} {{ content: url('{logo_uri}'); vertical-align: middle; }}")
            cover_overrides.append(f"  {pos} {{ content: none; }}")

        if text:
            pos = _HEADER_POSITIONS.get(text_position, "@top-left")
            rules.append(
                f"  {pos} {{ content: '{_escape_html(text)}'; "
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

    color = config.get("section_bar_color", "#2563eb")
    text_color = config.get("section_bar_text_color", "#ffffff")
    text_on_bar = config.get("section_bar_text_on_bar", True)
    headings = config.get("section_bar_headings", "h1,h2")
    heading_list = [h.strip() for h in headings.split(",")]

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


def _build_page_header_bar_elements(
    bar_cfg: dict[str, Any] | None,
    header_text: str | None = None,
    header_text_position: str = "left",
    header_logo_uri: str | None = None,
    header_logo_position: str = "right",
) -> tuple[str, str]:
    """Return (bar_html, bar_css) for the fixed page header bar.

    Uses position:fixed to repeat on every content page. Positioned with
    negative offsets to extend into the page margins for a full-bleed bar.
    Text and logo are rendered inside the bar div itself.
    """
    if not bar_cfg or not bar_cfg.get("enabled"):
        return "", ""

    color = bar_cfg.get("color", "#2563eb")
    text_color = bar_cfg.get("text_color", "#ffffff")
    height = bar_cfg.get("height", "12mm")

    padding_after = bar_cfg.get("padding", "6mm")

    show_footer_line = bar_cfg.get("footer_line", False)
    footer_border_css = ""
    if not show_footer_line:
        footer_border_css = """
  @bottom-left { border-top: none; }
  @bottom-center { border-top: none; }
  @bottom-right { border-top: none; }"""

    css = f"""<style>
@page {{
  margin-top: calc({height} + {padding_after});{footer_border_css}
}}
@page cover {{
  margin-top: 0;
}}
.page-header-bar-fixed {{
  position: fixed;
  top: calc(-1 * ({height} + {padding_after}));
  left: -25mm;
  right: -20mm;
  height: {height};
  background: {color};
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20mm 0 25mm;
  box-sizing: border-box;
}}
.page-header-bar-fixed .phb-text {{
  font-size: 8pt;
  color: {text_color};
  font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
}}
.page-header-bar-fixed .phb-logo {{
  max-height: 8mm;
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

    left_html = "".join(left_parts) if left_parts else "<span></span>"
    center_html = "".join(center_parts) if center_parts else ""
    right_html = "".join(right_parts) if right_parts else "<span></span>"

    mid_section = f'<span class="phb-center">{center_html}</span>' if center_html else ""
    html = f'<div class="page-header-bar-fixed">{left_html}{mid_section}{right_html}</div>'

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

    # Walk from doc_path up to repo_root looking for _pdf-theme.css (deepest wins)
    if doc_path is not None and repo_root is not None:
        doc_dir = doc_path.parent if doc_path.is_file() else doc_path
        try:
            rel = doc_dir.relative_to(repo_root)
            # All dirs from repo_root to doc_dir (inclusive), deepest first
            candidate_dirs = [
                repo_root / Path(*rel.parts[:i]) for i in range(len(rel.parts), 0, -1)
            ]
        except ValueError:
            candidate_dirs = [doc_dir]
        for directory in candidate_dirs:
            candidate = directory / "_pdf-theme.css"
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

    # Strip frontmatter (already processed by renderer)
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", rendered_md, count=1, flags=re.DOTALL)

    title: str = config.get("title") or _extract_title(body) or out_path.stem
    author: str = config.get("author", "Document Producer")
    date_str: str = config.get("date") or datetime.date.today().strftime("%-d %B %Y")

    cover_page: bool = bool(config.get("cover_page", True))

    cover_logo_path = _resolve_logo(config.get("cover_logo"), repo_root, doc_path)
    cover_logo_uri = cover_logo_path.as_uri() if cover_logo_path else None

    cover_bar_logo_path = _resolve_logo(config.get("cover_bar_logo"), repo_root, doc_path)
    cover_bar_logo_uri = cover_bar_logo_path.as_uri() if cover_bar_logo_path else None

    header_logo_path = _resolve_logo(config.get("header_logo"), repo_root, doc_path)
    header_logo_uri = header_logo_path.as_uri() if header_logo_path else None
    header_logo_position: str = config.get("header_logo_position", "right")
    header_text: str | None = config.get("header_text")
    header_text_position: str = config.get("header_text_position", "left")

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
            "logos": phb_logos,
        }
        if phb_logo_path and not header_logo_uri:
            header_logo_uri = phb_logo_path.as_uri()
            header_logo_position = config.get("page_header_bar_logo_position", "right")

    if cover_page:
        body = _strip_leading_h1(body)
    body = _inject_appendix_breaks(body)

    is_form = bool(config.get("pdf_forms"))
    body = _expand_form_fields(body, is_form)

    md_engine = markdown.Markdown(extensions=_MD_EXTENSIONS)
    html_body = md_engine.convert(body)

    css_path = _resolve_css(config, repo_root, doc_path=doc_path)

    # Render Mermaid diagram blocks to inline SVGs, themed from the CSS
    from ..mermaid import process_html as _process_mermaid, extract_theme_from_css

    mermaid_theme = None
    if css_path and css_path.exists():
        try:
            mermaid_theme = extract_theme_from_css(css_path.read_text(encoding="utf-8"))
        except Exception:
            pass  # fall back to default theme
    html_body = _process_mermaid(html_body, theme=mermaid_theme)

    html_body = _keep_heading_with_next(html_body)
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
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wp_kwargs = {"pdf_forms": True} if config.get("pdf_forms") else {}
    weasyprint.HTML(string=html, base_url=str(out_path.parent)).write_pdf(
        str(out_path), **wp_kwargs
    )
