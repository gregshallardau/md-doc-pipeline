# Export guide

`md-doc export` turns a folder of notes, such as an Obsidian vault, into published documents
without building everything. Only notes that opt in with `export: true` are built.

```bash
md-doc export /path/to/vault                 # scan, build, collect into vault/Exports/
md-doc export -w acme                        # a named remote workspace
md-doc export /path/to/vault --tag cheatsheet --format pdf
md-doc export /path/to/vault -o /mnt/NAS/Exports
md-doc export . --dry-run                    # show what would be exported
```

## Marking a note for export

Put these keys in a note's frontmatter, or in any `_meta.yml` above it (a parent folder's
`export: true` is inherited by every note below):

```yaml
---
export: true                  # required: opts this note in
export_format: pdf            # pdf, docx, dotx or pptx (default: pdf)
export_path: Cheat Sheets     # sub-folder inside the destination (default: mirrors the source tree)
export_filename: Git Cheats   # output name; the extension is added for you
draft: true                   # skip this note even though export is true
tags: [cheatsheet, cli]       # used by --tag
---
```

Notes inside folders whose name starts with `.` are ignored. A note whose `export_path` would
land outside the destination is skipped with a warning.

## What happens

1. The command finds every note with `export: true` and not `draft: true`. With `--tag`
   (repeatable) it keeps only notes that carry at least one of the tags.
2. The notes are staged into an internal workspace, by default as symlinks to the originals
   (`--no-symlinks` copies them), so your vault is never modified. Symlinks that resolve outside
   the source tree are refused.
3. The staged notes are built like any other documents, with the normal config cascade and
   themes. `--format` overrides each note's `export_format`.
4. The outputs are copied to the destination, honouring `export_path` and `export_filename`.

## Where the files go

In order of precedence:

1. `-o, --output DIRECTORY`
2. `export_folder` in the nearest `_meta.yml` at or above the source (a relative path is
   resolved against the source folder; `~` is expanded)
3. `SOURCE/Exports/`

```yaml
# vault/_meta.yml
export_folder: /mnt/NAS/Published
```

## Tips

- Run with `--dry-run` first to confirm which notes match.
- Put brand defaults (`author`, `outputs`, theme) in the vault's `_meta.yml` so exported notes
  look consistent without per-note frontmatter.
- Combine with `md-doc sync` if outputs should also be uploaded.

See the [CLI reference](cli-reference.md#export) for every option and the
[config reference](config-reference.md) for the export keys.
