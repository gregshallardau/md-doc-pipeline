"""Tests for Phase 1 sync reliability: retry/backoff and partial-failure isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from md_doc import sync as S


def test_with_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = S._with_retry(flaky, attempts=3, base_delay=0, sleep=lambda _d: None)
    assert result == "ok"
    assert calls["n"] == 3


def test_with_retry_reraises_after_exhaustion():
    def always():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        S._with_retry(always, attempts=3, base_delay=0, sleep=lambda _d: None)


def test_local_uploader_is_atomic(tmp_path):
    src_root = tmp_path / "src"
    src_root.mkdir()
    dest = tmp_path / "dest"
    f = src_root / "a.pdf"
    f.write_bytes(b"hello")

    upload = S._load_uploader("local")(src_root, {"path": str(dest)})
    upload(f)

    assert (dest / "a.pdf").read_bytes() == b"hello"
    # No partial temp file is left behind.
    assert not list(dest.glob("*.part"))


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "_meta.yml").write_text(
        "sync_target: local\nsync_config:\n  path: %s\n" % (tmp_path / "out"),
        encoding="utf-8",
    )
    (tmp_path / "a.pdf").write_bytes(b"a")
    (tmp_path / "b.pdf").write_bytes(b"b")
    return tmp_path


def test_run_reports_and_isolates_per_file_failure(tmp_path, monkeypatch):
    root = _make_repo(tmp_path)

    # Make the second file always fail, even after retries.
    real_factory = S._load_uploader("local")

    def failing_factory(r, cfg):
        upload = real_factory(r, cfg)

        def _upload(src: Path) -> str:
            if src.name == "b.pdf":
                raise RuntimeError("network down")
            return upload(src)

        return _upload

    monkeypatch.setattr(S, "_load_uploader", lambda name: failing_factory)
    monkeypatch.setattr(S.time, "sleep", lambda _d: None)  # no real backoff sleeps

    with pytest.raises(S.SyncError):
        S.run(root, backend="local", retries=2)

    # The good file still uploaded despite the other failing.
    assert (root / "out" / "a.pdf").exists()
    assert not (root / "out" / "b.pdf").exists()


def test_run_dry_run_uploads_nothing(tmp_path):
    root = _make_repo(tmp_path)
    summary = S.run(root, backend="local", dry_run=True)
    assert summary == {"uploaded": [], "failed": []}
    assert not (root / "out").exists()
