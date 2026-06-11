# md-doc.nvim

Neovim plugin for md-doc-pipeline.
Previews `{% include %}` template fragments and resolves `{{ variable }}` values
inline while you edit `.md` documents.

Activates automatically on `.md` files inside an md-doc project (any directory
containing a `pyproject.toml` or `.git` marker).

## Installation

### lazy.nvim

```lua
{
  dir = "/path/to/md-doc-pipeline/nvim-plugin",
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

## Configuration

```lua
require("md-doc").setup({
  auto_show = true,           -- show preview on CursorHold
  auto_show_delay = 500,      -- milliseconds before CursorHold fires
  modes = {
    float   = true,           -- LSP-style hover popup (default on)
    virtual = false,          -- inline virtual text below the line
    split   = false,          -- persistent right-side split pane
  },
  resolve_frontmatter = false, -- include document frontmatter in {{ }} resolution
  keymaps = {
    toggle_float        = "<leader>mf",
    toggle_virtual      = "<leader>mv",
    toggle_split        = "<leader>ms",
    toggle_frontmatter  = "<leader>mr",
    show_now            = "K",   -- force-show float immediately
  },
})
```

All keymaps are buffer-local — they only apply inside md-doc `.md` files.
`K` does not override LSP hover in other buffers.

## What it previews

| Cursor on | Shows |
|---|---|
| `{% include "header.md" %}` | Full contents of the resolved template file |
| `{{ client }}` | Resolved value from `_meta.yml` cascade |
| `{{ status \| upper }}` | Resolved value (filter stripped for lookup) |

## Display modes

All three modes can be active simultaneously.

| Mode | Description | Toggle |
|---|---|---|
| Float | Popup window, closes on cursor move | `<leader>mf` |
| Virtual text | Dimmed lines inserted below the include/variable line | `<leader>mv` |
| Split | Persistent right-side pane, updates on cursor move | `<leader>ms` |

## Frontmatter toggle

By default, `{{ variable }}` resolution only uses `_meta.yml` cascade values.
Press `<leader>mr` to also include the current document's frontmatter variables.
