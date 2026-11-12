"""Durable local operation journals and conflict-aware, retryable undo."""

from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid

from src.file_operations import (
    FileConflictError,
    fcntl,
    file_identity,
    fsync_directory,
    locked_paths,
    require_identity,
    verified_transfer,
)
from src.logger import logger

JOURNAL_DIR = Path("logs/undo_journals")


def _write_journal(path, actions):
    """Never truncate the only durable copy of a journal."""
    fd, name = tempfile.mkstemp(prefix=".journal-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(actions, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _session_lock(path):
    fd = os.open(
        str(path) + ".lock",
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


class UndoManager:
    def __init__(self, journal_dir=None):
        self._journal_dir = Path(journal_dir) if journal_dir is not None else None
        self.session_id = None
        self.journal_path = None
        self.actions = []
        self._lock = threading.RLock()
        self._session_fd = None

    def __enter__(self):
        self.start_session()
        return self

    def __exit__(self, *exc):
        self.end_session()

    @property
    def journal_dir(self):
        return (self._journal_dir or JOURNAL_DIR).absolute()

    def start_session(self):
        with self._lock:
            if self.session_id is not None:
                raise RuntimeError("An undo session is already active on this manager")
            self.journal_dir.mkdir(parents=True, exist_ok=True)
            self.session_id = (
                datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f") + "_" + uuid.uuid4().hex
            )
            self.journal_path = self.journal_dir / f"journal_{self.session_id}.json"
            self.actions = []
            self._session_fd = _session_lock(self.journal_path)
            try:
                self._save_journal()
            except BaseException:
                self.end_session()
                raise
            return self.session_id

    def _save_journal(self):
        if self.journal_path is None:
            raise RuntimeError("No active journal")
        _write_journal(self.journal_path, self.actions)

    def prepare_action(self, action, src, dst, source_identity, output_identity):
        """Record intent before a verified temporary output is published."""
        with self._lock:
            if self.session_id is None:
                raise RuntimeError("No active undo session")
            entry = {
                "id": uuid.uuid4().hex,
                "action": action,
                "src": str(Path(src).absolute()),
                "dst": str(Path(dst).absolute()),
                "source_identity": source_identity,
                "output_identity": output_identity,
                "state": "prepared",
                "timestamp": datetime.now().isoformat(),
            }
            self.actions.append(entry)
            self._save_journal()  # An error propagates and prevents publication.
            return entry

    def cancel_action(self, entry):
        with self._lock:
            entry["state"] = "cancelled"
            self._save_journal()

    def complete_action(self, entry, output_identity):
        with self._lock:
            entry["output_identity"] = output_identity
            entry["state"] = "completed"
            self._save_journal()

    def log_action(self, action_type, src, dst):
        """Compatibility for older callers; new transfers must record intent first.

        Old path-only journals remain readable, but undo refuses them because they
        cannot prove ownership of the current file. Missing outputs are recorded
        as unresolved rather than later acquiring an unrelated file's identity.
        """
        if self.session_id is None:
            raise RuntimeError("No active undo session")
        try:
            identity = file_identity(dst)
        except OSError:
            identity = None
        try:
            source_identity = file_identity(src)
        except OSError:
            source_identity = None
        entry = self.prepare_action(action_type, src, dst, source_identity, identity)
        self.complete_action(entry, identity)

    def end_session(self):
        with self._lock:
            try:
                if self.journal_path and not self.actions:
                    self.journal_path.unlink(missing_ok=True)
            finally:
                if self._session_fd is not None:
                    os.close(self._session_fd)
                self._session_fd = None
                self.session_id = None
                self.actions = []
                self.journal_path = None

    def list_sessions(self):
        sessions = []
        for path in sorted(self.journal_dir.glob("journal_*.json"), reverse=True):
            fd = None
            try:
                fd = _session_lock(path)
                actions = json.loads(path.read_text())
                count = sum(
                    a.get("state") not in {"undone", "cancelled"} for a in actions
                )
                if count:
                    sessions.append(
                        {
                            "id": path.stem.removeprefix("journal_"),
                            "path": path,
                            "count": count,
                        }
                    )
            except (OSError, ValueError, TypeError):
                continue
            finally:
                if fd is not None:
                    os.close(fd)
        return sessions

    @staticmethod
    def _check_copy_survivor(entry):
        identity = file_identity(entry["src"])
        expected = entry.get("source_identity") or entry.get("output_identity")
        if not expected or any(identity[k] != expected[k] for k in ("sha256", "size")):
            raise FileConflictError(
                "The original copy source is missing or changed; retaining the output"
            )

    def _undo_entry(self, entry, save):
        action, src, dst = entry["action"], Path(entry["src"]), Path(entry["dst"])
        expected = entry.get("output_identity")
        if action not in {"copy", "move"} or not expected:
            raise FileConflictError(
                "Journal has no supported, verified output identity; manual review required"
            )
        with locked_paths(src, dst):
            if not os.path.lexists(dst):
                if entry.get("undo_phase") == "removing":
                    if action == "copy":
                        self._check_copy_survivor(entry)
                    else:
                        require_identity(src, entry["restore_identity"])
                    return
                if entry.get("state") == "prepared":
                    require_identity(src, entry["source_identity"])
                    return  # The intent was written but no final output was published.
                raise FileConflictError(f"Recorded output is missing: {dst}")
            require_identity(dst, expected, published=entry.get("state") == "prepared")
            if action == "copy":
                self._check_copy_survivor(entry)
            elif os.path.lexists(src):
                if entry.get("restore_identity"):
                    require_identity(src, entry["restore_identity"])
                elif entry.get("state") == "prepared":
                    require_identity(src, entry["source_identity"])
                else:
                    raise FileConflictError(
                        f"Restore path is occupied; retaining both files: {src}"
                    )
            else:
                restored = verified_transfer(dst, src, "copy", collision="error")
                entry["restore_identity"] = file_identity(restored)
                save()
            entry["undo_phase"] = "removing"
            save()  # A retry can distinguish an interrupted undo from a missing file.
            if action == "copy":
                self._check_copy_survivor(entry)
            else:
                require_identity(
                    src, entry.get("restore_identity") or entry["source_identity"]
                )
            require_identity(dst, expected, published=entry.get("state") == "prepared")
            dst.unlink()
            fsync_directory(dst.parent)

    def undo_session(self, session_path):
        path = Path(session_path).absolute()
        fd = None
        try:
            fd = _session_lock(path)
            actions = json.loads(path.read_text())

            def save():
                _write_journal(path, actions)

            for entry in reversed(actions):
                if entry.get("state") in {"undone", "cancelled"}:
                    continue
                try:
                    self._undo_entry(entry, save)
                    entry["state"] = "undone"
                    entry.pop("error", None)
                    save()
                except Exception as exc:
                    logger.error("Undo conflict for %s: %s", entry.get("dst"), exc)
                    entry["error"] = str(exc)
                    save()
            if any(a.get("state") not in {"undone", "cancelled"} for a in actions):
                return False
            os.replace(path, str(path) + ".reverted")
            fsync_directory(path.parent)
            return True
        except (OSError, ValueError, TypeError) as exc:
            logger.error("Could not revert journal %s: %s", path, exc)
            return False
        finally:
            if fd is not None:
                os.close(fd)


undo_manager = UndoManager()
