# md-doc.nvim

Neovim plugin for [md-doc-pipeline](https://github.com/gregshallardau/md-doc-pipeline).

Previews `{% include %}` template fragments and resolves `{{ variable }}` values
inline while you edit `.md` documents. Activates automatically on any `.md` file
inside an md-doc project (a directory that contains a `pyproject.toml` or `.git`
marker).

## Requirements

- **Neovim 0.9+**
- A plugin manager (lazy.nvim, packer.nvim, vim-plug, or manual `runtimepath`)
- An md-doc-pipeline project (directory with `pyproject.toml` or `.git`)

---

## Installation

### lazy.nvim (recommended)

```lua
{
  dir = "/path/to/md-doc-pipeline/nvim-plugin",
  ft = "markdown",
  config = function()
    require("md-doc").setup({})
  end,
}
```

If md-doc-pipeline is cloned to `~/projects/md-doc-pipeline`:

```lua
{
  dir = vim.fn.expand("~/projects/md-doc-pipeline/nvim-plugin"),
  ft = "markdown",
  config = function()
    require("md-doc").setup({})
  end,
}
```

### packer.nvim

```lua
use {
  "/path/to/md-doc-pipeline/nvim-plugin",
  config = function()
    require("md-doc").setup({})
  end,
}
```

### vim-plug

```vim
Plug '/path/to/md-doc-pipeline/nvim-plugin'
```

Then in your `init.lua` or a `after/plugin/md-doc.lua`:

```lua
require("md-doc").setup({})
```

### Manual (no plugin manager)

Add the plugin directory to Neovim's runtime path in your `init.lua`:

```lua
vim.opt.runtimepath:append("/path/to/md-doc-pipeline/nvim-plugin")
require("md-doc").setup({})
```

---

## Configuration

Call `setup()` with any options you want to override. All keys are optional.

```lua
require("md-doc").setup({
  -- Show preview automatically when the cursor rests on a line
  auto_show = true,

  -- Milliseconds before CursorHold fires (controls auto-show delay)
  auto_show_delay = 500,

  -- Which display modes are active by default
  modes = {
    float    = true,   -- LSP-style hover popup (closes on cursor move)
    virtual  = false,  -- Inline virtual text inserted below the line
    split    = false,  -- Persistent right-side split pane (cursor fragment)
    document = false,  -- Full rendered document in the split pane
  },

  -- Also use the current document's frontmatter in {{ }} resolution
  resolve_frontmatter = false,

  -- Buffer-local keymaps (only active inside md-doc .md files)
  keymaps = {
    toggle_float       = "<leader>mf",
    toggle_virtual     = "<leader>mv",
    toggle_split       = "<leader>ms",
    toggle_document    = "<leader>mD",
    toggle_frontmatter = "<leader>mr",
    show_now           = "K",   -- force-show float immediately
  },
})
```

> **Note:** `K` only overrides LSP hover inside md-doc `.md` buffers.
> It has no effect in other file types.

---

## Usage

Open any `.md` file inside an md-doc project. The plugin activates automatically.

### Preview on hover

With the default config, the float preview appears whenever the cursor rests on
a line containing a template tag (`auto_show = true`). Move the cursor away to
dismiss it.

### Keymaps

| Key | Action |
|---|---|
| `K` | Show float preview immediately |
| `<leader>mf` | Toggle float mode on/off |
| `<leader>mv` | Toggle virtual text mode on/off |
| `<leader>ms` | Toggle split pane (cursor fragment) on/off |
| `<leader>mD` | Toggle full document preview on/off |
| `<leader>mr` | Toggle frontmatter resolution on/off |

### What it previews

| Cursor on | What you see |
|---|---|
| `{% include "partials/header.md" %}` | Full resolved contents of the template file |
| `{{ client }}` | Value from the `_meta.yml` cascade |
| `{{ status \| upper }}` | Resolved value (Jinja2 filters stripped for lookup) |

---

## Display modes

All three modes can be active at the same time.

| Mode | Description | Toggle |
|---|---|---|
| **Float** | Popup window at the cursor, closes when cursor moves | `<leader>mf` |
| **Virtual text** | Dimmed lines inserted below the include/variable line | `<leader>mv` |
| **Split** | Persistent right-side pane showing the fragment under the cursor | `<leader>ms` |
| **Document** | Persistent right-side pane showing the whole rendered document | `<leader>mD` |

---

## How project detection works

The plugin looks for a `.git` directory or `pyproject.toml` by walking up from
the directory of the current file. If neither is found, the buffer is treated as
a plain Markdown file and the plugin stays inactive.

---

## Troubleshooting

**Plugin doesn't activate**
- Make sure the file is inside a directory that has `.git` or `pyproject.toml`
  somewhere above it.
- Check `:messages` for any Lua errors during startup.

**`{{ variable }}` shows `(undefined)`**
- Verify a `_meta.yml` file exists at or above the document directory.
- Enable frontmatter resolution with `<leader>mr` if the variable is defined in
  the document's own YAML front matter.

**`{% include %}` preview is empty**
- The template path is resolved relative to the document's directory, then
  ancestor `templates/` directories, then the repo root. Confirm the file exists
  at one of those locations.

**K conflicts with LSP hover in other buffers**
- The keymap is buffer-local and only set when the plugin activates on an md-doc
  `.md` file. It does not affect other buffers.
