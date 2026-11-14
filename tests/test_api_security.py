"""Regression tests for the unauthenticated local API's trust boundaries."""

import stat
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask
from PIL import Image


def finished_job(client, response):
    assert response.status_code == 200, response.get_json()
    job_id = response.get_json()["job_id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").get_json()["job"]
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.02)
    pytest.fail("Background job did not finish within 30 seconds")


def scanned_library(client, tmp_path):
    source = tmp_path / "library"
    source.mkdir()
    Image.new("RGB", (64, 48), "#336699").save(source / "a.jpg")
    Image.new("RGB", (64, 48), "#996633").save(source / "b.jpg")
    job = finished_job(client, client.post("/api/duplicates/scan", json={"source_dir": str(source)}))
    assert job["status"] == "completed", job
    return source


# ── Cross-site and DNS-rebinding protection ──────────────────────────────


def test_other_sites_get_no_cors_read_access(client):
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_cross_origin_state_change_is_refused(client, tmp_path):
    victim = tmp_path / "keep.jpg"
    Image.new("RGB", (8, 8)).save(victim)
    response = client.post(
        "/api/duplicates/delete",
        json={"selected_images": [{"path": str(victim)}], "mode": "permanent", "confirm_text": "DELETE"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert victim.exists()


def test_same_origin_state_change_is_accepted(client):
    response = client.post(
        "/api/config", json={"phash_threshold": 7}, headers={"Origin": "http://localhost"}
    )
    assert response.status_code == 200, response.get_json()


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8080", "localhost.evil.example"])
def test_unexpected_host_header_is_refused(client, host):
    response = client.get("/api/health", headers={"Host": host})
    assert response.status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:8080", "192.168.1.20:8080", "[::1]:8080", "app.localhost"])
def test_loopback_and_ip_hosts_are_accepted(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_configured_hostname_is_accepted(client, monkeypatch):
    monkeypatch.setenv("CLEAN_BACKUP_ALLOWED_HOSTS", "nas.local, photos.example.org")
    assert client.get("/api/health", headers={"Host": "nas.local:8080"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "other.local"}).status_code == 403


# ── File disclosure ──────────────────────────────────────────────────────


def test_image_endpoint_does_not_serve_non_image_files(client, tmp_path):
    source = scanned_library(client, tmp_path)
    secret = source / "id_rsa"
    secret.write_text("PRIVATE KEY MATERIAL")
    notes = source / "notes.txt"
    notes.write_text("private notes")

    for path in (secret, notes):
        response = client.get("/api/image", query_string={"path": str(path)})
        assert response.status_code == 415
        assert b"PRIVATE" not in response.data and b"private notes" not in response.data

    assert client.get("/api/image", query_string={"path": str(source / "a.jpg")}).mimetype == "image/jpeg"


def test_undecodable_image_is_only_offered_as_a_download(client, tmp_path):
    source = scanned_library(client, tmp_path)
    fake = source / "page.jpg"
    fake.write_text("<script>alert(1)</script>")
    response = client.get("/api/image", query_string={"path": str(fake)})
    assert response.mimetype == "application/octet-stream"
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_demo_mode_cannot_scan_outside_its_media_folder(client, tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    Image.new("RGB", (32, 32), "red").save(media / "a.jpg")
    Image.new("RGB", (32, 32), "blue").save(media / "b.jpg")
    outside = tmp_path / "home"
    outside.mkdir()
    (outside / "secret.jpg").write_text("not for visitors")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("CLEAN_BACKUP_MEDIA_PATH", str(media))

    job = finished_job(client, client.post("/api/duplicates/scan", json={"source_dir": str(outside)}))
    assert job["status"] == "failed" and "sample media" in job["error"]
    assert client.get("/api/image", query_string={"path": str(outside / "secret.jpg")}).status_code == 400

    job = finished_job(client, client.post("/api/duplicates/scan", json={"source_dir": str(media)}))
    assert job["status"] == "completed", job


@pytest.mark.parametrize("face_id", ["../../../etc/passwd", "1/../2", "", "abc"])
def test_face_crop_requires_a_numeric_id(client, face_id):
    assert client.get("/api/face-crop", query_string={"id": face_id}).status_code == 400


# ── Deletion ─────────────────────────────────────────────────────────────


def test_delete_rejects_malformed_entries_without_crashing(client, tmp_path):
    response = client.post("/api/duplicates/delete", json={"selected_images": ["x", 3, None]})
    assert response.status_code == 200
    body = response.get_json()
    assert body["deleted_count"] == 0 and len(body["errors"]) == 3


def test_trash_never_replaces_an_earlier_trashed_file(client, api_module, tmp_path, monkeypatch):
    source = scanned_library(client, tmp_path)
    target = source / "a.jpg"
    monkeypatch.setattr(api_module.time, "time", lambda: 1_700_000_000)  # same second twice

    first = target.read_bytes()
    assert client.post("/api/duplicates/delete", json={"selected_images": [{"path": str(target)}]}).get_json()["deleted_count"] == 1
    target.write_bytes(b"a different file that reuses the name")
    second = target.read_bytes()
    assert client.post("/api/duplicates/delete", json={"selected_images": [{"path": str(target)}]}).get_json()["deleted_count"] == 1

    trashed = sorted(p.read_bytes() for p in api_module.TRASH_ROOT.iterdir() if not p.name.startswith("."))
    assert trashed == sorted([first, second])
    assert not target.exists()


def test_trashed_file_can_be_restored_by_undo(client, api_module, tmp_path):
    source = scanned_library(client, tmp_path)
    target = source / "b.jpg"
    original = target.read_bytes()
    assert client.post("/api/duplicates/delete", json={"selected_images": [{"path": str(target)}]}).get_json()["deleted_count"] == 1
    assert not target.exists()
    assert client.post("/api/undo/revert", json={}).get_json()["ok"]
    assert target.read_bytes() == original


# ── SQL identifiers ──────────────────────────────────────────────────────


@pytest.fixture
def watcher_db(api_module):
    from src.watcher import db

    db.init_db()
    config_id = db.add_config("Inbox", "/tmp/inbox", True, 2, [], [], "leave", "leave", False)
    yield db, config_id
    db.delete_config(config_id)


def test_watcher_update_rejects_injected_column_names(watcher_db):
    db, config_id = watcher_db
    with pytest.raises(ValueError):
        db.update_config(config_id, **{"label = 'pwned', watch_path": "/"})
    config = db.get_config(config_id)
    assert (config.label, config.watch_path) == ("Inbox", "/tmp/inbox")

    assert db.update_config(config_id, label="Renamed", pipeline=[{"job_type": "dedupe"}])
    assert db.get_config(config_id).label == "Renamed"


def test_watcher_api_reports_unknown_fields_as_a_client_error(watcher_db, monkeypatch):
    from src.watcher import api

    db, config_id = watcher_db
    monkeypatch.setattr(api.daemon, "sync_configs", lambda: None)
    app = Flask(__name__)
    app.register_blueprint(api.watcher_bp)
    client = app.test_client()

    injected = client.patch(f"/api/watchers/{config_id}", json={"label = 'pwned' --": 1})
    assert injected.status_code == 400
    assert client.patch(f"/api/watchers/{config_id}", json=["not", "an", "object"]).status_code == 400
    assert client.patch(f"/api/watchers/{config_id}", json={"label": "Fine"}).status_code == 200
    assert db.get_config(config_id).label == "Fine"


def test_sync_run_update_rejects_unknown_columns(api_module):
    from src.cloud.manifest import update_sync_run

    with pytest.raises(ValueError):
        update_sync_run(1, **{"status = 'x', account_id": 2})


# ── Cloud ────────────────────────────────────────────────────────────────


def test_drive_queries_escape_file_names():
    from src.cloud.provider_gdrive import GoogleDriveProvider, _q

    assert _q("O'Brien.jpg") == r"'O\'Brien.jpg'"
    assert _q("back\\slash") == r"'back\\slash'"

    queries = []

    class Files:
        def list(self, q, **_):
            queries.append(q)
            return self

        def execute(self):
            return {"files": []}

    class Service:
        def files(self):
            return Files()

    provider = GoogleDriveProvider()
    provider._service = Service()
    provider.delete("x' or name contains '.jpg")
    assert queries == [r"name='x\' or name contains \'.jpg' and 'root' in parents and trashed=false"]


def test_oauth_url_carries_exactly_one_state(tmp_path, monkeypatch):
    import json

    from src.cloud.provider_gdrive import start_oauth_flow

    (tmp_path / "credentials.json").write_text(json.dumps({"web": {
        "client_id": "test-client.apps.googleusercontent.com",
        "client_secret": "not-a-real-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost:8080/api/cloud/accounts/gdrive/callback"],
    }}))
    monkeypatch.chdir(tmp_path)

    url, state, _flow = start_oauth_flow("http://localhost:8080/api/cloud/accounts/gdrive/callback")
    assert parse_qs(urlsplit(url).query)["state"] == [state]


def test_oauth_callback_escapes_error_text(client, api_module):
    class Flow:
        def fetch_token(self, **_):
            raise RuntimeError("<script>alert(1)</script>")

    api_module._oauth_flows["known-state"] = Flow()
    response = client.get("/api/cloud/accounts/gdrive/callback", query_string={"state": "known-state"})
    assert response.status_code == 500
    assert b"<script>" not in response.data and b"&lt;script&gt;" in response.data


def test_credential_files_are_never_group_or_world_readable(tmp_path):
    from src.cloud.credential_store import _write_private

    target = tmp_path / "secret.key"
    _write_private(target, b"key material")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_bytes() == b"key material"
    assert list(tmp_path.iterdir()) == [target]


# ── Resource retention ───────────────────────────────────────────────────


def test_finished_jobs_are_pruned(api_module):
    manager = api_module.JobManager()
    manager.MAX_FINISHED_JOBS = 5
    ids = []
    for index in range(12):
        ids.append(manager.submit("noop", lambda progress, value: {"value": value}, index))
        deadline = time.monotonic() + 5
        while manager.get(ids[-1]).status != "completed" and time.monotonic() < deadline:
            time.sleep(0.005)
    assert manager.get(ids[0]) is None
    assert manager.get(ids[-1]).result == {"value": 11}
    assert sum(manager.get(job_id) is not None for job_id in ids) <= 6
