import os
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import IFD
from pillow_heif import register_heif_opener

from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from src import constants
from src.logger import logger

register_heif_opener()

_DATETIME_ORIGINAL = 0x9003
_DATETIME_DIGITIZED = 0x9004


def _parse_exif_datetime(value):
    """Parse EXIF "YYYY:MM:DD HH:MM:SS"; return None for absent or blank values."""
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def get_image_date(file_path):
    try:
        with Image.open(file_path) as img:
            exif_data = img.getexif()
            if not exif_data:
                return None

            # Cameras store capture times in the Exif sub-IFD; a few writers
            # put them in the top-level IFD, so check both.
            exif_ifd = exif_data.get_ifd(IFD.Exif)
            for tag_id in (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED):
                for ifd in (exif_ifd, exif_data):
                    parsed = _parse_exif_datetime(ifd.get(tag_id))
                    if parsed:
                        return parsed
    except Exception as e:
        logger.warning(f"Could not read EXIF for image {file_path}: {e}")
    return None

def get_video_date(file_path):
    try:
        parser = createParser(file_path)
        if not parser:
            return None

        #get creation date
        with parser:
            metadata = extractMetadata(parser)
            if metadata and metadata.has("creation_date"):
                return metadata.get("creation_date")
    except Exception as e:
        logger.warning(f"Could not read metadata for video {file_path}: {e}")
    return None

#return current system DateTime is no DateTime is extracted or available
def get_file_modification_date(file_path):
    return datetime.fromtimestamp(os.path.getmtime(file_path))


def get_media_date(file_path):
    """Capture date from image/video metadata, else the file's modification time."""
    ext = Path(file_path).suffix.lower()
    taken = None
    if ext in constants.IMAGE_EXTENSIONS:
        taken = get_image_date(str(file_path))
    elif ext in constants.VIDEO_EXTENSIONS:
        taken = get_video_date(str(file_path))
    return taken or get_file_modification_date(str(file_path))
