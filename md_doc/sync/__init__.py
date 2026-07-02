"""
Pluggable sync module for md-doc-pipeline.

Syncs built output files (PDF, DOCX, and optionally .md) to a remote or local
destination. Backend and destination are configured via _meta.yml:

    sync_target: azure   # "azure", "s3", or "local"
    sync_config:
      # backend-specific keys (see each backend module)

The ``include_md_in_share`` config key controls whether .md source files are
included in the sync output (default: false).
"""

from __future__ import annotations

import logging
import time
from functools import partial
from pathlib import Path
from typing import Any, Callable

from ..config import load_config, should_sync_md

logger = logging.getLogger(__name__)

# Extensions treated as "built outputs" to always include
_OUTPUT_EXTENSIONS: set[str] = {".pdf", ".docx"}

# Directories to exclude from sync discovery
_EXCLUDE_DIRS: set[str] = {".git", "__pycache__", "themes", "templates"}


class SyncError(RuntimeError):
    """Raised when one or more files fail to sync."""


def _with_retry(
    fn: Callable[[], Any],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Call *fn*, retrying on any exception with exponential backoff.

    Retries *attempts* times total (so ``attempts - 1`` retries). The last
    exception is re-raised if every attempt fails.
    """
    last_exc: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — backends raise varied SDK errors
            last_exc = exc
            if i < attempts - 1:
                delay = base_delay * (2**i)
                logger.warning(
                    "sync attempt %d/%d failed: %s — retrying in %.0fs", i + 1, attempts, exc, delay
                )
                sleep(delay)
    assert last_exc is not None
    raise last_exc


def _collect_files(root: Path, include_md: bool) -> list[Path]:
    """Return the list of files to sync under root."""
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # Skip excluded directories
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        # Skip _meta.yml files and hidden files
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        if path.suffix in _OUTPUT_EXTENSIONS:
            files.append(path)
        elif include_md and path.suffix == ".md":
            files.append(path)
    return files


def _get_backend_name(root: Path, cli_backend: str | None) -> str:
    """Resolve the backend name from CLI arg or root config."""
    if cli_backend:
        return cli_backend.lower()
    config = load_config(root)
    target = config.get("sync_target")
    if not target:
        raise ValueError(
            "No sync backend specified. Set 'sync_target' in _meta.yml or use --backend."
        )
    return str(target).lower()


def _load_uploader(backend_name: str) -> Callable[..., Callable[[Path], str]]:
    """Return the backend's ``make_uploader`` factory."""
    if backend_name == "local":
        from .local import make_uploader
    elif backend_name == "azure":
        from .azure_files import make_uploader  # type: ignore[import]
    elif backend_name == "s3":
        from .s3 import make_uploader  # type: ignore[import]
    else:
        raise ValueError(f"Unknown sync backend: {backend_name!r}. Choose from: azure, s3, local.")
    return make_uploader


def run(
    root: Path,
    backend: str | None = None,
    dry_run: bool = False,
    *,
    retries: int = 3,
) -> dict[str, list]:
    """
    Sync built documents under *root* to the configured storage backend.

    Each file is uploaded independently with bounded retry, so a single
    transient failure neither aborts the batch nor loses track of what
    succeeded. Raises :class:`SyncError` if any file ultimately fails (the CLI
    turns that into a non-zero exit).

    Parameters
    ----------
    root:
        Directory to scan for built output files.
    backend:
        Override backend name ("azure", "s3", "local"). If omitted, read from
        ``sync_target`` in the cascading _meta.yml config.
    dry_run:
        If True, print what would be synced without uploading anything.
    retries:
        Total upload attempts per file (default 3).

    Returns
    -------
    dict
        ``{"uploaded": [rel, ...], "failed": [(rel, error_str), ...]}``.
    """
    root = Path(root).resolve()

    # Load root config for sync settings
    config = load_config(root)
    include_md = should_sync_md(config)
    sync_config: dict[str, Any] = config.get("sync_config", {}) or {}

    backend_name = _get_backend_name(root, backend)

    files = _collect_files(root, include_md)
    if not files:
        print(f"No files to sync under {root}")
        return {"uploaded": [], "failed": []}

    print(f"Backend: {backend_name}")
    print(f"Files to sync ({len(files)}):")
    for f in files:
        print(f"  {f.relative_to(root)}")

    if dry_run:
        return {"uploaded": [], "failed": []}

    # Config/credential problems surface here (before the loop) rather than
    # being retried per file.
    uploader = _load_uploader(backend_name)(root, sync_config)

    uploaded: list[Path] = []
    failed: list[tuple[Path, str]] = []
    for src in files:
        rel = src.relative_to(root)
        try:
            desc = _with_retry(partial(uploader, src), attempts=retries)
            uploaded.append(rel)
            print(f"  ✓ {desc}")
        except Exception as exc:  # noqa: BLE001
            failed.append((rel, str(exc)))
            print(f"  ✗ {rel}: {exc}")

    print(f"\nSynced {len(uploaded)}/{len(files)} file(s); {len(failed)} failed.")
    if failed:
        raise SyncError(f"{len(failed)} of {len(files)} file(s) failed to sync (see log above).")
    return {"uploaded": uploaded, "failed": failed}
