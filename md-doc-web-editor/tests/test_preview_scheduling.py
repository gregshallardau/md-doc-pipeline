"""Exercise preview scheduling with a slow backend and changing drafts."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_long_preview_coalesces_edits_and_manual_refresh_replaces_it():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the browser scheduling regression")
    source = (
        Path(__file__).resolve().parents[1] / "md_doc_web_editor/static/editor.js"
    ).read_text()
    render = source.split("  async function renderPreview(", 1)[1].split(
        "  function renderDiagnostics()", 1
    )[0]
    script = "async function renderPreview(" + render
    script += r"""
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const crypto = {randomUUID};
const state = {pinned: 'long.md', revision: 1, auto: true};
const node = {replaceChildren() {}};
const $ = () => node;
const buffers = () => ({'long.md': 'revision ' + state.revision});
const setRenderState = () => {};
const renderInspector = () => {};
const renderDiagnostics = () => {};
const icon = () => {};
let scheduled = 0;
const schedulePreview = () => scheduled++;
let requests = [];
let completions = [];
async function api(path, options = {}) {
  requests.push({path, options});
  if (options.method === 'DELETE') return {};
  return new Promise(resolve => completions.push(resolve));
}
(async () => {
  const first = renderPreview();
  assert.equal(requests.length, 1);
  state.revision++;
  await renderPreview();
  state.revision++;
  await renderPreview();
  assert.equal(requests.length, 1, 'automatic edits must not cancel or restart');
  completions.shift()({id: 'first', state: 'succeeded', artifact: 'old.pdf'});
  await first;
  assert.equal(scheduled, 1, 'all edits become one follow-up');
  assert.equal(state.previewRunning, null);
  assert.equal(state.artifact, undefined, 'stale output must not be published');

  const second = renderPreview();
  await new Promise(resolve => setImmediate(resolve));
  const secondRequest = requests.findLast(r => r.options.method === 'POST');
  assert.equal(JSON.parse(secondRequest.options.body).buffers['long.md'], 'revision 3');
  const manual = renderPreview(true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.filter(r => r.options.method === 'POST').length, 3);
  completions.shift()({id: 'second', state: 'succeeded'});
  await second;
  assert.ok(state.previewRunning, 'obsolete completion must not clear the manual job');
  completions.shift()({id: 'manual', state: 'cancelled'});
  await manual;
  assert.equal(state.previewRunning, null);
  assert.equal(scheduled, 1);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
