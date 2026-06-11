local M = {}
local parser = require("md-doc.parser")

local function exists(path)
  local f = io.open(path, "r")
  if f then f:close() return true end
  return false
end

local function dir_of(path)
  return path:match("^(.+)/[^/]+$") or "."
end

function M.find_repo_root(start_dir)
  local dir = start_dir
  while true do
    if exists(dir .. "/pyproject.toml") or vim.fn.isdirectory(dir .. "/.git") == 1 or vim.fn.filereadable(dir .. "/.git") == 1 then
      return dir
    end
    local parent = dir:match("^(.+)/[^/]+$")
    if not parent then return nil end
    dir = parent
  end
end

local function collect_meta_files(doc_path, repo_root)
  local doc_dir = dir_of(doc_path)
  local dirs = { repo_root }
  local rel = doc_dir:sub(#repo_root + 2)
  local accumulated = repo_root
  for part in rel:gmatch("[^/]+") do
    accumulated = accumulated .. "/" .. part
    table.insert(dirs, accumulated)
  end
  local files = {}
  for _, d in ipairs(dirs) do
    local p = d .. "/_meta.yml"
    if exists(p) then table.insert(files, p) end
  end
  return files
end

function M.load_context(doc_path, include_frontmatter)
  local repo_root = M.find_repo_root(dir_of(doc_path))
  if not repo_root then
    if include_frontmatter then
      local f = io.open(doc_path, "r")
      if f then
        local content = f:read("*a")
        f:close()
        return parser.strip_frontmatter(content).vars
      end
    end
    return {}
  end

  local context = {}
  for _, meta_path in ipairs(collect_meta_files(doc_path, repo_root)) do
    local f = io.open(meta_path, "r")
    if f then
      local vars = parser.parse_yaml(f:read("*a"))
      f:close()
      for k, v in pairs(vars) do context[k] = v end
    end
  end

  if include_frontmatter then
    local f = io.open(doc_path, "r")
    if f then
      local vars = parser.strip_frontmatter(f:read("*a")).vars
      f:close()
      for k, v in pairs(vars) do context[k] = v end
    end
  end

  return context
end

return M
