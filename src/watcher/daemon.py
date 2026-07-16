"""
Daemon to monitor folders using watchdog and enqueue jobs.
"""
import time
import threading
import logging
from pathlib import Path
from fnmatch import fnmatch
from typing import Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent

from src.watcher import db
from src.web_app import jobs

logger = logging.getLogger(__name__)

class WatcherDaemon:
    def __init__(self) -> None:
        self.observer = Observer()
        self._lock = threading.Lock()
        
        # config_id -> Handler
        self.handlers: dict[int, "ConfigHandler"] = {}
        
        self.running = False

    def start(self) -> None:
        if self.running:
            return
            
        db.init_db()
        self.running = True
        
        # Sync configs
        self.sync_configs()
        
        self.observer.start()
        logger.info("Watcher daemon started.")

        # Background thread to check for config updates and polling fallbacks
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self.observer.stop()
        self.observer.join()
        logger.info("Watcher daemon stopped.")

    def sync_configs(self) -> None:
        with self._lock:
            configs = db.get_all_configs()
            active_ids = {c.id for c in configs if c.enabled}
            
            # Remove disabled/deleted
            for cid in list(self.handlers.keys()):
                if cid not in active_ids:
                    self._remove_watch(cid)
                    
            # Add/Update active
            for config in configs:
                if config.enabled:
                    if config.id not in self.handlers:
                        self._add_watch(config)
                    else:
                        # For simplicity, if config changed, we just recreate the watch
                        # A robust version would check if watch_path changed
                        self._remove_watch(config.id)
                        self._add_watch(config)

    def _add_watch(self, config: db.WatcherConfig) -> None:
        path = Path(config.watch_path).resolve()
        if not path.exists() or not path.is_dir():
            logger.warning(f"Watcher path {path} does not exist. Disabling watcher {config.id}.")
            db.update_config(config.id, enabled=False)
            return

        handler = ConfigHandler(config)
        try:
            watch = self.observer.schedule(handler, str(path), recursive=config.recursive)
            handler.watch = watch
            self.handlers[config.id] = handler
            logger.info(f"Started watching {path} for config {config.id}")
            
            # Startup reconciliation
            handler.reconcile()
        except Exception as e:
            logger.error(f"Failed to schedule watch for {path}: {e}")

    def _remove_watch(self, config_id: int) -> None:
        handler = self.handlers.pop(config_id, None)
        if handler and handler.watch:
            self.observer.unschedule(handler.watch)
            handler.stop()
            logger.info(f"Stopped watching for config {config_id}")

    def _monitor_loop(self) -> None:
        last_sync = time.time()
        while self.running:
            time.sleep(1.0)
            
            now = time.time()
            if now - last_sync > 30: # Sync configs every 30s
                self.sync_configs()
                last_sync = now
                
            # Process batches and debouncing for each handler
            with self._lock:
                for handler in self.handlers.values():
                    handler.process_queues()


class ConfigHandler(FileSystemEventHandler):
    def __init__(self, config: db.WatcherConfig) -> None:
        self.config = config
        self.watch = None
        self._lock = threading.Lock()
        
        # file_path -> (first_seen_time, last_size, last_mtime, last_check_time, unchanged_count)
        self.pending_files: dict[str, dict[str, Any]] = {}
        
        # file_path -> event_id
        self.stable_files: dict[str, int] = {}
        self.last_stable_time = 0.0

    def stop(self) -> None:
        pass
        
    def _is_ignored(self, file_path: str) -> bool:
        name = Path(file_path).name
        
        # Hardcoded transient ignore
        if name.startswith(".") or name.endswith(".tmp") or name.endswith(".part") or name.endswith(".crdownload"):
            return True
        if name in (".DS_Store", "Thumbs.db"):
            return True
            
        for pattern in self.config.ignore_patterns:
            if fnmatch(name, pattern):
                return True
                
        return False

    def on_created(self, event: Any) -> None:
        if not event.is_directory:
            self.add_file(event.src_path)

    def on_moved(self, event: Any) -> None:
        if not event.is_directory:
            self.add_file(event.dest_path)
            
    def add_file(self, file_path: str) -> None:
        if self._is_ignored(file_path):
            return
            
        with self._lock:
            if file_path not in self.pending_files and file_path not in self.stable_files:
                # Check if it was already processed
                processed = db.get_processed_paths(self.config.id)
                if file_path in processed:
                    return
                    
                self.pending_files[file_path] = {
                    "first_seen": time.time(),
                    "last_size": -1,
                    "last_mtime": -1,
                    "last_check": 0,
                    "unchanged_count": 0,
                }
                logger.debug(f"File added to debounce queue: {file_path}")

    def reconcile(self) -> None:
        """Scan directory on startup for missed files."""
        path = Path(self.config.watch_path).resolve()
        processed = db.get_processed_paths(self.config.id)
        
        def scan(d: Path) -> None:
            try:
                for p in d.iterdir():
                    if p.is_file():
                        sp = str(p)
                        if sp not in processed:
                            self.add_file(sp)
                    elif p.is_dir() and self.config.recursive:
                        scan(p)
            except Exception as e:
                logger.warning(f"Error scanning {d}: {e}")
                
        scan(path)

    def process_queues(self) -> None:
        now = time.time()
        
        with self._lock:
            # 1. Debounce checking
            stuck_files = []
            stable_this_tick = []
            
            for fpath, state in self.pending_files.items():
                # Check max wait (5 mins)
                if now - state["first_seen"] > 300:
                    stuck_files.append(fpath)
                    continue
                    
                if now - state["last_check"] >= 1.0:
                    try:
                        stat = os.stat(fpath)
                        size = stat.st_size
                        mtime = stat.st_mtime
                        
                        if size == state["last_size"] and mtime == state["last_mtime"]:
                            state["unchanged_count"] += 1
                        else:
                            state["unchanged_count"] = 0
                            
                        state["last_size"] = size
                        state["last_mtime"] = mtime
                        state["last_check"] = now
                        
                        # Reached stability window
                        if state["unchanged_count"] >= self.config.stability_window_seconds:
                            stable_this_tick.append(fpath)
                    except FileNotFoundError:
                        # File was deleted before it became stable
                        stuck_files.append(fpath)
                        
            for fpath in stuck_files:
                del self.pending_files[fpath]
                
            for fpath in stable_this_tick:
                del self.pending_files[fpath]
                # Insert into DB
                event_id = db.add_event(self.config.id, fpath, status="stabilized")
                self.stable_files[fpath] = event_id
                self.last_stable_time = now
                logger.info(f"File stable: {fpath}")

            # 2. Batching (3s rolling window since last stable file)
            if self.stable_files and (now - self.last_stable_time > 3.0):
                self._flush_batch()
                
    def _flush_batch(self) -> None:
        files = list(self.stable_files.keys())
        event_ids = list(self.stable_files.values())
        self.stable_files.clear()
        
        for eid in event_ids:
            db.update_event(eid, status="enqueued")
            
        logger.info(f"Flushing batch of {len(files)} files for config {self.config.id}")
        
        # Submit the pipeline job
        job_id = jobs.submit("watcher_pipeline", _run_watcher_pipeline_task, self.config.id, files, event_ids)
        
        for eid in event_ids:
            db.update_event(eid, status="enqueued", triggered_job_id=job_id)


def _run_watcher_pipeline_task(progress, config_id: int, target_files: list[str], event_ids: list[int]) -> dict[str, Any]:
    """Meta-job that orchestrates pipeline execution."""
    from src.web_app import _classify_task, _organize_task
    # TODO: Import cloud sync task and implement logic
    
    config = db.get_config(config_id)
    if not config:
        return {"error": "Config deleted"}
        
    total_steps = len(config.pipeline)
    if total_steps == 0:
        return {"error": "Empty pipeline"}
        
    for eid in event_ids:
        db.update_event(eid, status="running")
        
    progress(5, f"Starting pipeline with {total_steps} steps")
    
    # ── Pipeline Execution Logic ──
    # Note: We will implement the actual task wrapping in the next phase 
    # to keep files isolated. For now we outline the execution.
    
    for i, step in enumerate(config.pipeline):
        if not step.get("enabled"):
            continue
            
        step_type = step.get("job_type")
        progress(10 + int((i/total_steps)*80), f"Running {step_type}")
        
        try:
            if step_type == "classify":
                from src.classify.pipeline import run_classify_pipeline
                from src.config import load_config
                wizard_config = load_config()
                # Run classify on specific files
                run_classify_pipeline(config.watch_path, "watcher_run", wizard_config, lambda p, m: None, target_files=target_files)
            elif step_type == "organize-by-date":
                from src.organiser import organise_files
                organise_files(
                    config.watch_path,
                    step.get("destination_dir", config.watch_path),
                    operation=step.get("operation", "move"),
                    target_files=target_files
                )
            # Add dedupe and cloud sync here...
        except Exception as e:
            logger.exception(f"Pipeline step {step_type} failed: {e}")
            # Do not halt pipeline! Graceful degradation.
            
    # Mark complete
    for eid in event_ids:
        db.update_event(eid, status="completed")
        
    return {"status": "success", "files_processed": len(target_files)}

# Global daemon instance
daemon = WatcherDaemon()
