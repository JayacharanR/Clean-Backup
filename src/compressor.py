"""
Compression module for images and videos.
Supports lossless and near-lossless compression with configurable levels.
"""

import os
import subprocess
from pathlib import Path
from typing import Literal, Optional
from dataclasses import dataclass
from PIL import Image
import pillow_heif

from src.constants import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from src.logger import logger

pillow_heif.register_heif_opener()

CompressionLevel = Literal[1, 2, 3]

@dataclass
class CompressionStats:
    """Statistics for compression operations"""
    total_files: int = 0
    images_compressed: int = 0
    videos_compressed: int = 0
    skipped: int = 0
    errors: int = 0
    original_size: int = 0  # bytes
    compressed_size: int = 0  # bytes
    
    @property
    def space_saved(self) -> int:
        """Calculate space saved in bytes"""
        return self.original_size - self.compressed_size
    
    @property
    def compression_ratio(self) -> float:
        """Calculate compression ratio as percentage"""
        if self.original_size == 0:
            return 0.0
        return (1 - self.compressed_size / self.original_size) * 100


def get_compression_settings(level: CompressionLevel) -> dict:
    """
    Get compression settings based on level.
    
    Level 1: High quality, minimal compression (visually lossless)
    Level 2: Balanced quality and size (recommended)
    Level 3: Maximum compression (still good quality)
    
    Returns:
        dict: Settings for image and video compression
    """
    settings = {
        1: {
            "image_quality": 95,
            "image_optimize": True,
            "video_crf": 18,  # Visually lossless
            "description": "High Quality (minimal compression)"
        },
        2: {
            "image_quality": 85,
            "image_optimize": True,
            "video_crf": 23,  # Balanced
            "description": "Balanced (recommended)"
        },
        3: {
            "image_quality": 75,
            "image_optimize": True,
            "video_crf": 28,  # Aggressive but still good
            "description": "Maximum Compression"
        }
    }
    return settings.get(level, settings[2])


def compress_image(
    image_path: Path,
    output_path: Path,
    level: CompressionLevel = 2
) -> bool:
    """
    Compress an image file using Pillow.
    
    Args:
        image_path: Path to input image
        output_path: Path for compressed output
        level: Compression level (1=high quality, 2=balanced, 3=max compression)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        settings = get_compression_settings(level)
        
        # Open image
        with Image.open(image_path) as img:
            # Convert RGBA to RGB if saving as JPEG
            if output_path.suffix.lower() in {'.jpg', '.jpeg'}:
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
            
            # Save with compression
            save_kwargs = {
                'optimize': settings['image_optimize'],
                'quality': settings['image_quality']
            }
            
            # PNG-specific settings
            if output_path.suffix.lower() == '.png':
                save_kwargs['compress_level'] = 9  # Max PNG compression
                del save_kwargs['quality']  # PNG doesn't use quality parameter
            
            img.save(output_path, **save_kwargs)
            logger.info(f"Compressed image: {image_path.name} -> {output_path.name}")
            return True
            
    except Exception as e:
        logger.error(f"Failed to compress image {image_path}: {e}")
        return False


def compress_video(
    video_path: Path,
    output_path: Path,
    level: CompressionLevel = 2
) -> bool:
    """
    Compress a video file using FFmpeg.
    
    Args:
        video_path: Path to input video
        output_path: Path for compressed output
        level: Compression level (1=high quality, 2=balanced, 3=max compression)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if FFmpeg is available
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            timeout=5
        )
        if result.returncode != 0:
            logger.error("FFmpeg not found. Install FFmpeg to compress videos.")
            return False
        
        settings = get_compression_settings(level)
        crf = settings['video_crf']
        
        # FFmpeg command for H.264 compression
        cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-c:v', 'libx264',  # H.264 codec
            '-crf', str(crf),  # Quality level
            '-preset', 'medium',  # Encoding speed/compression tradeoff
            '-c:a', 'aac',  # Audio codec
            '-b:a', '128k',  # Audio bitrate
            '-movflags', '+faststart',  # Web optimization
            '-y',  # Overwrite output
            str(output_path)
        ]
        
        logger.info(f"Compressing video: {video_path.name} (CRF={crf})...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout per video
        )
        
        if result.returncode == 0:
            logger.info(f"Compressed video: {video_path.name} -> {output_path.name}")
            return True
        else:
            logger.error(f"FFmpeg failed for {video_path.name}: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"Video compression timeout for {video_path.name}")
        return False
    except FileNotFoundError:
        logger.error("FFmpeg not found. Install FFmpeg to compress videos.")
        return False
    except Exception as e:
        logger.error(f"Failed to compress video {video_path}: {e}")
        return False


def compress_files(
    source_dir: str,
    output_dir: str,
    level: CompressionLevel = 2,
    file_types: Literal["images", "videos", "both"] = "both"
) -> CompressionStats:
    """
    Compress all images and/or videos in a directory.
    
    Args:
        source_dir: Source directory containing media files
        output_dir: Output directory for compressed files
        level: Compression level (1-3)
        file_types: Which file types to compress
    
    Returns:
        CompressionStats: Statistics about the compression operation
    """
    source = Path(source_dir)
    output = Path(output_dir)
    
    if not source.exists():
        logger.error(f"Source directory not found: {source}")
        return CompressionStats()
    
    # Create output directory
    output.mkdir(parents=True, exist_ok=True)
    
    stats = CompressionStats()
    settings = get_compression_settings(level)
    
    logger.info(f"Starting compression with level {level}: {settings['description']}")
    logger.info(f"Source: {source}")
    logger.info(f"Output: {output}")
    
    # Collect all files
    all_files = []
    for file_path in source.rglob('*'):
        if file_path.is_file():
            ext = file_path.suffix.lower()
            
            if file_types in ("images", "both") and ext in IMAGE_EXTENSIONS:
                all_files.append(('image', file_path))
            elif file_types in ("videos", "both") and ext in VIDEO_EXTENSIONS:
                all_files.append(('video', file_path))
    
    stats.total_files = len(all_files)
    logger.info(f"Found {stats.total_files} files to compress")
    
    # Process each file
    for file_type, file_path in all_files:
        # Preserve directory structure
        rel_path = file_path.relative_to(source)
        output_path = output / rel_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Get original size
        original_size = file_path.stat().st_size
        stats.original_size += original_size
        
        success = False
        
        if file_type == 'image':
            success = compress_image(file_path, output_path, level)
            if success:
                stats.images_compressed += 1
        elif file_type == 'video':
            success = compress_video(file_path, output_path, level)
            if success:
                stats.videos_compressed += 1
        
        if success and output_path.exists():
            compressed_size = output_path.stat().st_size
            stats.compressed_size += compressed_size
            
            # Log compression result
            saved = original_size - compressed_size
            ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
            logger.info(f"  {file_path.name}: {original_size:,} -> {compressed_size:,} bytes ({ratio:.1f}% reduction)")
        else:
            stats.errors += 1
            stats.compressed_size += original_size  # Count as no compression
    
    return stats


def print_compression_summary(stats: CompressionStats):
    """Print a summary of compression results"""
    print("\n" + "="*60)
    print("COMPRESSION SUMMARY")
    print("="*60)
    print(f"Total files processed:     {stats.total_files}")
    print(f"  Images compressed:       {stats.images_compressed}")
    print(f"  Videos compressed:       {stats.videos_compressed}")
    print(f"  Errors:                  {stats.errors}")
    print(f"  Skipped:                 {stats.skipped}")
    print()
    print(f"Original size:             {stats.original_size:,} bytes ({stats.original_size / (1024**2):.2f} MB)")
    print(f"Compressed size:           {stats.compressed_size:,} bytes ({stats.compressed_size / (1024**2):.2f} MB)")
    print(f"Space saved:               {stats.space_saved:,} bytes ({stats.space_saved / (1024**2):.2f} MB)")
    print(f"Compression ratio:         {stats.compression_ratio:.2f}%")
    print("="*60)
