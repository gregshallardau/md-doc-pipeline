"""Tests for global logging flags and build timing output."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from md_doc.cli import main


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "doc.md").write_text(
        "---\ntitle: T\noutputs: [pdf]\n---\n# T\nBody.\n", encoding="utf-8"
    )
    return tmp_path


def test_build_reports_timing_and_count(repo):
    r = CliRunner().invoke(main, ["build", str(repo), "--force"], env={"MD_DOC_NO_COLOR": "1"})
    assert r.exit_code == 0, r.output
    assert "1 built" in r.output
    assert "s)" in r.output  # elapsed time suffix, e.g. "(1 built, 0.7s)"


def test_debug_flag_sets_logger_to_debug(repo):
    import logging

    r = CliRunner().invoke(
        main, ["--debug", "build", str(repo), "--force"], env={"MD_DOC_NO_COLOR": "1"}
    )
    assert r.exit_code == 0, r.output
    assert logging.getLogger("md_doc").level == logging.DEBUG


def test_quiet_flag_sets_logger_to_error(repo):
    import logging

    r = CliRunner().invoke(
        main, ["--quiet", "build", str(repo), "--force"], env={"MD_DOC_NO_COLOR": "1"}
    )
    assert r.exit_code == 0, r.output
    assert logging.getLogger("md_doc").level == logging.ERROR
