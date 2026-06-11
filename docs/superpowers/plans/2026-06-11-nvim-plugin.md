# Neovim Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Neovim plugin (`nvim-plugin/`) that shows inline previews of `{% include %}` template fragments and `{{ variable }}` values from the md-doc-pipeline cascade, with three independently-togglable display modes: float, virtual text, and split pane.

**Architecture:** Pure Lua, no external dependencies. Core modules (`parser`, `cascade`, `resolve`) reimplement the Python cascade logic using standard Lua I/O. UI modules use Neovim APIs. An `init.lua` module wires everything together via autocommands and buffer-local keymaps.

**Tech Stack:** Lua 5.1 (Neovim's LuaJIT), Neovim 0.9+ APIs (`nvim_open_win`, `nvim_buf_set_extmark`, `nvim_create_autocmd`), no external libraries.

---

## File Map

| File | Responsibility |
|---|---|
| `nvim-plugin/plugin/md-doc.lua` | Autoload guard shim — prevents double-loading |
| `nvim-plugin/lua/md-doc/parser.lua` | Flat YAML key-value parser + frontmatter strip |
| `nvim-plugin/lua/md-doc/cascade.lua` | Repo root detection, `_meta.yml` walk, context merge |
| `nvim-plugin/lua/md-doc/resolve.lua` | Search dir builder, `{% include %}` resolver, `{{ var }}` lookup |
| `nvim-plugin/lua/md-doc/ui/float.lua` | Floating window display |
| `nvim-plugin/lua/md-doc/ui/virtual.lua` | Virtual text via extmarks |
| `nvim-plugin/lua/md-doc/ui/split.lua` | Vertical split pane |
| `nvim-plugin/lua/md-doc/init.lua` | `setup()`, autocommands, keymaps, cursor dispatch |
| `nvim-plugin/tests/run.lua` | Headless test runner |
| `nvim-plugin/tests/test_parser.lua` | Parser unit tests |
| `nvim-plugin/tests/test_cascade.lua` | Cascade unit tests |
| `nvim-plugin/tests/test_resolve.lua` | Resolve unit tests |
| `nvim-plugin/README.md` | Installation and usage docs |

---

## Task 1: Scaffold directory structure and autoload shim

**Files:**
- Create: `nvim-plugin/plugin/md-doc.lua`
- Create: `nvim-plugin/lua/md-doc/parser.lua` (stub)
- Create: `nvim-plugin/lua/md-doc/cascade.lua` (stub)
- Create: `nvim-plugin/lua/md-doc/resolve.lua` (stub)
- Create: `nvim-plugin/lua/md-doc/ui/float.lua` (stub)
- Create: `nvim-plugin/lua/md-doc/ui/virtual.lua` (stub)
- Create: `nvim-plugin/lua/md-doc/ui/split.lua` (stub)
- Create: `nvim-plugin/lua/md-doc/init.lua` (stub)
- Create: `nvim-plugin/tests/run.lua`

- [ ] **Step 1: Create directory tree**

```bash
mkdir -p nvim-plugin/plugin
mkdir -p nvim-plugin/lua/md-doc/ui
mkdir -p nvim-plugin/tests
```

- [ ] **Step 2: Create the autoload shim**

`nvim-plugin/plugin/md-doc.lua`:
```lua
if vim.g.loaded_md_doc then return end
vim.g.loaded_md_doc = 1
```

- [ ] **Step 3: Create stub modules**

Each of these files starts the same way — empty module, returns M. Create them:

`nvim-plugin/lua/md-doc/parser.lua`:
```lua
local M = {}
return M
```

`nvim-plugin/lua/md-doc/cascade.lua`:
```lua
local M = {}
return M
```

`nvim-plugin/lua/md-doc/resolve.lua`:
```lua
local M = {}
return M
```

`nvim-plugin/lua/md-doc/ui/float.lua`:
```lua
local M = {}
return M
```

`nvim-plugin/lua/md-doc/ui/virtual.lua`:
```lua
local M = {}
return M
```

`nvim-plugin/lua/md-doc/ui/split.lua`:
```lua
local M = {}
return M
```

`nvim-plugin/lua/md-doc/init.lua`:
```lua
local M = {}
return M
```

- [ ] **Step 4: Create the test runner**

`nvim-plugin/tests/run.lua`:
```lua
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
```

- [ ] **Step 5: Create placeholder test files**

`nvim-plugin/tests/test_parser.lua`:
```lua
-- parser tests (filled in Task 2)
```

`nvim-plugin/tests/test_cascade.lua`:
```lua
-- cascade tests (filled in Task 3)
```

`nvim-plugin/tests/test_resolve.lua`:
```lua
-- resolve tests (filled in Task 4)
```

- [ ] **Step 6: Verify runner loads without error**

```bash
nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
```

Expected: prints `0 passed, 0 failed`, exits cleanly (exit code 0).

- [ ] **Step 7: Commit**

```bash
git add nvim-plugin/
git commit -m "feat(nvim): scaffold plugin directory structure"
```

---

## Task 2: `parser.lua` — YAML key-value parser and frontmatter strip

**Files:**
- Modify: `nvim-plugin/lua/md-doc/parser.lua`
- Modify: `nvim-plugin/tests/test_parser.lua`

- [ ] **Step 1: Write failing tests**

`nvim-plugin/tests/test_parser.lua`:
```lua
local P = require("md-doc.parser")

describe("parser.parse_yaml", function()
  it("parses simple string key-value pairs", function()
    local vars = P.parse_yaml("title: My Doc\nauthor: Greg")
    eq(vars.title, "My Doc")
    eq(vars.author, "Greg")
  end)

  it("strips surrounding double quotes from values", function()
    local vars = P.parse_yaml('name: "Hello World"')
    eq(vars.name, "Hello World")
  end)

  it("strips surrounding single quotes from values", function()
    local vars = P.parse_yaml("name: 'Hello World'")
    eq(vars.name, "Hello World")
  end)

  it("skips comment lines (# prefix)", function()
    local vars = P.parse_yaml("# this is a comment\ntitle: Test")
    is_nil(vars["# this is a comment"])
    eq(vars.title, "Test")
  end)

  it("skips blank lines", function()
    local vars = P.parse_yaml("\ntitle: Test\n\nauthor: Greg\n")
    eq(vars.title, "Test")
    eq(vars.author, "Greg")
  end)

  it("returns empty table for empty input", function()
    local vars = P.parse_yaml("")
    eq(next(vars), nil)
  end)

  it("handles keys with underscores", function()
    local vars = P.parse_yaml("output_pdf: My Doc.pdf")
    eq(vars.output_pdf, "My Doc.pdf")
  end)

  it("handles keys with hyphens", function()
    local vars = P.parse_yaml("some-key: value")
    eq(vars["some-key"], "value")
  end)

  it("silently skips nested/list values (lines starting with spaces)", function()
    local vars = P.parse_yaml("top_key: value\n  nested: ignored\nother: kept")
    eq(vars.top_key, "value")
    eq(vars.other, "kept")
    is_nil(vars.nested)
  end)
end)

describe("parser.strip_frontmatter", function()
  it("splits frontmatter and body", function()
    local result = P.strip_frontmatter("---\ntitle: Test\n---\n# Body")
    eq(result.vars.title, "Test")
    eq(result.body, "# Body")
  end)

  it("returns empty frontmatter when none present", function()
    local result = P.strip_frontmatter("# Just a doc\nno frontmatter")
    eq(result.frontmatter, "")
    eq(result.body, "# Just a doc\nno frontmatter")
    eq(next(result.vars), nil)
  end)

  it("parses multiple frontmatter vars", function()
    local content = "---\ntitle: Proposal\ndate: 2026-06-11\nstatus: draft\n---\nBody text"
    local result = P.strip_frontmatter(content)
    eq(result.vars.title, "Proposal")
    eq(result.vars.date, "2026-06-11")
    eq(result.vars.status, "draft")
    eq(result.body, "Body text")
  end)

  it("returns empty body when nothing after frontmatter", function()
    local result = P.strip_frontmatter("---\ntitle: Test\n---\n")
    eq(result.vars.title, "Test")
    eq(result.body, "")
  end)

  it("returns full content as body when opening --- is not at line 1", function()
    local result = P.strip_frontmatter("# Header\n---\ntitle: Test\n---\n")
    eq(result.frontmatter, "")
    eq(result.body, "# Header\n---\ntitle: Test\n---\n")
  end)
end)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
```

Expected: failures because `parse_yaml` and `strip_frontmatter` don't exist yet.

- [ ] **Step 3: Implement `parser.lua`**

`nvim-plugin/lua/md-doc/parser.lua`:
```lua
local M = {}

function M.parse_yaml(text)
  local result = {}
  for line in (text .. "\n"):gmatch("([^\n]*)\n") do
    if not line:match("^%s*#") and line:match("%S") and not line:match("^%s+") then
      local key, value = line:match("^([%w_%-]+)%s*:%s*(.+)%s*$")
      if key and value then
        local quoted = value:match('^"(.*)"$') or value:match("^'(.*)'$")
        result[key] = quoted or value
      end
    end
  end
  return result
end

function M.strip_frontmatter(content)
  if not content:match("^%-%-%-\n") then
    return { frontmatter = "", body = content, vars = {} }
  end
  local after_open = content:sub(5)
  local close_pos = after_open:find("\n%-%-%-\n")
  if not close_pos then
    return { frontmatter = "", body = content, vars = {} }
  end
  local fm_content = after_open:sub(1, close_pos - 1)
  local body = after_open:sub(close_pos + 5)
  return {
    frontmatter = "---\n" .. fm_content .. "\n---\n",
    body = body,
    vars = M.parse_yaml(fm_content),
  }
end

return M
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
```

Expected: all parser tests pass, `0 failed`.

- [ ] **Step 5: Commit**

```bash
git add nvim-plugin/lua/md-doc/parser.lua nvim-plugin/tests/test_parser.lua
git commit -m "feat(nvim): implement parser.lua — YAML and frontmatter parsing"
```

---

## Task 3: `cascade.lua` — repo root detection and context merge

**Files:**
- Modify: `nvim-plugin/lua/md-doc/cascade.lua`
- Modify: `nvim-plugin/tests/test_cascade.lua`

- [ ] **Step 1: Write failing tests**

`nvim-plugin/tests/test_cascade.lua`:
```lua
local C = require("md-doc.cascade")

local function tmpdir()
  local path = vim.fn.tempname()
  vim.fn.mkdir(path, "p")
  return path
end

local function write(path, content)
  local f = assert(io.open(path, "w"))
  f:write(content)
  f:close()
end

local function mkdir(path)
  vim.fn.mkdir(path, "p")
end

describe("cascade.find_repo_root", function()
  it("finds repo root via pyproject.toml", function()
    local root = tmpdir()
    write(root .. "/pyproject.toml", "[project]")
    local subdir = root .. "/sub/dir"
    mkdir(subdir)
    eq(C.find_repo_root(subdir), root)
  end)

  it("finds repo root via .git directory", function()
    local root = tmpdir()
    mkdir(root .. "/.git")
    local subdir = root .. "/a/b"
    mkdir(subdir)
    eq(C.find_repo_root(subdir), root)
  end)

  it("returns nil when no repo root marker found", function()
    local isolated = tmpdir()
    local sub = isolated .. "/no/markers"
    mkdir(sub)
    is_nil(C.find_repo_root(sub))
  end)

  it("returns the dir itself when marker is in start_dir", function()
    local root = tmpdir()
    write(root .. "/pyproject.toml", "[project]")
    eq(C.find_repo_root(root), root)
  end)
end)

describe("cascade.load_context", function()
  it("merges _meta.yml files shallow-to-deep (deeper wins)", function()
    local root = tmpdir()
    write(root .. "/pyproject.toml", "[project]")
    write(root .. "/_meta.yml", "company: Blueshift\nstatus: draft")
    local client_dir = root .. "/clients/acme"
    mkdir(client_dir)
    write(root .. "/clients/_meta.yml", "region: APAC")
    write(client_dir .. "/_meta.yml", "company: ACME\nclient: ACME Corp")
    local doc = client_dir .. "/proposal.md"
    write(doc, "---\ntitle: Proposal\n---\n# Body")

    local ctx = C.load_context(doc, false)
    eq(ctx.company, "ACME")       -- client dir overrides root
    eq(ctx.status, "draft")       -- from root _meta.yml
    eq(ctx.region, "APAC")        -- from intermediate _meta.yml
    eq(ctx.client, "ACME Corp")
    is_nil(ctx.title)             -- frontmatter excluded
  end)

  it("includes frontmatter vars when flag is true", function()
    local root = tmpdir()
    write(root .. "/pyproject.toml", "[project]")
    local doc = root .. "/doc.md"
    write(doc, "---\ntitle: My Title\ndate: 2026-06-11\n---\n# Body")
    local ctx = C.load_context(doc, true)
    eq(ctx.title, "My Title")
    eq(ctx.date, "2026-06-11")
  end)

  it("frontmatter overrides _meta.yml when flag is true", function()
    local root = tmpdir()
    write(root .. "/pyproject.toml", "[project]")
    write(root .. "/_meta.yml", "status: draft")
    local doc = root .. "/doc.md"
    write(doc, "---\nstatus: final\n---\n# Body")
    local ctx = C.load_context(doc, true)
    eq(ctx.status, "final")
  end)

  it("returns empty table when no repo root found", function()
    local isolated = tmpdir()
    local doc = isolated .. "/doc.md"
    write(doc, "# Body")
    local ctx = C.load_context(doc, false)
    eq(next(ctx), nil)
  end)

  it("works when doc is at repo root level", function()
    local root = tmpdir()
    write(root .. "/pyproject.toml", "[project]")
    write(root .. "/_meta.yml", "author: Greg")
    local doc = root .. "/doc.md"
    write(doc, "# Body")
    local ctx = C.load_context(doc, false)
    eq(ctx.author, "Greg")
  end)
end)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
```

Expected: cascade tests fail, parser tests still pass.

- [ ] **Step 3: Implement `cascade.lua`**

`nvim-plugin/lua/md-doc/cascade.lua`:
```lua
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
    if exists(dir .. "/pyproject.toml") or exists(dir .. "/.git") then
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
```

Expected: all parser + cascade tests pass.

- [ ] **Step 5: Commit**

```bash
git add nvim-plugin/lua/md-doc/cascade.lua nvim-plugin/tests/test_cascade.lua
git commit -m "feat(nvim): implement cascade.lua — repo root detection and context merge"
```

---

## Task 4: `resolve.lua` — search dirs, template resolution, variable lookup

**Files:**
- Modify: `nvim-plugin/lua/md-doc/resolve.lua`
- Modify: `nvim-plugin/tests/test_resolve.lua`

- [ ] **Step 1: Write failing tests**

`nvim-plugin/tests/test_resolve.lua`:
```lua
local R = require("md-doc.resolve")

local function tmpdir()
  local path = vim.fn.tempname()
  vim.fn.mkdir(path, "p")
  return path
end

local function write(path, content)
  local f = assert(io.open(path, "w"))
  f:write(content)
  f:close()
end

local function mkdir(path)
  vim.fn.mkdir(path, "p")
end

describe("resolve.build_search_dirs", function()
  it("starts with the doc directory", function()
    local root = tmpdir()
    local doc = root .. "/clients/acme/proposal.md"
    mkdir(root .. "/clients/acme")
    local dirs = R.build_search_dirs(doc, root)
    eq(dirs[1], root .. "/clients/acme")
  end)

  it("second entry is doc/templates/", function()
    local root = tmpdir()
    local doc = root .. "/clients/acme/proposal.md"
    mkdir(root .. "/clients/acme")
    local dirs = R.build_search_dirs(doc, root)
    eq(dirs[2], root .. "/clients/acme/templates")
  end)

  it("ends with repo root", function()
    local root = tmpdir()
    local doc = root .. "/clients/acme/proposal.md"
    mkdir(root .. "/clients/acme")
    local dirs = R.build_search_dirs(doc, root)
    eq(dirs[#dirs], root)
  end)

  it("second-to-last is repo root templates/", function()
    local root = tmpdir()
    local doc = root .. "/clients/acme/proposal.md"
    mkdir(root .. "/clients/acme")
    local dirs = R.build_search_dirs(doc, root)
    eq(dirs[#dirs - 1], root .. "/templates")
  end)

  it("puts deeper ancestor templates/ before shallower ones", function()
    local root = tmpdir()
    local doc = root .. "/a/b/c/doc.md"
    mkdir(root .. "/a/b/c")
    local dirs = R.build_search_dirs(doc, root)
    -- a/b/templates must come before a/templates
    local pos_ab, pos_a
    for i, d in ipairs(dirs) do
      if d == root .. "/a/b/templates" then pos_ab = i end
      if d == root .. "/a/templates" then pos_a = i end
    end
    not_nil(pos_ab)
    not_nil(pos_a)
    if pos_ab >= pos_a then
      error("expected a/b/templates before a/templates, got positions " .. pos_ab .. " and " .. pos_a)
    end
  end)

  it("contains no duplicates when doc is at repo root", function()
    local root = tmpdir()
    local doc = root .. "/doc.md"
    local dirs = R.build_search_dirs(doc, root)
    local seen = {}
    for _, d in ipairs(dirs) do
      if seen[d] then error("duplicate: " .. d) end
      seen[d] = true
    end
  end)
end)

describe("resolve.resolve_include", function()
  it("finds template in repo root templates/ dir", function()
    local root = tmpdir()
    mkdir(root .. "/templates")
    write(root .. "/templates/header.md", "# Header")
    mkdir(root .. "/clients/acme")
    local doc = root .. "/clients/acme/proposal.md"
    write(doc, "body")
    local result = R.resolve_include("header.md", doc, root)
    not_nil(result)
    eq(result.content, "# Header")
  end)

  it("prefers closer ancestor templates/ over repo-root templates/", function()
    local root = tmpdir()
    mkdir(root .. "/templates")
    write(root .. "/templates/header.md", "# Root Header")
    mkdir(root .. "/clients/templates")
    write(root .. "/clients/templates/header.md", "# Client Header")
    mkdir(root .. "/clients/acme")
    local doc = root .. "/clients/acme/proposal.md"
    write(doc, "body")
    local result = R.resolve_include("header.md", doc, root)
    eq(result.content, "# Client Header")
  end)

  it("prefers doc-local template over ancestor templates/", function()
    local root = tmpdir()
    mkdir(root .. "/templates")
    write(root .. "/templates/header.md", "# Root Header")
    local docdir = root .. "/clients/acme"
    mkdir(docdir)
    write(docdir .. "/header.md", "# Local Header")
    local doc = docdir .. "/proposal.md"
    write(doc, "body")
    local result = R.resolve_include("header.md", doc, root)
    eq(result.content, "# Local Header")
  end)

  it("returns nil when template not found anywhere", function()
    local root = tmpdir()
    local doc = root .. "/doc.md"
    write(doc, "body")
    local result = R.resolve_include("nonexistent.md", doc, root)
    is_nil(result)
  end)

  it("returns path alongside content", function()
    local root = tmpdir()
    mkdir(root .. "/templates")
    write(root .. "/templates/header.md", "# Header")
    local doc = root .. "/doc.md"
    write(doc, "body")
    local result = R.resolve_include("header.md", doc, root)
    not_nil(result.path)
    eq(result.path, root .. "/templates/header.md")
  end)
end)

describe("resolve.resolve_variable", function()
  it("returns value for known variable", function()
    local ctx = { client = "Acme Corp", status = "draft" }
    eq(R.resolve_variable("client", ctx), "Acme Corp")
  end)

  it("strips Jinja filter before lookup (| upper)", function()
    local ctx = { status = "draft" }
    eq(R.resolve_variable("status | upper", ctx), "draft")
  end)

  it("strips leading/trailing whitespace from var expression", function()
    local ctx = { client = "Acme" }
    eq(R.resolve_variable("  client  ", ctx), "Acme")
  end)

  it("returns nil for unknown variable", function()
    local ctx = { client = "Acme" }
    is_nil(R.resolve_variable("unknown_var", ctx))
  end)

  it("returns nil for empty context", function()
    is_nil(R.resolve_variable("any_var", {}))
  end)
end)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
```

Expected: resolve tests fail, previous tests still pass.

- [ ] **Step 3: Implement `resolve.lua`**

`nvim-plugin/lua/md-doc/resolve.lua`:
```lua
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

  local rel = doc_dir:sub(#repo_root + 2)
  local parts = {}
  for part in rel:gmatch("[^/]+") do table.insert(parts, part) end
  -- Remove last part (that is doc_dir itself)
  if #parts > 0 then table.remove(parts, #parts) end

  for i = #parts, 1, -1 do
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
```

- [ ] **Step 4: Run all tests to confirm they pass**

```bash
nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
```

Expected: all tests pass, `0 failed`.

- [ ] **Step 5: Commit**

```bash
git add nvim-plugin/lua/md-doc/resolve.lua nvim-plugin/tests/test_resolve.lua
git commit -m "feat(nvim): implement resolve.lua — include path resolution and variable lookup"
```

---

## Task 5: `ui/float.lua` — floating window

No automated tests — requires running Neovim UI. Manual verification at end.

**Files:**
- Modify: `nvim-plugin/lua/md-doc/ui/float.lua`

- [ ] **Step 1: Implement `float.lua`**

`nvim-plugin/lua/md-doc/ui/float.lua`:
```lua
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
```

- [ ] **Step 2: Commit**

```bash
git add nvim-plugin/lua/md-doc/ui/float.lua
git commit -m "feat(nvim): implement ui/float.lua — floating hover window"
```

---

## Task 6: `ui/virtual.lua` — virtual text via extmarks

**Files:**
- Modify: `nvim-plugin/lua/md-doc/ui/virtual.lua`

- [ ] **Step 1: Implement `virtual.lua`**

`nvim-plugin/lua/md-doc/ui/virtual.lua`:
```lua
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
```

- [ ] **Step 2: Commit**

```bash
git add nvim-plugin/lua/md-doc/ui/virtual.lua
git commit -m "feat(nvim): implement ui/virtual.lua — virtual text extmarks"
```

---

## Task 7: `ui/split.lua` — vertical split pane

**Files:**
- Modify: `nvim-plugin/lua/md-doc/ui/split.lua`

- [ ] **Step 1: Implement `split.lua`**

`nvim-plugin/lua/md-doc/ui/split.lua`:
```lua
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
```

- [ ] **Step 2: Commit**

```bash
git add nvim-plugin/lua/md-doc/ui/split.lua
git commit -m "feat(nvim): implement ui/split.lua — vertical split pane"
```

---

## Task 8: `init.lua` — setup, autocommands, cursor dispatch, keymaps

**Files:**
- Modify: `nvim-plugin/lua/md-doc/init.lua`

- [ ] **Step 1: Implement `init.lua`**

`nvim-plugin/lua/md-doc/init.lua`:
```lua
local M = {}

local cascade = require("md-doc.cascade")
local resolve  = require("md-doc.resolve")
local float    = require("md-doc.ui.float")
local virtual  = require("md-doc.ui.virtual")
local split    = require("md-doc.ui.split")

local default_config = {
  auto_show = true,
  auto_show_delay = 500,
  modes = { float = true, virtual = false, split = false },
  resolve_frontmatter = false,
  keymaps = {
    toggle_float       = "<leader>mf",
    toggle_virtual     = "<leader>mv",
    toggle_split       = "<leader>ms",
    toggle_frontmatter = "<leader>mr",
    show_now           = "K",
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

local function parse_cursor_line(line)
  local tmpl = line:match("{%%%-?%s*include%s+\"([^\"]+)\"%s*%-?%%}")
  if tmpl then return "include", tmpl end
  local var = line:match("{{%s*([^}]+)}}")
  if var then return "variable", var end
  return nil, nil
end

function M.show_preview(bufnr, force)
  local state = get_state(bufnr)
  local lnum = vim.api.nvim_win_get_cursor(0)[1]
  local line = vim.api.nvim_buf_get_lines(bufnr, lnum - 1, lnum, false)[1] or ""

  local action, arg = parse_cursor_line(line)
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
    local context = cascade.load_context(doc_path, state.resolve_frontmatter)
    local value = resolve.resolve_variable(arg, context)
    local var_name = arg:match("^%s*([%w_]+)") or arg
    title = "⚙ " .. var_name
    display_lines = { value and ("⟶  " .. value) or "(undefined)" }
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

local function set_keymaps(bufnr)
  local state = get_state(bufnr)
  local km = config.keymaps
  local opts = { buffer = bufnr, noremap = true, silent = true }

  vim.keymap.set("n", km.toggle_float, function()
    state.modes.float = not state.modes.float
    vim.notify("md-doc: float " .. (state.modes.float and "on" or "off"))
  end, opts)

  vim.keymap.set("n", km.toggle_virtual, function()
    state.modes.virtual = not state.modes.virtual
    if not state.modes.virtual then virtual.clear_all(bufnr) end
    vim.notify("md-doc: virtual text " .. (state.modes.virtual and "on" or "off"))
  end, opts)

  vim.keymap.set("n", km.toggle_split, function()
    state.modes.split = not state.modes.split
    if not state.modes.split then split.close(bufnr) end
    vim.notify("md-doc: split " .. (state.modes.split and "on" or "off"))
  end, opts)

  vim.keymap.set("n", km.toggle_frontmatter, function()
    state.resolve_frontmatter = not state.resolve_frontmatter
    vim.notify("md-doc: frontmatter " .. (state.resolve_frontmatter and "on" or "off"))
  end, opts)

  vim.keymap.set("n", km.show_now, function()
    M.show_preview(bufnr, true)
  end, opts)
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

  if config.auto_show then
    if config.auto_show_delay < vim.o.updatetime then
      vim.o.updatetime = config.auto_show_delay
    end
    vim.api.nvim_create_autocmd("CursorHold", {
      buffer = bufnr,
      callback = function() M.show_preview(bufnr, false) end,
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

  vim.api.nvim_create_autocmd({ "BufEnter", "BufReadPost" }, {
    pattern = "*.md",
    callback = function(ev)
      local path = vim.api.nvim_buf_get_name(ev.buf)
      if path == "" then return end
      local dir = vim.fn.fnamemodify(path, ":h")
      if cascade.find_repo_root(dir) then
        activate(ev.buf)
      end
    end,
  })
end

return M
```

- [ ] **Step 2: Run the automated tests to make sure nothing regressed**

```bash
nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
```

Expected: all tests still pass.

- [ ] **Step 3: Manual smoke test**

Add the plugin to your Neovim config temporarily by adding the plugin dir to rtp:

```lua
-- in your init.lua or via :lua in nvim
vim.opt.rtp:prepend("/path/to/md-doc-pipeline/nvim-plugin")
require("md-doc").setup({})
```

Open `examples/blueshift/clients/stormfront-inc/onboarding-proposal.md` and:
1. Move cursor to line 11 (`{% include "company-header.md" %}`). After `updatetime` ms, a float should appear showing the header content.
2. Press `K` — float should appear immediately.
3. Move cursor to line 14 (`{{ client_contact }}`). After hold, float should show the resolved value `Jamie Rowe, Head of Engineering`.
4. Press `<leader>mf` to toggle float off, then `K` — no float should appear.
5. Press `<leader>mv` to toggle virtual text on. Move cursor to the include line — virtual text should expand below.
6. Press `<leader>ms` to open split. A right pane should appear and update as you move.

- [ ] **Step 4: Commit**

```bash
git add nvim-plugin/lua/md-doc/init.lua
git commit -m "feat(nvim): implement init.lua — setup, cursor dispatch, keymaps"
```

---

## Task 9: README and final commit

**Files:**
- Create: `nvim-plugin/README.md`

- [ ] **Step 1: Write README**

`nvim-plugin/README.md`:
```markdown
# md-doc.nvim

Neovim plugin for [md-doc-pipeline](https://github.com/yourname/md-doc-pipeline).
Previews `{% include %}` template fragments and resolves `{{ variable }}` values
inline while you edit `.md` documents.

Activates automatically on `.md` files inside an md-doc project (any directory
containing a `pyproject.toml` or `.git` marker).

## Installation

### lazy.nvim

```lua
{
  dir = "/path/to/md-doc-pipeline/nvim-plugin",
  ft = "markdown",
  config = function()
    require("md-doc").setup({})
  end,
}
```

### packer.nvim

```lua
use {
  "/path/to/md-doc-pipeline/nvim-plugin",
  config = function()
    require("md-doc").setup({})
  end,
}
```

## Configuration

```lua
require("md-doc").setup({
  auto_show = true,           -- show preview on CursorHold
  auto_show_delay = 500,      -- milliseconds before CursorHold fires
  modes = {
    float   = true,           -- LSP-style hover popup (default on)
    virtual = false,          -- inline virtual text below the line
    split   = false,          -- persistent right-side split pane
  },
  resolve_frontmatter = false, -- include document frontmatter in {{ }} resolution
  keymaps = {
    toggle_float        = "<leader>mf",
    toggle_virtual      = "<leader>mv",
    toggle_split        = "<leader>ms",
    toggle_frontmatter  = "<leader>mr",
    show_now            = "K",   -- force-show float immediately
  },
})
```

All keymaps are buffer-local — they only apply inside md-doc `.md` files.
`K` does not override LSP hover in other buffers.

## What it previews

| Cursor on | Shows |
|---|---|
| `{% include "header.md" %}` | Full contents of the resolved template file |
| `{{ client }}` | Resolved value from `_meta.yml` cascade |
| `{{ status \| upper }}` | Resolved value (filter stripped for lookup) |

## Display modes

All three modes can be active simultaneously.

| Mode | Description | Toggle |
|---|---|---|
| Float | Popup window, closes on cursor move | `<leader>mf` |
| Virtual text | Dimmed lines inserted below the include/variable line | `<leader>mv` |
| Split | Persistent right-side pane, updates on cursor move | `<leader>ms` |

## Frontmatter toggle

By default, `{{ variable }}` resolution only uses `_meta.yml` cascade values.
Press `<leader>mr` to also include the current document's frontmatter variables.
```

- [ ] **Step 2: Run tests one final time**

```bash
nvim --headless -u NONE -c "lua dofile('nvim-plugin/tests/run.lua')" +qa!
```

Expected: all tests pass, `0 failed`.

- [ ] **Step 3: Final commit**

```bash
git add nvim-plugin/README.md nvim-plugin/tests/run.lua nvim-plugin/tests/test_parser.lua nvim-plugin/tests/test_cascade.lua nvim-plugin/tests/test_resolve.lua
git commit -m "feat(nvim): add README and complete test suite"
```
