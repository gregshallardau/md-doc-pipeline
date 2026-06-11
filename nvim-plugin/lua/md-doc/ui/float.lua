local M = {}

local _win = nil
local _buf = nil

function M.close()
  if _win and vim.api.nvim_win_is_valid(_win) then
    vim.api.nvim_win_close(_win, true)
  end
  _win = nil
  _buf = nil
end

function M.show(lines, title)
  M.close()

  local width = math.min(60, vim.o.columns - 4)
  local height = math.min(#lines, 15)
  if height == 0 then return end

  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.api.nvim_set_option_value("modifiable", false, { buf = buf })
  vim.api.nvim_set_option_value("filetype", "markdown", { buf = buf })

  local win = vim.api.nvim_open_win(buf, false, {
    relative = "cursor",
    row = 1,
    col = 0,
    width = width,
    height = height,
    style = "minimal",
    border = "rounded",
    title = " " .. title .. " ",
    title_pos = "left",
  })

  _win = win
  _buf = buf

  vim.api.nvim_create_autocmd("CursorMoved", {
    once = true,
    callback = M.close,
  })
end

return M
