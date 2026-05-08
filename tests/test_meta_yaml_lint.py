"""Tests for the _meta.yml structural lint check.

Catches the common mistake of authoring a `_meta.yml` file with markdown-style
'---' frontmatter delimiters, which silently truncates everything after the
second '---' from the cascade.
"""

import pytest
from click.testing import CliRunner

from md_doc.cli import main
from md_doc.linter import lint_meta_file


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


# ── lint_meta_file (unit) ───────────────────────────────────────────────────


class TestLintMetaFile:
    def test_clean_meta_passes(self, tmp_repo):
        meta = tmp_repo / "_meta.yml"
        meta.write_text("product_name: acme\nversion: '1.0'\n", encoding="utf-8")
        assert lint_meta_file(meta) == []

    def test_empty_meta_passes(self, tmp_repo):
        meta = tmp_repo / "_meta.yml"
        meta.write_text("", encoding="utf-8")
        assert lint_meta_file(meta) == []

    def test_markdown_style_frontmatter_errors(self, tmp_repo):
        """Wrapping in '---' / '---' creates two YAML docs; second is ignored."""
        meta = tmp_repo / "_meta.yml"
        meta.write_text(
            "---\nproduct_name: acme\ninsurer_name: cgu\n---\n\n# Notes\n\nTODO\n",
            encoding="utf-8",
        )
        issues = lint_meta_file(meta)
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert "2 YAML documents" in issues[0].message

    def test_three_docs_errors(self, tmp_repo):
        meta = tmp_repo / "_meta.yml"
        meta.write_text("---\na: 1\n---\nb: 2\n---\nc: 3\n", encoding="utf-8")
        issues = lint_meta_file(meta)
        assert any("3 YAML documents" in i.message for i in issues)

    def test_non_mapping_top_level_errors(self, tmp_repo):
        meta = tmp_repo / "_meta.yml"
        # A YAML list instead of a mapping
        meta.write_text("- one\n- two\n", encoding="utf-8")
        issues = lint_meta_file(meta)
        assert any("must be a YAML mapping" in i.message for i in issues)

    def test_invalid_yaml_errors(self, tmp_repo):
        meta = tmp_repo / "_meta.yml"
        meta.write_text("title: [unclosed\n", encoding="utf-8")
        issues = lint_meta_file(meta)
        assert len(issues) == 1
        assert "Invalid YAML" in issues[0].message

    def test_leading_yaml_document_marker_alone_is_fine(self, tmp_repo):
        """A single leading '---' (YAML doc start) is valid, no warning."""
        meta = tmp_repo / "_meta.yml"
        meta.write_text("---\nproduct_name: acme\n", encoding="utf-8")
        assert lint_meta_file(meta) == []


# ── md-doc lint integration ─────────────────────────────────────────────────


class TestLintCliMeta:
    def test_md_doc_lint_catches_meta_yaml_with_frontmatter_wrapper(self, tmp_repo):
        """Reproduces the original bug: `_meta.yml` written like markdown
        frontmatter silently loses the half after the second '---'."""
        (tmp_repo / "_meta.yml").write_text(
            "---\nproduct_name: acme\ninsurer_name: cgu\n---\n\nTODO\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(tmp_repo)])
        # Errors abort with non-zero exit; the message should call out
        # the multi-document issue.
        assert result.exit_code == 1
        assert "_meta.yml" in result.output
        assert "YAML documents" in result.output

    def test_md_doc_lint_passes_clean_meta(self, tmp_repo):
        (tmp_repo / "_meta.yml").write_text(
            "product_name: acme\nversion: '1.0'\n", encoding="utf-8"
        )
        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(tmp_repo)])
        assert result.exit_code == 0
