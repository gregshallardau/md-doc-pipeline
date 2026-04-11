"""Tests for the cascading _meta.yml config system."""

import textwrap
from pathlib import Path

import pytest

from md_doc.config import load_config, get_output_formats, should_sync_md


@pytest.fixture()
def tmp_repo(tmp_path):
    """Create a minimal repo layout with .git marker."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def write_meta(directory: Path, data: str) -> None:
    (directory / "_meta.yml").write_text(textwrap.dedent(data))


def write_md(path: Path, frontmatter: str = "", body: str = "# Hello") -> None:
    if frontmatter:
        content = f"---\n{textwrap.dedent(frontmatter)}---\n\n{body}"
    else:
        content = body
    path.write_text(content)


class TestCascadingInheritance:
    def test_root_meta_only(self, tmp_repo):
        write_meta(tmp_repo, """\
            title: Root Title
            product: Acme
            version: "1.0"
            outputs: [pdf]
        """)
        doc = tmp_repo / "doc.md"
        write_md(doc)
        config = load_config(doc, repo_root=tmp_repo)
        assert config["title"] == "Root Title"
        assert config["product"] == "Acme"
        assert config["version"] == "1.0"

    def test_child_overrides_parent(self, tmp_repo):
        write_meta(tmp_repo, "title: Parent\nproduct: Old\n")
        subdir = tmp_repo / "binder" / "renewals"
        subdir.mkdir(parents=True)
        write_meta(subdir, "product: NewProduct\n")
        doc = subdir / "letter.md"
        write_md(doc)
        config = load_config(doc, repo_root=tmp_repo)
        assert config["title"] == "Parent"   # inherited from root
        assert config["product"] == "NewProduct"  # overridden by subdir

    def test_frontmatter_overrides_meta(self, tmp_repo):
        write_meta(tmp_repo, "title: Meta Title\nversion: '1.0'\n")
        doc = tmp_repo / "doc.md"
        write_md(doc, frontmatter="title: Frontmatter Title\n")
        config = load_config(doc, repo_root=tmp_repo)
        assert config["title"] == "Frontmatter Title"
        assert config["version"] == "1.0"  # still from meta

    def test_deep_path_merges_all_layers(self, tmp_repo):
        write_meta(tmp_repo, "title: Root\nproduct: Base\n")
        mid = tmp_repo / "a"
        mid.mkdir()
        write_meta(mid, "product: Mid\n")
        deep = mid / "b"
        deep.mkdir()
        write_meta(deep, "version: '2.0'\n")
        doc = deep / "doc.md"
        write_md(doc)
        config = load_config(doc, repo_root=tmp_repo)
        assert config["title"] == "Root"
        assert config["product"] == "Mid"
        assert config["version"] == "2.0"

    def test_missing_meta_files_ignored(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        write_md(doc, frontmatter="title: Only Frontmatter\n")
        config = load_config(doc, repo_root=tmp_repo)
        assert config["title"] == "Only Frontmatter"

    def test_no_frontmatter_md(self, tmp_repo):
        write_meta(tmp_repo, "outputs: [pdf, docx]\n")
        doc = tmp_repo / "doc.md"
        write_md(doc)  # no frontmatter
        config = load_config(doc, repo_root=tmp_repo)
        assert config["outputs"] == ["pdf", "docx"]


class TestHelpers:
    def test_get_output_formats_list(self):
        assert get_output_formats({"outputs": ["pdf", "docx"]}) == ["pdf", "docx"]

    def test_get_output_formats_string(self):
        assert get_output_formats({"outputs": "pdf"}) == ["pdf"]

    def test_get_output_formats_default(self):
        assert get_output_formats({}) == ["pdf"]

    def test_should_sync_md_false_by_default(self):
        assert should_sync_md({}) is False

    def test_should_sync_md_true(self):
        assert should_sync_md({"include_md_in_share": True}) is True
