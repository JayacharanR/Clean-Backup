"""Run API tests against disposable state, including module import side effects."""

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def api_module(tmp_path_factory):
    state = tmp_path_factory.mktemp("clean-backup-api")
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(state)
        patch.setenv("CLEAN_BACKUP_DB_PATH", str(state / "test.db"))
        patch.setenv("CLEAN_BACKUP_CONFIG_DIR", str(state / "config"))
        patch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
        module = importlib.import_module("src.web_app")
        yield module
        # SQLite connections are thread-local; close the main test connection.
        db = sys.modules["src.classify.db"]
        connection = getattr(db._local, "conn", None)
        if connection is not None:
            connection.close()
            del db._local.conn


@pytest.fixture
def client(api_module, monkeypatch, tmp_path):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs" / "undo_journals").mkdir(parents=True)
    # Real background jobs and file operations, isolated per test.
    monkeypatch.setattr(api_module, "jobs", api_module.JobManager())
    monkeypatch.setattr(api_module, "_allowed_roots", set())
    monkeypatch.setattr(api_module, "TRASH_ROOT", tmp_path / "trash")
    api_module.app.config.update(TESTING=True)
    with api_module.app.test_client() as test_client:
        yield test_client
