"""Move or copy classified files into category folders."""

import logging
import os
import re
from pathlib import Path

from src.classify.db import get_all_tags_for_run, get_run_config
from src.file_operations import verified_transfer
from src.metadata import get_media_date
from src.undo_manager import UndoManager

logger = logging.getLogger(__name__)


def apply_classification(run_id, dest_dir, operation, progress_cb=None):
    """
    Applies the classification results from the DB to physical files.

    ``progress_cb`` follows the job convention ``(percent, message)``.
    """
    if operation not in {"move", "copy"}:
        raise ValueError("operation must be move or copy")
    with UndoManager() as undo_mgr:
        return _apply_classification(run_id, dest_dir, operation, progress_cb, undo_mgr)


def _folder_name(label):
    """One safe directory name per category: "Nature / Scenery" -> "Nature - Scenery"."""
    return re.sub(r"\s*[/\\:]+\s*", " - ", str(label)).strip(" .") or "Other"


def _category_folder(folder_scheme, label, yyyy, mm):
    label = _folder_name(label)
    if folder_scheme == "yyyy_mm_category":
        return Path(yyyy) / mm / label
    if folder_scheme == "category_yyyy_mm":
        return Path(label) / yyyy / mm
    return Path(label)  # flat_tags


def _apply_classification(run_id, dest_dir, operation, progress_cb, undo_mgr):
    dest_path = Path(dest_dir).expanduser().resolve()
    dest_path.mkdir(parents=True, exist_ok=True)

    config = get_run_config(run_id)
    if not config:
        raise ValueError(f"Run ID {run_id} not found in DB")

    folder_scheme = config.get("folder_scheme", "yyyy_mm_category")
    multi_category = config.get("multi_category", "tags")

    # get_all_tags_for_run orders by category priority, so each file's first
    # tag is its primary category.
    files = {}
    for tag in get_all_tags_for_run(run_id):
        files.setdefault(tag["path"], []).append(tag)

    total_files = len(files)
    processed = 0
    transferred = 0
    errors = 0

    for src_path_str, file_tags in files.items():
        processed += 1
        src_path = Path(src_path_str)
        if not src_path.is_file():
            logger.warning(f"File not found: {src_path}")
            continue

        # Capture date from the media itself (same rule as date organization),
        # not the time the file happened to be catalogued.
        taken = get_media_date(src_path)
        yyyy, mm = taken.strftime("%Y"), taken.strftime("%m")

        target_dir = dest_path / _category_folder(
            folder_scheme, file_tags[0]["category_label"], yyyy, mm
        )
        try:
            # Verified, journaled and collision-safe; never replaces a file.
            target_file = verified_transfer(
                src_path, target_dir / src_path.name, operation, journal=undo_mgr
            )
            transferred += 1
        except Exception as e:
            logger.error(f"Failed to {operation} {src_path}: {e}")
            errors += 1
            continue

        # Handle multi-category symlinks if enabled
        if multi_category == "symlink":
            for secondary_tag in file_tags[1:]:
                sec_dir = dest_path / _category_folder(
                    folder_scheme, secondary_tag["category_label"], yyyy, mm
                )
                sec_file = sec_dir / target_file.name
                try:
                    sec_dir.mkdir(parents=True, exist_ok=True)
                    if not os.path.lexists(sec_file):
                        os.symlink(str(target_file), str(sec_file))
                except Exception as e:
                    logger.error(f"Failed to create symlink for {src_path}: {e}")

        if progress_cb and processed % 5 == 0:
            progress_cb(
                5 + int(processed / total_files * 90),
                f"Processing {processed}/{total_files}...",
            )

    if progress_cb:
        progress_cb(98, f"Finished. Processed {total_files} files.")

    return {
        "total_processed": processed,
        "transferred": transferred,
        "errors": errors,
        "session_id": undo_mgr.session_id,
    }
