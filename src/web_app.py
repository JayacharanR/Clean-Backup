from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, request, send_file, send_from_directory
from PIL import Image

from src.compressor import compress_files, get_compression_settings
from src.config import get_threshold, load_config, save_config
from src.duplicate_handler import scan_for_duplicates_with_progress
from src.logger import logger
from src.organiser import organise_files
from src.phash import get_backend
from src.undo_manager import undo_manager
from src.demo import demo_guard, is_demo_mode

# Classification module
from src.classify.db import (
    init_db,
    get_categories,
    get_classification_summary,
    get_review_queue,
    get_run_config,
    get_people,
    get_unidentified_faces,
    save_run_config,
    update_category,
    create_person,
    update_person,
    delete_person,
    merge_people,
    assign_face_to_person,
    resolve_review,
    purge_face_data,
)
from src.classify.pipeline import run_classify_pipeline
from src.classify.stage_face_recognize import cluster_unidentified_faces

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    # HEIF previews will be unavailable if pillow-heif is missing.
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = PROJECT_ROOT / "web" / "dist"
TRASH_ROOT = PROJECT_ROOT / "logs" / "web_trash"

app = Flask(__name__, static_folder=str(WEB_DIST), static_url_path="")

# Initialise classification database (creates tables + seeds categories)
try:
    init_db()
except Exception as exc:
    logger.warning("Classification DB init deferred: %s", exc)

FACE_CACHE_DIR = PROJECT_ROOT / "logs" / "face_cache"


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str
    progress: int
    message: str
    created_at: float
    updated_at: float
    result: dict[str, Any] | None = None
    error: str | None = None


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}

    def submit(self, kind: str, task_fn: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()

        with self._lock:
            self._jobs[job_id] = JobRecord(
                id=job_id,
                kind=kind,
                status="queued",
                progress=0,
                message="Queued",
                created_at=now,
                updated_at=now,
            )

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, task_fn, args, kwargs),
            daemon=True,
        )
        thread.start()
        return job_id

    def _run_job(
        self,
        job_id: str,
        task_fn: Callable[..., dict[str, Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        self.update(job_id, status="running", progress=5, message="Starting")

        def progress_cb(progress: int, message: str) -> None:
            progress = max(0, min(100, int(progress)))
            self.update(job_id, progress=progress, message=message)

        try:
            result = task_fn(progress_cb, *args, **kwargs)
            self.update(
                job_id,
                status="completed",
                progress=100,
                message="Completed",
                result=result,
            )
        except Exception as exc:
            logger.exception("Job failed: %s", exc)
            self.update(
                job_id,
                status="failed",
                message="Failed",
                error=str(exc),
            )

    def update(self, job_id: str, **patch: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in patch.items():
                setattr(job, key, value)
            job.updated_at = time.time()

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)


jobs = JobManager()
_allowed_roots: set[Path] = set()
_allowed_roots_lock = threading.Lock()


def _add_allowed_root(root: Path) -> None:
    root = root.resolve()
    with _allowed_roots_lock:
        _allowed_roots.add(root)


def _is_allowed(path: Path) -> bool:
    path = path.resolve()
    with _allowed_roots_lock:
        roots = set(_allowed_roots)

    roots.add(TRASH_ROOT.resolve())
    for root in roots:
        if root == path or root in path.parents:
            return True
    return False


def _resolve_path(raw_path: str, must_exist: bool = True) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if must_exist and not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not _is_allowed(path):
        raise PermissionError("Path is outside allowed scan roots")
    return path


def _format_bytes(size_bytes: int) -> str:
    if size_bytes >= 1024**3:
        return f"{size_bytes / (1024**3):.2f} GB"
    if size_bytes >= 1024**2:
        return f"{size_bytes / (1024**2):.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes} B"


def _compress_stats_payload(stats: Any) -> dict[str, Any]:
    return {
        "total_files": stats.total_files,
        "images_compressed": stats.images_compressed,
        "videos_compressed": stats.videos_compressed,
        "skipped": stats.skipped,
        "errors": stats.errors,
        "original_size": stats.original_size,
        "compressed_size": stats.compressed_size,
        "space_saved": stats.space_saved,
        "compression_ratio": stats.compression_ratio,
    }


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def _image_payload(path: Path, is_best: bool) -> dict[str, Any]:
    size_bytes = path.stat().st_size
    width, height = _image_dimensions(path)

    return {
        "path": str(path),
        "name": path.name,
        "is_best": is_best,
        "size_bytes": size_bytes,
        "size_human": _format_bytes(size_bytes),
        "width": width,
        "height": height,
    }


def _scan_duplicates_task(progress: Callable[[int, str], None], source_dir: str, threshold: int) -> dict[str, Any]:
    source = Path(source_dir).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise ValueError(f"Source directory not found: {source}")

    _add_allowed_root(source)

    scan_started = time.perf_counter()
    scan_stats: dict[str, float | int] = {}
    groups = scan_for_duplicates_with_progress(
        str(source),
        threshold=threshold,
        progress_callback=progress,
        stats_out=scan_stats,
    )

    payload_started = time.perf_counter()
    progress(91, "Building response payload")
    payload_groups: list[dict[str, Any]] = []
    total_duplicates = 0
    recoverable = 0

    for idx, group in enumerate(groups):
        images: list[dict[str, Any]] = []
        for raw_path in group.paths:
            p = Path(raw_path)
            if not p.exists() or not p.is_file():
                continue

            is_best = p.resolve() == Path(group.best).resolve()
            image_item = _image_payload(p, is_best)
            images.append(image_item)
            if not is_best:
                total_duplicates += 1
                recoverable += image_item["size_bytes"]

        images.sort(key=lambda item: (not item["is_best"], item["name"].lower()))
        if images:
            payload_groups.append(
                {
                    "id": f"group_{idx + 1}",
                    "hash": group.hash,
                    "best_path": group.best,
                    "count": len(images),
                    "images": images,
                }
            )

        progress(91 + int(((idx + 1) / max(len(groups), 1)) * 7), "Preparing groups")

    progress(98, "Finishing")

    payload_time_seconds = time.perf_counter() - payload_started
    scan_time_seconds = time.perf_counter() - scan_started
    images_found = int(scan_stats.get("images_found_total", 0))
    average_images_per_group = (
        sum(group["count"] for group in payload_groups) / len(payload_groups)
        if payload_groups
        else 0.0
    )
    duplicate_ratio_pct = (total_duplicates / images_found) * 100 if images_found else 0.0

    return {
        "source_dir": str(source),
        "threshold": threshold,
        "backend": get_backend(),
        "duplicate_groups": len(payload_groups),
        "total_duplicates": total_duplicates,
        "space_recoverable_bytes": recoverable,
        "space_recoverable_human": _format_bytes(recoverable),
        "scan_time_seconds": round(scan_time_seconds, 2),
        "core_scan_seconds": round(float(scan_stats.get("core_scan_seconds", 0.0)), 2),
        "payload_time_seconds": round(payload_time_seconds, 2),
        "collection_time_seconds": round(float(scan_stats.get("collection_seconds", 0.0)), 2),
        "hash_time_seconds": round(float(scan_stats.get("hashing_seconds", 0.0)), 2),
        "group_time_seconds": round(float(scan_stats.get("grouping_seconds", 0.0)), 2),
        "files_seen": int(scan_stats.get("files_seen_total", 0)),
        "images_found": images_found,
        "hashes_fetched": int(scan_stats.get("hashes_fetched_total", 0)),
        "images_without_hash": int(scan_stats.get("images_without_hash_total", 0)),
        "hash_success_rate_pct": round(float(scan_stats.get("hash_success_rate_pct", 0.0)), 1),
        "avg_images_per_group": round(average_images_per_group, 2),
        "duplicate_ratio_pct": round(duplicate_ratio_pct, 1),
        "groups": payload_groups,
    }


def _organize_task(
    progress: Callable[[int, str], None],
    source_dir: str,
    destination_dir: str,
    operation: str,
    check_duplicates: bool,
    duplicate_threshold: int,
    check_name_duplicates: bool,
) -> dict[str, Any]:
    source = Path(source_dir).expanduser().resolve()
    destination = Path(destination_dir).expanduser().resolve()

    if not source.exists() or not source.is_dir():
        raise ValueError(f"Source directory not found: {source}")

    _add_allowed_root(source)
    _add_allowed_root(destination)

    progress(10, "Running organize workflow")

    def organize_progress(completed: int, total: int, result: dict[str, Any] | None) -> None:
        if total <= 0:
            progress(95, "No files found")
            return

        pct = 10 + int((completed / total) * 85)
        pct = max(10, min(95, pct))

        if result and result.get("source"):
            file_name = Path(result["source"]).name
            state = result.get("status", "processed")
            progress(pct, f"{state}: {file_name} ({completed}/{total})")
        else:
            progress(pct, f"Processed {completed}/{total} files")

    stats = organise_files(
        str(source),
        str(destination),
        operation=operation,
        check_duplicates=check_duplicates,
        duplicate_threshold=duplicate_threshold,
        check_name_duplicates=check_name_duplicates,
        progress_callback=organize_progress,
    )
    progress(96, "Preparing summary")

    return {
        "source_dir": str(source),
        "destination_dir": str(destination),
        "operation": operation,
        "check_duplicates": check_duplicates,
        "check_name_duplicates": check_name_duplicates,
        "duplicate_threshold": duplicate_threshold,
        "stats": {
            **stats,
            "folders_created": dict(stats.get("folders_created", {})),
        },
    }


def _compress_task(
    progress: Callable[[int, str], None],
    source_dir: str,
    output_dir: str,
    level: int,
    file_types: str,
) -> dict[str, Any]:
    source = Path(source_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()

    if not source.exists() or not source.is_dir():
        raise ValueError(f"Source directory not found: {source}")

    _add_allowed_root(source)
    _add_allowed_root(output)

    progress(10, "Running compression workflow")

    def compression_progress(completed: int, total: int, file_path: Any, success: bool, file_type: Any) -> None:
        if total <= 0:
            progress(95, "No files found")
            return

        pct = 10 + int((completed / total) * 85)
        pct = max(10, min(95, pct))
        file_name = Path(file_path).name if file_path else "n/a"
        outcome = "ok" if success else "error"
        kind = file_type or "file"
        progress(pct, f"{kind} {outcome}: {file_name} ({completed}/{total})")

    stats = compress_files(
        str(source),
        str(output),
        level=level,
        file_types=file_types,
        progress_callback=compression_progress,
    )
    progress(96, "Preparing summary")

    return {
        "source_dir": str(source),
        "output_dir": str(output),
        "level": level,
        "file_types": file_types,
        "settings": get_compression_settings(level),
        "stats": _compress_stats_payload(stats),
    }


def _trash_target_for(path: Path) -> Path:
    timestamp = int(time.time())
    relative = path.as_posix().replace("/", "__")
    return TRASH_ROOT / f"{timestamp}_{relative}"


def _run_picker_command(
    command: list[str],
    *,
    cancel_return_codes: set[int] | None = None,
    cancel_markers: tuple[str, ...] = (),
) -> tuple[str, Path | None]:
    cancel_codes = cancel_return_codes or {1}

    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return "missing", None
    except Exception as exc:
        logger.debug("Folder picker command failed to start: %s (%s)", command[0], exc)
        return "failed", None

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip().lower()

    if proc.returncode == 0:
        if not stdout:
            return "cancelled", None
        return "selected", Path(stdout).expanduser().resolve()

    if proc.returncode in cancel_codes:
        return "cancelled", None

    if any(marker in stderr for marker in cancel_markers):
        return "cancelled", None

    logger.debug(
        "Folder picker command returned non-cancel error: %s rc=%s stderr=%s",
        command[0],
        proc.returncode,
        proc.stderr,
    )
    return "failed", None


def _pick_folder_tkinter(start_dir: Path) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError("Tkinter is unavailable, so folder picker cannot open.") from exc

    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    selected = filedialog.askdirectory(initialdir=str(start_dir), title="Select folder")
    root.destroy()

    if not selected:
        return None

    return Path(selected).expanduser().resolve()


def _pick_folder_native(initial_dir: str | None = None) -> Path | None:
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("No desktop display found. Run the Web GUI from a local desktop session.")

    start_dir = Path.home()
    if initial_dir:
        candidate = Path(initial_dir).expanduser()
        if candidate.exists() and candidate.is_dir():
            start_dir = candidate.resolve()

    start_dir_str = str(start_dir)

    if os.name == "nt":
        escaped = start_dir_str.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = 'Select folder'; "
            f"$dialog.SelectedPath = '{escaped}'; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "Write-Output $dialog.SelectedPath }"
        )

        for shell in ("powershell", "pwsh"):
            status, selected = _run_picker_command(
                [shell, "-NoProfile", "-STA", "-Command", script],
                cancel_return_codes={0, 1},
            )
            if status == "selected":
                return selected
            if status == "cancelled":
                return None

        return _pick_folder_tkinter(start_dir)

    if os.name == "posix":
        desktop_env = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()

        # Prefer KDE picker when available, then GNOME/GTK picker.
        linux_commands: list[tuple[list[str], set[int], tuple[str, ...]]] = []
        if "kde" in desktop_env:
            linux_commands.append((["kdialog", "--getexistingdirectory", start_dir_str], {1}, ()))

        linux_commands.append(
            (["zenity", "--file-selection", "--directory", "--filename", f"{start_dir_str}/"], {1}, ())
        )
        linux_commands.append((["kdialog", "--getexistingdirectory", start_dir_str], {1}, ()))

        for command, cancel_codes, cancel_markers in linux_commands:
            status, selected = _run_picker_command(
                command,
                cancel_return_codes=cancel_codes,
                cancel_markers=cancel_markers,
            )
            if status == "selected":
                return selected
            if status == "cancelled":
                return None

        escaped = start_dir_str.replace("\\", "\\\\").replace('"', '\\"')
        applescript = (
            'POSIX path of (choose folder with prompt "Select folder" '
            f'default location POSIX file "{escaped}")'
        )
        status, selected = _run_picker_command(
            ["osascript", "-e", applescript],
            cancel_return_codes={1},
            cancel_markers=("-128", "user canceled"),
        )
        if status == "selected":
            return selected
        if status == "cancelled":
            return None

        return _pick_folder_tkinter(start_dir)

    return _pick_folder_tkinter(start_dir)


@app.after_request
def _after_request(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
    return response


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify(
        {
            "ok": True,
            "backend": get_backend(),
            "default_threshold": get_threshold(),
            "demo_mode": is_demo_mode(),
        }
    )


@app.route("/api/config", methods=["GET", "POST", "OPTIONS"])
def api_config():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    if request.method == "GET":
        return jsonify({"ok": True, "config": load_config()})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    threshold_raw = payload.get("phash_threshold")

    if threshold_raw is None:
        return jsonify({"ok": False, "error": "phash_threshold is required"}), 400

    try:
        threshold = int(threshold_raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "phash_threshold must be an integer"}), 400

    if threshold < 0:
        threshold = 0
    if threshold > 25:
        threshold = 25

    saved = save_config("phash_threshold", threshold)
    if not saved:
        return jsonify({"ok": False, "error": "Could not save configuration"}), 500

    return jsonify({"ok": True, "config": load_config()})


@app.route("/api/duplicates/scan", methods=["POST", "OPTIONS"])
def api_start_scan():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    source_dir = (payload.get("source_dir") or "").strip()
    try:
        threshold = int(payload.get("threshold", get_threshold()))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "threshold must be an integer"}), 400

    if not source_dir:
        return jsonify({"ok": False, "error": "source_dir is required"}), 400

    job_id = jobs.submit("duplicate_scan", _scan_duplicates_task, source_dir, threshold)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/organize/start", methods=["POST", "OPTIONS"])
def api_start_organize():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    source_dir = str(payload.get("source_dir", "")).strip()
    destination_dir = str(payload.get("destination_dir", "")).strip()
    operation = str(payload.get("operation", "move")).strip().lower()
    check_duplicates = bool(payload.get("check_duplicates", False))
    check_name_duplicates = bool(payload.get("check_name_duplicates", False))

    try:
        duplicate_threshold = int(payload.get("duplicate_threshold", get_threshold()))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "duplicate_threshold must be an integer"}), 400

    if operation not in {"move", "copy"}:
        return jsonify({"ok": False, "error": "operation must be move or copy"}), 400

    if not source_dir or not destination_dir:
        return jsonify({"ok": False, "error": "source_dir and destination_dir are required"}), 400

    job_id = jobs.submit(
        "organize",
        _organize_task,
        source_dir,
        destination_dir,
        operation,
        check_duplicates,
        duplicate_threshold,
        check_name_duplicates,
    )
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/compress/start", methods=["POST", "OPTIONS"])
def api_start_compress():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    source_dir = str(payload.get("source_dir", "")).strip()
    output_dir = str(payload.get("output_dir", "")).strip()
    file_types = str(payload.get("file_types", "both")).strip().lower()

    try:
        level = int(payload.get("level", 2))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "level must be an integer"}), 400

    if file_types not in {"images", "videos", "both"}:
        return jsonify({"ok": False, "error": "file_types must be images, videos, or both"}), 400

    if level not in {1, 2, 3}:
        return jsonify({"ok": False, "error": "level must be 1, 2, or 3"}), 400

    if not source_dir or not output_dir:
        return jsonify({"ok": False, "error": "source_dir and output_dir are required"}), 400

    job_id = jobs.submit("compress", _compress_task, source_dir, output_dir, level, file_types)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/jobs/<job_id>", methods=["GET"])
def api_job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job not found"}), 404

    return jsonify(
        {
            "ok": True,
            "job": {
                "id": job.id,
                "kind": job.kind,
                "status": job.status,
                "progress": job.progress,
                "message": job.message,
                "result": job.result,
                "error": job.error,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            },
        }
    )


@app.route("/api/folder/pick", methods=["POST", "OPTIONS"])
def api_pick_folder():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    initial_dir = str(payload.get("initial_dir", "")).strip() or None

    try:
        selected_path = _pick_folder_native(initial_dir)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if selected_path is None:
        return jsonify({"ok": True, "cancelled": True, "path": None})

    _add_allowed_root(selected_path)
    return jsonify({"ok": True, "cancelled": False, "path": str(selected_path)})


@app.route("/api/duplicates/delete", methods=["POST", "OPTIONS"])
def api_delete_selected():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    selected_images = payload.get("selected_images") or []
    mode = payload.get("mode", "trash")
    allow_best_delete = bool(payload.get("allow_best_delete", False))
    confirm_text = str(payload.get("confirm_text", "")).strip()

    if not isinstance(selected_images, list) or not selected_images:
        return jsonify({"ok": False, "error": "selected_images is required"}), 400

    if mode not in {"trash", "permanent"}:
        return jsonify({"ok": False, "error": "mode must be trash or permanent"}), 400

    if mode == "permanent" and confirm_text != "DELETE":
        return jsonify({"ok": False, "error": "Type DELETE to confirm permanent deletion"}), 400

    TRASH_ROOT.mkdir(parents=True, exist_ok=True)

    deleted_paths: list[str] = []
    errors: list[str] = []

    undo_manager.start_session()

    try:
        for item in selected_images:
            raw_path = str(item.get("path", "")).strip()
            is_best = bool(item.get("is_best", False))

            if not raw_path:
                errors.append("Missing path in selection")
                continue

            if is_best and not allow_best_delete:
                errors.append(f"Best image locked: {raw_path}")
                continue

            try:
                file_path = _resolve_path(raw_path, must_exist=True)
                if not file_path.is_file():
                    errors.append(f"Not a file: {file_path}")
                    continue

                if mode == "trash":
                    target = _trash_target_for(file_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    file_path.rename(target)
                    undo_manager.log_action("move", str(file_path), str(target))
                else:
                    file_path.unlink()

                deleted_paths.append(str(file_path))
            except Exception as exc:
                errors.append(str(exc))

        undo_manager.end_session()
    except Exception:
        undo_manager.end_session()
        raise

    return jsonify(
        {
            "ok": True,
            "mode": mode,
            "deleted_count": len(deleted_paths),
            "deleted_paths": deleted_paths,
            "errors": errors,
        }
    )


@app.route("/api/undo/sessions", methods=["GET"])
def api_undo_sessions():
    sessions = []
    for s in undo_manager.list_sessions():
        sessions.append({"id": s["id"], "path": str(s["path"]), "count": s["count"]})
    return jsonify({"ok": True, "sessions": sessions})


@app.route("/api/undo/revert", methods=["POST", "OPTIONS"])
def api_undo_revert():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    session_id = payload.get("session_id")

    sessions = undo_manager.list_sessions()
    if not sessions:
        return jsonify({"ok": False, "error": "No sessions found"}), 404

    target = sessions[0]
    if session_id:
        match = next((s for s in sessions if s["id"] == session_id), None)
        if not match:
            return jsonify({"ok": False, "error": "Session not found"}), 404
        target = match

    success = undo_manager.undo_session(target["path"])
    return jsonify({"ok": success, "session": {"id": target["id"], "count": target["count"]}})


@app.route("/api/image", methods=["GET"])
def api_image():
    raw_path = (request.args.get("path") or "").strip()
    variant = (request.args.get("variant") or "full").strip().lower()

    if not raw_path:
        return jsonify({"ok": False, "error": "path query parameter is required"}), 400

    try:
        image_path = _resolve_path(raw_path, must_exist=True)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if not image_path.is_file():
        return jsonify({"ok": False, "error": "Not a file"}), 400

    try:
        with Image.open(image_path) as img:
            out = img.copy()

            if variant == "thumb":
                out.thumbnail((360, 360), Image.Resampling.LANCZOS)
                quality = 88
            else:
                out.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                quality = 95

            if out.mode not in ("RGB", "L"):
                out = out.convert("RGB")

            buffer = io.BytesIO()
            out.save(buffer, format="JPEG", quality=quality, optimize=True)
            buffer.seek(0)

            return send_file(buffer, mimetype="image/jpeg")
    except Exception:
        # Fallback for files Pillow cannot decode through current codecs.
        return send_file(image_path)



# ── Classification endpoints ──────────────────────────────────────────────


def _classify_task(
    progress: Callable[[int, str], None],
    source_dir: str,
    run_id: str,
) -> dict[str, Any]:
    source = Path(source_dir).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise ValueError(f"Source directory not found: {source}")
    _add_allowed_root(source)

    config = get_run_config(run_id) or {}
    result = run_classify_pipeline(str(source), run_id, config, progress)
    return result


@app.route("/api/classify/config", methods=["POST", "OPTIONS"])
def api_classify_config():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    run_id = uuid.uuid4().hex
    save_run_config(run_id, payload)
    return jsonify({"ok": True, "run_id": run_id})


@app.route("/api/classify/start", methods=["POST", "OPTIONS"])
def api_classify_start():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    run_id = str(payload.get("run_id", "")).strip()
    source_dir = str(payload.get("source_dir", "")).strip()

    if not run_id:
        return jsonify({"ok": False, "error": "run_id is required"}), 400
    if not source_dir:
        return jsonify({"ok": False, "error": "source_dir is required"}), 400

    job_id = jobs.submit("classify", _classify_task, source_dir, run_id)
    return jsonify({"ok": True, "job_id": job_id, "run_id": run_id})


def _classify_apply_task(progress_cb, run_id, dest_dir, operation):
    from src.classify.apply_org import apply_classification
    try:
        return apply_classification(run_id, dest_dir, operation, progress_cb)
    except Exception as e:
        logger.error(f"Classification apply failed: {e}")
        return {"error": str(e)}


@app.route("/api/classify/apply", methods=["POST", "OPTIONS"])
def api_classify_apply():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    run_id = str(payload.get("run_id", "")).strip()
    dest_dir = str(payload.get("dest_dir", "")).strip()
    operation = str(payload.get("operation", "move")).strip().lower()

    if not run_id:
        return jsonify({"ok": False, "error": "run_id is required"}), 400
    if not dest_dir:
        return jsonify({"ok": False, "error": "dest_dir is required"}), 400
    if operation not in ("move", "copy"):
        return jsonify({"ok": False, "error": "operation must be move or copy"}), 400

    job_id = jobs.submit("classify_apply", _classify_apply_task, run_id, dest_dir, operation)
    return jsonify({"ok": True, "job_id": job_id})
@app.route("/api/classify/results/<run_id>", methods=["GET"])
def api_classify_results(run_id: str):
    summary = get_classification_summary(run_id)
    return jsonify({"ok": True, **summary})


@app.route("/api/categories", methods=["GET"])
def api_categories():
    cats = get_categories()
    return jsonify({"ok": True, "categories": cats})


@app.route("/api/categories/<int:cat_id>", methods=["PATCH", "OPTIONS"])
def api_update_category(cat_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    enabled = payload.get("enabled")
    priority = payload.get("priority")

    if enabled is not None:
        enabled = bool(enabled)
    if priority is not None:
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "priority must be an integer"}), 400

    success = update_category(cat_id, enabled=enabled, priority=priority)
    return jsonify({"ok": success, "categories": get_categories()})


# ── People management ─────────────────────────────────────────────────────


@app.route("/api/people", methods=["GET"])
def api_list_people():
    return jsonify({"ok": True, "people": get_people()})


@app.route("/api/people", methods=["POST", "OPTIONS"])
def api_create_person():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400

    cover_face_id = payload.get("cover_face_id")
    person_id = create_person(name, cover_face_id)
    return jsonify({"ok": True, "person_id": person_id})


@app.route("/api/people/<int:person_id>", methods=["PATCH", "OPTIONS"])
def api_update_person(person_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    merge_with = payload.get("merge_with")

    if merge_with is not None:
        try:
            merge_people(person_id, int(merge_with))
            return jsonify({"ok": True, "merged": True, "people": get_people()})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    if name is not None:
        update_person(person_id, str(name).strip())
    return jsonify({"ok": True, "people": get_people()})


@app.route("/api/people/<int:person_id>", methods=["DELETE", "OPTIONS"])
def api_delete_person(person_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    purge = bool(payload.get("purge_embeddings", False))
    delete_person(person_id, purge_embeddings=purge)
    return jsonify({"ok": True, "people": get_people()})


# ── Faces ──────────────────────────────────────────────────────────────────


@app.route("/api/faces/unidentified", methods=["GET"])
def api_unidentified_faces():
    faces = get_unidentified_faces()
    do_cluster = request.args.get("cluster", "false").lower() == "true"

    if do_cluster and faces:
        raw_clusters = cluster_unidentified_faces(faces)
        clusters = []
        for idx, cluster in enumerate(raw_clusters):
            clusters.append({
                "id": f"cluster_{idx}",
                "count": len(cluster),
                "faces": [
                    {
                        "id": f.get("id"),
                        "file_id": f.get("file_id"),
                        "path": f.get("path"),
                        "filename": f.get("filename"),
                        "bbox": f.get("bbox"),
                        "confidence": f.get("confidence"),
                    }
                    for f in cluster
                ],
            })
        return jsonify({"ok": True, "clusters": clusters, "total_faces": len(faces)})

    return jsonify({
        "ok": True,
        "faces": [
            {
                "id": f.get("id"),
                "file_id": f.get("file_id"),
                "path": f.get("path"),
                "filename": f.get("filename"),
                "bbox": f.get("bbox"),
                "confidence": f.get("confidence"),
            }
            for f in faces
        ],
    })


@app.route("/api/faces/<int:face_id>/assign", methods=["POST", "OPTIONS"])
def api_assign_face(face_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    person_id = payload.get("person_id")

    if person_id is None:
        return jsonify({"ok": False, "error": "person_id is required"}), 400

    try:
        assign_face_to_person(face_id, int(person_id))
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/faces/purge", methods=["POST", "OPTIONS"])
def api_purge_faces():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    confirm = str(payload.get("confirm", "")).strip()
    if confirm != "PURGE":
        return jsonify({"ok": False, "error": "Type PURGE to confirm"}), 400

    result = purge_face_data()

    # Also clear cached face crops
    if FACE_CACHE_DIR.exists():
        import shutil
        shutil.rmtree(FACE_CACHE_DIR, ignore_errors=True)

    return jsonify({"ok": True, **result})


@app.route("/api/face-crop", methods=["GET"])
def api_face_crop():
    face_id = request.args.get("id", "")
    if not face_id:
        return jsonify({"ok": False, "error": "id is required"}), 400

    crop_path = FACE_CACHE_DIR / f"face_{face_id}.jpg"
    if crop_path.exists():
        return send_file(crop_path, mimetype="image/jpeg")

    return jsonify({"ok": False, "error": "Face crop not found"}), 404


# ── Review queue ───────────────────────────────────────────────────────────


@app.route("/api/review-queue", methods=["GET"])
def api_review_queue():
    review_type = request.args.get("type")
    items = get_review_queue(review_type=review_type, resolved=False)
    return jsonify({"ok": True, "items": items})


@app.route("/api/review-queue/<int:review_id>/resolve", methods=["POST", "OPTIONS"])
def api_resolve_review(review_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    category_id = payload.get("category_id")
    if category_id is None:
        return jsonify({"ok": False, "error": "category_id is required"}), 400

    try:
        success = resolve_review(review_id, int(category_id))
        return jsonify({"ok": success})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


# ── Cloud Sync endpoints ───────────────────────────────────────────────────

# In-memory OAuth flow cache (keyed by a random state token)
_oauth_flows: dict[str, Any] = {}


@app.route("/api/cloud/accounts", methods=["GET"])
def api_cloud_accounts():
    from src.cloud.manifest import list_cloud_accounts
    return jsonify({"ok": True, "accounts": list_cloud_accounts()})


@app.route("/api/cloud/accounts/gdrive/connect", methods=["POST", "OPTIONS"])
def api_gdrive_connect():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    try:
        from src.cloud.provider_gdrive import start_oauth_flow
        # Build the redirect URI pointing back to our callback endpoint
        host_url = request.host_url.rstrip("/")
        redirect_uri = f"{host_url}/api/cloud/accounts/gdrive/callback"
        auth_url, flow = start_oauth_flow(redirect_uri)

        # Store flow in memory keyed by a state token
        state = uuid.uuid4().hex
        _oauth_flows[state] = flow
        return jsonify({"ok": True, "auth_url": f"{auth_url}&state={state}", "state": state})
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("OAuth start failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/cloud/accounts/gdrive/callback", methods=["GET"])
def api_gdrive_callback():
    """OAuth redirect handler — finishes the flow, stores credentials, creates account."""
    from src.cloud.provider_gdrive import finish_oauth_flow, GoogleDriveProvider
    from src.cloud import credential_store
    from src.cloud.manifest import create_cloud_account

    state = request.args.get("state", "")
    flow = _oauth_flows.pop(state, None)
    if not flow:
        return "Invalid OAuth state. Please try connecting again.", 400

    try:
        token_data = finish_oauth_flow(flow, request.url)

        # Get account label by authenticating
        provider = GoogleDriveProvider()
        auth = provider.authenticate({"token_json": token_data})
        label = auth.account_label or "Google Drive"

        # Store credentials securely
        cred_ref = f"gdrive_{uuid.uuid4().hex[:8]}"
        credential_store.store(cred_ref, token_data)

        # Create DB record
        create_cloud_account("gdrive", label, cred_ref)

        # Redirect back to the web UI
        return (
            "<html><body><h2>✅ Google Drive connected!</h2>"
            "<p>You can close this tab and return to Clean-Backup.</p>"
            "<script>window.close();</script></body></html>"
        )
    except Exception as exc:
        logger.error("OAuth callback failed: %s", exc)
        return f"<html><body><h2>❌ Connection failed</h2><p>{exc}</p></body></html>", 500


@app.route("/api/cloud/accounts/<int:account_id>", methods=["DELETE", "OPTIONS"])
def api_cloud_disconnect(account_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    from src.cloud import credential_store
    from src.cloud.manifest import get_cloud_account, delete_cloud_account

    account = get_cloud_account(account_id)
    if not account:
        return jsonify({"ok": False, "error": "Account not found"}), 404

    # Revoke token if Google Drive
    if account["provider"] == "gdrive":
        try:
            from src.cloud.provider_gdrive import revoke_token
            cred_data = credential_store.retrieve(account["credential_ref"])
            if cred_data:
                revoke_token(cred_data)
        except Exception:
            pass  # Best-effort revocation

    # Delete stored credentials
    credential_store.delete(account["credential_ref"])
    delete_cloud_account(account_id)
    return jsonify({"ok": True})


@app.route("/api/cloud/sync/config", methods=["POST", "OPTIONS"])
def api_cloud_sync_config():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    from src.cloud.manifest import create_sync_run

    payload = request.get_json(silent=True) or {}
    account_id = payload.get("account_id")
    if not account_id:
        return jsonify({"ok": False, "error": "account_id is required"}), 400

    run_id = create_sync_run(int(account_id), payload)
    return jsonify({"ok": True, "run_id": run_id})


def _cloud_sync_task(progress_cb, run_id):
    from src.cloud.sync_pipeline import run_sync
    try:
        return run_sync(run_id, progress_cb)
    except Exception as e:
        logger.error(f"Cloud sync failed: {e}")
        return {"error": str(e)}


@app.route("/api/cloud/sync/start", methods=["POST", "OPTIONS"])
def api_cloud_sync_start():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    run_id = payload.get("run_id")
    if not run_id:
        return jsonify({"ok": False, "error": "run_id is required"}), 400

    job_id = jobs.submit("cloud_sync", _cloud_sync_task, int(run_id))
    return jsonify({"ok": True, "job_id": job_id, "run_id": run_id})


def _cloud_undo_task(progress_cb, run_id):
    from src.cloud.sync_pipeline import undo_sync
    try:
        return undo_sync(run_id, progress_cb)
    except Exception as e:
        logger.error(f"Cloud sync undo failed: {e}")
        return {"error": str(e)}


@app.route("/api/cloud/sync/<int:run_id>/undo", methods=["POST", "OPTIONS"])
def api_cloud_sync_undo(run_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    job_id = jobs.submit("cloud_undo", _cloud_undo_task, run_id)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/cloud/sync/history", methods=["GET"])
def api_cloud_sync_history():
    from src.cloud.manifest import list_sync_runs, get_run_stats, get_latest_run_for_account
    runs = list_sync_runs()
    # Annotate each run with stats and whether undo is allowed
    result = []
    latest_per_account: dict[int, int] = {}
    for r in runs:
        aid = r["account_id"]
        if aid not in latest_per_account:
            latest = get_latest_run_for_account(aid)
            latest_per_account[aid] = latest["id"] if latest else -1

        entry = {**r, **get_run_stats(r["id"])}
        entry["can_undo"] = (
            r["id"] == latest_per_account[aid]
            and r["status"] in ("completed", "partial")
        )
        result.append(entry)
    return jsonify({"ok": True, "runs": result})


# ── Frontend catch-all ─────────────────────────────────────────────────────


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path: str):
    if WEB_DIST.exists():
        requested = WEB_DIST / path
        if path and requested.exists() and requested.is_file():
            return send_from_directory(WEB_DIST, path)

        index_file = WEB_DIST / "index.html"
        if index_file.exists():
            return send_from_directory(WEB_DIST, "index.html")

    return (
        "Web UI build not found. Run: cd web && npm install && npm run build",
        200,
    )


def start_web_gui(host: str = "0.0.0.0", port: int = None, auto_open: bool = True) -> None:
    if port is None:
        port = int(os.environ.get("CLEAN_BACKUP_PORT", 8080))
    # Note: host defaults to 0.0.0.0 to allow Docker binding
    
    # We display 127.0.0.1 in the terminal for clicking convenience
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{display_host}:{port}"
    if auto_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    print("\n--- Clean-Backup Web GUI ---")
    print(f"Starting server at: {url}")
    print("Press Ctrl+C to stop and return to CLI.")

    try:
        from src.watcher.api import watcher_bp
        from src.watcher.daemon import daemon
        app.register_blueprint(watcher_bp)
        daemon.start()
    except Exception as e:
        logger.error(f"Failed to start watcher daemon: {e}")

    # Demo mode: seed data and start auto-reset scheduler
    if is_demo_mode():
        try:
            from deploy.demo.seed_demo_db import seed
            seed()
            from deploy.demo.reset_demo import start_reset_scheduler
            start_reset_scheduler()
        except Exception as e:
            logger.warning(f"Demo seed/reset setup: {e}")

    app.run(host=host, port=port, debug=False, use_reloader=False)

    try:
        from src.watcher.daemon import daemon
        daemon.stop()
    except Exception:
        pass


if __name__ == "__main__":
    start_web_gui()
