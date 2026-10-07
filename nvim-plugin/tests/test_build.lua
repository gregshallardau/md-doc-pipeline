local plugin = require("md-doc")
local runner = require("md-doc.runner")

local function fixture(fn)
  local root = vim.fn.tempname()
  vim.fn.mkdir(root .. "/.git", "p")
  vim.fn.writefile({ "pipeline: " .. root }, root .. "/.md-doc.yml")
  local buffers = {}
  local function buffer(path)
    vim.fn.writefile({ "old" }, path)
    local buf = vim.fn.bufadd(path)
    vim.fn.bufload(buf)
    vim.api.nvim_buf_set_lines(buf, 0, -1, false, { "new" })
    table.insert(buffers, buf)
    return buf
  end
  local original_run, original_notify = runner.run, vim.notify
  local calls, notices = {}, {}
  runner.run = function(args)
    table.insert(calls, args)
    -- All workspace writes must finish before the command launches.
    for _, buf in ipairs(buffers) do
      local name = vim.api.nvim_buf_get_name(buf)
      if name:sub(1, #root + 1) == root .. "/" then
        eq(vim.fn.readfile(name)[1], "new")
      end
    end
  end
  vim.notify = function(message) table.insert(notices, message) end
  local ok, err = pcall(fn, root, buffer, calls, notices)
  runner.run, vim.notify = original_run, original_notify
  for _, buf in ipairs(buffers) do vim.api.nvim_buf_delete(buf, { force = true }) end
  vim.fn.delete(root, "rf")
  if not ok then error(err) end
end

describe("Build saves", function()
  it("saves the current buffer before a single-file build", function()
    fixture(function(root, buffer, calls)
      local buf = buffer(root .. "/doc.md")
      plugin.build_file(buf)
      eq(#calls, 1)
      eq(calls[1][2], root .. "/doc.md")
      eq(vim.bo[buf].modified, false)
    end)
  end)

  it("saves all modified workspace files before a workspace build", function()
    fixture(function(root, buffer, calls)
      local first = buffer(root .. "/doc.md")
      buffer(root .. "/_meta.yml")
      plugin.build_workspace(first)
      eq(#calls, 1)
      eq(calls[1][2], root)
      eq(calls[1][3], "--force")
    end)
  end)

  it("builds meta-only workspaces using their configured pipeline", function()
    fixture(function(root, buffer, calls)
      vim.fn.delete(root .. "/.git", "rf")
      vim.fn.writefile({ "company: Acme" }, root .. "/_meta.yml")
      vim.fn.mkdir(root .. "/client", "p")
      vim.fn.writefile({ "status: draft" }, root .. "/client/_meta.yml")
      local buf = buffer(root .. "/client/doc.md")
      plugin.build_file(buf)
      plugin.build_workspace(buf)
      eq(#calls, 2)
      eq(calls[1][2], root .. "/client/doc.md")
      eq(calls[2][2], root)
    end)
  end)

  it("cancels a build when a file cannot be saved", function()
    fixture(function(root, buffer, calls, notices)
      local buf = buffer(root .. "/doc.md")
      vim.bo[buf].readonly = true
      plugin.build_file(buf)
      eq(#calls, 0)
      eq(vim.bo[buf].modified, true)
      eq(#notices, 1)
      not_nil(notices[1]:match("build cancelled"))
    end)
  end)
end)
