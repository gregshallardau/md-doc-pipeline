"""Tests for Phase 1 export staging: unique temp dir, cleaned up after the run."""

from __future__ import annotations

import glob
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from md_doc.cli import main


@pytest.fixture()
def vault(tmp_path):
    (tmp_path / ".git").mkdir()
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "keep.md").write_text(
        "---\nexport: true\ntitle: Keep\n---\n# Keep\nBody.\n", encoding="utf-8"
    )
    (notes / "skip.md").write_text("---\ntitle: Skip\n---\n# Skip\n", encoding="utf-8")
    return tmp_path


def test_export_produces_output_and_cleans_staging(vault):
    before = set(glob.glob(str(Path(tempfile.gettempdir()) / "md-doc-export-*")))

    result = CliRunner().invoke(main, ["export", str(vault)])
    assert result.exit_code == 0, result.output

    # Only the export:true note was built, into the default Exports/ dir.
    assert (vault / "Exports" / "notes" / "keep.pdf").exists()
    assert not list((vault / "Exports").rglob("skip*"))

    # No staging temp dir is left behind (unique dir + cleanup).
    after = set(glob.glob(str(Path(tempfile.gettempdir()) / "md-doc-export-*")))
    assert after == before


def test_export_staging_removed_even_on_no_matches(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "note.md").write_text("---\ntitle: X\n---\n# X\n", encoding="utf-8")
    before = set(glob.glob(str(Path(tempfile.gettempdir()) / "md-doc-export-*")))

    result = CliRunner().invoke(main, ["export", str(tmp_path)])
    assert result.exit_code == 0

    after = set(glob.glob(str(Path(tempfile.gettempdir()) / "md-doc-export-*")))
    assert after == before
