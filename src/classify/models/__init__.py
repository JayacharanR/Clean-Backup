"""
ONNX model loader utilities for the classification pipeline.

Models are stored in this directory as ``.onnx`` files.  The pipeline
gracefully degrades (skips the relevant stage) when a model file is absent.
"""

from __future__ import annotations

from pathlib import Path

from src.logger import logger

MODELS_DIR = Path(__file__).resolve().parent

# Expected model filenames
MODEL_FILES: dict[str, str] = {
    "scene": "mobilenetv3_small.onnx",
    "face_detect": "yunet.onnx",
    "face_embed": "mobilefacenet.onnx",
}


def get_model_path(name: str) -> Path | None:
    """Return the absolute path to a model file, or *None* if it does not exist."""
    filename = MODEL_FILES.get(name)
    if not filename:
        return None
    path = MODELS_DIR / filename
    return path if path.is_file() else None


def is_model_available(name: str) -> bool:
    """Check whether an ONNX model file is present on disk."""
    return get_model_path(name) is not None


def load_onnx_session(name: str):
    """
    Load an ONNX model and return an ``onnxruntime.InferenceSession``.

    Returns *None* (and logs a warning) if the model file is missing or
    ONNX Runtime is not installed.
    """
    path = get_model_path(name)
    if path is None:
        logger.warning(
            "ONNX model '%s' not found in %s — stage will be skipped",
            name,
            MODELS_DIR,
        )
        return None

    try:
        import onnxruntime as ort  # type: ignore[import-untyped]

        session = ort.InferenceSession(
            str(path),
            providers=["CPUExecutionProvider"],
        )
        logger.info("Loaded ONNX model '%s' from %s", name, path)
        return session
    except ImportError:
        logger.warning(
            "onnxruntime is not installed — ML classification stages will be skipped"
        )
        return None
    except Exception as exc:
        logger.error("Failed to load ONNX model '%s': %s", name, exc)
        return None
