"""Keep Markdown code examples out of document-directive preprocessing."""

from __future__ import annotations

import re
from collections.abc import Callable


def transform_outside_code(source: str, transform: Callable[[str], str]) -> str:
    """Transform prose while preserving fenced blocks and inline code verbatim."""
    examples: list[str] = []
    prefix = "MDDOCLITERAL"
    while prefix in source:
        prefix += "X"

    def protect(text: str) -> str:
        examples.append(text)
        # Preserve line counts for lint diagnostics.
        return f"{prefix}{len(examples) - 1}END" + "\n" * text.count("\n")

    lines = source.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    while index < len(lines):
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})[^\n]*", lines[index])
        if not opening:
            output.append(lines[index])
            index += 1
            continue
        fence = opening.group(1)
        end = index + 1
        closing = re.compile(
            r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*(?:\n)?$"
        )
        while end < len(lines):
            if closing.match(lines[end]):
                end += 1
                break
            end += 1
        output.append(protect("".join(lines[index:end])))
        index = end

    masked = "".join(output)
    masked = re.sub(
        r"(?<!`)(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)",
        lambda match: protect(match.group(0)),
        masked,
    )
    result = transform(masked)
    for number, example in enumerate(examples):
        result = result.replace(f"{prefix}{number}END" + "\n" * example.count("\n"), example)
    return result
