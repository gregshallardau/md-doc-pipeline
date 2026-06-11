local M = {}

local _state = {}  -- keyed by main bufnr: { bufnr, win }

function M.is_open(main_bufnr)
  local s = _state[main_bufnr]
  return s ~= nil and vim.api.nvim_buf_is_valid(s.bufnr)
end

local function set_content(bufnr, lines, title)
  local display = { "# " .. title, "" }
  for _, line in ipairs(lines) do table.insert(display, line) end
  vim.api.nvim_set_option_value("modifiable", true, { buf = bufnr })
  vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, display)
  vim.api.nvim_set_option_value("modifiable", false, { buf = bufnr })
end

function M.open(main_bufnr, lines, title)
  if M.is_open(main_bufnr) then
    M.update(main_bufnr, lines, title)
    return _state[main_bufnr].bufnr
  end

  local orig_win = vim.api.nvim_get_current_win()
  local split_width = math.floor(vim.o.columns * 0.3)
  vim.cmd("botright " .. split_width .. "vsplit")
  local split_win = vim.api.nvim_get_current_win()

  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_win_set_buf(split_win, buf)
  vim.api.nvim_set_option_value("filetype", "markdown", { buf = buf })
  vim.api.nvim_set_option_value("buftype", "nofile", { buf = buf })
  set_content(buf, lines, title)

  _state[main_bufnr] = { bufnr = buf, win = split_win }
  vim.api.nvim_set_current_win(orig_win)

  vim.api.nvim_create_autocmd({ "BufDelete", "BufUnload" }, {
    buffer = main_bufnr,
    once = true,
    callback = function() M.close(main_bufnr) end,
  })

  return buf
end

function M.update(main_bufnr, lines, title)
  local s = _state[main_bufnr]
  if not s or not vim.api.nvim_buf_is_valid(s.bufnr) then return end
  set_content(s.bufnr, lines, title)
end

function M.close(main_bufnr)
  local s = _state[main_bufnr]
  if not s then return end
  if vim.api.nvim_win_is_valid(s.win) then
    vim.api.nvim_win_close(s.win, true)
  end
  _state[main_bufnr] = nil
end

return M
