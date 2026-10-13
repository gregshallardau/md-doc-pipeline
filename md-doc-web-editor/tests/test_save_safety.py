"""Data-loss regressions: conditional saves, durable recovery, and async races."""

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from md_doc_web_editor.server import create_app
from md_doc_web_editor.snapshots import revision


def test_existing_file_requires_revision_and_history_survives_restart(tmp_path):
    source = tmp_path / "doc.md"
    original = b"# Original\r\nNon-ASCII: \xc3\xa9\r\n"
    source.write_bytes(original)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/file?path=doc.md").headers["cache-control"] == "no-store"
        for supplied in ({}, {"revision": None}, {"revision": "stale"}):
            result = client.put("/api/file", json={"path": "doc.md", "content": "lost", **supplied})
            assert result.status_code == 409
            assert source.read_bytes() == original
        result = client.put(
            "/api/file",
            json={"path": "doc.md", "content": "Saved draft", "revision": revision(original)},
        )
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
    folder = tmp_path / ".editor-history/doc.md"
    assert (folder / (revision(original) + ".txt")).read_bytes() == original
    assert (folder / (revision(b"Saved draft") + ".txt")).read_bytes() == b"Saved draft"
    with TestClient(create_app(tmp_path)) as client:
        assert folder.exists()
        assert ".editor-history" not in client.get("/api/tree").text


def test_history_failure_leaves_source_untouched(tmp_path, monkeypatch):
    from md_doc_web_editor import snapshots

    source = tmp_path / "doc.md"
    source.write_text("Original")

    def fail(*args):
        raise OSError("History disk full")

    monkeypatch.setattr(snapshots, "preserve_revision", fail)
    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        response = client.put(
            "/api/file",
            json={"path": "doc.md", "content": "New", "revision": revision(b"Original")},
        )
        assert response.status_code == 500
        assert source.read_text() == "Original"


def test_actual_browser_save_and_polling_functions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for asynchronous editor regression")
    source = (
        Path(__file__).resolve().parents[1] / "md_doc_web_editor/static/editor.js"
    ).read_text()
    sections = [
        ("  async function closeFile(", "  async function save("),
        ("  async function save(", "  function compareBuffer("),
        ("  async function checkChanges()", "  async function init()"),
        ("  function persist()", "  function updateSaveState()"),
    ]
    script = "\n".join(
        start + source.split(start, 1)[1].split(end, 1)[0] for start, end in sections
    )
    script += r"""
const assert = require('node:assert/strict');
const state = {buffers: new Map(), active: 'doc.md', recoveryDrafts: {}, changeSignature: 'old', revision: 0};
const dirty = b => b.content !== b.saved;
const projection = () => null;
const updateSaveState = () => {};
const renderTree = () => {};
const toast = () => {};
const schedulePreview = () => {};
const loadTree = async () => {};
const confirmDialog = async () => 'save';
const document = {hidden: false};
const $ = () => ({classList: {remove() {}, add() {}}});
const recoveryJournalName = 'recovery:test';
const recoveryJournal = {};
const storage = {};
const store = (name, value) => storage[name] = JSON.parse(JSON.stringify(value));
let api;
(async () => {
  const b = {path: 'doc.md', saved: 'baseline', content: 'draft', revision: 'r1'};
  state.buffers.set(b.path, b);
  let finish;
  api = () => new Promise(resolve => finish = resolve);
  const saving = save(b.path);
  b.content = 'typed while saving';
  finish({revision: 'r2'});
  assert.equal(await saving, false);
  assert.equal(b.saved, 'draft');
  assert.equal(b.content, 'typed while saving');
  assert.equal(storage.drafts[b.path].content, b.content);
  assert.equal(storage[recoveryJournalName][b.path].content, b.content);
  b.saved = b.content;
  persist();
  assert.deepEqual(storage.drafts, {});
  assert.equal(storage[recoveryJournalName][b.path].content, 'typed while saving');

  // GET started before PUT completion must not replace newly saved work.
  b.saved = 'baseline'; b.content = 'draft'; b.revision = 'r1';
  let fetched;
  api = async url => url === '/api/changes' ? {signature: 'new'} : new Promise(resolve => fetched = resolve);
  const polling = checkChanges();
  while (!fetched) await new Promise(resolve => setImmediate(resolve));
  b.saved = b.content; b.revision = 'r2';
  fetched({content: 'baseline', revision: 'r1'});
  await polling;
  assert.equal(b.content, 'draft', 'stale GET must not discard successful save');
  assert.equal(state.pendingFileRefresh, true, 'skipped refresh must be retried');

  // Retry even with the same disk signature. Edits during GET stay dirty.
  b.saved = b.content; b.revision = 'r2'; fetched = null;
  const nextPoll = checkChanges();
  while (!fetched) await new Promise(resolve => setImmediate(resolve));
  b.content = 'new unsaved edits';
  fetched({content: 'VS Code edits', revision: 'r3'});
  await nextPoll;
  assert.equal(b.content, 'new unsaved edits');
  assert.equal(b.saved, 'draft');

  // The initial poll must refresh files opened before its signature was read.
  state.changeSignature = null;
  b.content = b.saved;
  fetched = null;
  const initialPoll = checkChanges();
  while (!fetched) await new Promise(resolve => setImmediate(resolve));
  fetched({content: 'initial external edit', revision: 'initial'});
  await initialPoll;
  assert.equal(b.content, 'initial external edit');

  // Save & close must not dispose text typed while the PUT was in flight.
  b.content = 'close draft';
  api = () => new Promise(resolve => finish = resolve);
  const closing = closeFile(b.path);
  await new Promise(resolve => setImmediate(resolve));
  b.content = 'typed while closing';
  finish({revision: 'r4'});
  await closing;
  assert.equal(state.buffers.get(b.path), b);
  assert.equal(b.content, 'typed while closing');

  // A save in flight also prevents an independently requested tab close.
  b.saving = true;
  await closeFile(b.path);
  assert.equal(state.buffers.get(b.path), b);
  b.saving = false;
})().catch(error => {console.error(error); process.exitCode = 1});
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
