"""
SQLite backend for the Watcher daemon configs and events.
Uses the central clean_backup.db
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from src.classify.db import DB_PATH

_local = threading.local()

def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn

def init_db() -> None:
    """Initialize the watcher tables if they don't exist."""
    conn = _get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watcher_configs (
            id INTEGER PRIMARY KEY,
            label TEXT,
            watch_path TEXT,
            recursive BOOLEAN,
            stability_window_seconds INTEGER,
            ignore_patterns TEXT,
            pipeline_json TEXT,
            on_complete TEXT,
            on_error TEXT,
            enabled BOOLEAN,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        """
    )
    
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watcher_events (
            id INTEGER PRIMARY KEY,
            watcher_config_id INTEGER,
            file_path TEXT,
            detected_at TIMESTAMP,
            triggered_job_id TEXT,
            status TEXT,
            error_message TEXT,
            FOREIGN KEY(watcher_config_id) REFERENCES watcher_configs(id)
        )
        """
    )
    
    conn.commit()


@dataclass
class WatcherConfig:
    id: int
    label: str
    watch_path: str
    recursive: bool
    stability_window_seconds: int
    ignore_patterns: list[str]
    pipeline: list[dict[str, Any]]
    on_complete: str
    on_error: str
    enabled: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> WatcherConfig:
        return cls(
            id=row["id"],
            label=row["label"],
            watch_path=row["watch_path"],
            recursive=bool(row["recursive"]),
            stability_window_seconds=row["stability_window_seconds"],
            ignore_patterns=json.loads(row["ignore_patterns"] or "[]"),
            pipeline=json.loads(row["pipeline_json"] or "[]"),
            on_complete=row["on_complete"],
            on_error=row["on_error"],
            enabled=bool(row["enabled"]),
        )


def get_all_configs() -> list[WatcherConfig]:
    conn = _get_conn()
    cur = conn.execute("SELECT * FROM watcher_configs ORDER BY id ASC")
    return [WatcherConfig.from_row(row) for row in cur]


def get_config(config_id: int) -> WatcherConfig | None:
    conn = _get_conn()
    cur = conn.execute("SELECT * FROM watcher_configs WHERE id = ?", (config_id,))
    row = cur.fetchone()
    return WatcherConfig.from_row(row) if row else None


def add_config(
    label: str,
    watch_path: str,
    recursive: bool,
    stability_window_seconds: int,
    ignore_patterns: list[str],
    pipeline: list[dict[str, Any]],
    on_complete: str,
    on_error: str,
    enabled: bool,
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """
        INSERT INTO watcher_configs (
            label, watch_path, recursive, stability_window_seconds,
            ignore_patterns, pipeline_json, on_complete, on_error,
            enabled, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            label,
            watch_path,
            recursive,
            stability_window_seconds,
            json.dumps(ignore_patterns),
            json.dumps(pipeline),
            on_complete,
            on_error,
            enabled,
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_config(config_id: int, **kwargs: Any) -> bool:
    if not kwargs:
        return True
        
    set_clauses = []
    values = []
    for k, v in kwargs.items():
        if k == "pipeline":
            k = "pipeline_json"
            v = json.dumps(v)
        elif k == "ignore_patterns":
            v = json.dumps(v)
            
        set_clauses.append(f"{k} = ?")
        values.append(v)
        
    set_clauses.append("updated_at = datetime('now')")
    values.append(config_id)
    
    conn = _get_conn()
    cur = conn.execute(
        f"UPDATE watcher_configs SET {', '.join(set_clauses)} WHERE id = ?",
        values,
    )
    conn.commit()
    return cur.rowcount > 0


def delete_config(config_id: int) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM watcher_configs WHERE id = ?", (config_id,))
    conn.commit()
    return cur.rowcount > 0


# ── Events ──────────────────────────────────────────────────────────────────

def add_event(watcher_config_id: int, file_path: str, status: str = "stabilizing") -> int:
    conn = _get_conn()
    cur = conn.execute(
        """
        INSERT INTO watcher_events (watcher_config_id, file_path, detected_at, status)
        VALUES (?, ?, datetime('now'), ?)
        """,
        (watcher_config_id, file_path, status),
    )
    conn.commit()
    return cur.lastrowid


def update_event(
    event_id: int,
    status: str,
    triggered_job_id: str | None = None,
    error_message: str | None = None,
) -> None:
    """Update an event row.  Only overwrites triggered_job_id / error_message
    when they are explicitly passed (not None)."""
    conn = _get_conn()
    set_clauses = ["status = ?"]
    values: list[Any] = [status]

    if triggered_job_id is not None:
        set_clauses.append("triggered_job_id = ?")
        values.append(triggered_job_id)
    if error_message is not None:
        set_clauses.append("error_message = ?")
        values.append(error_message)

    values.append(event_id)
    conn.execute(
        f"UPDATE watcher_events SET {', '.join(set_clauses)} WHERE id = ?",
        values,
    )
    conn.commit()


def get_events(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    conn = _get_conn()
    cur = conn.execute(
        """
        SELECT 
            e.id, e.watcher_config_id, e.file_path, e.detected_at, 
            e.triggered_job_id, e.status, e.error_message,
            c.label as watcher_label
        FROM watcher_events e
        LEFT JOIN watcher_configs c ON e.watcher_config_id = c.id
        ORDER BY e.detected_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    
    events = []
    for row in cur:
        events.append({
            "id": row["id"],
            "watcher_config_id": row["watcher_config_id"],
            "watcher_label": row["watcher_label"],
            "file_path": row["file_path"],
            "detected_at": row["detected_at"],
            "triggered_job_id": row["triggered_job_id"],
            "status": row["status"],
            "error_message": row["error_message"],
        })
    return events



def get_processed_paths(watcher_config_id: int) -> set[str]:
    """Return all file paths that have already been fully processed or ignored."""
    conn = _get_conn()
    cur = conn.execute(
        """
        SELECT file_path FROM watcher_events 
        WHERE watcher_config_id = ? AND status IN ('completed', 'ignored', 'failed')
        """,
        (watcher_config_id,)
    )
    return {row["file_path"] for row in cur}
