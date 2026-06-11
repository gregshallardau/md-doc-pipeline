# Neovim Plugin Design — md-doc Template Preview

**Date:** 2026-06-11
**Status:** Approved

---

## Problem

Authors editing `.md` documents in Neovim have no visibility into what `{% include "template.md" %}` fragments or `{{ variable }}` expressions resolve to without running the full build. A lightweight plugin can surface this inline — showing template content and resolved variable values as the author writes.

---

## Approach: Pure Lua Plugin with Reimplemented Cascade

A Neovim plugin living inside the `md-doc-pipeline` repo at `nvim-plugin/`. All template path resolution and variable resolution logic is reimplemented in Lua, mirroring the Python cascade behaviour. No subprocess calls, no external dependencies — just file reads and table merges.

Three display modes (all user-togglable independently):
1. **Float** — LSP-style hover popup on `CursorHold` or keymap
2. **Virtual text** — dimmed inline expansion below the include/variable line
3. **Split** — persistent right-side pane that updates as cursor moves

---

## File Detection

The plugin activates only on `*.md` files inside an md-doc project, detected by finding a `pyproject.toml` or `.git` directory in an ancestor path. On any other `.md` file it stays completely dormant — no autocommands, no keymaps set.

---

## Directory Structure

```
nvim-plugin/
  lua/
    md-doc/
      init.lua       — setup(), autocommands, cursor dispatch
      cascade.lua    — repo root detection, _meta.yml walking, context merge
      parser.lua     — minimal YAML parser (scalar key-value + frontmatter strip)
      resolve.lua    — {% include %} path resolution, {{ var }} lookup
      ui/
        float.lua    — floating window
        virtual.lua  — virtual text via extmarks
        split.lua    — vertical split pane
  plugin/
    md-doc.lua       — autoload shim
  README.md
```

---

## Core Modules

### `cascade.lua`

Mirrors Python's `_find_repo_root` and `_build_search_dirs`:

1. Walk up from the doc file looking for `.git` or `pyproject.toml` → repo root
2. Collect all `_meta.yml` files from repo root down to doc dir
3. Shallow-merge them in order (deeper files win), then merge doc frontmatter on top
4. Returns a flat Lua table: `{ client = "Stormfront", status = "draft", … }`

### `parser.lua`

Minimal YAML for this project's actual usage:

- Parses flat `key: value` lines (strings, numbers, booleans)
- Strips YAML frontmatter block (`---…---`) from `.md` files, returns both parts separately
- Does **not** handle nested YAML, lists, or multi-line values — `_meta.yml` files in this codebase are all flat scalar; complex values are silently skipped

### `resolve.lua`

Two public functions:

- `resolve_include(template_name, doc_path, repo_root)` — builds the same search dir list as Python's `_build_search_dirs` (doc dir → doc/templates/ → ancestor templates/ dirs deepest-first → repo root templates/ → repo root), returns first matching file path and its raw contents
- `resolve_variable(var_name, context)` — simple table lookup against the merged context, returns string value or `nil`

---

## UI Modules

### `ui/float.lua`

- Opens via `vim.api.nvim_open_win` with `relative='cursor'`, positioned below-right of cursor
- Header line: `📄 company-header.md` for includes, `⚙ client = "Stormfront Inc"` for variables
- Width capped at 60 cols, height capped at 15 lines, scrollable
- Closes on `CursorMoved`; only one float open at a time

### `ui/virtual.lua`

- Uses `vim.api.nvim_buf_set_extmark` with `virt_lines` to insert dimmed lines below the target line
- Template content shown as-is; variables shown as `  ⟶  value`
- Highlight group: `MdDocVirtual` (linked to `Comment` by default, user-overridable)
- Extmarks stored by line number; toggling off calls `nvim_buf_del_extmark` to clean up

### `ui/split.lua`

- Opens a scratch buffer in a right-side vsplit (30% width default)
- `CursorHold` on the main buffer updates split content as cursor moves between `{% include %}` lines
- For variables: shows a summary panel of all resolved context variables
- Split closes when main buffer loses focus or is closed; keyed to the buffer

---

## Triggers

- **Auto-show:** `CursorHold` autocommand on `*.md` files (md-doc projects only)
- **Force-show:** `show_now` keymap triggers the float immediately regardless of `CursorHold` delay
- **Cursor patterns detected:**
  - Include: `{%%[- ]*include "([^"]+)"[- ]*%%}`
  - Variable: `{{ *([a-zA-Z_][a-zA-Z0-9_]*) *}}`  (filters like `| upper` are stripped before lookup)

---

## Configuration

```lua
require("md-doc").setup({
  auto_show = true,          -- trigger on CursorHold
  auto_show_delay = 500,     -- ms (sets vim.o.updatetime if lower than current value)
  modes = {
    float   = true,          -- on by default
    virtual = false,
    split   = false,
  },
  resolve_frontmatter = false, -- include frontmatter vars in {{ }} resolution
  keymaps = {
    toggle_float        = "<leader>mf",
    toggle_virtual      = "<leader>mv",
    toggle_split        = "<leader>ms",
    toggle_frontmatter  = "<leader>mr",
    show_now            = "K",
  },
})
```

- All keymaps are buffer-local, set only on md-doc `.md` files
- `K` does not override LSP hover in other buffers
- Multiple modes can be active simultaneously
- `resolve_frontmatter` starts at its configured default; `<leader>mr` flips it for the current session

---

## Out of Scope (v1)

- `{% for %}` / `{% if %}` block evaluation
- Rendering Jinja filters beyond stripping them for variable lookup
- Support for `.dotx` merge field syntax (`[[field_name]]`)
- Go-to-definition for includes (jumping into the template file)
- Integration with the existing `md-doc preview` server
