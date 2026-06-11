-- Headless test runner. Run with:
--   nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
--
-- Exit code 1 on failure (via cquit).

local repo_root = vim.fn.getcwd()
package.path = repo_root .. "/nvim-plugin/lua/?.lua;"
            .. repo_root .. "/nvim-plugin/lua/?/init.lua;"
            .. package.path

local pass_count = 0
local fail_count = 0

_G.describe = function(suite_name, fn)
  io.write("\n" .. suite_name .. "\n")
  fn()
end

_G.it = function(name, fn)
  local ok, err = pcall(fn)
  if ok then
    pass_count = pass_count + 1
    io.write("  ✓ " .. name .. "\n")
  else
    fail_count = fail_count + 1
    io.write("  ✗ " .. name .. "\n")
    io.write("    " .. tostring(err) .. "\n")
  end
end

_G.eq = function(a, b)
  if a ~= b then
    error("expected " .. vim.inspect(b) .. ", got " .. vim.inspect(a), 2)
  end
end

_G.is_nil = function(a)
  if a ~= nil then
    error("expected nil, got " .. vim.inspect(a), 2)
  end
end

_G.not_nil = function(a)
  if a == nil then
    error("expected non-nil value, got nil", 2)
  end
end

_G.neq = function(a, b)
  if a == b then
    error("expected values to differ, both are " .. vim.inspect(a), 2)
  end
end

dofile(repo_root .. "/nvim-plugin/tests/test_parser.lua")
dofile(repo_root .. "/nvim-plugin/tests/test_cascade.lua")
dofile(repo_root .. "/nvim-plugin/tests/test_resolve.lua")

io.write("\n────────────────────────────────────\n")
io.write(pass_count .. " passed, " .. fail_count .. " failed\n")

if fail_count > 0 then
  vim.cmd("cquit 1")
end
