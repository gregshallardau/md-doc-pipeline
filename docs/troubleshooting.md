# Troubleshooting

Start with the built-in preflight — it checks your Python version, the core
dependencies, WeasyPrint's system libraries, and the optional extras, and prints
an install hint for anything missing:

```bash
md-doc doctor
```

For more detail on any command, raise the log level (place the flag *before* the
subcommand):

```bash
md-doc --debug build workspace/acme/     # show config/theme warnings + timing
md-doc --quiet build workspace/          # errors only
```

## PDF build fails with a `libpango` / `libcairo` / `gobject` error

WeasyPrint needs native libraries that aren't Python packages. `md-doc doctor`
reports this as a failed "render a test PDF" check.

- **Debian / Ubuntu**
  ```bash
  sudo apt-get install -y \
    libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 libcairo2 libffi-dev shared-mime-info
  ```
- **macOS (Homebrew)**
  ```bash
  brew install pango gdk-pixbuf libffi
  ```
- **Other platforms**: see the
  [WeasyPrint install guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).

## Mermaid diagrams show as source code in Word (.docx / .dotx)

Rasterizing diagrams for Word needs the optional `cairosvg` dependency (which in
turn needs `libcairo2`):

```bash
pip install "md-doc-pipeline[mermaid]"   # + libcairo2 on Linux
```

Without it, diagrams still work in PDF; in Word they fall back to a code block
rather than breaking the build. PDF diagrams never require `cairosvg`.

## S3 / Azure sync says the backend isn't available

Install the matching extra:

```bash
pip install "md-doc-pipeline[s3]"      # boto3
pip install "md-doc-pipeline[azure]"   # azure-storage-file-share
```

Credentials come from the standard chains (env vars, `~/.aws/credentials`,
`AZURE_STORAGE_CONNECTION_STRING`) or `sync_config` in `_meta.yml`. A sync now
retries each file and reports an uploaded/failed summary; run with `--debug` to
see retry attempts.

## My `_meta.yml` change had no effect

- Run `md-doc lint` — it now flags likely typos of reserved keys (e.g.
  `cover_bard` → `cover_bar`) and wrong-typed values.
- Remember the cascade is **shallow-merged**: a nested key set deeper fully
  replaces the parent's value for that key.
- Note that config keys double as Jinja variables, so an unrecognised key is
  only warned about when it closely resembles a reserved one — arbitrary custom
  variables are intentionally allowed.

## A build didn't regenerate an output

Builds are incremental: an output newer than its source, config, theme, and
`templates/` fragments is skipped. Force a full rebuild with:

```bash
md-doc build workspace/ --force
```
