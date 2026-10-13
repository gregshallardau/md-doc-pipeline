"""Fit presets must follow page geometry in mixed-orientation previews."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_fit_presets_follow_page_changes_and_loaded_geometry():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the viewer regression")
    source = (
        Path(__file__).resolve().parents[1] / "md_doc_web_editor/static/viewer.js"
    ).read_text()
    source = "class DocumentViewer" + source.split("export class DocumentViewer", 1)[1]
    script = r"""
const assert = require('node:assert/strict');
const elements = new Map();
const $ = id => {
  if (!elements.has(id)) elements.set(id, {
    value: id === 'pdf-zoom' ? 'page-width' : 'single',
    querySelectorAll: () => [],
  });
  return elements.get(id);
};
const pdfjs = {AnnotationMode: {ENABLE: 1}};
const base = '';
class EventBus {
  constructor() { this.listeners = {}; }
  on(name, callback) { this.listeners[name] = callback; }
  dispatch(name, event) { this.listeners[name]?.(event); }
}
class PDFViewer {
  constructor() {
    this.currentPageNumber = 1;
    this.widths = [600, 850, 600];
    this.heights = [850, 600, 850];
    this.assignments = 0;
  }
  set currentScaleValue(value) {
    this.assignments++;
    this.preset = value;
    const index = this.currentPageNumber - 1;
    this.scale = value === 'page-width' ? 1000 / this.widths[index]
      : value === 'page-fit' ? Math.min(1000 / this.widths[index], 700 / this.heights[index])
      : Number(value);
  }
  update() {}
}
const components = {
  EventBus, PDFViewer,
  PDFLinkService: class {setViewer() {}},
  PDFFindController: class {},
};
const ResizeObserver = class {observe() {}};
let nextFrame = 0;
const frames = new Map();
const requestAnimationFrame = callback => { frames.set(++nextFrame, callback); return nextFrame; };
const cancelAnimationFrame = id => frames.delete(id);
const flush = () => {
  const pending = [...frames.values()]; frames.clear();
  pending.forEach(callback => callback());
};
"""
    script += source
    script += r"""
const preview = new DocumentViewer(() => {});
preview.document = {numPages: 3};
for (const preset of ['page-width', 'page-fit']) {
  $('pdf-zoom').value = preset;
  preview.viewer.currentPageNumber = 1;
  preview.resize();
  const portraitScale = preview.viewer.scale;
  preview.viewer.currentPageNumber = 2;
  preview.eventBus.dispatch('pagechanging', {pageNumber: 2});
  // Repeated events coalesce, and fitting waits for the updated scroll location.
  preview.eventBus.dispatch('pagechanging', {pageNumber: 2});
  assert.equal(frames.size, 1);
  assert.equal(preview.viewer.scale, portraitScale);
  flush();
  assert.equal(preview.viewer.preset, preset);
  assert.ok(preview.viewer.scale * 850 <= 1000);
  preview.viewer.currentPageNumber = 3;
  preview.eventBus.dispatch('pagechanging', {pageNumber: 3});
  flush();
  assert.equal(preview.viewer.scale, portraitScale);
}
$('pdf-zoom').value = 'page-width';
preview.viewer.currentPageNumber = 2;
preview.viewer.widths[1] = 600; // Placeholder inherited from the first page.
preview.resize();
preview.viewer.widths[1] = 850;
preview.eventBus.dispatch('pagesloaded', {});
flush();
assert.equal(preview.viewer.scale, 1000 / 850);
$('pdf-zoom').value = '1.5';
preview.resize();
const assignments = preview.viewer.assignments;
preview.eventBus.dispatch('pagechanging', {pageNumber: 3});
preview.eventBus.dispatch('pagesloaded', {});
flush();
assert.equal(preview.viewer.assignments, assignments);
// A user selecting a fixed zoom before the scheduled refit keeps that zoom.
$('pdf-zoom').value = 'page-width';
preview.scheduleFit();
$('pdf-zoom').value = '1.5';
flush();
assert.equal(preview.viewer.assignments, assignments);
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
