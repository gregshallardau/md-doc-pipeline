# md-doc-web-editor

A self-contained browser editor for [md-doc-pipeline](https://github.com/gregshallardau/md-doc-pipeline) workspaces. Distributed as a separate Python package so it can be installed independently — `pip install md-doc-web-editor`, then `md-doc-edit serve workspace/`.

```
┌──────────────────────────────────────────────────────────────────┐
│ Files               │ Monaco editor          │ ● Preview         │
│                     │                        │   Config          │
│ workspace/          │ ---                    │   CSS             │
│ ├── acme/ ▼        │ title: Proposal        │                   │
│ │  proposal.md      │ ---                    │   <Live HTML>     │
│ │  _meta.yml        │                        │                   │
│ │  _theme.css       │ # {{ product }}        │   <PDF iframe>    │
│ └── blueshift/      │                        │                   │
│                     │           [Save]       │                   │
│                     │  [Build PDF] [DOCX]   │                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## What it does

- **File tree** of any workspace directory (`.md`, `_meta.yml`, `*.css`)
- **Monaco editor** with syntax highlighting tuned for md-doc:
  - YAML frontmatter, Jinja2 expressions, `[[fields]]`, `?[forms]`, mermaid blocks
  - Known md-doc config keys highlighted distinctly
- **Live HTML preview** rendered client-side (marked.js) with the resolved CSS theme injected
- **Config cascade panel** — every `_meta.yml` layer from repo root down to the doc, plus frontmatter, plus the merged result
- **CSS theme panel** — the resolved `_pdf-theme.css` / `_theme.css` cascade, with a one-click "open this file" shortcut
- **Included templates** bar — every `{% include "..." %}` becomes a clickable button to jump to the included file
- **Build PDF / DOCX** buttons — runs `md-doc build` via subprocess; PDF renders inline in the preview pane, DOCX provides a download link

No database, no auth, no Laravel — just a single Python process, a static SPA, and the `md-doc` CLI as a sidecar for builds.

---

## Quick start

```bash
# Install the editor (depends on FastAPI + uvicorn) and md-doc-pipeline
pip install fastapi 'uvicorn[standard]' md-doc-pipeline
pip install -e ./md-doc-web-editor       # while developing
# OR (when published)
# pip install md-doc-web-editor

# Launch — auto-opens a browser tab on http://127.0.0.1:8765
md-doc-edit serve workspace/

# Other paths and ports
md-doc-edit serve .                          # whole repo
md-doc-edit serve docs/ --port 9000          # different port
md-doc-edit serve workspace/ --no-browser    # don't auto-open
md-doc-edit serve workspace/ --host 0.0.0.0  # expose on network
```

---

## Requirements

| Component | Version | Why |
|---|---|---|
| Python | 3.11+ | match md-doc-pipeline |
| md-doc-pipeline | latest | core library + `md-doc` CLI for builds |
| FastAPI | 0.110+ | server framework |
| uvicorn | 0.27+ | ASGI server |
| `md-doc` CLI on PATH | optional | only needed for the **Build PDF/DOCX** buttons |

---

## API reference

The SPA is the only client, but the API is plain JSON if you want to script against it:

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | SPA entry point (HTML) |
| GET | `/api/tree` | Workspace file tree (recursive) |
| GET | `/api/file?path=...` | Read a file's contents |
| PUT | `/api/file` | Write a file: body `{path, content}` |
| GET | `/api/config?path=...` | Cascade layers + merged config for the doc |
| GET | `/api/css?path=...` | Resolved theme CSS + source path |
| GET | `/api/includes?path=...` | `{% include "..." %}` references and their resolved paths |
| POST | `/api/build` | Run `md-doc build`: body `{path, format}` returns `{token, filename, format}` |
| GET | `/api/build/{token}` | Stream the built artefact (PDF/DOCX) |
| GET | `/static/...` | JS / CSS assets (Monaco loaded from a CDN by default) |

All file paths are workspace-relative; `..` traversal is rejected with HTTP 400.

---

## Behind a proxy / no internet

Monaco and marked are loaded from jsDelivr by default. To self-host:

1. `npm install monaco-editor marked` in the editor's `static/vendor/` dir (or wherever you serve from)
2. Edit `static/index.html` and replace the two CDN script tags with the local paths

This is the same pattern as the Filament plugin's `MD_DOC_MONACO_URL` env var; the SPA is small enough that you can just edit the HTML directly. (A future env var is on the wishlist.)

---

## Concurrent users

This v1 has **no locking** — two users editing the same file will silently overwrite each other on save. If you need locking, use the [Filament v5 plugin](../filament-md-doc/) which has database-backed pessimistic locks. A simple in-process lock for the standalone server is on the roadmap.

---

## Architecture

```
┌──────────────┐     HTTP      ┌─────────────────────────┐
│  Browser SPA │ ◄────────────►│  md-doc-edit (FastAPI)  │
│              │               │                         │
│ - Monaco     │               │ - Workspace file I/O    │
│ - marked.js  │               │ - Config cascade        │
│ - tokenizers │               │ - CSS resolver          │
└──────────────┘               │ - md-doc CLI sidecar    │
                               └────────────┬────────────┘
                                            │ subprocess
                                            ▼
                                    ┌──────────────┐
                                    │  md-doc CLI  │
                                    │ (WeasyPrint) │
                                    └──────────────┘
```

Reads/writes are sandboxed: the server resolves every `?path=` against the workspace root and rejects anything that escapes (via `Path.relative_to` check). The build endpoint generates a random URL-safe token and stores artefacts in a per-token tmp dir; tokens expire after 30 minutes.

---

## License

MIT
