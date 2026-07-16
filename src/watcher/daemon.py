"""
Daemon to monitor folders using watchdog and enqueue jobs.

Fixes applied from code audit:
- Added missing `import os` (BUG 1 — crash on every debounce tick)
- Lazy-import `jobs` to break circular dependency (BUG 2)
- Cache processed paths per-handler with TTL (BUG 3)
- Only recreate watchers when config actually changed (BUG 6)
- Wire up all pipeline steps including dedupe and cloud_sync (BUG 11)
- Use proper classify wizard config from DB (BUG 12)
"""
import os
import time
import threading
import logging
from pathlib import Path
from fnmatch import fnmatch
from typing import Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.watcher import db

logger = logging.getLogger(__name__)

# ── Processed-paths cache ─────────────────────────────────────────────────
# Instead of querying the DB on every filesystem event (BUG 3), each handler
# keeps a local set that is refreshed from the DB at most once per TTL.

_PROCESSED_CACHE_TTL = 30.0  # seconds


class _ProcessedCache:
    """Thread-safe cache of already-processed file paths for one watcher config."""

    def __init__(self, config_id: int) -> None:
        self._config_id = config_id
        self._paths: set[str] = set()
        self._last_refresh = 0.0
        self._lock = threading.Lock()

    def contains(self, path: str) -> bool:
        with self._lock:
            if time.time() - self._last_refresh > _PROCESSED_CACHE_TTL:
                self._paths = db.get_processed_paths(self._config_id)
                self._last_refresh = time.time()
            return path in self._paths

    def add(self, path: str) -> None:
        """Mark a path as processed locally (avoids waiting for TTL refresh)."""
        with self._lock:
            self._paths.add(path)


# ── Watcher Daemon ────────────────────────────────────────────────────────


class WatcherDaemon:
    def __init__(self) -> None:
        self._observer: Observer | None = None
        self._lock = threading.Lock()

        # config_id -> Handler
        self.handlers: dict[int, "ConfigHandler"] = {}

        self.running = False

    def start(self) -> None:
        if self.running:
            return

        db.init_db()
        self.running = True

        self._observer = Observer()

        # Sync configs (adds watches for enabled configs)
        self.sync_configs()

        self._observer.start()
        logger.info("Watcher daemon started.")

        # Background thread for config polling, debounce processing, batching
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
        logger.info("Watcher daemon stopped.")

    def sync_configs(self) -> None:
        """Reconcile running watchers with DB configs.

        BUG 6 fix: only tear down + recreate a handler if its config
        actually changed (watch_path, recursive, enabled, etc.).
        """
        with self._lock:
            configs = db.get_all_configs()
            active_map = {c.id: c for c in configs if c.enabled}

            # Remove handlers for disabled / deleted configs
            for cid in list(self.handlers.keys()):
                if cid not in active_map:
                    self._remove_watch(cid)

            # Add new or update changed
            for config in active_map.values():
                existing = self.handlers.get(config.id)
                if existing is None:
                    self._add_watch(config)
                elif _config_changed(existing.config, config):
                    self._remove_watch(config.id)
                    self._add_watch(config)
                # else: config unchanged — leave handler running

    def _add_watch(self, config: db.WatcherConfig) -> None:
        path = Path(config.watch_path).resolve()
        if not path.exists() or not path.is_dir():
            logger.warning("Watcher path %s does not exist, disabling config %d", path, config.id)
            db.update_config(config.id, enabled=False)
            return

        handler = ConfigHandler(config)
        try:
            watch = self._observer.schedule(handler, str(path), recursive=config.recursive)
            handler.watch = watch
            self.handlers[config.id] = handler
            logger.info("Started watching %s (config %d)", path, config.id)

            # Startup reconciliation — pick up files added while we were offline
            handler.reconcile()
        except Exception:
            logger.exception("Failed to schedule watch for %s", path)

    def _remove_watch(self, config_id: int) -> None:
        handler = self.handlers.pop(config_id, None)
        if handler and handler.watch and self._observer:
            try:
                self._observer.unschedule(handler.watch)
            except Exception:
                pass  # watch may have already been removed
            logger.info("Stopped watching config %d", config_id)

    def _monitor_loop(self) -> None:
        last_sync = time.time()
        while self.running:
            time.sleep(1.0)

            now = time.time()
            if now - last_sync > 30:
                try:
                    self.sync_configs()
                except Exception:
                    logger.exception("Error syncing watcher configs")
                last_sync = now

            # Process debounce queues (must hold lock to iterate handlers safely)
            with self._lock:
                for handler in self.handlers.values():
                    try:
                        handler.process_queues()
                    except Exception:
                        logger.exception("Error processing queues for config %d", handler.config.id)


def _config_changed(old: db.WatcherConfig, new: db.WatcherConfig) -> bool:
    """Return True if the config changed in a way that requires re-scheduling."""
    return (
        old.watch_path != new.watch_path
        or old.recursive != new.recursive
        or old.stability_window_seconds != new.stability_window_seconds
        or old.ignore_patterns != new.ignore_patterns
        or old.pipeline != new.pipeline
    )


# ── Per-config filesystem event handler ───────────────────────────────────


class ConfigHandler(FileSystemEventHandler):
    def __init__(self, config: db.WatcherConfig) -> None:
        self.config = config
        self.watch = None
        self._lock = threading.Lock()

        # file_path -> debounce state dict
        self.pending_files: dict[str, dict[str, Any]] = {}

        # file_path -> event_id (files that passed debounce, waiting to be batched)
        self.stable_files: dict[str, int] = {}
        self.last_stable_time = 0.0

        # Cached set of already-processed paths (BUG 3 fix)
        self._processed = _ProcessedCache(config.id)

    def _is_ignored(self, file_path: str) -> bool:
        name = Path(file_path).name

        # Always ignore transient / OS files
        if name.startswith(".") or name.endswith((".tmp", ".part", ".crdownload")):
            return True
        if name in (".DS_Store", "Thumbs.db"):
            return True

        for pattern in self.config.ignore_patterns:
            if fnmatch(name, pattern):
                return True

        return False

    # ── Watchdog callbacks (called on the observer thread) ────────────

    def on_created(self, event: Any) -> None:
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_moved(self, event: Any) -> None:
        if not event.is_directory:
            self._enqueue(event.dest_path)

    def _enqueue(self, file_path: str) -> None:
        if self._is_ignored(file_path):
            return

        with self._lock:
            if file_path in self.pending_files or file_path in self.stable_files:
                return

            if self._processed.contains(file_path):
                return

            self.pending_files[file_path] = {
                "first_seen": time.time(),
                "last_size": -1,
                "last_mtime": -1.0,
                "last_check": 0.0,
                "unchanged_count": 0,
            }
            logger.debug("Queued for debounce: %s", file_path)

    # ── Startup reconciliation ────────────────────────────────────────

    def reconcile(self) -> None:
        """Scan the directory for files missed while the daemon was down."""
        root = Path(self.config.watch_path).resolve()

        def _scan(d: Path) -> None:
            try:
                for entry in d.iterdir():
                    if entry.is_file():
                        self._enqueue(str(entry))
                    elif entry.is_dir() and self.config.recursive:
                        _scan(entry)
            except PermissionError:
                logger.warning("Permission denied scanning %s", d)
            except Exception:
                logger.exception("Error scanning %s", d)

        _scan(root)

    # ── Debounce + batch processing (called every ~1s from monitor loop)

    def process_queues(self) -> None:
        now = time.time()

        with self._lock:
            # 1. Debounce: check if pending files have stabilised
            expired = []
            newly_stable = []

            for fpath, state in self.pending_files.items():
                # Hard timeout — give up after 5 minutes
                if now - state["first_seen"] > 300:
                    expired.append(fpath)
                    continue

                # Only stat once per second
                if now - state["last_check"] < 1.0:
                    continue

                try:
                    st = os.stat(fpath)
                    size = st.st_size
                    mtime = st.st_mtime

                    if size == state["last_size"] and mtime == state["last_mtime"]:
                        state["unchanged_count"] += 1
                    else:
                        state["unchanged_count"] = 0

                    state["last_size"] = size
                    state["last_mtime"] = mtime
                    state["last_check"] = now

                    if state["unchanged_count"] >= self.config.stability_window_seconds:
                        newly_stable.append(fpath)

                except FileNotFoundError:
                    expired.append(fpath)
                except OSError as exc:
                    logger.warning("Cannot stat %s: %s", fpath, exc)

            # Clean up expired
            for fpath in expired:
                del self.pending_files[fpath]

            # Promote stable files
            for fpath in newly_stable:
                del self.pending_files[fpath]
                event_id = db.add_event(self.config.id, fpath, status="stabilized")
                self.stable_files[fpath] = event_id
                self.last_stable_time = now
                logger.info("File stable: %s", fpath)

            # 2. Batching: flush when 3 seconds have passed since last stable file
            if self.stable_files and (now - self.last_stable_time > 3.0):
                self._flush_batch()

    def _flush_batch(self) -> None:
        files = list(self.stable_files.keys())
        event_ids = list(self.stable_files.values())
        self.stable_files.clear()

        for eid in event_ids:
            db.update_event(eid, status="enqueued")

        logger.info("Flushing batch of %d files for config %d", len(files), self.config.id)

        # Lazy import to break circular dependency (BUG 2 fix)
        from src.web_app import jobs

        job_id = jobs.submit(
            "watcher_pipeline",
            _run_watcher_pipeline_task,
            self.config.id,
            files,
            event_ids,
        )

        for eid in event_ids:
            db.update_event(eid, status="enqueued", triggered_job_id=job_id)

        # Mark files as processed in the local cache
        for fpath in files:
            self._processed.add(fpath)


# ── Pipeline meta-task ────────────────────────────────────────────────────


def _run_watcher_pipeline_task(
    progress,
    config_id: int,
    target_files: list[str],
    event_ids: list[int],
) -> dict[str, Any]:
    """Meta-job that runs each pipeline step on the batch of target files."""

    config = db.get_config(config_id)
    if not config:
        return {"error": "Config deleted"}

    pipeline = [s for s in config.pipeline if s.get("enabled", True)]
    total_steps = len(pipeline)
    if total_steps == 0:
        for eid in event_ids:
            db.update_event(eid, status="completed")
        return {"error": "Empty pipeline"}

    for eid in event_ids:
        db.update_event(eid, status="running")

    progress(5, f"Starting pipeline with {total_steps} steps")

    step_results: dict[str, str] = {}

    for i, step in enumerate(pipeline):
        step_type = step.get("job_type", "unknown")
        pct = 10 + int((i / total_steps) * 80)
        progress(pct, f"Running: {step_type}")

        try:
            if step_type == "classify":
                _run_classify_step(config, target_files)
                step_results[step_type] = "ok"

            elif step_type == "organize-by-date":
                _run_organize_step(config, step, target_files)
                step_results[step_type] = "ok"

            elif step_type == "dedupe":
                _run_dedupe_step(config, target_files)
                step_results[step_type] = "ok"

            elif step_type == "cloud_sync":
                _run_cloud_sync_step(config, step, target_files)
                step_results[step_type] = "ok"

            else:
                logger.warning("Unknown pipeline step type: %s", step_type)
                step_results[step_type] = "skipped_unknown"

        except Exception:
            logger.exception("Pipeline step '%s' failed", step_type)
            step_results[step_type] = "failed"
            # Graceful degradation — continue to next step

    # Mark events as completed
    for eid in event_ids:
        db.update_event(eid, status="completed")

    return {"status": "success", "files_processed": len(target_files), "steps": step_results}


# ── Individual pipeline step implementations ──────────────────────────────


def _run_classify_step(config: db.WatcherConfig, target_files: list[str]) -> None:
    """Run the classify pipeline on the target files."""
    from src.classify.pipeline import run_classify_pipeline
    from src.classify.db import get_run_config

    # Use the saved classify wizard config (BUG 12 fix).
    # Fall back to a safe default if no wizard config has been saved.
    wizard_config = get_run_config("latest") or {
        "enabled_categories": ["other"],
        "confidence_threshold": 0.5,
        "face_sensitivity": "balanced",
    }

    run_classify_pipeline(
        config.watch_path,
        f"watcher_{config.id}_{int(time.time())}",
        wizard_config,
        lambda _p, _m: None,
        target_files=target_files,
    )


def _run_organize_step(
    config: db.WatcherConfig,
    step: dict[str, Any],
    target_files: list[str],
) -> None:
    """Run the organiser on the target files."""
    from src.organiser import organise_files

    organise_files(
        config.watch_path,
        step.get("destination_dir", config.watch_path),
        operation=step.get("operation", "move"),
        target_files=target_files,
    )


def _run_dedupe_step(config: db.WatcherConfig, target_files: list[str]) -> None:
    """Scan the watch directory for duplicates of the target files.

    As noted in the spec, deduplication must scan the entire destination
    to catch duplicates of existing files, not just the new batch.
    """
    from src.duplicate_handler import scan_for_duplicates_with_progress
    from src.config import get_threshold

    threshold = get_threshold()
    scan_for_duplicates_with_progress(
        config.watch_path,
        threshold,
        lambda _p, _m: None,
    )


def _run_cloud_sync_step(
    config: db.WatcherConfig,
    step: dict[str, Any],
    target_files: list[str],
) -> None:
    """Trigger a cloud sync for the target files."""
    from src.cloud.sync_pipeline import run_sync
    from src.cloud.manifest import create_sync_run, get_cloud_account, list_cloud_accounts

    # Find the account to sync to — use the one specified in the step,
    # or fall back to the first connected account.
    account_id = step.get("account_id")
    if not account_id:
        accounts = list_cloud_accounts()
        if not accounts:
            logger.warning("No cloud accounts configured — skipping cloud_sync step")
            return
        account_id = accounts[0]["id"]

    sync_config = {
        "source_dir": config.watch_path,
        "sync_type": "incremental",
        "remote_path": step.get("remote_path", "Clean-Backup"),
        "folder_scheme": step.get("folder_scheme", "flat"),
    }

    run_id = create_sync_run(account_id, sync_config)
    run_sync(run_id, progress_cb=None, target_files=target_files)


# ── Global singleton ──────────────────────────────────────────────────────

daemon = WatcherDaemon()
