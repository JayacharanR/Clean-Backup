"""
Abstract CloudProvider interface.

Every cloud backend (Google Drive, AWS S3, …) implements this interface
so that ``sync_pipeline.py`` never imports provider SDKs directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class AuthResult:
    """Returned by ``CloudProvider.authenticate``."""
    success: bool
    account_label: str = ""
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RemoteFileInfo:
    """One entry returned by ``CloudProvider.list_remote``."""
    remote_path: str
    size_bytes: int = 0
    content_hash: str = ""          # provider-specific or our custom SHA-256
    modified_at: str = ""           # ISO-8601 string
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class UploadResult:
    """Returned by ``CloudProvider.upload``."""
    success: bool
    remote_path: str = ""
    content_hash: str = ""
    bytes_uploaded: int = 0
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ── Progress callback type ────────────────────────────────────────────────

UploadProgressCb = Callable[[int, int], None]   # (bytes_sent, bytes_total)


# ── Abstract interface ────────────────────────────────────────────────────

class CloudProvider(ABC):
    """
    Minimal contract every cloud backend must satisfy.

    ``sync_pipeline.py`` calls *only* these methods — never provider SDKs.
    """

    @abstractmethod
    def authenticate(self, credentials: dict) -> AuthResult:
        """Validate stored credentials and establish a session."""
        ...

    @abstractmethod
    def ensure_destination(self, path: str) -> None:
        """Create the remote folder / bucket-prefix if it does not exist."""
        ...

    @abstractmethod
    def list_remote(self, path: str) -> list[RemoteFileInfo]:
        """List files at *path* (non-recursive) for incremental diffing."""
        ...

    @abstractmethod
    def upload(
        self,
        local_path: str,
        remote_path: str,
        metadata: dict[str, str],
        progress_cb: UploadProgressCb | None = None,
    ) -> UploadResult:
        """Upload a single file.  Must be resumable for large files."""
        ...

    @abstractmethod
    def delete(self, remote_path: str) -> None:
        """Delete a single remote object (used only by undo)."""
        ...

    @abstractmethod
    def verify(self, remote_path: str, expected_hash: str) -> bool:
        """Return ``True`` if the remote file matches *expected_hash*."""
        ...
