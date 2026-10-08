"""Real remote trees and links must survive scanning, reading and previewing."""

import io
import time

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from md_doc_web_editor.server import create_app
from tools.create_remote_editor_demo import create_demo


@pytest.fixture
def remote_demo(tmp_path):
    return create_demo(tmp_path / "demo")


@pytest.mark.parametrize("name", ["affinity-demo", "affinity-linked-demo"])
def test_fifteen_remote_folders_and_fifty_files(remote_demo, name):
    from pathlib import Path

    with TestClient(create_app(project=Path(remote_demo["project"]))) as client:
        data = client.get("/api/tree", params={"workspace": name}).json()
        assert data["documentCount"] == 50
        assert len([node for node in data["tree"] if node["type"] == "dir"]) == 15
        assert not data["scanWarnings"]
        documents = []

        def flatten(nodes):
            for node in nodes:
                if node["type"] == "dir":
                    flatten(node["children"])
                elif node["type"] == "md":
                    documents.append(node["path"])

        flatten(data["tree"])
        assert len(documents) == 50
        for document in documents:
            response = client.get("/api/file", params={"workspace": name, "path": document})
            assert response.status_code == 200, response.text
            assert "# Affinity document" in response.json()["content"]
        document = next(path for path in documents if path.endswith("document-01.md"))
        original = client.get("/api/file", params={"workspace": name, "path": document}).json()
        edited = original["content"].replace("Affinity document 01", "Unsaved remote document")
        job = client.post(
            "/api/preview/jobs",
            params={"workspace": name},
            json={"path": document, "buffers": {document: edited}},
        ).json()
        deadline = time.monotonic() + 30
        while job["state"] in {"queued", "running"}:
            assert time.monotonic() < deadline, job
            time.sleep(0.05)
            job = client.get("/api/jobs/" + job["id"], params={"workspace": name}).json()
        assert job["state"] == "succeeded", job
        pdf = client.get(job["artifact"]["url"], params={"workspace": name})
        with pdfplumber.open(io.BytesIO(pdf.content)) as document_pdf:
            text = "\n".join(page.extract_text() or "" for page in document_pdf.pages)
        assert "Unsaved remote document" in text
        assert "Affinity Demo" in text
        assert "Included from the remote document root" in text
        assert (
            client.get("/api/file", params={"workspace": name, "path": document}).json()["content"]
            == original["content"]
        )


def test_cycles_and_external_links_are_reported(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "doc.md").write_text("# A document\n")
    (root / "cycle").symlink_to(root, target_is_directory=True)
    external = tmp_path / "external"
    external.mkdir()
    (external / "secret.md").write_text("# Not a workspace document\n")
    (root / "external").symlink_to(external, target_is_directory=True)
    with TestClient(create_app(root)) as client:
        tree = client.get("/api/tree").json()
        assert tree["documentCount"] == 1
        assert len(tree["scanWarnings"]) == 2
        assert any("cycle" in warning["message"] for warning in tree["scanWarnings"])
        assert any("outside" in warning["message"] for warning in tree["scanWarnings"])
        assert client.get("/api/file?path=external/secret.md").status_code == 400


def test_permission_errors_are_visible(tmp_path, monkeypatch):
    from pathlib import Path

    (tmp_path / "blocked").mkdir()
    original = Path.iterdir

    def blocked(path):
        if path.name == "blocked":
            raise PermissionError("Permission denied")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", blocked)
    with TestClient(create_app(tmp_path)) as client:
        tree = client.get("/api/tree").json()
        assert tree["tree"][0]["name"] == "blocked"
        assert tree["tree"][0]["scanError"] == "Permission denied"
        assert tree["scanWarnings"][0]["message"] == "Permission denied"
