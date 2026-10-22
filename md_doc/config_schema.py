"""Lightweight validation for ``_meta.yml`` / frontmatter config.

The config cascade (``config.py``) accepts any YAML and silently ignores keys it
doesn't recognise, so a typo like ``cover_bard: true`` or ``output_foramt: pdf``
produces wrong output with no warning. This module knows the documented key set
(see ``docs/handbook.md#configuration`` / ``AGENTS.md``) and reports:

- **warnings** for unknown keys (with a "did you mean …?" suggestion), and
- **errors** for values of the wrong type / outside an allowed enum.

It has no third-party dependencies and returns plain ``(severity, message)``
tuples so callers (the linter) can wrap them in their own issue type.
"""

from __future__ import annotations

import difflib
from typing import Any, Iterable

from .config import is_boolish
from .critic import MODES as REVIEW_MODES
from .pdf_features import (
    BAR_LAYOUTS,
    CHAPTER_BREAKS,
    IMAGE_FITS,
    NUMBER_STYLES,
    PDF_VARIANTS,
    PRINT_MARKS,
)

_FORMATS = {"pdf", "docx", "dotx", "pptx"}
_LCR = {"left", "center", "right"}

# Keys whose value must be a boolean.
BOOL_KEYS: frozenset[str] = frozenset(
    {
        "pdf_forms",
        "include_md_in_share",
        "preserve_blank_lines",
        "preserve_line_breaks",
        "cover_page",
        "cover_divider",
        "cover_footer",
        "cover_footer_line",
        "cover_bar",
        "cover_text_on_bar",
        "cover_meta",
        "cover_date",
        "toc_page_numbers",
        "cover_stripe",
        "page_header_bar",
        "section_bar",
        "section_bar_text_on_bar",
        "draft",
        "export",
        # PDF container & production
        "pdf_tags",
        "pdf_custom_metadata",
        "pdf_presentational_hints",
        "pdf_optimize_images",
        "pdf_uncompressed",
        "pdf_srgb",
        "pdf_full_fonts",
        "pdf_hinting",
        "pdf_attach_source",
        "pdf_bookmarks",
        "pdf_layout_check",
        # typography, numbering, navigation, page layout (PDF)
        "tabular_numbers",
        "hyphenate",
        "page_footnotes",
        "xref_pages",
        "numbered_headings",
        "duplex",
        "header_first_page",
    }
)

#: Whole-number keys and the range each accepts (inclusive).
INT_KEYS: dict[str, tuple[int, int]] = {
    "pdf_jpeg_quality": (0, 95),
    "pdf_image_dpi": (36, 1200),
    "pdf_bookmark_depth": (1, 6),
    "numbered_headings_depth": (1, 4),
    "columns": (2, 6),
}

# Keys whose value must be one of a fixed set (checked case-insensitively).
ENUM_KEYS: dict[str, set[str]] = {
    "dotx_field_type": {"form", "merge"},
    "body_text_align": {"justify", "left", "center", "right"},
    "cover_text_align": _LCR,
    "cover_bar_position": {"top", "bottom", "both"},
    "header_logo_position": _LCR,
    "header_text_position": _LCR,
    "page_header_bar_logo_position": _LCR,
    "sync_target": {"azure", "s3", "local"},
    "export_format": _FORMATS,
    "bullet_style": {"leaf", "dot", "square", "diamond"},
    "slide_size": {"16:9", "4:3"},
    "slide_split": {"h1", "h2", "marker"},
    "pdf_variant": set(PDF_VARIANTS),
    "chapter_break": set(CHAPTER_BREAKS),
    "heading_number_style": set(NUMBER_STYLES),
    "image_fit": set(IMAGE_FITS),
    "print_marks": set(PRINT_MARKS),
    "review_markup": set(REVIEW_MODES),
    "header_layout": set(BAR_LAYOUTS),
    "footer_layout": set(BAR_LAYOUTS),
}

# Every documented key. Unknown keys outside this set trigger a warning.
KNOWN_KEYS: frozenset[str] = frozenset(
    {
        # metadata & output control
        "title",
        "product",
        "document_type",
        "version",
        "status",
        "author",
        "date",
        "outputs",
        "output_filename",
        "imported_from",
        "imported_on",
        "output_dir",
        "pdf_forms",
        "include_md_in_share",
        # theme & styling
        "pdf_theme",
        "dotx_field_type",
        "body_text_align",
        "table_col_widths",
        "preserve_blank_lines",
        "preserve_line_breaks",
        "css_vars",
        # slides (pptx)
        "pptx_template",
        "slide_size",
        "slide_split",
        # cover page
        "cover_page",
        "cover_label",
        "cover_text_align",
        "cover_background",
        "cover_divider",
        "cover_meta_label",
        "cover_meta_author",
        "cover_meta",
        "cover_date",
        "cover_subtitle",
        "toc_title",
        "toc_depth",
        "toc_page_numbers",
        "bullet_style",
        "bullet_color",
        "cover_version",
        "cover_footer",
        "cover_footer_text",
        "cover_footer_line",
        "cover_footer_color",
        "cover_logo",
        "cover_bar",
        "cover_bar_position",
        "cover_bar_height",
        "cover_bar_top_height",
        "cover_bar_bottom_height",
        "cover_bar_logo",
        "cover_text_on_bar",
        "cover_stripe",
        "cover_stripe_height",
        "cover_stripe_width",
        # headers & footers
        "header_logo",
        "header_logo_position",
        "header_logo_height",
        "header_text",
        "header_text_position",
        "footer_left",
        "footer_center",
        "footer_right",
        # page header bar
        "page_header_bar",
        "page_header_bar_color",
        "page_header_bar_text_color",
        "page_header_bar_height",
        "page_header_bar_padding",
        "page_header_bar_offset",
        "page_header_bar_logo",
        "page_header_bar_logo_position",
        "page_header_bar_logos",
        # section heading styling
        "section_bar",
        "section_bar_color",
        "section_bar_text_on_bar",
        "section_bar_text_color",
        "section_bar_headings",
        # sync & integration
        "sync_target",
        "sync_config",
        # export workflow
        "export",
        "export_format",
        "export_path",
        "export_filename",
        "export_folder",
        "tags",
        # PDF container & production
        "pdf_variant",
        "pdf_version",
        "pdf_identifier",
        "pdf_jpeg_quality",
        "pdf_image_dpi",
        "pdf_zoom",
        "pdf_attachments",
        "pdf_xmp",
        "pdf_color_profile",
        "pdf_bookmark_depth",
        "description",
        "keywords",
        # typography, numbering, navigation, page layout (PDF)
        "lang",
        "fonts",
        "font_features",
        "numbered_headings_depth",
        "heading_number_style",
        "binding_margin",
        "chapter_break",
        "columns",
        "column_gap",
        "column_rule",
        "image_fit",
        "image_resolution",
        "print_marks",
        "bleed",
        "header_layout",
        "footer_layout",
        # review markup (CriticMarkup)
        "review_markup",
        "review_author",
        "review_exports",
    }
    | BOOL_KEYS
)

Issue = tuple[str, str]  # (severity, message)


def _norm_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def validate_config(config: dict[str, Any]) -> list[Issue]:
    """Return ``(severity, message)`` issues for *config* (one mapping level).

    Validate the keys a user actually wrote — pass a document's frontmatter or a
    single ``_meta.yml`` mapping, not the fully-merged cascade (that would report
    an inherited typo once per descendant document).
    """
    issues: list[Issue] = []
    if not isinstance(config, dict):
        return issues

    for key, value in config.items():
        if key not in KNOWN_KEYS:
            # Config keys double as Jinja variables, so arbitrary custom keys are
            # legitimate. Only flag a key that is a near-miss of a reserved
            # control key (likely a typo, e.g. ``cover_bard`` → ``cover_bar``);
            # stay silent otherwise.
            hint = difflib.get_close_matches(key, KNOWN_KEYS, n=1, cutoff=0.8)
            if hint:
                issues.append(
                    ("warning", f"Unknown config key '{key}' — did you mean '{hint[0]}'?")
                )
            continue

        # Values are validated before Jinja rendering, so an unresolved template
        # (e.g. ``cover_page: "{{ want_cover }}"``) can't be type-checked yet —
        # its real type is only known after rendering. Skip type checks for it.
        if isinstance(value, str) and "{{" in value:
            continue

        if key in BOOL_KEYS and not is_boolish(value):
            issues.append(
                (
                    "error",
                    f"'{key}' must be true or false (or a yes/no string), "
                    f"got {type(value).__name__} {value!r}",
                )
            )
        elif key in ENUM_KEYS:
            allowed = ENUM_KEYS[key]
            for item in _norm_list(value):
                if str(item).lower() not in allowed:
                    issues.append(
                        (
                            "error",
                            f"'{key}' has invalid value '{item}'; "
                            f"expected one of {sorted(allowed)}",
                        )
                    )
        elif key == "outputs":
            for item in _norm_list(value):
                if str(item).lower() not in _FORMATS:
                    issues.append(("error", f"Unknown output format '{item}' in 'outputs'"))
        elif key == "table_col_widths":
            if not isinstance(value, list) or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in value
            ):
                issues.append(("error", "'table_col_widths' must be a list of numbers"))
        elif key == "tags":
            if not isinstance(value, (list, str)):
                issues.append(("error", "'tags' must be a list (or a single string)"))
        elif key in INT_KEYS:
            low, high = INT_KEYS[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, str))
                or not (str(value).strip().lstrip("-").isdigit() and low <= int(str(value)) <= high)
            ):
                issues.append(("error", f"'{key}' must be a whole number from {low} to {high}"))
        elif key == "pdf_zoom":
            try:
                ok = not isinstance(value, bool) and 0.1 <= float(value) <= 10
            except (TypeError, ValueError):
                ok = False
            if not ok:
                issues.append(("error", "'pdf_zoom' must be a number from 0.1 to 10"))
        elif key == "review_exports":
            from .critic import VARIANTS

            names = [str(item).strip().lower() for item in _norm_list(value)]
            bad = [n for n in names if n not in VARIANTS]
            if bad:
                issues.append(
                    (
                        "error",
                        f"'review_exports' has unknown variant(s) {bad}; "
                        f"expected any of {sorted(VARIANTS)}",
                    )
                )
        elif key in {"pdf_attachments", "pdf_xmp"}:
            if not all(isinstance(item, str) for item in _norm_list(value)):
                issues.append(("error", f"'{key}' must be a path or a list of paths"))
        elif key == "fonts":
            if not isinstance(value, list) or not all(
                isinstance(item, (str, dict)) for item in value
            ):
                issues.append(
                    ("error", "'fonts' must be a list of paths or {family, path, …} mappings")
                )

    return issues


def known_keys() -> Iterable[str]:
    """Return the sorted documented config keys (used by tooling/tests)."""
    return sorted(KNOWN_KEYS)
