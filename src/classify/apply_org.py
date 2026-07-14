import os
import shutil
import logging
from pathlib import Path
from src.classify.db import _get_conn, get_run_config, get_all_tags_for_run
from src.undo_manager import UndoManager

logger = logging.getLogger(__name__)

def apply_classification(run_id, dest_dir, operation, progress_cb=None):
    """
    Applies the classification results from the DB to physical files.
    """
    dest_path = Path(dest_dir)
    if not dest_path.exists():
        dest_path.mkdir(parents=True)

    undo_mgr = UndoManager()
    undo_mgr.start_session()
    
    config = get_run_config(run_id)
    if not config:
        raise ValueError(f"Run ID {run_id} not found in DB")
        
    folder_scheme = config.get("folder_scheme", "yyyy_mm_category")
    multi_category = config.get("multi_category", "tags")
    
    tags = get_all_tags_for_run(run_id)
    
    # Group tags by file path
    files = {}
    for tag in tags:
        path = tag["path"]
        if path not in files:
            files[path] = []
        files[path].append(tag)
        
    total_files = len(files)
    processed = 0
    
    for src_path_str, file_tags in files.items():
        src_path = Path(src_path_str)
        if not src_path.exists():
            logger.warning(f"File not found: {src_path}")
            processed += 1
            continue
            
        # The query get_all_tags_for_run already orders by c.priority, so the first is primary
        primary_tag = file_tags[0]
        primary_cat_label = primary_tag["category_label"]
        
        # Extract date from DB or fallback to file modified time
        with _get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT created_at FROM media_files WHERE path = ?", (src_path_str,))
            row = c.fetchone()
            
        if row and row["created_at"]:
            try:
                from datetime import datetime
                # Assuming timestamp is ISO 8601 string
                dt = datetime.fromisoformat(row["created_at"])
            except:
                from datetime import datetime
                dt = datetime.fromtimestamp(src_path.stat().st_mtime)
        else:
            from datetime import datetime
            dt = datetime.fromtimestamp(src_path.stat().st_mtime)
            
        yyyy = dt.strftime("%Y")
        mm = dt.strftime("%m")
        
        # Determine primary destination
        if folder_scheme == "yyyy_mm_category":
            rel_dest = Path(yyyy) / mm / primary_cat_label
        elif folder_scheme == "category_yyyy_mm":
            rel_dest = Path(primary_cat_label) / yyyy / mm
        else: # flat_tags
            rel_dest = Path(primary_cat_label)
            
        target_dir = dest_path / rel_dest
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / src_path.name
        
        # Handle duplicate filename in destination
        counter = 1
        stem = src_path.stem
        suffix = src_path.suffix
        while target_file.exists():
            target_file = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1
            
        # Perform primary operation
        try:
            if operation == "move":
                shutil.move(str(src_path), str(target_file))
                undo_mgr.log_action("move", str(src_path), str(target_file))
            else: # copy
                shutil.copy2(str(src_path), str(target_file))
                undo_mgr.log_action("copy", str(src_path), str(target_file))
                
        except Exception as e:
            logger.error(f"Failed to {operation} {src_path}: {e}")
            processed += 1
            continue
            
        # Handle multi-category symlinks if enabled
        if multi_category == "symlink" and len(file_tags) > 1:
            for secondary_tag in file_tags[1:]:
                sec_cat_label = secondary_tag["category_label"]
                
                if folder_scheme == "yyyy_mm_category":
                    sec_rel = Path(yyyy) / mm / sec_cat_label
                elif folder_scheme == "category_yyyy_mm":
                    sec_rel = Path(sec_cat_label) / yyyy / mm
                else: # flat_tags
                    sec_rel = Path(sec_cat_label)
                    
                sec_dir = dest_path / sec_rel
                sec_dir.mkdir(parents=True, exist_ok=True)
                sec_file = sec_dir / target_file.name
                
                try:
                    # Target needs to be absolute
                    if not sec_file.exists():
                        os.symlink(str(target_file.absolute()), str(sec_file))
                        # Record symlink creation for undo
                        # Since undo_manager doesn't have a specific 'symlink' action out of box, 
                        # we can record it as a 'move' from SYMLINK (dummy) to allow reversing by delete
                        undo_mgr.log_action("move", "SYMLINK", str(sec_file))
                except Exception as e:
                    logger.error(f"Failed to create symlink for {src_path}: {e}")

        processed += 1
        if progress_cb and processed % 5 == 0:
            progress_cb(f"Processing {processed}/{total_files}...")
            
    if progress_cb:
        progress_cb(f"Finished. Processed {total_files} files.")
        
    return {"total_processed": processed, "session_id": undo_mgr.session_id}
