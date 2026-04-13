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
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify(
        {
            "ok": True,
            "backend": get_backend(),
            "default_threshold": get_threshold(),
        }
    )


@app.route("/api/config", methods=["GET", "POST", "OPTIONS"])
def api_config():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    if request.method == "GET":
        return jsonify({"ok": True, "config": load_config()})

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


def start_web_gui(host: str = "127.0.0.1", port: int = 5179, auto_open: bool = True) -> None:
    url = f"http://{host}:{port}"
    if auto_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    print("\n--- Clean-Backup Web GUI ---")
    print(f"Starting server at: {url}")
    print("Press Ctrl+C to stop and return to CLI.")

    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    start_web_gui()
