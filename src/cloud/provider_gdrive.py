"""
Google Drive implementation of the CloudProvider interface.

Uses OAuth 2.0 installed-app flow with ``drive.file`` scope (least-privilege).
Migrated and improved from the original ``src/gdrive_sync.py``.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any

from src.cloud.provider_base import (
    AuthResult,
    CloudProvider,
    RemoteFileInfo,
    UploadProgressCb,
    UploadResult,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
RESUMABLE_THRESHOLD = 8 * 1024 * 1024  # 8 MB

# MIME type lookup (carried over from original gdrive_sync.py)
_MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".bmp": "image/bmp", ".heic": "image/heic",
    ".webp": "image/webp", ".tiff": "image/tiff", ".raf": "image/x-fuji-raf",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska", ".webm": "video/webm", ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
}


def _mime(path: Path) -> str:
    return _MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class GoogleDriveProvider(CloudProvider):
    """Google Drive CloudProvider — uses ``googleapiclient``."""

    def __init__(self) -> None:
        self._service: Any = None
        self._folder_cache: dict[str, str] = {}   # "parent_id/name" → folder_id

    # ── Authentication ────────────────────────────────────────────────────

    def authenticate(self, credentials: dict) -> AuthResult:
        """
        *credentials* must contain either:
        - ``token_json``  : a serialised ``google.oauth2.credentials.Credentials``
        - ``client_config`` + ``token_json`` : for refresh

        Returns an ``AuthResult``.  On success the internal ``_service`` is ready.
        """
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            token_data = credentials.get("token_json")
            if not token_data:
                return AuthResult(success=False, error="No token data provided")

            creds = Credentials.from_authorized_user_info(token_data, SCOPES)

            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                logger.info("Refreshed Google Drive token")

            if not creds.valid:
                return AuthResult(success=False, error="Token invalid after refresh")

            self._service = build("drive", "v3", credentials=creds)

            # Grab user email for the account label
            about = self._service.about().get(fields="user(emailAddress)").execute()
            email = about.get("user", {}).get("emailAddress", "Google Drive")

            return AuthResult(
                success=True,
                account_label=email,
                extra={"token_json": _creds_to_dict(creds)},
            )
        except Exception as exc:
            logger.error("Google Drive auth failed: %s", exc)
            return AuthResult(success=False, error=str(exc))

    # ── Destination management ────────────────────────────────────────────

    def ensure_destination(self, path: str) -> None:
        """Walk-or-create the folder hierarchy under the user's Drive root."""
        parts = [p for p in path.strip("/").split("/") if p]
        parent_id = "root"
        for part in parts:
            parent_id = self._get_or_create_folder(part, parent_id)

    def _get_or_create_folder(self, name: str, parent_id: str) -> str:
        cache_key = f"{parent_id}/{name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        # Search for existing
        query = (
            f"name='{name}' and '{parent_id}' in parents and "
            f"mimeType='application/vnd.google-apps.folder' and trashed=false"
        )
        results = self._service.files().list(
            q=query, spaces="drive", fields="files(id)", pageSize=1,
        ).execute()
        files = results.get("files", [])

        if files:
            fid = files[0]["id"]
        else:
            meta = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            created = self._service.files().create(body=meta, fields="id").execute()
            fid = created["id"]
            logger.debug("Created Drive folder: %s", name)

        self._folder_cache[cache_key] = fid
        return fid

    def _resolve_folder_id(self, path: str) -> str:
        """Return the Drive folder-ID for a slash-delimited path."""
        parts = [p for p in path.strip("/").split("/") if p]
        parent_id = "root"
        for part in parts:
            parent_id = self._get_or_create_folder(part, parent_id)
        return parent_id

    # ── Listing ───────────────────────────────────────────────────────────

    def list_remote(self, path: str) -> list[RemoteFileInfo]:
        folder_id = self._resolve_folder_id(path)
        items: list[RemoteFileInfo] = []
        page_token = None

        while True:
            resp = self._service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                spaces="drive",
                fields="nextPageToken, files(id, name, size, modifiedTime, properties)",
                pageSize=100,
                pageToken=page_token,
            ).execute()

            for f in resp.get("files", []):
                props = f.get("properties", {})
                items.append(RemoteFileInfo(
                    remote_path=f["name"],
                    size_bytes=int(f.get("size", 0)),
                    content_hash=props.get("clean_backup_sha256", ""),
                    modified_at=f.get("modifiedTime", ""),
                    extra={"id": f["id"]},
                ))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return items

    # ── Upload ────────────────────────────────────────────────────────────

    def upload(
        self,
        local_path: str,
        remote_path: str,
        metadata: dict[str, str],
        progress_cb: UploadProgressCb | None = None,
    ) -> UploadResult:
        from googleapiclient.http import MediaFileUpload

        lp = Path(local_path)
        if not lp.exists():
            return UploadResult(success=False, error=f"File not found: {local_path}")

        file_size = lp.stat().st_size
        sha = _sha256(local_path)

        # Determine parent folder
        remote_dir = "/".join(remote_path.strip("/").split("/")[:-1])
        remote_name = remote_path.strip("/").split("/")[-1]
        parent_id = self._resolve_folder_id(remote_dir) if remote_dir else "root"

        file_meta: dict[str, Any] = {
            "name": remote_name,
            "parents": [parent_id],
            "properties": {"clean_backup_sha256": sha, **metadata},
        }

        resumable = file_size > RESUMABLE_THRESHOLD
        media = MediaFileUpload(
            local_path,
            mimetype=_mime(lp),
            resumable=resumable,
            chunksize=4 * 1024 * 1024 if resumable else -1,
        )

        try:
            if resumable:
                request = self._service.files().create(
                    body=file_meta, media_body=media, fields="id",
                )
                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status and progress_cb:
                        progress_cb(int(status.resumable_progress), file_size)
            else:
                response = self._service.files().create(
                    body=file_meta, media_body=media, fields="id",
                ).execute()
                if progress_cb:
                    progress_cb(file_size, file_size)

            return UploadResult(
                success=True,
                remote_path=remote_path,
                content_hash=sha,
                bytes_uploaded=file_size,
                extra={"id": response.get("id", "")},
            )

        except Exception as exc:
            logger.error("Drive upload failed for %s: %s", local_path, exc)
            return UploadResult(success=False, remote_path=remote_path, error=str(exc))

    # ── Delete (for undo) ─────────────────────────────────────────────────

    def delete(self, remote_path: str) -> None:
        """Delete a file by its remote_path.

        We store the Drive file-ID in the manifest's ``extra`` via
        UploadResult, but the pipeline calls ``delete(remote_path)``
        so we need to search by name + properties.
        """
        # remote_path format: "Clean-Backup/2024/01/Travel/IMG.jpg"
        parts = remote_path.strip("/").split("/")
        name = parts[-1]
        folder_path = "/".join(parts[:-1])

        try:
            folder_id = self._resolve_folder_id(folder_path) if folder_path else "root"
            query = f"name='{name}' and '{folder_id}' in parents and trashed=false"
            resp = self._service.files().list(
                q=query, spaces="drive", fields="files(id)", pageSize=1,
            ).execute()
            files = resp.get("files", [])
            if files:
                self._service.files().delete(fileId=files[0]["id"]).execute()
                logger.info("Deleted from Drive: %s", remote_path)
        except Exception as exc:
            logger.error("Drive delete failed for %s: %s", remote_path, exc)
            raise

    # ── Verification ──────────────────────────────────────────────────────

    def verify(self, remote_path: str, expected_hash: str) -> bool:
        parts = remote_path.strip("/").split("/")
        name = parts[-1]
        folder_path = "/".join(parts[:-1])

        try:
            folder_id = self._resolve_folder_id(folder_path) if folder_path else "root"
            query = f"name='{name}' and '{folder_id}' in parents and trashed=false"
            resp = self._service.files().list(
                q=query, spaces="drive", fields="files(id, properties)", pageSize=1,
            ).execute()
            files = resp.get("files", [])
            if not files:
                return False
            stored = files[0].get("properties", {}).get("clean_backup_sha256", "")
            return stored == expected_hash
        except Exception:
            return False


# ── OAuth helpers (used by Flask endpoints) ───────────────────────────────

def start_oauth_flow(redirect_uri: str) -> tuple[str, Any]:
    """
    Begin the OAuth flow.

    Returns ``(auth_url, flow)`` — the caller must persist *flow* in
    the session/state so the callback can finish it.
    """
    from google_auth_oauthlib.flow import Flow

    client_config_path = Path("credentials.json")
    if not client_config_path.exists():
        raise FileNotFoundError(
            "credentials.json not found. Download OAuth 2.0 credentials "
            "from Google Cloud Console and place in the project root."
        )

    flow = Flow.from_client_secrets_file(
        str(client_config_path),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url, flow


def finish_oauth_flow(flow: Any, auth_response_url: str) -> dict:
    """
    Complete the OAuth flow after the user has authorised.

    Returns a dict suitable for ``credential_store.store()``.
    """
    flow.fetch_token(authorization_response=auth_response_url)
    creds = flow.credentials
    return _creds_to_dict(creds)


def _creds_to_dict(creds) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }


def revoke_token(token_json: dict) -> bool:
    """Attempt to revoke a Google OAuth token. Returns True on success."""
    import requests
    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": token_json.get("token", "")},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("Token revocation failed: %s", exc)
        return False
