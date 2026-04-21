"""
AWS S3 sync backend.

Uploads built output files to an S3 bucket, preserving relative path
structure as the object key prefix.

_meta.yml config:
    sync_target: s3
    sync_config:
      bucket: my-bucket             # required
      prefix: docs/outputs          # optional key prefix inside the bucket
      region: ap-southeast-2        # optional; falls back to AWS_DEFAULT_REGION / boto3 defaults

Credentials are resolved by boto3's standard chain (env vars, ~/.aws/credentials,
instance profile, etc.).

Dependencies (optional extra):
    pip install "md-doc-pipeline[s3]"
    # i.e. boto3>=1.34
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any


def sync(files: list[Path], root: Path, sync_config: dict[str, Any]) -> None:
    """
    Upload *files* to an S3 bucket.

    Parameters
    ----------
    files:
        Absolute paths of files to upload.
    root:
        Source root (used to compute relative paths for mirroring).
    sync_config:
        Must contain ``bucket``. May contain ``prefix`` and ``region``.
    """
    try:
        import boto3
    except ImportError as exc:
        raise ImportError(
            "boto3 is required for the S3 backend. "
            "Install with: pip install 'md-doc-pipeline[s3]'"
        ) from exc

    bucket: str = sync_config.get("bucket", "")
    if not bucket:
        raise ValueError("s3 sync backend requires 'bucket' in sync_config.")

    prefix: str = sync_config.get("prefix", "").strip("/")
    region: str | None = sync_config.get("region") or os.environ.get("AWS_DEFAULT_REGION") or None

    kwargs: dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region

    s3 = boto3.client("s3", **kwargs)

    # Guess content type from extension
    _CONTENT_TYPES: dict[str, str] = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown; charset=utf-8",
    }

    for src in files:
        rel = src.relative_to(root)
        rel_posix = str(PurePosixPath(*rel.parts))
        key = f"{prefix}/{rel_posix}" if prefix else rel_posix

        extra: dict[str, str] = {}
        content_type = _CONTENT_TYPES.get(src.suffix.lower())
        if content_type:
            extra["ContentType"] = content_type

        s3.upload_file(str(src), bucket, key, ExtraArgs=extra if extra else None)
        print(f"  uploaded  {rel}  →  s3://{bucket}/{key}")
