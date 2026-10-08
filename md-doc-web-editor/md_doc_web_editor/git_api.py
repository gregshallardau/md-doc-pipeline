"""Workspace-scoped Git inspection and deliberate source-control actions."""

from __future__ import annotations

import subprocess
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from .snapshots import safe_path


class GitAction(BaseModel):
    action: str
    path: str = ""
    message: str = ""
    branch: str = ""


def install_git(app, workspace, write_lock):
    def run(*args, check=True, env=None, directory=None):
        try:
            result = subprocess.run(
                ["git", "-C", str(directory or workspace), *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(503, f"Git is unavailable: {exc}") from exc
        if check and result.returncode:
            raise HTTPException(422, result.stderr.strip() or result.stdout.strip())
        return result

    def context():
        result = run("rev-parse", "--show-toplevel", check=False)
        if result.returncode:
            return None
        root = Path(result.stdout.strip()).resolve()
        return root, workspace.relative_to(root).as_posix()

    def status():
        project = context()
        if not project:
            return {"available": False, "files": [], "branch": ""}
        root, scope = project
        raw = run(
            "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", str(workspace)
        ).stdout
        entries = iter(raw.split("\0"))
        files = []
        for entry in entries:
            if not entry:
                continue
            code, name = entry[:2], entry[3:]
            original = next(entries, "") if "R" in code or "C" in code else None
            full = root / name
            if not full.is_relative_to(workspace):
                continue
            files.append(
                {
                    "path": full.relative_to(workspace).as_posix(),
                    "code": code,
                    "staged": code[0] not in {" ", "?"},
                    "original": original,
                }
            )
        branch = run("branch", "--show-current").stdout.strip() or "Detached HEAD"
        upstream = run("rev-parse", "--abbrev-ref", "@{upstream}", check=False)
        history = run("log", "-8", "--format=%h%x09%s%x09%ar", "--", str(workspace), check=False)
        return {
            "available": True,
            "branch": branch,
            "root": str(root),
            "files": files,
            "upstream": upstream.stdout.strip() if upstream.returncode == 0 else None,
            "history": [line.split("\t", 2) for line in history.stdout.splitlines()],
        }

    @app.get("/api/git/status")
    def git_status():
        return status()

    @app.get("/api/git/diff")
    def git_diff(path: str, staged: bool = False):
        try:
            full = safe_path(workspace, path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        flags = ["--cached"] if staged else []
        diff = run("diff", "--no-ext-diff", "--no-textconv", *flags, "--", str(full)).stdout
        if not diff and full.is_file() and full.stat().st_size < 2 * 1024 * 1024:
            tracked = run("ls-files", "--", str(full)).stdout
            if not tracked:
                diff = "New file\n" + full.read_text(errors="replace")
        return {"diff": diff[:200000], "path": path, "staged": staged}

    @app.post("/api/git/action")
    def git_action(req: GitAction):
        project = context()
        if not project:
            raise HTTPException(400, "This workspace is not in a Git repository")
        with write_lock:
            if req.action in {"stage", "unstage"}:
                try:
                    full = safe_path(workspace, req.path)
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from exc
                if req.action == "stage":
                    run("add", "--", str(full))
                else:
                    head = run("rev-parse", "--verify", "HEAD", check=False)
                    if head.returncode:
                        run("rm", "--cached", "--", str(full))
                    else:
                        run("restore", "--staged", "--", str(full))
            elif req.action == "commit":
                if not req.message.strip() or len(req.message) > 10000:
                    raise HTTPException(400, "Enter a commit message")
                staged = [item["path"] for item in status()["files"] if item["staged"]]
                if not staged:
                    raise HTTPException(400, "Stage the files you want to commit first")
                # An alternate index preserves staged work outside this workspace
                # and commits staged blobs rather than any later working edits.
                root, _ = project
                with tempfile.TemporaryDirectory(prefix="md-doc-git-") as temporary:
                    env = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index")}
                    head = run("rev-parse", "--verify", "HEAD", check=False)
                    run("read-tree", "HEAD" if head.returncode == 0 else "--empty", env=env)
                    index_entries = run(
                        "ls-files", "--full-name", "--stage", "-z", "--", str(workspace)
                    ).stdout
                    entries = {}
                    for entry in index_entries.split("\0"):
                        if not entry:
                            continue
                        metadata, filename = entry.split("\t", 1)
                        mode, digest, stage = metadata.split()
                        if stage != "0":
                            raise HTTPException(409, "Resolve merge conflicts before committing")
                        entries[filename] = (mode, digest)
                    for relative in staged:
                        filename = (workspace / relative).relative_to(root).as_posix()
                        if filename in entries:
                            mode, digest = entries[filename]
                            run(
                                "update-index",
                                "--add",
                                "--cacheinfo",
                                mode,
                                digest,
                                filename,
                                env=env,
                                directory=root,
                            )
                        else:
                            run(
                                "update-index",
                                "--force-remove",
                                "--",
                                filename,
                                env=env,
                                directory=root,
                            )
                    run("commit", "-m", req.message, env=env)
                run("reset", "HEAD", "--", *[str(workspace / p) for p in staged])
            elif req.action == "branch":
                if not req.branch or req.branch.startswith("-"):
                    raise HTTPException(400, "Enter a valid branch name")
                run("check-ref-format", "--branch", req.branch)
                run("switch", "-c", req.branch)
            elif req.action == "pull":
                run("pull", "--ff-only")
            else:
                raise HTTPException(400, "Unknown Git action")
        return status()
