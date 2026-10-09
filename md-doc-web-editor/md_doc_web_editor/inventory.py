"""Workspace tree traversal, including local links and explicit scan failures."""

from pathlib import Path

SKIP_FOLDERS = {"node_modules", "__pycache__", "dist", "build"}


def scan_tree(directory, root, classify, prefix="", ancestors=frozenset(), warnings=None):
    warnings = warnings if warnings is not None else []
    directory, root = Path(directory), Path(root).resolve()
    resolved = directory.resolve()
    if not resolved.is_relative_to(root):
        warnings.append(
            {"path": str(directory), "message": "Folder link points outside this workspace"}
        )
        return []
    if resolved in ancestors:
        warnings.append({"path": str(directory), "message": "Folder link creates a cycle"})
        return []
    try:
        entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
    except OSError as exc:
        warnings.append({"path": str(directory), "message": str(exc)})
        return []
    items = []
    for entry in entries:
        if entry.name.startswith(".") or entry.name in SKIP_FOLDERS:
            continue
        relative = prefix + entry.relative_to(root).as_posix()
        try:
            if entry.is_dir():
                previous = len(warnings)
                children = scan_tree(
                    entry, root, classify, prefix, ancestors | {resolved}, warnings
                )
                count = sum(
                    node.get("documentCount", int(node["type"] == "md")) for node in children
                )
                node = {
                    "name": entry.name,
                    "path": relative,
                    "type": "dir",
                    "children": children,
                    "documentCount": count,
                    "linked": entry.is_symlink(),
                }
                if len(warnings) > previous:
                    node["scanError"] = warnings[previous]["message"]
                items.append(node)
            else:
                kind = classify(entry.name)
                if kind is None:
                    continue
                if not entry.resolve().is_relative_to(root):
                    warnings.append(
                        {"path": str(entry), "message": "File link points outside this workspace"}
                    )
                    continue
                if not entry.exists():
                    warnings.append({"path": str(entry), "message": "Broken file link"})
                    continue
                items.append(
                    {
                        "name": entry.name,
                        "path": relative,
                        "type": kind,
                        "linked": entry.is_symlink(),
                    }
                )
        except OSError as exc:
            warnings.append({"path": str(entry), "message": str(exc)})
    return items
