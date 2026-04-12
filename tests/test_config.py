"""Tests for the cascading _meta.yml config system."""

import textwrap
from pathlib import Path

import pytest

from md_doc.config import load_config, get_output_formats, should_sync_md, load_merge_fields, load_merge_fields


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


class TestMergeFields:
    def test_single_file_at_root(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text(
            "contact_name: Full name of the primary contact\ncompany: Client company name\n"
        )
        doc = tmp_repo / "doc.md"
        doc.write_text("# Hello")
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields == {
            "contact_name": "Full name of the primary contact",
            "company": "Client company name",
        }

    def test_cascade_additive(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text(
            "contact_name: Full name\ncompany: Company name\n"
        )
        sub = tmp_repo / "clients" / "acme"
        sub.mkdir(parents=True)
        (sub / "_merge_fields.yml").write_text("account_manager: Assigned manager\n")
        doc = sub / "proposal.md"
        doc.write_text("# Hello")
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields == {
            "contact_name": "Full name",
            "company": "Company name",
            "account_manager": "Assigned manager",
        }

    def test_deeper_overrides_shallower_for_same_key(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text("sign_off: Root signatory\n")
        sub = tmp_repo / "team"
        sub.mkdir()
        (sub / "_merge_fields.yml").write_text("sign_off: Team lead name\n")
        doc = sub / "letter.md"
        doc.write_text("# Hello")
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields["sign_off"] == "Team lead name"

    def test_no_merge_fields_files_returns_empty(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        doc.write_text("# Hello")
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields == {}

    def test_missing_file_at_level_is_skipped(self, tmp_repo):
        sub = tmp_repo / "level1" / "level2"
        sub.mkdir(parents=True)
        (sub / "_merge_fields.yml").write_text("item: A line item\n")
        doc = sub / "invoice.md"
        doc.write_text("# Hello")
        # no _merge_fields.yml at root or level1 — only level2 has one
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields == {"item": "A line item"}


class TestMergeFields:
    def test_single_file_at_root(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text(
            "contact_name: Full name of the primary contact\ncompany: Client company name\n"
        )
        doc = tmp_repo / "doc.md"
        doc.write_text("# Hello")
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields == {
            "contact_name": "Full name of the primary contact",
            "company": "Client company name",
        }

    def test_cascade_additive(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text(
            "contact_name: Full name\ncompany: Company name\n"
        )
        sub = tmp_repo / "clients" / "acme"
        sub.mkdir(parents=True)
        (sub / "_merge_fields.yml").write_text("account_manager: Assigned manager\n")
        doc = sub / "proposal.md"
        doc.write_text("# Hello")
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields == {
            "contact_name": "Full name",
            "company": "Company name",
            "account_manager": "Assigned manager",
        }

    def test_deeper_overrides_shallower_for_same_key(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text("sign_off: Root signatory\n")
        sub = tmp_repo / "team"
        sub.mkdir()
        (sub / "_merge_fields.yml").write_text("sign_off: Team lead name\n")
        doc = sub / "letter.md"
        doc.write_text("# Hello")
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields["sign_off"] == "Team lead name"

    def test_no_merge_fields_files_returns_empty(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        doc.write_text("# Hello")
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields == {}

    def test_missing_file_at_level_is_skipped(self, tmp_repo):
        sub = tmp_repo / "level1" / "level2"
        sub.mkdir(parents=True)
        (sub / "_merge_fields.yml").write_text("item: A line item\n")
        doc = sub / "invoice.md"
        doc.write_text("# Hello")
        fields = load_merge_fields(doc, repo_root=tmp_repo)
        assert fields == {"item": "A line item"}


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
