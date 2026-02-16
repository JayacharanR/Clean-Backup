"""
Perceptual Hashing Module for Duplicate Detection

This module provides a Python wrapper around the Rust-based phash_rs library
for fast perceptual image hashing. It gracefully falls back to a pure Python
implementation if the Rust library is not available.

Usage:
    from src.phash import find_duplicates, compute_hash, are_similar
    
    # Find all duplicates in a directory
    duplicates = find_duplicates("/path/to/images", threshold=10)
    
    # Compare two specific images
    if are_similar("image1.jpg", "image2.jpg"):
        print("Images are duplicates!")
"""

import os
from pathlib import Path
from typing import List, Dict, Optional, Literal
from dataclasses import dataclass
from src.logger import logger
from src import constants

# Try to import the Rust extension
_USE_RUST = False
try:
    import phash_rs as _phash
    _USE_RUST = True
    logger.info("Using Rust-based perceptual hashing (phash_rs)")
except ImportError:
    logger.warning("Rust phash_rs not found, using pure Python fallback (slower)")
    _phash = None

# Recommended thresholds
THRESHOLD_IDENTICAL = 0
THRESHOLD_VERY_SIMILAR = 5
THRESHOLD_SIMILAR = 10
THRESHOLD_SOMEWHAT_SIMILAR = 15


@dataclass
class DuplicateGroup:
    """Represents a group of duplicate images."""
    paths: List[str]
    hash: str
    best: str  # Path to highest resolution image
    
    def __len__(self) -> int:
        return len(self.paths)
    
    @property
    def duplicates(self) -> List[str]:
        """Return paths of duplicates (excluding the best one)."""
        return [p for p in self.paths if p != self.best]


def compute_hash(
    path: str,
    hash_size: int = 8
) -> Optional[str]:
    """
    Compute perceptual hash (pHash) of an image using DCT.
    
    Args:
        path: Path to the image file
        hash_size: Size of hash (default 8 = 64-bit hash)
    
    Returns:
        Hex string hash, or None if image couldn't be processed
    """
    if _USE_RUST:
        try:
            return _phash.compute_hash(path, hash_size)
        except Exception as e:
            logger.debug(f"Failed to hash {path}: {e}")
            return None
    else:
        return _python_compute_hash(path, hash_size)


def hamming_distance(hash1: str, hash2: str) -> int:
    """
    Compute Hamming distance between two hashes.
    
    Args:
        hash1: First hash (hex string)
        hash2: Second hash (hex string)
    
    Returns:
        Number of differing bits (0 = identical)
    """
    if _USE_RUST:
        return _phash.hamming_distance(hash1, hash2)
    else:
        return _python_hamming_distance(hash1, hash2)


def are_similar(
    path1: str,
    path2: str,
    threshold: int = THRESHOLD_SIMILAR
) -> bool:
    """
    Check if two images are perceptually similar using pHash.
    
    Args:
        path1: Path to first image
        path2: Path to second image
        threshold: Maximum Hamming distance for similarity
    
    Returns:
        True if images are similar
    """
    if _USE_RUST:
        try:
            return _phash.are_similar(path1, path2, threshold)
        except Exception:
            return False
    else:
        h1 = compute_hash(path1)
        h2 = compute_hash(path2)
        if h1 is None or h2 is None:
            return False
        return hamming_distance(h1, h2) <= threshold


def find_duplicates(
    source: str,
    threshold: int = THRESHOLD_SIMILAR,
    extensions: Optional[set] = None
) -> List[DuplicateGroup]:
    """
    Find duplicate images in a directory using pHash.
    
    Args:
        source: Directory path to scan
        threshold: Maximum Hamming distance for duplicates
        extensions: File extensions to include (default: IMAGE_EXTENSIONS)
    
    Returns:
        List of DuplicateGroup objects for each set of duplicates
    """
    if extensions is None:
        extensions = constants.IMAGE_EXTENSIONS
    
    # Collect image paths
    source_path = Path(source)
    image_paths = []
    
    for file_path in source_path.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in extensions:
            image_paths.append(str(file_path.absolute()))
    
    logger.info(f"Found {len(image_paths)} images to scan for duplicates")
    
    if not image_paths:
        return []
        
    return find_duplicates_from_paths(image_paths, threshold)


def find_duplicates_from_paths(
    image_paths: List[str],
    threshold: int = THRESHOLD_SIMILAR
) -> List[DuplicateGroup]:
    """
    Find duplicates within a provided list of image paths using pHash.
    
    Args:
        image_paths: List of absolute paths to images
        threshold: Maximum Hamming distance
        
    Returns:
        List of DuplicateGroup objects
    """
    if not image_paths:
        return []

    # Find duplicates
    if _USE_RUST:
        try:
            raw_groups = _phash.find_duplicate_images(image_paths, threshold)
            return [
                DuplicateGroup(
                    paths=g["paths"],
                    hash=g["hash"],
                    best=g["best"]
                )
                for g in raw_groups
            ]
        except Exception as e:
            logger.error(f"Rust duplicate detection failed: {e}")
            logger.info("Falling back to Python implementation")
    
    return _python_find_duplicates(image_paths, threshold)


def compute_hashes_batch(
    paths: List[str]
) -> Dict[str, str]:
    """
    Compute pHashes for multiple images (parallel if Rust available).
    
    Args:
        paths: List of image paths
    
    Returns:
        Dictionary mapping paths to their hashes
    """
    if _USE_RUST:
        try:
            return _phash.compute_hashes_parallel(paths, algorithm) # type: ignore
        except Exception as e:
            logger.error(f"Batch hashing failed: {e}")
    
    # Python fallback
    result = {}
    for path in paths:
        h = compute_hash(path, algorithm)  # type: ignore
        if h:
            result[path] = h
    return result


# ============================================================================
# Pure Python Fallback Implementation
# ============================================================================

def _python_compute_hash(
    path: str,
    hash_size: int = 8
) -> Optional[str]:
    """Pure Python pHash computation (fallback)."""
    try:
        from PIL import Image
        
        img = Image.open(path).convert('L')  # Grayscale
        return _python_phash(img, hash_size)
    except Exception as e:
        logger.debug(f"Python hash failed for {path}: {e}")
        return None


def _python_phash(img, hash_size: int) -> str:
    """Perceptual hash using DCT."""
    from PIL import Image
    import math
    
    # Resize to 32x32 for DCT
    img = img.resize((32, 32), Image.Resampling.LANCZOS)
    pixels = list(img.getdata())
    
    # Simple 2D DCT (not optimized, but works)
    dct = _simple_dct_2d(pixels, 32)
    
    # Use top-left 8x8 (excluding DC)
    coeffs = []
    for y in range(hash_size):
        for x in range(hash_size):
            if x == 0 and y == 0:
                continue
            coeffs.append(dct[y * 32 + x])
    
    median = sorted(coeffs)[len(coeffs) // 2]
    bits = ''.join('1' if c > median else '0' for c in coeffs)
    
    # Pad to hash_size^2 bits
    bits = '0' + bits  # DC placeholder
    bits = bits[:hash_size * hash_size].ljust(hash_size * hash_size, '0')
    
    return _bits_to_hex(bits)


def _simple_dct_2d(pixels: list, size: int) -> list:
    """Simple 2D DCT implementation."""
    import math
    
    # 1D DCT on rows
    temp = [0.0] * (size * size)
    for y in range(size):
        for u in range(size):
            s = 0.0
            for x in range(size):
                s += pixels[y * size + x] * math.cos(math.pi * u * (2 * x + 1) / (2 * size))
            cu = 1 / math.sqrt(2) if u == 0 else 1
            temp[y * size + u] = s * cu * math.sqrt(2 / size)
    
    # 1D DCT on columns
    result = [0.0] * (size * size)
    for x in range(size):
        for v in range(size):
            s = 0.0
            for y in range(size):
                s += temp[y * size + x] * math.cos(math.pi * v * (2 * y + 1) / (2 * size))
            cv = 1 / math.sqrt(2) if v == 0 else 1
            result[v * size + x] = s * cv * math.sqrt(2 / size)
    
    return result


def _bits_to_hex(bits: str) -> str:
    """Convert bit string to hex."""
    hex_str = ''
    for i in range(0, len(bits), 4):
        chunk = bits[i:i+4].ljust(4, '0')
        hex_str += format(int(chunk, 2), 'x')
    return hex_str


def _python_hamming_distance(hash1: str, hash2: str) -> int:
    """Compute Hamming distance between two hex hashes."""
    if len(hash1) != len(hash2):
        raise ValueError("Hashes must be same length")
    
    distance = 0
    for c1, c2 in zip(hash1, hash2):
        diff = int(c1, 16) ^ int(c2, 16)
        distance += bin(diff).count('1')
    return distance


def _python_find_duplicates(
    paths: List[str],
    threshold: int
) -> List[DuplicateGroup]:
    """Pure Python duplicate finder (fallback)."""
    from PIL import Image
    
    # Compute hashes
    image_data = []
    for path in paths:
        h = _python_compute_hash(path)
        if h:
            try:
                with Image.open(path) as img:
                    res = img.size[0] * img.size[1]
            except Exception:
                res = 0
            image_data.append((path, h, res))
    
    if not image_data:
        return []
    
    # Union-Find for grouping
    n = len(image_data)
    parent = list(range(n))
    
    def find(i):
        if parent[i] != i:
            parent[i] = find(parent[i])
        return parent[i]
    
    def union(i, j):
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pi] = pj
    
    # Compare all pairs
    for i in range(n):
        for j in range(i + 1, n):
            dist = _python_hamming_distance(image_data[i][1], image_data[j][1])
            if dist <= threshold:
                union(i, j)
    
    # Group by parent
    groups = {}
    for i in range(n):
        root = find(i)
        if root not in groups:
            groups[root] = []
        groups[root].append(i)
    
    # Convert to DuplicateGroup
    result = []
    for indices in groups.values():
        if len(indices) > 1:  # Only actual duplicates
            paths_in_group = [image_data[i][0] for i in indices]
            best_idx = max(indices, key=lambda i: image_data[i][2])
            result.append(DuplicateGroup(
                paths=sorted(paths_in_group),
                hash=image_data[indices[0]][1],
                best=image_data[best_idx][0]
            ))
    
    return result


# ============================================================================
# Convenience Functions
# ============================================================================

def is_rust_available() -> bool:
    """Check if Rust implementation is available."""
    return _USE_RUST


def get_backend() -> str:
    """Get current backend name."""
    return "rust (phash_rs)" if _USE_RUST else "python (fallback)"
