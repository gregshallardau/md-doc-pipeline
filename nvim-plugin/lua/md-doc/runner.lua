local M = {}

local split = require("md-doc.ui.split")

-- Read pipeline path from .md-doc.yml in the repo root.
function M.find_pipeline(repo_root)
  if not repo_root then return nil end
  local f = io.open(repo_root .. "/.md-doc.yml", "r")
  if not f then return nil end
  local content = f:read("*a")
  f:close()
  local path = content:match("[^\n]*pipeline:%s*([^\n]+)")
  if not path then return nil end
  path = path:match("^%s*(.-)%s*$")
  -- Expand ~
  path = path:gsub("^~", vim.fn.expand("~"))
  return path
end

-- Run an md-doc CLI command asynchronously, streaming output to the split pane.
-- args: list of CLI args after "md-doc" (e.g. {"build", "/path/to/file.md"})
-- bufnr: the source buffer (for the split pane)
-- title: split pane title
function M.run(args, pipeline_path, bufnr, title)
  if not pipeline_path then
    vim.notify("md-doc: no pipeline path — add 'pipeline: /path/to/md-doc-pipeline' to .md-doc.yml", vim.log.levels.ERROR)
    return
  end

  local lines = { "$ md-doc " .. table.concat(args, " "), "" }
  if split.is_open(bufnr) then
    split.update(bufnr, lines, title)
  else
    split.open(bufnr, lines, title)
  end

  local cmd = { "uv", "run", "md-doc" }
  vim.list_extend(cmd, args)

  local function append(data)
    if not data then return end
    for _, line in ipairs(data) do
      if line ~= "" then
        table.insert(lines, line)
      end
    end
    split.update(bufnr, lines, title)
  end

  vim.fn.jobstart(cmd, {
    cwd = pipeline_path,
    on_stdout = function(_, data) append(data) end,
    on_stderr = function(_, data) append(data) end,
    on_exit = function(_, code)
      table.insert(lines, "")
      table.insert(lines, code == 0 and "✓ done" or ("✗ exited " .. code))
      split.update(bufnr, lines, title)
      vim.notify(
        "md-doc " .. args[1] .. (code == 0 and " complete" or " failed (exit " .. code .. ")"),
        code == 0 and vim.log.levels.INFO or vim.log.levels.ERROR
      )
    end,
  })
end

return M
