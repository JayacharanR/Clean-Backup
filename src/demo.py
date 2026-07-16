"""
Demo mode enforcement for Clean-Backup.

When DEMO_MODE=true is set in the environment, all destructive/mutating
endpoints return a 403 with a friendly message instead of executing.
Read-only and DB-only endpoints work normally so the UI feels alive.

Usage in route handlers::

    from src.demo import demo_guard

    @app.route("/api/some/destructive", methods=["POST"])
    def do_something():
        blocked = demo_guard()
        if blocked:
            return blocked
        # ... normal logic ...
"""

from __future__ import annotations

import os
from flask import jsonify


def is_demo_mode() -> bool:
    """Return True when the server is running in read-only demo mode."""
    return os.environ.get("DEMO_MODE", "").lower() in ("true", "1", "yes")


def demo_guard():
    """Return a 403 JSON response if demo mode is active, else None.

    Intended to be called at the top of any mutating endpoint::

        blocked = demo_guard()
        if blocked:
            return blocked
    """
    if not is_demo_mode():
        return None

    return jsonify({
        "ok": False,
        "demo": True,
        "error": (
            "This action is disabled in the read-only demo. "
            "Clone the repo to run Clean-Backup for real: "
            "https://github.com/JayacharanR/Clean-Backup"
        ),
    }), 403
