local M = {}

function M.parse_yaml(text)
  local result = {}
  for line in (text .. "\n"):gmatch("([^\n]*)\n") do
    if not line:match("^%s*#") and line:match("%S") and not line:match("^%s+") then
      local key, value = line:match("^([%w_%-]+)%s*:%s*(.-)%s*$")
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
