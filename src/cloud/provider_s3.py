"""
AWS S3 implementation of the CloudProvider interface.

Stub implementation — full S3 support to be completed in a later phase.
Provides the skeleton so the interface is satisfied and the UI can show
"AWS S3 (coming soon)".
"""

from __future__ import annotations

import logging

from src.cloud.provider_base import (
    AuthResult,
    CloudProvider,
    RemoteFileInfo,
    UploadProgressCb,
    UploadResult,
)

logger = logging.getLogger(__name__)


class S3Provider(CloudProvider):
    """AWS S3 CloudProvider — stub for future implementation."""

    def authenticate(self, credentials: dict) -> AuthResult:
        # TODO: implement with boto3
        return AuthResult(success=False, error="S3 support coming soon")

    def ensure_destination(self, path: str) -> None:
        raise NotImplementedError("S3 support coming soon")

    def list_remote(self, path: str) -> list[RemoteFileInfo]:
        raise NotImplementedError("S3 support coming soon")

    def upload(
        self,
        local_path: str,
        remote_path: str,
        metadata: dict[str, str],
        progress_cb: UploadProgressCb | None = None,
    ) -> UploadResult:
        raise NotImplementedError("S3 support coming soon")

    def delete(self, remote_path: str) -> None:
        raise NotImplementedError("S3 support coming soon")

    def verify(self, remote_path: str, expected_hash: str) -> bool:
        raise NotImplementedError("S3 support coming soon")
