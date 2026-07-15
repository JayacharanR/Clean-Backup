"""
Classification pipeline orchestrator.

Runs all six stages sequentially on every media file in a source
directory:

    Stage A: EXIF / metadata extraction
    Stage B: Document / Screenshot heuristic
    Stage C: Scene classifier (ONNX)
    Stage D: Face detection (YuNet)
    Stage E: Face recognition (embedding + cosine match)
    Stage F: Tag resolution (priority table + confidence threshold)

ML models (Stages C/D/E) are loaded **once** at pipeline start and
reused for all files.  If a model file is missing the corresponding
stage is silently skipped.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from src.classify import db
from src.classify.stage_document import detect_document, detect_screenshot
from src.classify.stage_exif import (
    ExifData,
    detect_events_from_exif,
    detect_night_from_exif,
    detect_travel,
    extract_exif,
)
from src.classify.stage_face_detect import FaceDetector, classify_faces
from src.classify.stage_face_recognize import FaceRecognizer, match_face
from src.classify.stage_scene import SceneClassifier
from src.classify.tag_resolver import resolve_tags
from src.constants import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from src.logger import logger
from src.undo_manager import undo_manager


def run_classify_pipeline(
    source_dir: str,
    run_id: str,
    config: dict,
    progress_cb: Callable[[int, str], None],
) -> dict[str, Any]:
    """
    Run the full classification pipeline on *source_dir*.

    Args:
        source_dir: Absolute path to the directory to scan.
        run_id: Unique run identifier (matches undo session + config).
        config: Wizard configuration dict (enabled categories, thresholds, etc.).
        progress_cb: ``(percent: int, message: str)`` callback for job status.

    Returns:
        Summary dict with tag counts, file totals, and review-queue size.
    """
    source = Path(source_dir).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise ValueError(f"Source directory not found: {source}")

    # ── Parse config ──────────────────────────────────────────────────
    enabled_cats: set[str] = set(config.get("enabled_categories", []))
    # Ensure "other" is always available for fallback
    enabled_cats.add("other")

    auto_threshold: float = float(config.get("confidence_threshold", 0.5))
    home_lat = _safe_float(config.get("home_gps_lat"))
    home_lon = _safe_float(config.get("home_gps_lon"))
    face_sensitivity: str = config.get("face_sensitivity", "balanced")

    face_threshold_map = {"strict": 0.7, "balanced": 0.6, "loose": 0.5}
    face_match_threshold = face_threshold_map.get(face_sensitivity, 0.6)

    # ── Collect files ─────────────────────────────────────────────────
    progress_cb(2, "Scanning directory")
    all_files: list[Path] = []
    for p in sorted(source.rglob("*")):
        if p.is_file():
            ext = p.suffix.lower()
            if ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS:
                all_files.append(p)

    total_files = len(all_files)
    if total_files == 0:
        progress_cb(100, "No media files found")
        return {"total_files": 0, "tags_assigned": 0, "categories_found": {}, "review_items": 0}

    progress_cb(5, f"Found {total_files} media files")

    # ── Load models ONCE ──────────────────────────────────────────────
    import os
    disable_ml = os.environ.get("CLEAN_BACKUP_DISABLE_ML", "0").lower() in ("1", "true", "yes")
    
    if disable_ml:
        logger.info("CLEAN_BACKUP_DISABLE_ML is set. Skipping ML model initialization.")
        # Dummy objects that mimic not-available status
        class DummyModel:
            available = False
        scene_classifier = DummyModel()
        face_detector = DummyModel()
        face_recognizer = DummyModel()
    else:
        scene_classifier = SceneClassifier()
        face_detector = FaceDetector()
        face_recognizer = FaceRecognizer()

    # Pre-load known face embeddings for Stage E matching
    known_embeddings = db.get_all_known_embeddings() if face_recognizer.available else []

    # ── Start undo session ────────────────────────────────────────────
    undo_manager.start_session()

    # ── Process each file ─────────────────────────────────────────────
    stats: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    total_tags = 0
    total_review = 0

    for idx, file_path in enumerate(all_files):
        file_num = idx + 1
        pct = 5 + int((file_num / total_files) * 90)
        pct = max(5, min(95, pct))

        ext = file_path.suffix.lower()
        candidate_tags: dict[str, tuple[float, str]] = {}

        # ── Videos pre-filter (priority 0) ────────────────────────────
        if ext in VIDEO_EXTENSIONS:
            candidate_tags["videos"] = (1.0, "filesystem")
            progress_cb(pct, f"Stage A (Video): {file_path.name} ({file_num}/{total_files})")
            stats["videos"] += 1

            # Write tags and continue — skip ML stages for videos
            file_id = db.get_or_create_media_file(str(file_path))
            results = resolve_tags(file_id, candidate_tags, enabled_cats, auto_threshold, run_id)
            for r in results:
                if r["status"] == "auto":
                    total_tags += 1
                    category_counts[r["category"]] += 1
                else:
                    total_review += 1
            continue

        # ── Stage A: EXIF ─────────────────────────────────────────────
        progress_cb(pct, f"Stage A (EXIF): {file_path.name} ({file_num}/{total_files})")
        exif = extract_exif(file_path)
        stats["exif_processed"] += 1

        # Travel detection (EXIF-based)
        if "travel" in enabled_cats:
            travel_conf = detect_travel(exif, home_lat, home_lon)
            if travel_conf > 0:
                candidate_tags["travel"] = (travel_conf, "exif")

        # Event detection (EXIF keywords)
        if "events" in enabled_cats:
            event_conf = detect_events_from_exif(exif)
            if event_conf > 0:
                candidate_tags["events"] = (event_conf, "exif")

        # Night detection (EXIF exposure)
        if "night" in enabled_cats:
            night_conf = detect_night_from_exif(exif)
            if night_conf > 0:
                candidate_tags["night"] = (night_conf, "exif")

        # ── Stage B: Document / Screenshot ────────────────────────────
        progress_cb(pct, f"Stage B (Heuristic): {file_path.name} ({file_num}/{total_files})")
        stats["heuristic_processed"] += 1

        if "screenshots" in enabled_cats:
            ss_conf = detect_screenshot(exif)
            if ss_conf > 0:
                candidate_tags["screenshots"] = (ss_conf, "heuristic")

        if "documents" in enabled_cats:
            doc_conf = detect_document(exif, str(file_path))
            if doc_conf > 0:
                candidate_tags["documents"] = (doc_conf, "heuristic")

        # ── Stage C: Scene classifier ─────────────────────────────────
        scene_cats_enabled = enabled_cats & {"nature", "food", "pets", "vehicles", "art", "travel", "night"}
        if scene_classifier.available and scene_cats_enabled:
            progress_cb(pct, f"Stage C (Scene): {file_path.name} ({file_num}/{total_files})")
            scene_scores = scene_classifier.get_category_scores(file_path)
            stats["scene_processed"] += 1

            for cat_key, score in scene_scores.items():
                if cat_key in enabled_cats:
                    # If EXIF already gave a higher score, keep the higher one
                    existing = candidate_tags.get(cat_key)
                    if existing is None or score > existing[0]:
                        candidate_tags[cat_key] = (score, "ml_scene")

        # ── Stage D: Face detection ───────────────────────────────────
        face_cats_enabled = enabled_cats & {"people", "selfies", "family", "events"}
        faces: list[dict] = []
        face_count = 0

        if face_detector.available and face_cats_enabled:
            progress_cb(pct, f"Stage D (Faces): {file_path.name} ({file_num}/{total_files})")
            faces = face_detector.detect(file_path)
            face_count = len(faces)
            stats["faces_detected"] += face_count
            stats["face_processed"] += 1

            if face_count > 0:
                is_travel = "travel" in candidate_tags
                face_tags = classify_faces(
                    face_count, faces, exif,
                    exif.width, exif.height,
                    home_lat, home_lon, is_travel,
                )
                for cat_key, conf in face_tags.items():
                    if cat_key in enabled_cats:
                        existing = candidate_tags.get(cat_key)
                        if existing is None or conf > existing[0]:
                            candidate_tags[cat_key] = (conf, "ml_face")

        # ── Stage E: Face recognition ─────────────────────────────────
        file_id = db.get_or_create_media_file(str(file_path))

        if face_recognizer.available and face_count > 0:
            progress_cb(pct, f"Stage E (Recognition): {file_path.name} ({file_num}/{total_files})")
            stats["recognition_processed"] += 1

            for face in faces:
                embedding = face_recognizer.get_embedding(file_path, face)
                if embedding is not None:
                    emb_bytes = embedding.tobytes()

                    # Try to match against known people
                    person_id, sim = match_face(
                        embedding, known_embeddings, threshold=face_match_threshold
                    )

                    face_db_id = db.save_face_embedding(
                        file_id, face, emb_bytes, face.get("confidence", 0.0)
                    )

                    if person_id is not None:
                        db.assign_face_to_person(face_db_id, person_id)
                        stats["faces_matched"] += 1
                    else:
                        stats["faces_unidentified"] += 1

                    # Cache face crop for UI
                    face_detector.cache_face_crop(file_path, face, face_db_id)
                else:
                    # Save face without embedding (model issue or crop failed)
                    face_db_id = db.save_face_embedding(
                        file_id, face, None, face.get("confidence", 0.0)
                    )
                    face_detector.cache_face_crop(file_path, face, face_db_id)

        # ── Stage F: Tag resolution ───────────────────────────────────
        progress_cb(pct, f"Stage F (Resolve): {file_path.name} ({file_num}/{total_files})")
        results = resolve_tags(file_id, candidate_tags, enabled_cats, auto_threshold, run_id)
        for r in results:
            if r["status"] == "auto":
                total_tags += 1
                category_counts[r["category"]] += 1
            else:
                total_review += 1

    # ── Finalise ──────────────────────────────────────────────────────
    undo_manager.end_session()
    progress_cb(98, "Building summary")

    summary = {
        "total_files": total_files,
        "tags_assigned": total_tags,
        "review_items": total_review,
        "categories_found": dict(category_counts),
        "stats": dict(stats),
    }

    progress_cb(100, "Classification complete")
    logger.info(
        "Classify pipeline finished: %d files, %d tags, %d review items",
        total_files, total_tags, total_review,
    )

    return summary


def _safe_float(value) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
