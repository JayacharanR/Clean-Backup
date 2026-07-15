"""
DB helper functions for cloud sync manifest and run tracking.

All tables live in the same ``clean_backup.db`` used by the classify
module — access via ``_get_conn()`` from ``src.classify.db``.
"""

from __future__ import annotations

import json
from datetime import datetime

from src.classify.db import _get_conn
from src.logger import logger


# ── Cloud accounts ─────────────────────────────────────────────────────────

def create_cloud_account(provider: str, label: str, credential_ref: str) -> int:
    """Insert a new cloud account row. Returns the new account ID."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO cloud_accounts (provider, label, credential_ref) VALUES (?, ?, ?)",
        (provider, label, credential_ref),
    )
    conn.commit()
    return cur.lastrowid


def list_cloud_accounts() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, provider, label, credential_ref, created_at FROM cloud_accounts ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_cloud_account(account_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, provider, label, credential_ref, created_at FROM cloud_accounts WHERE id = ?",
        (account_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_cloud_account(account_id: int) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM cloud_accounts WHERE id = ?", (account_id,))
    conn.commit()
    return cur.rowcount > 0


# ── Sync runs ──────────────────────────────────────────────────────────────

def create_sync_run(account_id: int, config: dict) -> int:
    """Create a new sync run record. Returns the run ID."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO sync_runs (account_id, config_json, status) VALUES (?, ?, 'pending')",
        (account_id, json.dumps(config)),
    )
    conn.commit()
    return cur.lastrowid


def update_sync_run(run_id: int, **fields) -> None:
    """Update fields on a sync run (status, started_at, completed_at, etc.)."""
    conn = _get_conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [run_id]
    conn.execute(f"UPDATE sync_runs SET {sets} WHERE id = ?", vals)
    conn.commit()


def get_sync_run(run_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, account_id, config_json, status, started_at, completed_at FROM sync_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d.pop("config_json"))
    return d


def get_latest_run_for_account(account_id: int) -> dict | None:
    """Return the most recent sync run for an account (for undo gating)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, account_id, config_json, status, started_at, completed_at "
        "FROM sync_runs WHERE account_id = ? ORDER BY id DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d.pop("config_json"))
    return d


def list_sync_runs(limit: int = 50) -> list[dict]:
    """List recent sync runs across all accounts."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT sr.id, sr.account_id, ca.provider, ca.label AS account_label, "
        "sr.status, sr.started_at, sr.completed_at "
        "FROM sync_runs sr "
        "JOIN cloud_accounts ca ON ca.id = sr.account_id "
        "ORDER BY sr.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Sync manifest ─────────────────────────────────────────────────────────

def record_upload(
    sync_run_id: int,
    local_path: str,
    remote_path: str,
    content_hash: str,
    file_id: int | None = None,
    status: str = "uploaded",
) -> int:
    conn = _get_conn()
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO sync_manifest (sync_run_id, file_id, local_path, remote_path, "
        "content_hash, uploaded_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sync_run_id, file_id, local_path, remote_path, content_hash, now, status),
    )
    conn.commit()
    return cur.lastrowid


def get_manifest_for_run(run_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, sync_run_id, file_id, local_path, remote_path, "
        "content_hash, uploaded_at, status FROM sync_manifest WHERE sync_run_id = ?",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_uploaded_hashes_for_account(account_id: int) -> dict[str, str]:
    """
    Return a mapping of ``local_path → content_hash`` for all successfully
    uploaded files across all runs for *account_id*.

    Used by incremental sync to decide which files can be skipped.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT sm.local_path, sm.content_hash "
        "FROM sync_manifest sm "
        "JOIN sync_runs sr ON sr.id = sm.sync_run_id "
        "WHERE sr.account_id = ? AND sm.status = 'uploaded' "
        "ORDER BY sm.uploaded_at DESC",
        (account_id,),
    ).fetchall()
    # Latest entry per path wins
    result: dict[str, str] = {}
    for r in rows:
        path = r["local_path"]
        if path not in result:
            result[path] = r["content_hash"]
    return result


def mark_deleted_by_undo(run_id: int) -> int:
    """Mark all 'uploaded' rows in *run_id* as 'deleted_by_undo'. Returns count."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE sync_manifest SET status = 'deleted_by_undo' "
        "WHERE sync_run_id = ? AND status = 'uploaded'",
        (run_id,),
    )
    conn.commit()
    return cur.rowcount


def get_run_stats(run_id: int) -> dict:
    """Return aggregate stats for a sync run."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT "
        "COUNT(*) AS total, "
        "SUM(CASE WHEN status='uploaded' THEN 1 ELSE 0 END) AS uploaded, "
        "SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped, "
        "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed "
        "FROM sync_manifest WHERE sync_run_id = ?",
        (run_id,),
    ).fetchone()
    return dict(row) if row else {"total": 0, "uploaded": 0, "skipped": 0, "failed": 0}
