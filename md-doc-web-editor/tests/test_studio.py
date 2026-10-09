"""Studio contracts with real pipeline artifacts and filesystem isolation."""

from __future__ import annotations

import io
import subprocess
import time
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from md_doc_web_editor.server import create_app
from md_doc_web_editor.snapshots import make_snapshot


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "_meta.yml").write_text(
        "product: Original\nauthor: Studio Test\ndate: 8 October 2026\n"
    )
    theme = Path(__file__).resolve().parents[2] / "examples/feature-showcase/_theme.css"
    (tmp_path / "_theme.css").write_text(theme.read_text() + '\n@import "palette.css";\n')
    (tmp_path / "palette.css").write_text(".report-body h2 { color: #23845d; }\n")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates/shared.md").write_text("Included original\n")
    (tmp_path / "_merge_fields.yml").write_text("contact_name: Contact full name\n")
    workspace = tmp_path / "documents"
    workspace.mkdir()
    (workspace / "_docx-theme.css").write_text("body { color: purple; }\n")
    (workspace / "doc.md").write_text(
        "---\ncover_page: true\n---\n# Snapshot {{ product }}\n\n"
        '## Content\n\n{% include "shared.md" %}\n\n'
        "<!-- pagebreak -->\n\n## Second page\n\nA final paragraph.\n"
    )
    return workspace


def wait_job(client, job):
    deadline = time.monotonic() + 30
    while job["state"] in {"queued", "running"}:
        assert time.monotonic() < deadline, job
        time.sleep(0.05)
        job = client.get("/api/jobs/" + job["id"]).json()
    return job


def test_composed_outline_uses_unsaved_context_nested_templates_and_source_locations(project):
    source = (
        "---\ncover_page: true\n---\n# {{ product }} report\n\n"
        '{% include "shared.md" %}\n\n'
        "{% if show_extra %}\n## Optional section\n{% endif %}\n"
        "```markdown\n# Example, not a heading\n```\n"
    )
    (project.parent / "templates/nested.html").write_text("<h3>Nested <em>section</em></h3>\n")
    fragment = (
        "## Shared {{ product }}\n\n"
        '{% include "nested.html" %}\n\n'
        "{% for item in sections %}\n### {{ item }}\n{% endfor %}\n\n"
        "Setext section\n--------------\n"
    )
    with TestClient(create_app(project)) as client:
        response = client.post(
            "/api/outline",
            json={
                "path": "doc.md",
                "revision": 3,
                "buffers": {
                    "doc.md": source,
                    "project:templates/shared.md": fragment,
                    "project:_meta.yml": "product: Draft\nshow_extra: false\nsections: [Alpha, Beta]\n",
                },
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["revision"] == 3
        assert [heading["title"] for heading in data["headings"]] == [
            "Draft report",
            "Shared Draft",
            "Nested section",
            "Alpha",
            "Beta",
            "Setext section",
        ]
        assert data["headings"][0]["path"] == "doc.md"
        assert data["headings"][0]["line"] == 4
        assert data["headings"][1]["path"] == "project:templates/shared.md"
        assert data["headings"][2]["path"] == "project:templates/nested.html"
        assert data["headings"][3]["line"] == data["headings"][4]["line"] == 6
        assert {link["path"] for link in data["includes"]} == {
            "project:templates/shared.md",
            "project:templates/nested.html",
        }
        assert (project.parent / "templates/shared.md").read_text() == "Included original\n"
        assert "Original" in (project.parent / "_meta.yml").read_text()
        assert "Snapshot" in (project / "doc.md").read_text()


def test_outline_rejects_invalid_templates_and_paths(project):
    with TestClient(create_app(project)) as client:
        assert client.post("/api/outline", json={"path": "../outside.md"}).status_code == 400
        response = client.post(
            "/api/outline",
            json={
                "path": "doc.md",
                "buffers": {"doc.md": '{% include "missing.md" %}'},
            },
        )
        assert response.status_code == 422


def test_exact_snapshot_preview_keeps_sources_untouched(project):
    original = (project / "doc.md").read_text()
    request = {
        "path": "doc.md",
        "revision": 7,
        "buffers": {
            "project:_meta.yml": "product: Unsaved\nauthor: Studio Test\ndate: 8 October 2026\n",
            "project:templates/shared.md": "Included unsaved text\n",
            "project:palette.css": ".report-body h2 { color: #c84449; }\n",
        },
    }
    with TestClient(create_app(project)) as client:
        response = client.post("/api/preview/jobs", json=request)
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json())
        assert job["state"] == "succeeded", job
        assert job["revision"] == 7
        assert job["inspection"]["merged"]["product"] == "Unsaved"
        assert job["inspection"]["theme"]["source"] == str(project.parent / "_theme.css")
        assert job["inspection"]["includes"][0]["path"] == "project:templates/shared.md"
        artifact = client.get(job["artifact"]["url"])
        assert artifact.headers["content-type"] == "application/pdf"
        assert artifact.content == client.get(job["artifact"]["url"] + "?download=true").content
        with pdfplumber.open(io.BytesIO(artifact.content)) as pdf:
            assert len(pdf.pages) == 3
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            assert "Snapshot Unsaved" in text
            assert "Included unsaved text" in text
            assert "Included original" not in text
        assert (project / "doc.md").read_text() == original
        assert "Original" in (project.parent / "_meta.yml").read_text()
        assert (project.parent / "templates/shared.md").read_text() == "Included original\n"


@pytest.mark.parametrize("format", ["docx", "dotx", "pptx"])
def test_office_snapshot_exports(project, format):
    original = (project / "doc.md").read_text()
    with TestClient(create_app(project)) as client:
        response = client.post(
            "/api/preview/jobs",
            json={"path": "doc.md", "format": format, "purpose": "export"},
        )
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json())
        assert job["state"] == "succeeded", job
        artifact = client.get(job["artifact"]["url"])
        assert artifact.content.startswith(b"PK")
        assert (project / "doc.md").read_text() == original


def test_invalid_snapshot_preserves_saved_files_and_cleans_job(project):
    with TestClient(create_app(project)) as client:
        response = client.post(
            "/api/preview/jobs",
            json={
                "path": "doc.md",
                "buffers": {"project:_meta.yml": "product: [invalid\n"},
            },
        )
        assert response.status_code == 422
        assert not list(client.app.state.build_root.iterdir())
        result = client.post(
            "/api/preview/jobs",
            json={
                "path": "doc.md",
                "buffers": {"doc.md": "# {{ missing_variable }}\n"},
            },
        )
        job = wait_job(client, result.json())
        assert job["state"] == "failed"
        assert "missing_variable" in job["error"]
        assert not list(client.app.state.build_root.iterdir())


def test_preview_with_no_theme_does_not_generate_source_theme(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "doc.md").write_text("# No theme\n")
    with TestClient(create_app(tmp_path)) as client:
        job = wait_job(client, client.post("/api/preview/jobs", json={"path": "doc.md"}).json())
        assert job["state"] == "succeeded", job
        assert not (tmp_path / "_pdf-theme.css").exists()


def test_revision_safe_save_and_origin_protection(project):
    with TestClient(create_app(project)) as client:
        disk = client.get("/api/file", params={"path": "doc.md"}).json()
        (project / "doc.md").write_text("External edit\n")
        result = client.put(
            "/api/file",
            json={"path": "doc.md", "content": "My draft", "revision": disk["revision"]},
        )
        assert result.status_code == 409
        assert result.json()["detail"]["content"] == "External edit\n"
        assert (project / "doc.md").read_text() == "External edit\n"
        request = {"path": "doc.md", "content": "Unsafe"}
        assert (
            client.put(
                "/api/file", json=request, headers={"Origin": "http://evil.test"}
            ).status_code
            == 403
        )
        assert (
            client.put(
                "/api/file", json=request, headers={"Origin": "http://testserver"}
            ).status_code
            == 403
        )
        token = client.get("/api/capabilities").json()["session"]
        assert (
            client.put(
                "/api/file",
                json=request,
                headers={"Origin": "http://testserver", "X-Editor-Token": token},
            ).status_code
            == 200
        )


def test_snapshot_scopes_project_dependencies_and_excludes_symlinks(project, tmp_path):
    (project / "escape.css").symlink_to("/etc/passwd")
    with pytest.raises(ValueError):
        make_snapshot(project, tmp_path / "blocked", {"../secret.md": "unsafe"})
    with pytest.raises(ValueError):
        make_snapshot(project, tmp_path / "blocked2", {"project:.git/config": "unsafe"})
    root1 = tmp_path / "snapshot-one"
    root2 = tmp_path / "snapshot-two"
    # Keep snapshots outside the source project to avoid recursive input discovery.
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root1 = Path(directory) / "one"
        root2 = Path(directory) / "two"
        selected, first = make_snapshot(project, root1, {"project:_meta.yml": "product: New"})
        _, second = make_snapshot(project, root2, {"project:_meta.yml": "product: New"})
        assert first == second
        assert not (selected / "escape.css").exists()


def test_recoverable_trash_and_file_search(project):
    with TestClient(create_app(project)) as client:
        original = (project / "doc.md").read_text()
        results = client.get("/api/search", params={"q": "final paragraph"}).json()["results"]
        assert results[0]["path"] == "doc.md"
        result = client.post("/api/files/action", json={"action": "trash", "path": "doc.md"}).json()
        assert not (project / "doc.md").exists()
        restore = client.post(
            "/api/files/action",
            json={"action": "restore", "path": "doc.md", "destination": result["restore"]},
        )
        assert restore.status_code == 200
        assert (project / "doc.md").read_text() == original


def test_asset_upload_validation_and_collision(project):
    import base64
    from PIL import Image

    content = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(content, format="PNG")
    encoded = base64.b64encode(content.getvalue()).decode()
    with TestClient(create_app(project)) as client:
        request = {"path": "assets/logo.png", "data": encoded}
        assert client.post("/api/assets", json=request).status_code == 200
        assert (project / "assets/logo.png").read_bytes() == content.getvalue()
        assert client.post("/api/assets", json=request).status_code == 409
        assert (
            client.post("/api/assets", json={**request, "path": "../logo.png"}).status_code == 400
        )
        assert (
            client.post("/api/assets", json={**request, "path": ".hidden/logo.png"}).status_code
            == 400
        )
        assert (
            client.post("/api/assets", json={**request, "path": "assets/not-jpeg.jpg"}).status_code
            == 422
        )


def test_cancelled_jobs_reap_worker_and_remove_snapshot(project):
    with TestClient(create_app(project)) as client:
        result = client.post("/api/preview/jobs", json={"path": "doc.md"}).json()
        assert client.delete("/api/jobs/" + result["id"]).status_code == 200
        job = wait_job(client, client.get("/api/jobs/" + result["id"]).json())
        assert job["state"] == "cancelled"
        deadline = time.monotonic() + 5
        while list(client.app.state.build_root.iterdir()):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert not client.app.state.studio.processes


def test_git_stage_commit_only_workspace_files(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True
        ).stdout

    git("init")
    git("config", "user.name", "Editor Test")
    git("config", "user.email", "editor@example.test")
    workspace = tmp_path / "documents"
    workspace.mkdir()
    (workspace / "doc.md").write_text("# Initial\n")
    (tmp_path / "outside.md").write_text("Outside initial\n")
    git("add", ".")
    git("commit", "-m", "Initial")
    (tmp_path / "outside.md").write_text("Outside staged edit\n")
    git("add", "outside.md")
    (workspace / "doc.md").write_text("# Updated\n")
    with TestClient(create_app(workspace)) as client:
        status = client.get("/api/git/status").json()
        assert [item["path"] for item in status["files"]] == ["doc.md"]
        assert "Updated" in client.get("/api/git/diff", params={"path": "doc.md"}).json()["diff"]
        assert (
            client.post(
                "/api/git/action", json={"action": "stage", "path": "../outside.md"}
            ).status_code
            == 400
        )
        assert (
            client.post("/api/git/action", json={"action": "stage", "path": "doc.md"}).status_code
            == 200
        )
        (workspace / "doc.md").write_text("# Later unstaged draft\n")
        result = client.post(
            "/api/git/action", json={"action": "commit", "message": "Update document"}
        )
        assert result.status_code == 200, result.text
        assert client.get("/api/git/status").json()["files"][0]["code"] == " M"
        assert git("show", "HEAD:documents/doc.md") == "# Updated\n"
        assert (workspace / "doc.md").read_text() == "# Later unstaged draft\n"
        assert "outside.md" in git("diff", "--cached", "--name-only")
        assert git("show", "HEAD:outside.md") == "Outside initial\n"


def test_inline_template_resolution_uses_cascade_and_authoring_boundary(project):
    with TestClient(create_app(project)) as client:
        response = client.get("/api/template", params={"path": "doc.md", "name": "shared.md"})
        assert response.status_code == 200
        assert response.json()["path"] == "project:templates/shared.md"
        assert (
            client.get("/api/file", params={"path": response.json()["path"]}).json()["content"]
            == "Included original\n"
        )
        (project.parent / "root-fragment.md").write_text("Root fragment\n")
        root_fragment = client.get(
            "/api/template", params={"path": "doc.md", "name": "root-fragment.md"}
        )
        assert root_fragment.json()["path"] == "project:root-fragment.md"
        assert (
            client.get("/api/file", params={"path": root_fragment.json()["path"]}).json()["content"]
            == "Root fragment\n"
        )
        (project.parent / "templates/header.html").write_text("<p>HTML fragment</p>")
        html_fragment = client.get(
            "/api/template", params={"path": "doc.md", "name": "header.html"}
        )
        assert html_fragment.status_code == 200
        assert html_fragment.json()["path"] == "project:templates/header.html"
        assert (
            client.get("/api/file", params={"path": html_fragment.json()["path"]}).json()["content"]
            == "<p>HTML fragment</p>"
        )
        (project / "templates").mkdir()
        (project / "templates/shared.md").write_text("Local override\n")
        assert (
            client.get("/api/template", params={"path": "doc.md", "name": "shared.md"}).json()[
                "path"
            ]
            == "templates/shared.md"
        )
        assert (
            client.get("/api/template", params={"path": "doc.md", "name": "missing.md"}).status_code
            == 404
        )
        assert (
            client.get(
                "/api/template", params={"path": "doc.md", "name": "/etc/passwd"}
            ).status_code
            == 404
        )
