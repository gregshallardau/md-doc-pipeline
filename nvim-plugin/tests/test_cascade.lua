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
