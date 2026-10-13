"""Content-linked scrolling uses PDF text anchors rather than document proportions."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_source_anchors_track_content_and_interpolate_across_pages():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the linked-scroll regression")
    source = (
        (Path(__file__).resolve().parents[1] / "md_doc_web_editor/static/scroll-sync.js")
        .read_text()
        .replace("export ", "")
    )
    script = source + r"""
const assert = require('node:assert/strict');
(async () => {
  const pdf = {
    numPages: 3,
    async getPage(page) {
      const width = page === 2 ? 850 : 600;
      const height = page === 2 ? 600 : 850;
      return {
        getViewport: () => ({width, height, convertToViewportPoint: (x, y) => [x, height-y]}),
        async getTextContent() {
          const texts = [
            ['A Document Title'],
            ['Introductory paragraph.', 'Wide section heading', 'Landscape content in a ', 'wrapped paragraph.'],
            ['Repeated heading', 'Final paragraph.', 'Repeated heading', 'Second final paragraph.'],
          ][page-1];
          return {items: texts.map((str, i) => ({str, height: 12, transform: [1,0,0,1,40,height-60-i*30]}))};
        },
      };
    },
  };
  const index = await indexPdfText(pdf);
  const markdown = [
    '---', 'title: Final paragraph.', '---', '# A Document Title', '',
    '<!-- Final paragraph. -->', 'Introductory **paragraph**.', '',
    '<!-- sectionbreak: landscape -->', '## Wide section heading', '',
    'Landscape content in a wrapped paragraph.', '',
    '{% include "not-in-output.md" %}', '<!--', 'Final paragraph.', '-->',
    '## Repeated heading', 'Final [paragraph](https://example.com).',
    '## Repeated heading', 'Second final paragraph.',
  ].join('\n');
  const anchors = sourceAnchors(markdown, index);
  assert.deepEqual(anchors.map(a => a.line), [4,7,10,12,18,19,20,21]);
  assert.deepEqual(anchors.map(a => a.page), [1,2,2,2,3,3,3,3]);
  assert.ok(anchors[6].top > anchors[4].top); // Repeated headings keep their order.
  assert.equal(locateSourceLine(anchors, 1).page, 1);
  assert.equal(locateSourceLine(anchors, 12).page, 2);
  const middle = locateSourceLine(anchors, 15);
  const start = anchors[3].page-1 + anchors[3].top;
  const end = anchors[4].page-1 + anchors[4].top;
  assert.ok(middle.page-1 + middle.top > start);
  assert.ok(middle.page-1 + middle.top < end);
  assert.equal(locateSourceLine(anchors, 999).page, 3);
  assert.equal(locateSourceLine([], 1), null);
  assert.deepEqual(sourceAnchors('![Picture](asset.png)\n?[text: name]\n{% include "file.md" %}', index), []);
  assert.equal(normalizeText('CAFÉ — A ﬁne\nparagraph!'), 'caféafineparagraph');
})().catch(error => {console.error(error); process.exit(1);});
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_viewer_scroll_ignores_superseded_and_cancelled_requests():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the linked-scroll regression")
    static = Path(__file__).resolve().parents[1] / "md_doc_web_editor/static"
    source = (static / "scroll-sync.js").read_text().replace("export ", "")
    viewer = (static / "viewer.js").read_text()
    source += "\nclass DocumentViewer" + viewer.split("export class DocumentViewer", 1)[1]
    script = source + r"""
const assert = require('node:assert/strict');
(async () => {
  const preview = Object.create(DocumentViewer.prototype);
  preview.document = {};
  preview.sourceSyncSequence = 0;
  const scrolls = [];
  preview.viewer = {scrollPageIntoView: target => scrolls.push(target)};
  const index = {
    text: 'firstparagraphsecondparagraph',
    items: [{offset:0, page:1, top:.1}, {offset:14, page:2, top:.4}],
    pages: [1,2].map(() => ({height:1000, convertToPdfPoint: (x,y) => [x,1000-y]})),
  };
  let finish;
  preview.textIndex = new Promise(resolve => {finish = resolve;});
  const first = preview.scrollToSource('First paragraph\nSecond paragraph', 1);
  const second = preview.scrollToSource('First paragraph\nSecond paragraph', 2);
  finish(index);
  await Promise.all([first, second]);
  assert.equal(scrolls.length, 1);
  assert.equal(scrolls[0].pageNumber, 2);
  assert.deepEqual(scrolls[0].destArray, [null, {name:'XYZ'}, 0, 600, null]);
  const cancelled = preview.scrollToSource('First paragraph\nSecond paragraph', 1);
  preview.cancelSourceScroll();
  await cancelled;
  assert.equal(scrolls.length, 1);
  const stale = preview.scrollToSource('First paragraph\nSecond paragraph', 1);
  preview.document = {};
  await stale;
  assert.equal(scrolls.length, 1);
})().catch(error => {console.error(error); process.exit(1);});
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
