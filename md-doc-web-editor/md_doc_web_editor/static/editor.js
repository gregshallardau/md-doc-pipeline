/**
 * md-doc-web-editor — single-page client.
 *
 * Architecture:
 *   - Monaco editor for the open file
 *   - Right panel with three tabs (preview / config / css)
 *   - Live preview rendered client-side via marked.js with theme CSS injected
 *   - All file I/O via the FastAPI server's /api/* endpoints
 */

(function () {
    'use strict';

    // ── State ────────────────────────────────────────────────────────────────

    const state = {
        editor: null,
        currentPath: null,
        currentType: null,           // md / meta / css
        mergedConfig: {},
        themeCss: "",
        themeSource: null,
        previewTimer: null,
    };

    // ── Helpers ──────────────────────────────────────────────────────────────

    function detectLanguage(fileType) {
        if (fileType === "css") return "css";
        if (fileType === "meta") return "mddoc-yaml";
        return "mddoc-markdown";
    }

    function stripFrontmatter(content) {
        const trimmed = content.trimStart();
        if (!trimmed.startsWith("---")) return content;
        const end = trimmed.indexOf("\n---", 3);
        if (end === -1) return content;
        return trimmed.slice(end + 4).trimStart();
    }

    function substituteVars(html, config) {
        if (!config || typeof config !== "object") return html;
        return html.replace(/\{\{\s*([\w_.]+)\s*\}\}/g, (m, key) => {
            const v = config[key];
            return v !== undefined ? String(v) : m;
        });
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        })[c]);
    }

    async function api(path, opts) {
        const res = await fetch(path, opts);
        if (!res.ok) {
            let detail;
            try { detail = (await res.json()).detail; } catch (_) { detail = res.statusText; }
            throw new Error(`${res.status}: ${detail}`);
        }
        return res.json();
    }

    // ── Tree rendering ───────────────────────────────────────────────────────

    function renderTree(nodes, container) {
        container.innerHTML = "";
        const ul = document.createElement("ul");
        ul.className = "md-doc-tree";
        renderTreeNodes(nodes, ul);
        container.appendChild(ul);
    }

    function renderTreeNodes(nodes, parent) {
        for (const node of nodes) {
            const li = document.createElement("li");
            if (node.type === "dir") {
                const det = document.createElement("details");
                det.className = "md-doc-tree-dir";
                det.open = true;
                const sum = document.createElement("summary");
                sum.textContent = "📁 " + node.name;
                det.appendChild(sum);
                if (node.children && node.children.length) {
                    const childUl = document.createElement("ul");
                    childUl.className = "md-doc-tree";
                    renderTreeNodes(node.children, childUl);
                    det.appendChild(childUl);
                }
                li.appendChild(det);
            } else {
                const btn = document.createElement("button");
                btn.className = "md-doc-tree-file md-doc-tree-file-" + node.type;
                btn.dataset.path = node.path;
                const icon = node.type === "md" ? "📄" : (node.type === "css" ? "🎨" : "⚙️");
                btn.innerHTML = `<span class="md-doc-tree-icon">${icon}</span>${escapeHtml(node.name)}`;
                btn.addEventListener("click", () => openFile(node.path));
                li.appendChild(btn);
            }
            parent.appendChild(li);
        }
    }

    function highlightActiveFile(path) {
        document.querySelectorAll(".md-doc-tree-file").forEach((el) => {
            el.classList.toggle("is-active", el.dataset.path === path);
        });
    }

    // ── File operations ──────────────────────────────────────────────────────

    async function openFile(path) {
        try {
            const data = await api("/api/file?path=" + encodeURIComponent(path));
            state.currentPath = data.path;
            state.currentType = data.type;
            const lang = detectLanguage(data.type);

            if (state.editor) {
                const model = state.editor.getModel();
                if (model) monaco.editor.setModelLanguage(model, lang);
                state.editor.setValue(data.content);
            }

            document.getElementById("md-doc-filename").textContent = data.path;
            document.getElementById("md-doc-save-btn").disabled = false;
            const isMd = data.type === "md";
            document.getElementById("md-doc-build-pdf-btn").disabled = !isMd;
            document.getElementById("md-doc-build-docx-btn").disabled = !isMd;
            highlightActiveFile(data.path);

            await refreshDerived();
            renderPreview();
        } catch (err) {
            alert("Failed to open file: " + err.message);
        }
    }

    async function saveFile() {
        if (!state.currentPath || !state.editor) return;
        const btn = document.getElementById("md-doc-save-btn");
        btn.disabled = true;
        btn.textContent = "Saving…";
        try {
            await api("/api/file", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    path: state.currentPath,
                    content: state.editor.getValue(),
                }),
            });
            btn.textContent = "Saved ✓";
            setTimeout(() => {
                btn.textContent = "Save";
                btn.disabled = false;
            }, 800);
            await refreshDerived();
        } catch (err) {
            alert("Save failed: " + err.message);
            btn.textContent = "Save";
            btn.disabled = false;
        }
    }

    // ── Derived data (config, css, includes) ────────────────────────────────

    async function refreshDerived() {
        if (!state.currentPath) return;
        const path = encodeURIComponent(state.currentPath);
        try {
            const [cfg, css, inc] = await Promise.all([
                api("/api/config?path=" + path),
                api("/api/css?path=" + path),
                api("/api/includes?path=" + path),
            ]);
            state.mergedConfig = cfg.merged || {};
            state.themeCss = css.css || "";
            state.themeSource = css.source || null;

            renderConfigPanel(cfg);
            renderCssPanel(css);
            renderIncludes(inc.includes || []);
        } catch (err) {
            console.error("Failed to refresh derived data:", err);
        }
    }

    function renderConfigPanel(data) {
        const container = document.getElementById("md-doc-panel-config");
        const layers = data.layers || [];
        const merged = data.merged || {};

        if (!layers.length) {
            container.innerHTML = '<p style="color:#9ca3af;font-size:0.8rem">No config loaded.</p>';
            return;
        }

        let html = "";
        for (const layer of layers) {
            const icon = layer.file === "frontmatter" ? "📝" : "⚙️";
            html += `<details class="md-doc-config-layer" open>
                <summary class="md-doc-config-layer-header">${icon} ${escapeHtml(layer.file)}</summary>
                <div class="md-doc-config-layer-body">${renderConfigTable(layer.values)}</div>
            </details>`;
        }
        html += `<details class="md-doc-config-layer md-doc-config-merged">
            <summary class="md-doc-config-layer-header">✅ Merged (final)</summary>
            <div class="md-doc-config-layer-body">${renderConfigTable(merged)}</div>
        </details>`;
        container.innerHTML = html;
    }

    function renderConfigTable(values) {
        let rows = "";
        for (const [k, v] of Object.entries(values)) {
            let display;
            if (Array.isArray(v)) display = v.join(", ");
            else if (typeof v === "boolean") display = v ? "true" : "false";
            else if (v === null || v === undefined) display = "";
            else display = String(v);
            rows += `<tr><td class="md-doc-config-key">${escapeHtml(k)}</td><td class="md-doc-config-value">${escapeHtml(display)}</td></tr>`;
        }
        return `<table class="md-doc-config-table">${rows}</table>`;
    }

    function renderCssPanel(data) {
        const container = document.getElementById("md-doc-panel-css");
        if (!data.source) {
            container.innerHTML = '<p style="color:#9ca3af;font-size:0.8rem">No CSS theme found for this document.</p>';
            return;
        }
        container.innerHTML = `
            <div class="md-doc-css-source-bar">
                <span class="md-doc-css-source-label">Source:</span>
                <code class="md-doc-css-source-path">${escapeHtml(data.source)}</code>
                <button class="md-doc-btn md-doc-btn-sm" id="md-doc-edit-css-btn">Edit ↗</button>
            </div>
            <pre class="md-doc-css-content"><code>${escapeHtml(data.css)}</code></pre>
        `;
        const btn = document.getElementById("md-doc-edit-css-btn");
        if (btn) btn.addEventListener("click", () => openFile(data.source));
    }

    function renderIncludes(includes) {
        const bar = document.getElementById("md-doc-includes");
        if (!includes.length) { bar.hidden = true; return; }
        let html = '<span class="md-doc-includes-label">Included templates:</span>';
        for (const inc of includes) {
            if (inc.found) {
                html += `<button class="md-doc-include-btn" data-path="${escapeHtml(inc.path)}" title="${escapeHtml(inc.path)}">${escapeHtml(inc.name)} ↗</button>`;
            } else {
                html += `<span class="md-doc-include-btn md-doc-include-missing" title="Not found">${escapeHtml(inc.name)}</span>`;
            }
        }
        bar.innerHTML = html;
        bar.hidden = false;
        bar.querySelectorAll(".md-doc-include-btn[data-path]").forEach((el) => {
            el.addEventListener("click", () => openFile(el.dataset.path));
        });
    }

    // ── Live preview (marked.js) ─────────────────────────────────────────────

    function renderPreview() {
        const target = document.getElementById("md-doc-preview");
        if (!state.editor || !target) return;
        const content = state.editor.getValue();
        if (state.currentType !== "md") {
            target.innerHTML = '<p style="color:#9ca3af;font-size:0.8rem">Preview is only shown for .md files. Open a markdown document to see the rendered output.</p>';
            return;
        }
        if (typeof marked === "undefined") {
            target.innerHTML = '<p style="color:#9ca3af;font-size:0.8rem">marked.js still loading…</p>';
            return;
        }
        const body = stripFrontmatter(content);
        let html = marked.parse(body);
        html = substituteVars(html, state.mergedConfig);
        const styleTag = state.themeCss ? `<style>${state.themeCss}</style>` : "";
        target.innerHTML = styleTag + html;
    }

    function debouncedPreview() {
        clearTimeout(state.previewTimer);
        state.previewTimer = setTimeout(renderPreview, 400);
    }

    // ── Build (calls md-doc via the server) ──────────────────────────────────

    async function runBuild(format) {
        if (!state.currentPath || state.currentType !== "md") return;
        const btnId = format === "pdf" ? "md-doc-build-pdf-btn" : "md-doc-build-docx-btn";
        const btn = document.getElementById(btnId);
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = "Building…";
        const target = document.getElementById("md-doc-preview");
        target.innerHTML = '<p style="color:#6b7280;font-size:0.85rem;padding:1rem">Running md-doc build…</p>';

        try {
            // Save first so the build sees the latest content
            await api("/api/file", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    path: state.currentPath,
                    content: state.editor.getValue(),
                }),
            });

            const result = await api("/api/build", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: state.currentPath, format }),
            });

            const url = "/api/build/" + result.token;
            if (format === "pdf") {
                // Show inline in the preview pane
                target.innerHTML = `<iframe class="md-doc-build-iframe" src="${url}" title="Built PDF"></iframe>`;
            } else {
                // DOCX/DOTX — provide a download link
                target.innerHTML = `
                    <div class="md-doc-build-download">
                        <p>Build complete: <code>${escapeHtml(result.filename)}</code></p>
                        <a href="${url}" download class="md-doc-btn md-doc-btn-primary">Download ${format.toUpperCase()}</a>
                    </div>`;
            }
            // Make sure the Preview tab is active so the user sees the result
            switchTab("preview");
        } catch (err) {
            target.innerHTML =
                `<p style="color:#dc2626;font-size:0.85rem;padding:1rem;white-space:pre-wrap">Build failed: ${escapeHtml(err.message)}</p>`;
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }

    // ── Tab switching ────────────────────────────────────────────────────────

    function switchTab(slug) {
        document.querySelectorAll(".md-doc-tab").forEach((t) =>
            t.classList.toggle("md-doc-tab-active", t.dataset.tab === slug));
        ["preview", "config", "css"].forEach((s) => {
            const panel = document.getElementById("md-doc-panel-" + s);
            if (panel) panel.hidden = (s !== slug);
        });
    }

    function setupTabs() {
        document.querySelectorAll(".md-doc-tab").forEach((tab) => {
            tab.addEventListener("click", () => switchTab(tab.dataset.tab));
        });
    }

    // ── Boot ─────────────────────────────────────────────────────────────────

    async function loadTree() {
        try {
            const data = await api("/api/tree");
            renderTree(data.tree, document.getElementById("md-doc-tree"));
        } catch (err) {
            document.getElementById("md-doc-tree").innerHTML =
                `<p style="color:#dc2626;font-size:0.8rem;padding:0.5rem">${escapeHtml(err.message)}</p>`;
        }
    }

    function bootMonaco() {
        require(["vs/editor/editor.main"], function () {
            if (typeof registerMdDocLanguages === "function") {
                registerMdDocLanguages(monaco);
            }
            const container = document.getElementById("md-doc-monaco");
            state.editor = monaco.editor.create(container, {
                value: "",
                language: "mddoc-markdown",
                theme: "mddoc-light",
                fontSize: 13,
                minimap: { enabled: false },
                wordWrap: "on",
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
            });
            state.editor.onDidChangeModelContent(debouncedPreview);
            // Cmd/Ctrl-S to save
            state.editor.addCommand(
                monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
                () => saveFile()
            );
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        setupTabs();
        loadTree();
        bootMonaco();
        document.getElementById("md-doc-save-btn").addEventListener("click", saveFile);
        document.getElementById("md-doc-build-pdf-btn").addEventListener("click", () => runBuild("pdf"));
        document.getElementById("md-doc-build-docx-btn").addEventListener("click", () => runBuild("docx"));
    });

}());
