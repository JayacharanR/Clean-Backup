"""
Seed the demo database with sample data.

Run at container startup when DEMO_MODE=true. Populates the SQLite DB
with pre-classified images and sample watcher configs so visitors land
on an already-populated UI.

Usage::

    DEMO_MODE=true python deploy/demo/seed_demo_db.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


SEED_MEDIA_DIR = Path(__file__).resolve().parent / "seed-media"
DEMO_MEDIA_DIR = Path(os.environ.get("CLEAN_BACKUP_MEDIA_PATH", "/data/media"))


def seed():
    """Main entry point — copies seed media and populates the database."""
    from src.demo import is_demo_mode

    if not is_demo_mode():
        print("DEMO_MODE is not set. Skipping seed.")
        return

    print("==> Seeding demo database...")

    # 1. Copy seed media to the demo media directory
    _copy_seed_media()

    # 2. Initialize the classification DB
    from src.classify.db import init_db
    init_db()

    # 3. Insert sample watcher configs (UI demo, won't actually run)
    _seed_watcher_configs()

    # 4. Insert sample classification results
    _seed_classification_data()

    # 5. Run the classify pipeline if models are available
    _run_initial_classify()

    print("==> Demo seeding complete!")


def _copy_seed_media():
    """Copy seed images to the demo media directory."""
    if not SEED_MEDIA_DIR.exists():
        print(f"  [skip] Seed media not found at {SEED_MEDIA_DIR}")
        print("         Run: bash deploy/demo/download_seed_media.sh")
        return

    DEMO_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    count = 0
    for src_file in SEED_MEDIA_DIR.iterdir():
        if src_file.is_file() and src_file.suffix.lower() in (".jpg", ".jpeg", ".png"):
            dest = DEMO_MEDIA_DIR / src_file.name
            if not dest.exists():
                shutil.copy2(src_file, dest)
                count += 1

    print(f"  [media] Copied {count} seed images to {DEMO_MEDIA_DIR}")


def _seed_watcher_configs():
    """Insert sample watcher configs for the UI demo."""
    from src.watcher import db as watcher_db

    watcher_db.init_db()

    # Check if already seeded
    existing = watcher_db.get_all_configs()
    if existing:
        print("  [watchers] Already seeded, skipping")
        return

    watcher_db.add_config(
        label="📸 Camera Import",
        watch_path=str(DEMO_MEDIA_DIR / "incoming"),
        recursive=True,
        stability_window_seconds=3,
        ignore_patterns=["*.tmp", "*.part"],
        pipeline=[
            {"job_type": "classify", "enabled": True},
            {"job_type": "organize-by-date", "enabled": True},
            {"job_type": "dedupe", "enabled": True},
        ],
        on_complete="leave",
        on_error="leave",
        enabled=False,  # Disabled in demo — just shows the UI
    )

    watcher_db.add_config(
        label="📁 SD Card Drop",
        watch_path=str(DEMO_MEDIA_DIR / "sd-card"),
        recursive=True,
        stability_window_seconds=5,
        ignore_patterns=[],
        pipeline=[
            {"job_type": "classify", "enabled": True},
            {"job_type": "cloud_sync", "enabled": True},
        ],
        on_complete="leave",
        on_error="leave",
        enabled=False,
    )

    # Add some sample events
    configs = watcher_db.get_all_configs()
    if configs:
        for img_name in ["travel_01.jpg", "nature_01.jpg", "food_01.jpg"]:
            watcher_db.add_event(
                configs[0].id,
                str(DEMO_MEDIA_DIR / img_name),
                status="completed",
            )

    print("  [watchers] Seeded 2 watcher configs + sample events")


def _seed_classification_data():
    """Insert sample classification results into the DB."""
    print("  [classify] Classification data will be populated by initial pipeline run")


def _run_initial_classify():
    """Run the classify pipeline on seed images if ML is available."""
    disable_ml = os.environ.get("CLEAN_BACKUP_DISABLE_ML", "").lower() in ("1", "true", "yes")
    if disable_ml:
        print("  [classify] ML disabled, skipping initial classify run")
        return

    media_files = list(DEMO_MEDIA_DIR.glob("*.jpg")) + list(DEMO_MEDIA_DIR.glob("*.png"))
    if not media_files:
        print("  [classify] No media files to classify")
        return

    try:
        from src.classify.pipeline import run_classify_pipeline
        from src.classify.db import save_run_config

        wizard_config = {
            "enabled_categories": [
                "travel", "nature", "food", "pets", "documents",
                "screenshots", "night", "events", "art", "vehicles",
                "selfies", "family", "other",
            ],
            "confidence_threshold": 0.4,
            "face_sensitivity": "balanced",
        }

        run_id = f"demo_seed_{int(time.time())}"
        save_run_config(run_id, wizard_config)

        print(f"  [classify] Running classify pipeline on {len(media_files)} files...")
        run_classify_pipeline(
            str(DEMO_MEDIA_DIR),
            run_id,
            wizard_config,
            lambda p, m: None,  # No progress callback needed
        )
        print(f"  [classify] Pipeline complete (run_id={run_id})")

    except Exception as exc:
        print(f"  [classify] Pipeline failed (non-fatal): {exc}")


if __name__ == "__main__":
    seed()
