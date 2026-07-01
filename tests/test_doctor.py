"""Tests for the `md-doc doctor` command."""

from __future__ import annotations

from click.testing import CliRunner

from md_doc.cli import main


def test_doctor_reports_sections_and_exits_zero_when_healthy():
    # In the test environment all core deps and system libs are present.
    result = CliRunner().invoke(main, ["doctor"], env={"MD_DOC_NO_COLOR": "1"})
    assert result.exit_code == 0, result.output
    assert "Core dependencies" in result.output
    assert "WeasyPrint system libraries" in result.output
    assert "Optional extras" in result.output
    assert "All required checks passed" in result.output


def test_doctor_fails_when_weasyprint_render_breaks(monkeypatch):
    import weasyprint

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def write_pdf(self, *a, **k):
            raise OSError("cannot load library 'libpango-1.0-0'")

    monkeypatch.setattr(weasyprint, "HTML", _Boom)
    result = CliRunner().invoke(main, ["doctor"], env={"MD_DOC_NO_COLOR": "1"})
    assert result.exit_code == 1
    assert "apt-get install" in result.output
    assert "libpango" in result.output
