"""
SQLite database layer for image classification.

Creates and manages all tables related to media tagging, people/face
recognition, and per-run configuration snapshots.  The database file
lives at ``clean_backup.db`` in the project root.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from src.classify.category_config import CATEGORY_TAXONOMY
from src.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "clean_backup.db"

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection (auto-created on first call)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


# ── Schema creation ────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS media_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    UNIQUE NOT NULL,
    filename    TEXT,
    extension   TEXT,
    size_bytes  INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT    UNIQUE NOT NULL,
    label           TEXT    NOT NULL,
    priority        INTEGER DEFAULT 5,
    default_enabled BOOLEAN DEFAULT 1,
    detection       TEXT
);

CREATE TABLE IF NOT EXISTS media_tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    confidence  REAL    DEFAULT 1.0,
    source      TEXT    DEFAULT 'heuristic',
    run_id      TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id)     REFERENCES media_files(id),
    FOREIGN KEY (category_id) REFERENCES categories(id),
    UNIQUE(file_id, category_id, run_id)
);

CREATE TABLE IF NOT EXISTS people (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    cover_face_id INTEGER,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS face_embeddings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER,
    file_id     INTEGER NOT NULL,
    bbox        TEXT    NOT NULL,
    embedding   BLOB,
    confidence  REAL    DEFAULT 0.0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (person_id) REFERENCES people(id),
    FOREIGN KEY (file_id)   REFERENCES media_files(id)
);

CREATE TABLE IF NOT EXISTS classify_run_config (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    UNIQUE NOT NULL,
    config_json TEXT    NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_queue (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id               INTEGER NOT NULL,
    review_type           TEXT    NOT NULL,
    suggested_category_id INTEGER,
    confidence            REAL,
    resolved              BOOLEAN DEFAULT 0,
    resolved_category_id  INTEGER,
    run_id                TEXT,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES media_files(id)
);

CREATE TABLE IF NOT EXISTS cloud_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider        TEXT    NOT NULL,
    label           TEXT    NOT NULL,
    credential_ref  TEXT    NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL,
    config_json     TEXT    NOT NULL,
    status          TEXT    DEFAULT 'pending',
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES cloud_accounts(id)
);

CREATE TABLE IF NOT EXISTS sync_manifest (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id     INTEGER NOT NULL,
    file_id         INTEGER,
    local_path      TEXT    NOT NULL,
    remote_path     TEXT    NOT NULL,
    content_hash    TEXT,
    uploaded_at     TIMESTAMP,
    status          TEXT    DEFAULT 'pending',
    FOREIGN KEY (sync_run_id) REFERENCES sync_runs(id)
);
"""


def init_db() -> None:
    """Create all tables (if they don't exist) and seed the category taxonomy."""
    conn = _get_conn()
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    seed_categories()
    logger.info("Classification database initialised at %s", DB_PATH)


def seed_categories() -> None:
    """Insert default categories from the taxonomy, skipping any that already exist."""
    conn = _get_conn()
    for cat in CATEGORY_TAXONOMY:
        conn.execute(
            """
            INSERT OR IGNORE INTO categories (key, label, priority, default_enabled, detection)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cat["key"], cat["label"], cat["priority"], cat["default_enabled"], cat["detection"]),
        )
    conn.commit()


# ── Media files ────────────────────────────────────────────────────────────

def get_or_create_media_file(path: str) -> int:
    """Return the ``file_id`` for *path*, inserting a new row if needed."""
    conn = _get_conn()
    p = Path(path)
    row = conn.execute("SELECT id FROM media_files WHERE path = ?", (str(p),)).fetchone()
    if row:
        return row["id"]

    size = p.stat().st_size if p.exists() else 0
    cur = conn.execute(
        "INSERT INTO media_files (path, filename, extension, size_bytes) VALUES (?, ?, ?, ?)",
        (str(p), p.name, p.suffix.lower(), size),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


# ── Tags ───────────────────────────────────────────────────────────────────

def _category_id_for_key(key: str) -> int | None:
    conn = _get_conn()
    row = conn.execute("SELECT id FROM categories WHERE key = ?", (key,)).fetchone()
    return row["id"] if row else None


def add_tag(
    file_id: int,
    category_key: str,
    confidence: float = 1.0,
    source: str = "heuristic",
    run_id: str | None = None,
) -> None:
    """Attach a category tag to a media file. Duplicates (same file+category+run) are silently ignored."""
    cat_id = _category_id_for_key(category_key)
    if cat_id is None:
        logger.warning("Unknown category key: %s", category_key)
        return
    conn = _get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO media_tags (file_id, category_id, confidence, source, run_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (file_id, cat_id, confidence, source, run_id),
    )
    conn.commit()


def get_tags_for_file(file_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT mt.id, c.key, c.label, mt.confidence, mt.source, mt.run_id, mt.created_at
        FROM media_tags mt
        JOIN categories c ON c.id = mt.category_id
        WHERE mt.file_id = ?
        ORDER BY c.priority
        """,
        (file_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_tags_for_run(run_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT mt.id, mf.path, mf.filename, c.key AS category_key, c.label AS category_label,
               mt.confidence, mt.source
        FROM media_tags mt
        JOIN media_files mf ON mf.id = mt.file_id
        JOIN categories c   ON c.id  = mt.category_id
        WHERE mt.run_id = ?
        ORDER BY c.priority, mf.filename
        """,
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Run configuration ─────────────────────────────────────────────────────

def save_run_config(run_id: str, config: dict) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO classify_run_config (run_id, config_json) VALUES (?, ?)",
        (run_id, json.dumps(config)),
    )
    conn.commit()


def get_run_config(run_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT config_json FROM classify_run_config WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row:
        return json.loads(row["config_json"])
    return None


# ── Categories ─────────────────────────────────────────────────────────────

def get_categories(enabled_only: bool = False) -> list[dict]:
    conn = _get_conn()
    query = "SELECT * FROM categories ORDER BY priority, label"
    if enabled_only:
        query = "SELECT * FROM categories WHERE default_enabled = 1 ORDER BY priority, label"
    return [dict(r) for r in conn.execute(query).fetchall()]


def update_category(cat_id: int, enabled: bool | None = None, priority: int | None = None) -> bool:
    conn = _get_conn()
    parts: list[str] = []
    values: list = []
    if enabled is not None:
        parts.append("default_enabled = ?")
        values.append(enabled)
    if priority is not None:
        parts.append("priority = ?")
        values.append(priority)
    if not parts:
        return False
    values.append(cat_id)
    conn.execute(f"UPDATE categories SET {', '.join(parts)} WHERE id = ?", values)
    conn.commit()
    return True


# ── Review queue ───────────────────────────────────────────────────────────

def add_to_review_queue(
    file_id: int,
    review_type: str,
    suggested_category_id: int | None,
    confidence: float,
    run_id: str | None = None,
) -> None:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO review_queue (file_id, review_type, suggested_category_id, confidence, run_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (file_id, review_type, suggested_category_id, confidence, run_id),
    )
    conn.commit()


def get_review_queue(review_type: str | None = None, resolved: bool = False) -> list[dict]:
    conn = _get_conn()
    query = """
        SELECT rq.id, mf.path, mf.filename, rq.review_type, rq.confidence, rq.resolved,
               c.key AS suggested_key, c.label AS suggested_label, c.id AS suggested_category_id,
               rq.run_id, rq.created_at
        FROM review_queue rq
        JOIN media_files mf ON mf.id = rq.file_id
        LEFT JOIN categories c ON c.id = rq.suggested_category_id
        WHERE rq.resolved = ?
    """
    params: list = [int(resolved)]
    if review_type and review_type != "all":
        query += " AND rq.review_type = ?"
        params.append(review_type)
    query += " ORDER BY rq.created_at DESC"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def resolve_review(review_id: int, category_id: int) -> bool:
    conn = _get_conn()
    # Get the review item to find the file_id
    row = conn.execute("SELECT file_id, run_id FROM review_queue WHERE id = ?", (review_id,)).fetchone()
    if not row:
        return False

    file_id = row["file_id"]
    run_id = row["run_id"]

    # Get category key
    cat_row = conn.execute("SELECT key FROM categories WHERE id = ?", (category_id,)).fetchone()
    if cat_row:
        add_tag(file_id, cat_row["key"], confidence=1.0, source="manual", run_id=run_id)

    conn.execute(
        "UPDATE review_queue SET resolved = 1, resolved_category_id = ? WHERE id = ?",
        (category_id, review_id),
    )
    conn.commit()
    return True


# ── People ─────────────────────────────────────────────────────────────────

def create_person(name: str, cover_face_id: int | None = None) -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO people (name, cover_face_id) VALUES (?, ?)", (name, cover_face_id)
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def get_people() -> list[dict]:
    conn = _get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM people ORDER BY name").fetchall()]


def update_person(person_id: int, name: str | None = None) -> bool:
    conn = _get_conn()
    if name is not None:
        conn.execute("UPDATE people SET name = ? WHERE id = ?", (name, person_id))
        conn.commit()
        return True
    return False


def delete_person(person_id: int, purge_embeddings: bool = False) -> bool:
    conn = _get_conn()
    if purge_embeddings:
        conn.execute("DELETE FROM face_embeddings WHERE person_id = ?", (person_id,))
    else:
        conn.execute("UPDATE face_embeddings SET person_id = NULL WHERE person_id = ?", (person_id,))
    conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
    conn.commit()
    return True


def merge_people(keep_id: int, merge_id: int) -> bool:
    """Merge *merge_id* into *keep_id*: move embeddings, then delete the merged person."""
    conn = _get_conn()
    conn.execute(
        "UPDATE face_embeddings SET person_id = ? WHERE person_id = ?", (keep_id, merge_id)
    )
    conn.execute("DELETE FROM people WHERE id = ?", (merge_id,))
    conn.commit()
    return True


# ── Face embeddings ────────────────────────────────────────────────────────

def save_face_embedding(
    file_id: int,
    bbox: dict,
    embedding: bytes | None = None,
    confidence: float = 0.0,
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """
        INSERT INTO face_embeddings (file_id, bbox, embedding, confidence)
        VALUES (?, ?, ?, ?)
        """,
        (file_id, json.dumps(bbox), embedding, confidence),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def assign_face_to_person(face_id: int, person_id: int) -> bool:
    conn = _get_conn()
    conn.execute(
        "UPDATE face_embeddings SET person_id = ? WHERE id = ?", (person_id, face_id)
    )
    conn.commit()
    return True


def get_unidentified_faces() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT fe.id, fe.file_id, fe.bbox, fe.confidence, mf.path, mf.filename
        FROM face_embeddings fe
        JOIN media_files mf ON mf.id = fe.file_id
        WHERE fe.person_id IS NULL
        ORDER BY fe.created_at DESC
        """,
    ).fetchall()
    return [dict(r) for r in rows]


def get_face_embedding_blob(face_id: int) -> bytes | None:
    conn = _get_conn()
    row = conn.execute("SELECT embedding FROM face_embeddings WHERE id = ?", (face_id,)).fetchone()
    return row["embedding"] if row else None


def get_all_known_embeddings() -> list[dict]:
    """Return all face embeddings that are assigned to a person (for matching)."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT fe.id, fe.person_id, fe.embedding, p.name
        FROM face_embeddings fe
        JOIN people p ON p.id = fe.person_id
        WHERE fe.embedding IS NOT NULL
        """,
    ).fetchall()
    return [dict(r) for r in rows]


def purge_face_data() -> dict:
    """Delete all face embeddings and people records. Returns counts."""
    conn = _get_conn()
    face_count = conn.execute("SELECT COUNT(*) AS c FROM face_embeddings").fetchone()["c"]
    people_count = conn.execute("SELECT COUNT(*) AS c FROM people").fetchone()["c"]
    conn.execute("DELETE FROM face_embeddings")
    conn.execute("DELETE FROM people")
    conn.commit()
    logger.info("Purged all face data: %d embeddings, %d people", face_count, people_count)
    return {"faces_deleted": face_count, "people_deleted": people_count}


# ── Classification results summary ────────────────────────────────────────

def get_classification_summary(run_id: str) -> dict:
    """Return per-category tag counts for a given run."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT c.key, c.label, COUNT(*) AS count
        FROM media_tags mt
        JOIN categories c ON c.id = mt.category_id
        WHERE mt.run_id = ?
        GROUP BY c.key
        ORDER BY count DESC
        """,
        (run_id,),
    ).fetchall()

    total = conn.execute(
        "SELECT COUNT(DISTINCT file_id) AS c FROM media_tags WHERE run_id = ?", (run_id,)
    ).fetchone()["c"]

    review_count = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE run_id = ? AND resolved = 0", (run_id,)
    ).fetchone()["c"]

    return {
        "run_id": run_id,
        "total_files_tagged": total,
        "review_pending": review_count,
        "categories": {row["key"]: {"label": row["label"], "count": row["count"]} for row in rows},
    }
