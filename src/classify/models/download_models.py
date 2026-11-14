"""
Download ONNX models required by the classification pipeline.

Usage::

    python -m src.classify.models.download_models

Downloads three models (about 275 MB in total, almost all of it the face
embedding model) from public GitHub repositories and verifies each against a
pinned SHA-256. A file that does not match is deleted and the script exits
non-zero, so a changed or tampered upstream file can never be baked into an
image. A failed download is reported but is not fatal: the pipeline skips
stages whose model is missing.
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent

# (local filename, source URL, SHA-256 of the expected file)
# The local names are historical: the scene model is MobileNetV2 and the face
# embedding model is ArcFace ResNet100.
MODELS: list[tuple[str, str, str]] = [
    (
        "mobilenetv3_small.onnx",
        "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-7.onnx",
        "c1c513582d56afceff8516c73804e484c81c6a830712ab6d682253f4a3cd042f",
    ),
    (
        "yunet.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    (
        "mobilefacenet.onnx",
        "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/arcface/model/arcfaceresnet100-8.onnx",
        "f3a6bc281e72f88862f5748b53be3d76b3b48f8f1ab1f4a537941bdc4e1b01da",
    ),
]


def _sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def download_models(force: bool = False) -> bool:
    """Download all required ONNX models to *MODELS_DIR*.

    Returns ``False`` if any file failed its checksum (it is removed).
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    verified = True

    for filename, url, expected_hash in MODELS:
        dest = MODELS_DIR / filename

        if dest.exists() and not force:
            if _sha256(dest) == expected_hash:
                print(f"  ✓ {filename} already exists — checksum OK")
                continue
            print(f"  ⚠ {filename} exists but does not match its checksum — replacing")

        print(f"  ↓ Downloading {filename} …")
        partial = dest.with_name(dest.name + ".part")
        try:
            urllib.request.urlretrieve(url, str(partial))
        except Exception as exc:
            print(f"    ✗ Download failed: {exc}")
            partial.unlink(missing_ok=True)
            continue

        actual = _sha256(partial)
        if actual != expected_hash:
            print(f"    ✗ Checksum mismatch: expected {expected_hash}, got {actual}")
            partial.unlink()
            dest.unlink(missing_ok=True)
            verified = False
            continue

        os.replace(partial, dest)
        print(f"    ✓ Saved and verified ({dest.stat().st_size / (1024 * 1024):.1f} MB)")

    return verified


if __name__ == "__main__":
    force = "--force" in sys.argv
    print("Clean-Backup — Downloading classification models\n")
    ok = download_models(force=force)
    print("\nDone." if ok else "\nA model failed verification and was removed.")
    sys.exit(0 if ok else 1)
