local M = {}

local cascade = require("md-doc.cascade")
local resolve  = require("md-doc.resolve")
local float    = require("md-doc.ui.float")
local virtual  = require("md-doc.ui.virtual")
local split    = require("md-doc.ui.split")

local default_config = {
  auto_show = true,
  auto_show_delay = 500,
  modes = { float = true, virtual = false, split = false },
  resolve_frontmatter = false,
  keymaps = {
    toggle_float       = "<leader>mf",
    toggle_virtual     = "<leader>mv",
    toggle_split       = "<leader>ms",
    toggle_frontmatter = "<leader>mr",
    show_now           = "K",
  },
}

local config = vim.deepcopy(default_config)
local buf_state = {}

local function get_state(bufnr)
  if not buf_state[bufnr] then
    buf_state[bufnr] = {
      modes = vim.deepcopy(config.modes),
      resolve_frontmatter = config.resolve_frontmatter,
      _active = false,
    }
  end
  return buf_state[bufnr]
end

local function parse_cursor_line(line)
  local tmpl = line:match("{%%%-?%s*include%s+\"([^\"]+)\"%s*%-?%%}")
  if tmpl then return "include", tmpl end
  local var = line:match("{{%s*([^}]+)}}")
  if var then return "variable", var end
  return nil, nil
end

function M.show_preview(bufnr, force)
  local state = get_state(bufnr)
  local win = vim.fn.bufwinid(bufnr)
  if win == -1 then return end
  local lnum = vim.api.nvim_win_get_cursor(win)[1]
  local line = vim.api.nvim_buf_get_lines(bufnr, lnum - 1, lnum, false)[1] or ""

  local action, arg = parse_cursor_line(line)
  if not action then return end

  local doc_path = vim.api.nvim_buf_get_name(bufnr)
  local repo_root = cascade.find_repo_root(vim.fn.fnamemodify(doc_path, ":h"))
  if not repo_root then return end

  local display_lines, title

  if action == "include" then
    local result = resolve.resolve_include(arg, doc_path, repo_root)
    if not result then return end
    title = "📄 " .. arg
    display_lines = {}
    for ln in (result.content .. "\n"):gmatch("([^\n]*)\n") do
      table.insert(display_lines, ln)
    end
    while #display_lines > 0 and display_lines[#display_lines] == "" do
      table.remove(display_lines)
    end
  else
    local context = cascade.load_context(doc_path, state.resolve_frontmatter)
    local value = resolve.resolve_variable(arg, context)
    local var_name = arg:match("^%s*([%w_]+)") or arg
    title = "⚙ " .. var_name
    display_lines = { value and ("⟶  " .. value) or "(undefined)" }
  end

  if #display_lines == 0 then return end

  if state.modes.float or force then float.show(display_lines, title) end
  if state.modes.virtual then virtual.show(bufnr, lnum, display_lines, title) end
  if state.modes.split then
    if split.is_open(bufnr) then
      split.update(bufnr, display_lines, title)
    else
      split.open(bufnr, display_lines, title)
    end
  end
end

local function set_keymaps(bufnr)
  local state = get_state(bufnr)
  local km = config.keymaps
  local opts = { buffer = bufnr, noremap = true, silent = true }

  -- Register which-key group if available (supports both v2 and v3 APIs)
  local ok, wk = pcall(require, "which-key")
  if ok then
    local prefix = km.toggle_float:match("^(.+)%a$") or "<leader>m"
    if wk.add then
      wk.add({ { prefix, group = "md-doc", buffer = bufnr } })
    elseif wk.register then
      wk.register({ [prefix] = { name = "md-doc" } }, { buffer = bufnr })
    end
  end

  vim.keymap.set("n", km.toggle_float, function()
    state.modes.float = not state.modes.float
    vim.notify("md-doc: float " .. (state.modes.float and "on" or "off"))
  end, vim.tbl_extend("force", opts, { desc = "md-doc: toggle float preview" }))

  vim.keymap.set("n", km.toggle_virtual, function()
    state.modes.virtual = not state.modes.virtual
    if not state.modes.virtual then virtual.clear_all(bufnr) end
    vim.notify("md-doc: virtual text " .. (state.modes.virtual and "on" or "off"))
  end, vim.tbl_extend("force", opts, { desc = "md-doc: toggle virtual text" }))

  vim.keymap.set("n", km.toggle_split, function()
    state.modes.split = not state.modes.split
    if not state.modes.split then split.close(bufnr) end
    vim.notify("md-doc: split " .. (state.modes.split and "on" or "off"))
  end, vim.tbl_extend("force", opts, { desc = "md-doc: toggle split pane" }))

  vim.keymap.set("n", km.toggle_frontmatter, function()
    state.resolve_frontmatter = not state.resolve_frontmatter
    vim.notify("md-doc: frontmatter " .. (state.resolve_frontmatter and "on" or "off"))
  end, vim.tbl_extend("force", opts, { desc = "md-doc: toggle frontmatter resolution" }))

  vim.keymap.set("n", km.show_now, function()
    M.show_preview(bufnr, true)
  end, vim.tbl_extend("force", opts, { desc = "md-doc: show preview now" }))
end

local function setup_highlights()
  vim.api.nvim_set_hl(0, "MdDocVirtual",      { link = "Comment", default = true })
  vim.api.nvim_set_hl(0, "MdDocVirtualLabel", { link = "Special", default = true })
end

local function activate(bufnr)
  local state = get_state(bufnr)
  if state._active then return end
  state._active = true

  set_keymaps(bufnr)

  if config.auto_show then
    if config.auto_show_delay < vim.o.updatetime then
      vim.o.updatetime = config.auto_show_delay
    end
    vim.api.nvim_create_autocmd("CursorHold", {
      buffer = bufnr,
      callback = function() M.show_preview(bufnr, false) end,
    })
  end

  vim.api.nvim_create_autocmd("BufDelete", {
    buffer = bufnr,
    once = true,
    callback = function()
      virtual.clear_all(bufnr)
      split.close(bufnr)
      buf_state[bufnr] = nil
    end,
  })
end

function M.setup(opts)
  config = vim.tbl_deep_extend("force", default_config, opts or {})
  setup_highlights()

  vim.api.nvim_create_autocmd({ "BufEnter", "BufReadPost" }, {
    pattern = "*.md",
    callback = function(ev)
      local path = vim.api.nvim_buf_get_name(ev.buf)
      if path == "" then return end
      local dir = vim.fn.fnamemodify(path, ":h")
      if cascade.find_repo_root(dir) then
        activate(ev.buf)
      end
    end,
  })
end

return M
