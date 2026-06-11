"""
CSS theme parser and applier for Word (docx/dotx) output.

Parses ``_docx-theme.css`` (Word-specific overrides) or falls back to
``_pdf-theme.css`` and applies extracted typography and colour properties
to a python-docx ``Document``.

Theme resolution order (``resolve_docx_theme``):
  1. Walk from the document directory up to ``repo_root``.
  2. At each level: look for ``_docx-theme.css`` first, then ``_pdf-theme.css``.
  3. Return the parsed theme from the first file found, or ``None`` if neither
     exists anywhere in the hierarchy.

Public API
----------
    parse_css_for_word(css_path)                    → dict[str, Any]
    apply_theme_to_doc(doc, theme)                  → None
    set_cell_shading(cell, hex_color)               → None
    resolve_docx_theme(doc_path, repo_root)         → dict[str, Any] | None
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

_log = logging.getLogger(__name__)

# Maximum @import recursion depth to prevent infinite loops
_MAX_IMPORT_DEPTH = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert a hex colour string to an (r, g, b) tuple.

    Accepts ``#rrggbb`` or ``#rgb`` (shorthand). Returns (0, 0, 0) on failure.
    """
    h = hex_str.strip().lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def _parse_pt(value: str) -> float | None:
    """Parse a CSS ``pt`` value to a float. Returns None if not a pt value."""
    m = re.search(r"([\d.]+)\s*pt", value, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _parse_margin(value: str) -> dict[str, float | None]:
    """Parse a CSS margin shorthand into a dict with top/right/bottom/left pt values.

    Returns a dict with keys ``top``, ``right``, ``bottom``, ``left``.
    Values are floats (pt) or ``None`` if a side is not a parseable pt value.
    Non-pt zero values (plain ``0``) map to 0.0.
    """
    parts = value.split()
    pts: list[float | None] = []
    for part in parts:
        if part == "0":
            pts.append(0.0)
        else:
            pts.append(_parse_pt(part))

    if len(pts) == 1:
        v = pts[0]
        return {"top": v, "right": v, "bottom": v, "left": v}
    if len(pts) == 2:
        tb, lr = pts[0], pts[1]
        return {"top": tb, "right": lr, "bottom": tb, "left": lr}
    if len(pts) == 3:
        return {"top": pts[0], "right": pts[1], "bottom": pts[2], "left": pts[1]}
    if len(pts) >= 4:
        return {"top": pts[0], "right": pts[1], "bottom": pts[2], "left": pts[3]}
    return {}


def _parse_padding(value: str) -> tuple[float | None, float | None]:
    """Parse a CSS padding shorthand, returning (top_bottom_pt, left_right_pt).

    Handles 1-value (all sides), 2-value (top/bottom left/right), and
    4-value (top right bottom left) shorthands. Returns (None, None) if
    the values are not pt units or cannot be parsed.
    """
    parts = value.split()
    pts: list[float] = []
    for part in parts:
        pt = _parse_pt(part)
        if pt is not None:
            pts.append(pt)
        else:
            return (None, None)
    if len(pts) == 1:
        return (pts[0], pts[0])
    if len(pts) == 2:
        return (pts[0], pts[1])
    if len(pts) == 4:
        return (pts[0], pts[1])  # top, right (use right for lr)
    return (None, None)


def _strip_comments(css: str) -> str:
    """Remove /* ... */ comments from a CSS string."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _parse_blocks(css: str) -> dict[str, dict[str, str]]:
    """Parse selector { property: value; } blocks from CSS.

    Returns a dict mapping selector → {property: value}.
    Later rules override earlier ones for the same selector+property.
    """
    result: dict[str, dict[str, str]] = {}
    # Match selector { declarations }
    for m in re.finditer(r"([^{]+)\{([^}]*)\}", css):
        selectors_raw = m.group(1).strip()
        declarations = m.group(2)
        # Split on comma for grouped selectors (e.g. "h1, h2")
        for selector in selectors_raw.split(","):
            selector = selector.strip()
            if not selector or selector.startswith("@"):
                continue
            if selector not in result:
                result[selector] = {}
            for decl in declarations.split(";"):
                decl = decl.strip()
                if ":" not in decl:
                    continue
                prop, _, val = decl.partition(":")
                prop = prop.strip().lower()
                val = val.strip()
                if prop and val:
                    # Strip !important
                    val = re.sub(r"\s*!important\s*$", "", val).strip()
                    result[selector][prop] = val
    return result


def _load_css_with_imports(css_path: Path, depth: int = 0) -> str:
    """Load CSS file, resolving @import statements recursively.

    Child properties (the file doing the importing) override parent properties
    because we prepend the imported content before the child's own rules.

    Depth-limited to ``_MAX_IMPORT_DEPTH`` to prevent infinite loops.
    """
    if depth > _MAX_IMPORT_DEPTH:
        _log.warning("CSS @import depth limit reached at %s — stopping recursion.", css_path)
        return ""

    try:
        css = css_path.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("Could not read CSS file %s: %s", css_path, exc)
        return ""

    # Find @import directives and resolve them
    import_pattern = re.compile(r'@import\s+["\']([^"\']+)["\']\s*;')
    imported_parts: list[str] = []

    def replace_import(m: re.Match[str]) -> str:
        import_file = css_path.parent / m.group(1)
        imported = _load_css_with_imports(import_file.resolve(), depth + 1)
        imported_parts.append(imported)
        return ""  # remove the @import line from the child CSS

    child_css = import_pattern.sub(replace_import, css)
    # Prepend all imported CSS so child rules (child_css) override them
    return "\n".join(imported_parts) + "\n" + child_css


# ---------------------------------------------------------------------------
# Public: parse_css_for_word
# ---------------------------------------------------------------------------


def parse_css_for_word(css_path: Path) -> dict[str, Any]:
    """Parse a CSS theme file and extract properties relevant to Word styling.

    Handles ``@import`` by reading the imported file relative to ``css_path.parent``
    and merging (child properties override parent). This supports the override-theme
    pattern where a sub-folder theme uses ``@import`` to inherit a parent theme.

    Returns a dict with zero or more of these keys:

    - ``font_body``              — body font name (str)
    - ``font_size_body``         — body font size in pt (float)
    - ``font_code``              — monospace font name (str)
    - ``color_h1``               — H1 colour hex (str, ``#rrggbb``)
    - ``font_size_h1``           — H1 font size in pt (float)
    - ``color_h2``               — H2 colour hex
    - ``font_size_h2``           — H2 font size in pt
    - ``color_h3``               — H3 colour hex
    - ``font_size_h3``           — H3 font size in pt
    - ``color_h4``               — H4 colour hex
    - ``font_size_h4``           — H4 font size in pt
    - ``color_table_header_bg``  — table header background hex
    - ``color_table_header_text``— table header text colour hex

    If the file cannot be parsed, returns an empty dict rather than crashing.
    """
    try:
        return _do_parse(css_path)
    except Exception as exc:
        _log.warning("Failed to parse CSS theme %s: %s — Word styling skipped.", css_path, exc)
        return {}


def _do_parse(css_path: Path) -> dict[str, Any]:
    raw_css = _load_css_with_imports(css_path)
    clean = _strip_comments(raw_css)
    blocks = _parse_blocks(clean)

    theme: dict[str, Any] = {}

    def _first_font(value: str) -> str:
        """Return the first font name from a font-family value."""
        first = value.split(",")[0].strip()
        # Strip surrounding quotes
        first = first.strip("'\"")
        return first if first else value

    def _first_color(value: str) -> str | None:
        """Extract a simple hex colour from a value string."""
        m = re.search(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", value)
        if m:
            return m.group(0).lower()
        return None

    # body / html
    for sel in ("body", "html", "html, body", "html,body"):
        props = blocks.get(sel, {})
        if "font-family" in props and "font_body" not in theme:
            theme["font_body"] = _first_font(props["font-family"])
        if "font-size" in props and "font_size_body" not in theme:
            pt = _parse_pt(props["font-size"])
            if pt is not None:
                theme["font_size_body"] = pt
        if "color" in props and "color_body" not in theme:
            col = _first_color(props["color"])
            if col:
                theme["color_body"] = col
        if "line-height" in props and "line_height_body" not in theme:
            try:
                theme["line_height_body"] = float(props["line-height"].strip())
            except ValueError:
                pass
        if "text-align" in props and "text_align_body" not in theme:
            theme["text_align_body"] = props["text-align"].strip().lower()

    # p — paragraph spacing and alignment
    for sel in ("p", "body p"):
        props = blocks.get(sel, {})
        # Handle both shorthand `margin` and explicit `margin-top`/`margin-bottom`
        if "margin" in props and ("para_space_after" not in theme or "para_space_before" not in theme):
            m = _parse_margin(props["margin"])
            if m.get("bottom") is not None and "para_space_after" not in theme:
                theme["para_space_after"] = m["bottom"]
            if m.get("top") is not None and "para_space_before" not in theme:
                theme["para_space_before"] = m["top"]
        for css_prop, theme_key in (
            ("margin-bottom", "para_space_after"),
            ("margin-top", "para_space_before"),
        ):
            if css_prop in props and theme_key not in theme:
                pt = _parse_pt(props[css_prop])
                if pt is not None:
                    theme[theme_key] = pt
        if "text-align" in props and "text_align_body" not in theme:
            theme["text_align_body"] = props["text-align"].strip().lower()

    # headings
    for level in range(1, 5):
        tag = f"h{level}"
        props = blocks.get(tag, {})
        if "font-family" in props:
            theme[f"font_{tag}"] = _first_font(props["font-family"])
        if "color" in props:
            col = _first_color(props["color"])
            if col:
                theme[f"color_{tag}"] = col
        if "font-size" in props:
            pt = _parse_pt(props["font-size"])
            if pt is not None:
                theme[f"font_size_{tag}"] = pt
        if "font-weight" in props:
            fw = props["font-weight"].strip().lower()
            try:
                theme[f"bold_{tag}"] = fw == "bold" or int(fw) >= 600
            except ValueError:
                theme[f"bold_{tag}"] = fw in ("bold", "bolder")
        # Heading spacing
        if "margin-top" in props:
            pt = _parse_pt(props["margin-top"])
            if pt is not None:
                theme[f"space_before_{tag}"] = pt
        if "margin-bottom" in props:
            pt = _parse_pt(props["margin-bottom"])
            if pt is not None:
                theme[f"space_after_{tag}"] = pt

    # code — inline monospace font, size, colour
    code_props = blocks.get("code", {})
    if "font-family" in code_props:
        theme["font_code"] = _first_font(code_props["font-family"])
    if "font-size" in code_props:
        pt = _parse_pt(code_props["font-size"])
        if pt is not None:
            theme["font_size_code"] = pt
    if "color" in code_props:
        col = _first_color(code_props["color"])
        if col:
            theme["color_code"] = col

    # pre — code block font size and left-border accent
    pre_props = blocks.get("pre", {})
    if "font-size" in pre_props:
        pt = _parse_pt(pre_props["font-size"])
        if pt is not None:
            theme["font_size_pre"] = pt
    if "border-left" in pre_props:
        val = pre_props["border-left"]
        col = _first_color(val)
        if col:
            theme["pre_border_color"] = col
        pt = _parse_pt(val)
        if pt is not None:
            theme["pre_border_pt"] = pt
    if "background" in pre_props:
        col = _first_color(pre_props["background"])
        if col:
            theme["pre_background_color"] = col

    # blockquote — left border, text colour, italic
    bq_props = blocks.get("blockquote", {})
    if "border-left" in bq_props:
        val = bq_props["border-left"]
        col = _first_color(val)
        if col:
            theme["blockquote_border_color"] = col
        pt = _parse_pt(val)
        if pt is not None:
            theme["blockquote_border_pt"] = pt
    if "color" in bq_props:
        col = _first_color(bq_props["color"])
        if col:
            theme["color_blockquote"] = col

    # hr — border-top color and size
    hr_props = blocks.get("hr", {})
    for css_prop in ("border-top", "border"):
        if css_prop in hr_props:
            val = hr_props[css_prop]
            col = _first_color(val)
            if col and "color_hr" not in theme:
                theme["color_hr"] = col
            pt = _parse_pt(val)
            if pt is not None and "size_hr" not in theme:
                theme["size_hr"] = pt

    # a — hyperlink colour
    a_props = blocks.get("a", {})
    if "color" in a_props:
        col = _first_color(a_props["color"])
        if col:
            theme["color_link"] = col

    # table — font size
    table_props = blocks.get("table", {})
    if "font-size" in table_props:
        pt = _parse_pt(table_props["font-size"])
        if pt is not None:
            theme["font_size_table"] = pt

    # table header (th) — background, colour, font size, transform, letter-spacing, padding
    th_props = blocks.get("th", {})
    if "background" in th_props:
        val = th_props["background"]
        col = _first_color(val)
        if col:
            theme["color_table_header_bg"] = col
    if "color" in th_props:
        col = _first_color(th_props["color"])
        if col:
            theme["color_table_header_text"] = col
    if "font-size" in th_props:
        pt = _parse_pt(th_props["font-size"])
        if pt is not None:
            theme["font_size_th"] = pt
    if th_props.get("text-transform", "").strip().lower() == "uppercase":
        theme["uppercase_th"] = True
    if "letter-spacing" in th_props:
        pt = _parse_pt(th_props["letter-spacing"])
        if pt is not None:
            theme["letter_spacing_th_pt"] = pt
    if "padding" in th_props:
        tb, lr = _parse_padding(th_props["padding"])
        if tb is not None:
            theme.setdefault("padding_cell_tb_pt", tb)
        if lr is not None:
            theme.setdefault("padding_cell_lr_pt", lr)

    # table body cells (td) — bottom border colour, size, and padding
    td_props = blocks.get("td", {})
    if "border-bottom" in td_props:
        val = td_props["border-bottom"]
        col = _first_color(val)
        if col:
            theme["color_table_cell_border"] = col
        pt = _parse_pt(val)
        if pt is not None:
            theme["size_table_cell_border"] = pt
    if "padding" in td_props:
        tb, lr = _parse_padding(td_props["padding"])
        if tb is not None:
            theme.setdefault("padding_cell_tb_pt", tb)
        if lr is not None:
            theme.setdefault("padding_cell_lr_pt", lr)

    # alternating row background — tr:nth-child(even) td
    even_row_props = blocks.get("tr:nth-child(even) td", {})
    if "background" in even_row_props:
        col = _first_color(even_row_props["background"])
        if col:
            theme["color_table_row_alt_bg"] = col

    # last row border — tr:last-child td
    last_row_props = blocks.get("tr:last-child td", {})
    if "border-bottom" in last_row_props:
        val = last_row_props["border-bottom"]
        col = _first_color(val)
        if col:
            theme["color_table_last_row_border"] = col
        pt = _parse_pt(val)
        if pt is not None:
            theme["size_table_last_row_border"] = pt

    # strong — colour for bold text
    strong_props = blocks.get("strong", {})
    if "color" in strong_props:
        col = _first_color(strong_props["color"])
        if col:
            theme["color_strong"] = col

    # em — colour for italic text
    em_props = blocks.get("em", {})
    if "color" in em_props:
        col = _first_color(em_props["color"])
        if col:
            theme["color_em"] = col

    # h1 border-bottom
    h1_props = blocks.get("h1", {})
    if "border-bottom" in h1_props:
        val = h1_props["border-bottom"]
        col = _first_color(val)
        if col:
            theme["h1_border_color"] = col
        pt = _parse_pt(val)
        if pt is not None:
            theme["h1_border_pt"] = pt

    return theme


# ---------------------------------------------------------------------------
# Public: apply_theme_to_doc
# ---------------------------------------------------------------------------


def _apply_font_name(font: Any, name: str) -> None:
    """Set a font name and strip any inherited Word theme-font attributes.

    python-docx's ``font.name`` setter writes ``w:ascii`` / ``w:hAnsi`` but
    does NOT remove ``w:asciiTheme`` / ``w:hAnsiTheme``.  Word treats theme
    attributes as higher-priority than explicit names, so Calibri Light keeps
    appearing even after the setter runs.  We strip the theme attributes here
    so the explicit name wins.
    """
    font.name = name
    rFonts = font._element.rPr.get_or_add_rFonts() if hasattr(font._element, "rPr") else None
    # Access rFonts via the lower-level XML when available
    try:
        rPr = font._element.rPr
        if rPr is None:
            return
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            return
        for attr in (
            qn("w:asciiTheme"),
            qn("w:hAnsiTheme"),
            qn("w:eastAsiaTheme"),
            qn("w:cstheme"),
        ):
            if rFonts.get(attr) is not None:
                del rFonts.attrib[attr]
    except Exception:
        pass


def apply_theme_to_doc(doc: Any, theme: dict[str, Any]) -> None:
    """Apply a parsed CSS theme dict to Word document styles.

    Sets font name and size on Normal, headings, and List Paragraph styles.
    Silently skips styles that don't exist in the document.

    Parameters
    ----------
    doc:
        The python-docx Document to modify (in-place).
    theme:
        Dict returned by ``parse_css_for_word()``. May be empty — in that case
        this function is a no-op.
    """
    if not theme:
        return

    font_body = theme.get("font_body")
    font_size_body = theme.get("font_size_body")

    _ALIGN_MAP = {
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "centre": WD_ALIGN_PARAGRAPH.CENTER,
    }

    # Normal style
    try:
        normal = doc.styles["Normal"]
        if font_body:
            _apply_font_name(normal.font, font_body)
        if font_size_body is not None:
            normal.font.size = Pt(font_size_body)
        if "color_body" in theme:
            r, g, b = _hex_to_rgb(theme["color_body"])
            normal.font.color.rgb = RGBColor(r, g, b)
        if "text_align_body" in theme:
            align = _ALIGN_MAP.get(theme["text_align_body"])
            if align is not None:
                normal.paragraph_format.alignment = align
        if "para_space_after" in theme:
            normal.paragraph_format.space_after = Pt(theme["para_space_after"])
        if "para_space_before" in theme:
            normal.paragraph_format.space_before = Pt(theme["para_space_before"])
        if "line_height_body" in theme:
            normal.paragraph_format.line_spacing = theme["line_height_body"]
            normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    except KeyError:
        pass

    # List Paragraph — match Normal font and color
    try:
        lp = doc.styles["List Paragraph"]
        if font_body:
            _apply_font_name(lp.font, font_body)
        if font_size_body is not None:
            lp.font.size = Pt(font_size_body)
        if "color_body" in theme:
            r, g, b = _hex_to_rgb(theme["color_body"])
            lp.font.color.rgb = RGBColor(r, g, b)
    except KeyError:
        pass

    # Hyperlink style — apply link colour
    try:
        hl = doc.styles["Hyperlink"]
        if "color_link" in theme:
            r, g, b = _hex_to_rgb(theme["color_link"])
            hl.font.color.rgb = RGBColor(r, g, b)
    except KeyError:
        pass

    # Title and Subtitle styles — override with theme font so cover page matches
    for style_name in ("Title", "Subtitle"):
        try:
            s = doc.styles[style_name]
            if font_body:
                _apply_font_name(s.font, font_body)
        except KeyError:
            pass

    # Heading styles H1–H4
    for level in range(1, 5):
        style_name = f"Heading {level}"
        tag = f"h{level}"
        color_key = f"color_{tag}"
        size_key = f"font_size_{tag}"

        try:
            heading_style = doc.styles[style_name]
        except KeyError:
            continue

        # Font name — only set if explicitly declared for this heading level
        heading_font = theme.get(f"font_{tag}")
        if heading_font:
            _apply_font_name(heading_style.font, heading_font)
        elif font_body:
            # Fall back to body font if no heading-specific font
            _apply_font_name(heading_style.font, font_body)

        # Font size
        if size_key in theme:
            heading_style.font.size = Pt(theme[size_key])

        # Font colour
        if color_key in theme:
            r, g, b = _hex_to_rgb(theme[color_key])
            heading_style.font.color.rgb = RGBColor(r, g, b)

        # Bold
        bold_key = f"bold_{tag}"
        if bold_key in theme:
            heading_style.font.bold = theme[bold_key]

        # Spacing
        if f"space_before_{tag}" in theme:
            heading_style.paragraph_format.space_before = Pt(theme[f"space_before_{tag}"])
        if f"space_after_{tag}" in theme:
            heading_style.paragraph_format.space_after = Pt(theme[f"space_after_{tag}"])


# ---------------------------------------------------------------------------
# Public: set_cell_shading
# ---------------------------------------------------------------------------


def resolve_docx_theme(doc_path: Path, repo_root: Path) -> "dict[str, Any] | None":
    """Find and parse the nearest Word CSS theme for *doc_path*.

    Walks from ``doc_path.parent`` up to (and including) ``repo_root``.  At
    each directory level it looks for:

    1. ``_docx-theme.css`` — Word-specific overrides (takes priority)
    2. ``_pdf-theme.css``  — fallback shared theme

    Returns the parsed theme dict from the first file found, or ``None`` if no
    theme file exists anywhere in the hierarchy.

    Parameters
    ----------
    doc_path:
        Path to the source ``.md`` file being built.
    repo_root:
        Top of the search hierarchy (typically the workspace or repo root).
    """
    try:
        start = doc_path.resolve().parent
        stop = repo_root.resolve()
    except Exception:
        return None

    # Build the list of directories to check, from deepest to shallowest
    dirs: list[Path] = []
    current = start
    while True:
        dirs.append(current)
        if current == stop:
            break
        parent = current.parent
        if parent == current:
            # filesystem root — stop
            break
        current = parent

    for d in dirs:
        for filename in ("_docx-theme.css", "_theme.css", "_pdf-theme.css"):
            candidate = d / filename
            if candidate.is_file():
                _log.debug("resolve_docx_theme: using %s for %s", candidate, doc_path)
                return parse_css_for_word(candidate)

    return None


def set_para_shading(paragraph: Any, hex_color: str) -> None:
    """Set a paragraph's background shading colour using w:shd on the pPr.

    Parameters
    ----------
    paragraph:
        A python-docx ``Paragraph`` object.
    hex_color:
        Hex colour string (``#rrggbb`` or ``#rgb``). Leading ``#`` is stripped.
    """
    fill = hex_color.lstrip("#").upper()
    pPr = paragraph._p.get_or_add_pPr()
    for existing in pPr.findall(qn("w:shd")):
        pPr.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pPr.append(shd)


def patch_docx_theme_fonts(path: "Path", font_body: str, font_heading: str | None = None) -> None:
    """Patch ``word/theme/theme1.xml`` in a saved .docx to set the major/minor fonts.

    This ensures that any element referencing the document theme font
    (via ``w:asciiTheme``) renders in *font_body* rather than the default
    Calibri/Cambria, and that renderers that do font substitution (e.g.
    LibreOffice on Linux) use the correct font family.

    Parameters
    ----------
    path:
        Path to the saved .docx or .dotx file (patched in-place).
    font_body:
        Font name to use as the minor (body) theme font.
    font_heading:
        Font name to use as the major (heading) theme font.
        Defaults to *font_body* if not provided.
    """
    import re
    import shutil
    import zipfile

    heading_font = font_heading or font_body
    tmp = path.with_suffix(".tmptheme")
    shutil.move(str(path), str(tmp))
    try:
        with zipfile.ZipFile(tmp, "r") as zin:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "word/theme/theme1.xml":
                        xml = data.decode("utf-8")
                        # Patch <a:majorFont><a:latin typeface="..."/>
                        xml = re.sub(
                            r'(<a:majorFont>\s*<a:latin typeface=")[^"]*(")',
                            rf'\g<1>{heading_font}\g<2>',
                            xml, flags=re.DOTALL,
                        )
                        # Patch <a:minorFont><a:latin typeface="..."/>
                        xml = re.sub(
                            r'(<a:minorFont>\s*<a:latin typeface=")[^"]*(")',
                            rf'\g<1>{font_body}\g<2>',
                            xml, flags=re.DOTALL,
                        )
                        data = xml.encode("utf-8")
                    zout.writestr(item, data)
    except Exception:
        shutil.move(str(tmp), str(path))
        raise
    finally:
        if tmp.exists():
            tmp.unlink()


def set_cell_shading(cell: Any, hex_color: str) -> None:
    """Set a table cell's background colour using OxmlElement (w:shd).

    Parameters
    ----------
    cell:
        A python-docx ``_Cell`` object.
    hex_color:
        Hex colour string (``#rrggbb`` or ``#rgb``). The leading ``#`` is
        stripped automatically.
    """
    fill = hex_color.lstrip("#").upper()
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    # Remove any existing w:shd
    for existing in tcPr.findall(qn("w:shd")):
        tcPr.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)
