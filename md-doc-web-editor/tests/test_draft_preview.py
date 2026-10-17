"""Draft preview: the builder's HTML, served without WeasyPrint layout."""

from __future__ import annotations

import base64
import re
import time

import pytest
from fastapi.testclient import TestClient

from md_doc_web_editor.server import create_app
from md_doc_web_editor.worker import draft_html

PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "_meta.yml").write_text("product: Draft\nauthor: Tester\ndate: 8 October 2026\n")
    workspace = tmp_path / "documents"
    workspace.mkdir()
    (workspace / "pixel.png").write_bytes(PIXEL)
    (workspace / "doc.md").write_text(
        "---\ncover_page: true\n---\n# Draft {{ product }}\n\n"
        "## Content\n\n![dot](pixel.png)\n\nBody text.\n"
    )
    return workspace


def run_draft(client, buffers=None, **extra):
    response = client.post(
        "/api/preview/jobs",
        json={"path": "doc.md", "format": "html", "buffers": buffers or {}, **extra},
    )
    if response.status_code != 202:
        return response
    job = response.json()
    deadline = time.monotonic() + 30
    while job["state"] in {"queued", "running"}:
        assert time.monotonic() < deadline, job
        time.sleep(0.05)
        job = client.get("/api/jobs/" + job["id"]).json()
    return job


def test_draft_html_is_self_contained_and_reflects_unsaved_text(project):
    with TestClient(create_app(project)) as client:
        job = run_draft(client, {"doc.md": "# Unsaved heading\n\n![dot](pixel.png)\n\nEdited.\n"})
        assert job["state"] == "succeeded", job
        assert job["artifact"]["format"] == "html"
        page = client.get(job["artifact"]["url"])
        assert page.headers["content-type"].startswith("text/html")
        assert "Unsaved heading" in page.text
        # Snapshot files disappear with the job, so no file:// reference may remain.
        assert "file://" not in page.text
        assert "data:image/png;base64," in page.text
        csp = page.headers["content-security-policy"]
        assert "default-src 'none'" in csp and "sandbox" in csp


def test_draft_is_a_preview_only_format(project):
    with TestClient(create_app(project)) as client:
        response = run_draft(client, purpose="export")
        assert response.status_code == 400


def test_draft_html_leaves_outside_files_alone(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(PIXEL)
    inside = project_root / "a.png"
    inside.write_bytes(PIXEL)
    markup = (
        f'<html><head></head><body><img src="file://{inside}">'
        f'<img src="file://{outside}"></body></html>'
    )
    result = draft_html(markup, project_root.resolve())
    assert len(re.findall(r"data:image/png;base64,", result)) == 1
    assert f"file://{outside}" in result
