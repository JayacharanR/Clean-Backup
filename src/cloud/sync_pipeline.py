"""
Cloud sync orchestration pipeline.

Handles: config resolution → auth → file scanning → diffing → upload → verify → manifest.
Talks *only* through the ``CloudProvider`` interface — never imports SDK modules directly.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.cloud import credential_store
from src.cloud.manifest import (
    create_sync_run,
    get_cloud_account,
    get_sync_run,
    get_uploaded_hashes_for_account,
    record_upload,
    update_sync_run,
    get_manifest_for_run,
    mark_deleted_by_undo,
    get_run_stats,
    get_latest_run_for_account,
)
from src.cloud.provider_base import CloudProvider
from src.logger import logger

# ── Helpers ────────────────────────────────────────────────────────────────

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic", ".webp",
    ".tiff", ".tif", ".raf", ".cr2", ".nef", ".arw",
}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_provider(provider_name: str) -> CloudProvider:
    """Instantiate the correct provider by name."""
    if provider_name == "gdrive":
        from src.cloud.provider_gdrive import GoogleDriveProvider
        return GoogleDriveProvider()
    elif provider_name == "s3":
        from src.cloud.provider_s3 import S3Provider
        return S3Provider()
    else:
        raise ValueError(f"Unknown cloud provider: {provider_name}")


def _collect_files(source_dir: str) -> list[Path]:
    """Recursively collect all media files under *source_dir*."""
    root = Path(source_dir)
    if not root.is_dir():
        return []
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS:
            files.append(p)
    return files


# ── Main pipeline ─────────────────────────────────────────────────────────

def run_sync(
    run_id: int,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """
    Execute a cloud sync run.

    1. Load config + account from DB
    2. Authenticate with the provider
    3. Scan local files matching scope
    4. Diff against manifest (skip unchanged for incremental)
    5. Upload with optional throttle
    6. Write manifest rows
    7. Return stats
    """

    def _progress(pct: int, msg: str) -> None:
        if progress_cb:
            progress_cb(pct, msg)

    # ── 1. Load config ─────────────────────────────────────────────────
    _progress(2, "Loading configuration…")
    run = get_sync_run(run_id)
    if not run:
        raise ValueError(f"Sync run {run_id} not found")

    config = run["config"]
    account = get_cloud_account(run["account_id"])
    if not account:
        raise ValueError(f"Cloud account {run['account_id']} not found")

    update_sync_run(run_id, status="running", started_at=datetime.now().isoformat())

    # ── 2. Authenticate ────────────────────────────────────────────────
    _progress(5, "Authenticating…")
    provider = _get_provider(account["provider"])

    cred_data = credential_store.retrieve(account["credential_ref"])
    if not cred_data:
        update_sync_run(run_id, status="failed", completed_at=datetime.now().isoformat())
        raise ValueError("Credentials not found — please reconnect the account")

    auth = provider.authenticate(cred_data)
    if not auth.success:
        update_sync_run(run_id, status="failed", completed_at=datetime.now().isoformat())
        raise ValueError(f"Authentication failed: {auth.error}")

    # If the token was refreshed, update stored credentials
    if auth.extra.get("token_json"):
        credential_store.store(account["credential_ref"], auth.extra["token_json"])

    # ── 3. Scan local files ────────────────────────────────────────────
    _progress(10, "Scanning local files…")
    source_dir = config.get("source_dir", "")
    if not source_dir:
        update_sync_run(run_id, status="failed", completed_at=datetime.now().isoformat())
        raise ValueError("No source directory specified")

    all_files = _collect_files(source_dir)
    if not all_files:
        update_sync_run(run_id, status="completed", completed_at=datetime.now().isoformat())
        return {"total": 0, "uploaded": 0, "skipped": 0, "failed": 0}

    # ── 4. Diff (incremental) ──────────────────────────────────────────
    incremental = config.get("sync_type", "incremental") == "incremental"
    already_uploaded: dict[str, str] = {}
    if incremental:
        _progress(12, "Checking previous uploads…")
        already_uploaded = get_uploaded_hashes_for_account(run["account_id"])

    # ── 5. Ensure remote destination ───────────────────────────────────
    remote_dest = config.get("remote_path", "Clean-Backup")
    _progress(15, "Preparing remote destination…")
    provider.ensure_destination(remote_dest)

    # ── 6. Upload loop ─────────────────────────────────────────────────
    folder_scheme = config.get("folder_scheme", "flat")
    duplicate_handling = config.get("duplicate_handling", "skip")
    throttle_kb = config.get("throttle_kb", 0)

    # Simple throttle via a semaphore (sequential uploads with optional delay)
    upload_delay = (1.0 / max(1, throttle_kb / 512)) if throttle_kb > 0 else 0

    total = len(all_files)
    uploaded_count = 0
    skipped_count = 0
    failed_count = 0
    total_bytes = 0
    source_root = Path(source_dir)

    for idx, local_path in enumerate(all_files):
        file_pct = 15 + int((idx / total) * 80)
        _progress(file_pct, f"Uploading {idx + 1}/{total}: {local_path.name}")

        local_str = str(local_path)
        local_hash = _sha256(local_str)

        # Incremental skip
        if incremental and local_str in already_uploaded:
            if already_uploaded[local_str] == local_hash:
                record_upload(run_id, local_str, "", local_hash, status="skipped")
                skipped_count += 1
                continue

        # Build remote path
        relative = local_path.relative_to(source_root)
        if folder_scheme == "mirror":
            remote_file_path = f"{remote_dest}/{relative}"
        else:
            remote_file_path = f"{remote_dest}/{local_path.name}"

        # Upload
        result = provider.upload(
            local_path=local_str,
            remote_path=remote_file_path,
            metadata={"source_path": local_str},
        )

        if result.success:
            record_upload(run_id, local_str, remote_file_path, local_hash, status="uploaded")
            uploaded_count += 1
            total_bytes += result.bytes_uploaded
        else:
            record_upload(run_id, local_str, remote_file_path, local_hash, status="failed")
            failed_count += 1
            logger.warning("Upload failed: %s — %s", local_path.name, result.error)

        if upload_delay:
            time.sleep(upload_delay)

    # ── 7. Finalise ────────────────────────────────────────────────────
    final_status = "completed" if failed_count == 0 else "partial"
    update_sync_run(run_id, status=final_status, completed_at=datetime.now().isoformat())
    _progress(100, "Sync complete")

    return {
        "total": total,
        "uploaded": uploaded_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "total_bytes": total_bytes,
    }


# ── Undo ───────────────────────────────────────────────────────────────────

def undo_sync(
    run_id: int,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """
    Undo a sync run: delete all uploaded files from the remote destination.

    Only allowed on the *most recent* run for its account (enforced by caller).
    """

    def _progress(pct: int, msg: str) -> None:
        if progress_cb:
            progress_cb(pct, msg)

    run = get_sync_run(run_id)
    if not run:
        raise ValueError(f"Sync run {run_id} not found")

    account = get_cloud_account(run["account_id"])
    if not account:
        raise ValueError(f"Cloud account not found")

    # Check it's the latest run
    latest = get_latest_run_for_account(run["account_id"])
    if not latest or latest["id"] != run_id:
        raise ValueError("Only the most recent sync run can be undone")

    _progress(5, "Authenticating…")
    provider = _get_provider(account["provider"])
    cred_data = credential_store.retrieve(account["credential_ref"])
    if not cred_data:
        raise ValueError("Credentials not found")

    auth = provider.authenticate(cred_data)
    if not auth.success:
        raise ValueError(f"Authentication failed: {auth.error}")

    # Get all uploaded entries
    manifest = get_manifest_for_run(run_id)
    uploaded = [m for m in manifest if m["status"] == "uploaded"]

    total = len(uploaded)
    deleted = 0
    failed = 0

    for idx, entry in enumerate(uploaded):
        pct = 5 + int((idx / max(total, 1)) * 90)
        _progress(pct, f"Deleting {idx + 1}/{total}: {entry['remote_path']}")

        try:
            provider.delete(entry["remote_path"])
            deleted += 1
        except Exception as exc:
            logger.error("Failed to delete %s: %s", entry["remote_path"], exc)
            failed += 1

    # Mark manifest
    mark_deleted_by_undo(run_id)
    update_sync_run(run_id, status="undone", completed_at=datetime.now().isoformat())
    _progress(100, "Undo complete")

    return {"deleted": deleted, "failed": failed, "total": total}
