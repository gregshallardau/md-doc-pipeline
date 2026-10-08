/* Document studio. The Python pipeline owns output; this client owns buffers and interaction. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const icons = {
    folder: "M3 7h6l2 2h10v11H3Z M3 7V4h6l2 3",
    file: "M5 3h9l5 5v13H5Z M14 3v6h5 M9 13h6 M9 17h5",
    files: "M8 3h10v14H8Z M5 7H3v14h11v-2",
    search: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14 M15 15l6 6",
    sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M12 2v2 M12 20v2 M2 12h2 M20 12h2 M5 5l1 1 M18 18l1 1 M5 19l1-1 M18 6l1-1",
    help: "M9 8a3 3 0 0 1 6 0c0 2-3 2-3 5 M12 17h.01 M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20",
    download: "M12 3v12 M7 10l5 5 5-5 M4 17v4h16v-4",
    upload: "M12 17V5 M7 10l5-5 5 5 M4 17v4h16v-4",
    "chevron-down": "m7 9 5 5 5-5",
    "chevron-right": "m9 6 6 6-6 6",
    "chevron-left": "m15 6-6 6 6 6",
    list: "M9 6h12 M9 12h12 M9 18h12 M3 6h.01 M3 12h.01 M3 18h.01",
    git: "M6 3v12a4 4 0 0 0 4 4h6 M18 5v9 M6 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4 M18 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4 M18 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4",
    maximize: "M8 3H3v5 M16 3h5v5 M3 16v5h5 M21 16v5h-5",
    settings:
      "M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6",
    "file-plus": "M14 3H5v18h14V8Z M14 3v5h5 M12 12v6 M9 15h6",
    refresh:
      "M20 8a8 8 0 0 0-14-3L3 8 M3 3v5h5 M4 16a8 8 0 0 0 14 3l3-3 M21 21v-5h-5",
    more: "M5 12h.01 M12 12h.01 M19 12h.01",
    shield: "m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6Z M8 12l3 3 5-6",
    save: "M4 3h13l4 4v14H3V3Z M7 3v7h9V3 M7 21v-7h10v7",
    heading: "M5 4v16 M19 4v16 M5 12h14",
    link: "m10 14 4-4 M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0 M16 8l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0",
    table: "M3 3h18v18H3Z M3 9h18 M9 3v18 M3 15h18",
    plus: "M12 5v14 M5 12h14",
    columns: "M3 4h18v16H3Z M12 4v16",
    sliders:
      "M5 3v5 M5 12v9 M12 3v10 M12 17v4 M19 3v3 M19 10v11 M2 8h6 M9 17h6 M16 6h6",
    panel: "M3 4h18v16H3Z M9 4v16",
    printer: "M6 9V3h12v6 M6 17H3V9h18v8h-3 M6 14h12v7H6Z M17 12h.01",
    close: "m6 6 12 12 M18 6 6 18",
    check: "m5 12 4 4 10-10",
    alert: "M12 3 2 21h20Z M12 9v5 M12 18h.01",
    code: "m8 7-5 5 5 5 M16 7l5 5-5 5 M14 4l-4 16",
    image: "M3 3h18v18H3Z m3 18 5-6 4 4 3-3 3 5 M8 9h.01",
    moon: "M20 14A9 9 0 0 1 10 4a9 9 0 1 0 10 10",
    undo: "M3 8h11a7 7 0 0 1 0 14 M3 8l5-5 M3 8l5 5",
    trash: "M3 6h18 M9 6V3h6v3 M6 6v15h12V6 M10 10v7 M14 10v7",
    copy: "M8 8h13v13H8Z M16 8V3H3v13h5",
    edit: "m15 3 6 6-12 12H3v-6Z M12 6l6 6",
    clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20 M12 6v6l4 2",
  };
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("icon");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", icons[name] || icons.file);
    svg.append(path);
    return svg;
  }
  function hydrate(root = document) {
    root.querySelectorAll("[data-icon]").forEach((el) => {
      if (!el.childElementCount) el.append(icon(el.dataset.icon));
    });
  }
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function escape(text) {
    const node = document.createElement("span");
    node.textContent = String(text ?? "");
    return node.innerHTML;
  }
  const state = {
    workspace: null,
    session: null,
    client: crypto.randomUUID(),
    files: [],
    tree: [],
    buffers: new Map(),
    active: null,
    pinned: null,
    editor: null,
    fallback: null,
    view: null,
    inspection: null,
    inspectTab: "properties",
    revision: 0,
    artifact: null,
    artifactPath: null,
    job: null,
    timer: null,
    auto: true,
    nav: "files",
    layout: "split",
    navWidth: 240,
    editRatio: 0.5,
    horizontalRatio: 0.5,
    mode: "source",
    appearance: "system",
    connected: true,
    error: null,
    log: "",
    changeSignature: null,
    commands: [],
    commandIndex: 0,
    writeChunks: [],
    loadingFiles: new Map(),
    recoveryDrafts: {},
    openSequence: 0,
  };
  let monacoReady;
  const current = () => state.buffers.get(state.active);
  const dirty = (buffer) => buffer.content !== buffer.saved;
  function key(name) {
    return `md-doc-studio:${state.workspace?.workspace || "pending"}:${name}`;
  }
  function readStorage(name, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key(name))) ?? fallback;
    } catch {
      return fallback;
    }
  }
  function store(name, value) {
    try {
      localStorage.setItem(key(name), JSON.stringify(value));
    } catch {
      if (!state.storageWarning) {
        state.storageWarning = true;
        toast(
          "Draft recovery storage is unavailable. Save your changes to disk.",
          true,
        );
      }
    }
  }
  const selectedWorkspace = new URLSearchParams(location.search).get(
    "workspace",
  );
  function workspaceUrl(url) {
    if (!selectedWorkspace) return url;
    return (
      url +
      (url.includes("?") ? "&" : "?") +
      "workspace=" +
      encodeURIComponent(selectedWorkspace)
    );
  }
  async function api(url, options = {}) {
    if (url !== "/api/workspaces") url = workspaceUrl(url);
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Editor-Token": state.session || "",
        ...options.headers,
      },
    });
    let data;
    try {
      data = await response.json();
    } catch {
      data = { detail: `Request failed (${response.status})` };
    }
    if (!response.ok) {
      const error = new Error(
        typeof data.detail === "string"
          ? data.detail
          : data.detail?.message || `Request failed (${response.status})`,
      );
      error.status = response.status;
      error.detail = data.detail;
      throw error;
    }
    if (data.artifact) data.artifact.url = workspaceUrl(data.artifact.url);
    return data;
  }
  function toast(message, error = false, action = null) {
    const node = el("div", "toast" + (error ? " error" : ""));
    node.append(icon(error ? "alert" : "check"), el("p", null, message));
    if (action) {
      const button = el("button", null, action.label);
      button.onclick = () => {
        action.run();
        node.remove();
      };
      node.append(button);
    }
    const close = el("button", "icon-button small");
    close.setAttribute("aria-label", "Dismiss");
    close.append(icon("close"));
    close.onclick = () => node.remove();
    node.append(close);
    $("toast-stack").append(node);
    setTimeout(() => node.remove(), action ? 18000 : 6000);
  }
  function dialog(title, body, actions = [], wide = false) {
    const node = $("form-dialog");
    if (node.open) node.close();
    node.classList.toggle("wide-dialog", wide);
    $("dialog-title").textContent = title;
    $("dialog-body").replaceChildren();
    if (typeof body === "string") $("dialog-body").innerHTML = body;
    else $("dialog-body").append(body);
    $("dialog-actions").replaceChildren();
    for (const item of actions) {
      const button = el(
        "button",
        "button " +
          (item.primary ? "primary" : "") +
          (item.danger ? " danger" : ""),
        item.label,
      );
      button.type = "button";
      button.onclick = async () => {
        button.disabled = true;
        try {
          await item.run(node);
        } catch (error) {
          toast(error.message, true);
        } finally {
          button.disabled = false;
        }
      };
      $("dialog-actions").append(button);
    }
    hydrate(node);
    node.showModal();
    setTimeout(() => node.querySelector("input,textarea,select")?.focus(), 0);
    return node;
  }
  function confirmDialog(title, message, options) {
    return new Promise((resolve) => {
      let settled = false;
      const node = dialog(
        title,
        `<p>${escape(message)}</p>`,
        options.map((option) => ({
          ...option,
          run: () => {
            settled = true;
            node.close();
            resolve(option.value);
          },
        })),
      );
      node.addEventListener(
        "close",
        () => {
          if (!settled) resolve(null);
        },
        { once: true },
      );
    });
  }
  function persist() {
    store("session", {
      paths: [...state.buffers.keys()],
      active: state.active,
      pinned: state.pinned,
    });
    const drafts = { ...state.recoveryDrafts };
    for (const [path, buffer] of state.buffers) {
      if (dirty(buffer))
        drafts[path] = {
          content: buffer.content,
          saved: buffer.saved,
          revision: buffer.revision,
        };
    }
    store("drafts", drafts);
    updateSaveState();
  }
  function updateSaveState() {
    const count = [...state.buffers.values()].filter(dirty).length;
    const buffer = current();
    $("md-doc-save-btn").disabled =
      !buffer || !dirty(buffer) || !!buffer.saving;
    $("save-status").textContent = count
      ? `${count} unsaved ${count === 1 ? "file" : "files"}`
      : "All changes saved";
    $("editor-word-count").textContent =
      `${buffer?.content.trim().split(/\s+/).filter(Boolean).length || 0} words`;
    renderTabs();
    document.title =
      (buffer
        ? (dirty(buffer) ? "• " : "") + buffer.path.split("/").pop() + " · "
        : "") + "md-doc studio";
  }
  function language(buffer) {
    return buffer.type === "css"
      ? "css"
      : buffer.type === "meta"
        ? "mddoc-yaml"
        : "mddoc-markdown";
  }
  function sourceValue(value) {
    if (state.editor) {
      const model = current()?.model;
      if (model)
        model.pushEditOperations(
          [],
          [{ range: model.getFullModelRange(), text: value }],
          () => null,
        );
    } else if (state.fallback) {
      state.fallback.value = value;
      changed(value);
    }
  }
  function changed(value) {
    const buffer = current();
    if (!buffer) return;
    buffer.content = value;
    state.revision++;
    persist();
    renderOutline();
    schedulePreview();
  }
  function initMonaco() {
    return new Promise((resolve) => {
      if (typeof window.require !== "function") {
        fallback();
        resolve();
        return;
      }
      window.require.config({
        paths: {
          vs: new URL(
            "/static/vendor/monaco-editor-0.52.2/min/vs",
            location.href,
          ).href,
        },
      });
      let settled = false;
      const done = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      window.require(
        ["vs/editor/editor.main"],
        () => {
          try {
            window.registerMdDocLanguages?.(monaco);
            state.editor = monaco.editor.create($("md-doc-monaco"), {
              value: "",
              language: "mddoc-markdown",
              theme: "mddoc-light",
              fontSize: 13,
              fontFamily:
                '"SFMono-Regular",Consolas,"Liberation Mono",monospace',
              lineHeight: 23,
              minimap: { enabled: false },
              wordWrap: "on",
              scrollBeyondLastLine: false,
              padding: { top: 22, bottom: 20 },
              automaticLayout: true,
              renderLineHighlight: "gutter",
              occurrencesHighlight: "off",
              smoothScrolling: true,
              roundedSelection: false,
              overviewRulerBorder: false,
              lineNumbersMinChars: 3,
              scrollbar: {
                verticalScrollbarSize: 7,
                horizontalScrollbarSize: 7,
              },
            });
            state.editor.onDidChangeModelContent(() => {
              if (!state.switching) changed(state.editor.getValue());
            });
            state.editor.onDidChangeCursorPosition((event) => {
              $("editor-position").textContent =
                `Ln ${event.position.lineNumber}, Col ${event.position.column}`;
            });
            state.editor.addCommand(
              monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
              () => save(),
            );
            state.editor.addCommand(
              monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyB,
              () => insert("bold"),
            );
            state.editor.addCommand(
              monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyI,
              () => insert("italic"),
            );
            applyAppearance();
            done();
          } catch (error) {
            fallback();
            done();
            toast("Source editor is using the local text fallback.", true);
          }
        },
        () => {
          fallback();
          done();
        },
      );
      setTimeout(() => {
        if (!settled) {
          fallback();
          done();
        }
      }, 12000);
    });
  }
  function fallback() {
    if (state.editor) return;
    const input = el("textarea", "md-doc-local-editor");
    input.setAttribute("aria-label", "Document source");
    input.spellcheck = false;
    input.oninput = () => changed(input.value);
    $("md-doc-monaco").replaceChildren(input);
    state.fallback = input;
  }
  async function loadTree() {
    const result = await api("/api/tree");
    state.tree = result.tree;
    state.files = [];
    const flatten = (nodes) =>
      nodes.forEach((node) => {
        if (node.type === "dir") flatten(node.children);
        else state.files.push(node);
      });
    flatten(result.tree);
    renderTree();
  }
  function renderTree() {
    const filter = $("file-filter").value.toLowerCase();
    $("md-doc-tree").replaceChildren();
    const build = (nodes) => {
      const list = el("ul", "tree-list");
      for (const node of nodes) {
        if (node.type === "dir") {
          const children = build(node.children);
          if (filter && !children.childElementCount) continue;
          const item = el("li");
          const details = el("details", "tree-folder");
          details.open =
            !!filter || readStorage("folders", []).includes(node.path);
          const summary = el("summary");
          const chevron = icon("chevron-down");
          chevron.classList.add("chevron");
          summary.append(chevron, icon("folder"), el("span", null, node.name));
          summary.title = node.path;
          details.append(summary, children);
          details.ontoggle = () => {
            if (filter) return;
            const folders = new Set(readStorage("folders", []));
            details.open ? folders.add(node.path) : folders.delete(node.path);
            store("folders", [...folders]);
          };
          item.append(details);
          list.append(item);
        } else {
          if (filter && !node.path.toLowerCase().includes(filter)) continue;
          const item = el("li");
          const button = el(
            "button",
            "tree-file " +
              node.type +
              (node.path === state.active ? " active" : ""),
          );
          button.dataset.path = node.path;
          button.title = node.path;
          button.append(
            icon(
              node.type === "css"
                ? "code"
                : node.type === "meta"
                  ? "settings"
                  : "file",
            ),
            el("span", "file-name", node.name),
          );
          if (
            state.buffers.has(node.path) &&
            dirty(state.buffers.get(node.path))
          )
            button.append(el("span", "dirty-dot"));
          button.onclick = () => openFile(node.path);
          button.oncontextmenu = (event) => {
            event.preventDefault();
            fileActions(node.path);
          };
          item.append(button);
          list.append(item);
        }
      }
      return list;
    };
    $("md-doc-tree").append(build(state.tree));
  }
  async function openFile(path, line = null) {
    const sequence = ++state.openSequence;
    await monacoReady;
    if (!state.buffers.has(path)) {
      if (state.loadingFiles.has(path)) await state.loadingFiles.get(path);
      else {
        const loading = (async () => {
          const data = await api("/api/file?path=" + encodeURIComponent(path));
          const draft = state.recoveryDrafts[path];
          delete state.recoveryDrafts[path];
          const buffer = {
            ...data,
            saved: data.content,
            model: null,
            viewState: null,
          };
          if (draft) {
            buffer.content = draft.content;
            buffer.saved = draft.saved;
            buffer.revision = draft.revision;
            toast("Recovered an unsaved draft: " + path, false, {
              label: "Compare",
              run: () => compareBuffer(buffer, data),
            });
          }
          state.buffers.set(path, buffer);
        })();
        state.loadingFiles.set(path, loading);
        try {
          await loading;
        } finally {
          state.loadingFiles.delete(path);
        }
      }
    }
    if (sequence !== state.openSequence) return state.buffers.get(path);
    const previous = current();
    if (previous && state.editor)
      previous.viewState = state.editor.saveViewState();
    state.active = path;
    const buffer = current();
    state.switching = true;
    if (state.editor) {
      if (!buffer.model)
        buffer.model = monaco.editor.createModel(
          buffer.content,
          language(buffer),
          monaco.Uri.parse("inmemory://workspace/" + encodeURI(path)),
        );
      state.editor.setModel(buffer.model);
      if (buffer.viewState) state.editor.restoreViewState(buffer.viewState);
      if (line) {
        state.editor.setPosition({ lineNumber: line, column: 1 });
        state.editor.revealLineInCenter(line);
      }
      state.editor.focus();
    } else if (state.fallback) state.fallback.value = buffer.content;
    state.switching = false;
    $("welcome").hidden = true;
    const parts = path.split("/");
    $("md-doc-filename").replaceChildren();
    parts.forEach((part, index) => {
      if (index) $("md-doc-filename").append(icon("chevron-right"));
      $("md-doc-filename").append(
        el(index === parts.length - 1 ? "strong" : "span", null, part),
      );
    });
    $("editor-language").textContent =
      buffer.type === "css"
        ? "CSS"
        : buffer.type === "meta"
          ? "YAML"
          : "Markdown";
    $("format-toolbar").hidden = buffer.type !== "md";
    if (
      buffer.type === "md" &&
      (!state.pinned ||
        !/(^|\/)templates\//.test(path.replace(/^project:/, "")))
    ) {
      if (state.pinned !== path) {
        state.pinned = path;
        state.revision++;
        state.artifact = null;
        state.view?.invalidate();
        $("preview-empty").hidden = false;
      }
      schedulePreview(0, true);
    }
    setEditMode(state.mode);
    updateSaveState();
    renderOutline();
    renderTree();
    persist();
    if (window.innerWidth <= 850) $("workbench").classList.remove("mobile-nav");
    return buffer;
  }
  function renderTabs() {
    const container = $("document-tabs");
    container.replaceChildren();
    for (const [path, buffer] of state.buffers) {
      const tab = el(
        "div",
        "document-tab" + (path === state.active ? " active" : ""),
      );
      const button = el("button");
      button.setAttribute("role", "tab");
      button.setAttribute(
        "aria-selected",
        path === state.active ? "true" : "false",
      );
      button.append(
        icon(
          buffer.type === "css"
            ? "code"
            : buffer.type === "meta"
              ? "settings"
              : "file",
        ),
        el("span", "tab-name", path.split("/").pop()),
      );
      button.title = path;
      button.onclick = () => openFile(path);
      if (dirty(buffer)) button.append(el("span", "dirty-dot"));
      const close = el("button", "tab-close");
      close.title = "Close " + path;
      close.setAttribute("aria-label", close.title);
      close.append(icon("close"));
      close.onclick = () => closeFile(path);
      tab.append(button, close);
      container.append(tab);
    }
    if (!state.buffers.size)
      container.append(el("span", "tabs-empty", "Your documents"));
  }
  async function closeFile(path) {
    const buffer = state.buffers.get(path);
    if (dirty(buffer)) {
      const choice = await confirmDialog(
        "Close unsaved document?",
        path + " has changes that are not saved to disk.",
        [
          { label: "Cancel", value: "cancel" },
          { label: "Discard", value: "discard", danger: true },
          { label: "Save & close", value: "save", primary: true },
        ],
      );
      if (!choice || choice === "cancel") return;
      if (choice === "save" && !(await save(path))) return;
    }
    state.buffers.delete(path);
    buffer.model?.dispose();
    if (state.active === path) {
      state.active = null;
      const next = [...state.buffers.keys()].pop();
      if (next) await openFile(next);
      else {
        $("welcome").hidden = false;
        $("md-doc-filename").textContent = "No file selected";
        if (state.editor) state.editor.setModel(null);
      }
    }
    if (state.pinned === path) {
      state.pinned = current()?.type === "md" ? state.active : null;
      state.revision++;
      state.artifact = null;
      state.view?.invalidate();
      $("preview-empty").hidden = false;
      schedulePreview();
    }
    persist();
    renderTree();
  }
  async function save(path = state.active) {
    const buffer = state.buffers.get(path);
    if (!buffer || buffer.saving) return false;
    const content = buffer.content;
    buffer.saving = true;
    updateSaveState();
    try {
      const result = await api("/api/file", {
        method: "PUT",
        body: JSON.stringify({ path, content, revision: buffer.revision }),
      });
      buffer.saved = content;
      buffer.revision = result.revision;
      toast("Saved " + path.split("/").pop());
      persist();
      renderTree();
      return true;
    } catch (error) {
      if (error.status === 409) compareBuffer(buffer, error.detail);
      else toast(error.message, true);
      return false;
    } finally {
      buffer.saving = false;
      updateSaveState();
    }
  }
  function compareBuffer(buffer, disk) {
    const body = el("div");
    body.append(
      el(
        "p",
        null,
        "The disk file and your draft differ. Review them before choosing how to continue.",
      ),
    );
    body.append(el("label", null, "Your draft"));
    const draft = el("textarea", "input");
    draft.value = buffer.content;
    draft.readOnly = true;
    body.append(draft, el("label", null, "Current disk file"));
    const stored = el("textarea", "input");
    stored.value = disk.content;
    stored.readOnly = true;
    body.append(stored);
    dialog(
      "Review file changes",
      body,
      [
        { label: "Keep editing", run: (d) => d.close() },
        {
          label: "Use disk version",
          run: (d) => {
            buffer.saved = disk.content;
            buffer.revision = disk.revision;
            if (buffer.model) buffer.model.setValue(disk.content);
            else {
              buffer.content = disk.content;
              if (state.active === buffer.path)
                state.fallback.value = disk.content;
            }
            buffer.content = disk.content;
            state.revision++;
            persist();
            schedulePreview();
            d.close();
          },
        },
        {
          label: "Save my draft",
          primary: true,
          run: async (d) => {
            buffer.revision = disk.revision;
            if (await save(buffer.path)) d.close();
          },
        },
      ],
      true,
    );
  }
  function buffers() {
    return Object.fromEntries(
      [...state.buffers]
        .filter(([, b]) => dirty(b))
        .map(([p, b]) => [p, b.content]),
    );
  }
  function setRenderState(text, kind = "") {
    const node = $("preview-status");
    node.textContent = text;
    node.className = "render-state " + kind;
    $("preview-loading").hidden = kind !== "updating";
  }
  function schedulePreview(delay = 800, force = false) {
    clearTimeout(state.timer);
    if (!state.pinned) return;
    setRenderState(
      state.artifact ? "Out of date" : "Waiting to render",
      "stale",
    );
    if (state.auto || force)
      state.timer = setTimeout(() => renderPreview().catch(reportError), delay);
  }
  function reportError(error) {
    state.error = error.message;
    setRenderState("Render failed", "failed");
    $("diagnostic-count").replaceChildren(
      icon("alert"),
      document.createTextNode("1 issue"),
    );
    renderDiagnostics();
    if (!state.artifact) {
      $("preview-empty").hidden = false;
      $("preview-empty").querySelector("h2").textContent =
        "Your document needs attention";
      $("preview-empty").querySelector("p").textContent = error.message;
    }
  }
  async function renderPreview() {
    if (!state.pinned) return;
    const path = state.pinned;
    const revision = state.revision;
    const content = buffers();
    const jobKey = crypto.randomUUID();
    state.jobKey = jobKey;
    setRenderState("Updating", "updating");
    $("preview-document").textContent = path;
    $("preview-document").title = path;
    try {
      if (state.job) await api("/api/jobs/" + state.job, { method: "DELETE" });
      const job = await api("/api/preview/jobs", {
        method: "POST",
        body: JSON.stringify({
          path,
          buffers: content,
          format: "pdf",
          revision,
          client: state.client,
          purpose: "preview",
        }),
      });
      if (state.jobKey !== jobKey) {
        await api("/api/jobs/" + job.id, { method: "DELETE" });
        return;
      }
      state.job = job.id;
      state.inspection = job.inspection;
      renderInspector();
      let result = job;
      while (result.state === "queued" || result.state === "running") {
        await new Promise((r) => setTimeout(r, 250));
        if (state.jobKey !== jobKey) return;
        result = await api("/api/jobs/" + job.id);
      }
      if (
        state.jobKey !== jobKey ||
        state.pinned !== path ||
        state.revision !== revision
      ) {
        if (state.jobKey === jobKey) {
          setRenderState("Out of date", "stale");
          if (state.auto) schedulePreview(0);
        }
        return;
      }
      state.log = result.log || "";
      if (result.state === "cancelled") {
        setRenderState("Paused", "stale");
        return;
      }
      if (result.state !== "succeeded")
        throw new Error(result.error || "Rendering failed");
      if (!state.view) {
        const module = await import("/static/viewer.js");
        state.view = new module.DocumentViewer((error) =>
          toast("PDF viewer: " + error.message, true),
        );
      }
      if (
        state.jobKey !== jobKey ||
        state.pinned !== path ||
        state.revision !== revision
      )
        return;
      await state.view.load(result.artifact, state.artifactPath === path);
      if (
        state.jobKey !== jobKey ||
        state.pinned !== path ||
        state.revision !== revision
      )
        return;
      state.artifact = result.artifact;
      state.artifactPath = path;
      state.artifactRevision = revision;
      state.error = null;
      setRenderState("Current", "");
      $("preview-time").textContent =
        "Updated " +
        new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        });
      $("diagnostic-count").replaceChildren(
        icon("check"),
        document.createTextNode("No issues"),
      );
      renderDiagnostics();
    } catch (error) {
      if (state.jobKey === jobKey) reportError(error);
    }
  }
  function renderDiagnostics() {
    $("diagnostics-content").replaceChildren();
    if (state.error) {
      const message = el("div", "diagnostic-error");
      message.append(icon("alert"), el("span", null, state.error));
      $("diagnostics-content").append(message);
    } else
      $("diagnostics-content").append(
        el(
          "div",
          "diagnostic-info",
          state.artifact
            ? "The preview uses the same PDF artifact that you download."
            : "Open a document to render its output.",
        ),
      );
    if (state.log) {
      const details = el("details");
      details.append(
        el("summary", "diagnostic-info", "Renderer log"),
        el("pre", null, state.log),
      );
      $("diagnostics-content").append(details);
    }
  }
  function renderOutline() {
    const container = $("outline-panel");
    container.replaceChildren();
    const buffer = current();
    if (!buffer || buffer.type !== "md") {
      container.append(
        el(
          "p",
          "inspector-note",
          "Open a Markdown document to see its outline.",
        ),
      );
      return;
    }
    let fenced = false;
    buffer.content.split("\n").forEach((line, index) => {
      if (/^\s*```/.test(line)) fenced = !fenced;
      if (fenced) return;
      const match = line.match(/^(#{1,6})\s+(.+)/);
      if (match) {
        const button = el("button", "outline-item", match[2]);
        button.style.paddingLeft = 8 + (match[1].length - 1) * 12 + "px";
        button.onclick = () => {
          setEditMode("source");
          state.editor?.revealLineInCenter(index + 1);
          state.editor?.setPosition({ lineNumber: index + 1, column: 1 });
        };
        container.append(button);
      }
    });
  }
  function nav(name) {
    state.nav = name;
    const titles = {
      files: "EXPLORER",
      search: "SEARCH",
      outline: "OUTLINE",
      git: "SOURCE CONTROL",
    };
    $("sidebar-title").textContent = titles[name];
    for (const id of [
      "md-doc-tree",
      "search-panel",
      "outline-panel",
      "git-panel",
    ])
      $(id).hidden =
        id !==
        {
          files: "md-doc-tree",
          search: "search-panel",
          outline: "outline-panel",
          git: "git-panel",
        }[name];
    $("file-filter").hidden = name !== "files";
    document
      .querySelectorAll(".rail-button[data-nav]")
      .forEach((b) => b.classList.toggle("active", b.dataset.nav === name));
    $("workbench").classList.remove("nav-hidden");
    if (window.innerWidth <= 850) $("workbench").classList.toggle("mobile-nav");
    if (name === "search") $("workspace-query").focus();
    if (name === "git") loadGit().catch((error) => toast(error.message, true));
    applyLayout();
  }
  function applyAppearance() {
    const dark =
      state.appearance === "dark" ||
      (state.appearance === "system" &&
        matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    state.editor?.updateOptions({ theme: dark ? "vs-dark" : "mddoc-light" });
    store("appearance", state.appearance);
  }
  function applyLayout() {
    const bench = $("workbench");
    for (const value of ["source", "preview", "horizontal"])
      bench.classList.toggle("layout-" + value, state.layout === value);
    const available =
      bench.clientWidth -
      46 -
      (bench.classList.contains("nav-hidden") ? 0 : state.navWidth) -
      10;
    const width = Math.max(
      320,
      Math.min(available - 320, available * state.editRatio),
    );
    bench.style.setProperty("--nav-width", state.navWidth + "px");
    bench.style.setProperty("--edit-fraction", Math.max(0, width) + "px");
    bench.style.setProperty(
      "--horizontal-split",
      state.horizontalRatio * 100 + "%",
    );
    $("preview-splitter").setAttribute(
      "aria-orientation",
      state.layout === "horizontal" ? "horizontal" : "vertical",
    );
    $("preview-splitter").setAttribute(
      "aria-valuenow",
      String(Math.round(available - width)),
    );
    $("preview-splitter").setAttribute(
      "aria-valuemax",
      String(Math.max(320, available - 320)),
    );
    $("nav-splitter").setAttribute(
      "aria-valuenow",
      String(Math.round(state.navWidth)),
    );
    state.editor?.layout();
    state.view?.resize();
    store("layout", {
      layout: state.layout,
      navWidth: state.navWidth,
      editRatio: state.editRatio,
      horizontalRatio: state.horizontalRatio,
    });
  }
  function splitters() {
    for (const id of ["nav-splitter", "preview-splitter"]) {
      const node = $(id);
      node.onpointerdown = (event) => {
        if (event.button !== 0) return;
        const start = event.clientX,
          startY = event.clientY,
          navWidth = state.navWidth,
          ratio = state.editRatio,
          horizontal = state.horizontalRatio;
        node.setPointerCapture(event.pointerId);
        node.classList.add("resizing");
        $("resize-shield").hidden = false;
        const available = $("workbench").clientWidth - 46 - state.navWidth - 10;
        node.onpointermove = (move) => {
          if (id === "nav-splitter")
            state.navWidth = Math.max(
              180,
              Math.min(420, navWidth + move.clientX - start),
            );
          else if (state.layout === "horizontal")
            state.horizontalRatio = Math.max(
              0.2,
              Math.min(
                0.8,
                horizontal +
                  (move.clientY - startY) / $("workbench").clientHeight,
              ),
            );
          else
            state.editRatio = Math.max(
              320 / available,
              Math.min(
                1 - 320 / available,
                ratio + (move.clientX - start) / available,
              ),
            );
          applyLayout();
        };
        const end = () => {
          node.onpointermove = null;
          node.classList.remove("resizing");
          $("resize-shield").hidden = true;
        };
        node.onpointerup = end;
        node.onlostpointercapture = end;
      };
      node.ondblclick = () => {
        if (id === "nav-splitter") state.navWidth = 240;
        else {
          state.editRatio = 0.5;
          state.horizontalRatio = 0.5;
        }
        applyLayout();
      };
      node.onkeydown = (event) => {
        const directions = {
          ArrowLeft: -1,
          ArrowUp: -1,
          ArrowRight: 1,
          ArrowDown: 1,
        };
        if (!(event.key in directions) && !["Home", "End"].includes(event.key))
          return;
        event.preventDefault();
        const amount = event.shiftKey ? 64 : 16;
        if (id === "nav-splitter") {
          state.navWidth =
            event.key === "Home"
              ? 180
              : event.key === "End"
                ? 420
                : Math.max(
                    180,
                    Math.min(
                      420,
                      state.navWidth + directions[event.key] * amount,
                    ),
                  );
        } else {
          const available =
            $("workbench").clientWidth - 46 - state.navWidth - 10;
          if (state.layout === "horizontal")
            state.horizontalRatio =
              event.key === "Home"
                ? 0.2
                : event.key === "End"
                  ? 0.8
                  : Math.max(
                      0.2,
                      Math.min(
                        0.8,
                        state.horizontalRatio +
                          (directions[event.key] * amount) /
                            $("workbench").clientHeight,
                      ),
                    );
          else
            state.editRatio =
              event.key === "Home"
                ? 320 / available
                : event.key === "End"
                  ? 1 - 320 / available
                  : Math.max(
                      320 / available,
                      Math.min(
                        1 - 320 / available,
                        state.editRatio +
                          (directions[event.key] * amount) / available,
                      ),
                    );
        }
        applyLayout();
      };
    }
  }
  function insert(kind, value = null) {
    if (!current()) return;
    setEditMode("source");
    const snippets = {
      heading: "## Heading",
      bold: "**text**",
      italic: "*text*",
      list: "- Item\n- Item",
      link: "[Link text](https://example.com)",
      table: "| Column 1 | Column 2 |\n| --- | --- |\n| Value | Value |",
      pagebreak: "\n<!-- pagebreak -->\n",
      mermaid: "\n```mermaid\nflowchart LR\n  A[Start] --> B[Finish]\n```\n",
      form: "?[text: field_name, required]",
      slide:
        "\n<!-- slide: columns -->\n## Slide title\n\nFirst column\n\n<!-- col -->\n\nSecond column\n",
    };
    let text = value ?? snippets[kind] ?? "";
    if (state.editor) {
      const selection = state.editor.getSelection();
      const selected = state.editor.getModel().getValueInRange(selection);
      if (selected && kind === "bold") text = "**" + selected + "**";
      if (selected && kind === "italic") text = "*" + selected + "*";
      state.editor.executeEdits("studio-insert", [
        { range: selection, text, forceMoveMarkers: true },
      ]);
      state.editor.pushUndoStop();
      state.editor.focus();
    } else {
      const input = state.fallback;
      const start = input.selectionStart,
        end = input.selectionEnd;
      input.setRangeText(text, start, end, "end");
      changed(input.value);
      input.focus();
    }
  }
  function chunks(source) {
    const output = [];
    let block = "",
      fenced = false,
      frontmatter = source.startsWith("---\n"),
      first = true;
    for (const line of source.match(/[^\n]*\n|[^\n]+$/g) || []) {
      if (/^\s*```/.test(line)) fenced = !fenced;
      if (frontmatter && line.trim() === "---" && !first) frontmatter = false;
      block += line;
      first = false;
      if (!line.trim() && !fenced && !frontmatter) {
        output.push(block);
        block = "";
      }
    }
    if (block) output.push(block);
    return output;
  }
  function serializeInline(node) {
    if (node.nodeType === Node.TEXT_NODE)
      return node.textContent.replace(/([*_`\[\]\\])/g, "\\$1");
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const text = [...node.childNodes].map(serializeInline).join("");
    switch (node.tagName) {
      case "STRONG":
      case "B":
        return "**" + text + "**";
      case "EM":
      case "I":
        return "*" + text + "*";
      case "CODE":
        return "`" + node.textContent + "`";
      case "BR":
        return "\n";
      case "DIV":
      case "P":
        return text + "\n";
      default:
        return text;
    }
  }
  function renderWrite() {
    const buffer = current();
    const container = $("write-editor");
    container.replaceChildren();
    if (!buffer) return;
    state.writeChunks = chunks(buffer.content);
    state.writeChunks.forEach((raw, index) => {
      const trim = raw.trim();
      if (!trim) {
        container.append(el("div", "write-block"));
        return;
      }
      const heading = trim.match(/^(#{1,3})\s+([^\n]+)$/);
      const simple =
        !/[{}\[\]<>|]/.test(trim) &&
        !/^---|^\s*```|^\s*[-*+]\s|^\s*\d+\.|^\s*#(?!#{0,2}\s)/m.test(trim) &&
        !trim.includes("!(");
      if (!simple) {
        const block = el("div", "protected-block");
        const label = el("span", null, "SOURCE BLOCK · CLICK TO EDIT");
        const code = el("div", null, raw.trimEnd());
        block.append(label, code);
        block.setAttribute("role", "button");
        block.tabIndex = 0;
        const select = () => {
          setEditMode("source");
          const line = state.writeChunks
            .slice(0, index)
            .join("")
            .split("\n").length;
          state.editor?.setPosition({ lineNumber: line, column: 1 });
          state.editor?.revealLineInCenter(line);
        };
        block.onclick = select;
        block.onkeydown = (e) => {
          if (e.key === "Enter") select();
        };
        container.append(block);
        return;
      }
      const block = el("div", "write-block");
      const editable = el(heading ? "h" + heading[1].length : "p");
      editable.contentEditable = "true";
      editable.setAttribute("role", "textbox");
      editable.setAttribute(
        "aria-label",
        heading ? "Heading text" : "Paragraph text",
      );
      const html = marked.parseInline(heading ? heading[2] : trim);
      const template = document.createElement("template");
      template.innerHTML = html;
      template.content.querySelectorAll("*").forEach((node) => {
        if (!["STRONG", "EM", "B", "I", "CODE", "BR"].includes(node.tagName))
          node.replaceWith(document.createTextNode(node.textContent));
        else
          [...node.attributes].forEach((attr) =>
            node.removeAttribute(attr.name),
          );
      });
      editable.append(template.content);
      editable.onpaste = (event) => {
        event.preventDefault();
        document.execCommand(
          "insertText",
          false,
          event.clipboardData.getData("text/plain"),
        );
      };
      editable.oninput = () => {
        const suffix = raw.match(/\n*$/)[0];
        state.writeChunks[index] =
          (heading ? heading[1] + " " : "") +
          serializeInline(editable).trimEnd() +
          suffix;
        sourceValue(state.writeChunks.join(""));
      };
      block.append(editable);
      container.append(block);
    });
  }
  function setEditMode(mode) {
    state.mode = mode;
    const write = mode === "write" && current()?.type === "md";
    $("write-editor").hidden = !write;
    $("md-doc-monaco").hidden = write;
    document
      .querySelectorAll("[data-edit-mode]")
      .forEach((b) =>
        b.classList.toggle(
          "active",
          b.dataset.editMode === (write ? "write" : "source"),
        ),
      );
    if (write) renderWrite();
    else state.editor?.layout();
  }
  function renderInspector() {
    const container = $("inspector-content");
    container.replaceChildren();
    const data = state.inspection;
    if (!data) {
      container.append(
        el(
          "p",
          "inspector-note",
          "Select a document to inspect its resolved properties and theme.",
        ),
      );
      return;
    }
    document
      .querySelectorAll("[data-inspect]")
      .forEach((b) =>
        b.classList.toggle("active", b.dataset.inspect === state.inspectTab),
      );
    if (state.inspectTab === "properties") {
      const section = el("div", "inspector-section");
      section.append(el("h3", null, "DOCUMENT PROPERTIES"));
      for (const [name, label, type, options] of [
        ["title", "Title", "text"],
        ["author", "Author", "text"],
        ["product", "Product / company", "text"],
        ["version", "Version", "text"],
        ["status", "Status", "text"],
        ["cover_page", "Cover page", "select", ["Inherited", "true", "false"]],
        [
          "pdf_forms",
          "PDF form fields",
          "select",
          ["Inherited", "true", "false"],
        ],
        [
          "body_text_align",
          "Body alignment",
          "select",
          ["Inherited", "left", "justify", "center", "right"],
        ],
      ]) {
        const field = el("div", "property");
        const lbl = el("label", null, label);
        lbl.htmlFor = "prop-" + name;
        field.append(lbl);
        const row = el("div", "property-row");
        const input = el(type === "select" ? "select" : "input", "input");
        input.id = "prop-" + name;
        if (type === "select") {
          for (const value of options) {
            const option = el("option", null, value);
            option.value = value === "Inherited" ? "" : value;
            input.append(option);
          }
          input.value =
            data.merged[name] === undefined ? "" : String(data.merged[name]);
        } else {
          input.type = "text";
          input.value = data.merged[name] ?? "";
        }
        input.onchange = () => setProperty(name, input.value || null);
        row.append(input);
        const reset = el("button", "icon-button small");
        reset.title = "Remove document override";
        reset.setAttribute("aria-label", reset.title);
        reset.append(icon("undo"));
        reset.onclick = () => setProperty(name, null);
        row.append(reset);
        field.append(row);
        const origin = el("span", "provenance");
        origin.append(
          icon("git"),
          document.createTextNode(data.provenance?.[name] || "Default"),
        );
        field.append(origin);
        section.append(field);
      }
      container.append(section);
      const layers = el("div", "inspector-section");
      layers.append(el("h3", null, "CONFIGURATION CASCADE"));
      for (const layer of data.layers || []) {
        const details = el("details", "layer");
        const summary = el("summary", null, layer.file);
        details.append(
          summary,
          el("pre", null, JSON.stringify(layer.values, null, 2)),
        );
        if (layer.file !== "frontmatter") {
          const button = el("button", "dependency-button", "Open source");
          button.onclick = () => openDependency(layer.file);
          details.append(button);
        }
        layers.append(details);
      }
      container.append(layers);
    } else if (state.inspectTab === "theme") {
      container.append(
        el(
          "p",
          "inspector-note",
          "The PDF uses this resolved theme and its local CSS imports. Word formats use their own theme cascade.",
        ),
      );
      const button = el(
        "button",
        "dependency-button",
        data.theme?.source || "Default PDF theme",
      );
      button.prepend(icon("code"));
      button.onclick = () =>
        data.theme?.source
          ? openDependency(data.theme.source)
          : toast("A default theme is applied inside the preview snapshot.");
      container.append(
        button,
        el(
          "pre",
          "theme-source",
          data.theme?.css ||
            "No theme found. The pipeline uses its default theme.",
        ),
      );
      const includes = el("div", "inspector-section");
      includes.append(el("h3", null, "INCLUDED TEMPLATES"));
      for (const item of data.includes || []) {
        const control = el(
          "button",
          "dependency-button",
          item.name + (item.found ? "" : " · missing"),
        );
        control.prepend(icon("file"));
        control.disabled = !item.path;
        control.onclick = () => openDependency(item.path);
        includes.append(control);
      }
      if (!(data.includes || []).length)
        includes.append(el("p", "inspector-note", "No included templates."));
      container.append(includes);
    } else {
      container.append(
        el(
          "p",
          "inspector-note",
          "Insert a documented Word field at the cursor. Form shorthand is available in the insertion menu.",
        ),
      );
      for (const [name, description] of Object.entries(data.fields || {})) {
        const card = el("div", "field-card");
        const button = el("button", null, "[[" + name + "]]");
        button.onclick = () => insert("field", "[[" + name + "]]");
        card.append(
          button,
          el(
            "p",
            null,
            typeof description === "string"
              ? description
              : JSON.stringify(description),
          ),
        );
        container.append(card);
      }
      if (!Object.keys(data.fields || {}).length)
        container.append(
          el(
            "p",
            "inspector-note",
            "Add a _merge_fields.yml file to document your available fields.",
          ),
        );
    }
  }
  function openDependency(path) {
    const root = state.workspace.workspace;
    if (path.startsWith(root + "/")) path = path.slice(root.length + 1);
    else if (path.startsWith("/")) {
      const project = state.workspace.projectRoot;
      if (project && path.startsWith(project + "/"))
        path = "project:" + path.slice(project.length + 1);
      else {
        toast("This inherited file is outside the project.", true);
        return;
      }
    }
    openFile(path).catch((error) => toast(error.message, true));
  }
  async function setProperty(name, value) {
    if (!state.pinned) return;
    const buffer =
      state.buffers.get(state.pinned) || (await openFile(state.pinned));
    const source = buffer.content;
    const match = source.match(/^---\s*\n([\s\S]*?)\n---(?:\n|$)/);
    let yaml = match ? match[1] : "";
    const lines = yaml.split("\n");
    const index = lines.findIndex((line) =>
      new RegExp("^" + name + "\\s*:").test(line),
    );
    if (index >= 0) {
      const old = lines[index].replace(
        new RegExp("^" + name + "\\s*:\\s*"),
        "",
      );
      if (/^[|>&*{\[]/.test(old) || lines[index + 1]?.match(/^\s+\S/)) {
        toast(
          "This property uses structured YAML. Edit it in Source mode to preserve its syntax.",
          true,
        );
        await openFile(buffer.path);
        setEditMode("source");
        return;
      }
      if (value === null) lines.splice(index, 1);
      else
        lines[index] =
          name +
          ": " +
          (["true", "false"].includes(value) ? value : JSON.stringify(value));
    } else if (value !== null)
      lines.push(
        name +
          ": " +
          (["true", "false"].includes(value) ? value : JSON.stringify(value)),
      );
    yaml = lines.filter((line, index) => line !== "" || index > 0).join("\n");
    const next =
      "---\n" + yaml + "\n---\n" + source.slice(match ? match[0].length : 0);
    if (buffer.model) buffer.model.setValue(next);
    buffer.content = next;
    if (state.active === buffer.path && state.fallback)
      state.fallback.value = next;
    state.revision++;
    persist();
    if (state.active === buffer.path && state.mode === "write") renderWrite();
    schedulePreview();
  }
  async function exportFile(format) {
    if (!state.pinned) {
      toast("Open a Markdown document first.", true);
      return;
    }
    const path = state.pinned,
      revision = state.revision,
      snapshot = buffers();
    if (
      format === "pdf" &&
      state.artifact &&
      state.artifactPath === path &&
      state.artifactRevision === revision
    ) {
      download(state.artifact);
      return;
    }
    toast(
      "Building " +
        format.toUpperCase() +
        " from your current editing snapshot…",
    );
    const job = await api("/api/preview/jobs", {
      method: "POST",
      body: JSON.stringify({
        path,
        buffers: snapshot,
        format,
        revision,
        client: state.client,
        purpose: "export",
      }),
    });
    let result = job;
    while (["queued", "running"].includes(result.state)) {
      await new Promise((r) => setTimeout(r, 300));
      result = await api("/api/jobs/" + job.id);
    }
    if (result.state !== "succeeded")
      throw new Error(result.error || "Export failed");
    download(result.artifact);
    toast("Export ready: " + result.artifact.filename);
  }
  function download(artifact) {
    const link = el("a");
    link.href =
      artifact.url + (artifact.url.includes("?") ? "&" : "?") + "download=true";
    link.download = artifact.filename;
    document.body.append(link);
    link.click();
    link.remove();
  }
  function option(label, description, iconName, run) {
    const button = el("button", "option-button");
    button.type = "button";
    button.append(icon(iconName));
    const text = el("span");
    text.append(el("strong", null, label), el("small", null, description));
    button.append(text);
    button.onclick = async () => {
      $("form-dialog").close();
      try {
        await run();
      } catch (error) {
        toast(error.message, true);
      }
    };
    return button;
  }
  function exportMenu() {
    const body = el("div");
    body.append(
      el(
        "p",
        null,
        "Export your current document and dependency edits. Exporting does not save source files.",
      ),
    );
    for (const [format, label, description] of [
      ["pdf", "PDF document", "The exact file shown in the output preview"],
      ["docx", "Word document", "Editable DOCX with the Word theme"],
      ["dotx", "Word template", "Template with fillable Word fields"],
      [
        "pptx",
        "PowerPoint deck",
        "Slides from document headings and directives",
      ],
    ])
      body.append(
        option(label, description, "download", () => exportFile(format)),
      );
    body.append(
      el(
        "p",
        "inspector-note",
        "PDF has an exact preview. Word and PowerPoint downloads use their native output engines; their layout may differ.",
      ),
    );
    dialog("Export document", body);
  }
  function layoutMenu() {
    const body = el("div");
    for (const [value, label, description, iconName] of [
      [
        "split",
        "Side by side",
        "Source on the left, final PDF on the right",
        "columns",
      ],
      ["horizontal", "Stacked", "Source above the final PDF", "panel"],
      ["source", "Source only", "More room for authoring", "code"],
      ["preview", "Preview only", "Review the complete document", "file"],
    ])
      body.append(
        option(label, description, iconName, () => {
          state.layout = value;
          applyLayout();
        }),
      );
    dialog("Workspace layout", body);
  }
  async function newDocument() {
    const parent = state.active?.includes("/")
      ? state.active.slice(0, state.active.lastIndexOf("/") + 1)
      : "";
    dialog(
      "Create a document",
      `<p>Start with a document scaffold. Settings are inherited from the folder.</p><label for="new-path">File path</label><input class="input" id="new-path" value="${escape(parent)}untitled.md"><label for="new-kind">Document type</label><select class="input" id="new-kind"><option value="report">Report</option><option value="form">Fillable PDF form</option><option value="deck">Slide deck</option><option value="blank">Blank document</option></select>`,
      [
        { label: "Cancel", run: (d) => d.close() },
        {
          label: "Create document",
          primary: true,
          run: async (d) => {
            const path = $("new-path").value.trim();
            const kind = $("new-kind").value;
            const title = path
              .split("/")
              .pop()
              .replace(/\.md$/, "")
              .replace(/[-_]/g, " ");
            const sources = {
              report: `---\ntitle: ${JSON.stringify(title)}\noutputs: [pdf, docx]\ncover_page: true\n---\n\n# ${title}\n\n## Overview\n\nStart writing your report here.\n`,
              form: `---\ntitle: ${JSON.stringify(title)}\npdf_forms: true\n---\n\n# ${title}\n\n## Contact details\n\nName: ?[text: contact_name, required]\n\nEmail: ?[email: email, required]\n`,
              deck: `---\ntitle: ${JSON.stringify(title)}\noutputs: [pptx]\nslide_size: "16:9"\n---\n\n# ${title}\n\n## First slide\n\n- First point\n- Second point\n`,
              blank: `# ${title}\n\n`,
            };
            await api("/api/files/action", {
              method: "POST",
              body: JSON.stringify({
                action: "new",
                path,
                content: sources[kind],
              }),
            });
            d.close();
            await loadTree();
            await openFile(path);
          },
        },
      ],
    );
  }
  function fileActions(path = state.active) {
    const body = el("div");
    if (path) {
      body.append(el("p", null, path));
      for (const [action, label, description, iconName] of [
        [
          "rename",
          "Rename or move",
          "Local asset references should be reviewed after a move",
          "edit",
        ],
        ["duplicate", "Duplicate", "Make a separate copy of this file", "copy"],
        [
          "trash",
          "Move to trash",
          "Recoverable from the confirmation toast",
          "trash",
        ],
      ])
        body.append(
          option(label, description, iconName, () => fileAction(action, path)),
        );
    }
    body.append(
      option(
        "New folder",
        "Create a folder with inherited settings",
        "folder",
        () => {
          dialog(
            "Create a folder",
            `<label for="folder-path">Folder path</label><input class="input" id="folder-path" placeholder="clients/new-client">`,
            [
              { label: "Cancel", run: (d) => d.close() },
              {
                label: "Create folder",
                primary: true,
                run: async (d) => {
                  await api("/api/files/action", {
                    method: "POST",
                    body: JSON.stringify({
                      action: "folder",
                      path: $("folder-path").value.trim(),
                    }),
                  });
                  d.close();
                  await loadTree();
                },
              },
            ],
          );
        },
      ),
    );
    dialog("File actions", body);
  }
  async function fileAction(action, path) {
    if (state.buffers.has(path) && dirty(state.buffers.get(path))) {
      toast(
        "Save or close this file before moving, duplicating or deleting it.",
        true,
      );
      return;
    }
    if (action === "trash") {
      const choice = await confirmDialog(
        "Move file to trash?",
        path + " will be moved to .editor-trash in this workspace.",
        [
          { label: "Cancel", value: false },
          { label: "Move to trash", value: true, danger: true },
        ],
      );
      if (!choice) return;
      const result = await api("/api/files/action", {
        method: "POST",
        body: JSON.stringify({ action, path }),
      });
      if (state.buffers.has(path)) await closeFile(path);
      await loadTree();
      toast("Moved to trash", false, {
        label: "Undo",
        run: async () => {
          await api("/api/files/action", {
            method: "POST",
            body: JSON.stringify({
              action: "restore",
              path,
              destination: result.restore,
            }),
          });
          await loadTree();
        },
      });
      return;
    }
    dialog(
      action === "rename" ? "Rename or move file" : "Duplicate file",
      `<p>Relative references are preserved as written. Check the preview after moving a document.</p><label for="file-destination">Destination path</label><input class="input" id="file-destination" value="${escape(path)}">`,
      [
        { label: "Cancel", run: (d) => d.close() },
        {
          label: action === "rename" ? "Move file" : "Duplicate",
          primary: true,
          run: async (d) => {
            const destination = $("file-destination").value.trim();
            await api("/api/files/action", {
              method: "POST",
              body: JSON.stringify({ action, path, destination }),
            });
            if (action === "rename" && state.buffers.has(path))
              await closeFile(path);
            d.close();
            await loadTree();
            await openFile(destination);
          },
        },
      ],
    );
  }
  function insertionMenu() {
    const body = el("div");
    body.append(
      option(
        "Image",
        "Copy a local image into this project",
        "image",
        insertImage,
      ),
    );
    for (const [kind, label, description, iconName] of [
      [
        "pagebreak",
        "Page break",
        "Start the next section on a new page",
        "file",
      ],
      ["mermaid", "Mermaid diagram", "Insert a flowchart block", "git"],
      ["form", "Form field", "Insert a required text field", "edit"],
      ["slide", "Slide layout", "Two-column slide directive", "columns"],
    ])
      body.append(option(label, description, iconName, () => insert(kind)));
    body.append(
      option(
        "Merge field",
        "Choose from your documented fields",
        "code",
        () => {
          state.inspectTab = "fields";
          $("inspector").hidden = false;
          renderInspector();
        },
      ),
    );
    body.append(
      option(
        "Include template",
        "Choose an available Markdown template",
        "files",
        () => commandPalette("templates"),
      ),
    );
    dialog("Insert into document", body);
  }
  function insertImage() {
    if (!current() || current().type !== "md") {
      toast("Open a Markdown document first.", true);
      return;
    }
    const parent = current().path.includes("/")
      ? current().path.slice(0, current().path.lastIndexOf("/") + 1)
      : "";
    dialog(
      "Insert a local image",
      `<p>The image is copied into the project and referenced by a relative path.</p><label for="image-file">Image</label><input class="input" id="image-file" type="file" accept=".png,.jpg,.jpeg,.gif,.webp"><label for="image-path">Asset destination</label><input class="input" id="image-path" value="${escape(parent)}assets/image.png"><label for="image-alt">Description</label><input class="input" id="image-alt" placeholder="Describe this image">`,
      [
        { label: "Cancel", run: (d) => d.close() },
        {
          label: "Insert image",
          primary: true,
          run: async (d) => {
            const file = $("image-file").files[0];
            if (!file) throw new Error("Choose an image file");
            if (file.size > 10 * 1024 * 1024)
              throw new Error("Image exceeds 10 MiB");
            const data = await new Promise((resolve, reject) => {
              const reader = new FileReader();
              reader.onload = () => resolve(reader.result.split(",")[1]);
              reader.onerror = () =>
                reject(new Error("Image could not be read"));
              reader.readAsDataURL(file);
            });
            const destination = $("image-path").value.trim();
            await api("/api/assets", {
              method: "POST",
              body: JSON.stringify({ path: destination, data }),
            });
            const from = parent.split("/").filter(Boolean),
              to = destination.split("/");
            let shared = 0;
            while (shared < from.length && from[shared] === to[shared])
              shared++;
            const relative = [
              ...from.slice(shared).map(() => ".."),
              ...to.slice(shared),
            ].join("/");
            insert(
              "image",
              `![${$("image-alt").value.replace(/[\[\]]/g, "")}](${encodeURI(relative).replace(/\(/g, "%28").replace(/\)/g, "%29")})`,
            );
            d.close();
            schedulePreview();
            toast("Image added to the project");
          },
        },
      ],
    );
    $("image-file").onchange = () => {
      const file = $("image-file").files[0];
      if (file)
        $("image-path").value =
          parent + "assets/" + file.name.replace(/[^a-zA-Z0-9._-]/g, "-");
    };
  }
  function settings() {
    dialog(
      "Studio settings",
      `<p>Preferences are saved for this workspace on this browser.</p><label for="settings-appearance">Appearance</label><select class="input" id="settings-appearance"><option value="system">Use system setting</option><option value="light">Light</option><option value="dark">Dark</option></select><label for="settings-refresh">Preview updates</label><select class="input" id="settings-refresh"><option value="auto">Automatic after typing pauses</option><option value="manual">Manual refresh</option></select><label for="settings-page">PDF reading layout</label><select class="input" id="settings-page"><option value="continuous">Continuous pages</option><option value="single">Single page</option></select><label for="settings-forms">PDF form test mode</label><select class="input" id="settings-forms"><option value="off">Off — show exported appearance</option><option value="on">On — fill fields for testing</option></select><p style="margin-top:15px">Form test values do not change document defaults or downloaded artifacts.</p>`,
      [
        {
          label: "Done",
          primary: true,
          run: async (d) => {
            state.appearance = $("settings-appearance").value;
            state.auto = $("settings-refresh").value === "auto";
            $("auto-preview").checked = state.auto;
            store("auto", state.auto);
            applyAppearance();
            if (state.view)
              await state.view.setFormTest($("settings-forms").value === "on");
            state.view?.setSinglePage($("settings-page").value === "single");
            if (state.auto) schedulePreview();
            d.close();
          },
        },
      ],
    );
    $("settings-appearance").value = state.appearance;
    $("settings-refresh").value = state.auto ? "auto" : "manual";
  }
  function help() {
    dialog(
      "Keyboard shortcuts",
      `<p>A familiar source editor, with a complete document preview.</p><div class="property-row"><span>Quick open</span><span class="toolbar-space"></span><kbd>Ctrl P</kbd></div><br><div class="property-row"><span>Commands</span><span class="toolbar-space"></span><kbd>Ctrl K</kbd></div><br><div class="property-row"><span>Save document</span><span class="toolbar-space"></span><kbd>Ctrl S</kbd></div><br><div class="property-row"><span>Bold / italic</span><span class="toolbar-space"></span><kbd>Ctrl B / I</kbd></div><br><div class="property-row"><span>Leave focus mode / close dialog</span><span class="toolbar-space"></span><kbd>Esc</kbd></div><br><div class="property-row"><span>Resize focused separator</span><span class="toolbar-space"></span><kbd>Arrows</kbd></div><p style="margin-top:20px">Use ⌘ on macOS. Source mode preserves all pipeline syntax. Write mode edits supported text blocks and keeps advanced syntax protected.</p>`,
      [{ label: "Got it", primary: true, run: (d) => d.close() }],
    );
  }
  const actions = {
    "quick-open": () => commandPalette(),
    appearance: () => {
      state.appearance =
        document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyAppearance();
    },
    help,
    export: exportMenu,
    new: newDocument,
    "file-actions": () => fileActions(),
    "refresh-tree": () => loadTree(),
    "open-sample": async () => {
      const file =
        state.files.find((f) => f.path.endsWith("branded-cover.md")) ||
        state.files.find((f) => f.path.endsWith("alpha-project-report.md")) ||
        state.files.find(
          (f) => f.type === "md" && !/README|CLAUDE|templates\//.test(f.path),
        );
      if (file) {
        const folders = file.path
          .split("/")
          .slice(0, -1)
          .map((_, i) =>
            file.path
              .split("/")
              .slice(0, i + 1)
              .join("/"),
          );
        store("folders", folders);
        await openFile(file.path);
      } else commandPalette("files");
    },
    "editor-find": () => {
      setEditMode("source");
      state.editor?.getAction("actions.find").run();
    },
    "insert-menu": insertionMenu,
    layout: layoutMenu,
    inspector: () => {
      $("inspector").hidden = !$("inspector").hidden;
      renderInspector();
    },
    "maximize-preview": () => {
      state.layout = state.layout === "preview" ? "split" : "preview";
      applyLayout();
    },
    focus: () => {
      $("studio").classList.toggle("focus");
      applyLayout();
    },
    settings,
    "nav-toggle": () => {
      if (window.innerWidth <= 850)
        $("workbench").classList.toggle("mobile-nav");
      else $("workbench").classList.toggle("nav-hidden");
      applyLayout();
    },
    diagnostics: () => {
      $("diagnostics-panel").hidden = !$("diagnostics-panel").hidden;
      renderDiagnostics();
      state.editor?.layout();
    },
    "refresh-preview": () => schedulePreview(0, true),
    "download-preview": () => {
      if (state.artifact) download(state.artifact);
      else toast("Render a document before downloading.", true);
    },
    print: () => {
      if (state.artifact) {
        const link = el("a");
        link.href = state.artifact.url;
        link.target = "_blank";
        link.rel = "noopener";
        link.click();
        toast("Opened the PDF. Use the browser’s PDF print control.");
      }
    },
    "pdf-find": () => {
      $("pdf-find-bar").hidden = !$("pdf-find-bar").hidden;
      if (!$("pdf-find-bar").hidden) $("pdf-find-query").focus();
      else state.view?.closeFind();
    },
  };
  function commandPalette(kind = "all") {
    $("command-query").value = "";
    state.commandKind = kind;
    state.commandIndex = 0;
    commandResults();
    $("command-dialog").showModal();
    $("command-query").focus();
  }
  function commandResults() {
    const query = $("command-query").value.toLowerCase();
    const commandList = [
      ["Create document", "new", "Ctrl N"],
      ["Export document", "export", ""],
      ["Change layout", "layout", ""],
      ["Refresh preview", "refresh-preview", ""],
      ["Document inspector", "inspector", ""],
      ["Save document", "save", "Ctrl S"],
      ["Focus mode", "focus", ""],
      ["Studio settings", "settings", ""],
      ["Source control", "git", ""],
      ["Insert form or diagram", "insert-menu", ""],
    ];
    let items = [];
    if (state.commandKind !== "templates")
      for (const file of state.files) {
        if (file.path.toLowerCase().includes(query))
          items.push({
            title: file.name,
            detail: file.path,
            icon:
              file.type === "css"
                ? "code"
                : file.type === "meta"
                  ? "settings"
                  : "file",
            run: () => openFile(file.path),
          });
      }
    else
      for (const file of state.files.filter(
        (f) => f.type === "md" && f.path.includes("templates/"),
      )) {
        if (file.path.toLowerCase().includes(query)) {
          const name = file.path.split("templates/").pop();
          items.push({
            title: file.name,
            detail: file.path,
            icon: "file",
            run: () => insert("include", '{% include "' + name + '" %}'),
          });
        }
      }
    if (state.commandKind !== "files" && state.commandKind !== "templates")
      for (const [title, action, shortcut] of commandList) {
        if (title.toLowerCase().includes(query))
          items.push({
            title,
            detail: "Command",
            icon: "settings",
            shortcut,
            run: () =>
              action === "save"
                ? save()
                : action === "git"
                  ? nav("git")
                  : actions[action](),
          });
      }
    state.commands = items.slice(0, 70);
    state.commandIndex = Math.min(
      state.commandIndex,
      Math.max(0, state.commands.length - 1),
    );
    const container = $("command-results");
    container.replaceChildren();
    state.commands.forEach((item, index) => {
      const button = el(
        "button",
        "command-item" + (index === state.commandIndex ? " selected" : ""),
      );
      button.setAttribute("role", "option");
      button.setAttribute(
        "aria-selected",
        index === state.commandIndex ? "true" : "false",
      );
      button.append(icon(item.icon));
      const text = el("span", "command-detail");
      text.append(
        el("strong", null, item.title),
        el("small", null, item.detail),
      );
      button.append(text);
      if (item.shortcut) button.append(el("kbd", null, item.shortcut));
      button.onclick = () => executeCommand(index);
      container.append(button);
    });
    if (!items.length)
      container.append(
        el("p", "diagnostic-info", "No matching files or commands."),
      );
  }
  async function executeCommand(index) {
    $("command-dialog").close();
    try {
      await state.commands[index]?.run();
    } catch (error) {
      toast(error.message, true);
    }
  }
  async function loadGit() {
    const data = await api("/api/git/status");
    $("git-branch").lastElementChild.textContent = data.branch || "No Git";
    const container = $("git-panel");
    container.replaceChildren();
    if (!data.available) {
      container.append(
        el(
          "p",
          "inspector-note",
          "This workspace is not inside a Git repository.",
        ),
      );
      return;
    }
    const heading = el("div", "git-heading");
    heading.append(icon("git"), el("span", null, data.branch));
    container.append(heading);
    const controls = el("div", "property-row");
    controls.append(
      option("New branch", "Create from current branch", "git", () =>
        gitBranch(),
      ),
      option("Pull", "Fast-forward only", "refresh", () => gitPull()),
    );
    container.append(controls);
    const staged = data.files.filter((f) => f.staged),
      unstaged = data.files.filter((f) => !f.staged || f.code[1] !== " ");
    for (const [label, list] of [
      ["STAGED CHANGES", staged],
      ["CHANGES", unstaged],
    ]) {
      container.append(el("label", "field-label", label + " · " + list.length));
      for (const item of list) {
        const row = el("div", "git-file");
        const diff = el("button", null, item.path);
        diff.title = item.path;
        diff.onclick = () => gitDiff(item.path, label === "STAGED CHANGES");
        row.append(diff, el("span", "git-code", item.code));
        const stage = el("button", "icon-button small");
        stage.title = label === "STAGED CHANGES" ? "Unstage" : "Stage";
        stage.setAttribute("aria-label", stage.title + " " + item.path);
        stage.append(icon(label === "STAGED CHANGES" ? "undo" : "plus"));
        stage.onclick = async () => {
          try {
            await api("/api/git/action", {
              method: "POST",
              body: JSON.stringify({
                action: label === "STAGED CHANGES" ? "unstage" : "stage",
                path: item.path,
              }),
            });
            await loadGit();
          } catch (error) {
            toast(error.message, true);
          }
        };
        row.append(stage);
        container.append(row);
      }
    }
    if (!data.files.length)
      container.append(
        el("p", "inspector-note", "No changes in this workspace."),
      );
    const message = el("textarea", "input");
    message.placeholder = "Commit message";
    message.setAttribute("aria-label", "Commit message");
    message.style.marginTop = "15px";
    message.style.minHeight = "70px";
    const commit = el("button", "button primary wide", "Commit staged changes");
    commit.disabled = !staged.length;
    commit.style.marginTop = "8px";
    commit.onclick = async () => {
      if (!message.value.trim()) {
        message.focus();
        return;
      }
      try {
        const choice = await confirmDialog(
          "Commit staged changes?",
          `Commit ${staged.length} workspace file(s) on ${data.branch} with message: ${message.value}`,
          [
            { label: "Cancel", value: false },
            { label: "Commit", value: true, primary: true },
          ],
        );
        if (choice) {
          await api("/api/git/action", {
            method: "POST",
            body: JSON.stringify({ action: "commit", message: message.value }),
          });
          await loadGit();
          toast("Committed staged workspace changes");
        }
      } catch (error) {
        toast(error.message, true);
      }
    };
    container.append(
      message,
      commit,
      el("label", "field-label", "RECENT WORKSPACE COMMITS"),
    );
    for (const [hash, subject, ago] of data.history || []) {
      const item = el("div", "git-log");
      item.append(
        el("strong", null, subject),
        el("span", null, hash + " · " + ago),
      );
      container.append(item);
    }
  }
  async function gitDiff(path, staged) {
    const data = await api(
      "/api/git/diff?path=" + encodeURIComponent(path) + "&staged=" + staged,
    );
    const pre = el("pre", "git-diff");
    for (const line of data.diff.split("\n")) {
      const node = el(
        "div",
        line.startsWith("+")
          ? "diff-add"
          : line.startsWith("-")
            ? "diff-remove"
            : "",
        line,
      );
      pre.append(node);
    }
    dialog(
      (staged ? "Staged diff: " : "Diff: ") + path,
      pre,
      [{ label: "Close", run: (d) => d.close() }],
      true,
    );
  }
  function gitBranch() {
    dialog(
      "Create a Git branch",
      `<p>Create and switch to a new branch from the current commit.</p><label for="branch-name">Branch name</label><input class="input" id="branch-name" placeholder="feature/document-update">`,
      [
        { label: "Cancel", run: (d) => d.close() },
        {
          label: "Create branch",
          primary: true,
          run: async (d) => {
            await api("/api/git/action", {
              method: "POST",
              body: JSON.stringify({
                action: "branch",
                branch: $("branch-name").value.trim(),
              }),
            });
            d.close();
            await loadGit();
          },
        },
      ],
    );
  }
  async function gitPull() {
    const choice = await confirmDialog(
      "Pull repository changes?",
      "Fetch and fast-forward the current branch from its configured upstream. Git will stop if a merge is needed.",
      [
        { label: "Cancel", value: false },
        { label: "Pull changes", value: true, primary: true },
      ],
    );
    if (choice) {
      await api("/api/git/action", {
        method: "POST",
        body: JSON.stringify({ action: "pull" }),
      });
      toast("Repository updated");
      await loadTree();
      await loadGit();
    }
  }
  async function checkChanges() {
    if (document.hidden) return;
    try {
      const data = await api("/api/changes");
      $("connection-dot").classList.remove("offline");
      $("connection-status").textContent = "Connected";
      if (state.changeSignature && data.signature !== state.changeSignature) {
        await loadTree();
        for (const [path, buffer] of state.buffers) {
          try {
            const disk = await api(
              "/api/file?path=" + encodeURIComponent(path),
            );
            if (disk.revision !== buffer.revision) {
              if (!dirty(buffer)) {
                buffer.saved = disk.content;
                buffer.content = disk.content;
                buffer.revision = disk.revision;
                buffer.model?.setValue(disk.content);
                if (state.active === path && state.fallback)
                  state.fallback.value = disk.content;
              } else if (buffer.warnedRevision !== disk.revision) {
                buffer.warnedRevision = disk.revision;
                toast("Changed on disk: " + path, true, {
                  label: "Review",
                  run: () => compareBuffer(buffer, disk),
                });
              }
            }
          } catch (error) {
            if (error.status === 404)
              toast("File removed on disk: " + path, true);
          }
        }
        state.revision++;
        persist();
        schedulePreview();
        if (state.nav === "git") await loadGit();
      }
      state.changeSignature = data.signature;
    } catch {
      $("connection-dot").classList.add("offline");
      $("connection-status").textContent = "Reconnecting…";
    }
  }
  async function init() {
    hydrate();
    monacoReady = initMonaco();
    splitters();
    document.addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]");
      if (action) {
        const fn = actions[action.dataset.action];
        if (fn)
          Promise.resolve()
            .then(fn)
            .catch((error) => toast(error.message, true));
      }
      const tool = event.target.closest("[data-insert]");
      if (tool) insert(tool.dataset.insert);
      const rail = event.target.closest("[data-nav]");
      if (rail) nav(rail.dataset.nav);
      const edit = event.target.closest("[data-edit-mode]");
      if (edit) setEditMode(edit.dataset.editMode);
      const inspection = event.target.closest("[data-inspect]");
      if (inspection) {
        state.inspectTab = inspection.dataset.inspect;
        renderInspector();
      }
    });
    $("md-doc-save-btn").onclick = () => save();
    $("dialog-close").onclick = () => $("form-dialog").close();
    $("dialog-form").onsubmit = (event) => event.preventDefault();
    for (const id of ["command-dialog", "form-dialog"])
      $(id).addEventListener("click", (event) => {
        if (event.target === $(id)) {
          const rect = $(id).getBoundingClientRect();
          if (
            event.clientX < rect.left ||
            event.clientX > rect.right ||
            event.clientY < rect.top ||
            event.clientY > rect.bottom
          )
            $(id).close();
        }
      });
    $("file-filter").oninput = renderTree;
    $("auto-preview").onchange = () => {
      state.auto = $("auto-preview").checked;
      store("auto", state.auto);
      if (state.auto) schedulePreview(0);
      else {
        clearTimeout(state.timer);
        if (state.job)
          api("/api/jobs/" + state.job, { method: "DELETE" }).catch(() => {});
        setRenderState("Paused", "stale");
      }
    };
    let searchTimer;
    $("workspace-query").oninput = () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(async () => {
        const query = $("workspace-query").value;
        try {
          const result = await api(
            "/api/search?q=" + encodeURIComponent(query),
          );
          if (query !== $("workspace-query").value) return;
          $("search-results").replaceChildren();
          for (const item of result.results) {
            const button = el("button", "search-result");
            button.append(
              el("strong", null, item.path + ":" + item.line),
              el("small", null, item.text),
            );
            button.onclick = () => openFile(item.path, item.line);
            $("search-results").append(button);
          }
          if (!result.results.length && query)
            $("search-results").append(
              el("p", "inspector-note", "No matches."),
            );
        } catch (error) {
          toast(error.message, true);
        }
      }, 250);
    };
    $("command-query").oninput = () => {
      state.commandIndex = 0;
      commandResults();
    };
    $("command-query").onkeydown = (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        state.commandIndex = Math.max(
          0,
          Math.min(
            state.commands.length - 1,
            state.commandIndex + (event.key === "ArrowDown" ? 1 : -1),
          ),
        );
        commandResults();
        $("command-results").children[state.commandIndex]?.scrollIntoView({
          block: "nearest",
        });
      }
      if (event.key === "Enter") {
        event.preventDefault();
        executeCommand(state.commandIndex);
      }
    };
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        $("studio").classList.remove("focus");
        $("inspector").hidden = true;
        $("workbench").classList.remove("mobile-nav");
        applyLayout();
      }
      if (!(event.ctrlKey || event.metaKey)) return;
      if (["p", "k", "s"].includes(event.key.toLowerCase())) {
        event.preventDefault();
        if (event.key.toLowerCase() === "s") save();
        else commandPalette(event.key.toLowerCase() === "p" ? "files" : "all");
      }
    });
    window.addEventListener("beforeunload", (event) => {
      if ([...state.buffers.values()].some(dirty)) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
    new ResizeObserver(() => applyLayout()).observe($("workbench"));
    matchMedia("(prefers-color-scheme: dark)").addEventListener(
      "change",
      () => {
        if (state.appearance === "system") applyAppearance();
      },
    );
    try {
      state.workspace = await api("/api/capabilities");
      state.session = state.workspace.session;
      state.recoveryDrafts = readStorage("drafts", {});
      $("workspace-name").textContent = state.workspace.name;
      $("tree-root-name").textContent = state.workspace.name;
      $("workspace-button").onclick = async () => {
        if (selectedWorkspace) {
          const data = await api("/api/workspaces");
          const body = el("div");
          for (const ws of data.workspaces) {
            const link = el(
              "a",
              "button",
              ws.name +
                (ws.remote ? " · Remote" : "") +
                (ws.available ? "" : " · Not mounted"),
            );
            if (ws.available)
              link.href = "/?workspace=" + encodeURIComponent(ws.name);
            body.append(link);
          }
          dialog("Open workspace", body, [
            { label: "Close", run: (d) => d.close() },
          ]);
          return;
        }
        dialog(
          "Local workspace",
          `<p>${escape(state.workspace.workspace)}</p><p>Files are edited locally. Previews and exports use the installed md-doc pipeline.</p>`,
          [{ label: "Close", run: (d) => d.close() }],
        );
      };
      const layout = readStorage("layout", {});
      Object.assign(state, {
        layout: layout.layout || "split",
        navWidth: layout.navWidth || 240,
        editRatio: layout.editRatio || 0.5,
        horizontalRatio: layout.horizontalRatio || 0.5,
      });
      state.appearance = readStorage("appearance", "system");
      state.auto = readStorage("auto", true);
      $("auto-preview").checked = state.auto;
      applyAppearance();
      await loadTree();
      applyLayout();
      const session = readStorage("session", {});
      for (const path of session.paths || [])
        try {
          await openFile(path);
        } catch {}
      if (session.active && state.buffers.has(session.active))
        await openFile(session.active);
      if (session.pinned && state.buffers.has(session.pinned))
        state.pinned = session.pinned;
      await checkChanges();
      loadGit().catch(() => {});
      setInterval(checkChanges, 4000);
      const parameters = new URLSearchParams(location.search);
      if (parameters.get("file")) await openFile(parameters.get("file"));
      else if (parameters.get("sample") === "1") await actions["open-sample"]();
    } catch (error) {
      toast("Could not connect to the workspace: " + error.message, true);
      $("connection-status").textContent = "Disconnected";
    }
    renderDiagnostics();
  }
  document.readyState === "loading"
    ? document.addEventListener("DOMContentLoaded", init)
    : init();
})();
