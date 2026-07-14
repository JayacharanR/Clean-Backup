"""
Stage E — Face recognition (embedding extraction + cosine matching).

For each detected face from Stage D, extracts a 128/512-dim embedding via
MobileFaceNet (ONNX) and compares it against known people in the database.

If no match is found the embedding is saved as *unidentified* and later
surfaced in the "Who is this?" clustering UI.

If the ONNX model is not present, this stage is skipped gracefully.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from src.classify.models import load_onnx_session
from src.logger import logger


class FaceRecognizer:
    """
    MobileFaceNet-based face embedding extractor.

    Instantiated **once** per pipeline run and reused across all images.
    """

    def __init__(self) -> None:
        self.session = load_onnx_session("face_embed")
        self._input_name: str | None = None
        self._input_size: tuple[int, int] = (112, 112)

        if self.session is not None:
            inp = self.session.get_inputs()[0]
            self._input_name = inp.name
            shape = inp.shape
            if len(shape) == 4:
                if shape[1] == 3:
                    self._input_size = (shape[3], shape[2])  # W, H from NCHW
                else:
                    self._input_size = (shape[2], shape[1])

    @property
    def available(self) -> bool:
        return self.session is not None

    def get_embedding(self, image_path: str | Path, bbox: dict) -> np.ndarray | None:
        """
        Extract a face embedding from the given bounding box region.

        Returns a normalised 1-D numpy array (float32), or *None* on error.
        """
        if not self.available:
            return None

        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]

                # Add slight padding
                pad = int(max(w, h) * 0.1)
                crop_box = (
                    max(0, x - pad),
                    max(0, y - pad),
                    min(img.width, x + w + pad),
                    min(img.height, y + h + pad),
                )
                face_img = img.crop(crop_box)
                face_img = face_img.resize(self._input_size, Image.Resampling.LANCZOS)

            arr = np.array(face_img, dtype=np.float32) / 255.0
            # Normalise (standard face recognition preprocessing)
            arr = (arr - 0.5) / 0.5

            # HWC → CHW → NCHW
            arr = np.transpose(arr, (2, 0, 1))
            arr = np.expand_dims(arr, axis=0)

            outputs = self.session.run(None, {self._input_name: arr})
            embedding = outputs[0][0].flatten().astype(np.float32)

            # L2 normalise
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            return embedding

        except Exception as exc:
            logger.debug("Face embedding extraction failed: %s", exc)
            return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two L2-normalised embeddings."""
    return float(np.dot(a, b))


def match_face(
    embedding: np.ndarray,
    known_embeddings: list[dict],
    threshold: float = 0.6,
) -> tuple[int | None, float]:
    """
    Match an embedding against known people.

    Args:
        embedding: The query face embedding (1-D, L2-normalised).
        known_embeddings: List of dicts with keys ``person_id`` and
            ``embedding`` (bytes that can be decoded to numpy).
        threshold: Minimum cosine similarity to consider a match.

    Returns:
        ``(person_id, similarity)`` of the best match, or
        ``(None, 0.0)`` if no match exceeds the threshold.
    """
    best_person_id: int | None = None
    best_sim = 0.0

    for record in known_embeddings:
        raw = record.get("embedding")
        pid = record.get("person_id")
        if raw is None or pid is None:
            continue

        try:
            known_emb = np.frombuffer(raw, dtype=np.float32)
            sim = cosine_similarity(embedding, known_emb)
            if sim > best_sim:
                best_sim = sim
                best_person_id = pid
        except Exception:
            continue

    if best_sim >= threshold:
        return best_person_id, best_sim

    return None, 0.0


def cluster_unidentified_faces(
    faces: list[dict],
    similarity_threshold: float = 0.5,
) -> list[list[dict]]:
    """
    Simple greedy cosine clustering for unidentified faces.

    Groups faces where pairwise cosine similarity exceeds the threshold.
    Returns a list of clusters, each cluster being a list of face dicts.
    """
    if not faces:
        return []

    # Extract embeddings
    face_data = []
    for f in faces:
        raw = f.get("embedding") if isinstance(f.get("embedding"), bytes) else None
        if raw is None:
            # Face without embedding — put in its own cluster
            face_data.append((f, None))
        else:
            try:
                emb = np.frombuffer(raw, dtype=np.float32)
                face_data.append((f, emb))
            except Exception:
                face_data.append((f, None))

    clusters: list[list[dict]] = []
    assigned = set()

    for i, (face_i, emb_i) in enumerate(face_data):
        if i in assigned:
            continue

        cluster = [face_i]
        assigned.add(i)

        if emb_i is None:
            clusters.append(cluster)
            continue

        for j in range(i + 1, len(face_data)):
            if j in assigned:
                continue
            _, emb_j = face_data[j]
            if emb_j is None:
                continue

            sim = cosine_similarity(emb_i, emb_j)
            if sim >= similarity_threshold:
                cluster.append(face_data[j][0])
                assigned.add(j)

        clusters.append(cluster)

    # Sort clusters by size descending
    clusters.sort(key=len, reverse=True)
    return clusters
