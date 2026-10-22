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
