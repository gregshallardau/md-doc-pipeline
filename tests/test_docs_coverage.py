"""Every user-facing feature must be documented, and the docs must not rot."""

from __future__ import annotations

import re
from pathlib import Path

import click

from md_doc.builders._assets import _MDDOC_PROP_TO_KEY
from md_doc.cli import main
from md_doc.config_schema import BOOL_KEYS, ENUM_KEYS, KNOWN_KEYS

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def _walk(cmd: click.Command, path: list[str]):
    yield path, cmd
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            yield from _walk(sub, [*path, name])


def test_every_config_key_is_in_the_key_index() -> None:
    reference = (DOCS / "handbook.md").read_text()
    keys = set(KNOWN_KEYS) | set(BOOL_KEYS) | set(ENUM_KEYS)
    missing = sorted(k for k in keys if f"| `{k}` |" not in reference)
    assert not missing, f"keys missing from docs/handbook.md#configuration key index: {missing}"


def test_every_cli_command_and_option_is_documented() -> None:
    text = (DOCS / "handbook.md").read_text()
    missing: list[str] = []
    for path, cmd in _walk(main, ["md-doc"]):
        name = " ".join(path[1:])
        if name and f"md-doc {name}" not in text:
            missing.append(f"command {name}")
        for param in cmd.params:
            if isinstance(param, click.Option):
                for opt in param.opts:
                    if opt.startswith("--") and opt != "--help" and opt not in text:
                        missing.append(f"{name or 'md-doc'} {opt}")
    assert not missing, f"undocumented in docs/handbook.md#commands: {missing}"


def test_every_brand_custom_property_is_documented() -> None:
    text = (DOCS / "handbook.md").read_text()
    missing = sorted(p for p in _MDDOC_PROP_TO_KEY if f"--mddoc-{p}" not in text)
    assert not missing, f"--mddoc-* properties missing from docs/handbook.md#themes: {missing}"


def test_every_guide_is_linked_from_the_readme() -> None:
    readme = (ROOT / "README.md").read_text()
    unlinked = sorted(p.name for p in DOCS.glob("*.md") if f"docs/{p.name}" not in readme)
    assert not unlinked, f"guides not linked from README.md: {unlinked}"


# Markdown links only: image examples such as ![alt](path/to/image.png) are syntax demos.
_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\((?!https?:|mailto:|#)([^)#\s]+)(?:#[^)]*)?\)")


def test_relative_links_in_docs_resolve() -> None:
    broken: list[str] = []
    for md in [
        ROOT / "README.md",
        *sorted(DOCS.glob("*.md")),
    ]:
        for target in _LINK_RE.findall(md.read_text()):
            if not (md.parent / target).resolve().exists():
                broken.append(f"{md.relative_to(ROOT)} -> {target}")
    assert not broken, f"broken relative links: {broken}"


_TOKENIZERS = [
    ROOT / "md-doc-web-editor" / "md_doc_web_editor" / "static" / "tokenizers.js",
    ROOT / "filament-md-doc" / "resources" / "js" / "tokenizers.js",
]


def test_editor_highlighters_know_every_config_key() -> None:
    """The browser editors colour config keys from a hand-kept list; keep it complete."""
    keys = set(KNOWN_KEYS) | set(BOOL_KEYS) | set(ENUM_KEYS)
    for path in _TOKENIZERS:
        listed = set(re.findall(r"'([a-z_]+)'", path.read_text()))
        missing = sorted(keys - listed)
        assert not missing, f"{path.relative_to(ROOT)} does not highlight: {missing}"
