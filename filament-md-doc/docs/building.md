# Build integration

The plugin can call the `md-doc` Python CLI as a sidecar to render real PDF/DOCX/DOTX output, then stream the result back to the browser.

This is **separate** from the live HTML preview, which is rendered client-side by `marked.js` for instant feedback. The build feature gives you the final, accurate output (cover page, page headers, mermaid diagrams, embedded fonts — everything).

---

## Prerequisites

Install the Python pipeline in a dedicated virtual environment and point PHP
at its absolute CLI path. From a source checkout (no PyPI release required):

```bash
git clone https://github.com/gregshallardau/md-doc-pipeline.git /opt/md-doc
cd /opt/md-doc
uv venv
uv sync --no-dev
.venv/bin/md-doc --version
```

Activation is optional when using the absolute executable. For interactive
commands use `source .venv/bin/activate` on Linux/macOS or
`.\.venv\Scripts\Activate.ps1` in Windows PowerShell. On Windows the CLI is
`.venv/Scripts/md-doc.exe`.

Set the absolute path in Laravel's `.env` so PHP does not depend on shell activation:

```env
MD_DOC_BIN=/opt/md-doc/.venv/bin/md-doc
```

---

## How a build is triggered

1. User clicks **Build PDF** (or **Build DOCX**) in the editor toolbar.
2. The plugin saves the current editor contents to disk (only if the user holds the lock).
3. `BuildRunner::build()` runs:
   ```
   <md_doc_bin> build <abs/path/to/doc.md> --output <tmp_dir> --format pdf
   ```
   via Symfony Process with a configurable timeout.
4. The resulting file is located by recursively scanning `<tmp_dir>` for the matching extension.
5. A random 40-char token is generated and cached (Laravel cache, 30 min default) mapping `token → file path`.
6. The Livewire component sets `$buildToken` and `$buildFormat`. The Preview tab swaps to:
   - PDF: `<iframe src="/md-doc/build/{token}">`
   - DOCX/DOTX: a download link
7. `BuildController::serve($token)` looks up the cached path and streams the file with the correct `Content-Type` and `Content-Disposition`.

---

## Output flow

```
[Browser]                         [Laravel app]                          [Filesystem]
   │                                    │                                      │
   │   Build PDF (Livewire)             │                                      │
   ├───────────────────────────────────►│                                      │
   │                                    │   exec md-doc build ...              │
   │                                    ├─────────────────────────────────────►│
   │                                    │                                      │  /tmp/md-doc-builds/
   │                                    │   <token, /tmp/.../proposal.pdf>     │  └─ <token>/
   │                                    │◄─────────────────────────────────────┤     └─ proposal.pdf
   │                                    │                                      │
   │   <iframe src="/md-doc/build/...">│                                      │
   │◄───────────────────────────────────┤                                      │
   │                                    │                                      │
   │   GET /md-doc/build/<token>        │                                      │
   ├───────────────────────────────────►│                                      │
   │                                    │   Cache::get(md-doc-build:<token>)   │
   │                                    │   readfile(...)                      │
   │   200 OK  application/pdf          │                                      │
   │◄───────────────────────────────────┤                                      │
```

---

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `MD_DOC_BIN` | `md-doc` | Path to the binary. Use absolute path in production. |
| `MD_DOC_BUILD_DIR` | `/tmp/md-doc-builds` | Where outputs are staged. Each build gets its own subdir keyed by the token. |
| `MD_DOC_BUILD_TIMEOUT` | `120` | Seconds before the build is killed. WeasyPrint can be slow on large docs — bump to 300+ for big proposals. |
| `MD_DOC_BUILD_TTL` | `30` | Minutes before the token expires (the file becomes unreachable). |

---

## Cleanup

Built artefacts are not auto-purged. The token cache entry expires, but the file on disk remains. Add a daily cron:

```bash
# Delete build dirs older than 1 day
find /tmp/md-doc-builds -type d -mtime +1 -exec rm -rf {} +
```

Or use Laravel's task scheduler:

```php
// app/Console/Kernel.php
$schedule->call(function () {
    $dir = config('md-doc.build_tmp_dir');
    if (is_dir($dir)) {
        \Symfony\Component\Process\Process::fromShellCommandline(
            "find " . escapeshellarg($dir) . " -type d -mtime +1 -exec rm -rf {} +"
        )->run();
    }
})->daily();
```

---

## Permissions

The PHP process needs:

- **Read** access to the entire workspace (it walks up to find the repo root, theme files, etc.)
- **Write** access to `MD_DOC_BUILD_DIR`
- **Execute** permission on the `md-doc` binary
- The `md-doc` binary needs the same workspace read access

If you run PHP-FPM as `www-data` and `md-doc` was installed as your user, either:

- Reinstall `md-doc` system-wide so `www-data` can execute it, or
- Set `MD_DOC_BIN` to a venv whose files are readable+executable by `www-data`

---

## Forms / interactive PDFs

The plugin does not pass any extra flags — `md-doc build` reads `pdf_forms: true` from your `_meta.yml` or frontmatter as normal. If your document specifies `pdf_forms: true`, the resulting file will be `<basename>-form.pdf`. The plugin's recursive search finds it automatically.

---

## Build failures

If `md-doc build` exits non-zero:

1. The toolbar shows a red toast with the trimmed stderr/stdout
2. `$buildError` is populated on the Livewire component for any UI you wrap around it
3. The Preview tab continues showing the live HTML render (the build state simply isn't applied)

Common failures and fixes are in [troubleshooting](troubleshooting.md#build-fails).

---

## Security notes

- The token is a 40-char random string — sufficiently large to prevent guessing for the 30-min TTL window
- Build tokens act as bearer credentials. `loadRoutesFrom` does not automatically apply panel middleware; the host application must protect these routes with its authentication policy.
- Failed builds are removed immediately. Expired files are pruned on requests and by a registered five-minute Laravel scheduled task. Run the host application's scheduler (`php artisan schedule:run` every minute) to clean idle installations.

Save and Build send the current Monaco content directly. Every write requires a valid
editing lock and holds its database row lock through the write; reload or request
editing again if the lock has expired. Live HTML previews use sandboxed frames and
do not load external assets.
