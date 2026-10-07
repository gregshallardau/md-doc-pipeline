# md-doc-web-editor

A self-contained browser editor for [md-doc-pipeline](https://github.com/gregshallardau/md-doc-pipeline) workspaces. The editor and pipeline must be installed in the same virtual environment. Use the source-checkout instructions below; they do not rely on either package being published to PyPI.

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

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.11+ first.
Run these commands from the repository root:

```bash
git clone https://github.com/gregshallardau/md-doc-pipeline.git
cd md-doc-pipeline
uv venv
uv sync --group editor

# Launch from the project environment without activating it
uv run --group editor md-doc-edit serve workspace/ --no-browser
```

Open http://127.0.0.1:8765/. Keep `--group editor` on `uv run` commands:
`uv run` synchronizes the environment and otherwise removes the optional editor.
Omit `--no-browser` to launch a browser automatically.

If you prefer activated commands, after the sync use:

```bash
# Linux / macOS
source .venv/bin/activate
md-doc-edit serve workspace/
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
md-doc-edit serve workspace/
```

In Windows Command Prompt, activate with `.venv\Scripts\activate.bat`.
Other launch options (from the repository root):

```bash
uv run --group editor md-doc-edit serve .
uv run --group editor md-doc-edit serve workspace/ --port 9000
uv run --group editor md-doc-edit serve workspace/ --host 0.0.0.0
```

For an existing virtual environment or an offline source deployment:

```bash
uv venv
uv pip install --python .venv/bin/python -e . -e ./md-doc-web-editor
.venv/bin/md-doc-edit serve workspace/ --no-browser
```

On Windows replace `.venv/bin/python` with `.venv/Scripts/python.exe` and
`.venv/bin/md-doc-edit` with `.venv/Scripts/md-doc-edit.exe`. Packages still
need network access or a populated local package cache at install time.


---

## Requirements

| Component | Version | Why |
|---|---|---|
| Python | 3.11+ | match md-doc-pipeline |
| md-doc-pipeline | latest | core library + `md-doc` CLI for builds |
| FastAPI | 0.110+ | server framework |
| uvicorn | 0.27+ | ASGI server |
| Pipeline in editor environment | required | imported at startup; builds use that environment’s Python |

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

## Save and preview behavior

Switching files prompts before discarding unsaved changes; closing the tab also
warns when edits are unsaved. A build uses the file and content selected when the
button was clicked, even if another file is opened while the build runs.

HTML previews use sandboxed frames with scripts, forms and network resources
blocked. Theme CSS is confined to the frame. Use the PDF/Word build for final
asset and math rendering. Failed builds are removed immediately; expired builds
are swept every minute and remaining builds are removed on graceful shutdown.
Abandoned server directories are recovered on the next startup after the timeout
and token retention period have passed.
