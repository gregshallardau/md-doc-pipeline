"""Tests for workspace + subdir resolution and cwd-relative path output."""

import os
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from md_doc.cli import _resolve_workspace_root, _short_path, main


@pytest.fixture()
def tmp_repo(tmp_path):
    """Create a tmp repo with a workspaces config and a sample workspace dir."""
    (tmp_path / ".git").mkdir()

    # Create a workspace dir with nested subdirs
    workspace = tmp_path / "ws-acme"
    workspace.mkdir()
    (workspace / "_meta.yml").write_text("title: Acme\n", encoding="utf-8")
    (workspace / "doc-root.md").write_text(
        "---\ntitle: Root doc\n---\n\n# Root\n", encoding="utf-8"
    )

    sub = workspace / "products" / "nova"
    sub.mkdir(parents=True)
    (sub / "doc-sub.md").write_text("---\ntitle: Sub doc\n---\n\n# Sub\n", encoding="utf-8")

    # Register the workspace
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    (ws_dir / "remote-workspaces.yml").write_text(
        yaml.dump({"acme": {"path": str(workspace)}}), encoding="utf-8"
    )

    return tmp_path


# ── _resolve_workspace_root ──────────────────────────────────────────────────


class TestResolveWorkspaceRoot:
    def test_default_root_returns_workspace(self, tmp_repo, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        result = _resolve_workspace_root("acme", Path("."), tmp_repo)
        assert result == (tmp_repo / "ws-acme").resolve()

    def test_subdir_returns_workspace_subpath(self, tmp_repo, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        result = _resolve_workspace_root("acme", Path("products/nova"), tmp_repo)
        assert result == (tmp_repo / "ws-acme" / "products" / "nova").resolve()

    def test_missing_subdir_errors(self, tmp_repo, monkeypatch):
        import click

        monkeypatch.chdir(tmp_repo)
        with pytest.raises(click.UsageError, match="not found in workspace"):
            _resolve_workspace_root("acme", Path("does/not/exist"), tmp_repo)

    def test_traversal_blocked(self, tmp_repo, monkeypatch):
        import click

        monkeypatch.chdir(tmp_repo)
        with pytest.raises(click.UsageError, match="escapes workspace"):
            _resolve_workspace_root("acme", Path("../.."), tmp_repo)


# ── md-doc lint -w workspace subdir ─────────────────────────────────────────


class TestLintWithWorkspaceSubdir:
    def test_lint_workspace_root(self, tmp_repo, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        runner = CliRunner()
        result = runner.invoke(main, ["lint", "-w", "acme"])
        assert result.exit_code == 0, f"failed: {result.output}"
        assert "Workspace:" in result.output
        assert "acme" in result.output

    def test_lint_workspace_subdir(self, tmp_repo, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        runner = CliRunner()
        result = runner.invoke(main, ["lint", "-w", "acme", "products/nova"])
        assert result.exit_code == 0, f"failed: {result.output}"
        # Confirmation line includes the subdir
        assert "acme/products/nova" in result.output

    def test_lint_workspace_missing_subdir(self, tmp_repo, monkeypatch):
        monkeypatch.chdir(tmp_repo)
        runner = CliRunner()
        result = runner.invoke(main, ["lint", "-w", "acme", "fake/path"])
        assert result.exit_code != 0
        assert "not found in workspace" in result.output


# ── _short_path ─────────────────────────────────────────────────────────────


class TestShortPath:
    def test_path_under_cwd_returns_relative(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        result = _short_path(sub)
        # Use Path to normalise separators across platforms
        assert Path(result) == Path("a/b") or result == os.path.join("a", "b")

    def test_path_outside_cwd_uses_dotdot(self, tmp_path, monkeypatch):
        cwd = tmp_path / "deep" / "subdir"
        cwd.mkdir(parents=True)
        monkeypatch.chdir(cwd)
        target = tmp_path / "other"
        target.mkdir()
        result = _short_path(target)
        # Should produce a ../../something path
        assert ".." in result, f"expected '..' in {result}"

    def test_verbose_returns_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sub = tmp_path / "a"
        sub.mkdir()
        result = _short_path(sub, verbose=True)
        assert os.path.isabs(result)
