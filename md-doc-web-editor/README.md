# md-doc Document Studio

A local browser workspace for the [md-doc pipeline](https://github.com/gregshallardau/md-doc-pipeline). Edit Markdown, inherited metadata and themes, review the actual generated PDF, and export PDF, DOCX, DOTX or PowerPoint. Monaco provides the source editor; PDF.js displays the pipeline's immutable output. All browser assets are bundled locally.

## Launch

From the repository root:

```bash
uv sync --group editor
uv run --offline --no-sync md-doc-edit
```

With no directory, the editor discovers local folders under `workspace/` and the remote shares in `workspace/remote-workspaces.yml`, falling back to examples on a fresh checkout. The workspace button switches between available workspaces; unmounted shares remain listed. Each workspace has its own editor session, buffers and output artifacts. New workspaces appear without restarting.

An available configured remote workspace is opened before local samples. Its configured `path` is used exactly; relative paths resolve from the project directory. The header identifies remote workspaces and the explorer displays the full directory path. **Choose document folder** lets you explicitly open a nested folder without changing the configuration or guessing where documents live.

The Files rail button toggles the sidebar. Click the workspace row to collapse its files, or use **Expand all / Collapse all** for folders. New sessions open the first two folder levels; folder badges count Markdown documents recursively. PDFs, Office outputs, images and authoring files appear alongside Markdown. PDF/image files open in a browser tab and Office files download. **Dark mode / Light mode** is available directly in the header.

To open all samples as one directory:

```bash
uv run --offline --no-sync md-doc-edit serve examples/
```

The browser opens at **http://127.0.0.1:8765/**. Choose **Open a sample** for a complete branded document. To work on live documents:

```bash
uv run --offline --no-sync md-doc-edit serve workspace/
uv run --offline --no-sync md-doc-edit serve workspace/acme/ --port 9000
```

Add `--no-browser` to start only the server. The editor and pipeline must be installed in the same Python environment. Include `--group editor` in subsequent `uv sync` commands to keep the editor installed. Installation needs internet access or a populated package cache; running the installed editor does not.

## Editing and preview

- **Source**: Monaco with Markdown, Jinja2, Word fields, PDF forms and YAML highlighting. Each tab retains its buffer, cursor, undo stack and scroll position.
- **Write**: visual editing for supported paragraphs and headings. Frontmatter, templates, forms, tables, HTML, images and other advanced syntax remain protected source blocks. Clicking a protected block opens it in Source. Untouched blocks retain their original source.
- **Output preview**: the actual PDF, including the complete theme, imported CSS, local fonts and images, cover, page breaks, diagrams, headers and footers. Automatic rendering starts after 800ms of idle time; pause it or refresh manually for large documents.
- **Unsaved edits**: previews include open unsaved document, YAML, CSS and template buffers. The renderer uses an isolated project snapshot. Preview and export never save these buffers or generate themes in your source project.
- **Pinned document**: opening its metadata, theme or included template keeps the document visible in the preview. Opening another document selects that document's output.
- **Current output**: a status label distinguishes current, updating, out-of-date and failed output. The last successful PDF remains visible during updates and errors. Errors and renderer logs are available from the status bar.

Drag either separator to resize navigation or source/preview. Focus a separator and use arrows (Shift for larger steps), Home/End, or double-click to reset. **Change layout** offers side-by-side, stacked, source-only and preview-only. Layouts and appearance persist per workspace. Narrow windows use a single main pane and navigation drawers.

The PDF viewer supports page navigation, fit page/width, zoom, text selection, search, lazy thumbnails, bookmarks and maximised preview. Form test mode is available in Settings; test values do not change source defaults or exported artifacts. Print opens the displayed PDF in a browser tab for the browser's print controls.

## Document tools

The inspector shows editable common properties, the configuration cascade and provenance, the resolved PDF theme, included templates, and documented merge fields. Simple property changes update individual frontmatter lines. Structured YAML is edited in Source to preserve its syntax. Inherited metadata, theme and template files can be opened without changing the selected document.

Use the insertion toolbar for formatting, tables, fields, PDF forms, page breaks, Mermaid, includes and slide directives. Local raster images can be copied into an asset directory; existing filenames are never silently overwritten. New document scaffolds support reports, fillable PDF forms, decks and blank documents. File actions include folder creation, duplicate, rename/move and recoverable trash. After moving a document, review relative asset/include references; the studio preserves them as written.

Workspace search finds text in Markdown, YAML and CSS. The outline navigates source headings. Quick open and the command palette provide access to documents and actions.

| Shortcut | Action |
| --- | --- |
| Ctrl/⌘ P | Quick open |
| Ctrl/⌘ K | Files and commands |
| Ctrl/⌘ S | Save active buffer |
| Ctrl/⌘ B / I | Bold / italic in Source |
| Escape | Close dialog or leave focus mode |
| Arrows on a separator | Resize panes |

## Saves and recovery

Save is an explicit action. Atomic, revision-checked writes detect external edits and offer a comparison before choosing the disk version or saving your draft. Switching tabs preserves unsaved changes. Closing an unsaved tab offers Save, Discard or Cancel.

Drafts and session preferences are stored in this browser's local storage, scoped to the workspace path. Reloading or reopening restores drafts without writing them to disk. If the disk revision changed, review the recovered draft before saving. Private browsing, storage limits and clearing browser data can remove these drafts; save important work to disk.

External file changes are checked every four seconds while the tab is visible. Clean buffers refresh; dirty buffers are preserved and offer a comparison. Dependency changes refresh the pinned preview.

## Source control

The Git panel shows the repository branch, workspace changes, staged changes, diffs and recent workspace history. Stage/unstage individual files, create a feature branch, commit staged workspace files, or explicitly pull with `--ff-only`. Git must be installed and the selected workspace must be inside a repository.

Commits use staged content and preserve unstaged edits and staged files outside the selected workspace. Commits, branch changes and pulls run only when selected in the interface. Git authentication and commit identity use the machine's existing configuration. Rename paths and deleted files are represented by Git's status. The editor has no push action.

## Export

Export uses the current editing snapshot, including unsaved dependency buffers. Downloading the displayed PDF reuses that exact immutable artifact. Save remains separate.

PDF has an authoritative visual preview. DOCX and DOTX use the Word theme and native pipeline builders; PPTX uses the slide builder. These formats are downloadable and do not claim exact browser/Word/PowerPoint layout equivalence. No Office conversion service is required.

## Local operation and limits

The editor defaults to loopback and is intended for use on your own machine. It is not an authenticated multi-user hosting service. Browser writes require the local session token and reject cross-origin requests. Document scripts and external links cannot execute in the PDF viewer. PDF assets are restricted to the project snapshot; remote resources are blocked.

Snapshots retain project-relative paths so the CLI's cascade, template resolution, CSS imports and assets continue to work when a subdirectory is selected. Hidden directories, symlinks, dependency packages and generated outputs are excluded. Preview can use inherited project metadata/themes/templates; there is no general filesystem browser.

Limits: 128 MiB / 10,000 snapshot inputs, 20 MiB text files, 100 unsaved buffers, 10 MiB uploaded raster images, two render workers, eight pending/running jobs, and 180 seconds per render. Artifact leases expire after 30 minutes and are refreshed by downloads. Refresh an expired preview to produce it again. Temporary snapshots are discarded after rendering; artifacts are cleaned on expiry/shutdown.

## Service APIs

| Endpoint | Purpose |
| --- | --- |
| GET `/api/capabilities` | Workspace, project context, formats, limits and local session token |
| GET `/api/tree` | Workspace authoring files |
| GET/PUT `/api/file` | Buffer contents and revision; conditional atomic save |
| POST `/api/preview/jobs` | Immutable buffer snapshot; format, revision, client and purpose |
| GET/DELETE `/api/jobs/{id}` | Poll render state, inspection, diagnostics and artifact; cancel |
| GET `/api/artifacts/{id}` | Display artifact; `?download=true` for attachment |
| GET `/api/changes` | Dependency change signature |
| GET `/api/search?q=…` | Workspace text matches |
| POST `/api/files/action` | Scaffold, duplicate, move, trash, restore |
| POST `/api/assets` | Validated base64 raster image upload |
| GET `/api/git/status`, `/api/git/diff` | Workspace source control inspection |
| POST `/api/git/action` | Explicit stage, unstage, commit, branch or pull |

Snapshot job responses include effective configuration, provenance, theme, fields and includes. Editable inherited resources use scoped `project:` handles. Legacy config/CSS/includes and saved-file `/api/build` endpoints remain available for existing integrations. Browser mutations send `X-Editor-Token` from capabilities; cross-origin requests are rejected.

## Verification

```bash
.venv/bin/pytest md-doc-web-editor/tests --no-cov
npm ci --prefix tests/browser
node tests/browser/studio.cjs
```

The browser suite uses a disposable Git project and blocks all nonlocal browser requests. It exercises real Monaco, PDF rendering, resizing, drafts, conflicts, visual editing, inspector dependencies, Git and responsive layouts. Set `MD_DOC_TEST_BROWSER` for a locally installed Chromium executable and `MD_DOC_TEST_PYTHON` for a packaged editor environment.

Build distributable assets and run the installed-package smoke check:

```bash
uv build md-doc-web-editor
python md-doc-web-editor/tests/smoke_installed.py
```

Run the smoke check with the installed environment's Python. The built wheel includes Monaco, marked, PDF.js, fonts, CMaps, WebAssembly decoders, icons, and vendor licenses; no frontend build or runtime Node installation is needed.
