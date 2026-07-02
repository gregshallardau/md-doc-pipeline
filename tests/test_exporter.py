"""Tests for the vault export module (find/stage/collect)."""

from __future__ import annotations


import pytest

from md_doc.exporter import find_exportable, stage_files, collect_outputs


@pytest.fixture()
def vault(tmp_path):
    (tmp_path / ".git").mkdir()
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "keep.md").write_text(
        "---\nexport: true\ntitle: Keep\ntags: [cheatsheet]\n---\n# Keep\n", encoding="utf-8"
    )
    (notes / "plain.md").write_text("---\ntitle: Plain\n---\n# Plain\n", encoding="utf-8")
    (notes / "draft.md").write_text(
        "---\nexport: true\ndraft: true\n---\n# Draft\n", encoding="utf-8"
    )
    return tmp_path


def _names(results):
    return {p.name for p, _ in results}


def test_find_requires_export_true(vault):
    found = find_exportable(vault, repo_root=vault)
    assert _names(found) == {"keep.md"}  # plain (no export) and draft excluded


def test_find_tag_filter(vault):
    assert _names(find_exportable(vault, tags=["cheatsheet"], repo_root=vault)) == {"keep.md"}
    assert find_exportable(vault, tags=["nonexistent"], repo_root=vault) == []


def test_find_skips_hidden_dirs_relative_to_source(tmp_path):
    # A vault living under a dotted path must not skip everything.
    vault = tmp_path / ".obsidian-vault"
    vault.mkdir()
    (vault / "n.md").write_text("---\nexport: true\n---\n# N\n", encoding="utf-8")
    found = find_exportable(vault, repo_root=vault)
    assert _names(found) == {"n.md"}


def test_stage_dedupes_same_filename(tmp_path):
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir(parents=True)
    f1 = src / "a" / "note.md"
    f2 = src / "b" / "note.md"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")
    staging = tmp_path / "staging"
    staged = stage_files([(f1, {}), (f2, {})], staging, use_symlinks=False, source_dir=src)
    names = {p.name for p, _orig, _fm in staged}
    assert "note.md" in names
    assert any(n.endswith("--note.md") for n in names)  # second was renamed


def test_stage_skips_symlink_escaping_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    outside = tmp_path / "secret.md"
    outside.write_text("secret", encoding="utf-8")
    link = src / "link.md"
    link.symlink_to(outside)
    staged = stage_files([(link, {})], tmp_path / "staging", source_dir=src)
    assert staged == []  # symlink pointing outside the source tree is skipped


def test_collect_places_by_export_path_and_filename(tmp_path):
    dest = tmp_path / "dest"
    src_root = tmp_path / "src"
    src_root.mkdir()
    orig = src_root / "notes" / "report.md"
    orig.parent.mkdir()
    orig.write_text("x", encoding="utf-8")
    built = tmp_path / "build" / "report.pdf"
    built.parent.mkdir()
    built.write_bytes(b"%PDF")

    fm = {"export_path": "Cheat Sheets", "export_filename": "My Report"}
    copied = collect_outputs([(built, orig, fm)], dest, src_root)
    assert copied == [dest / "Cheat Sheets" / "My Report.pdf"]
    assert (dest / "Cheat Sheets" / "My Report.pdf").exists()


def test_collect_mirrors_source_when_no_export_path(tmp_path):
    dest = tmp_path / "dest"
    src_root = tmp_path / "src"
    src_root.mkdir()
    orig = src_root / "a" / "b" / "doc.md"
    orig.parent.mkdir(parents=True)
    orig.write_text("x", encoding="utf-8")
    built = tmp_path / "build" / "doc.pdf"
    built.parent.mkdir()
    built.write_bytes(b"%PDF")

    copied = collect_outputs([(built, orig, {})], dest, src_root)
    assert copied == [dest / "a" / "b" / "doc.pdf"]


def test_collect_rejects_export_path_traversal(tmp_path):
    dest = tmp_path / "dest"
    src_root = tmp_path / "src"
    src_root.mkdir()
    built = tmp_path / "build" / "doc.pdf"
    built.parent.mkdir()
    built.write_bytes(b"%PDF")
    fm = {"export_path": "../../escape"}
    copied = collect_outputs([(built, src_root / "doc.md", fm)], dest, src_root)
    assert copied == []  # traversal outside dest is refused
