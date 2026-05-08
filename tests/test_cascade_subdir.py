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

    (tmp_path / "_meta.yml").write_text("product_name: affinity\n", encoding="utf-8")

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


@pytest.fixture()
def very_deep_repo(tmp_path):
    """Stress test: 10 levels deep, with intermediate ``_meta.yml`` files
    at every layer that DON'T re-declare the variable.

    Cascade path:
        tmp_path/_meta.yml  ←  product_name: affinity
        tmp_path/L01/_meta.yml
        tmp_path/L01/L02/_meta.yml
        ...
        tmp_path/L01/L02/.../L10/doc.md
    """
    (tmp_path / ".git").mkdir()
    (tmp_path / "_meta.yml").write_text(
        "product_name: affinity\nauthor: Acme Co\n", encoding="utf-8"
    )

    current = tmp_path
    for i in range(1, 11):
        current = current / f"L{i:02d}"
        current.mkdir()
        # An intermediate _meta.yml at every level — none re-declare product_name
        (current / "_meta.yml").write_text(f"layer{i}_key: value{i}\n", encoding="utf-8")

    (current / "doc.md").write_text(
        "---\n"
        'output_filename: "{{ product_name | title }}-deep"\n'
        "---\n\n"
        "# {{ product_name | title }} (10 levels deep)\n\n"
        "Author: {{ author }}\n",
        encoding="utf-8",
    )

    return tmp_path, current


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


class TestCascadeTenLevelsDeep:
    """Stress test: cascade walking 10 levels of intermediate _meta.yml files."""

    def test_lint_at_root_sees_var_10_deep(self, very_deep_repo):
        repo, _doc_dir = very_deep_repo
        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(repo)])
        assert result.exit_code == 0, f"failed: {result.output}"
        assert "Undefined" not in result.output

    def test_lint_at_doc_dir_sees_var_10_levels_above(self, very_deep_repo):
        """The fix: lint the deepest dir directly — should still inherit
        product_name and author from the root _meta.yml."""
        _repo, doc_dir = very_deep_repo
        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(doc_dir)])
        assert result.exit_code == 0, f"failed: {result.output}"
        assert (
            "Undefined" not in result.output
        ), f"cascade should reach 10 levels up: {result.output}"

    def test_lint_at_intermediate_level_sees_var_above(self, very_deep_repo):
        """Lint at level 5 — should still see var defined at level 0 (root)."""
        repo, _doc_dir = very_deep_repo
        mid = repo / "L01" / "L02" / "L03" / "L04" / "L05"
        runner = CliRunner()
        result = runner.invoke(main, ["lint", str(mid)])
        assert result.exit_code == 0, f"failed: {result.output}"
        assert "Undefined" not in result.output

    def test_render_strict_at_doc_dir_10_deep(self, very_deep_repo):
        """--render does a full strict Jinja2 render. With 10 levels of
        intermediate _meta.yml between root and doc, all vars must still
        resolve."""
        _repo, doc_dir = very_deep_repo
        runner = CliRunner()
        result = runner.invoke(main, ["lint", "--render", str(doc_dir)])
        assert result.exit_code == 0, f"failed: {result.output}"
        assert "Undefined" not in result.output
