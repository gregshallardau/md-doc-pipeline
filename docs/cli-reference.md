# CLI reference

Every `md-doc` command, option, environment variable and the file that defines remote
workspaces. Run any command with `--help` for the same information in your terminal.

```bash
uv run md-doc <command> [options]      # from a checkout
md-doc <command> [options]             # when installed on PATH
python -m md_doc <command> [options]   # with the current Python environment
```

## Global options

Place these **before** the subcommand: `md-doc --debug build workspace/`.

| Option | Description |
|--------|-------------|
| `--version` | Show the version and exit. |
| `--log-level [debug\|info\|warning\|error]` | Logging verbosity (default `warning`). |
| `--debug` | Shortcut for `--log-level debug`: sync retries, config and theme warnings, per-document timing. |
| `--quiet` | Shortcut for `--log-level error`: errors only. |

## Commands at a glance

| Command | Purpose |
|---------|---------|
| [`build`](#build) | Build Markdown documents to PDF, DOCX, DOTX and/or PPTX. |
| [`lint`](#lint) | Check documents for build errors without rendering. |
| [`fields`](#fields) | List the `[[merge fields]]` available at a folder. |
| [`new`](#new) | Scaffold a folder or a document. |
| [`theme`](#theme) | Create a brand theme or a colour override. |
| [`export`](#export) | Build only notes marked `export: true` and collect the outputs. |
| [`extract`](#extract) | Convert a PDF or DOCX back to Markdown. |
| [`sync`](#sync) | Upload built files to Azure, S3 or a local folder. |
| [`register`](#register) | Write a document register (JSON, Markdown, CSV). |
| [`workspaces`](#workspaces) | List named remote workspaces. |
| [`doctor`](#doctor) | Check that the environment can build documents. |

## build

```
md-doc build [ROOT] [options]
```

Builds every document under `ROOT` (default: the current directory) to the formats named by its
`outputs` config. A pre-flight lint runs first; lint errors abort the build.

| Option | Description |
|--------|-------------|
| `-o, --output DIRECTORY` | Write outputs under this directory, mirroring the source tree. Wins over the `output_dir` config key. Default: next to each source file. |
| `-w, --workspace NAME` | Build a named [remote workspace](#remote-workspaces-file). Overrides `ROOT`. |
| `-f, --format [pdf\|docx\|dotx\|pptx\|all]` | Force the output format(s), overriding each document's `outputs`. |
| `-t, --theme FILE` | Use this `_pdf-theme.css` instead of the normal cascade for this build. |
| `--strict` | Fail on undefined Jinja2 variables instead of rendering them empty. |
| `--no-lint` | Skip the pre-flight lint (to build anyway while iterating). |
| `--dry-run` | Print what would be built without building. |
| `--force` | Rebuild everything. By default a document is skipped when its outputs are newer than its source, config, theme, templates and the md-doc code itself. |
| `-j, --jobs N` | Build up to N documents in parallel (process pool). Default 1. |
| `-v, --verbose` | Print full tracebacks on errors. |

```bash
md-doc build workspace/acme/                       # one company
md-doc build workspace/ --force -j 8               # everything, ignoring freshness, 8 in parallel
md-doc build workspace/acme/ --format dotx         # only the Word templates
md-doc build my-doc/ --theme brand/_pdf-theme.css  # one-off theme
md-doc build -w acme                               # a named remote workspace
```

PDF forms (`pdf_forms: true`) are written with a `-form` suffix: `intake.md` becomes
`intake-form.pdf`.

## lint

```
md-doc lint [ROOT] [options]
```

Checks, without invoking WeasyPrint: frontmatter YAML is valid; `outputs` are recognised
formats; Jinja2 syntax is valid; `{{ variables }}` (body and frontmatter strings) exist in the
config cascade (warning); `{% include %}` targets resolve (error); `[[fields]]` exist in the
`_merge_fields.yml` cascade (warning, when a schema is present); config keys are known and well
typed; PDF form fields have valid types and unique names. Exits non-zero on errors; warnings do
not affect the exit code.

| Option | Description |
|--------|-------------|
| `-w, --workspace NAME` | Lint a named remote workspace. |
| `--render` | Also run a strict Jinja2 render of every document so a missing variable is an error. |
| `--fix` | Repair fixable issues in place (currently CRLF to LF line endings). |

## fields

```
md-doc fields [DIRECTORY] [-w NAME]
```

Lists every `[[merge field]]` available at `DIRECTORY` (default: current folder), grouped by the
`_merge_fields.yml` file that defines it, shallowest first. Deeper files add to their parents.

## new

```
md-doc new folder NAME [--in DIRECTORY]
md-doc new doc NAME [--in DIRECTORY]
```

- `new folder` creates `NAME` (nested paths allowed) with an empty `_meta.yml` and prints the
  keys it inherits. It refuses to overwrite an existing folder.
- `new doc` creates `NAME.md` with starter frontmatter. It prompts for the output format
  (`pdf`, `docx` or `dotx`) and whether to include a cover page. Answers can be piped:
  `printf 'pdf\nn\n' | md-doc new doc proposal --in clients/acme/`.

## theme

```
md-doc theme init [DIRECTORY] [--force]
md-doc theme override [DIRECTORY] [--force]
```

- `init` writes a complete `_pdf-theme.css` (and a starter `_meta.yml` if there is none). It
  prompts, in order, for: organisation name, primary, accent, body-text and muted colours, body
  font, monospace font, page size (A4 or Letter), and whether covers are on by default. An empty
  answer accepts the default; answers can be piped on stdin.
- `override` writes a minimal `_pdf-theme.css` in a sub-folder that `@import`s the nearest parent
  theme and overrides only colours.
- Both refuse to overwrite without `--force`. See the [theming guide](theming-guide.md).

## export

```
md-doc export [SOURCE] [options]
```

Scans `SOURCE` for Markdown files with `export: true`, builds them and collects the outputs. See
the [export guide](export-guide.md) for the frontmatter keys and destination rules.

| Option | Description |
|--------|-------------|
| `-w, --workspace NAME` | Export a named remote workspace. Overrides `SOURCE`. |
| `-o, --output DIRECTORY` | Destination. Default: the `export_folder` config key, else `SOURCE/Exports/`. |
| `-f, --format [pdf\|docx\|dotx\|pptx\|all]` | Force the format. Default: each note's `export_format`, else `pdf`. |
| `-t, --tag TEXT` | Only export notes with this tag. Repeatable. |
| `--no-symlinks` | Copy the notes into the staging area instead of symlinking them (use when the source is on a filesystem that does not support symlinks). |
| `--dry-run` | Show what would be exported. |
| `-v, --verbose` | Full tracebacks on errors. |

## extract

```
md-doc extract FILE_PATH [--dest DESTINATION] [--force]
```

Converts a PDF or DOCX to Markdown, written to `DESTINATION` (default `templates/`) with the
source name and a `.md` extension. `--force` overwrites without prompting. See the
[extraction guide](extraction-guide.md).

## sync

```
md-doc sync [ROOT] [-b, --backend azure|s3|local] [--dry-run] [-w, --workspace NAME]
```

Uploads built `.pdf`, `.docx`, `.dotx`, `.pptx` (and, with `include_md_in_share: true`, `.md`) files,
preserving the folder structure under `ROOT`. The backend comes from `-b` or the `sync_target`
config key; its settings come from `sync_config`. Uploads are retried; failures are reported at
the end.

`${NAME}` references anywhere in `sync_config` are replaced from the environment, so secrets stay
out of `_meta.yml`. An unset variable is an error (a `--dry-run` leaves it unexpanded).

| Backend | `sync_config` keys | Notes |
|---------|--------------------|-------|
| `azure` | `share_name` (required), `connection_string`, `directory` | Needs the `azure` extra (`uv sync --extra azure`, or see [Installation](../README.md#installation)). `connection_string` falls back to the `AZURE_STORAGE_CONNECTION_STRING` environment variable. |
| `s3` | `bucket` (required), `prefix`, `region` | Needs the `s3` extra (`uv sync --extra s3`, or see [Installation](../README.md#installation)). `region` falls back to `AWS_DEFAULT_REGION`; credentials come from boto3's normal chain (environment, profile, role). |
| `local` | `path` (required) | Copies atomically to a folder; the destination must differ from the source. |

```yaml
sync_target: azure
sync_config:
  connection_string: "${AZURE_CONN_STRING}"
  share_name: documents
  directory: acme/outgoing
```

## register

```
md-doc register [ROOT] [-o FILE] [--md|--no-md] [-w NAME]
```

Scans built documents and their resolved config and writes `register.json` (default
`ROOT/register.json`), plus `register.md` unless `--no-md`, and `register.csv`. `README.md`,
`AGENTS.md`, `CLAUDE.md` and `GEMINI.md` are never listed.

## workspaces

```
md-doc workspaces
```

Lists the names in `workspace/remote-workspaces.yml` with their resolved path and whether it
exists (for example a share that is not mounted).

## doctor

```
md-doc doctor
```

Verifies the Python version, core dependencies and WeasyPrint's system libraries (with a tiny
in-memory render), and reports which optional extras (S3, Azure, Mermaid-in-Word) are installed.
Exits non-zero if a required check fails, so it can gate CI.

## Remote workspaces file

`workspace/remote-workspaces.yml` (at the repo root) gives names to document folders that live
elsewhere, such as a mounted share, so any command can use `-w NAME` instead of a path. Each
entry is either a path or a mapping:

```yaml
acme: /mnt/NAS/Documents/Acme
blueshift:
  path: ~/Documents/Blueshift
  description: Blueshift Labs client documents
```

`~` is expanded. A name that is not defined, or a path that does not exist, is a usage error that
lists the defined names. With `-w`, a positional `ROOT` is read as a path *relative to the
workspace*: `md-doc build -w acme products/nova`.

## Environment variables

| Variable | Used by | Effect |
|----------|---------|--------|
| `MD_DOC_NO_COLOR` | all commands | Any non-empty value disables coloured output. |
| `AZURE_STORAGE_CONNECTION_STRING` | `sync` (azure) | Connection string when `sync_config.connection_string` is not set. |
| `AWS_DEFAULT_REGION` | `sync` (s3) | Region when `sync_config.region` is not set. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, … | `sync` (s3) | Standard boto3 credentials. |
| anything you name | `sync_config` | Referenced as `"${NAME}"`. |

## Exit codes

`0` on success. Non-zero when `lint` finds errors, `doctor` finds a failed required check, a
build or sync fails, or a command is misused.
