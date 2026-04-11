"""Tests for the Jinja2 Markdown renderer."""

import textwrap
from pathlib import Path

import pytest

from md_doc.renderer import render, render_string


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_repo(tmp_path):
    """Minimal repo with .git marker and root _meta.yml."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def write_meta(directory: Path, data: str) -> None:
    (directory / "_meta.yml").write_text(textwrap.dedent(data))


def write_md(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content))


# ── render_string tests ───────────────────────────────────────────────────────

class TestRenderString:
    def test_plain_passthrough(self):
        assert render_string("# Hello", {}) == "# Hello"

    def test_variable_substitution(self):
        result = render_string("Hello {{ name }}!", {"name": "Greg"})
        assert result == "Hello Greg!"

    def test_for_loop(self):
        source = "{% for item in items %}- {{ item }}\n{% endfor %}"
        result = render_string(source, {"items": ["a", "b", "c"]})
        assert "- a" in result
        assert "- b" in result
        assert "- c" in result

    def test_undefined_variable_renders_blank(self):
        result = render_string("Hello {{ missing }}!", {})
        assert result == "Hello !"

    def test_strict_raises_on_undefined(self):
        from jinja2 import UndefinedError
        with pytest.raises(UndefinedError):
            render_string("Hello {{ missing }}!", {}, strict=True)

    def test_include_fragment(self, tmp_path):
        fragment = tmp_path / "header.md"
        fragment.write_text("## AIB Header\n")
        source = "{% include 'header.md' %}\n# Body"
        result = render_string(source, {}, search_dirs=[tmp_path])
        assert "## AIB Header" in result
        assert "# Body" in result


# ── render() (file-based) tests ───────────────────────────────────────────────

class TestRender:
    def test_simple_variable_from_meta(self, tmp_repo):
        write_meta(tmp_repo, "product: Acme Insurance\n")
        doc = tmp_repo / "letter.md"
        write_md(doc, "Product: {{ product }}\n")
        result = render(doc, repo_root=tmp_repo)
        assert "Product: Acme Insurance" in result

    def test_frontmatter_preserved_verbatim(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        content = "---\ntitle: My Doc\n---\n\nHello {{ world }}\n"
        doc.write_text(content)
        result = render(doc, repo_root=tmp_repo, extra_context={"world": "Greg"})
        assert result.startswith("---\ntitle: My Doc\n---\n")
        assert "Hello Greg" in result

    def test_frontmatter_variable_available(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        doc.write_text("---\nauthor: Greg\n---\n\nBy {{ author }}\n")
        result = render(doc, repo_root=tmp_repo)
        assert "By Greg" in result

    def test_include_from_templates_subdir(self, tmp_repo):
        templates = tmp_repo / "templates"
        templates.mkdir()
        (templates / "footer.md").write_text("---\n*Confidential*\n")
        doc = tmp_repo / "doc.md"
        doc.write_text("# Main\n\n{% include 'footer.md' %}\n")
        result = render(doc, repo_root=tmp_repo)
        assert "*Confidential*" in result

    def test_include_from_doc_local_templates(self, tmp_repo):
        subdir = tmp_repo / "binder"
        subdir.mkdir()
        local_templates = subdir / "templates"
        local_templates.mkdir()
        (local_templates / "intro.md").write_text("## Product Intro\n")
        doc = subdir / "letter.md"
        doc.write_text("{% include 'intro.md' %}\n# Body\n")
        result = render(doc, repo_root=tmp_repo)
        assert "## Product Intro" in result

    def test_extra_context_overrides_config(self, tmp_repo):
        write_meta(tmp_repo, "product: Old\n")
        doc = tmp_repo / "doc.md"
        doc.write_text("{{ product }}\n")
        result = render(doc, repo_root=tmp_repo, extra_context={"product": "Override"})
        assert "Override" in result

    def test_config_values_available(self, tmp_repo):
        write_meta(tmp_repo, "version: '2.1'\nstatus: draft\n")
        doc = tmp_repo / "doc.md"
        doc.write_text("Version {{ version }} — {{ status }}\n")
        result = render(doc, repo_root=tmp_repo)
        assert "Version 2.1" in result
        assert "draft" in result

    def test_no_frontmatter_renders_body(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        doc.write_text("# Hello {{ name }}\n")
        result = render(doc, repo_root=tmp_repo, extra_context={"name": "World"})
        assert result == "# Hello World\n"

    def test_nested_templates_intermediate_dir(self, tmp_repo):
        """templates/ in an intermediate ancestor dir is found (deepest wins)."""
        mid = tmp_repo / "products"
        deep = mid / "renewals"
        deep.mkdir(parents=True)
        (mid / "templates").mkdir()
        (mid / "templates" / "mid-header.md").write_text("## Mid Header\n")
        doc = deep / "letter.md"
        doc.write_text("{% include 'mid-header.md' %}\n# Body\n")
        result = render(doc, repo_root=tmp_repo)
        assert "## Mid Header" in result

    def test_nested_templates_deeper_overrides_ancestor(self, tmp_repo):
        """A templates/fragment.md closer to the document overrides the same name higher up."""
        mid = tmp_repo / "products"
        deep = mid / "renewals"
        deep.mkdir(parents=True)
        (mid / "templates").mkdir()
        (mid / "templates" / "header.md").write_text("## Mid Header\n")
        (deep / "templates").mkdir()
        (deep / "templates" / "header.md").write_text("## Deep Header\n")
        doc = deep / "letter.md"
        doc.write_text("{% include 'header.md' %}\n# Body\n")
        result = render(doc, repo_root=tmp_repo)
        assert "## Deep Header" in result
        assert "## Mid Header" not in result
