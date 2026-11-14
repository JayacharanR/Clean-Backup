//! Perceptual Image Hashing Library
//!
//! This library provides fast perceptual hashing (pHash) for detecting
//! visually similar or duplicate images, even when they differ in:
//! - Resolution
//! - Format (JPG, PNG, etc.)
//! - Minor edits or compression artifacts
//!
//! Uses DCT-based perceptual hashing for robustness.

#![allow(clippy::useless_conversion)]

mod duplicate;
mod hash;

use pyo3::conversion::ToPyObject;
use pyo3::prelude::*;
use std::collections::HashMap;

pub use duplicate::{
    find_duplicates, find_duplicates_parallel, group_duplicates, hash_images_parallel,
    DuplicateGroup, ImageInfo,
};
pub use hash::{HashAlgorithm, ImageHash};

/// Compute the perceptual hash (pHash) of an image file.
///
/// Args:
///     path: Path to the image file
///     hash_size: Size of the hash (default: 8, produces 64-bit hash)
///
/// Returns:
///     Hex string representation of the hash
#[pyfunction]
#[pyo3(signature = (path, hash_size = 8))]
fn compute_hash(path: &str, hash_size: usize) -> PyResult<String> {
    let hash = ImageHash::from_path(path, HashAlgorithm::PHash, hash_size)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;

    Ok(hash.to_hex())
}

/// Compute the Hamming distance between two hash strings.
///
/// Args:
///     hash1: First hash as hex string
///     hash2: Second hash as hex string
///
/// Returns:
///     Number of differing bits (0 = identical, higher = more different)
#[pyfunction]
fn hamming_distance(hash1: &str, hash2: &str) -> PyResult<u32> {
    let h1 = ImageHash::from_hex(hash1)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let h2 = ImageHash::from_hex(hash2)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    Ok(h1.distance(&h2))
}

/// Check if two images are perceptually similar using pHash.
///
/// Args:
///     path1: Path to first image
///     path2: Path to second image
///     threshold: Maximum Hamming distance to consider similar (default: 10)
///
/// Returns:
///     True if images are similar, False otherwise
#[pyfunction]
#[pyo3(signature = (path1, path2, threshold = 10))]
fn are_similar(path1: &str, path2: &str, threshold: u32) -> PyResult<bool> {
    let hash1 = ImageHash::from_path(path1, HashAlgorithm::PHash, 8)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
    let hash2 = ImageHash::from_path(path2, HashAlgorithm::PHash, 8)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;

    Ok(hash1.distance(&hash2) <= threshold)
}

/// Find duplicate images in a list of file paths using pHash.
///
/// Args:
///     paths: List of image file paths to check
///     threshold: Maximum Hamming distance for duplicates (default: 10)
///
/// Returns:
///     List of duplicate groups, each containing:
///     - "paths": List of file paths in this duplicate group
///     - "hash": The representative hash for this group
///     - "best": Path to the highest resolution image in the group
#[pyfunction]
#[pyo3(signature = (paths, threshold = 10))]
fn find_duplicate_images(
    py: Python<'_>,
    paths: Vec<String>,
    threshold: u32,
) -> PyResult<Vec<HashMap<String, PyObject>>> {
    // Decoding and hashing touch no Python objects: let other threads run.
    let groups =
        py.allow_threads(|| find_duplicates_parallel(&paths, HashAlgorithm::PHash, threshold));
    groups_to_python(py, groups)
}

fn groups_to_python(
    py: Python<'_>,
    groups: Result<Vec<DuplicateGroup>, String>,
) -> PyResult<Vec<HashMap<String, PyObject>>> {
    let groups = groups.map_err(pyo3::exceptions::PyRuntimeError::new_err)?;

    Ok(groups
        .into_iter()
        .filter(|g| g.paths.len() > 1) // Only return actual duplicates
        .map(|g| {
            let mut map = HashMap::new();
            map.insert("paths".to_string(), g.paths.to_object(py));
            map.insert("hash".to_string(), g.hash.to_object(py));
            map.insert("best".to_string(), g.best_path.to_object(py));
            map
        })
        .collect())
}

/// Compute pHash and pixel count (width * height) for many images in parallel.
///
/// Each file is decoded once. Use with `group_hashes` to report progress
/// between hashing batches without hashing anything twice.
///
/// Returns:
///     Dictionary mapping file paths to `(hash, resolution)`.
///     Failed images are excluded from the result.
#[pyfunction]
#[pyo3(signature = (paths))]
fn compute_hashes_with_resolution(
    py: Python<'_>,
    paths: Vec<String>,
) -> HashMap<String, (String, u64)> {
    py.allow_threads(|| {
        hash_images_parallel(&paths, HashAlgorithm::PHash)
            .into_iter()
            .map(|info| (info.path, (info.hash.to_hex(), info.resolution)))
            .collect()
    })
}

/// Group already-hashed images into duplicate sets without reading any file.
///
/// Args:
///     items: List of `(path, hash, resolution)` tuples
///     threshold: Maximum Hamming distance for duplicates (default: 10)
///
/// Returns:
///     Same structure as `find_duplicate_images`.
#[pyfunction]
#[pyo3(signature = (items, threshold = 10))]
fn group_hashes(
    py: Python<'_>,
    items: Vec<(String, String, u64)>,
    threshold: u32,
) -> PyResult<Vec<HashMap<String, PyObject>>> {
    let images = items
        .into_iter()
        .map(|(path, hex, resolution)| {
            ImageHash::from_hex(&hex).map(|hash| ImageInfo {
                path,
                hash,
                resolution,
            })
        })
        .collect::<Result<Vec<_>, _>>()
        .map_err(pyo3::exceptions::PyValueError::new_err)?;

    let groups = py.allow_threads(|| group_duplicates(images, threshold));
    groups_to_python(py, groups)
}

/// Compute pHashes for multiple images in parallel.
///
/// Args:
///     paths: List of image file paths
///
/// Returns:
///     Dictionary mapping file paths to their hash strings.
///     Failed images are excluded from the result.
#[pyfunction]
#[pyo3(signature = (paths))]
fn compute_hashes_parallel(py: Python<'_>, paths: Vec<String>) -> HashMap<String, String> {
    use rayon::prelude::*;

    py.allow_threads(|| {
        paths
            .par_iter()
            .filter_map(|path| {
                ImageHash::from_path(path, HashAlgorithm::PHash, 8)
                    .ok()
                    .map(|h| (path.clone(), h.to_hex()))
            })
            .collect()
    })
}

/// Python module definition
#[pymodule]
fn phash_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_hash, m)?)?;
    m.add_function(wrap_pyfunction!(hamming_distance, m)?)?;
    m.add_function(wrap_pyfunction!(are_similar, m)?)?;
    m.add_function(wrap_pyfunction!(find_duplicate_images, m)?)?;
    m.add_function(wrap_pyfunction!(compute_hashes_parallel, m)?)?;
    m.add_function(wrap_pyfunction!(compute_hashes_with_resolution, m)?)?;
    m.add_function(wrap_pyfunction!(group_hashes, m)?)?;

    // Add constants for recommended thresholds
    m.add("THRESHOLD_IDENTICAL", 0)?;
    m.add("THRESHOLD_VERY_SIMILAR", 5)?;
    m.add("THRESHOLD_SIMILAR", 10)?;
    m.add("THRESHOLD_SOMEWHAT_SIMILAR", 15)?;

    Ok(())
}
