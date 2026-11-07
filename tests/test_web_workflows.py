"""Exercise the real API, Rust hashing, file operations, and undo journal."""

import hashlib
import time

import pytest
from PIL import Image, ImageDraw


def make_photo(path, date="2025:03:15 10:30:00"):
    image = Image.new("RGB", (320, 240), "#237d9a")
    draw = ImageDraw.Draw(image)
    draw.polygon([(0, 239), (120, 40), (210, 239)], fill="#183e39")
    draw.ellipse((215, 20, 280, 85), fill="#ffd372")
    draw.rectangle((20, 175, 90, 215), fill="#cc6257")
    exif = image.getexif()
    exif[306] = date
    exif[36867] = date
    image.save(path, quality=95, exif=exif)
    return image, exif


def wait_for_job(client, response):
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["ok"], payload
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job_response = client.get(f'/api/jobs/{payload["job_id"]}')
        assert job_response.status_code == 200
        job = job_response.get_json()["job"]
        if job["status"] in {"completed", "failed"}:
            assert job["status"] == "completed", job
            assert job["progress"] == 100
            return job["result"]
        time.sleep(0.02)
    pytest.fail("Background job did not finish within 30 seconds")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_health_uses_compiled_rust_backend(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["ok"]
    assert response.get_json()["backend"] == "rust (phash_rs)"


def test_scan_detects_resized_and_recompressed_duplicates(client, tmp_path):
    source = tmp_path / "photos"
    source.mkdir()
    image, exif = make_photo(source / "original.jpg")
    image.resize((160, 120)).save(source / "resized.jpg", quality=75, exif=exif)
    image.save(source / "compressed.jpg", quality=30, exif=exif)
    before = {p.name: digest(p) for p in source.iterdir()}
    result = wait_for_job(client, client.post("/api/duplicates/scan", json={
        "source_dir": str(source), "threshold": 10,
    }))
    assert result["images_found"] == 3
    assert result["duplicate_groups"] == 1
    assert result["total_duplicates"] == 2
    assert result["images_without_hash"] == 0
    assert result["space_recoverable_bytes"] > 0
    group = result["groups"][0]
    assert {p["name"] for p in group["images"]} == set(before)
    assert sum(p["is_best"] for p in group["images"]) == 1
    assert {p.name: digest(p) for p in source.iterdir()} == before
    preview = client.get("/api/image", query_string={
        "path": str(source / "resized.jpg"), "variant": "thumb",
    })
    assert preview.status_code == 200
    assert preview.mimetype.startswith("image/")


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_organize_by_exif_date_and_undo(client, monkeypatch, tmp_path, operation):
    # Keep multiprocessing real while limiting CI resource usage.
    from src import organiser
    monkeypatch.setattr(organiser, "cpu_count", lambda: 2)
    source = tmp_path / "photos"
    source.mkdir()
    destination = tmp_path / "organized"
    make_photo(source / "spring.jpg")
    make_photo(source / "summer.jpg", "2025:06:21 12:00:00")
    before = {p.name: digest(p) for p in source.iterdir()}
    result = wait_for_job(client, client.post("/api/organize/start", json={
        "source_dir": str(source), "destination_dir": str(destination),
        "operation": operation,
    }))
    assert result["stats"]["processed"] == 2
    assert result["stats"]["errors"] == 0
    assert digest(destination / "2025" / "March" / "spring.jpg") == before["spring.jpg"]
    assert digest(destination / "2025" / "June" / "summer.jpg") == before["summer.jpg"]
    assert len(list(source.glob("*.jpg"))) == (2 if operation == "copy" else 0)
    sessions = client.get("/api/undo/sessions").get_json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["count"] == 2
    reverted = client.post("/api/undo/revert", json={"session_id": sessions[0]["id"]})
    assert reverted.status_code == 200
    assert reverted.get_json()["ok"]
    assert not list(destination.rglob("*.jpg"))
    assert {p.name: digest(p) for p in source.iterdir()} == before
    assert client.get("/api/undo/sessions").get_json()["sessions"] == []


@pytest.mark.parametrize("endpoint", [
    "/api/organize/start", "/api/compress/start", "/api/duplicates/delete",
    "/api/undo/revert", "/api/config",
])
def test_demo_mode_rejects_file_and_config_mutations(client, monkeypatch, endpoint):
    monkeypatch.setenv("DEMO_MODE", "true")
    response = client.post(endpoint, json={})
    assert response.status_code == 403
    assert response.get_json()["demo"]
    assert not response.get_json()["ok"]


@pytest.mark.parametrize("payload", [{}, {"source_dir": "/tmp", "threshold": "invalid"}])
def test_scan_rejects_invalid_input(client, payload):
    response = client.post("/api/duplicates/scan", json=payload)
    assert response.status_code == 400
    assert not response.get_json()["ok"]


def test_unknown_job_returns_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_image_outside_scanned_library_is_blocked(client, tmp_path):
    photo = tmp_path / "private.jpg"
    make_photo(photo)
    response = client.get("/api/image", query_string={"path": str(photo)})
    assert response.status_code == 400
    assert "outside allowed scan roots" in response.get_json()["error"]


@pytest.mark.parametrize(("value", "expected"), [(-1, 0), (8, 8), (100, 25)])
def test_sensitivity_is_clamped_and_persisted(client, value, expected):
    response = client.post("/api/config", json={"phash_threshold": value})
    assert response.status_code == 200
    assert response.get_json()["config"]["phash_threshold"] == expected
    assert client.get("/api/health").get_json()["default_threshold"] == expected
