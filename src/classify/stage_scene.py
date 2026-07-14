"""
Stage C — Scene classifier (ONNX, single model, single pass per image).

Uses a MobileNetV3-Small (or compatible) ImageNet-pretrained model to
classify the dominant scene in each image.  One inference call maps to
zero or more categories via the ``SCENE_CLASS_MAP`` lookup table.

If the ONNX model file is not present, this stage is skipped gracefully.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from src.classify.category_config import SCENE_CLASS_MAP
from src.classify.models import load_onnx_session
from src.logger import logger


class SceneClassifier:
    """
    Wraps an ONNX scene classification model.

    Designed to be instantiated **once** per pipeline run and reused
    across all files — do NOT create a new instance per image.
    """

    def __init__(self) -> None:
        self.session = load_onnx_session("scene")
        self._input_name: str | None = None
        self._input_shape: tuple[int, ...] | None = None

        if self.session is not None:
            inp = self.session.get_inputs()[0]
            self._input_name = inp.name
            # Expected shape: [1, 3, H, W] or [1, H, W, 3]
            shape = inp.shape
            if len(shape) == 4:
                if shape[1] == 3:
                    self._input_shape = (shape[2], shape[3])  # NCHW
                else:
                    self._input_shape = (shape[1], shape[2])  # NHWC

    @property
    def available(self) -> bool:
        return self.session is not None

    def classify(self, image_path: str | Path, top_k: int = 5) -> list[dict]:
        """
        Run scene classification on a single image.

        Returns a list of ``{"class_index": int, "category": str | None,
        "probability": float}`` sorted by probability descending.
        """
        if not self.available:
            return []

        try:
            img = Image.open(image_path).convert("RGB")
            target_size = self._input_shape or (224, 224)
            img = img.resize(target_size, Image.Resampling.LANCZOS)

            # Normalise to [0, 1] then ImageNet mean/std
            arr = np.array(img, dtype=np.float32) / 255.0
            mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
            std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
            arr = (arr - mean) / std

            # HWC → CHW → NCHW
            arr = np.transpose(arr, (2, 0, 1))
            arr = np.expand_dims(arr, axis=0)

            outputs = self.session.run(None, {self._input_name: arr})
            logits = outputs[0][0]

            # Softmax
            exp = np.exp(logits - np.max(logits))
            probs = exp / exp.sum()

            top_indices = np.argsort(probs)[::-1][:top_k]

            results = []
            for idx in top_indices:
                idx_int = int(idx)
                results.append(
                    {
                        "class_index": idx_int,
                        "category": SCENE_CLASS_MAP.get(idx_int),
                        "probability": float(probs[idx_int]),
                    }
                )
            return results

        except Exception as exc:
            logger.debug("Scene classification failed for %s: %s", image_path, exc)
            return []

    def get_category_scores(self, image_path: str | Path) -> dict[str, float]:
        """
        Run classification and return per-category max confidence scores.

        Only categories present in ``SCENE_CLASS_MAP`` are returned.
        """
        results = self.classify(image_path, top_k=10)

        category_scores: dict[str, float] = {}
        for r in results:
            cat = r["category"]
            if cat and r["probability"] > 0.05:
                if cat not in category_scores or r["probability"] > category_scores[cat]:
                    category_scores[cat] = r["probability"]

        return category_scores
