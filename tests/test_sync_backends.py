"""Tests for s3/azure sync backend logic with the cloud SDKs mocked out.

Neither boto3 nor azure-storage-file-share is installed in the dev env, so we
inject fake module chains into sys.modules and assert the backends compute the
right keys/paths and validate config before any network call.
"""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture()
def tree(tmp_path):
    root = tmp_path / "out"
    (root / "acme").mkdir(parents=True)
    f = root / "acme" / "proposal.pdf"
    f.write_bytes(b"%PDF")
    return root, f


# ── S3 ──────────────────────────────────────────────────────────────────────


def _install_fake_boto3(monkeypatch):
    calls: list[tuple] = []

    class _Client:
        def upload_file(self, src, bucket, key, ExtraArgs=None):
            calls.append((src, bucket, key, ExtraArgs))

    fake = types.SimpleNamespace(client=lambda *a, **k: _Client())
    monkeypatch.setitem(sys.modules, "boto3", fake)
    return calls


def test_s3_builds_key_and_content_type(tree, monkeypatch):
    root, f = tree
    calls = _install_fake_boto3(monkeypatch)
    from md_doc.sync import s3

    upload = s3.make_uploader(root, {"bucket": "my-bucket", "prefix": "docs"})
    desc = upload(f)

    src, bucket, key, extra = calls[0]
    assert bucket == "my-bucket"
    assert key == "docs/acme/proposal.pdf"
    assert extra["ContentType"] == "application/pdf"
    assert "s3://my-bucket/docs/acme/proposal.pdf" in desc


def test_s3_missing_bucket_raises_before_network(tree, monkeypatch):
    root, _ = tree
    _install_fake_boto3(monkeypatch)
    from md_doc.sync import s3

    with pytest.raises(ValueError, match="bucket"):
        s3.make_uploader(root, {})


# ── Azure ───────────────────────────────────────────────────────────────────


def _install_fake_azure(monkeypatch):
    uploaded: list[str] = []

    class _FileClient:
        def __init__(self, path):
            self._path = path

        def upload_file(self, fh):
            uploaded.append(self._path)

    class _ShareClient:
        def get_directory_client(self, path):
            return types.SimpleNamespace(create_directory=lambda: None)

        def get_file_client(self, path):
            return _FileClient(path)

    class _ServiceClient:
        @classmethod
        def from_connection_string(cls, cs):
            return cls()

        def get_share_client(self, name):
            return _ShareClient()

    # Build the azure.* package chain the backend imports from.
    for name in (
        "azure",
        "azure.storage",
        "azure.storage.fileshare",
        "azure.core",
        "azure.core.exceptions",
    ):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    sys.modules["azure.storage.fileshare"].ShareServiceClient = _ServiceClient
    sys.modules["azure.core.exceptions"].ResourceExistsError = type(
        "ResourceExistsError", (Exception,), {}
    )
    return uploaded


def test_azure_builds_remote_path(tree, monkeypatch):
    root, f = tree
    uploaded = _install_fake_azure(monkeypatch)
    from md_doc.sync import azure_files

    upload = azure_files.make_uploader(
        root, {"share_name": "share", "directory": "docs", "connection_string": "cs"}
    )
    desc = upload(f)
    assert uploaded == ["docs/acme/proposal.pdf"]
    assert "share/docs/acme/proposal.pdf" in desc


def test_azure_missing_credentials_raises(tree, monkeypatch):
    root, _ = tree
    _install_fake_azure(monkeypatch)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    from md_doc.sync import azure_files

    with pytest.raises(ValueError, match="connection string"):
        azure_files.make_uploader(root, {"share_name": "share"})
