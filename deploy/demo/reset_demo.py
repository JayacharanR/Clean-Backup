"""
Reset the demo instance to a pristine state.

Called by a scheduled job every 30 minutes when DEMO_MODE=true.
Wipes the database and re-seeds from scratch so one visitor's
poking around doesn't degrade the demo for the next person.

Usage::

    DEMO_MODE=true python deploy/demo/reset_demo.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


RESET_INTERVAL_SECONDS = 30 * 60  # 30 minutes


def reset_demo():
    """Wipe DB tables and re-seed."""
    from src.demo import is_demo_mode

    if not is_demo_mode():
        return

    print("[demo-reset] Resetting demo database...")

    db_path = Path(os.environ.get(
        "CLEAN_BACKUP_DB_PATH",
        str(PROJECT_ROOT / "clean_backup.db"),
    ))

    # Wipe the DB by deleting and re-initializing
    if db_path.exists():
        # Close any existing connections (best-effort)
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            # Delete all user-created data, keep schema
            for table in [
                "watcher_events", "watcher_configs",
                "classifications", "classification_runs",
                "faces", "people", "review_queue",
                "cloud_sync_runs", "cloud_sync_files", "cloud_accounts",
            ]:
                try:
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass  # Table may not exist
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"[demo-reset] DB cleanup warning: {exc}")

    # Re-seed
    from deploy.demo.seed_demo_db import seed
    seed()

    print("[demo-reset] Reset complete.")


def start_reset_scheduler():
    """Start a background thread that resets the demo periodically.

    Call this from the Flask startup path when DEMO_MODE=true.
    """
    from src.demo import is_demo_mode

    if not is_demo_mode():
        return

    def _loop():
        while True:
            time.sleep(RESET_INTERVAL_SECONDS)
            try:
                reset_demo()
            except Exception as exc:
                print(f"[demo-reset] Scheduled reset failed: {exc}")

    thread = threading.Thread(target=_loop, daemon=True, name="demo-reset")
    thread.start()
    print(f"[demo-reset] Scheduled reset every {RESET_INTERVAL_SECONDS // 60} minutes")


if __name__ == "__main__":
    reset_demo()
