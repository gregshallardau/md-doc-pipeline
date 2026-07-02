"""Lightweight validation for ``_meta.yml`` / frontmatter config.

The config cascade (``config.py``) accepts any YAML and silently ignores keys it
doesn't recognise, so a typo like ``cover_bard: true`` or ``output_foramt: pdf``
produces wrong output with no warning. This module knows the documented key set
(see ``docs/config-reference.md`` / ``CLAUDE.md``) and reports:

- **warnings** for unknown keys (with a "did you mean …?" suggestion), and
- **errors** for values of the wrong type / outside an allowed enum.

It has no third-party dependencies and returns plain ``(severity, message)``
tuples so callers (the linter) can wrap them in their own issue type.
"""

from __future__ import annotations

import difflib
from typing import Any, Iterable

_FORMATS = {"pdf", "docx", "dotx"}
_LR = {"left", "right"}
_LCR = {"left", "center", "right"}

# Keys whose value must be a boolean.
BOOL_KEYS: frozenset[str] = frozenset(
    {
        "pdf_forms",
        "include_md_in_share",
        "cover_page",
        "cover_divider",
        "cover_footer",
        "cover_footer_line",
        "cover_bar",
        "cover_text_on_bar",
        "cover_stripe",
        "page_header_bar",
        "section_bar",
        "section_bar_text_on_bar",
        "draft",
        "export",
    }
)

# Keys whose value must be one of a fixed set (checked case-insensitively).
ENUM_KEYS: dict[str, set[str]] = {
    "dotx_field_type": {"form", "merge"},
    "body_text_align": {"justify", "left", "center", "right"},
    "cover_text_align": _LR,
    "cover_bar_position": {"top", "bottom", "both"},
    "header_logo_position": _LCR,
    "header_text_position": _LCR,
    "page_header_bar_logo_position": _LCR,
    "sync_target": {"azure", "s3", "local"},
    "export_format": _FORMATS,
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
        "output_dir",
        "pdf_forms",
        "include_md_in_share",
        # theme & styling
        "pdf_theme",
        "dotx_field_type",
        "body_text_align",
        "table_col_widths",
        # cover page
        "cover_page",
        "cover_label",
        "cover_text_align",
        "cover_background",
        "cover_divider",
        "cover_meta_label",
        "cover_meta_author",
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
    }
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

        if key in BOOL_KEYS and not isinstance(value, bool):
            issues.append(("error", f"'{key}' must be true or false, got {type(value).__name__}"))
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

    return issues


def known_keys() -> Iterable[str]:
    """Return the sorted documented config keys (used by tooling/tests)."""
    return sorted(KNOWN_KEYS)
