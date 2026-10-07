"""Reproductions of application review findings, exercising public build paths."""

from zipfile import ZipFile

import pytest
from click.testing import CliRunner
from jinja2 import TemplateNotFound
from PIL import Image

from md_doc.cli import _apply_filename_override, _run_export_build, main
from md_doc.exporter import stage_files
from md_doc.renderer import render
from md_doc.sync import run as sync


@pytest.mark.parametrize(
    "name",
    ["../../escaped", "../escaped.pdf", "/tmp/escaped", r"..\escaped", "C:escaped", "..", " "],
)
def test_output_filename_cannot_escape(tmp_path, name):
    with pytest.raises(ValueError):
        _apply_filename_override(tmp_path / "doc.pdf", {"output_filename": name}, "pdf")


def test_output_filename_rejects_symlink_target(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "escape.pdf").symlink_to(tmp_path / "outside.pdf")
    with pytest.raises(ValueError):
        _apply_filename_override(out / "doc.pdf", {"output_filename": "escape"}, "pdf")


@pytest.mark.parametrize("reference", ["../secret.md", "alias.md", "templates/secret.md"])
def test_include_cannot_read_outside_workspace(tmp_path, reference):
    root = tmp_path / "workspace"
    root.mkdir()
    (tmp_path / "secret.md").write_text("private")
    (root / "alias.md").symlink_to(tmp_path / "secret.md")
    (root / "templates").symlink_to(tmp_path, target_is_directory=True)
    doc = root / "doc.md"
    doc.write_text('{% include "' + reference + '" %}')
    with pytest.raises(TemplateNotFound):
        render(doc, repo_root=root)


@pytest.mark.parametrize("symlinks", [True, False])
def test_export_staging_handles_three_colliding_names(tmp_path, symlinks):
    files = []
    for name in ["a", "b", "c"]:
        src = tmp_path / name / "same" / "note.md"
        src.parent.mkdir(parents=True)
        src.write_text(name)
        files.append((src, {}))
    staged = stage_files(files, tmp_path / "stage", use_symlinks=symlinks)
    assert len({p.name for p, _, _ in staged}) == 3
    assert [p.read_text() for p, _, _ in staged] == ["a", "b", "c"]


def test_copied_export_preserves_config_includes_and_assets(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "_meta.yml").write_text("company: Acme\noutputs: [docx]\n")
    (source / "fragment.md").write_text("Hello {{ company }}")
    Image.new("RGB", (5, 5), "red").save(source / "logo.png")
    doc = source / "note.md"
    doc.write_text('{% include "fragment.md" %}\n\n![Logo](logo.png)')
    staging = tmp_path / "stage"
    staged = stage_files([(doc, {})], staging, use_symlinks=False)
    _run_export_build(staged, staging, source, tmp_path / "export", "docx", False)
    with ZipFile(tmp_path / "export" / "note.docx") as archive:
        assert b"Hello Acme" in archive.read("word/document.xml")
        assert any(p.startswith("word/media/") for p in archive.namelist())


def test_local_sync_never_recopies_its_destination(tmp_path):
    dest = tmp_path / "share"
    (tmp_path / "_meta.yml").write_text(f"sync_target: local\nsync_config:\n  path: {dest}\n")
    (tmp_path / "note.pdf").write_bytes(b"pdf")
    sync(tmp_path)
    sync(tmp_path)
    assert (dest / "note.pdf").exists()
    assert not (dest / "share").exists()


def test_local_sync_rejects_source_as_destination(tmp_path):
    (tmp_path / "_meta.yml").write_text(f"sync_target: local\nsync_config:\n  path: {tmp_path}\n")
    with pytest.raises(ValueError):
        sync(tmp_path)


def test_table_images_are_embedded_inside_the_cell(tmp_path):
    from md_doc.builders.docx import build
    from lxml import etree

    Image.new("RGB", (10, 10), "red").save(tmp_path / "image.png")
    doc = tmp_path / "doc.md"
    doc.write_text("| Image |\n|---|\n| before ![image](image.png) after |\n| ![missing](no.png) |")
    output = tmp_path / "doc.docx"
    build(doc.read_text(), {}, output, doc_path=doc, repo_root=tmp_path)
    with ZipFile(output) as archive:
        xml = etree.fromstring(archive.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        assert len(xml.xpath("//w:tc//w:drawing", namespaces=ns)) == 1
        assert "missing" in "".join(xml.xpath("//w:tc//w:t/text()", namespaces=ns))


def test_incremental_tracks_neighbor_edits_and_deletions(tmp_path):
    (tmp_path / ".git").mkdir()
    fragment = tmp_path / "fragment.md"
    fragment.write_text("original")
    doc = tmp_path / "doc.md"
    doc.write_text('{% include "fragment.md" %}')
    args = ["build", str(doc), "--format", "docx", "--no-lint"]
    runner = CliRunner()
    assert runner.invoke(main, args).exit_code == 0
    assert "up to date" in runner.invoke(main, args).output
    fragment.write_text("changed")
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    fragment.unlink()
    result = runner.invoke(main, args)
    assert result.exit_code != 0
    assert "TemplateNotFound" in result.output


def test_dependency_signature_tracks_assets_and_external_css_imports(tmp_path):
    from md_doc.dependencies import signature

    root = tmp_path / "workspace"
    root.mkdir()
    theme = tmp_path / "theme.css"
    imported = tmp_path / "colors.css"
    theme.write_text('@import "colors.css";')
    imported.write_text("body { color: red }")
    before = signature(root, {}, [theme])
    imported.write_text("body { color: blue }")
    assert signature(root, {}, [theme]) != before
    image = root / "image.png"
    image.write_bytes(b"old")
    before = signature(root, {})
    image.unlink()
    assert signature(root, {}) != before


def test_workspace_theme_tracks_external_import_deletion(tmp_path):
    from md_doc.dependencies import signature

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "_theme.css").write_text('@import "../shared.css";')
    shared = tmp_path / "shared.css"
    shared.write_text("body { color: red }")
    before = signature(root, {})
    shared.unlink()
    assert signature(root, {}) != before


def test_include_parent_inside_workspace_is_allowed(tmp_path):
    (tmp_path / "fragment.md").write_text("shared")
    (tmp_path / "child").mkdir()
    doc = tmp_path / "child" / "doc.md"
    doc.write_text('{% include "../fragment.md" %}')
    assert "shared" in render(doc, repo_root=tmp_path)
