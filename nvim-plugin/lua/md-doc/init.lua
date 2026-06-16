local M = {}

local cascade = require("md-doc.cascade")
local resolve  = require("md-doc.resolve")
local runner   = require("md-doc.runner")
local float    = require("md-doc.ui.float")
local virtual  = require("md-doc.ui.virtual")
local split    = require("md-doc.ui.split")

local default_config = {
  auto_show = true,
  auto_show_delay = 500,
  modes = { float = true, virtual = false, split = false, document = false },
  resolve_frontmatter = true,
  disable_marksman = true,
  keymaps = {
    toggle_float       = "<leader>mf",
    toggle_virtual     = "<leader>mv",
    toggle_split       = "<leader>ms",
    toggle_document    = "<leader>mD",
    toggle_frontmatter = "<leader>mr",
    show_now           = "K",
    debug_context      = "<leader>m?",
    goto_source        = "<leader>mg",
    show_dependents    = "<leader>mu",
    build_file         = "<leader>mb",
    lint_file          = "<leader>ml",
    build_workspace    = "<leader>mB",
    lint_workspace     = "<leader>mL",
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

-- col is the 0-indexed cursor byte offset; when given, picks the {{ }}
-- closest to the cursor rather than always the first one on the line.
local function parse_cursor_line(line, col)
  local tmpl = line:match("{%%%-?%s*include%s+\"([^\"]+)\"%s*%-?%%}")
  if tmpl then return "include", tmpl end

  -- Collect all {{ expr }} spans with their positions (1-indexed)
  local best_expr, best_dist = nil, math.huge
  local pos = 1
  while true do
    local s, e, expr = line:find("{{%s*([^}]+)}}", pos)
    if not s then break end
    if col then
      local c = col + 1  -- convert nvim 0-indexed col to Lua 1-indexed
      local dist = (c >= s and c <= e) and 0
                   or math.min(math.abs(c - s), math.abs(c - e))
      if dist < best_dist then
        best_dist = dist
        best_expr = expr
      end
    else
      best_expr = expr
      break
    end
    pos = e + 1
  end

  if best_expr then return "variable", best_expr end
  return nil, nil
end

local parser = require("md-doc.parser")

-- Find the 1-indexed line in a file where `var_name:` is defined.
local function find_var_in_file(filepath, var_name)
  local pat = "^" .. var_name:gsub("[%^%$%(%)%%%.%[%]%*%+%-%?]", "%%%1") .. "%s*:"
  local f = io.open(filepath, "r")
  if not f then return 1 end
  local n = 0
  for line in f:lines() do
    n = n + 1
    if line:match(pat) then f:close(); return n end
  end
  f:close()
  return 1
end

-- Same but searches an already-loaded lines table (for the live buffer).
local function find_var_in_lines(lines, var_name)
  local pat = "^" .. var_name:gsub("[%^%$%(%)%%%.%[%]%*%+%-%?]", "%%%1") .. "%s*:"
  for i, line in ipairs(lines) do
    if line:match(pat) then return i end
  end
  return 1
end

-- Render the full document with all includes and variables resolved.
local function render_document(bufnr)
  local doc_path = vim.api.nvim_buf_get_name(bufnr)
  local repo_root = cascade.find_repo_root(vim.fn.fnamemodify(doc_path, ":h"))
  if not repo_root then return nil end

  local lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
  local raw = table.concat(lines, "\n")

  -- Parse frontmatter from the live buffer (handles unsaved changes).
  -- Use the parser's strip_frontmatter which correctly handles multi-line YAML.
  local fm = parser.strip_frontmatter(raw)
  local content = fm.body

  -- Load _meta.yml cascade from disk, then overlay live buffer frontmatter
  -- (buffer values take highest precedence, same as the build pipeline).
  local context = cascade.load_context(doc_path, false)
  for k, v in pairs(fm.vars) do context[k] = v end

  -- Resolve includes (guard against infinite loops with a depth counter)
  local function resolve_includes(text, depth)
    if depth > 10 then return text end
    return (text:gsub("{%%%-?%s*include%s+\"([^\"]+)\"%s*%-?%%}", function(tmpl)
      local result = resolve.resolve_include(tmpl, doc_path, repo_root)
      if not result then return "(include not found: " .. tmpl .. ")" end
      return resolve_includes(result.content, depth + 1)
    end))
  end
  content = resolve_includes(content, 0)

  -- Resolve variables
  content = content:gsub("{{%s*([^}]+)%s*}}", function(expr)
    local value = resolve.resolve_variable(expr, context)
    return value or ("{{ " .. expr:match("^%s*(.-)%s*$") .. " }}")
  end)

  local result = {}
  for line in (content .. "\n"):gmatch("([^\n]*)\n") do
    table.insert(result, line)
  end
  while #result > 0 and result[#result] == "" do table.remove(result) end
  return result
end

local function get_pipeline(bufnr)
  local doc_path = vim.api.nvim_buf_get_name(bufnr)
  local repo_root = cascade.find_repo_root(vim.fn.fnamemodify(doc_path, ":h"))
  return runner.find_pipeline(repo_root), doc_path, repo_root
end

function M.build_file(bufnr)
  local pipeline, doc_path = get_pipeline(bufnr)
  runner.run({ "build", doc_path }, pipeline, bufnr, "󰆨 build: " .. vim.fn.fnamemodify(doc_path, ":t"))
end

function M.lint_file(bufnr)
  local pipeline, doc_path = get_pipeline(bufnr)
  runner.run({ "lint", "--fix", doc_path }, pipeline, bufnr, "󰸖 lint: " .. vim.fn.fnamemodify(doc_path, ":t"))
end

function M.build_workspace(bufnr)
  local pipeline, _, repo_root = get_pipeline(bufnr)
  if not repo_root then
    vim.notify("md-doc: cannot detect workspace root", vim.log.levels.ERROR)
    return
  end
  runner.run({ "build", repo_root }, pipeline, bufnr, "󰆨 build workspace")
end

function M.lint_workspace(bufnr)
  local pipeline, _, repo_root = get_pipeline(bufnr)
  if not repo_root then
    vim.notify("md-doc: cannot detect workspace root", vim.log.levels.ERROR)
    return
  end
  runner.run({ "lint", "--fix", repo_root }, pipeline, bufnr, "󰸖 lint workspace")
end

function M.show_document_preview(bufnr)
  local doc_path = vim.api.nvim_buf_get_name(bufnr)
  local name = vim.fn.fnamemodify(doc_path, ":t:r")
  local lines = render_document(bufnr)
  if not lines or #lines == 0 then return end
  if split.is_open(bufnr) then
    split.update(bufnr, lines, "📋 " .. name)
  else
    split.open(bufnr, lines, "📋 " .. name)
  end
end

function M.show_preview(bufnr, force)
  local state = get_state(bufnr)

  -- Document mode takes over the split pane entirely
  if state.modes.document then
    M.show_document_preview(bufnr)
    return
  end

  local win = vim.fn.bufwinid(bufnr)
  if win == -1 then return end
  local cursor = vim.api.nvim_win_get_cursor(win)
  local lnum, col = cursor[1], cursor[2]
  local line = vim.api.nvim_buf_get_lines(bufnr, lnum - 1, lnum, false)[1] or ""

  local action, arg = parse_cursor_line(line, col)
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
    -- Always build context from cascade + live buffer frontmatter for hover.
    -- Track sources so we can show which file each variable comes from.
    local sourced = cascade.load_context_with_sources(doc_path)
    local all_lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
    local fm = parser.strip_frontmatter(table.concat(all_lines, "\n"))
    for k, v in pairs(fm.vars) do
      sourced[k] = { value = v, source = doc_path, frontmatter = true }
    end
    local var_name = arg:match("^%s*([%w_]+)") or arg
    local entry = sourced[var_name]
    local value = entry and tostring(entry.value)
    title = "⚙ " .. var_name
    if value then
      local src_label
      if entry.frontmatter then
        src_label = "  📝 frontmatter"
      else
        src_label = "  📄 " .. entry.source:sub(#repo_root + 2)
      end
      display_lines = { "  ⟶  " .. value, src_label }
    else
      display_lines = { "  (undefined)" }
    end
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

-- Jump to where a {{ variable }} is defined or open an {% include %} template.
function M.goto_source(bufnr)
  local doc_path = vim.api.nvim_buf_get_name(bufnr)
  local repo_root = cascade.find_repo_root(vim.fn.fnamemodify(doc_path, ":h"))
  if not repo_root then return end

  local win = vim.fn.bufwinid(bufnr)
  if win == -1 then return end
  local cursor = vim.api.nvim_win_get_cursor(win)
  local lnum, col = cursor[1], cursor[2]
  local line = vim.api.nvim_buf_get_lines(bufnr, lnum - 1, lnum, false)[1] or ""
  local action, arg = parse_cursor_line(line, col)
  if not action then
    vim.notify("md-doc: cursor is not on a template tag", vim.log.levels.INFO)
    return
  end

  if action == "include" then
    local result = resolve.resolve_include(arg, doc_path, repo_root)
    if not result then
      vim.notify("md-doc: include not found: " .. arg, vim.log.levels.WARN)
      return
    end
    vim.cmd("normal! m'")
    vim.cmd("edit " .. vim.fn.fnameescape(result.path))
  else
    local sourced = cascade.load_context_with_sources(doc_path)
    local all_lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
    local fm = parser.strip_frontmatter(table.concat(all_lines, "\n"))
    for k, v in pairs(fm.vars) do
      sourced[k] = { value = v, source = doc_path, frontmatter = true }
    end
    local var_name = arg:match("^%s*([%w_]+)") or arg
    local entry = sourced[var_name]
    if not entry then
      vim.notify("md-doc: '" .. var_name .. "' not found in cascade", vim.log.levels.WARN)
      return
    end
    vim.cmd("normal! m'")
    if entry.frontmatter then
      local n = find_var_in_lines(all_lines, var_name)
      vim.fn.cursor(n, 1)
    else
      local target_line = find_var_in_file(entry.source, var_name)
      vim.cmd("edit " .. vim.fn.fnameescape(entry.source))
      vim.fn.cursor(target_line, 1)
    end
  end
end

-- Find all .md files in the workspace that {% include %} the current file.
-- Results open in the quickfix list so the user can navigate them with <CR>.
function M.show_dependents(bufnr)
  local doc_path = vim.api.nvim_buf_get_name(bufnr)
  local repo_root = cascade.find_repo_root(vim.fn.fnamemodify(doc_path, ":h"))
  if not repo_root then
    vim.notify("md-doc: not in a project", vim.log.levels.WARN)
    return
  end
  local filename = vim.fn.fnamemodify(doc_path, ":t")
  local output = {}
  vim.fn.jobstart(
    {
      "grep", "-rl",
      "--include=*.md",
      "--exclude-dir=.git",
      "--exclude-dir=.venv",
      "--exclude-dir=node_modules",
      filename,
      repo_root,
    },
    {
      stdout_buffered = true,
      on_stdout = function(_, data)
        for _, p in ipairs(data) do
          if p ~= "" then table.insert(output, p) end
        end
      end,
      on_exit = function()
        vim.schedule(function()
          if #output == 0 then
            vim.notify("md-doc: nothing includes '" .. filename .. "'", vim.log.levels.INFO)
            return
          end
          local items = {}
          for _, path in ipairs(output) do
            table.insert(items, {
              filename = path,
              lnum = 1,
              text = path:sub(#repo_root + 2),
            })
          end
          vim.fn.setqflist({}, "r", {
            title = "md-doc: includes ← " .. filename,
            items = items,
          })
          vim.cmd("copen")
        end)
      end,
    }
  )
end

local function set_keymaps(bufnr)
  local state = get_state(bufnr)
  local km = config.keymaps
  local opts = { buffer = bufnr, noremap = true, silent = true }

  local function state_desc(label, getter)
    return function() return (getter() and "disable" or "enable") .. " " .. label end
  end

  local function toggle_icon(getter)
    return function()
      return getter()
        and { icon = "󰔡", color = "green" }
        or  { icon = "󰔢", color = "orange" }
    end
  end

  -- Register which-key group + dynamic state descriptions if available
  local ok, wk = pcall(require, "which-key")
  if ok then
    local prefix = km.toggle_float:match("^(.+)%a$") or "<leader>m"
    if wk.add then
      wk.add({
        { prefix,                group = "md-doc", icon = "󰦪", buffer = bufnr },
        { km.toggle_float,       icon = toggle_icon(function() return state.modes.float end),          desc = state_desc("float preview",      function() return state.modes.float end),         buffer = bufnr },
        { km.toggle_virtual,     icon = toggle_icon(function() return state.modes.virtual end),        desc = state_desc("virtual text",        function() return state.modes.virtual end),       buffer = bufnr },
        { km.toggle_split,       icon = toggle_icon(function() return state.modes.split end),          desc = state_desc("split pane",          function() return state.modes.split end),         buffer = bufnr },
        { km.toggle_document,    icon = toggle_icon(function() return state.modes.document end),       desc = state_desc("document preview",    function() return state.modes.document end),      buffer = bufnr },
        { km.toggle_frontmatter, icon = toggle_icon(function() return state.resolve_frontmatter end),  desc = state_desc("frontmatter vars",    function() return state.resolve_frontmatter end), buffer = bufnr },
        { km.show_now,           desc = "show preview now",               buffer = bufnr },
        { km.debug_context,      desc = "dump resolved variable context",  buffer = bufnr },
        { km.goto_source,        desc = "go to source / definition",       buffer = bufnr },
        { km.show_dependents,    desc = "show files that include this",     buffer = bufnr },
        { km.build_file,         desc = "build this file",                 buffer = bufnr },
        { km.lint_file,          desc = "lint this file",                  buffer = bufnr },
        { km.build_workspace,    desc = "build workspace",                 buffer = bufnr },
        { km.lint_workspace,     desc = "lint workspace",                  buffer = bufnr },
      })
    elseif wk.register then
      wk.register({ [prefix] = { name = "󰦪 md-doc" } }, { buffer = bufnr })
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

  vim.keymap.set("n", km.toggle_document, function()
    state.modes.document = not state.modes.document
    if state.modes.document then
      state.modes.split = false
      M.show_document_preview(bufnr)
      vim.notify("md-doc: document preview on")
    else
      split.close(bufnr)
      vim.notify("md-doc: document preview off")
    end
  end, vim.tbl_extend("force", opts, { desc = "md-doc: toggle full document preview" }))

  vim.keymap.set("n", km.toggle_frontmatter, function()
    state.resolve_frontmatter = not state.resolve_frontmatter
    vim.notify("md-doc: frontmatter " .. (state.resolve_frontmatter and "on" or "off"))
  end, vim.tbl_extend("force", opts, { desc = "md-doc: toggle frontmatter resolution" }))

  vim.keymap.set("n", km.show_now, function()
    M.show_preview(bufnr, true)
  end, vim.tbl_extend("force", opts, { desc = "md-doc: show preview now" }))

  vim.keymap.set("n", km.debug_context, function()
    local doc_path = vim.api.nvim_buf_get_name(bufnr)
    local repo_root = cascade.find_repo_root(vim.fn.fnamemodify(doc_path, ":h"))
    local lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
    local raw = table.concat(lines, "\n")
    local fm = parser.strip_frontmatter(raw)
    local cascade_ctx = repo_root and cascade.load_context(doc_path, false) or {}
    local merged = vim.deepcopy(cascade_ctx)
    for k, v in pairs(fm.vars) do merged[k] = v end

    local out = { "## md-doc context", "", "### Frontmatter (buffer)" }
    local fm_keys = vim.tbl_keys(fm.vars)
    table.sort(fm_keys)
    if #fm_keys == 0 then table.insert(out, "  (none parsed)") end
    for _, k in ipairs(fm_keys) do
      table.insert(out, string.format("  %s = %s", k, tostring(fm.vars[k])))
    end
    table.insert(out, "")
    table.insert(out, "### Cascade (_meta.yml)")
    local cas_keys = vim.tbl_keys(cascade_ctx)
    table.sort(cas_keys)
    if #cas_keys == 0 then table.insert(out, "  (none)") end
    for _, k in ipairs(cas_keys) do
      table.insert(out, string.format("  %s = %s", k, tostring(cascade_ctx[k])))
    end
    table.insert(out, "")
    table.insert(out, "### Merged (what the preview uses)")
    local merged_keys = vim.tbl_keys(merged)
    table.sort(merged_keys)
    for _, k in ipairs(merged_keys) do
      table.insert(out, string.format("  %s = %s", k, tostring(merged[k])))
    end
    float.show(out, "󰦪 md-doc context")
  end, vim.tbl_extend("force", opts, { desc = "md-doc: dump resolved variable context" }))

  vim.keymap.set("n", km.goto_source, function()
    M.goto_source(bufnr)
  end, vim.tbl_extend("force", opts, { desc = "md-doc: go to source" }))

  vim.keymap.set("n", km.show_dependents, function()
    M.show_dependents(bufnr)
  end, vim.tbl_extend("force", opts, { desc = "md-doc: show dependents" }))

  vim.keymap.set("n", km.build_file, function()
    M.build_file(bufnr)
  end, vim.tbl_extend("force", opts, { desc = "md-doc: build this file" }))

  vim.keymap.set("n", km.lint_file, function()
    M.lint_file(bufnr)
  end, vim.tbl_extend("force", opts, { desc = "md-doc: lint this file" }))

  vim.keymap.set("n", km.build_workspace, function()
    M.build_workspace(bufnr)
  end, vim.tbl_extend("force", opts, { desc = "md-doc: build workspace" }))

  vim.keymap.set("n", km.lint_workspace, function()
    M.lint_workspace(bufnr)
  end, vim.tbl_extend("force", opts, { desc = "md-doc: lint workspace" }))
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

  -- Marksman treats [[field]] as wiki-links; in md-doc projects they are Word
  -- merge field placeholders.  When disable_marksman = true (default), stop the
  -- client from attaching to this buffer entirely.  Otherwise fall back to
  -- suppressing only the false-positive "Link to non-existent document"
  -- diagnostics (requires Neovim 0.10+ for namespace-scoped config).
  local function handle_marksman(client_id)
    local client = vim.lsp.get_client_by_id(client_id)
    if not (client and client.name == "marksman") then return end
    if config.disable_marksman then
      vim.lsp.buf_detach_client(bufnr, client_id)
      -- Detaching stops future updates but leaves already-published diagnostics
      -- in the buffer. Clear them explicitly after the current event loop tick.
      vim.schedule(function()
        pcall(function()
          local ns = vim.lsp.diagnostic.get_namespace(client_id)
          vim.diagnostic.reset(ns, bufnr)
        end)
      end)
      return
    end
    -- Suppress [[field]] false positives without disabling marksman fully
    if vim.fn.has("nvim-0.10") == 1 then
      local ok, ns = pcall(vim.lsp.diagnostic.get_namespace, client_id)
      if ok then
        vim.diagnostic.config({
          filter = function(diag)
            return not diag.message:match("Link to non%-existent document")
          end,
        }, ns)
      end
    end
  end

  vim.api.nvim_create_autocmd("LspAttach", {
    buffer = bufnr,
    callback = function(ev) handle_marksman(ev.data.client_id) end,
  })

  -- Handle the race where Marksman attached before activate() was called
  for _, client in ipairs(vim.lsp.get_clients({ bufnr = bufnr })) do
    handle_marksman(client.id)
  end

  if config.auto_show then
    if config.auto_show_delay < vim.o.updatetime then
      vim.o.updatetime = config.auto_show_delay
    end
    vim.api.nvim_create_autocmd("CursorHold", {
      buffer = bufnr,
      callback = function() M.show_preview(bufnr, false) end,
    })
    -- Keep document preview fresh when the buffer is written
    vim.api.nvim_create_autocmd("BufWritePost", {
      buffer = bufnr,
      callback = function()
        local s = get_state(bufnr)
        if s.modes.document then M.show_document_preview(bufnr) end
      end,
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

  local function try_activate(bufnr)
    local path = vim.api.nvim_buf_get_name(bufnr)
    if path == "" then return end
    local dir = vim.fn.fnamemodify(path, ":h")
    if cascade.find_repo_root(dir) or cascade.find_meta_root(dir) then
      activate(bufnr)
    end
  end

  vim.api.nvim_create_autocmd({ "BufEnter", "BufReadPost" }, {
    pattern = "*.md",
    callback = function(ev) try_activate(ev.buf) end,
  })

  -- When loaded lazily (ft = "markdown"), BufReadPost has already fired for
  -- the triggering buffer before setup() runs. Activate any open md buffers now.
  vim.schedule(function()
    for _, bufnr in ipairs(vim.api.nvim_list_bufs()) do
      if vim.api.nvim_buf_is_loaded(bufnr)
         and vim.bo[bufnr].filetype == "markdown" then
        try_activate(bufnr)
      end
    end
  end)
end

return M
