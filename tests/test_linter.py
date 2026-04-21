"""Tests for the Markdown linter (md-doc lint)."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from md_doc.linter import lint_file
from md_doc.cli import main


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def make_doc(
    path: Path, frontmatter: str = "title: Test\noutputs: [pdf]", body: str = "# Hello\n"
) -> None:
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


class TestFrontmatterValidity:
    def test_invalid_yaml_reports_error(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        doc.write_text("---\ntitle: [unclosed bracket\n---\n\n# Hello\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        errors = [i for i in issues if i.severity == "error"]
        assert errors
        assert any("frontmatter" in i.message.lower() for i in errors)

    def test_valid_frontmatter_no_frontmatter_error(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc)
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any("frontmatter" in i.message.lower() for i in issues)

    def test_no_frontmatter_no_issue(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        doc.write_text("# Just a heading\n\nSome body text.\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any(i.severity == "error" for i in issues)


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------


class TestOutputFormats:
    def test_unknown_format_reports_error(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc, frontmatter="title: Test\noutputs: [xlsx]")
        issues = lint_file(doc, repo_root=tmp_repo)
        errors = [i for i in issues if i.severity == "error"]
        assert errors
        assert any("xlsx" in i.message for i in errors)

    def test_mixed_valid_and_invalid_reports_only_invalid(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc, frontmatter="title: Test\noutputs: [pdf, xlsx]")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert any("xlsx" in i.message for i in issues)
        assert not any("pdf" in i.message for i in issues)

    def test_all_valid_formats_no_issue(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc, frontmatter="title: Test\noutputs: [pdf, docx, dotx]")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any(
            "pdf" in i.message or "docx" in i.message or "dotx" in i.message for i in issues
        )

    def test_outputs_inherited_from_meta_not_re_checked(self, tmp_repo):
        """outputs in _meta.yml is not double-reported if doc has no outputs key."""
        (tmp_repo / "_meta.yml").write_text("outputs: [pdf]\n")
        doc = tmp_repo / "doc.md"
        doc.write_text("---\ntitle: Test\n---\n\n# Hello\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any(i.severity == "error" for i in issues)


# ---------------------------------------------------------------------------
# Jinja2 template body
# ---------------------------------------------------------------------------


class TestJinja2Syntax:
    def test_broken_jinja2_syntax_reports_error(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="{{ unclosed\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert any(i.severity == "error" for i in issues)

    def test_valid_jinja2_no_syntax_error(self, tmp_repo):
        (tmp_repo / "_meta.yml").write_text("product: Widget\n")
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="The {{ product }} is ready.\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any(i.severity == "error" for i in issues)


# ---------------------------------------------------------------------------
# Jinja2 variable references  {{ var }}
# ---------------------------------------------------------------------------


class TestVariableReferences:
    def test_undefined_variable_reports_warning(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="Hello {{ ghost_var }}.\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        warnings = [i for i in issues if i.severity == "warning"]
        assert warnings
        assert any("ghost_var" in i.message for i in warnings)

    def test_variable_defined_in_meta_no_warning(self, tmp_repo):
        (tmp_repo / "_meta.yml").write_text("author: Blueshift Labs\n")
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="By {{ author }}.\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any("author" in i.message for i in issues)

    def test_variable_defined_in_frontmatter_no_warning(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(
            doc,
            frontmatter="title: Test\noutputs: [pdf]\nproduct: Widget",
            body="The {{ product }}.\n",
        )
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any("product" in i.message for i in issues)

    def test_loop_variable_not_flagged(self, tmp_repo):
        (tmp_repo / "_meta.yml").write_text("items: [a, b, c]\n")
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="{% for item in items %}- {{ item }}\n{% endfor %}\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any("item" in i.message for i in issues)

    def test_multiple_undefined_vars_all_reported(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="{{ alpha }} and {{ beta }}.\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        messages = " ".join(i.message for i in issues)
        assert "alpha" in messages
        assert "beta" in messages


# ---------------------------------------------------------------------------
# Template includes  {% include "path" %}
# ---------------------------------------------------------------------------


class TestTemplateIncludes:
    def test_missing_include_reports_error(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc, body='{% include "templates/nonexistent.md" %}\n')
        issues = lint_file(doc, repo_root=tmp_repo)
        errors = [i for i in issues if i.severity == "error"]
        assert errors
        assert any("nonexistent.md" in i.message for i in errors)

    def test_existing_include_no_error(self, tmp_repo):
        tmpl_dir = tmp_repo / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "header.md").write_text("# Header\n")
        doc = tmp_repo / "doc.md"
        make_doc(doc, body='{% include "templates/header.md" %}\n')
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any("header.md" in i.message for i in issues)

    def test_include_in_ancestor_templates_dir_no_error(self, tmp_repo):
        # Template at root templates/ should be found from a sub-document
        tmpl_dir = tmp_repo / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "footer.md").write_text("Footer\n")
        sub = tmp_repo / "projects"
        sub.mkdir()
        doc = sub / "report.md"
        make_doc(doc, body='{% include "templates/footer.md" %}\n')
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any("footer.md" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Merge field references  [[field]]
# ---------------------------------------------------------------------------


class TestMergeFieldReferences:
    def test_undefined_field_reports_warning_when_schema_exists(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text("contact_name: Full name\n")
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="Dear [[ghost_field]],\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        warnings = [i for i in issues if i.severity == "warning"]
        assert warnings
        assert any("ghost_field" in i.message for i in warnings)

    def test_defined_field_no_warning(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text("contact_name: Full name\n")
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="Dear [[contact_name]],\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any("contact_name" in i.message for i in issues)

    def test_no_schema_files_fields_not_checked(self, tmp_repo):
        """If no _merge_fields.yml exists anywhere, [[fields]] aren't validated."""
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="Dear [[anyone]],\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any("anyone" in i.message for i in issues)

    def test_field_defined_in_ancestor_schema_no_warning(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text("company: Company name\n")
        sub = tmp_repo / "clients"
        sub.mkdir()
        (sub / "_merge_fields.yml").write_text("account_manager: Assigned manager\n")
        doc = sub / "letter.md"
        make_doc(doc, body="[[company]] — [[account_manager]]\n")
        issues = lint_file(doc, repo_root=tmp_repo)
        assert not any(
            i.message for i in issues if "company" in i.message or "account_manager" in i.message
        )


# ---------------------------------------------------------------------------
# Clean file — no issues
# ---------------------------------------------------------------------------


class TestCleanFile:
    def test_fully_valid_document_returns_no_issues(self, tmp_repo):
        (tmp_repo / "_meta.yml").write_text("author: Blueshift Labs\noutputs: [dotx]\n")
        (tmp_repo / "_merge_fields.yml").write_text("contact_name: Full name\n")
        tmpl_dir = tmp_repo / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "header.md").write_text("# Header\n")
        doc = tmp_repo / "proposal.md"
        make_doc(
            doc,
            frontmatter="title: Test Proposal\noutputs: [dotx]",
            body='{% include "templates/header.md" %}\n\nDear [[contact_name]], from {{ author }}.\n',
        )
        issues = lint_file(doc, repo_root=tmp_repo)
        assert issues == []


# ---------------------------------------------------------------------------
# CLI command: md-doc lint
# ---------------------------------------------------------------------------


class TestLintCommand:
    def test_clean_workspace_exits_zero(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc)
        result = CliRunner().invoke(main, ["lint", str(tmp_repo)])
        assert result.exit_code == 0

    def test_errors_cause_nonzero_exit(self, tmp_repo):
        doc = tmp_repo / "doc.md"
        make_doc(doc, frontmatter="title: Test\noutputs: [xlsx]")
        result = CliRunner().invoke(main, ["lint", str(tmp_repo)])
        assert result.exit_code != 0

    def test_output_contains_filename(self, tmp_repo):
        doc = tmp_repo / "my-proposal.md"
        make_doc(doc, frontmatter="title: Test\noutputs: [xlsx]")
        result = CliRunner().invoke(main, ["lint", str(tmp_repo)])
        assert "my-proposal.md" in result.output

    def test_no_documents_exits_zero(self, tmp_repo):
        result = CliRunner().invoke(main, ["lint", str(tmp_repo)])
        assert result.exit_code == 0

    def test_warnings_only_exits_zero(self, tmp_repo):
        """Warnings alone shouldn't fail the lint — only errors do."""
        doc = tmp_repo / "doc.md"
        make_doc(doc, body="Hello {{ undefined_var }}.\n")
        result = CliRunner().invoke(main, ["lint", str(tmp_repo)])
        assert result.exit_code == 0

    def test_defaults_to_current_directory(self, tmp_repo, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        doc = tmp_repo / "doc.md"
        make_doc(doc)
        result = CliRunner().invoke(main, ["lint"])
        assert result.exit_code == 0
