import json
import os
import shutil
import glob
from pathlib import Path
from datetime import datetime
from src.logger import logger

JOURNAL_DIR = Path("logs/undo_journals")

class UndoManager:
    def __init__(self):
        self.session_id = None
        self.journal_path = None
        self.actions = []
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

    def start_session(self):
        """Start a new transaction session."""
        self.session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.journal_path = JOURNAL_DIR / f"journal_{self.session_id}.json"
        self.actions = []
        logger.info(f"Started undo session: {self.session_id}")

    def log_action(self, action_type, src, dst):
        """Log a file operation.
        
        Args:
            action_type (str): 'move' or 'copy'
            src (str): Source path
            dst (str): Destination path
        """
        if not self.session_id:
            return # No active session

        entry = {
            "action": action_type,
            "src": str(src),
            "dst": str(dst),
            "timestamp": datetime.now().isoformat()
        }
        self.actions.append(entry)
        
        # Write to disk immediately for crash safety (append mode would be better in production, but JSON list is simple)
        self._save_journal()

    def _cleanup_empty_dirs(self, directory):
        """Recursively delete empty directories up the tree."""
        path = Path(directory)
        try:
            # Stop if we reach root or get a permission error
            while path.is_dir() and path != path.parent:  
                if not any(path.iterdir()):
                    path.rmdir()
                    logger.info(f"Cleanup: Deleted empty directory {path}")
                    path = path.parent
                else:
                    break
        except Exception as e:
            # Stops bubbling up if duplicate_handler or other process is using the dir, or permission denied
            pass

    def _save_journal(self):
        try:
            with open(self.journal_path, 'w') as f:
                json.dump(self.actions, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save undo journal: {e}")

    def end_session(self):
        """Close the current session."""
        if self.actions:
            logger.info(f"Ended undo session {self.session_id} with {len(self.actions)} actions.")
        else:
            # Cleanup empty journal
            if self.journal_path and self.journal_path.exists():
                os.remove(self.journal_path)
        
        self.session_id = None
        self.actions = []
        self.journal_path = None

    def list_sessions(self):
        """List available undo sessions."""
        files = sorted(JOURNAL_DIR.glob("journal_*.json"), reverse=True)
        sessions = []
        for p in files:
            try:
                # filename format: journal_YYYY-MM-DD_HH-MM-SS.json
                # session_id matches the timestamp part
                sid = p.stem.replace("journal_", "")
                with open(p, 'r') as f:
                    data = json.load(f)
                    count = len(data)
                sessions.append({"id": sid, "path": p, "count": count})
            except Exception:
                continue
        return sessions

    def undo_session(self, session_path):
        """Revert a specific session."""
        logger.info(f"Reverting session from {session_path}")
        try:
            with open(session_path, 'r') as f:
                actions = json.load(f)
        except Exception as e:
            logger.error(f"Could not read journal file: {e}")
            return False

        success_count = 0
        fail_count = 0

        # Reverse order to undo correctly
        for entry in reversed(actions):
            action = entry.get("action")
            src = entry.get("src") # This was the ORIGINAL source
            dst = entry.get("dst") # This was the destination

            try:
                if action == "move":
                    # Undo move: Move dst back to src
                    if os.path.exists(dst):
                        # Ensure src directory exists
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        shutil.move(dst, src)
                        logger.info(f"Undo Move: {dst} -> {src}")
                        success_count += 1
                        
                        # Cleanup empty directories at destination
                        self._cleanup_empty_dirs(os.path.dirname(dst))
                    else:
                        logger.warning(f"Undo failed: File not found at {dst}")
                        fail_count += 1
                        
                elif action == "copy":
                    # Undo copy: Delete dst
                    if os.path.exists(dst):
                        os.remove(dst)
                        logger.info(f"Undo Copy: Deleted {dst}")
                        success_count += 1
                        
                        # Cleanup empty directories at destination
                        self._cleanup_empty_dirs(os.path.dirname(dst))
                    else:
                        logger.warning(f"Undo failed: File not found at {dst}")
                        fail_count += 1
                    # Note: we don't strictly need to do anything to 'src' for a copy undo, 
                    # as it is essentially "delete the copy".
            
            except Exception as e:
                logger.error(f"Error undoing action {entry}: {e}")
                fail_count += 1

        print(f"\nUndo Complete.")
        print(f"Successfully reverted: {success_count} files")
        print(f"Failed to revert: {fail_count} files")
        
        # Rename journal to indicate it's undone (or delete it?)
        # Let's rename it to .undone
        try:
            new_path = str(session_path) + ".reverted"
            os.rename(session_path, new_path)
            logger.info("Marked journal as reverted.")
        except:
            pass
            
        return True

undo_manager = UndoManager()
