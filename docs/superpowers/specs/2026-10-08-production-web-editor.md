# Production web editor specification

Status: design and implementation record. The local studio is implemented on `feature/production-editor`; the original requirements below retain the longer-term product direction.

## Implementation record

The branch delivers a redesigned studio shell, locally bundled PDF.js, exact automatic PDF snapshots, source and protected-block visual editing, tabs, persisted resizable layouts, navigation/search/outline, property/theme/field inspection, inherited dependency buffers, local image insertion, atomic revision-safe saving, browser draft recovery, recoverable trash, and workspace-scoped Git controls. DOCX, DOTX and PPTX export through the existing builders.

The frontend uses maintainable formatted JavaScript and CSS with Monaco rather than introducing a framework and runtime build requirement. Dependency changes are polled every four seconds while visible. The viewer delegates printing to a browser PDF tab. Exact Office visual conversion and unrestricted rich block editing remain future work; advanced syntax is protected and edited in Source. The studio is intended for local use rather than network multi-user hosting.

Validation includes real PDF artifact/unsaved dependency tests, write conflicts, cancellation and resource cleanup, image validation, staged-only Git commits preserving other index entries, a full pipeline regression run, and 27 real Chromium checks with external requests blocked. The wheel bundles its editor, viewer, worker, font/CMap/decoder assets and licenses; installed-package startup and output are smoke-tested outside the checkout.

## Product outcome

Build a polished local document studio for authoring branded reports, proposals, forms, Word templates, and slide decks. A user can open a sample, edit it, see the real output, inspect inherited settings, and export without needing terminal commands. Preserve the repository's plain-file workflow and offline operation.

The two immediate requirements are authoritative previews with the complete document styling and user-resizable preview/editor panes. These are release gates, not optional visual enhancements.

Reference: [the user's Reddit example](https://www.reddit.com/r/sideprojects/comments/1skvhc0/i_spent_nearly_2_years_building_this_side_project/). Its author describes visual editing, source mode, split views, toolbar commands, and drag-and-drop. Use this as a product-quality benchmark. The linked lightbox image could not be retrieved during research; this specification does not claim a visual inspection or copy its exact appearance.

## Current implementation findings

- `static/editor.js::renderPreview` uses marked.js and variable substitution, rather than the Python document pipeline. Includes, forms, Mermaid, cover composition, running furniture, and pagination consequently diverge from output.
- `isolatedPreview` injects theme CSS into a bare body. Pipeline-specific wrappers and generated CSS are absent. Its CSP permits only embedded images/fonts, blocking ordinary local assets and CSS imports. Browser layout also cannot reproduce WeasyPrint's paged layout.
- `server.py::_resolve_css` searches only to the selected workspace boundary, ignores `pdf_theme`, and permits `_docx-theme.css` ahead of `_theme.css`. The PDF builder uses a different cascade and repository boundary.
- `static/editor.css` fixes columns at `240px 1fr 380px`. There are no splitters or persistent layout preferences.
- A built PDF can be embedded today, but builds save the document first, replace the preview contents, and provide limited failure feedback. The current browser-native PDF frame does not provide a consistent application-controlled viewer.
- Config inspection reads saved frontmatter. Editing YAML in the buffer can leave the inspection and preview context behind the editor.

## Workspace and visual design

Use a quiet document-studio interface: neutral surfaces, restrained blue accent, fine separators, consistent typography, a unified line-icon set, and visible focus states. Avoid emoji icons, excessive cards, oversized buttons, and nested panels. Documents retain their own brand colours independently of the application theme.

Desktop layout:

```text
Workspace / recent files              Quick open          Commands   Export
----------------------------------------------------------------------------
Files / Search / Outline | document tabs                    | Preview toolbar
                        | breadcrumbs and formatting tools | format / zoom
resizable navigation    |                                  | page canvas
                        | source or visual editor          | thumbnails
                        |                                  |
----------------------------------------------------------------------------
Saved / Unsaved • document path       Render status        Diagnostics
```

The inspector is a collapsible drawer for Properties, Theme, Fields, and Dependencies; opening it must not displace the preview with an unrelated tab. Diagnostics expand from the status bar. Source, Split, and Preview layouts are one-click choices. A focus mode hides surrounding navigation while keeping an obvious exit control.

Initial widths: navigation 240px; remaining space divided equally between source and preview. Navigation range 180–420px. Source minimum 320px; preview minimum 320px. At narrow widths, use one main pane at a time and navigation/inspector drawers rather than crushing all columns.

Both vertical boundaries support pointer dragging and keyboard adjustment. Use accessible separators with orientation and current/min/max values; arrow keys move 16px, Shift+arrow 64px, Home/End go to limits. Double-click resets the split. Pointer capture or a temporary drag shield prevents iframe interception. Preserve widths per workspace, clamp restored widths to the current viewport, and call Monaco layout through ResizeObserver. Also support a horizontal source/preview layout, preview maximisation, and restoring the previous layout.

Application chrome defaults to system appearance, with explicit light and dark choices. PDF pages remain faithful to the document. Define colour, spacing, typography, radius, elevation, and interaction tokens before building screens. Use 4/8px spacing increments, 13–14px chrome text, 16px comfortable authoring text, and 28–32px compact controls with adequate hit areas. Reduced-motion settings disable decorative animation.

## Authoritative preview contract

PDF is the default final-output preview. Display the PDF produced by the same renderer, config resolver, theme resolver, asset handling, and PDF builder used by export. Cover pages, page geometry, breaks, headers, footers, fonts, tables, diagrams, images, CSS imports, custom properties, and form appearance must match that artifact.

Offer an optional fast HTML view labelled “Draft HTML”. It uses shared server-side preparation and is never described as pagination-accurate. The PDF view is labelled “PDF output”. Typing must not silently revert an output preview to marked.js HTML.

Preview unsaved buffers without saving source files. Capture an immutable snapshot of the document and open dependency buffers. Resolve inherited metadata, templates, themes, and local assets against their original logical paths. Refactor shared pipeline preparation into a supported service rather than reproducing it in JavaScript. A virtual filesystem/overlay must cover config, template loading, CSS imports, and assets; moving a temporary Markdown file alone is insufficient because it changes cascade semantics. Preview must not generate default theme files in the repository; use an in-memory fallback and report it.

Resolve the selected workspace's repository context consistently with CLI builds. Ancestor dependencies can be read within the approved project context and appear in the inspector as inherited files. Do not turn this into a general filesystem-serving endpoint. Assets outside allowed roots produce an actionable diagnostic.

Each preview carries document ID, revision, dependency fingerprint, output format, and artifact ID. A response can replace the viewer only when these still match current state. Keep the last successful output visible during updates and failures. Display “Updating”, “Current”, “Out of date”, or “Render failed” alongside the revision time. Never show an older artifact as current.

Default automatic rendering begins after 800ms idle; manual refresh is always available. Coalesce queued requests for the same document, bound worker concurrency, cancel queued stale jobs, and terminate active work safely when cancellation is supported. Changes to inherited metadata, templates, CSS imports, fonts, and images invalidate dependent previews. Auto refresh can be paused for large documents.

Export offers current-buffer snapshot or saved-file output explicitly when they differ. Exporting the displayed snapshot reuses its immutable artifact, so the downloaded PDF is the file being viewed. Saving remains a separate intentional action.

### Viewer

Bundle a maintained PDF viewer locally with text selection, find, thumbnails, document outline where available, page jump, page count, fit width/page, 50–200% presets, continuous/single-page modes, download, print, and fullscreen. Virtualise offscreen page canvases and release resources when artifacts change. Preserve reading position and zoom through refresh; clamp if page count changes. Provide a download/open fallback if the viewer fails.

Form fields support an explicit test mode. Test values stay separate from source defaults and preview downloads unless the user chooses a supported filled-form export. Unsupported form-viewer behaviour must be visible.

DOCX/DOTX are downloadable artifacts with format-specific theme inspection. A PDF approximation must be labelled clearly; do not promise Word's exact pagination in a browser. Exact Word visual preview requires an evaluated conversion service and comparison fixtures. PPTX export is supported; an exact slide preview requires rendering the produced deck with an evaluated local converter. Until then label any HTML slide representation as a draft. Surface converter availability through capabilities rather than broken controls.

## Authoring experience

Retain Monaco as the reliable source editor. Add tabs with dirty indicators, per-file undo/cursor/scroll state, quick open, breadcrumbs, document outline, workspace search, find/replace, command palette, and shortcuts displayed in menus. Closing dirty tabs offers Save, Discard, or Cancel. Restore sessions without silently overwriting disk contents.

Provide a compact formatting toolbar for headings, lists, links, tables, images, page breaks, fields, forms, includes, Mermaid, and slide directives. Commands operate at the selection and preserve undo history. Field and template pickers use the resolved schemas/search paths. Asset insertion copies to a selected project asset directory and inserts a valid relative reference; handle filename collisions explicitly.

Add guided properties for common metadata, cover, headers, footers, output formats, and form settings. Show whether a value is inherited or overridden and link to its source. Removing an override restores inheritance. Preserve comments and unrelated YAML when editing guided properties; unsupported YAML constructs fall back to source editing rather than rewriting the entire file.

Introduce visual editing after rendering correctness and file reliability. Visual mode must preserve Jinja2, merge fields, form shorthand, raw HTML, Mermaid, comments, and slide directives as structured protected blocks. No automatic conversion that loses syntax. Unsupported sections remain editable in source. Release visual mode only after round-trip fixtures prove that opening and saving does not alter untouched content.

Keep the selected document preview pinned when opening its CSS, metadata, or included template. Show which document is being previewed. Provide an obvious “Preview this document” action to change that target.

## Files, reliability, and recovery

Support new document/folder from pipeline scaffolds, rename, move, duplicate, refresh, and delete with confirmation and recoverable trash where feasible. Asset references are audited during moves; offer a concrete change list before updating references. Do not silently rewrite arbitrary Jinja expressions.

Reads return a revision/etag. Writes require the matching revision and use atomic replacement. An external edit produces a conflict view with disk/buffer comparison and explicit resolution. Filesystem notifications refresh the tree and clean buffers; dirty buffers are never replaced automatically. Detect editor-tab and process concurrency through revision checks.

Persist recoverable draft buffers locally, scoped to workspace identity. On restart present recovered changes with comparison to disk. Provide draft deletion and explain where drafts live. Test storage quota failures and browser-private mode; do not claim recovery succeeded when persistence fails.

Empty state offers “Open a sample” and a short explanation of Source, Preview, and Export. No mandatory lengthy onboarding. Loading, missing-file, disconnected-server, permission, expired-artifact, and unavailable-dependency states each provide a clear next action. Inline diagnostics link to file/line when available and keep full build logs in an expandable panel.

## Frontend and service architecture

Proposed architecture: typed component frontend with a local build pipeline, retaining FastAPI and Monaco. Select the framework during implementation planning based on team maintenance needs; framework choice is not the quality gate. Ship compiled assets and licensed vendor dependencies in the Python package; no CDN or runtime Node requirement. Separate workspace, document buffers, layout preferences, render jobs, artifacts, and diagnostics into explicit state modules.

Proposed API contracts:

| Endpoint | Contract |
| --- | --- |
| GET `/api/capabilities` | Available output engines, converters, viewer support, limits |
| GET/PUT `/api/file` | Content and revision; conditional atomic writes; conflict response |
| POST `/api/preview/jobs` | Logical document path, snapshot buffers, format, client revision; returns job ID |
| GET `/api/jobs/{id}` | Queued/running/succeeded/failed/cancelled state, revision, diagnostics, artifact |
| DELETE `/api/jobs/{id}` | Idempotent cancellation request |
| GET `/api/events` | Workspace changes and job updates; reconnect sequence support |
| GET `/api/artifacts/{id}` | Immutable output with appropriate MIME, etag, expiry |
| POST `/api/inspect` | Snapshot-aware effective config, value provenance, themes, fields, dependencies |
| POST `/api/export/jobs` | Snapshot or saved-source export; independent of saving |

Validate requests and return structured errors with code, user-facing message, source locations, and recoverable action. Set explicit job timeout, input-size, artifact-size, retention, and worker limits after representative benchmarks. Expose progress stages honestly; avoid fabricated percentages. Clean artifacts on expiry/shutdown and handle reconnects without duplicating builds.

Preserve loopback and offline operation. Validate origin for writes and job creation, retain path/symlink boundaries, reject external asset fetching, and isolate preview content. A local-only session token protects mutating APIs without a sign-in screen. PDF viewing must not allow embedded document actions to execute application commands. Broader network hosting and collaboration need a separate authentication/authorization design.

## Performance and accessibility targets

Proposed acceptance budgets on documented reference hardware: input-to-editor response under 50ms p95; splitter movement without visible lag; cached small-document preview under 1s; uncached representative 10-page PDF under 3s after idle debounce. Benchmark a 100-page report and a large tree separately, report results, and adjust explicit budgets with evidence before release. Rendering must not block file save or typing.

All core tasks work by keyboard. Provide accessible names, predictable focus return, live announcements for saves/errors, tab semantics, keyboard tree navigation, sufficient contrast, and 200% browser-zoom support. Automated accessibility checks are supplemented with manual keyboard and screen-reader review. Supported desktop browsers are current Chromium and Firefox; include Safari in release validation when hardware is available.

## Delivery sequence

1. **Rendering foundation:** shared snapshot-aware pipeline, exact PDF jobs, dependency tracking, error states, golden fixtures. Remove misleading client-side preview as the default.
2. **Studio shell:** design tokens, tabs, splitters, persistent layouts, responsive drawers, status bar, command palette, accessible navigation.
3. **Document viewer:** bundled PDF viewer, page navigation/zoom/search, automatic refresh, snapshot export, pinned preview, cancellation and performance work.
4. **Reliable authoring:** revision-safe saves, conflict handling, draft recovery, search, scaffold actions, properties/theme/field inspectors, insertion tools.
5. **Visual authoring and additional outputs:** protected syntax blocks and round-trip validation; evaluated Word/slide conversion. These features cannot delay the PDF correctness release.
6. **Production release:** packaged/offline install checks, browser/accessibility review, representative benchmarks, recovery tests, documentation, and visual review against the approved design system.

Each phase should produce a usable increment and include its necessary service work. A cosmetic shell alone does not satisfy phase 1 or the requested preview behaviour.

## Release acceptance

- A branded sample automatically displays its full cover, page furniture, local fonts/images, tables, Mermaid, and page breaks without pressing Build.
- Preview and export of the same snapshot use the same PDF artifact. CLI comparison uses matching metadata, assets, dates, and environment; compare page count/text and rasterised pages with documented tolerances, avoiding brittle binary equality across independent builds.
- Fixtures cover `pdf_theme`, ancestor themes beyond a selected subdirectory, CSS imports, `css_vars`, config overrides, forms, headerless tables, includes, and missing dependencies.
- Unsaved Markdown, CSS, metadata, and included-template edits update the pinned preview without writing those edits to disk.
- Dragging either splitter works over the viewer, updates Monaco correctly, supports keyboard controls, and survives reload and viewport changes.
- Slow responses from a previously selected document cannot overwrite the current preview. Render failure leaves the previous output visible and clearly out of date.
- Concurrent external edits produce a conflict rather than lost data. Draft recovery survives a forced reload and flags disk divergence.
- Export, cancellation, server disconnect/reconnect, token expiry, invalid YAML/Jinja, absent fonts/assets, and unavailable converters have actionable states.
- Installed-package smoke tests verify locally bundled frontend/viewer/Monaco assets and offline operation. Browser end-to-end tests cover editing, resizing, refreshing, saving, conflict recovery, and export.
- A manual polish review verifies typography, alignment, icon consistency, focus/hover/disabled/loading states, empty states, narrow layouts, light/dark modes, and realistic document samples.

## Decisions to validate during implementation planning

Default authoring starts in Split/source mode for full syntax compatibility; visual mode arrives after round-trip safety. Final PDF auto-preview is the initial priority. Word and slide exact preview remain capability-gated until conversion is evaluated. The product remains a local document studio; knowledge graphs, databases, AI chat, account systems, and cloud collaboration are outside this specification.
