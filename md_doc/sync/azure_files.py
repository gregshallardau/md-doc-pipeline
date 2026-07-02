"""
Azure File Share sync backend.

Uploads built output files to an Azure File Share, preserving relative path
structure as subdirectories within the share.

_meta.yml config:
    sync_target: azure
    sync_config:
      share_name: my-share          # required
      directory: docs/outputs       # optional prefix directory inside the share
      connection_string: "..."      # optional; falls back to env AZURE_STORAGE_CONNECTION_STRING

Dependencies (optional extra):
    pip install "md-doc-pipeline[azure]"
    # i.e. azure-storage-file-share>=12.0
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any, Callable


def make_uploader(root: Path, sync_config: dict[str, Any]) -> Callable[[Path], str]:
    """Return a function that uploads one file to the Azure File Share.

    The SDK import, ``share_name``, and connection string are resolved once here
    so configuration/credential errors surface before the per-file loop.
    """
    try:
        from azure.storage.fileshare import ShareServiceClient
    except ImportError as exc:
        raise ImportError(
            "azure-storage-file-share is required for the Azure backend. "
            "Install with: pip install 'md-doc-pipeline[azure]'"
        ) from exc

    from azure.core.exceptions import ResourceExistsError

    share_name: str = sync_config.get("share_name", "")
    if not share_name:
        raise ValueError("azure sync backend requires 'share_name' in sync_config.")

    connection_string: str = sync_config.get("connection_string") or os.environ.get(
        "AZURE_STORAGE_CONNECTION_STRING", ""
    )
    if not connection_string:
        raise ValueError(
            "Azure connection string not found. Set 'connection_string' in sync_config "
            "or set the AZURE_STORAGE_CONNECTION_STRING environment variable."
        )

    base_directory: str = sync_config.get("directory", "")

    service_client = ShareServiceClient.from_connection_string(connection_string)
    share_client = service_client.get_share_client(share_name)

    def _ensure_directory(dir_path: str) -> None:
        """Create the directory (and parents) inside the share if not present."""
        parts = [p for p in dir_path.split("/") if p]
        built: list[str] = []
        for part in parts:
            built.append(part)
            dir_client = share_client.get_directory_client("/".join(built))
            try:
                dir_client.create_directory()
            except ResourceExistsError:
                pass  # Already exists — any other error propagates so failures surface

    def _upload(src: Path) -> str:
        rel = src.relative_to(root)
        remote_rel = (
            str(PurePosixPath(base_directory) / PurePosixPath(*rel.parts))
            if base_directory
            else str(PurePosixPath(*rel.parts))
        )
        remote_dir = str(PurePosixPath(remote_rel).parent)
        remote_name = PurePosixPath(remote_rel).name

        if remote_dir and remote_dir != ".":
            _ensure_directory(remote_dir)
            file_client = share_client.get_file_client(remote_rel)
        else:
            file_client = share_client.get_file_client(remote_name)

        with open(src, "rb") as fh:
            file_client.upload_file(fh)
        return f"uploaded  {rel}  →  {share_name}/{remote_rel}"

    return _upload


def sync(files: list[Path], root: Path, sync_config: dict[str, Any]) -> None:
    """Upload *files* to an Azure File Share (compat wrapper)."""
    upload = make_uploader(root, sync_config)
    for src in files:
        print(f"  {upload(src)}")
