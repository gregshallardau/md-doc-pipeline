"""Tests for md-doc-web-editor's FastAPI server."""

import pytest
from fastapi.testclient import TestClient

from md_doc_web_editor import create_app


@pytest.fixture()
def workspace(tmp_path):
    """A small workspace with a few files and a 2-level _meta.yml cascade."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "_meta.yml").write_text("product_name: acme\n", encoding="utf-8")
    (tmp_path / "_pdf-theme.css").write_text("body { color: black; }\n", encoding="utf-8")

    sub = tmp_path / "products" / "nova"
    sub.mkdir(parents=True)
    (sub / "_meta.yml").write_text("version: '3.2'\n", encoding="utf-8")
    (sub / "doc.md").write_text(
        "---\ntitle: Test Doc\n---\n\n"
        "# {{ product_name | title }} v{{ version }}\n\n"
        '{% include "header.md" %}\n',
        encoding="utf-8",
    )

    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "header.md").write_text("Shared header\n", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def client(workspace):
    return TestClient(create_app(workspace))


# ── /api/tree ────────────────────────────────────────────────────────────────


class TestTree:
    def test_tree_lists_files_and_dirs(self, client, workspace):
        r = client.get("/api/tree")
        assert r.status_code == 200
        data = r.json()
        assert data["workspace"] == str(workspace)

        # Top-level should include the _meta.yml, _pdf-theme.css, products dir,
        # and templates dir
        names = [item["name"] for item in data["tree"]]
        assert "_meta.yml" in names
        assert "_pdf-theme.css" in names
        assert "products" in names
        assert "templates" in names

    def test_tree_classifies_file_types(self, client):
        r = client.get("/api/tree")
        for item in r.json()["tree"]:
            if item["name"] == "_meta.yml":
                assert item["type"] == "meta"
            elif item["name"] == "_pdf-theme.css":
                assert item["type"] == "css"


# ── /api/file (read + write) ─────────────────────────────────────────────────


class TestFileRead:
    def test_read_file_returns_content(self, client):
        r = client.get("/api/file?path=products/nova/doc.md")
        assert r.status_code == 200
        data = r.json()
        assert data["path"] == "products/nova/doc.md"
        assert data["type"] == "md"
        assert "product_name" in data["content"]

    def test_read_missing_file_returns_404(self, client):
        r = client.get("/api/file?path=does/not/exist.md")
        assert r.status_code == 404

    def test_read_path_traversal_blocked(self, client):
        r = client.get("/api/file?path=../etc/passwd")
        assert r.status_code == 400


class TestFileWrite:
    def test_write_creates_or_updates_file(self, client, workspace):
        r = client.put(
            "/api/file",
            json={"path": "products/nova/doc.md", "content": "new content"},
        )
        assert r.status_code == 200
        assert (workspace / "products" / "nova" / "doc.md").read_text() == "new content"

    def test_write_path_traversal_blocked(self, client):
        r = client.put(
            "/api/file",
            json={"path": "../escape.txt", "content": "x"},
        )
        assert r.status_code == 400


# ── /api/config ──────────────────────────────────────────────────────────────


class TestConfig:
    def test_config_returns_cascaded_layers(self, client):
        r = client.get("/api/config?path=products/nova/doc.md")
        assert r.status_code == 200
        data = r.json()
        # Three layers: workspace _meta.yml + products/nova/_meta.yml + frontmatter
        assert len(data["layers"]) == 3
        merged = data["merged"]
        assert merged["product_name"] == "acme"
        assert merged["version"] == "3.2"
        assert merged["title"] == "Test Doc"


# ── /api/css ─────────────────────────────────────────────────────────────────


class TestCss:
    def test_css_resolves_pdf_theme(self, client):
        r = client.get("/api/css?path=products/nova/doc.md")
        assert r.status_code == 200
        data = r.json()
        assert data["source"] == "_pdf-theme.css"
        assert "body { color: black; }" in data["css"]

    def test_css_returns_empty_when_no_theme(self, tmp_path):
        # Workspace with no theme files at all
        (tmp_path / ".git").mkdir()
        (tmp_path / "doc.md").write_text("# x\n", encoding="utf-8")
        client = TestClient(create_app(tmp_path))
        r = client.get("/api/css?path=doc.md")
        assert r.status_code == 200
        assert r.json()["source"] is None


# ── /api/includes ────────────────────────────────────────────────────────────


class TestIncludes:
    def test_includes_lists_resolved_templates(self, client):
        r = client.get("/api/includes?path=products/nova/doc.md")
        assert r.status_code == 200
        items = r.json()["includes"]
        assert len(items) == 1
        assert items[0]["name"] == "header.md"
        assert items[0]["found"] is True
        assert items[0]["path"] == "templates/header.md"

    def test_missing_template_marked_not_found(self, workspace, client):
        # Replace doc with one that references a missing template
        (workspace / "products" / "nova" / "doc.md").write_text(
            '---\ntitle: x\n---\n{% include "ghost.md" %}\n',
            encoding="utf-8",
        )
        r = client.get("/api/includes?path=products/nova/doc.md")
        assert r.status_code == 200
        items = r.json()["includes"]
        assert items[0]["name"] == "ghost.md"
        assert items[0]["found"] is False

    def test_non_md_file_returns_empty(self, client):
        r = client.get("/api/includes?path=_meta.yml")
        assert r.status_code == 200
        assert r.json()["includes"] == []


# ── Static / index ───────────────────────────────────────────────────────────


class TestIndex:
    def test_index_serves_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "md-doc editor" in r.text
        assert "tokenizers.js" in r.text

    def test_static_assets_are_served(self, client):
        r = client.get("/static/editor.js")
        assert r.status_code == 200
        assert "registerMdDocLanguages" in r.text or "loadTree" in r.text


# ── Programmatic registration ────────────────────────────────────────────────


class TestProgrammatic:
    def test_create_app_rejects_non_dir(self, tmp_path):
        f = tmp_path / "not-a-dir"
        f.write_text("x")
        with pytest.raises(ValueError, match="not a directory"):
            create_app(f)
