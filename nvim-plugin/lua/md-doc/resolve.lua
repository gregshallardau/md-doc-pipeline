local M = {}

local function exists(path)
  local f = io.open(path, "r")
  if f then f:close() return true end
  return false
end

local function read_file(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local content = f:read("*a")
  f:close()
  return content
end

local function dir_of(path)
  return path:match("^(.+)/[^/]+$") or "."
end

function M.build_search_dirs(doc_path, repo_root)
  local doc_dir = dir_of(doc_path)
  local dirs = {}
  local seen = {}
  local function add(d)
    if not seen[d] then seen[d] = true; table.insert(dirs, d) end
  end

  add(doc_dir)
  add(doc_dir .. "/templates")

  -- Extract relative path from repo_root to doc_dir
  local rel = doc_dir:sub(#repo_root + 2)
  local parts = {}
  for part in rel:gmatch("[^/]+") do table.insert(parts, part) end

  -- Build intermediate ancestors (deepest first)
  for i = #parts - 1, 1, -1 do
    local ancestor = repo_root
    for j = 1, i do ancestor = ancestor .. "/" .. parts[j] end
    add(ancestor .. "/templates")
    add(ancestor)
  end

  add(repo_root .. "/templates")
  add(repo_root)
  return dirs
end

function M.resolve_include(template_name, doc_path, repo_root)
  for _, dir in ipairs(M.build_search_dirs(doc_path, repo_root)) do
    local candidate = dir .. "/" .. template_name
    if exists(candidate) then
      return { path = candidate, content = read_file(candidate) }
    end
  end
  return nil
end

function M.resolve_variable(var_expr, context)
  local var_name = var_expr:match("^%s*([%w_]+)")
  if not var_name then return nil end
  return context[var_name]
end

return M
