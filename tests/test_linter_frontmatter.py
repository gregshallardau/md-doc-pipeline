"""Tests for the linter's frontmatter-jinja and --render features."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from md_doc.cli import main
from md_doc.linter import lint_file


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def write_meta(repo: Path, content: str) -> None:
    (repo / "_meta.yml").write_text(content, encoding="utf-8")


# ── Frontmatter Jinja2 variable detection ───────────────────────────────────


class TestFrontmatterJinjaVars:
    def test_undefined_var_in_output_filename_warns(self, tmp_repo):
        """The classic case: output_filename uses {{ product_name }} but it's not in the cascade."""
        write_meta(tmp_repo, "title: Doc\nauthor: Acme\n")  # note: no product_name
        doc = tmp_repo / "doc.md"
        doc.write_text(
            "---\noutput_filename: '{{ product_name }}-proposal'\n---\n\n# Hello\n",
            encoding="utf-8",
        )

        issues = lint_file(doc, repo_root=tmp_repo)
        warnings = [i for i in issues if i.severity == "warning"]

        msgs = [w.message for w in warnings]
        assert any(
            "product_name" in m and "output_filename" in m for m in msgs
        ), f"expected product_name/output_filename warning, got: {msgs}"

    def test_defined_var_in_frontmatter_no_warning(self, tmp_repo):
        write_meta(tmp_repo, "title: Doc\nproduct: Nova\n")
        doc = tmp_repo / "doc.md"
        doc.write_text(
            "---\noutput_filename: '{{ product }}-proposal'\n---\n\n# Hello\n",
            encoding="utf-8",
        )

        issues = lint_file(doc, repo_root=tmp_repo)
        msgs = [i.message for i in issues]
        assert not any(
            "product" in m and "output_filename" in m for m in msgs
        ), f"unexpected warning for defined var: {msgs}"

    def test_nested_dict_value_scanned(self, tmp_repo):
        """Nested config like sync_config.path should be walked."""
        write_meta(tmp_repo, "title: Doc\n")
        doc = tmp_repo / "doc.md"
        doc.write_text(
            "---\nsync_config:\n  path: '/tmp/{{ region_code }}/'\n---\n\n# Hello\n",
            encoding="utf-8",
        )

        issues = lint_file(doc, repo_root=tmp_repo)
        msgs = [i.message for i in issues]
        assert any(
            "region_code" in m and "sync_config.path" in m for m in msgs
        ), f"expected region_code/sync_config.path warning, got: {msgs}"

    def test_list_item_value_scanned(self, tmp_repo):
        """Vars inside list-of-strings should also be detected."""
        write_meta(tmp_repo, "title: Doc\n")
        doc = tmp_repo / "doc.md"
        doc.write_text(
            "---\ntags:\n  - '{{ unknown_tag }}'\n  - cheatsheet\n---\n\n# Hello\n",
            encoding="utf-8",
        )

        issues = lint_file(doc, repo_root=tmp_repo)
        msgs = [i.message for i in issues]
        assert any(
            "unknown_tag" in m and "tags[0]" in m for m in msgs
        ), f"expected unknown_tag/tags[0] warning, got: {msgs}"

    def test_non_string_values_ignored(self, tmp_repo):
        """Booleans, numbers, etc. shouldn't be scanned."""
        write_meta(tmp_repo, "title: Doc\n")
        doc = tmp_repo / "doc.md"
        doc.write_text(
            "---\ncover_page: true\nseats: 25\n---\n\n# Hello\n",
            encoding="utf-8",
        )

        issues = lint_file(doc, repo_root=tmp_repo)
        # No frontmatter-related warnings expected
        assert not any(
            "frontmatter value" in i.message for i in issues
        ), f"unexpected frontmatter warning on non-string values: {[i.message for i in issues]}"


# ── md-doc lint --render ────────────────────────────────────────────────────


class TestLintRenderFlag:
    def test_render_flag_catches_undefined_in_body(self, tmp_repo):
        """Strict render of the body raises UndefinedError on missing vars."""
        write_meta(tmp_repo, "title: Doc\n")
        doc = tmp_repo / "doc.md"
        doc.write_text(
            "---\ntitle: Test\n---\n\n# Hello {{ never_defined }}\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["lint", "--render", str(tmp_repo)])

        assert result.exit_code == 1, f"expected non-zero exit, got: {result.output}"
        assert "never_defined" in result.output

    def test_no_render_flag_no_strict_check(self, tmp_repo):
        """Without --render, the same doc only emits a warning (exit 0)."""
        write_meta(tmp_repo, "title: Doc\n")
        doc = tmp_repo / "doc.md"
        doc.write_text(
            "---\ntitle: Test\n---\n\n# Hello {{ never_defined }}\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(tmp_repo)])

        # Warning, not error — exit 0
        assert result.exit_code == 0, f"expected zero exit, got: {result.output}"
        assert "never_defined" in result.output

    def test_render_passes_when_all_vars_defined(self, tmp_repo):
        write_meta(tmp_repo, "title: Doc\nproduct: Nova\n")
        doc = tmp_repo / "doc.md"
        doc.write_text(
            "---\ntitle: Test\n---\n\n# {{ title }} for {{ product }}\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["lint", "--render", str(tmp_repo)])

        assert result.exit_code == 0, f"expected clean exit, got: {result.output}"
