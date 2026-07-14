"""
Stage B — Document / Screenshot heuristic detection.

Uses metadata and simple image analysis (no ML) to identify:
- **Screenshots**: no camera EXIF + pixel dimensions match common screens
- **Documents**: tall aspect ratio + high edge density (text-like patterns)
"""

from __future__ import annotations

from src.classify.category_config import SCREEN_RESOLUTIONS
from src.classify.stage_exif import ExifData
from src.logger import logger


def detect_screenshot(exif: ExifData) -> float:
    """
    Return confidence (0.0–1.0) that the image is a screenshot.

    Signals (combined):
    - No camera Make/Model in EXIF
    - Pixel dimensions exactly match a known screen resolution
    - Software field contains screenshot-related keywords
    """
    confidence = 0.0
    signals = 0

    # Signal 1: no camera metadata
    has_camera = bool(exif.make) or bool(exif.model)

    # Signal 2: exact screen resolution match
    dims = (exif.width, exif.height)
    resolution_match = dims in SCREEN_RESOLUTIONS

    # Signal 3: software field indicates screenshot
    software_match = False
    if exif.software:
        sw_lower = exif.software.lower()
        if any(kw in sw_lower for kw in ("screenshot", "snip", "capture", "screen", "grabber", "sharex", "lightshot", "greenshot")):
            software_match = True

    # Scoring
    if not has_camera and resolution_match:
        confidence = 0.9
        signals = 2
    elif software_match:
        confidence = 0.85
        signals += 1
    elif not has_camera and not exif.has_exif and resolution_match:
        confidence = 0.8
    elif resolution_match and not has_camera:
        confidence = 0.7

    if software_match and confidence > 0:
        confidence = min(1.0, confidence + 0.05)

    return confidence


def detect_document(exif: ExifData, image_path: str | None = None) -> float:
    """
    Return confidence (0.0–1.0) that the image is a scanned document.

    Signals:
    - No camera metadata (EXIF absent or no Make/Model)
    - Aspect ratio matches standard document formats (A4, US Letter, etc.)
    - High edge density (optional, uses Pillow for basic edge analysis)
    """
    if exif.width == 0 or exif.height == 0:
        return 0.0

    confidence = 0.0
    has_camera = bool(exif.make) or bool(exif.model)

    # Aspect ratio check — documents are typically tall/narrow
    w, h = exif.width, exif.height
    # Normalize so the longer side is height
    if w > h:
        w, h = h, w

    ratio = h / w if w > 0 else 0

    # Standard document ratios (with 5% tolerance)
    doc_ratios = [
        1.4142,  # A4, A3 (ISO 216: √2)
        1.2941,  # US Letter (11/8.5)
        1.5455,  # US Legal (14/8.5)
    ]

    is_doc_ratio = any(abs(ratio - dr) / dr < 0.05 for dr in doc_ratios)

    if is_doc_ratio and not has_camera:
        confidence = 0.7
    elif is_doc_ratio:
        confidence = 0.4  # has camera metadata — less likely a document

    # Edge density analysis (basic) — documents have many horizontal edges (text lines)
    if image_path and confidence > 0.3:
        edge_conf = _analyse_edge_density(image_path)
        if edge_conf > 0:
            confidence = min(1.0, confidence + edge_conf * 0.25)

    return confidence


def _analyse_edge_density(image_path: str) -> float:
    """
    Basic edge density analysis using Pillow.

    Converts to grayscale, applies a simple edge-detection kernel,
    and measures the proportion of strong-edge pixels.

    Returns a score from 0.0 (few edges) to 1.0 (many edges).
    Documents typically score > 0.3.
    """
    try:
        from PIL import Image, ImageFilter

        with Image.open(image_path) as img:
            # Resize to speed up analysis
            img_small = img.convert("L").resize((400, 400), Image.Resampling.LANCZOS)
            edges = img_small.filter(ImageFilter.FIND_EDGES)

            # Count pixels above an intensity threshold
            edge_pixels = sum(1 for p in edges.getdata() if p > 80)
            total_pixels = 400 * 400
            density = edge_pixels / total_pixels

            return min(1.0, density * 2.5)  # Scale up — 0.4 density → 1.0 score
    except Exception as exc:
        logger.debug("Edge density analysis failed: %s", exc)
        return 0.0
