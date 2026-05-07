# Troubleshooting

Common problems and how to fix them.

---

## Editor doesn't load — blank centre column

**Cause**: Monaco failed to load (most often a CDN/proxy issue).

**Fix**: Open browser DevTools → Network tab → reload. Look for failed requests to `cdn.jsdelivr.net`. If they're blocked, switch to local Monaco — see [local-assets](local-assets.md).

Also check the JS console for errors. A common one:

```
Uncaught ReferenceError: registerMdDocLanguages is not defined
```

This means `tokenizers.js` didn't load. Check that `php artisan vendor:publish --tag=md-doc-assets` ran successfully and that `public/vendor/md-doc/js/tokenizers.js` exists.

---

## "File path escapes workspace root"

**Cause**: A request tried to read or write a path that resolves outside `workspace_path`.

**Fix**: This is a security check, not a bug. If you genuinely need to edit a file outside your configured workspace, set `MD_DOC_WORKSPACE` to a higher-level directory that contains both.

If it happens unexpectedly, check that `workspace_path` is an *absolute* path. Relative paths and unresolved symlinks can produce this error.

---

## "Locked by &lt;sessionId&gt;" with a hash you don't recognise

**Cause**: `lock_user_source` is set to `session` but you expected `auth`. Or auth isn't configured and the system fell back to session IDs.

**Fix**: Set `MD_DOC_LOCK_USER=auth` and confirm `auth()->check()` returns true on a request to the editor. If you're hitting the editor without being logged in, configure your Filament panel's auth.

---

## Lock won't release (file shows 🔒 forever)

**Cause**: A previous session crashed before `sendBeacon` fired, or the lock TTL is set very high.

**Fix**: Wait `lock_ttl_minutes` for the lock to expire naturally, then click **Request edit**. Or clear it manually:

```bash
php artisan tinker
>>> \MdDoc\FilamentMdDoc\Models\FileLock::where('file_path', '<path>')->delete();
```

For a permanent fix, lower `MD_DOC_LOCK_TTL` (default 10 min — try 5).

---

## Heartbeat returns 419 (CSRF mismatch)

**Cause**: The `<meta name="csrf-token">` tag is missing from the page, or session expired.

**Fix**: Filament's default layout always emits the CSRF meta tag. If you've customised the layout, ensure it still includes:

```blade
<meta name="csrf-token" content="{{ csrf_token() }}">
```

---

## Build fails

### `md-doc: command not found`

The PHP process can't find the binary. Set the absolute path:

```env
MD_DOC_BIN=/opt/md-doc/.venv/bin/md-doc
```

### `Permission denied`

The PHP user can't execute the binary. Either:

- `chmod +x` and ensure the parent directories are world-readable
- Reinstall md-doc system-wide

### `Build timeout exceeded`

Large documents (50+ pages with mermaid) can take 60+ seconds. Increase the cap:

```env
MD_DOC_BUILD_TIMEOUT=300
```

### `WeasyPrint: Pango not found`

The `md-doc` Python pipeline depends on system libraries. Install them:

```bash
# Ubuntu/Debian
apt install libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf2.0-0

# RHEL/Fedora
dnf install pango gdk-pixbuf2
```

### Build succeeds but no PDF appears

Check `BuildRunner::findBuiltFile()` — it scans the tmp dir recursively. If your `_meta.yml` sets `output_dir` to an absolute path outside the tmp dir, the build artefact lands somewhere unexpected and the recursive search returns null.

Workaround: don't set `output_dir` for documents you build via the editor. Use it only for CLI builds.

---

## Git history shows nothing

**Cause**: The workspace isn't inside a git repo, or `git` isn't on PATH for the PHP user.

**Fix**: Run as the PHP user and verify:

```bash
sudo -u www-data which git
sudo -u www-data git -C /your/workspace log --oneline -1
```

If the workspace genuinely isn't tracked, that's expected — the History tab will be empty.

---

## Diff viewer is blank

**Cause**: The fetch to `/md-doc/git/file-at-commit` failed.

**Fix**: Open Network tab and look for the `git/file-at-commit` request. Common errors:

- `404` — file didn't exist at that commit (the commit deleted/created it). Pick a different commit.
- `500` — `git show` failed. Check the Laravel log for the underlying git error.

---

## Preview shows raw `{{ var }}` instead of substituted value

**Cause**: The variable isn't in your merged config.

**Fix**: Open the Config tab and check the **Merged (final)** layer — your variable name must appear there. If it doesn't, add it to a `_meta.yml` somewhere in the cascade (or to the document's frontmatter).

The substitution is intentionally simple — only top-level keys are supported. Nested access like `{{ contact.name }}` won't work in the preview (but does work in the actual `md-doc build` output via Jinja2).

---

## Live preview "freezes" — doesn't update on type

**Cause**: A JS error broke the debounce loop.

**Fix**: Open DevTools console. Common errors:

- `marked is not defined` — marked.js failed to load. See [local-assets](local-assets.md).
- A custom field name in your document collides with a JS reserved word and breaks the var substitution regex (rare).

Reload the page to recover.

---

## Toast notifications not showing

**Cause**: Filament's notification rendering isn't set up.

**Fix**: Filament v5 emits notifications via Livewire, which requires the `<livewire:notifications />` component in your layout. If you've heavily customised the panel chrome, add it back to the main layout.

---

## "Class App\Models\User not found" or similar auth errors

**Cause**: `lock_user_source=auth` but you don't have a User model / Laravel Auth configured.

**Fix**: Either configure auth properly, or set `MD_DOC_LOCK_USER=session` to fall back to session IDs.

---

## Migrations don't run

**Cause**: The migration is auto-loaded but not picked up.

**Fix**:

```bash
php artisan migrate:status | grep md_doc
```

If absent, force-publish then migrate:

```bash
php artisan vendor:publish --tag=md-doc-migrations
php artisan migrate
```

---

## Still stuck?

1. Check the Laravel log: `storage/logs/laravel.log`
2. Check the browser console
3. Reproduce with the simplest possible workspace (one `.md`, one `_meta.yml`)
4. Open an issue at https://github.com/gregshallardau/md-doc-pipeline/issues with:
   - PHP / Laravel / Filament versions
   - Relevant `.env` settings (redact secrets)
   - The exact error message and steps to reproduce
