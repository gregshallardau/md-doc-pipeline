# New workspace onboarding — agent prompt

For a **coding agent with file and shell access** (Claude Code, Codex, etc.) opened at the root
of an md-doc-pipeline checkout. It interviews the user once, then scaffolds a new company
workspace: brand theme, cascading config, shared templates, merge-field schema, starter
documents, and a verified first build.

Paste everything between `---START---` and `---END---`. Replace `{{COMPANY}}` with the company
name and `{{WORKSPACE_PATH}}` with where it should live (default `workspace/<slug>/`).

If the company already has a brand stylesheet, do this prompt first for the structure and then
run `prompts/upgrade-css.md` on the old CSS instead of generating a fresh theme.

---

---START---

You are onboarding a new company workspace for md-doc-pipeline: **{{COMPANY}}** at
`{{WORKSPACE_PATH}}`. You are authoring a document library, not changing the pipeline.

## Hard rules

1. **Interview first, generate second.** Ask every question in Step 1 in a single round, then
   wait. Do not scaffold anything until the user answers (or says "use defaults").
2. **Never invent** brand colours, fonts, addresses, ABNs/company numbers, legal wording,
   contact details, logos or credentials. If a value is unknown, use the stated default, leave a
   clearly marked `TODO:` in the file, and list it in the final report.
3. **No secrets in files.** Sync credentials go in environment variables and are referenced as
   `"${NAME}"` in `_meta.yml`.
4. Do not edit `md_doc/`, `tests/` or the root `pyproject.toml`.
5. Do not create `AGENTS.md`, `CLAUDE.md`, `README.md` or `CHANGELOG.md` inside the workspace: the build skips
   them and they confuse later authors. Hand-off notes go in your final message.
6. Only reference `{{ variables }}`, `[[fields]]` and `{% include %}` names that exist in the
   cascade you created.
7. `workspace/` is gitignored in the pipeline repo: a company library is its **own git
   repository**. Offer to `git init` inside `{{WORKSPACE_PATH}}`; never push.

## How the workspace works (so your choices are right)

- Config cascades: every `_meta.yml` from the repo root down to the document is shallow-merged;
  deeper wins; the document's own frontmatter wins over all. Put a value at the highest level
  where it is true for everything below, and never repeat an inherited value.
- Theme: PDF checks `_pdf-theme.css` then `_theme.css` at each level; Word checks
  `_docx-theme.css`, then `_theme.css`, then `_pdf-theme.css`. `md-doc theme init` produces one
  complete `_pdf-theme.css`, which Word uses as its fallback. Sub-folders can recolour with
  `md-doc theme override`.
- Includes resolve from the document's folder, a local `templates/`, ancestor `templates/`
  folders (deepest first), then the repo-root `templates/`.
- Three value types never mix: `{{ var }}` (build-time, from `_meta.yml`/frontmatter), `[[field]]`
  (Word merge/form field, declared in `_merge_fields.yml`), `?[...]` (PDF form field, needs
  `pdf_forms: true`).
- `cover_page` defaults to `false` in the pipeline; a workspace `_meta.yml` usually sets it.

## Step 0 — Preflight

```bash
uv sync --group dev
uv run md-doc doctor
ls workspace/                      # does {{WORKSPACE_PATH}} already exist? never overwrite it
```

If `doctor` fails, report exactly what is missing (usually WeasyPrint system libraries) and stop.
Also check whether `workspace/remote-workspaces.yml` exists: it maps names to folders (for
example a mounted share) so commands can use `-w <name>`.

## Step 1 — Interview (one round)

Ask all of these together, showing the default in brackets:

1. **Names:** company display name; folder slug [lower-case, hyphens]; the author/organisation
   string for documents and the page footer [company name].
2. **Outputs:** default `outputs` [pdf] — any of `pdf`, `docx`, `dotx` (mail-merge templates).
3. **Cover page** by default? [no — formal reports and proposals can opt in per document].
4. **Brand:** primary, accent, body-text and muted colours as hex [#1b4f72, #2e86c1, #1a1a2e,
   #5d6d7e]; body font family and monospace font [Segoe UI / Consolas stacks]; page size
   [A4 or Letter].
5. **Logo:** path to a logo file and where it should appear (page header, cover, header bar)
   [none].
6. **Page furniture:** solid page header bar? coloured section-heading bars? footer text
   [organisation name] [no, no].
7. **Content:** which document types will be written (letters, proposals, reports, forms,
   handbooks, decks) and an example of each. Decks use the separate deck prompt.
8. **Structure:** do documents group by client, by product, or both? Names of the first few
   clients/products.
9. **Merge fields** (only if `dotx`): the per-recipient values with a one-line description each
   (for example `contact_name`, `client_ref`, `invoice_total`).
10. **Shared text:** a letterhead/company-header block and a legal/confidentiality footer —
    supply the exact wording, or say "TODO".
11. **Sync:** upload built files anywhere? `azure`, `s3`, `local` or none [none]; if yes, the
    non-secret settings and the name of each environment variable that holds a secret.

Wait for the answers. Summarise your understanding in five lines and proceed.

## Step 2 — Scaffold

Use the CLI where it exists; it writes correct files and refuses to overwrite.

### 2.1 Folder and theme

`md-doc theme init` is interactive and asks nine questions in this order: organisation name,
primary, accent, body-text and muted colours, body font, monospace font, page size, include a
cover by default (y/N). Feed it the interview answers on stdin; an empty line accepts the default:

```bash
mkdir -p {{WORKSPACE_PATH}}
printf '%s\n' "ORG NAME" "#PRIMARY" "#ACCENT" "#BODYTEXT" "#MUTED" "" "" "A4" "n" \
  | uv run md-doc theme init {{WORKSPACE_PATH}}
```

This writes `_pdf-theme.css` and, if absent, a starter `_meta.yml` (`author`, `cover_page`,
`outputs`). Open both and check the result against the interview. If the user supplied fonts,
replace the font lines by hand, keeping the brand exact.

### 2.2 Root `_meta.yml`

Edit `{{WORKSPACE_PATH}}/_meta.yml` so it carries only values true for the whole company:

```yaml
author: <organisation string>
outputs: [pdf]               # as agreed
cover_page: false            # as agreed
status: draft
include_md_in_share: false
# Optional, only if agreed. Secrets come from the environment:
# sync_target: azure
# sync_config:
#   connection_string: "${AZURE_CONN_STRING}"
#   share_name: documents
```

Footer text, logos and page furniture (only the ones the user asked for):

```yaml
footer_left: "<organisation string>"
header_logo: assets/logo.png       # resolved from the document folder up to the repo root
page_header_bar: true
page_header_bar_color: "#PRIMARY"
section_bar: true
```

Copy the logo into `{{WORKSPACE_PATH}}/assets/` (never a path outside the repo). Brand *look*
values that are the same for everything (bar colours and heights) may instead live in the theme
as `--mddoc-*` custom properties; see the root `AGENTS.md`.

### 2.3 Templates and merge fields

- `templates/company-header.md` and `templates/legal-footer.md` with **exactly** the wording the
  user supplied (or a single `TODO:` line). Use `{{ author }}` etc. only for variables that exist.
- If `dotx` is in scope, `_merge_fields.yml` as `field_name: description` for each field from
  question 9. Deeper `_merge_fields.yml` files add to it.

### 2.4 Clients and products

For each group from question 8:

```bash
uv run md-doc new folder clients/<slug> --in {{WORKSPACE_PATH}}
uv run md-doc new folder products/<slug> --in {{WORKSPACE_PATH}}
```

`new folder` creates an empty `_meta.yml` and prints what it inherits. Add only new keys, for
example `client`, `account_manager`, `product`, `version`. For a sub-brand that only needs
different colours: `uv run md-doc theme override {{WORKSPACE_PATH}}/products/<slug>/`.

### 2.5 Starter documents

Create one starter per document type from question 7. `new doc` prompts for output format
(`pdf`, `docx` or `dotx`) then cover (y/N, default yes):

```bash
printf 'pdf\nn\n' | uv run md-doc new doc proposal --in {{WORKSPACE_PATH}}/clients/<slug>
```

Fill the body following `prompts/document-author.md`: one H1, `##` sections,
`{{ variables }}` only from the cascade, `[[fields]]` only from `_merge_fields.yml`, includes
only for templates that exist. For forms set `pdf_forms: true`, `cover_page: false` and use the
`?[...]` shorthand (see `docs/pdf-forms-guide.md`). Keep samples short and clearly generic;
do not make up client facts.

## Step 3 — Verify

```bash
uv run md-doc fields {{WORKSPACE_PATH}}/clients/<slug>     # merge fields visible here
uv run md-doc lint --render {{WORKSPACE_PATH}}             # strict render of every document
uv run md-doc build {{WORKSPACE_PATH}} --force
```

Then look at the output: render the first page of each PDF to an image and check that the brand
colours, fonts, logo, footer and cover (if enabled) are what the interview asked for. For each
`dotx`, confirm the merge fields exist (`md-doc build ... --format dotx`). Fix problems at the
level where they originate (theme, `_meta.yml`, template), not in the document.

If `docx` or `dotx` is in scope and LibreOffice is available, convert one Word output to PDF
(`soffice --headless --convert-to pdf`) and confirm the page count and footer are sensible.

## Step 4 — Hand-off

1. Offer `git init` in `{{WORKSPACE_PATH}}` with a first commit on a branch. Do not push.
2. Reply with:
   - the folder tree you created;
   - a table of every interview answer and where it landed (file and key);
   - each `TODO:` that needs a human, and each default you applied without being told;
   - the exact commands to build everything, one client, and one format
     (`md-doc build {{WORKSPACE_PATH}}`, `... clients/<slug>/`, `--format dotx`), and how to add
     the next client (`md-doc new folder`, `md-doc new doc`);
   - a pointer to `workspace/AGENTS.md` for authoring rules and `prompts/document-author.md` /
     `prompts/document-converter-standalone.md` for writing or converting documents.

---END---
