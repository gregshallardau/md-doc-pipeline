"""Workspace discovery: the editor finds a project's workspaces on its own."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from md_doc_web_editor import create_app
from md_doc_web_editor.cli import main
from md_doc_web_editor.workspaces import discover


@pytest.fixture()
def project(tmp_path):
    """A project with two local workspaces and a remote one."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "workspace" / "acme" / "clients").mkdir(parents=True)
    (tmp_path / "workspace" / "acme" / "_meta.yml").write_text("author: Acme\n", encoding="utf-8")
    (tmp_path / "workspace" / "acme" / "_pdf-theme.css").write_text("h1 { color: red; }\n")
    (tmp_path / "workspace" / "acme" / "templates").mkdir()
    (tmp_path / "workspace" / "acme" / "templates" / "head.md").write_text("HEAD\n")
    (tmp_path / "workspace" / "acme" / "clients" / "q1.md").write_text(
        '---\ntitle: Q1\n---\n{% include "head.md" %}\n# Q1\n', encoding="utf-8"
    )
    (tmp_path / "workspace" / "blueshift").mkdir()
    (tmp_path / "workspace" / "blueshift" / "doc.md").write_text("# B\n", encoding="utf-8")
    (tmp_path / "workspace" / ".hidden").mkdir()
    (tmp_path / "workspace" / "AGENTS.md").write_text("not a workspace\n")
    share = tmp_path / "mnt" / "share"
    share.mkdir(parents=True)
    (share / "note.md").write_text("# remote note\n", encoding="utf-8")
    (tmp_path / "workspace" / "remote-workspaces.yml").write_text(
        f"nas: {share}\nmissing:\n  path: {tmp_path / 'not-mounted'}\n  description: Offline share\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def client(project):
    return TestClient(create_app(project=project))


def test_discovers_local_and_remote_workspaces(project):
    found = {w.name: w for w in discover(project)}
    assert list(found) == ["acme", "blueshift", "nas", "missing"]
    assert not found["acme"].remote and found["nas"].remote
    assert found["nas"].available and not found["missing"].available
    assert found["missing"].description == "Offline share"
    assert ".hidden" not in found


def test_tree_lists_each_workspace_as_a_top_level_folder(client):
    data = client.get("/api/tree").json()
    nodes = {n["path"]: n for n in data["tree"]}
    assert list(nodes) == ["acme", "blueshift", "nas", "missing"]
    assert nodes["nas"]["remote"] is True and nodes["nas"]["name"] == "nas (remote)"
    assert nodes["missing"]["available"] is False and nodes["missing"]["children"] == []
    acme_files = [c["path"] for c in nodes["acme"]["children"]]
    assert "acme/_meta.yml" in acme_files
    assert [w["name"] for w in data["workspaces"]] == ["acme", "blueshift", "nas", "missing"]


def test_paths_are_prefixed_by_workspace_for_files_config_css_and_includes(client):
    doc = "acme/clients/q1.md"
    assert "title: Q1" in client.get("/api/file", params={"path": doc}).json()["content"]
    layers = client.get("/api/config", params={"path": doc}).json()["layers"]
    assert any(layer["file"] == "acme/_meta.yml" for layer in layers)
    assert client.get("/api/css", params={"path": doc}).json()["source"] == "acme/_pdf-theme.css"
    includes = client.get("/api/includes", params={"path": doc}).json()["includes"]
    assert includes[0]["path"] == "acme/templates/head.md"


def test_remote_workspace_is_readable_and_writable(client, project):
    assert (
        "remote note" in client.get("/api/file", params={"path": "nas/note.md"}).json()["content"]
    )
    r = client.put("/api/file", json={"path": "nas/new.md", "content": "# new\n"})
    assert r.status_code == 200 and (project / "mnt" / "share" / "new.md").read_text() == "# new\n"


def test_unknown_unavailable_and_escaping_paths_are_rejected(client):
    assert client.get("/api/file", params={"path": "nope/x.md"}).status_code == 404
    assert client.get("/api/file", params={"path": "missing/x.md"}).status_code == 404
    # one workspace can never reach another, or the project around it
    assert client.get("/api/file", params={"path": "acme/../blueshift/doc.md"}).status_code == 400
    assert client.get("/api/file", params={"path": "acme/../../.git/config"}).status_code == 400
    assert client.put("/api/file", json={"path": "acme/../x.md", "content": "x"}).status_code == 400


def test_new_workspaces_appear_without_a_restart(client, project):
    (project / "workspace" / "fresh").mkdir()
    (project / "workspace" / "fresh" / "a.md").write_text("# a\n")
    names = [n["path"] for n in client.get("/api/tree").json()["tree"]]
    assert "fresh" in names


def test_name_collisions_between_local_and_remote_are_disambiguated(project):
    (project / "workspace" / "remote-workspaces.yml").write_text(
        f"acme: {project / 'mnt' / 'share'}\n", encoding="utf-8"
    )
    names = [w.name for w in discover(project)]
    assert names == ["acme", "blueshift", "acme-remote"]


def test_fresh_checkout_falls_back_to_examples_then_the_project(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "examples" / "demo").mkdir(parents=True)
    assert [w.name for w in discover(tmp_path)] == ["demo"]
    (tmp_path / "examples" / "demo").rmdir()
    (tmp_path / "examples").rmdir()
    assert [w.root for w in discover(tmp_path)] == [tmp_path.resolve()]


def test_explicit_directory_keeps_the_original_single_root_behaviour(project):
    c = TestClient(create_app(project / "workspace" / "acme"))
    assert c.get("/api/file", params={"path": "clients/q1.md"}).status_code == 200
    tree = c.get("/api/tree").json()
    assert "workspaces" not in tree and any(n["path"] == "_meta.yml" for n in tree["tree"])


def test_running_with_no_arguments_serves_with_discovery(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "md_doc_web_editor.cli._run_serve", lambda args: seen.update(vars(args)) or 0
    )
    assert main([]) == 0 and seen["workspace"] is None and seen["port"] == 8765
    assert main(["--port", "9100", "--no-browser"]) == 0 and seen["port"] == 9100
    assert main(["serve", "somewhere"]) == 0 and seen["workspace"] == "somewhere"
