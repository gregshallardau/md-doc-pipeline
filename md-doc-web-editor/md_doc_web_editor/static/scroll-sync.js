/* Content anchors connect source lines to rendered PDF text, independent of pagination. */
export function normalizeText(text) {
  return text.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
}

export async function indexPdfText(document) {
  let text = "";
  const items = [], pages = [];
  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber++) {
    const page = await document.getPage(pageNumber);
    const viewport = page.getViewport({scale: 1});
    pages.push(viewport);
    const content = await page.getTextContent();
    for (const item of content.items) {
      if (!item.str) continue;
      const normalized = normalizeText(item.str);
      if (!normalized) continue;
      const [, y] = viewport.convertToViewportPoint(item.transform[4], item.transform[5]);
      items.push({offset: text.length, page: pageNumber,
        top: Math.max(0, Math.min(1, (y - (item.height || 0)) / viewport.height))});
      text += normalized;
    }
  }
  return {text, items, pages};
}

export function sourceAnchors(source, index) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const anchors = [];
  let cursor = 0, itemIndex = 0, frontmatter = lines[0]?.trim() === "---";
  let comment = false;
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    if (frontmatter) {
      if (i > 0 && /^(---|\.\.\.)\s*$/.test(line)) frontmatter = false;
      continue;
    }
    // Comments and metadata are source-only; do not anchor them to PDF text.
    line = line.replace(/<!--[\s\S]*?-->/g, "");
    if (comment) {
      const end = line.indexOf("-->");
      if (end < 0) continue;
      line = line.slice(end + 3);
      comment = false;
    }
    const start = line.indexOf("<!--");
    if (start >= 0) { line = line.slice(0, start); comment = true; }
    if (/^\s*(`{3,}|~{3,})/.test(line)) continue;
    line = line
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/<[^>]*>/g, "")
      .replace(/^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)/, "");
    // Template variables and form declarations do not appear verbatim in output.
    const phrases = line.split(/\{\{.*?\}\}|\{%.*?%\}|\?\[.*?\]|\[\[.*?\]\]/)
      .map(normalizeText).filter(text => text.length >= 6);
    let match = null;
    for (const phrase of phrases) {
      const needle = phrase.slice(0, 64);
      const offset = index.text.indexOf(needle, cursor);
      if (offset >= 0 && (!match || offset < match.offset)) match = {offset, needle};
    }
    if (!match) continue;
    while (itemIndex + 1 < index.items.length && index.items[itemIndex + 1].offset <= match.offset)
      itemIndex++;
    const item = index.items[itemIndex];
    if (!item) continue;
    anchors.push({line: i + 1, page: item.page, top: item.top});
    cursor = match.offset + match.needle.length;
  }
  return anchors;
}

export function locateSourceLine(anchors, line) {
  if (!anchors.length) return null;
  let low = 0, high = anchors.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (anchors[mid].line <= line) low = mid + 1;
    else high = mid;
  }
  const before = anchors[Math.max(0, low - 1)], after = anchors[low];
  if (!after || line <= before.line) return before;
  const fraction = (line - before.line) / (after.line - before.line);
  const start = before.page - 1 + before.top;
  const end = after.page - 1 + after.top;
  // Text columns and tables can have non-monotonic vertical positions.
  if (end < start) return before;
  const position = start + (end - start) * fraction;
  return {page: Math.floor(position) + 1, top: position % 1};
}
