"""Tests for `md-doc new folder` and `md-doc new doc` CLI commands."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from md_doc.cli import main


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


class TestNewFolder:
    def test_creates_directory_and_meta(self, tmp_repo):
        result = CliRunner().invoke(
            main,
            ["new", "folder", "clients/acme", "--in", str(tmp_repo)],
        )
        assert result.exit_code == 0
        target = tmp_repo / "clients" / "acme"
        assert target.is_dir()
        assert (target / "_meta.yml").exists()

    def test_meta_contains_only_new_keys(self, tmp_repo):
        # Root already has author and outputs — new folder should not repeat them
        (tmp_repo / "_meta.yml").write_text("author: Blueshift Labs\noutputs: [pdf]\n")
        CliRunner().invoke(
            main,
            ["new", "folder", "clients/acme", "--in", str(tmp_repo)],
            input="Acme Corp\n",  # answer the client prompt
        )
        meta = (tmp_repo / "clients" / "acme" / "_meta.yml").read_text()
        assert "author" not in meta  # inherited — don't duplicate
        assert "outputs" not in meta  # inherited — don't duplicate

    def test_fails_if_directory_exists(self, tmp_repo):
        existing = tmp_repo / "existing"
        existing.mkdir()
        result = CliRunner().invoke(
            main,
            ["new", "folder", "existing", "--in", str(tmp_repo)],
        )
        assert result.exit_code != 0
        assert (
            "already exists" in result.output.lower()
            or "already exists"
            in (result.output + (result.exception and str(result.exception) or "")).lower()
        )

    def test_nested_path_creates_intermediate_dirs(self, tmp_repo):
        result = CliRunner().invoke(
            main,
            ["new", "folder", "a/b/c", "--in", str(tmp_repo)],
        )
        assert result.exit_code == 0
        assert (tmp_repo / "a" / "b" / "c").is_dir()
        assert (tmp_repo / "a" / "b" / "c" / "_meta.yml").exists()


class TestNewDoc:
    def test_creates_md_file(self, tmp_repo):
        result = CliRunner().invoke(
            main,
            ["new", "doc", "proposal", "--in", str(tmp_repo)],
            input="dotx\nno\n\n",  # output format, cover page, empty=done
        )
        assert result.exit_code == 0
        assert (tmp_repo / "proposal.md").exists()

    def test_created_file_has_frontmatter(self, tmp_repo):
        CliRunner().invoke(
            main,
            ["new", "doc", "report", "--in", str(tmp_repo)],
            input="pdf\nyes\n\n",
        )
        content = (tmp_repo / "report.md").read_text()
        assert content.startswith("---\n")
        assert "title:" in content
        assert "outputs:" in content

    def test_fails_if_file_exists(self, tmp_repo):
        (tmp_repo / "existing.md").write_text("# Hello")
        result = CliRunner().invoke(
            main,
            ["new", "doc", "existing", "--in", str(tmp_repo)],
            input="pdf\nyes\n\n",
        )
        assert result.exit_code != 0

    def test_name_without_extension(self, tmp_repo):
        """Passing 'proposal' creates proposal.md, not proposal.md.md."""
        CliRunner().invoke(
            main,
            ["new", "doc", "proposal", "--in", str(tmp_repo)],
            input="pdf\nyes\n\n",
        )
        assert (tmp_repo / "proposal.md").exists()
        assert not (tmp_repo / "proposal.md.md").exists()


def test_pdf_forms_output_has_form_suffix(tmp_path):
    """Build loop should use -form.pdf extension when pdf_forms: true."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "_pdf-theme.css").write_text("body {}")
    doc = tmp_path / "onboarding.md"
    doc.write_text("---\npdf_forms: true\n---\n\n# Onboarding\n")

    captured_paths: list[Path] = []

    def fake_write_pdf(out_path, **kwargs):
        captured_paths.append(Path(out_path))
        Path(out_path).write_bytes(b"%PDF-fake")

    mock_html_inst = MagicMock()
    mock_html_inst.write_pdf.side_effect = fake_write_pdf

    with patch("md_doc.builders.pdf.weasyprint") as mock_wp:
        mock_wp.HTML.return_value = mock_html_inst
        runner = CliRunner()
        result = runner.invoke(main, ["build", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert any(
        p.name == "onboarding-form.pdf" for p in captured_paths
    ), f"Expected onboarding-form.pdf, got: {[p.name for p in captured_paths]}"
