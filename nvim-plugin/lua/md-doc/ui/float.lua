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

  local width = math.min(72, vim.o.columns - 4)

  -- Calculate height accounting for lines that wrap within the window.
  local height = 0
  for _, line in ipairs(lines) do
    local display_len = vim.fn.strdisplaywidth(line)
    height = height + math.max(1, math.ceil(display_len / width))
  end
  height = math.min(height, 20)
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

  vim.api.nvim_set_option_value("wrap", true, { win = win })

  _win = win
  _buf = buf

  vim.api.nvim_create_autocmd("CursorMoved", {
    once = true,
    callback = M.close,
  })
end

return M
