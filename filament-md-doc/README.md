# filament-md-doc

A [Filament v5](https://filamentphp.com) plugin that turns the [md-doc-pipeline](https://github.com/gregshallardau/md-doc-pipeline) Python tool into a browser-based editor — with live preview, inherited YAML config, CSS theme cascade, file locking, git history, and one-click PDF/DOCX builds.

```
┌──────────────────────────────────────────────────────────────────┐
│ Files                │ Monaco editor          │ ● Preview        │
│                      │                        │   Config         │
│ workspace/           │ ---                    │   CSS            │
│ ├── acme/ ▼         │ title: Proposal        │   History        │
│ │  proposal.md ●    │ ---                    │                  │
│ │  _meta.yml         │                        │   <Live HTML>    │
│ │  _theme.css        │ # Hello {{ client }}   │                  │
│ └── blueshift/       │                        │   <PDF iframe>   │
│                      │            [Save]      │                  │
│  🔒 onboarding.md   │     [Build PDF] [DOCX] │                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## What it does

- **Editor** — Monaco code editor for `.md`, `_meta.yml`, and CSS theme files with custom syntax highlighting for md-doc syntax (Jinja2, `[[fields]]`, `?[forms]`, frontmatter, mermaid).
- **Live preview** — client-side HTML render via `marked.js` with the resolved theme CSS injected, plus `{{ var }}` substitution from the merged config cascade.
- **Inherited config panel** — shows every `_meta.yml` layer from the repo root down to the doc, plus the document's frontmatter, plus the final merged result.
- **CSS theme panel** — displays the resolved `_pdf-theme.css` / `_theme.css` for the current document and lets you jump to it.
- **Template navigation** — clickable buttons for every `{% include "..." %}` in the document; opens the included file in the editor.
- **File locking** — pessimistic, database-backed locks prevent two users editing the same file. Auto-released on tab close via `sendBeacon`. Heartbeat keeps the lock alive while you're typing.
- **Git integration** — file history, dirty-status indicators in the file tree, and a Monaco diff viewer for comparing your working copy to any commit.
- **One-click builds** — runs `md-doc build` via PHP `exec()` and renders the resulting PDF inline (or DOCX as a download).

---

## Quick start

```bash
# 1. In your Laravel 12 + Filament v5 app:
composer require md-doc/filament-md-doc

# 2. Run the lock-table migration
php artisan migrate

# 3. Publish the JS/CSS assets
php artisan vendor:publish --tag=md-doc-assets

# 4. Register the plugin in your panel provider
```

```php
// app/Providers/Filament/AdminPanelProvider.php
->plugins([
    \MdDoc\FilamentMdDoc\MdDocPlugin::make()
        ->workspacePath('/path/to/your/md-doc/workspace'),
])
```

```bash
# 5. Open /admin/md-doc-documents in your browser
```

For local Monaco / behind-proxy installs, see [docs/local-assets.md](docs/local-assets.md).

---

## Documentation

| Guide | What's in it |
|---|---|
| [Installation](docs/installation.md) | Composer, migration, asset publish, panel registration |
| [Configuration](docs/configuration.md) | Every `config/md-doc.php` key + env var |
| [Usage](docs/usage.md) | Editor walkthrough — tabs, panels, shortcuts |
| [Build integration](docs/building.md) | Wiring up `md-doc build` (PDF + DOCX) |
| [Git integration](docs/git-integration.md) | History panel, diff viewer, dirty indicators |
| [Locking](docs/locking.md) | Lock lifecycle, heartbeat, expiry, stealing |
| [Local assets](docs/local-assets.md) | npm-install Monaco for behind-proxy / production |
| [Architecture](docs/architecture.md) | Services, controllers, data flow |
| [Troubleshooting](docs/troubleshooting.md) | Common errors and fixes |

---

## Requirements

- PHP 8.2+
- Laravel 12+
- Filament v5
- A database (for the lock table)
- Optional but recommended:
  - `git` CLI (for history + diff features)
  - `md-doc` CLI (for the build feature) — see the parent project for install
  - Node.js (only if you need to self-host Monaco behind a proxy)

---

## License

MIT
