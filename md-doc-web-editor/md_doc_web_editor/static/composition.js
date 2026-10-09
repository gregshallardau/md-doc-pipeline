/* Editable source projection: included text keeps its own file and source offsets. */
(() => {
  const include = /\{%[-+]?\s*include\s+["']([^"']+)["'][^%]*[-+]?%\}/;
  class DocumentComposition {
    constructor(root, buffers) {
      this.root = root;
      this.buffers = buffers;
      this.expanded = new Map();
      this.build();
    }
    build() {
      this.text = "";
      this.segments = [];
      this.includes = [];
      let instanceSequence = 0;
      const append = (path, start, end, text, instance = null) => {
        if (!text) return;
        const previous = this.segments.at(-1);
        if (
          path &&
          previous?.path === path &&
          previous.instance === instance &&
          previous.sourceEnd === start
        ) {
          previous.end += text.length;
          previous.sourceEnd = end;
          this.text += text;
          return;
        }
        this.segments.push({
          path,
          instance,
          sourceStart: start,
          sourceEnd: end,
          start: this.text.length,
          end: this.text.length + text.length,
        });
        this.text += text;
      };
      const visit = (path, ancestors) => {
        if (ancestors.includes(path) || ancestors.length >= 16)
          throw new Error("A recursive template cannot be expanded here.");
        const instance = instanceSequence++;
        const raw = this.buffers.get(path).content;
        if (!raw && path !== this.root) {
          append(path, 0, 0, "\n", instance);
          return;
        }
        let offset = 0,
          start = 0;
        const occurrences = new Map();
        for (const line of raw.match(/[^\n]*\n|[^\n]+$/g) || []) {
          const match = line.match(include);
          if (match) {
            const occurrence = occurrences.get(match[1]) || 0;
            occurrences.set(match[1], occurrence + 1);
            const key = path + "\0" + match[1] + "\0" + occurrence;
            append(
              path,
              start,
              offset + line.length,
              raw.slice(start, offset + line.length),
              instance,
            );
            const entry = {
              key,
              path,
              name: match[1],
              sourceOffset: offset,
              sourceLine: raw.slice(0, offset).split("\n").length,
              offset: this.text.length - line.length,
              length: line.replace(/\n$/, "").length,
            };
            this.includes.push(entry);
            const child = this.expanded.get(key);
            if (child && this.buffers.has(child)) {
              entry.child = child;
              if (!this.text.endsWith("\n")) append(null, 0, 0, "\n");
              visit(child, [...ancestors, path]);
              if (!this.text.endsWith("\n")) append(null, 0, 0, "\n");
            }
            start = offset + line.length;
          }
          offset += line.length;
        }
        append(path, start, raw.length, raw.slice(start), instance);
      };
      visit(this.root, []);
      return this.text;
    }
    owner(offset, length = 0) {
      const segment =
        this.segments.find(
          (part) =>
            offset >= part.start &&
            offset < part.end &&
            offset + length <= part.end,
        ) || (offset === this.text.length ? this.segments.at(-1) : null);
      return segment?.path ? segment : null;
    }
    sourceEdits(changes) {
      const groups = new Map();
      for (const change of changes) {
        if (
          this.includes.some(
            (entry) =>
              entry.child &&
              change.rangeOffset < entry.offset + entry.length &&
              change.rangeOffset + change.rangeLength >= entry.offset,
          )
        )
          throw new Error(
            "Collapse this template before changing its include declaration.",
          );
        const part = this.owner(change.rangeOffset, change.rangeLength);
        if (!part)
          throw new Error(
            "Edit one source section at a time. Collapse templates to change an include.",
          );
        const start = Math.min(
          part.sourceEnd,
          part.sourceStart + change.rangeOffset - part.start,
        );
        const edit = {
          start,
          length: Math.max(
            0,
            Math.min(change.rangeLength, part.sourceEnd - start),
          ),
          text: change.text,
        };
        const occurrences = groups.get(part.path) || new Map();
        const list = occurrences.get(part.instance) || [];
        list.push(edit);
        occurrences.set(part.instance, list);
        groups.set(part.path, occurrences);
      }
      const edits = new Map();
      for (const [path, occurrences] of groups) {
        const unique = new Map();
        for (const list of occurrences.values())
          for (const edit of list) unique.set(JSON.stringify(edit), edit);
        const merged = [...unique.values()].sort((a, b) => b.start - a.start);
        const overlaps = merged.some(
          (edit, index) =>
            index > 0 && edit.start + edit.length > merged[index - 1].start,
        );
        if (!overlaps) {
          edits.set(path, merged);
          continue;
        }
        // Monaco may undo the original edit and its mirrored occurrences with
        // different minimal ranges. Accept them once if they yield the same source.
        const candidates = [...occurrences.values()].map((list) => {
          list.sort((a, b) => b.start - a.start);
          let value = this.buffers.get(path).content;
          for (const edit of list)
            value =
              value.slice(0, edit.start) +
              edit.text +
              value.slice(edit.start + edit.length);
          return { list, value };
        });
        if (
          !candidates.every(
            (candidate) => candidate.value === candidates[0].value,
          )
        )
          throw new Error(
            "Edit one occurrence of a shared template at a time.",
          );
        edits.set(path, candidates[0].list);
      }
      return edits;
    }
    location(path, line) {
      const raw = this.buffers.get(path)?.content;
      if (raw === undefined) return null;
      const offset = raw
        .split("\n")
        .slice(0, line - 1)
        .reduce((sum, text) => sum + text.length + 1, 0);
      const part = this.segments.find(
        (part) =>
          part.path === path &&
          offset >= part.sourceStart &&
          offset <= part.sourceEnd,
      );
      return part ? part.start + offset - part.sourceStart : null;
    }
  }
  window.DocumentComposition = DocumentComposition;
})();
