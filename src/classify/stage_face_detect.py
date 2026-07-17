"""
Stage D — Face detection using YuNet (ONNX).

Detects faces in images and returns bounding boxes + count.  The face
count feeds into People/Selfies/Family/Events tagging.  Face crops are
cached to ``logs/face_cache/`` for the management UI.

If the YuNet ONNX model is not present, this stage is skipped gracefully.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from src.classify.models import get_model_path
from src.classify.stage_exif import ExifData
from src.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FACE_CACHE_DIR = PROJECT_ROOT / "logs" / "face_cache"


class FaceDetector:
    """
    YuNet-based face detector.

    Instantiated **once** per pipeline run and reused across all images.
    """

    def __init__(self) -> None:
        self._detector = None
        self._available = False
        self._init_detector()

    def _init_detector(self) -> None:
        model_path = get_model_path("face_detect")
        if model_path is None:
            return

        try:
            import cv2  # type: ignore[import-untyped]

            self._detector = cv2.FaceDetectorYN.create(
                str(model_path),
                "",
                (320, 320),       # will be resized per image
                0.6,              # score threshold
                0.3,              # NMS threshold
                5000,             # top-k
            )
            self._available = True
            logger.info("YuNet face detector loaded from %s", model_path)
        except ImportError:
            logger.warning("opencv-python not installed — face detection will be skipped")
        except Exception as exc:
            logger.error("Failed to initialise YuNet face detector: %s", exc)

    @property
    def available(self) -> bool:
        return self._available

    def detect(self, image_path: str | Path) -> list[dict]:
        """
        Detect faces in *image_path*.

        Returns a list of ``{"x": int, "y": int, "w": int, "h": int,
        "confidence": float}`` bounding boxes.
        """
        if not self._available:
            return []

        try:
            import cv2

            img = cv2.imread(str(image_path))
            if img is None:
                # Fallback: use Pillow to read, then convert
                pil_img = Image.open(image_path).convert("RGB")
                img = np.array(pil_img)[:, :, ::-1]  # RGB → BGR

            h, w = img.shape[:2]
            self._detector.setInputSize((w, h))

            _, faces = self._detector.detect(img)

            if faces is None:
                return []

            results = []
            for face in faces:
                x, y, fw, fh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
                conf = float(face[-1]) if len(face) > 4 else 0.9
                results.append({"x": x, "y": y, "w": fw, "h": fh, "confidence": conf})

            return results

        except Exception as exc:
            logger.debug("Face detection failed for %s: %s", image_path, exc)
            return []

    def cache_face_crop(
        self,
        image_path: str | Path,
        bbox: dict,
        face_id: int,
    ) -> Path | None:
        """Save a face crop thumbnail to the face cache directory."""
        try:
            FACE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path = FACE_CACHE_DIR / f"face_{face_id}.jpg"

            with Image.open(image_path) as img:
                x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
                # Add 20% padding around the face
                pad_x = int(w * 0.2)
                pad_y = int(h * 0.2)
                crop_box = (
                    max(0, x - pad_x),
                    max(0, y - pad_y),
                    min(img.width, x + w + pad_x),
                    min(img.height, y + h + pad_y),
                )
                face_crop = img.crop(crop_box).convert("RGB")
                face_crop.thumbnail((120, 120), Image.Resampling.LANCZOS)
                face_crop.save(cache_path, "JPEG", quality=85)

            return cache_path
        except Exception as exc:
            logger.debug("Face crop caching failed for face %d: %s", face_id, exc)
            return None


def classify_faces(
    face_count: int,
    faces: list[dict],
    exif: ExifData,
    image_width: int,
    image_height: int,
    home_lat: float | None = None,
    home_lon: float | None = None,
    is_travel: bool = False,
) -> dict[str, float]:
    """
    Determine face-based category tags from face detection results.

    Returns ``{category_key: confidence}`` for applicable categories.
    """
    tags: dict[str, float] = {}

    if face_count == 0:
        return tags

    # People — any faces
    tags["people"] = 0.9

    # Selfies — single face + front camera or large face bbox
    if face_count == 1 and faces:
        face = faces[0]
        face_area = face["w"] * face["h"]
        image_area = image_width * image_height
        face_ratio = face_area / image_area if image_area > 0 else 0

        if exif.is_front_camera or face_ratio > 0.35:
            tags["selfies"] = 0.85

    # Family — multiple faces + not travelling
    if face_count >= 2 and not is_travel:
        tags["family"] = 0.7

    # Events — many faces or event keywords
    if face_count >= 4:
        tags["events"] = 0.75

    return tags
