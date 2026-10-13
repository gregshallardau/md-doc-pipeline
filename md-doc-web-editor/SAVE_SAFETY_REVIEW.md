# File saving and recovery review

Reviewed 13 October 2026: server file APIs, atomic writes, browser buffers and
Monaco events, local storage, session restoration, external-change polling,
comparison dialogs, file actions, Git integration, preview snapshots and cleanup.

The reported remote WSL incident cannot be attributed to a specific cause from
this checkout. The affected files, running editor version and request sequence
are unavailable. These findings establish risks in the code reviewed here;
they do not prove which risk caused that incident.

| Finding in previous code | Consequence | Change |
| --- | --- | --- |
| PUT accepted an absent or null revision for existing files | A caller could overwrite changes without a conflict | Every save compares the supplied revision, including null |
| No persistent save history | A successful overwrite removed the previous source copy | Preserve disk and incoming text before replacement, fail without replacing if preservation fails |
| External GET could finish after a successful PUT | A now-clean buffer could be replaced by content read before that save | Capture the buffer revision before GET, reject responses after revision changes or while saving, retry skipped refreshes |
| First polling signature only established a baseline | A change between opening a file and the initial poll could be missed | Initial poll also checks open files |
| Save returned success despite newer edits remaining | Save & close could dispose text typed during a save | Return false while newer edits remain; keep the tab open and refuse closes during saves |
| Comparison and file-action dialogs retained earlier decisions while text changed | An action could discard text typed after the dialog opened | Recheck draft content and saving state at action time |
| Workspace draft storage was shared by browser tabs | Another tab could clear the sole automatic draft entry | Independent recovery journals retain each session's last unsaved text even after save or discard |
| File/API fetches did not explicitly exclude caching | A cache could supply an older file or revision | Server API responses and browser API requests use no-store |
| Atomic save synced file content but not its parent directory | Rename durability after sudden power loss was weaker | Sync the parent directory after replacement on POSIX |

Recovery paths and their limits:

- **Saved source history:** `.editor-history/<filename>/<sha256>.txt` under each
  edited file's parent. Exact UTF-8 contents and line endings; deduplicated by
  content. History is excluded from preview scans, file tree and editor Git
  status. External Git needs an ignore rule. No automatic pruning.
- **Automatic drafts:** the existing workspace-scoped local-storage entry still
  restores unsaved buffers. Multiple tabs can still compete over this entry;
  journals provide independent manual recovery, not automatic merging.
- **Session recovery journals:** `md-doc-studio:<workspace>:recovery:<session>`
  preserves last unsaved text per file for each page session. Save, discard and
  disk replacement do not remove it. Browser-origin/profile-specific, subject
  to quota and browser-data deletion. No automatic pruning; no keystroke history.
- **Preview snapshots and caches:** isolated rendering inputs, never written
  back as source; intentionally deleted after jobs, expiry or shutdown. They
  cannot be treated as durable backups.
- **Trash:** file actions move deleted files into `.editor-trash` and support
  explicit restoration; ordinary saves do not go through trash.
- **External editor:** VS Code changes are observed by polling and checked at
  save. Its unsaved buffers are outside this application's control. Server
  locks coordinate writes within an app instance, not VS Code or another
  server process. An external write during check-and-replace can still race.
- **WSL:** atomic writes occur on the source filesystem; directory fsync improves
  durability on POSIX. Mounted Windows/network filesystems may have different
  durability guarantees. No live remote WSL reproduction was available.

Validation covers conditional saves, CRLF/non-ASCII recovery copies, backup
failure, cleanup/restart survival, cache headers, save/edit and polling/save
races, draft journal retention, and Save & close. The browser regression executes
actual editor functions with controlled asynchronous completions; the existing
Playwright suite exercises the integrated Monaco editor and real server.

Deploying this checkout to the affected machine is separate from these changes.
Recovery protection begins with the updated version; it cannot recreate content
lost before history or journal copies existed.
