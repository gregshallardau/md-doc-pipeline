"""Editor regressions for config, sandbox scanning, and build lifetimes."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from md_doc_web_editor.server import create_app


def test_yaml_dates_are_json_serializable(tmp_path):
    (tmp_path / "_meta.yml").write_text("date: 2026-10-07\ntime: 2026-10-07T12:00:00Z\n")
    (tmp_path / "doc.md").write_text("# Test")
    with TestClient(create_app(tmp_path)) as client:
        result = client.get("/api/config", params={"path": "doc.md"})
        assert result.status_code == 200
        assert result.json()["merged"]["date"] == "2026-10-07"
        assert result.json()["merged"]["time"].startswith("2026-10-07T12:00:00")


def test_tree_and_includes_do_not_follow_outside_symlinks(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (tmp_path / "secret.md").write_text("secret")
    (root / "outside").symlink_to(tmp_path, target_is_directory=True)
    (root / "loop").symlink_to(root, target_is_directory=True)
    (root / "doc.md").write_text('{% include "outside/secret.md" %}')
    with TestClient(create_app(root)) as client:
        assert [item["name"] for item in client.get("/api/tree").json()["tree"]] == ["doc.md"]
        includes = client.get("/api/includes", params={"path": "doc.md"}).json()["includes"]
        assert includes == [{"name": "outside/secret.md", "path": None, "found": False}]


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing"])
def test_failed_build_removes_temporary_files(tmp_path, monkeypatch, failure):
    from md_doc_web_editor import server

    (tmp_path / "doc.md").write_text("# Test")
    app = create_app(tmp_path)

    def run(args, **kwargs):
        output = Path(args[args.index("--output") + 1])
        (output / "partial.tmp").write_bytes(b"partial")
        if failure == "timeout":
            raise server.subprocess.TimeoutExpired(args, 180)
        return SimpleNamespace(returncode=1 if failure == "exit" else 0, stderr="broken", stdout="")

    monkeypatch.setattr(server.subprocess, "run", run)
    with TestClient(app) as client:
        result = client.post("/api/build", json={"path": "doc.md"})
        assert result.status_code in (500, 504)
        assert list(app.state.build_root.iterdir()) == []
        assert app.state.builds == {}
    assert not app.state.build_root.exists()


def test_expiration_deletes_artifact_and_token(tmp_path, monkeypatch):

    app = create_app(tmp_path)
    directory = app.state.build_root / "expired"
    directory.mkdir()
    (directory / "file.pdf").write_bytes(b"pdf")
    app.state.builds["expired"] = {"path": str(directory / "file.pdf"), "expires_at": 0}
    with TestClient(app) as client:
        assert client.get("/api/build/expired").status_code == 404
        assert not directory.exists()
        assert app.state.builds == {}


def test_local_assets_and_network_policy(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        page = client.get("/")
        assert "https://cdn" not in page.text
        assert "connect-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["x-dns-prefetch-control"] == "off"
        for asset in (
            "vendor/marked-17.0.5/marked.umd.js",
            "vendor/monaco-editor-0.52.2/min/vs/loader.js",
            "vendor/monaco-editor-0.52.2/min/vs/editor/editor.main.js",
            "vendor/monaco-editor-0.52.2/min/vs/base/worker/workerMain.js",
            "vendor/monaco-editor-0.52.2/min/vs/base/browser/ui/codicons/codicon/codicon.ttf",
        ):
            result = client.get("/static/" + asset)
            assert result.status_code == 200, asset
            assert result.content
