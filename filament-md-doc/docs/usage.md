# Using the editor

A walkthrough of the day-to-day editing experience.

---

## Opening a file

Two routes:

1. From the **Documents** resource (`/admin/md-doc-documents`) — table of every `.md` file in your workspace; click **Edit** on any row.
2. From the file tree sidebar inside the editor — click any `.md`, `_meta.yml`, or `*.css` file. The editor switches files in place.

Switching files automatically:
- Releases your lock on the previous file
- Acquires a lock on the new file (or opens it read-only if locked by someone else)
- Re-resolves the config cascade and CSS theme for the new file

## The three columns

```
┌────────────────────┬──────────────────────────┬─────────────────┐
│  File tree         │  Monaco editor           │  Tab panel      │
│  (sidebar)         │  (centre)                │  (right)        │
└────────────────────┴──────────────────────────┴─────────────────┘
```

### File tree (left)

Shows your workspace as a collapsible tree. Three file icons:

| Icon | File type |
|---|---|
| 📄 | `.md` markdown |
| ⚙️ | `_meta.yml` config |
| 🎨 | `.css` theme file |
| 🔒 | locked by another user |
| ● | uncommitted changes (when git is enabled) |

### Monaco editor (centre)

Custom Monarch tokenizers with first-class highlighting for:

- YAML frontmatter (`---` … `---`)
- Jinja2 expressions `{{ var }}`, tags `{% include "..." %}`, comments `{# ... #}`
- `[[field_name]]` Word merge fields (violet, bold)
- `?[type: name, …]` PDF form fields (teal)
- All standard Markdown (headings, bold/italic, lists, tables, code, links, blockquotes)
- Mermaid blocks (flowchart, pie, gantt, etc.)
- Embedded HTML form tags

Known md-doc config keys (`title`, `cover_page`, `pdf_forms`, etc.) are highlighted in violet bold; unknown YAML keys appear in teal.

#### Toolbar

| Element | When visible | What it does |
|---|---|---|
| Filename | Always | Path of the open file |
| 🔒 / ✏️ badge | Always | Lock status (see [locking](locking.md)) |
| **Save** | When you hold the lock | Writes the editor contents to disk |
| **Build PDF** | `.md` file open | Runs `md-doc build` and shows the PDF in the Preview tab |
| **Build DOCX** | `.md` file open | Same but for Word output (download link) |
| **Request edit** | When read-only | Try to acquire an expired lock |

#### Included templates

If your `.md` contains `{% include "fragment.md" %}` directives, the editor shows a row of clickable buttons below the toolbar. Clicking one opens the included file in place. Missing templates appear greyed out with a strike-through.

### Tab panel (right)

Five tabs:

#### Preview

Live HTML render of the editor body using `marked.js`, debounced 400 ms. Frontmatter is stripped before rendering. `{{ var }}` tokens are substituted from the merged config. The resolved theme CSS is injected as a `<style>` tag so colours, fonts, and section bars look close to the final PDF.

When you click **Build PDF**, this tab is replaced by an inline `<iframe>` showing the built PDF.

#### Config

Layer-by-layer accordion of the cascading `_meta.yml` files plus the document's frontmatter, ending with a final **Merged** layer showing the effective config. Keys are colour-coded so you can see exactly which layer contributed each setting.

#### CSS

The resolved theme — typically `_pdf-theme.css` from the deepest matching directory. Shows:

- Source path (with an **Edit ↗** button to open the file)
- Full CSS contents in a syntax-highlighted code block

#### History (when git is enabled)

The 30 most recent commits that touched the open file: short SHA, subject, author, date. Click any commit to open the **Diff** tab.

#### Diff

Monaco's side-by-side diff editor. Left pane = file at the selected commit; right pane = your working copy. Read-only — for review only, not editing.

---

## Saving

Two ways to trigger a save:

- Click the **Save** button
- Standard Monaco shortcuts work (Cmd/Ctrl-S triggers the form's submit)

A successful save shows a Filament toast notification. Save fails with a red toast if:

- Your lock has expired (the file is now read-only)
- The file path resolves outside the workspace root (security check)

After saving, the Config and CSS panels refresh.

---

## Editing `_meta.yml`

YAML editor with the same Jinja2 + md-doc-key highlighting. Saving an `_meta.yml` file does **not** automatically rebuild downstream documents — you'll see the new values reflected in any `.md` editor that already had this file in its cascade only after you reload that document.

## Editing CSS theme files

Standard Monaco CSS support (full IntelliSense, formatting, etc.). When the open file is a `_pdf-theme.css`, the **CSS** tab shows the contents of the file you're editing. Saving updates the in-memory copy used by the live preview, so changes appear in the next 400 ms preview refresh of any open `.md` file.

---

## Keyboard shortcuts

All Monaco defaults apply. Useful ones:

| Shortcut | Action |
|---|---|
| Cmd/Ctrl-S | Save (via the Save button) |
| Cmd/Ctrl-F | Find |
| Cmd/Ctrl-H | Find & replace |
| Cmd/Ctrl-/ | Toggle line comment |
| Alt-↑ / Alt-↓ | Move line up/down |
| Cmd/Ctrl-D | Add next selection match |
| Cmd/Ctrl-Shift-K | Delete current line |
| F1 | Command palette |

---

## Concurrency

The plugin assumes multiple editors at once. Behaviour:

- Two users open the same file → second user sees read-only mode + "🔒 Locked by Jane" badge
- File on disk changed via `git pull` while you were editing → no auto-reload yet; reload the page to pick up the new contents (planned)
- Network drops → heartbeat fails → next interaction shows "Lock expired"; reload to recover

See [locking](locking.md) for full details.
