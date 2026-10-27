"""Tests for the shared-content refactor endpoints."""

import pytest
from fastapi.testclient import TestClient

from md_doc_web_editor import create_app

ABOUT = (
    "## About Blueshift\n\n"
    "Blueshift is a consultancy helping teams ship documents faster, with\n"
    "templates, themes and automated builds across every format.\n"
)


@pytest.fixture()
def workspace(tmp_path):
    (tmp_path / ".git").mkdir()
    for client in ("a", "b", "c"):
        d = tmp_path / "clients" / client
        d.mkdir(parents=True)
        (d / "proposal.md").write_text(f"# {client}\n\n{ABOUT}\nEnd {client}.\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(workspace):
    return TestClient(create_app(workspace))


def scan(client, **params):
    r = client.get("/api/refactor/scan", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def payload(group, docs=None, name=None):
    occ = group["occurrences"]
    return {
        "path": "",
        "min_docs": 2,
        "min_chars": 80,
        "key": group["key"],
        "name": group["name"] if name is None else name,
        "documents": docs or [o["path"] for o in occ],
        "revisions": {o["path"]: o["revision"] for o in occ},
    }


def test_scan_reports_groups(client):
    data = scan(client)
    assert data["scanned"] == 3
    [g] = data["groups"]
    assert g["name"] == "about-blueshift"
    assert g["target"] == "clients/templates/about-blueshift.md"
    assert g["copies"] == 3
    assert {o["path"] for o in g["occurrences"]} == {f"clients/{c}/proposal.md" for c in "abc"}
    assert g["occurrences"][0]["line"] == 3
    assert "Blueshift is a consultancy" in g["text"]


def test_scan_folder_scope_and_validation(client):
    assert scan(client, path="clients/a")["groups"] == []
    assert client.get("/api/refactor/scan", params={"min_docs": 1}).status_code == 400
    assert (
        client.get("/api/refactor/scan", params={"path": "clients/a/proposal.md"}).status_code
        == 400
    )
    assert client.get("/api/refactor/scan", params={"path": "../x"}).status_code in {400, 404}


def test_apply_extracts_subset_and_keeps_snapshots(client, workspace):
    [g] = scan(client)["groups"]
    docs = [o["path"] for o in g["occurrences"]][:2]
    r = client.post("/api/refactor/apply", json=payload(g, docs, name="about-us"))
    assert r.status_code == 200, r.text
    assert r.json()["template"] == "clients/templates/about-us.md"
    assert (workspace / "clients/templates/about-us.md").read_text().startswith("## About")
    changed = {c["path"] for c in r.json()["changed"]}
    assert changed == set(docs)
    for path in docs:
        assert '{% include "about-us.md" %}' in (workspace / path).read_text()
        assert list((workspace / path).parent.glob(".editor-history/proposal.md/*.txt"))
    other = (set(o["path"] for o in g["occurrences"]) - set(docs)).pop()
    assert "Blueshift is a consultancy" in (workspace / other).read_text()


@pytest.mark.parametrize("name", ["", "Has Space", "../evil", ".hidden", "a/b"])
def test_apply_rejects_bad_names(client, name):
    [g] = scan(client)["groups"]
    assert client.post("/api/refactor/apply", json=payload(g, name=name)).status_code == 400


def test_apply_needs_two_documents_and_fresh_revisions(client, workspace):
    [g] = scan(client)["groups"]
    one = [g["occurrences"][0]["path"]]
    assert client.post("/api/refactor/apply", json=payload(g, one)).status_code == 400
    (workspace / g["occurrences"][0]["path"]).write_text(
        (workspace / g["occurrences"][0]["path"]).read_text() + "\nedited\n"
    )
    r = client.post("/api/refactor/apply", json=payload(g))
    assert r.status_code == 409
    assert "Changed on disk" in r.json()["detail"]["message"]
    assert not (workspace / "clients/templates").exists()


def test_apply_refuses_existing_template_and_stale_scan(client, workspace):
    [g] = scan(client)["groups"]
    (workspace / "clients/templates").mkdir()
    (workspace / "clients/templates/taken.md").write_text("x")
    assert client.post("/api/refactor/apply", json=payload(g, name="taken")).status_code == 409
    bad = payload(g)
    bad["key"] = "0" * 16
    assert client.post("/api/refactor/apply", json=bad).status_code == 409


def test_crlf_documents_stay_crlf(client, workspace):
    for c in "abc":
        p = workspace / f"clients/{c}/proposal.md"
        p.write_bytes(p.read_text().replace("\n", "\r\n").encode())
    [g] = scan(client)["groups"]
    assert client.post("/api/refactor/apply", json=payload(g)).status_code == 200
    raw = (workspace / "clients/a/proposal.md").read_bytes()
    assert b'{% include "about-blueshift.md" %}\r\n' in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_apply_into_chosen_parent_folder(client, workspace):
    [g] = scan(client)["groups"]
    body = payload(g)
    body["folder"] = "templates"
    r = client.post("/api/refactor/apply", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["template"] == "templates/about-blueshift.md"
    assert (workspace / "templates/about-blueshift.md").exists()
    from md_doc.renderer import render

    assert "Blueshift is a consultancy" in render(workspace / "clients/a/proposal.md")


def test_subset_defaults_to_its_own_closest_folder(client, workspace):
    (workspace / "clients/a/second.md").write_text(f"# s\n\n{ABOUT}")
    [g] = scan(client)["groups"]
    docs = ["clients/a/proposal.md", "clients/a/second.md"]
    r = client.post("/api/refactor/apply", json=payload(g, docs))
    assert r.status_code == 200, r.text
    assert r.json()["template"] == "clients/a/templates/about-blueshift.md"


@pytest.mark.parametrize(
    "folder", ["clients/a/templates", "clients/templates/sub", "other", "../x"]
)
def test_apply_rejects_unreachable_locations(client, folder):
    [g] = scan(client)["groups"]
    body = payload(g)
    body["folder"] = folder
    assert client.post("/api/refactor/apply", json=body).status_code in {400, 404}


def test_matches_existing_template_and_replaces_in_one_document(client, workspace):
    (workspace / "templates").mkdir()
    (workspace / "templates" / "about.md").write_text(ABOUT)
    (workspace / "solo.md").write_text(f"# Solo\n\n{ABOUT}")
    data = scan(client)
    existing = [g for g in data["groups"] if g["existing"]]
    assert len(existing) == 1
    g = existing[0]
    assert g["name"] == "about.md" and g["target"] == "templates/about.md"
    assert g["copies"] == 4  # solo.md and the three client proposals
    body = payload(g, ["solo.md"])
    body["name"] = ""
    r = client.post("/api/refactor/apply", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["existing"] and r.json()["template"] == "templates/about.md"
    assert '{% include "about.md" %}' in (workspace / "solo.md").read_text()
    assert (workspace / "templates/about.md").read_text() == ABOUT


def test_ignore_and_restore_persist_across_scans(client, workspace):
    [g] = scan(client)["groups"]
    assert g["ignored"] is False
    r = client.post(
        "/api/refactor/ignore", json={"key": g["key"], "ignored": True, "name": g["name"]}
    )
    assert r.status_code == 200
    assert scan(client)["groups"][0]["ignored"] is True
    assert (workspace / ".editor-ignored-matches.json").exists()
    client.post("/api/refactor/ignore", json={"key": g["key"], "ignored": False})
    assert scan(client)["groups"][0]["ignored"] is False
    assert (
        client.post("/api/refactor/ignore", json={"key": "../x", "ignored": True}).status_code
        == 400
    )


def test_scan_ignores_documents_linked_from_outside_the_workspace(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text(f"# Secret\n\n{ABOUT}\nOnly outside.\n", encoding="utf-8")
    workspace = tmp_path / "project"
    (workspace / ".git").mkdir(parents=True)
    for name in ("a", "b"):
        (workspace / f"{name}.md").write_text(
            f"# {name}\n\n{ABOUT}\nEnd {name}.\n", encoding="utf-8"
        )
    try:
        (workspace / "linked.md").symlink_to(outside / "secret.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")

    with TestClient(create_app(workspace)) as client:
        data = scan(client)

    paths = {o["path"] for g in data["groups"] for o in g["occurrences"]}
    assert paths == {"a.md", "b.md"}
