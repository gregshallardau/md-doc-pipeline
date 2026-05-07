# Installation

## Requirements

| Component | Version |
|---|---|
| PHP | 8.2+ |
| Laravel | 12+ |
| Filament | v5 |
| Database | any Laravel-supported (the lock table is small) |
| `git` CLI | optional — needed for git history/diff features |
| `md-doc` CLI | optional — needed for one-click build |
| Node.js | optional — only for self-hosting Monaco (see [local-assets](local-assets.md)) |

---

## 1. Install via Composer

Until the package is published on Packagist, install from the path or VCS:

```bash
# Path repository (during development, plugin alongside your app):
composer config repositories.filament-md-doc path /path/to/md-doc-pipeline/filament-md-doc
composer require md-doc/filament-md-doc:@dev
```

```bash
# Or via VCS (production):
composer config repositories.filament-md-doc vcs https://github.com/gregshallardau/md-doc-pipeline
composer require md-doc/filament-md-doc:dev-main
```

## 2. Run migrations

The plugin ships one migration that creates the `md_doc_file_locks` table:

```bash
php artisan migrate
```

The migration is auto-loaded via `loadMigrationsFrom()`, so no publish step is required. If you prefer to manage it yourself:

```bash
php artisan vendor:publish --tag=md-doc-migrations
```

## 3. Publish assets

The CSS and JavaScript live in `public/vendor/md-doc/`:

```bash
php artisan vendor:publish --tag=md-doc-assets
```

Re-run after every package update. If you keep `public/vendor/md-doc/` in `.gitignore`, add a deploy step to re-publish on release.

## 4. Publish config (optional)

If you want a project-local `config/md-doc.php`:

```bash
php artisan vendor:publish --tag=md-doc-config
```

Otherwise the package config is used and overridden via `.env` (see [configuration](configuration.md)).

## 5. Register the plugin

Add the plugin to your Filament panel provider:

```php
// app/Providers/Filament/AdminPanelProvider.php

use MdDoc\FilamentMdDoc\MdDocPlugin;

public function panel(Panel $panel): Panel
{
    return $panel
        // ... your other config
        ->plugins([
            MdDocPlugin::make()
                ->workspacePath(base_path('../md-doc-pipeline/workspace')),
        ]);
}
```

`workspacePath()` must be an absolute path that contains your `.md`, `_meta.yml`, and CSS theme files. All file reads/writes are sandboxed to this directory.

## 6. Configure environment

Add to `.env` (only the first line is required):

```env
MD_DOC_WORKSPACE=/absolute/path/to/your/workspace

# Optional — only set these if you customise behaviour
MD_DOC_BIN=/opt/md-doc/.venv/bin/md-doc
MD_DOC_LOCK_TTL=10
MD_DOC_MONACO_URL=https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs
MD_DOC_MARKED_URL=https://cdn.jsdelivr.net/npm/marked/marked.min.js
```

See [configuration](configuration.md) for every setting.

## 7. Open the editor

Navigate to `/admin/md-doc-documents` (or whatever path your Filament panel uses). You should see a table of all `.md` files in your workspace. Click **Edit** on any row to open the editor.

---

## Verifying the install

Quick sanity checks after install:

```bash
# Database migration ran
php artisan migrate:status | grep md_doc_file_locks

# Assets published
ls public/vendor/md-doc/

# Plugin recognised by Filament
php artisan filament:list-resources | grep -i document
```

Visit the editor and confirm:

- File tree on the left shows your workspace contents
- Opening a `.md` file loads Monaco with markdown syntax highlighting
- Typing into the editor updates the **Preview** pane within ~400 ms
- The **Config** tab shows your `_meta.yml` cascade
- The **CSS** tab shows the resolved theme

If any step fails, see [troubleshooting](troubleshooting.md).
