"""Tests for the document register generator."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from md_doc.register import generate


@pytest.fixture()
def built_tree(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "acme").mkdir()
    (tmp_path / "acme" / "proposal.pdf").write_bytes(b"%PDF-1.4 body")
    (tmp_path / "acme" / "proposal.docx").write_bytes(b"PK\x03\x04docx")
    # underscore-prefixed dir contents must be excluded
    (tmp_path / "_internal").mkdir()
    (tmp_path / "_internal" / "hidden.pdf").write_bytes(b"%PDF")
    return tmp_path


def test_generate_writes_json_md_csv(built_tree):
    json_path = built_tree / "register.json"
    records = generate(built_tree, json_path, write_md=True)

    assert json_path.exists()
    assert (built_tree / "register.md").exists()
    assert (built_tree / "register.csv").exists()

    data = json.loads(json_path.read_text())
    assert data == records
    names = {Path(r["path"]).name for r in records}
    assert "proposal.pdf" in names and "proposal.docx" in names


def test_generate_excludes_underscore_dirs(built_tree):
    records = generate(built_tree, built_tree / "register.json")
    assert all("_internal" not in r["path"] for r in records)
    assert all("hidden.pdf" not in Path(r["path"]).name for r in records)


def test_generate_under_underscore_root_still_includes(tmp_path):
    # The underscore filter must be relative to root, not the absolute path.
    root = tmp_path / "_work" / "out"
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "doc.pdf").write_bytes(b"%PDF")
    records = generate(root, root / "register.json")
    assert {Path(r["path"]).name for r in records} == {"doc.pdf"}


def test_csv_is_wellformed(built_tree):
    generate(built_tree, built_tree / "register.json")
    with open(built_tree / "register.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2  # proposal.pdf + proposal.docx
