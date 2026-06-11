local M = {}

local NS = vim.api.nvim_create_namespace("md-doc-virtual")

function M.show(bufnr, lnum, lines, title)
  M.clear(bufnr, lnum)

  local virt_lines = {}
  table.insert(virt_lines, { { "  ╔ " .. title, "MdDocVirtualLabel" } })
  for _, line in ipairs(lines) do
    table.insert(virt_lines, { { "  │ " .. line, "MdDocVirtual" } })
  end
  table.insert(virt_lines, { { "  ╚" .. string.rep("─", 38), "MdDocVirtualLabel" } })

  vim.api.nvim_buf_set_extmark(bufnr, NS, lnum - 1, 0, {
    virt_lines = virt_lines,
    virt_lines_above = false,
  })
end

function M.clear(bufnr, lnum)
  local marks = vim.api.nvim_buf_get_extmarks(bufnr, NS, { lnum - 1, 0 }, { lnum - 1, -1 }, {})
  for _, mark in ipairs(marks) do
    vim.api.nvim_buf_del_extmark(bufnr, NS, mark[1])
  end
end

function M.clear_all(bufnr)
  vim.api.nvim_buf_clear_namespace(bufnr, NS, 0, -1)
end

return M
