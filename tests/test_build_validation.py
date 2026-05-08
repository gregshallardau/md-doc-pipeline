"""Tests for build-time validation: strict filename rendering + lint pre-flight."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from md_doc.cli import _apply_filename_override, main


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def write_meta(repo: Path, content: str) -> None:
    (repo / "_meta.yml").write_text(content, encoding="utf-8")


def write_doc(repo: Path, name: str, frontmatter: str = "title: Test", body: str = "# Hello\n"):
    doc = repo / name
    doc.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return doc


# ── _apply_filename_override: strict undefined ──────────────────────────────


class TestStrictFilenameOverride:
    def test_undefined_var_raises(self, tmp_path):
        from jinja2 import UndefinedError

        out_path = tmp_path / "doc.pdf"
        config = {"output_filename": "{{ product_name }}-proposal"}

        with pytest.raises(UndefinedError):
            _apply_filename_override(out_path, config, "pdf")

    def test_defined_var_renders(self, tmp_path):
        out_path = tmp_path / "doc.pdf"
        config = {"output_filename": "{{ product }}-proposal", "product": "Nova"}

        result = _apply_filename_override(out_path, config, "pdf")
        assert result.name == "Nova-proposal.pdf"

    def test_no_override_unchanged(self, tmp_path):
        out_path = tmp_path / "doc.pdf"
        result = _apply_filename_override(out_path, {}, "pdf")
        assert result == out_path


# ── md-doc build pre-flight lint ────────────────────────────────────────────


class TestBuildPreflightLint:
    def test_build_aborts_on_lint_error(self, tmp_repo, monkeypatch):
        """An unresolvable {% include %} is a lint error → build aborts."""
        write_meta(tmp_repo, "title: Doc\n")
        write_doc(
            tmp_repo,
            "doc.md",
            frontmatter="title: Doc",
            body='{% include "missing-fragment.md" %}\n',
        )

        runner = CliRunner()
        result = runner.invoke(main, ["build", str(tmp_repo)])

        assert result.exit_code == 1, f"expected abort, got: {result.output}"
        assert "Lint errors" in result.output
        assert "Include not found" in result.output
        # Did not proceed to actual build:
        assert "Build complete" not in result.output

    def test_build_warnings_dont_abort(self, tmp_repo):
        """Undefined frontmatter var is a *warning* — build should still attempt."""
        pytest.importorskip("weasyprint")

        write_meta(tmp_repo, "title: Doc\n")
        write_doc(
            tmp_repo,
            "doc.md",
            frontmatter="title: Test\noutputs: [pdf]",
            body="# Hello\n",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["build", str(tmp_repo)])

        # No errors, build proceeds
        assert "Lint errors" not in result.output
        assert "Build complete" in result.output

    def test_no_lint_flag_skips_preflight(self, tmp_repo):
        """--no-lint bypasses the pre-flight check entirely."""
        pytest.importorskip("weasyprint")

        write_meta(tmp_repo, "title: Doc\n")
        write_doc(
            tmp_repo,
            "doc.md",
            frontmatter="title: Test",
            body='{% include "missing.md" %}\n',
        )

        runner = CliRunner()
        result = runner.invoke(main, ["build", str(tmp_repo), "--no-lint"])

        # The pre-flight is skipped, so 'Lint errors' should NOT appear.
        # Build itself will still fail downstream on the missing include,
        # but via the per-doc render error path, not the pre-flight gate.
        assert "Lint errors" not in result.output


# ── md-doc build with strict filename override ─────────────────────────────


class TestBuildStrictFilename:
    def test_undefined_filename_var_caught_at_build(self, tmp_repo):
        """Undefined var in output_filename surfaces as per-doc build error,
        not a silently-produced empty filename."""
        pytest.importorskip("weasyprint")

        write_meta(tmp_repo, "title: Doc\n")
        write_doc(
            tmp_repo,
            "doc.md",
            frontmatter='title: Test\noutput_filename: "{{ missing_var }}-x"',
            body="# Hello\n",
        )

        runner = CliRunner()
        # Use --no-lint so the lint pre-flight (which would also catch this)
        # doesn't intercept — we want to verify the build-time strict rendering.
        result = runner.invoke(main, ["build", str(tmp_repo), "--no-lint"])

        # Build attempted but failed on this doc
        assert "output_filename render failed" in result.output
        assert result.exit_code == 1
        # No silently-named '-x.pdf' file should exist
        assert not list(tmp_repo.glob("*-x.pdf"))
