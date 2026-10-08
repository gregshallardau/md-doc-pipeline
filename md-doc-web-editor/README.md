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
- **CSS theme panel** — the theme the PDF builder would use, with a one-click "open this file" shortcut. In each folder from the document up to the workspace, `_pdf-theme.css` comes before the shared `_theme.css`; `@import`s inside the workspace are inlined so the preview is styled, and the Word-only `_docx-theme.css` is ignored
- **Included templates** bar — every `{% include "..." %}` becomes a clickable button to jump to the included file
- **Build PDF / DOCX** buttons — runs `md-doc build` via subprocess; PDF renders inline in the preview pane, DOCX provides a download link. The API also builds `.dotx` templates (`format: "dotx"`)

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
uv run --offline --no-sync md-doc-edit serve workspace/ --no-browser
```

Open http://127.0.0.1:8765/. `md-doc-edit serve [WORKSPACE]` takes `--host` (default `127.0.0.1`), `--port` (default `8765`) and `--no-browser`. `--offline --no-sync` uses the installed environment
without resolving or downloading dependencies. Include `--group editor` when
explicitly syncing again to retain the optional editor.
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
uv run --offline --no-sync md-doc-edit serve .
uv run --offline --no-sync md-doc-edit serve workspace/ --port 9000
uv run --offline --no-sync md-doc-edit serve workspace/ --host 0.0.0.0
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
| POST | `/api/build` | Run `md-doc build --no-lint`: body `{path, format}` with `format` one of `pdf`, `docx`, `dotx` returns `{token, filename, format}` |
| GET | `/api/build/{token}` | Stream the built artefact (PDF inline; DOCX/DOTX as downloads) |
| GET | `/static/...` | Bundled JS / CSS / fonts / Monaco workers (all local) |

All file paths are workspace-relative; `..` traversal is rejected with HTTP 400.

---

## Offline operation

All browser dependencies are shipped with the editor: Monaco 0.52.2 and
marked 17.0.5, with their licenses in `static/vendor/`. No CDN, telemetry,
remote fonts or update checks are needed while editing or exporting.
A Content Security Policy restricts browser resources to the local server;
PDF rendering rejects network URLs (including remote CSS, fonts and images)
and network file shares before fetching them. Put document assets in local
files. Remote resources are omitted; hyperlinks in exports remain links and
are not fetched during export. Preview links cannot navigate to external sites.

Install once while online, from the repository root:

```bash
uv venv  # skip if .venv already exists
uv sync --group editor
```

Then launch without dependency resolution or downloads:

```bash
# Linux / macOS
.venv/bin/md-doc-edit serve workspace/ --no-browser
```

```powershell
# Windows PowerShell
.\.venv\Scripts\md-doc-edit.exe serve workspace/ --no-browser
```

Alternatively, `uv run --offline --no-sync md-doc-edit serve workspace/ --no-browser`
uses the existing environment without syncing. Open http://127.0.0.1:8765/.
The server defaults to loopback. Keep it there for local use.

If packaged Monaco assets are missing, a local text editor preserves basic
editing, saving and preview without fetching a replacement. Properly installed
packages include Monaco and its workers, languages and font assets.

Offline operation applies to the local editor and exports. Explicit remote
storage commands such as `md-doc sync` are separate online operations; do not
use those in a no-network environment. OS/browser background traffic is outside
the application's control; workplace network policy remains the outer boundary.


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
