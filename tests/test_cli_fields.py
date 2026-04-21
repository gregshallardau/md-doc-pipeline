"""Tests for `md-doc fields` CLI command."""

import pytest
from click.testing import CliRunner

from md_doc.cli import main


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


class TestFieldsCommand:
    def test_lists_fields_from_single_file(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text(
            "contact_name: Full name of the primary contact\ncompany: Client company name\n"
        )
        result = CliRunner().invoke(main, ["fields", str(tmp_repo)])
        assert result.exit_code == 0
        assert "contact_name" in result.output
        assert "Full name of the primary contact" in result.output
        assert "company" in result.output

    def test_shows_fields_from_all_cascade_levels(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text("contact_name: Root contact\n")
        sub = tmp_repo / "clients" / "acme"
        sub.mkdir(parents=True)
        (sub / "_merge_fields.yml").write_text("account_manager: Assigned manager\n")
        result = CliRunner().invoke(main, ["fields", str(sub)])
        assert result.exit_code == 0
        assert "contact_name" in result.output
        assert "account_manager" in result.output

    def test_groups_by_source_level(self, tmp_repo):
        (tmp_repo / "_merge_fields.yml").write_text("contact_name: Root contact\n")
        sub = tmp_repo / "projects"
        sub.mkdir()
        (sub / "_merge_fields.yml").write_text("delivery_date: Agreed delivery date\n")
        result = CliRunner().invoke(main, ["fields", str(sub)])
        assert result.exit_code == 0
        # Source paths should appear as section headers
        assert "_merge_fields.yml" in result.output

    def test_no_fields_files_shows_message(self, tmp_repo):
        result = CliRunner().invoke(main, ["fields", str(tmp_repo)])
        assert result.exit_code == 0
        assert "No merge fields" in result.output

    def test_defaults_to_current_directory(self, tmp_repo, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        (tmp_repo / "_merge_fields.yml").write_text("sign_off: Closing name\n")
        result = CliRunner().invoke(main, ["fields"])
        assert result.exit_code == 0
        assert "sign_off" in result.output
