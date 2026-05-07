# Git integration

The plugin reads (only reads — never writes) the git state of your workspace and surfaces three things:

1. **Dirty indicator** — a `●` next to any file with uncommitted changes in the file tree
2. **History panel** — the 30 most recent commits that touched the open file
3. **Diff viewer** — a side-by-side Monaco diff between your working copy and any commit

---

## Setup

There's nothing to configure — the plugin walks up from the workspace path looking for a `.git` marker on every page load. If found, git features are enabled. If not (e.g. workspace is outside a repo), the History tab simply shows "No git history" and the dirty dots don't appear.

The PHP process must have:

- The `git` binary on PATH (or installed at `/usr/bin/git`)
- Read access to the `.git` directory (which is normally fine for any user that can read the repo)

To verify:

```bash
sudo -u www-data git -C /path/to/your/repo log --oneline -1
```

If that works, you're good.

---

## Dirty indicators

`GitService::dirtyPaths()` runs `git status --porcelain` once per page load and returns a map of path → true. The file tree component renders a `●` and changes the colour to amber for any matching file.

Limitations:

- Updates only on full page load. After saving the file in the editor, the dirty status is recomputed (since you've definitely just dirtied something), but if someone else commits via CLI you'll need to refresh the page.
- The map is keyed by repo-relative path, but the file tree uses workspace-relative paths. The component handles both forms via a fall-through check.

---

## History panel

Located in the right tab panel, fourth tab. Shows up to 30 commits returned by:

```bash
git log --max-count=30 --follow \
  --pretty=format:'%H<US>%h<US>%an<US>%ad<US>%s' \
  --date=short \
  -- <path>
```

`--follow` means renames are traced through history.

Each entry is a button:

```
┌─────────────────────────────────────────────────────────────┐
│ a1b2c3d   Add cover page bar to all proposals               │
│           Jane Doe · 2026-04-15                             │
└─────────────────────────────────────────────────────────────┘
```

Clicking it dispatches a browser event (`show-diff`) that:

1. Switches the right panel to the **Diff** tab
2. Calls `window.mdDocLoadDiff(sha)` which fetches the commit's file contents
3. Renders a Monaco diff editor

---

## Diff viewer

Implemented via `monaco.editor.createDiffEditor()`. Layout:

```
┌──────────────────────────────────┬──────────────────────────────────┐
│  At commit a1b2c3d (read-only)   │  Working copy                    │
│  (left)                          │  (right)                         │
└──────────────────────────────────┴──────────────────────────────────┘
```

Configuration:

- `renderSideBySide: true` — split view; Monaco can also do inline mode if you need to change this
- `readOnly: true` — both panes are non-editable in the diff view
- Same `mddoc-light` theme as the main editor
- Auto-resizes via `automaticLayout: true`

Data flow for the right pane:

```
[Click commit a1b2c3d]
       │
       ▼
[show-diff event] ─► [JS: fetch /md-doc/git/file-at-commit?path=…&commit=a1b2c3d]
                                            │
                                            ▼
                                  [GitController::fileAtCommit]
                                            │
                                            ▼
                              [GitService::showFileAtCommit($sha, $path)]
                                            │
                                            ▼
                                  exec: git show <sha>:<path>
                                            │
                                            ▼
                                  JSON: { content: "..." }
       ┌────────────────────────────────────┘
       ▼
[mdDocLoadDiff calls renderDiff(oldText, newText, language)]
       │
       ▼
[monaco.editor.createDiffEditor]
```

---

## Branch awareness

The current branch name is shown at the top of the **History** panel:

```
Branch: main
```

If the file is dirty, a small `● modified` flag appears next to the branch name.

There is **no branch switcher** in the UI — switching branches requires a clean working directory and the plugin won't risk overwriting unsaved edits. Use `git checkout` from the CLI.

---

## What's intentionally out of scope

- **Committing from the editor** — too risky without a proper commit-message UI and pre-commit hook integration. Use your terminal or your IDE.
- **Pushing / pulling** — same reasoning.
- **Branch switching** — would silently invalidate every open lock and possibly destroy unsaved work. Better as a manual step.
- **Merge conflict resolution** — outside the scope of a markdown editor.

If you need any of these, raise an issue describing the workflow and we can scope a Phase 3.

---

## API endpoints

Only one endpoint is exposed to the frontend:

```
GET /md-doc/git/file-at-commit?path=<rel>&commit=<sha>

200 → { "content": "<file contents at that commit>" }
404 → { "error": "file not found at commit" }
422 → { "error": "missing path or commit" }
```

The history list is rendered server-side from the Livewire component's `$gitHistory` property, no separate JSON endpoint.

---

## Performance

- `git log` for a single file with `--max-count=30 --follow` is fast even on large repos (< 100 ms).
- `git status --porcelain` is the slowest call — it can take 200–500 ms on repos with thousands of files. It runs once per page load only.
- `git show <sha>:<path>` is fast (< 50 ms typically).

If you find dirty-status calls dominating page load on a huge repo, you can disable them by stubbing `GitService::dirtyPaths()` to return `[]` in a custom subclass.
