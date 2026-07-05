"""Shared parsing for the ``?[...]`` form-field shorthand.

Lives outside ``builders/pdf.py`` so the linter and the Word builder can parse
field specs without importing WeasyPrint. The PDF builder renders these specs
to HTML; the dotx builder maps them to Word form fields; the linter validates
them.

Spec grammar::

    ?[TYPE: NAME, attr=value, flag]           input / textarea / checkbox / …
    ?[select: NAME | Option 1 | Option 2]     options after the first |
    ?[yesno: NAME]                            Yes/No checkbox pair
    ?[submit LABEL]                           submit button
    ?[row] … ?[/row]                          borderless side-by-side cells
    ?[box[: widths=70,30]] … ?[/box]          bordered field-grid
"""

from __future__ import annotations

import re

FIELD_RE = re.compile(r"\?\[(.+?)\]")

# Input types passed through verbatim; anything else falls back to text.
INPUT_TYPES = ("text", "email", "date", "number", "tel", "url")

# Field types with |-separated options.
OPTION_TYPES = frozenset({"select", "radio", "radio-inline", "checkbox-inline"})

KNOWN_FIELD_TYPES = frozenset(
    (*INPUT_TYPES, "textarea", "checkbox", "signature", "yesno", *OPTION_TYPES)
)

# Structural markers that are not fields themselves.
_STRUCTURAL_RE = re.compile(r"^(/?(row|box)(:.*)?|submit(\s.*)?)$", re.IGNORECASE | re.DOTALL)


def parse_field_attrs(attr_str: str) -> dict[str, str | bool]:
    """Parse comma-separated ``key=value`` / bare-flag attributes."""
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


def parse_field_spec(spec: str) -> tuple[str, str, list[str], dict[str, str | bool]] | None:
    """Parse a ``?[...]`` spec into ``(type, name, options, attrs)``.

    Returns ``None`` for structural markers (``row``/``box``/``submit``) and
    specs without a ``TYPE:`` prefix.
    """
    spec = spec.strip()
    if _STRUCTURAL_RE.match(spec) or ":" not in spec:
        return None
    type_part, rest = spec.split(":", 1)
    ftype = type_part.strip().lower()
    if ftype in OPTION_TYPES:
        parts = [p.strip() for p in rest.split("|")]
        name_attrs = parse_field_attrs(parts[0]) if parts else {}
        name = next(iter(name_attrs), "field")
        options = parts[1:] if len(parts) > 1 else []
        return ftype, str(name), options, name_attrs
    parts = rest.split(",")
    name = parts[0].strip()
    attrs = parse_field_attrs(",".join(parts[1:])) if len(parts) > 1 else {}
    return ftype, name, [], attrs


def iter_field_specs(md_content: str) -> list[tuple[str, str, list[str], dict[str, str | bool]]]:
    """All parsed field specs in *md_content* (structural markers skipped)."""
    out = []
    for m in FIELD_RE.finditer(md_content):
        parsed = parse_field_spec(m.group(1))
        if parsed is not None:
            out.append(parsed)
    return out
