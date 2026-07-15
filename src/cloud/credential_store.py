"""
Secure credential storage for cloud provider tokens.

Primary backend : OS keyring (macOS Keychain / Windows Credential Locker /
                  Linux Secret Service) via the ``keyring`` library.
Fallback        : Fernet symmetric encryption with a locally generated key
                  stored at ``~/.clean-backup/secret.key`` (mode 0600).

Never stores credentials in plaintext config files or logs.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

_SERVICE_NAME = "clean-backup-cloud"
_env_config_dir = os.environ.get("CLEAN_BACKUP_CONFIG_DIR")
_KEY_DIR = Path(_env_config_dir) if _env_config_dir else Path.home() / ".clean-backup"
_KEY_FILE = _KEY_DIR / "secret.key"

# ── Detect available backend ──────────────────────────────────────────────

_USE_KEYRING = False
try:
    import keyring as _keyring

    # Probe: some Linux installs have keyring but no usable backend.
    _keyring.get_password(_SERVICE_NAME, "__probe__")
    _USE_KEYRING = True
except Exception:
    _USE_KEYRING = False


def _get_fernet():
    """Return a ``Fernet`` instance, creating the key file if needed."""
    from cryptography.fernet import Fernet

    _KEY_DIR.mkdir(parents=True, exist_ok=True)
    if not _KEY_FILE.exists():
        key = Fernet.generate_key()
        _KEY_FILE.write_bytes(key)
        os.chmod(str(_KEY_FILE), stat.S_IRUSR | stat.S_IWUSR)  # 0600
        logger.info("Generated new Fernet key at %s", _KEY_FILE)
    return Fernet(_KEY_FILE.read_bytes())


# ── Public API ────────────────────────────────────────────────────────────

def store(account_id: str, data: dict) -> None:
    """Persist *data* (JSON-serialisable dict) for *account_id*."""
    payload = json.dumps(data)
    if _USE_KEYRING:
        _keyring.set_password(_SERVICE_NAME, account_id, payload)
        logger.info("Stored credentials for %s via keyring", account_id)
    else:
        fernet = _get_fernet()
        encrypted = fernet.encrypt(payload.encode()).decode()
        cred_file = _KEY_DIR / f"{account_id}.enc"
        cred_file.write_text(encrypted)
        os.chmod(str(cred_file), stat.S_IRUSR | stat.S_IWUSR)
        logger.info("Stored credentials for %s via Fernet fallback", account_id)


def retrieve(account_id: str) -> dict | None:
    """Return the stored dict, or ``None`` if nothing is stored."""
    try:
        if _USE_KEYRING:
            payload = _keyring.get_password(_SERVICE_NAME, account_id)
            if payload:
                return json.loads(payload)
            return None
        else:
            cred_file = _KEY_DIR / f"{account_id}.enc"
            if not cred_file.exists():
                return None
            fernet = _get_fernet()
            decrypted = fernet.decrypt(cred_file.read_bytes()).decode()
            return json.loads(decrypted)
    except Exception as exc:
        logger.error("Failed to retrieve credentials for %s: %s", account_id, exc)
        return None


def delete(account_id: str) -> None:
    """Remove stored credentials for *account_id*."""
    try:
        if _USE_KEYRING:
            _keyring.delete_password(_SERVICE_NAME, account_id)
        cred_file = _KEY_DIR / f"{account_id}.enc"
        if cred_file.exists():
            cred_file.unlink()
        logger.info("Deleted credentials for %s", account_id)
    except Exception as exc:
        logger.warning("Could not fully delete credentials for %s: %s", account_id, exc)
