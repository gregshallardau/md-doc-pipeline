"""Regression test for the cascade-truncation bug.

When a user runs ``md-doc lint workspace/a/b/c/d/`` (or ``build`` etc.) on
a subdirectory of the repo, the config / theme / template cascade should
still walk upwards from the doc dir to the actual git repo root — not
stop at the user's chosen subdirectory.

Bug: the lint and build commands previously called
``lint_directory(root, repo_root=root)``, which forced the cascade to stop
at the lint/build target. So ``_meta.yml`` files defined higher up the
tree (e.g. ``workspace/_meta.yml``) became invisible when linting deep
subdirectories, producing false "Undefined variable" warnings.
"""

import pytest
from click.testing import CliRunner

from md_doc.cli import main


@pytest.fixture()
def deep_repo(tmp_path):
    """Repo with var defined at root and a doc 4 levels deep that uses it."""
    (tmp_path / ".git").mkdir()

    (tmp_path / "_meta.yml").write_text("product_name: acme\n", encoding="utf-8")

    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "doc.md").write_text(
        "---\n"
        'output_filename: "{{ product_name | title }}-proposal"\n'
        "---\n\n"
        "# {{ product_name | title }} Proposal\n",
        encoding="utf-8",
    )

    return tmp_path


class TestCascadeFromSubdir:
    def test_lint_full_repo_passes(self, deep_repo):
        """Sanity check: linting the whole repo finds product_name."""
        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(deep_repo)])
        assert result.exit_code == 0
        assert "Undefined variable" not in result.output

    def test_lint_subdir_inherits_from_repo_root(self, deep_repo):
        """REGRESSION: linting just the deep subdir should still see the
        product_name defined in the repo root's _meta.yml."""
        target = deep_repo / "a" / "b" / "c" / "d"
        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(target)])
        assert result.exit_code == 0, f"failed: {result.output}"
        assert (
            "Undefined variable" not in result.output
        ), f"cascade should reach repo root but didn't: {result.output}"

    def test_lint_subdir_with_filter_inherits(self, deep_repo):
        """The variable is referenced via a filter (`| title`) — make sure
        the filter doesn't confuse the AST extraction."""
        target = deep_repo / "a" / "b" / "c" / "d"
        runner = CliRunner()
        result = runner.invoke(main, ["lint", "--render", str(target)])
        assert result.exit_code == 0, f"failed: {result.output}"
        assert "Undefined" not in result.output

    def test_build_subdir_inherits_from_repo_root(self, deep_repo):
        """REGRESSION: build with cascade-needing config from above."""
        pytest.importorskip("weasyprint")
        target = deep_repo / "a" / "b" / "c" / "d"
        runner = CliRunner()
        result = runner.invoke(main, ["build", str(target)])
        # Should not abort with "Undefined" lint error — cascade reaches root
        assert "Undefined" not in result.output, f"build cascade truncated: {result.output}"
