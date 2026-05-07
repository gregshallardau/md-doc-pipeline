# Configuration

All settings live in `config/md-doc.php` and are overrideable via `.env`. Most are optional — the only one that **must** be set is `workspace_path`.

```bash
php artisan vendor:publish --tag=md-doc-config
```

---

## Reference

### Workspace

| Key | Env var | Default | Purpose |
|---|---|---|---|
| `workspace_path` | `MD_DOC_WORKSPACE` | `base_path('workspace')` | Absolute path to the directory containing your `.md`, `_meta.yml`, and CSS files. All file I/O is sandboxed to this directory; paths that resolve outside it are rejected. |

You can also set this in code — `MdDocPlugin::make()->workspacePath('/abs/path')` — which takes precedence over the env value.

### Editor assets

| Key | Env var | Default | Purpose |
|---|---|---|---|
| `monaco_base_url` | `MD_DOC_MONACO_URL` | `https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs` | URL to the Monaco editor `min/vs` directory. Override to a local path when behind a proxy. |
| `marked_url` | `MD_DOC_MARKED_URL` | `https://cdn.jsdelivr.net/npm/marked/marked.min.js` | URL to the marked.js bundle. |

For self-hosting, see [local-assets](local-assets.md).

### File locking

| Key | Env var | Default | Purpose |
|---|---|---|---|
| `lock_ttl_minutes` | `MD_DOC_LOCK_TTL` | `10` | How long a lock survives without a heartbeat. The browser pings every `lock_ttl_minutes / 2` minutes while the editor is open, so a 10-min TTL means a 5-min heartbeat interval. |
| `lock_user_source` | `MD_DOC_LOCK_USER` | `auth` | How to identify the lock-holder. `auth` uses `auth()->user()->name ?? email`; `session` uses the session ID (use this when running unauthenticated). |

See [locking](locking.md) for the full lock lifecycle.

### Build (Phase 2 — md-doc CLI sidecar)

| Key | Env var | Default | Purpose |
|---|---|---|---|
| `md_doc_bin` | `MD_DOC_BIN` | `md-doc` | Path to the `md-doc` CLI binary. In production set this to the absolute path of your venv-installed binary, e.g. `/opt/md-doc/.venv/bin/md-doc`. |
| `build_tmp_dir` | `MD_DOC_BUILD_DIR` | `/tmp/md-doc-builds` | Where built PDF/DOCX outputs are staged before being served via tokenised URL. |
| `build_timeout_seconds` | `MD_DOC_BUILD_TIMEOUT` | `120` | Hard ceiling for a single `md-doc build` invocation. WeasyPrint can be slow on large documents — increase if you see timeouts. |
| `build_token_ttl_minutes` | `MD_DOC_BUILD_TTL` | `30` | How long a build artefact remains downloadable after completion. |

See [building](building.md) for the full build flow.

---

## Sample `.env`

A complete env block for production:

```env
# Required
MD_DOC_WORKSPACE=/var/www/md-doc-pipeline/workspace

# Editor assets — local install behind proxy
MD_DOC_MONACO_URL=/build/monacoeditorwork
MD_DOC_MARKED_URL=/build/js/marked.min.js

# Locking — shorten TTL for noisy environments
MD_DOC_LOCK_TTL=15

# Build — point at the venv-installed md-doc binary
MD_DOC_BIN=/opt/md-doc/.venv/bin/md-doc
MD_DOC_BUILD_DIR=/var/cache/md-doc-builds
MD_DOC_BUILD_TIMEOUT=180
```

---

## Programmatic config

You can also set config values on the plugin instance, which override env values:

```php
MdDocPlugin::make()
    ->workspacePath(base_path('../shared/workspace'))
    // (workspacePath is the only programmatic setter at present;
    //  other settings come from config('md-doc.*') / env)
```

Everything else is read live from `config('md-doc.*')` so you can override per-environment in the standard Laravel way (`config/md-doc.php` per env, runtime `Config::set(...)`, etc.).

---

## Resetting the cache

After changing config or env vars in production:

```bash
php artisan config:clear
php artisan view:clear
```
