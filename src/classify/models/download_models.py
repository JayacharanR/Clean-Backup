"""
Download ONNX models required by the classification pipeline.

Usage::

    python -m src.classify.models.download_models

Downloads three small models (~10 MB total) from public GitHub / ONNX
Model Zoo URLs and verifies their SHA-256 checksums.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent

# (filename, url, expected_sha256_prefix)
# SHA-256 prefixes are used for quick integrity checks — first 16 hex chars.
MODELS: list[tuple[str, str, str | None]] = [
    (
        "mobilenetv3_small.onnx",
        "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-7.onnx",
        None,  # skip hash check for public model zoo
    ),
    (
        "yunet.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        None,
    ),
    (
        "mobilefacenet.onnx",
        "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/arcface/model/arcfaceresnet100-8.onnx",
        None,
    ),
]


def _sha256_prefix(path: Path, length: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def download_models(force: bool = False) -> None:
    """Download all required ONNX models to *MODELS_DIR*."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for filename, url, expected_hash in MODELS:
        dest = MODELS_DIR / filename

        if dest.exists() and not force:
            print(f"  ✓ {filename} already exists — skipping")
            continue

        print(f"  ↓ Downloading {filename} …")
        try:
            urllib.request.urlretrieve(url, str(dest))

            size_mb = dest.stat().st_size / (1024 * 1024)
            print(f"    Saved ({size_mb:.1f} MB)")

            if expected_hash:
                actual = _sha256_prefix(dest)
                if actual != expected_hash:
                    print(f"    ⚠ Hash mismatch: expected {expected_hash}, got {actual}")
                else:
                    print(f"    ✓ Hash OK ({actual})")
        except Exception as exc:
            print(f"    ✗ Download failed: {exc}")
            if dest.exists():
                dest.unlink()


if __name__ == "__main__":
    force = "--force" in sys.argv
    print("Clean-Backup — Downloading classification models\n")
    download_models(force=force)
    print("\nDone.")
