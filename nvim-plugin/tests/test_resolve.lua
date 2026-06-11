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
