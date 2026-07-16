"""Flask blueprints for Watcher Daemon API."""

from flask import Blueprint, jsonify, request
from src.demo import demo_guard
from src.watcher import db
from src.watcher.daemon import daemon

watcher_bp = Blueprint("watcher", __name__, url_prefix="/api/watchers")


@watcher_bp.route("", methods=["GET", "OPTIONS"])
def get_watchers():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    configs = db.get_all_configs()
    events = db.get_events(limit=50)

    return jsonify({
        "ok": True,
        "watchers": [c.__dict__ for c in configs],
        "events": events,
    })


@watcher_bp.route("", methods=["POST", "OPTIONS"])
def create_watcher():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}

    watch_path = payload.get("watch_path")
    if not watch_path:
        return jsonify({"ok": False, "error": "watch_path is required"}), 400

    config_id = db.add_config(
        label=payload.get("label", "New Watcher"),
        watch_path=watch_path,
        recursive=payload.get("recursive", True),
        stability_window_seconds=payload.get("stability_window_seconds", 2),
        ignore_patterns=payload.get("ignore_patterns", []),
        pipeline=payload.get("pipeline", []),
        on_complete=payload.get("on_complete", "leave"),
        on_error=payload.get("on_error", "leave"),
        enabled=payload.get("enabled", True),
    )

    daemon.sync_configs()
    return jsonify({"ok": True, "id": config_id})


@watcher_bp.route("/<int:config_id>", methods=["PATCH", "OPTIONS"])
def update_watcher(config_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    payload = request.get_json(silent=True) or {}
    success = db.update_config(config_id, **payload)
    if not success:
        return jsonify({"ok": False, "error": "Watcher not found"}), 404

    daemon.sync_configs()
    return jsonify({"ok": True})


@watcher_bp.route("/<int:config_id>", methods=["DELETE", "OPTIONS"])
def delete_watcher(config_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    success = db.delete_config(config_id)
    if not success:
        return jsonify({"ok": False, "error": "Watcher not found"}), 404

    daemon.sync_configs()
    return jsonify({"ok": True})


@watcher_bp.route("/<int:config_id>/start", methods=["POST", "OPTIONS"])
def start_watcher(config_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    db.update_config(config_id, enabled=True)
    daemon.sync_configs()
    return jsonify({"ok": True})


@watcher_bp.route("/<int:config_id>/stop", methods=["POST", "OPTIONS"])
def stop_watcher(config_id: int):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    blocked = demo_guard()
    if blocked:
        return blocked

    db.update_config(config_id, enabled=False)
    daemon.sync_configs()
    return jsonify({"ok": True})


@watcher_bp.route("/<int:config_id>/events", methods=["GET"])
def get_watcher_events(config_id: int):
    events = [e for e in db.get_events(limit=100) if e["watcher_config_id"] == config_id]
    return jsonify({"ok": True, "events": events})
