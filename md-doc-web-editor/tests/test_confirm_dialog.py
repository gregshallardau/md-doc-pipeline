"""A late close event from the previous dialog must not cancel a confirmation."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_stale_close_event_does_not_cancel_confirmation(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for asynchronous editor regression")
    source = (
        Path(__file__).resolve().parents[1] / "md_doc_web_editor/static/editor.js"
    ).read_text()
    function = "  function confirmDialog(" + source.split("  function confirmDialog(", 1)[1]
    function = function.split("  function persist()", 1)[0]
    script = (
        r"""
const assert = require('node:assert/strict');
const escape = (value) => value;
let node;
function dialog(title, body, actions) {
  const listeners = [];
  node = {
    open: true,
    actions,
    addEventListener(name, fn) { if (name === 'close') listeners.push(fn); },
    close() { node.open = false; listeners.forEach((fn) => fn()); },
    fireStaleClose() { listeners.forEach((fn) => fn()); },
  };
  return node;
}
"""
        + function
        + r"""
(async () => {
  const pending = confirmDialog('t', 'm', [
    {label: 'Cancel', value: false},
    {label: 'Go', value: true},
  ]);
  node.fireStaleClose();
  await new Promise((resolve) => setTimeout(resolve, 10));
  node.actions[1].run();
  assert.equal(await pending, true);

  const dismissed = confirmDialog('t', 'm', [{label: 'Go', value: true}]);
  node.close();
  assert.equal(await dismissed, null);
})();
"""
    )
    path = tmp_path / "confirm.js"
    path.write_text(script)
    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
