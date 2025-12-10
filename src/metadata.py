import os
from datetime import datetime

from PIL import Image
from PIL.ExifTags import TAGS
from pillow_heif import register_heif_opener

from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from src.logger import logger

register_heif_opener()

def get_image_date(file_path):
    try:
        with Image.open(file_path) as img:
            exif_data = img.getexif()
            if not exif_data:
                return None
                
            # Look for datetime
            for tag_id, value in exif_data.items():
                tag_name = TAGS.get(tag_id, tag_id)
                if tag_name == 'DateTimeOriginal':
                    # Format - "YYYY:MM:DD HH:MM:SS"
                    return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
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