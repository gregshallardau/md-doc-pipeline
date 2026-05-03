# Live Preview Design

**Date:** 2026-05-03  
**Status:** Approved

## Problem

Editing `.md` documents in VSCode produces no usable preview. The pipeline applies Jinja2 templating, CSS themes, and template fragment includes — none of which VSCode's built-in markdown preview understands. Authors need to see the rendered result while editing.

---

## Approach: Preview Server + Thin VSCode Extension

Two components:

1. **`md-doc preview`** — a new Python CLI command that starts a local HTTP server, renders the document using the existing pipeline, watches for file changes, and pushes live-reload events to connected browsers via Server-Sent Events (SSE).
2. **VSCode extension** — a thin TypeScript wrapper (~80 lines) that spawns the server for the currently open file and loads the result in a WebviewPanel. The extension contains zero rendering logic.

The server works standalone (browser tab only). The extension is an optional convenience for in-editor panel support.

---

## Data Flow

```
User opens doc.md in VSCode
  → Extension detects .md file
  → spawns: md-doc preview doc.md --port 8765
  → WebviewPanel loads http://localhost:8765

md-doc preview starts:
  1. render immediately → serve at GET /
  2. watch: doc.md + cascade _meta.ymls + theme CSS + templates/ dirs
  3. open SSE stream at GET /events

On file change:
  file change detected → pipeline re-renders → SSE push → browser reloads
```

---

## `md-doc preview` Command

### CLI

```
md-doc preview <path> [options]

  --mode     html|pdf      Render mode (default: html)
  --trigger  save|idle|manual  When to rebuild (default: save)
  --port     N             Server port (default: 8765)
  --idle-ms  N             Debounce delay for idle trigger (default: 500)
  --poll-ms  N             File poll interval in ms (default: 1000)
  --open                   Auto-open browser on start
```

### Server Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Rendered preview page |
| `GET /events` | SSE stream — browser reconnects automatically |
| `GET /preview.pdf` | PDF bytes (PDF mode only) |
| `GET /rebuild` | Trigger an immediate rebuild (available in all modes) |

### Render Modes

**HTML mode** (default, ~100ms): Runs `config.load_config` → `renderer.render` → `pdf._build_html`, injects an SSE reload script, and serves the HTML directly. Fast enough for on-save or idle triggers.

**PDF mode** (~2-3s): Same pipeline, then WeasyPrint generates `/tmp/preview.pdf`. The main page is an HTML wrapper with `<embed src="/preview.pdf">`. SSE reloads the embed src on rebuild.

The injected reload script in every page:

```html
<script>
  new EventSource('/events').onmessage = () => location.reload();
</script>
```

### Trigger Modes

| Mode | Behaviour |
|---|---|
| `save` | Rebuild on every detected file modification |
| `idle` | Rebuild after `--idle-ms` of no further changes (debounce) |
| `manual` | No automatic watching; only rebuilds via `GET /rebuild` |

### File Watching

Watched paths (resolved at startup from the config cascade):

- The target `.md` file
- All `_meta.yml` files from document directory up to repo root
- The resolved CSS theme file (`_pdf-theme.css` cascade)
- Any `templates/` directories in the cascade

**WSL / mounted paths:** WSL-mounted paths (e.g. `/mnt/c/...`, network shares) don't reliably trigger `inotify` events for changes made from the Windows side. The watcher checks if any watched path starts with `/mnt/`; if so, it uses `watchdog.PollingObserver` for all paths in that session. Native WSL paths (not under `/mnt/`) use `InotifyObserver`. Poll interval is configurable via `--poll-ms` (default 1000ms).

### Implementation

- HTTP server: Python stdlib `http.server.HTTPServer` — no new web framework dependency
- File watching: `watchdog` (new dependency, added to core deps)
- SSE: open response streams held in a thread-safe list; watcher thread pushes `data: reload\n\n` to each on rebuild
- New file: `md_doc/preview.py`
- Updated file: `md_doc/cli.py` — add `preview` command

---

## VSCode Extension

### Location

```
vscode-extension/
  src/extension.ts    ← activate(), commands, WebviewPanel, child process
  package.json        ← contributes commands, settings
  tsconfig.json
  README.md
```

### Commands

| Command | Description |
|---|---|
| `md-doc: Open Preview` | Start server for current file, open WebviewPanel |
| `md-doc: Stop Preview` | Kill server, close panel |
| `md-doc: Rebuild Now` | POST to /rebuild (manual trigger mode) |

No default keybindings — users assign their own via `keybindings.json`.

### Status Bar

A status bar item shows the current state:
- `⬤ md-doc: watching · html · save` (active)
- `○ md-doc: idle` (inactive)

Clicking toggles the preview on/off.

### Behaviour

1. On `md-doc: Open Preview`: check if a server is already running on the configured port; if not, spawn `md-doc preview <current-file> <settings-flags>` as a managed child process; open WebviewPanel loading `http://localhost:<port>`.
2. On panel dispose: kill the child process.
3. On active editor change to a different `.md` file: show a VSCode info notification "Switch preview to &lt;filename&gt;?" with a Yes button. If `autoOpen` is true, switch automatically without prompting.

### VSCode Settings

```json
"md-doc.preview.mode":     "html",   // "html" | "pdf"
"md-doc.preview.trigger":  "save",   // "save" | "idle" | "manual"
"md-doc.preview.port":     8765,
"md-doc.preview.pollMs":   1000,
"md-doc.preview.autoOpen": false
```

---

## Out of Scope (v1)

- Multi-file preview (one preview server per invocation)
- Authentication on the preview server
- Diff/change highlighting in the preview
- Preview of DOCX/DOTX output
