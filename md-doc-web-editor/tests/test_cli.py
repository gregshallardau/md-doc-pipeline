"""CLI startup and virtual-environment isolation regressions."""

import subprocess
import sys

from md_doc_web_editor.cli import main


def test_help_works_in_installed_environment():
    result = subprocess.run(
        [sys.executable, "-m", "md_doc_web_editor.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "serve" in result.stdout


def test_invalid_workspace_does_not_start_server(tmp_path, capsys):
    assert main(["serve", str(tmp_path / "missing"), "--no-browser"]) == 2
    assert "not a directory" in capsys.readouterr().err


def test_serve_passes_app_to_uvicorn(tmp_path, monkeypatch):
    from md_doc_web_editor import cli

    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    monkeypatch.setattr(cli.webbrowser, "open", lambda _: (_ for _ in ()).throw(AssertionError()))
    assert main(["serve", str(tmp_path), "--no-browser", "--port", "9000"]) == 0
    assert calls[0][0].title == "md-doc editor"
    assert calls[0][1]["port"] == 9000


def test_allowed_hosts_loopback_and_bound_host():
    from md_doc_web_editor.cli import _allowed_hosts

    assert _allowed_hosts("127.0.0.1") == ["127.0.0.1", "localhost"]
    assert _allowed_hosts("192.168.1.5") == ["127.0.0.1", "192.168.1.5", "localhost"]
    assert _allowed_hosts("0.0.0.0") is None


def test_serve_on_all_interfaces_warns(tmp_path, monkeypatch, capsys):
    from md_doc_web_editor import cli

    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: None)
    assert main(["serve", str(tmp_path), "--no-browser", "--host", "0.0.0.0"]) == 0
    assert "no sign-in" in capsys.readouterr().err
