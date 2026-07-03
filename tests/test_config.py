"""Tests for the cascading _meta.yml config system."""

import textwrap
from pathlib import Path

import pytest

from md_doc.config import (
    _find_repo_root,
    coerce_bool,
    is_boolish,
    load_config,
    get_output_formats,
    should_sync_md,
    load_merge_fields,
)


class TestCoerceBool:
    def test_real_bools(self):
        assert coerce_bool(True) is True
        assert coerce_bool(False) is False

    def test_truthy_strings(self):
        for v in ("true", "True", "TRUE", "yes", "on", "1", " t "):
            assert coerce_bool(v) is True, v

    def test_falsy_strings(self):
        # Critically: the string "false" must be False (plain bool() gets this wrong).
        for v in ("false", "False", "no", "off", "0", ""):
            assert coerce_bool(v) is False, v

    def test_none_uses_default(self):
        assert coerce_bool(None) is False
        assert coerce_bool(None, default=True) is True

    def test_is_boolish(self):
        assert is_boolish("false") and is_boolish(True) and is_boolish(0)
        assert not is_boolish("maybe") and not is_boolish(None)


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


class TestFindRepoRoot:
    def test_git_marker_wins(self, tmp_path):
        (tmp_path / ".git").mkdir()
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        assert _find_repo_root(deep) == tmp_path.resolve()

    def test_pyproject_marker(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        deep = tmp_path / "a"
        deep.mkdir()
        assert _find_repo_root(deep) == tmp_path.resolve()

    def test_meta_only_project_uses_topmost_meta(self, tmp_path):
        # No .git / pyproject: the highest _meta.yml is the cascade ceiling, so a
        # single-file build resolves the same root as a directory build (and
        # doesn't collapse to the document's own folder).
        root = tmp_path / "proposals"
        leaf = root / "clients" / "acme"
        leaf.mkdir(parents=True)
        (root / "_meta.yml").write_text("author: Acme\n")
        (leaf / "_meta.yml").write_text("client: Acme\n")
        assert _find_repo_root(leaf) == root.resolve()

    def test_no_markers_falls_back_to_start(self, tmp_path):
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        assert _find_repo_root(deep) == deep.resolve()

    def test_git_above_meta_still_wins(self, tmp_path):
        (tmp_path / ".git").mkdir()
        proj = tmp_path / "proposals"
        leaf = proj / "acme"
        leaf.mkdir(parents=True)
        (proj / "_meta.yml").write_text("author: Acme\n")
        # A VCS marker is the strongest signal even when a _meta.yml sits lower.
        assert _find_repo_root(leaf) == tmp_path.resolve()


class TestCascadingInheritance:
    def test_root_meta_only(self, tmp_repo):
        write_meta(
            tmp_repo,
            """\
            title: Root Title
            product: Acme
            version: "1.0"
            outputs: [pdf]
        """,
        )
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
        assert config["title"] == "Parent"  # inherited from root
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
