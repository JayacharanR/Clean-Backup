"""
Stage A — EXIF / metadata extraction.

Reads EXIF data from image files using Pillow and returns a structured
``ExifData`` dataclass.  No ML models are involved; this stage runs on
every file and feeds downstream stages with camera info, GPS coordinates,
keywords, and image dimensions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from PIL.ExifTags import IFD, TAGS

from src.classify.category_config import EVENT_KEYWORDS, TRAVEL_KEYWORDS
from src.logger import logger


@dataclass
class ExifData:
    """Structured EXIF metadata extracted from a single image file."""

    has_exif: bool = False
    make: str | None = None
    model: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    iso: int | None = None
    exposure_time: float | None = None
    keywords: list[str] = field(default_factory=list)
    software: str | None = None
    width: int = 0
    height: int = 0
    is_front_camera: bool = False
    datetime_original: str | None = None


def _dms_to_decimal(dms_tuple, ref: str) -> float | None:
    """Convert EXIF GPS DMS (degrees/minutes/seconds) to decimal degrees."""
    try:
        if not dms_tuple or len(dms_tuple) < 3:
            return None
        degrees = float(dms_tuple[0])
        minutes = float(dms_tuple[1])
        seconds = float(dms_tuple[2])
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except Exception:
        return None


def _safe_str(value) -> str | None:
    """Safely coerce an EXIF value to a string, returning *None* on failure."""
    if value is None:
        return None
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").strip("\x00 ")
        return str(value).strip()
    except Exception:
        return None


def extract_exif(file_path: str | Path) -> ExifData:
    """
    Extract EXIF metadata from *file_path* and return an ``ExifData`` object.

    Never raises — returns an empty ``ExifData`` on any error.
    """
    result = ExifData()
    path = Path(file_path)

    try:
        with Image.open(path) as img:
            result.width, result.height = img.size

            exif = img.getexif()
            if not exif:
                return result

            result.has_exif = True

            # Basic tags
            for tag_id, value in exif.items():
                tag_name = TAGS.get(tag_id, str(tag_id))

                if tag_name == "Make":
                    result.make = _safe_str(value)
                elif tag_name == "Model":
                    m = _safe_str(value)
                    result.model = m
                    if m and any(kw in m.lower() for kw in ("front", "selfie", "facetime")):
                        result.is_front_camera = True
                elif tag_name == "ISOSpeedRatings":
                    try:
                        result.iso = int(value)
                    except (TypeError, ValueError):
                        pass
                elif tag_name == "ExposureTime":
                    try:
                        if hasattr(value, "numerator"):
                            result.exposure_time = float(value)
                        else:
                            result.exposure_time = float(value)
                    except (TypeError, ValueError):
                        pass
                elif tag_name == "Software":
                    result.software = _safe_str(value)
                elif tag_name == "DateTimeOriginal":
                    result.datetime_original = _safe_str(value)
                elif tag_name in ("ImageDescription", "UserComment", "XPKeywords"):
                    text = _safe_str(value)
                    if text:
                        # Split on commas, semicolons, newlines
                        for kw in text.replace(";", ",").replace("\n", ",").split(","):
                            kw = kw.strip().lower()
                            if kw:
                                result.keywords.append(kw)

            # GPS IFD
            try:
                gps_ifd = exif.get_ifd(IFD.GPSInfo)
                if gps_ifd:
                    lat_dms = gps_ifd.get(2)  # GPSLatitude
                    lat_ref = gps_ifd.get(1, "N")  # GPSLatitudeRef
                    lon_dms = gps_ifd.get(4)  # GPSLongitude
                    lon_ref = gps_ifd.get(3, "E")  # GPSLongitudeRef

                    result.gps_lat = _dms_to_decimal(lat_dms, lat_ref)
                    result.gps_lon = _dms_to_decimal(lon_dms, lon_ref)
            except Exception:
                pass

    except Exception as exc:
        logger.debug("EXIF extraction failed for %s: %s", path.name, exc)

    return result


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance in km between two GPS coordinates."""
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def detect_travel(exif: ExifData, home_lat: float | None, home_lon: float | None) -> float:
    """
    Return a confidence score (0.0–1.0) for the 'travel' category.

    Signals:
    - GPS distance > 50 km from home → 0.8
    - EXIF keywords matching travel terms → 0.7
    - Both → 0.9
    """
    confidence = 0.0

    gps_travel = False
    if (
        exif.gps_lat is not None
        and exif.gps_lon is not None
        and home_lat is not None
        and home_lon is not None
    ):
        distance = haversine_km(home_lat, home_lon, exif.gps_lat, exif.gps_lon)
        if distance > 50:
            gps_travel = True
            confidence = max(confidence, 0.8)

    keyword_travel = False
    for kw in exif.keywords:
        if kw in TRAVEL_KEYWORDS:
            keyword_travel = True
            confidence = max(confidence, 0.7)
            break

    if gps_travel and keyword_travel:
        confidence = 0.9

    return confidence


def detect_events_from_exif(exif: ExifData) -> float:
    """Return confidence for 'events' category based on EXIF keywords."""
    for kw in exif.keywords:
        if kw in EVENT_KEYWORDS:
            return 0.7
    return 0.0


def detect_night_from_exif(exif: ExifData) -> float:
    """
    Return confidence for 'night' category based on EXIF exposure settings.

    High ISO (>= 3200) + long exposure (>= 1s) suggests night photography.
    """
    if exif.iso is not None and exif.exposure_time is not None:
        if exif.iso >= 3200 and exif.exposure_time >= 1.0:
            return 0.75
        if exif.iso >= 1600 and exif.exposure_time >= 0.5:
            return 0.5
    return 0.0
