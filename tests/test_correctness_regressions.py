"""Regressions for capture-date handling, classification apply and CLI helpers."""

import importlib
import os
import sqlite3
import time
from datetime import datetime

import pytest
from PIL import Image
from PIL.ExifTags import IFD


def camera_photo(path, original="2019:07:04 12:00:00", *, iso=None, exposure=None, color="gray"):
    """Write EXIF the way cameras do: capture fields in the Exif sub-IFD."""
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    exif[0x0132] = "2021:01:01 00:00:00"  # IFD0 DateTime = last modification
    sub = exif.get_ifd(IFD.Exif)
    if original:
        sub[0x9003] = original
    if iso:
        sub[0x8827] = iso
    if exposure:
        sub[0x829A] = exposure
    Image.new("RGB", (64, 48), color).save(path, exif=exif)
    old = time.mktime((2015, 2, 3, 0, 0, 0, 0, 0, -1))
    os.utime(path, (old, old))
    return path


def test_capture_date_is_read_from_the_exif_sub_ifd(tmp_path):
    from src.metadata import get_image_date, get_media_date

    photo = camera_photo(tmp_path / "camera.jpg")
    assert get_image_date(str(photo)) == datetime(2019, 7, 4, 12, 0, 0)
    assert get_media_date(photo) == datetime(2019, 7, 4, 12, 0, 0)


def test_missing_or_blank_capture_date_falls_back_to_mtime(tmp_path):
    from src.metadata import get_image_date, get_media_date

    for name, value in (("none.jpg", None), ("blank.jpg", "    :  :     :  :  "), ("zero.jpg", "0000:00:00 00:00:00")):
        photo = camera_photo(tmp_path / name, value)
        assert get_image_date(str(photo)) is None
        assert get_media_date(photo).year == 2015


def test_organize_uses_camera_capture_date_not_file_time(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from src.organiser import organise_files

    source = tmp_path / "in"
    source.mkdir()
    camera_photo(source / "holiday.jpg")
    stats = organise_files(str(source), str(tmp_path / "out"), "copy")
    assert stats["processed"] == 1 and stats["errors"] == 0
    assert (tmp_path / "out" / "2019" / "July" / "holiday.jpg").is_file()


def test_classifier_sees_exposure_fields_of_camera_files(tmp_path):
    from src.classify.stage_exif import detect_night_from_exif, extract_exif

    night = extract_exif(camera_photo(tmp_path / "night.jpg", iso=6400, exposure=0.5))
    assert (night.iso, night.exposure_time) == (6400, 0.5)
    assert night.datetime_original == "2019:07:04 12:00:00"
    assert detect_night_from_exif(night) > 0


@pytest.fixture
def classified(api_module, tmp_path, monkeypatch):
    """Two catalogued photos tagged in a fresh run, with journals in tmp_path."""
    from src.classify import db

    monkeypatch.chdir(tmp_path)
    source = tmp_path / "library"
    source.mkdir()
    run_id = f"run-{time.monotonic_ns()}"
    db.save_run_config(run_id, {"folder_scheme": "yyyy_mm_category"})
    photos = [
        camera_photo(source / f"photo{i}.jpg", color=color)
        for i, color in enumerate(["red", "green", "blue", "white", "black", "gray"])
    ]
    for photo in photos:
        db.add_tag(db.get_or_create_media_file(str(photo)), "nature", run_id=run_id)
    return run_id, photos, tmp_path / "sorted"


def test_classification_apply_reports_progress_and_files_by_capture_date(classified):
    from src.classify.apply_org import apply_classification

    run_id, photos, destination = classified
    progress = []
    result = apply_classification(run_id, str(destination), "copy", lambda pct, msg: progress.append((pct, msg)))

    assert result["transferred"] == len(photos) and result["errors"] == 0
    assert progress and all(isinstance(pct, int) and 0 <= pct <= 100 for pct, _ in progress)
    # Filed under the photo's capture month, not the month it was catalogued.
    assert sorted(p.name for p in (destination / "2019" / "07" / "Nature - Scenery").iterdir()) == sorted(p.name for p in photos)
    assert all(p.exists() for p in photos)


def test_classification_apply_job_completes_and_can_be_undone(client, classified):
    run_id, photos, destination = classified
    originals = {p.name: p.read_bytes() for p in photos}
    started = client.post("/api/classify/apply", json={"run_id": run_id, "dest_dir": str(destination), "operation": "move"})
    job_id = started.get_json()["job_id"]
    deadline = time.monotonic() + 30
    while (job := client.get(f"/api/jobs/{job_id}").get_json()["job"])["status"] not in {"completed", "failed"}:
        assert time.monotonic() < deadline
        time.sleep(0.02)

    assert job["status"] == "completed", job
    assert job["result"]["transferred"] == len(photos) and "error" not in job["result"]
    assert not any(p.exists() for p in photos)

    assert client.post("/api/undo/revert", json={}).get_json()["ok"]
    assert {p.name: p.read_bytes() for p in photos} == originals


def test_classification_apply_never_replaces_an_existing_file(classified):
    from src.classify.apply_org import apply_classification

    run_id, photos, destination = classified
    occupied = destination / "2019" / "07" / "Nature - Scenery" / photos[0].name
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(b"already here")
    result = apply_classification(run_id, str(destination), "copy")
    assert result["transferred"] == len(photos)
    assert occupied.read_bytes() == b"already here"
    assert len(list(occupied.parent.iterdir())) == len(photos) + 1


def test_failed_apply_is_reported_as_a_failed_job(client):
    started = client.post("/api/classify/apply", json={"run_id": "no-such-run", "dest_dir": "/tmp/unused-clean-backup", "operation": "copy"})
    job_id = started.get_json()["job_id"]
    deadline = time.monotonic() + 30
    while (job := client.get(f"/api/jobs/{job_id}").get_json()["job"])["status"] not in {"completed", "failed"}:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert job["status"] == "failed" and "not found" in job["error"]


def test_duplicate_report_counts_every_supported_image_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from src.duplicate_handler import handle_duplicates

    library = tmp_path / "library"
    library.mkdir()
    for name in ("a.jpg", "B.JPG", "c.png", "d.raf", "notes.txt"):
        (library / name).write_bytes(b"x")
    assert handle_duplicates(str(library), action="report").total_scanned == 4


def test_cli_module_has_no_missing_imports():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "main.py").read_text())
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    for module in sorted(m for m in modules if m.startswith("src")):
        importlib.import_module(module)


def test_demo_reset_clears_the_tables_that_exist(api_module, tmp_path, monkeypatch):
    """The reset list must name real tables, or the demo never returns to its seed state."""
    from deploy.demo import reset_demo
    from src.classify import db
    from src.watcher import db as watcher_db

    watcher_db.init_db()
    photo = camera_photo(tmp_path / "visitor.jpg")
    db.add_tag(db.get_or_create_media_file(str(photo)), "nature", run_id="visitor-run")
    db.create_person("Visitor")
    db._get_conn().commit()

    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("CLEAN_BACKUP_MEDIA_PATH", str(tmp_path / "media"))
    monkeypatch.setattr("deploy.demo.seed_demo_db.seed", lambda: None)
    reset_demo.reset_demo()

    with sqlite3.connect(os.environ["CLEAN_BACKUP_DB_PATH"]) as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("media_tags", "people", "media_files", "face_embeddings")
        }
    assert counts == {"media_tags": 0, "people": 0, "media_files": 0, "face_embeddings": 0}
