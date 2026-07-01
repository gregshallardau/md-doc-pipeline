"""Tests for Phase 1 incremental build: skip up-to-date outputs; --force rebuilds."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from md_doc.cli import main, _newest_dep_mtime


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def _write_doc(tmp_repo: Path, name: str = "doc.md") -> Path:
    p = tmp_repo / name
    p.write_text("---\ntitle: T\noutputs: [pdf]\n---\n# T\nBody.\n", encoding="utf-8")
    return p


def _build(tmp_repo: Path, *extra: str):
    return CliRunner().invoke(main, ["build", str(tmp_repo), *extra])


def test_second_build_skips_unchanged(tmp_repo):
    _write_doc(tmp_repo)
    r1 = _build(tmp_repo)
    assert r1.exit_code == 0, r1.output
    assert "wrote" in r1.output

    r2 = _build(tmp_repo)
    assert r2.exit_code == 0, r2.output
    assert "up to date" in r2.output
    assert "wrote" not in r2.output


def test_touching_source_triggers_rebuild(tmp_repo):
    doc = _write_doc(tmp_repo)
    _build(tmp_repo)
    # Make the source newer than the output.
    future = time.time() + 10
    os.utime(doc, (future, future))

    r = _build(tmp_repo)
    assert "wrote" in r.output
    assert "up to date" not in r.output


def test_force_rebuilds_even_when_fresh(tmp_repo):
    _write_doc(tmp_repo)
    _build(tmp_repo)
    r = _build(tmp_repo, "--force")
    assert "wrote" in r.output
    assert "up to date" not in r.output


def test_editing_meta_yml_triggers_rebuild(tmp_repo):
    _write_doc(tmp_repo)
    _build(tmp_repo)
    meta = tmp_repo / "_meta.yml"
    meta.write_text("author: New Author\n", encoding="utf-8")
    future = time.time() + 10
    os.utime(meta, (future, future))

    r = _build(tmp_repo)
    assert "wrote" in r.output


def test_newest_dep_mtime_includes_meta_and_templates(tmp_repo):
    doc = _write_doc(tmp_repo)
    (tmp_repo / "_meta.yml").write_text("author: A\n", encoding="utf-8")
    tdir = tmp_repo / "templates"
    tdir.mkdir()
    frag = tdir / "frag.md"
    frag.write_text("x", encoding="utf-8")
    future = time.time() + 100
    os.utime(frag, (future, future))

    # The template fragment (newest) dominates the dependency mtime.
    assert _newest_dep_mtime(doc, tmp_repo) >= future
