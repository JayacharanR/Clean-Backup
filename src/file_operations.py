"""Verified local transfers with atomic, non-replacing publication.

The final name is a hard link to a fully written and verified temporary file.
Filesystems without hard-link support fail closed; no replacing fallback is used.
Locks coordinate Clean_Backup operations, not unrelated editors or filesystem tools.
"""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading

try:
    import fcntl
except ImportError:  # Windows still gets process-local locking and exclusive publication.
    fcntl = None


class FileConflictError(OSError):
    """A source or recorded output no longer matches its expected revision."""


_mutation_lock = threading.RLock()
_held_locks = threading.local()


@contextmanager
def locked_paths(*paths):
    """Serialize cooperating writers, including separate POSIX app processes."""
    with _mutation_lock:
        held = getattr(_held_locks, "paths", {})
        _held_locks.paths = held
        acquired = []
        try:
            for name in sorted({str(Path(p).absolute().parent.resolve() / Path(p).name) for p in paths}):
                if name in held:
                    continue
                lock_dir = Path(tempfile.gettempdir()) / f"clean-backup-locks-{getattr(os, 'getuid', lambda: 0)()}"
                lock_dir.mkdir(mode=0o700, exist_ok=True)
                lock_path = lock_dir / hashlib.sha256(name.encode()).hexdigest()
                fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    if fcntl:
                        fcntl.flock(fd, fcntl.LOCK_EX)
                except BaseException:
                    os.close(fd)
                    raise
                held[name] = fd
                acquired.append(name)
            yield
        finally:
            for name in reversed(acquired):
                os.close(held.pop(name))


def fsync_directory(path):
    """Persist a directory entry after link, rename or unlink on POSIX."""
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _revision(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def file_identity(path):
    """Hash a regular file and refuse symlinks or a revision changed during reading."""
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise FileConflictError(f"Not a regular file: {path}")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    if _revision(before) != _revision(after) or _revision(after) != _revision(path.lstat()):
        raise FileConflictError(f"File changed while reading: {path}")
    return dict(zip(("device", "inode", "size", "mtime_ns", "ctime_ns"), _revision(after)), sha256=digest)


def require_identity(path, expected, *, published=False):
    actual = file_identity(path)
    # Linking/unlinking the staging name changes ctime. Pending journal intents
    # still identify the exact inode and bytes even across that publication step.
    keys = ("device", "inode", "size", "mtime_ns", "sha256") if published else expected.keys()
    if not expected or any(actual.get(key) != expected.get(key) for key in keys):
        raise FileConflictError(f"File changed since the operation was recorded: {path}")
    return actual


def validate_roots(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir():
        raise ValueError(f"Source directory not found: {source}")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and destination directories must not overlap")
    return source, destination


def _temporary_path(target, *, suffix=".partial"):
    fd, name = tempfile.mkstemp(prefix=".clean-backup-", suffix=suffix, dir=target.parent)
    os.close(fd)
    return Path(name)


def _publish(temporary, target):
    # os.link is atomic and refuses all existing targets, including dangling links.
    os.link(temporary, target, follow_symlinks=False)
    fsync_directory(target.parent)


def verified_transfer(source, target, operation="copy", *, journal=None, collision="rename"):
    """Copy, read back and publish; only then remove an unchanged Move source.

    A journal, when supplied, persists intent before publication and completion
    afterward. A failure after publication retains the verified output and its
    pending intent for recovery rather than attempting a destructive rollback.
    """
    if operation not in {"copy", "move"} or collision not in {"rename", "error"}:
        raise ValueError("Invalid transfer operation or collision policy")
    source, target = Path(source).absolute(), Path(target).absolute()
    if source.resolve() == target.resolve():
        raise FileConflictError("Source and destination must differ")
    target.parent.mkdir(parents=True, exist_ok=True)
    with locked_paths(source, target):
        original = file_identity(source)
        temporary = _temporary_path(target)
        try:
            shutil.copy2(source, temporary)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            copied = file_identity(temporary)
            if (copied["size"], copied["sha256"]) != (original["size"], original["sha256"]):
                raise FileConflictError(f"Copy verification failed: {source}")
            require_identity(source, original)
            candidate = target
            counter = 0
            while True:
                entry = journal.prepare_action(operation, source, candidate, original, copied) if journal else None
                try:
                    _publish(temporary, candidate)
                    break
                except FileExistsError:
                    if journal:
                        journal.cancel_action(entry)
                    if collision == "error":
                        raise
                    counter += 1
                    tail = "" if counter == 1 else f"-{counter}"
                    candidate = target.with_name(f"{target.stem}-{original['sha256'][:12]}{tail}{target.suffix}")
            temporary.unlink()
            # Read back once more under the final name before a Move can remove its source.
            output_identity = require_identity(candidate, copied, published=True)
            if operation == "move":
                require_identity(source, original)
                source.unlink()
                fsync_directory(source.parent)
            if journal:
                journal.complete_action(entry, output_identity)
            return candidate
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def staged_output(source, target):
    """Give an encoder private output space, then publish without replacement."""
    source, target = Path(source).absolute(), Path(target).absolute()
    if source.resolve() == target.resolve():
        raise FileConflictError("Compression cannot overwrite its source")
    target.parent.mkdir(parents=True, exist_ok=True)
    with locked_paths(source, target):
        if os.path.lexists(target):
            raise FileExistsError(f"Output already exists: {target}")
        original = file_identity(source)
        temporary = _temporary_path(target, suffix=f".partial{target.suffix}")
        try:
            yield temporary
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            if not temporary.stat().st_size:
                raise FileConflictError("Encoder produced an empty output")
            require_identity(source, original)
            _publish(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
