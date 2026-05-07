# Architecture

A reference for understanding (and extending) the plugin internals.

---

## Component map

```
filament-md-doc/
├── src/
│   ├── MdDocPlugin.php                  # Filament plugin entry — registers resource
│   ├── MdDocServiceProvider.php         # Boot — config, views, routes, migration
│   │
│   ├── Resources/
│   │   └── DocumentResource.php         # Filament Resource (table of .md files)
│   │
│   ├── Livewire/
│   │   └── DocumentEditor.php           # Main editor component (state + actions)
│   │
│   ├── Services/
│   │   ├── FilesystemScanner.php        # Workspace tree, read/write, includes
│   │   ├── ConfigResolver.php           # _meta.yml cascade + frontmatter
│   │   ├── CssResolver.php              # CSS theme cascade
│   │   ├── FileLockService.php          # Acquire / release / refresh / list
│   │   ├── BuildRunner.php              # exec md-doc build → tokenised file
│   │   └── GitService.php               # log / show / status wrappers
│   │
│   ├── Http/Controllers/
│   │   ├── LockController.php           # /md-doc/lock/refresh + /release
│   │   ├── BuildController.php          # /md-doc/build/{token}
│   │   └── GitController.php            # /md-doc/git/file-at-commit
│   │
│   └── Models/
│       └── FileLock.php                 # Eloquent — md_doc_file_locks table
│
├── resources/
│   ├── views/
│   │   ├── document-editor.blade.php    # Main 3-column layout
│   │   └── components/
│   │       ├── file-tree.blade.php
│   │       ├── config-panel.blade.php
│   │       ├── css-panel.blade.php
│   │       └── history-panel.blade.php
│   ├── css/editor.css
│   └── js/
│       ├── editor.js                    # Monaco init, preview, lock heartbeat
│       └── tokenizers.js                # Custom Monarch + theme
│
├── routes/web.php                       # All plugin routes
├── config/md-doc.php                    # All settings
├── database/migrations/                 # md_doc_file_locks table
└── docs/                                # This documentation
```

---

## Request flow: opening a file

```
[User clicks "Edit" on /admin/md-doc-documents]
       │
       ▼
[Filament action] ─► route('md-doc.editor.path', ['path' => '...'])
       │
       ▼
[DocumentEditor::mount($path)]
       │
       ├─► FilesystemScanner::scan()                    → file tree
       ├─► FileLockService::activeLocks()                → who holds locks
       ├─► GitService::dirtyPaths()                      → uncommitted files
       ├─► GitService::currentBranch()                   → branch name
       │
       ├─► loadFile($path)
       │      │
       │      ├─► FilesystemScanner::read($path)        → file contents
       │      ├─► FileLockService::acquire($path, …)    → lock (or read-only)
       │      └─► refreshDerivedData()
       │            ├─► ConfigResolver::resolve(...)    → cascade layers
       │            ├─► CssResolver::resolve(...)       → theme CSS
       │            ├─► FilesystemScanner::findIncludes → template buttons
       │            ├─► GitService::isDirty(...)         → bool
       │            └─► GitService::fileHistory(...)    → commits
       │
       ▼
[Blade renders document-editor.blade.php]
       │
       ▼
[Browser]
   ├─► <script>window.mdDocConfig = {...}</script>      ← merged config
   ├─► <script>window.mdDocCss = "..."</script>          ← theme
   ├─► <script>window.mdDocLockKey = "uuid"</script>     ← lock_key
   │
   ├─► Load monaco-editor/loader.js + tokenizers.js
   ├─► registerMdDocLanguages(monaco)                   → mddoc-markdown, mddoc-yaml, mddoc-light
   ├─► monaco.editor.create(...) with readOnly=isReadOnly
   ├─► startLockHeartbeat()                              → setInterval
   └─► renderPreview(content, config, css)               → marked.js
```

---

## State diagram: lock lifecycle

```
                  ┌────────────────┐
                  │   No lock      │
                  └───┬────────────┘
                      │ user opens file
                      ▼
                  ┌────────────────┐
              ┌──►│  Locked by me  │◄────┐
              │   └───┬────────────┘     │
              │       │                  │ heartbeat
              │       │ heartbeat OK     │ success
              │       └──────────────────┘
              │       │ heartbeat fail
              │       ▼
   tryStealLock   ┌────────────────┐
   (only if       │   Read-only    │
    expired)      │  (someone else │
              │   │   has it)      │
              └───┴───────┬────────┘
                          │ lock TTL elapses
                          ▼
                  ┌────────────────┐
                  │ Expired        │
                  │ (purged on     │
                  │  next acquire) │
                  └────────────────┘
```

---

## Data model

### `md_doc_file_locks`

```sql
CREATE TABLE md_doc_file_locks (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    file_path   VARCHAR(500) NOT NULL UNIQUE,
    locked_by   VARCHAR(255) NOT NULL,
    lock_key    VARCHAR(36)  NOT NULL UNIQUE,
    locked_at   TIMESTAMP    NOT NULL,
    expires_at  TIMESTAMP    NOT NULL,
    created_at  TIMESTAMP NULL,
    updated_at  TIMESTAMP NULL,
    INDEX (expires_at)
);
```

Two unique constraints:

- `file_path` UNIQUE — one lock per file (race-safe: concurrent `INSERT`s collide)
- `lock_key` UNIQUE — every issued key is globally unique

The `expires_at` index makes the `purgeExpired()` cleanup query fast.

### Cache keys

| Key | TTL | Set by | Read by |
|---|---|---|---|
| `md-doc-build:<token>` | `build_token_ttl_minutes` (30) | `BuildRunner::build()` | `BuildController::serve()` |

Uses Laravel's default cache driver. No queue or message broker required.

---

## Routes

| Method | Path | Controller | Purpose |
|---|---|---|---|
| GET | `/md-doc/editor` | DocumentEditor (Livewire) | Editor without a file |
| GET | `/md-doc/editor/{path}` | DocumentEditor (Livewire) | Editor opened on a file |
| POST | `/md-doc/lock/release` | LockController@release | Beacon release on tab close |
| POST | `/md-doc/lock/refresh` | LockController@refresh | Heartbeat |
| GET | `/md-doc/build/{token}` | BuildController@serve | Stream a built PDF/DOCX |
| GET | `/md-doc/git/file-at-commit` | GitController@fileAtCommit | Diff data |

All routes inherit any middleware applied to your Filament panel. To add custom auth, wrap them in your service provider's boot method or use Filament's `->middleware()` builder.

---

## Frontend layers

```
┌────────────────────────────────────────────────────────────────┐
│ Filament panel chrome (Livewire + Alpine)                      │
└────────────────────────────────────────────────────────────────┘
                          │ embeds
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ DocumentEditor Livewire component                              │
│   • Server state: $content, $configLayers, $resolvedCss, etc.  │
│   • Actions: save, loadFile, openTemplate, buildPdf, …         │
└────────────────────────────────────────────────────────────────┘
                          │ renders
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ document-editor.blade.php                                      │
│   • Three-column grid                                          │
│   • Alpine x-data for tab switching                            │
│   • Pushes server state into window.mdDoc* globals             │
└────────────────────────────────────────────────────────────────┘
                          │ scripts load
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ Vendor: monaco-editor + marked.js (CDN or local)               │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ tokenizers.js                                                  │
│   • Defines mddoc-markdown, mddoc-yaml, mddoc-light theme      │
│   • registerMdDocLanguages(monaco)                             │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ editor.js                                                      │
│   • monaco.editor.create(...) with mddoc-light theme           │
│   • Live preview (marked + var substitution + theme CSS)       │
│   • Lock heartbeat (fetch /md-doc/lock/refresh)                │
│   • Beacon release (sendBeacon /md-doc/lock/release)           │
│   • Diff editor (monaco.editor.createDiffEditor)               │
└────────────────────────────────────────────────────────────────┘
```

---

## Extending

### Custom syntax in tokenizers

Edit `resources/js/tokenizers.js`. The file is hand-written Monarch — no compilation needed. Add new tokens to the rule arrays, then map them to colours in the `MDDOC_LIGHT_THEME` rules.

### A new right-panel tab

1. Add a new computed property on `DocumentEditor` (e.g. `$myTabData`)
2. Add a new tab button + pane in `document-editor.blade.php`
3. Optionally extract the pane contents into a Blade component under `resources/views/components/`

### Custom lock policies

Subclass `FileLockService` and bind it in your service provider:

```php
$this->app->bind(FileLockService::class, MyCustomLockService::class);
```

Then update `DocumentEditor::boot()` to resolve the service from the container instead of `new`-ing it (currently it uses direct instantiation for explicitness — a one-line change to use `app()`).

### Different file types

`FilesystemScanner::classifyFile()` decides which files appear in the tree. Add a case for `.txt`, `.json`, etc. Update `DocumentEditor::detectFileType()` to map the extension to a Monaco language. The tree view will pick up the new icon class via your edits to `file-tree.blade.php`.
