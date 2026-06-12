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
  resolve_frontmatter = true,

  -- Detach Marksman LSP from md-doc buffers (recommended).
  -- Marksman treats [[field]] as wiki-links; in md-doc projects they are Word
  -- merge field placeholders, causing spurious diagnostics.  Set to false to
  -- keep Marksman attached but only suppress the "Link to non-existent document"
  -- warnings (requires Neovim 0.10+).
  disable_marksman = true,

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
| `<leader>mb` | Build current file |
| `<leader>ml` | Lint current file |
| `<leader>mB` | Build workspace |
| `<leader>mL` | Lint workspace |
| `<leader>mg` | Go to source (open the file where the variable/include is defined) |
| `<leader>mu` | Show files that include this file (quickfix list) |
| `<leader>m?` | Dump resolved variable context |

### What it previews

| Cursor on | What you see |
|---|---|
| `{% include "partials/header.md" %}` | Full resolved contents of the template file |
| `{{ client }}` | Value from the `_meta.yml` cascade + which file it came from |
| `{{ status \| upper }}` | Resolved value (Jinja2 filters stripped for lookup) |

The hover float shows where each variable is inherited from:

```
⚙ client
  ⟶  Acme Corp
  📄 workspace/acme/_meta.yml
```

Or for variables defined in the document's own frontmatter:

```
⚙ type
  ⟶  Policy Wording
  📝 frontmatter
```

### Navigation

**Go to source** (`<leader>mg`): jump to where the thing under the cursor is defined.
- On `{{ variable }}` → opens the `_meta.yml` file at the line where the variable is set (or jumps to the frontmatter line if it's defined in this document). Press `<C-o>` to come back.
- On `{% include "path" %}` → opens the template file directly.

**Show dependents** (`<leader>mu`): find all `.md` files in the workspace that `{% include %}` the current file. Results appear in the quickfix list — press `<CR>` on any entry to open it.

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

## Running builds and lints from Neovim

Add a `.md-doc.yml` file to the root of your document project pointing at your `md-doc-pipeline` installation:

```yaml
# ~/aib-document-generator/.md-doc.yml
pipeline: ~/md-doc-pipeline
```

Then from any `.md` file in the project:

| Key | Command |
|---|---|
| `<leader>mb` | `md-doc build <current file>` |
| `<leader>ml` | `md-doc lint <current file>` |
| `<leader>mB` | `md-doc build <workspace root>` |
| `<leader>mL` | `md-doc lint <workspace root>` |

Output streams live into the split pane. A notification fires on completion.

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
- Verify a `_meta.yml` file exists at or above the document directory, or that
  the variable is defined in the document's own YAML front matter.
- The hover/float preview always resolves both cascade and frontmatter variables.
  Use `<leader>m?` to dump the full resolved context and confirm the variable exists.

**`{% include %}` preview is empty**
- The template path is resolved relative to the document's directory, then
  ancestor `templates/` directories, then the repo root. Confirm the file exists
  at one of those locations.

**K conflicts with LSP hover in other buffers**
- The keymap is buffer-local and only set when the plugin activates on an md-doc
  `.md` file. It does not affect other buffers.
