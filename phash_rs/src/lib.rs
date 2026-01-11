//! Perceptual Image Hashing Library
//! 
//! This library provides fast perceptual hashing algorithms for detecting
//! visually similar or duplicate images, even when they differ in:
//! - Resolution
//! - Format (JPG, PNG, etc.)
//! - Minor edits or compression artifacts
//! 
//! Supported algorithms:
//! - aHash (Average Hash): Fast, good for identical images
//! - dHash (Difference Hash): Good for detecting similar images
//! - pHash (Perceptual Hash): Most robust, uses DCT

mod hash;
mod duplicate;

use pyo3::prelude::*;
use pyo3::conversion::ToPyObject;
use std::collections::HashMap;

pub use hash::{ImageHash, HashAlgorithm};
pub use duplicate::{DuplicateGroup, find_duplicates, find_duplicates_parallel};

/// Compute the perceptual hash of an image file.
/// 
/// Args:
///     path: Path to the image file
///     algorithm: Hash algorithm - "ahash", "dhash", or "phash" (default: "phash")
///     hash_size: Size of the hash (default: 8, produces 64-bit hash)
/// 
/// Returns:
///     Hex string representation of the hash
#[pyfunction]
#[pyo3(signature = (path, algorithm = "phash", hash_size = 8))]
fn compute_hash(path: &str, algorithm: &str, hash_size: usize) -> PyResult<String> {
    let algo = match algorithm.to_lowercase().as_str() {
        "ahash" | "average" => HashAlgorithm::AHash,
        "dhash" | "difference" => HashAlgorithm::DHash,
        "phash" | "perceptual" => HashAlgorithm::PHash,
        _ => return Err(pyo3::exceptions::PyValueError::new_err(
            format!("Unknown algorithm: {}. Use 'ahash', 'dhash', or 'phash'", algorithm)
        )),
    };
    
    let hash = ImageHash::from_path(path, algo, hash_size)
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

/// Check if two images are perceptually similar.
/// 
/// Args:
///     path1: Path to first image
///     path2: Path to second image
///     threshold: Maximum Hamming distance to consider similar (default: 10)
///     algorithm: Hash algorithm to use (default: "phash")
/// 
/// Returns:
///     True if images are similar, False otherwise
#[pyfunction]
#[pyo3(signature = (path1, path2, threshold = 10, algorithm = "phash"))]
fn are_similar(path1: &str, path2: &str, threshold: u32, algorithm: &str) -> PyResult<bool> {
    let algo = match algorithm.to_lowercase().as_str() {
        "ahash" | "average" => HashAlgorithm::AHash,
        "dhash" | "difference" => HashAlgorithm::DHash,
        "phash" | "perceptual" => HashAlgorithm::PHash,
        _ => return Err(pyo3::exceptions::PyValueError::new_err(
            format!("Unknown algorithm: {}", algorithm)
        )),
    };
    
    let hash1 = ImageHash::from_path(path1, algo, 8)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
    let hash2 = ImageHash::from_path(path2, algo, 8)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
    
    Ok(hash1.distance(&hash2) <= threshold)
}

/// Find duplicate images in a list of file paths.
/// 
/// Args:
///     paths: List of image file paths to check
///     threshold: Maximum Hamming distance for duplicates (default: 10)
///     algorithm: Hash algorithm to use (default: "phash")
/// 
/// Returns:
///     List of duplicate groups, each containing:
///     - "paths": List of file paths in this duplicate group
///     - "hash": The representative hash for this group
///     - "best": Path to the highest resolution image in the group
#[pyfunction]
#[pyo3(signature = (paths, threshold = 10, algorithm = "phash"))]
fn find_duplicate_images(
    paths: Vec<String>,
    threshold: u32,
    algorithm: &str,
) -> PyResult<Vec<HashMap<String, PyObject>>> {
    let algo = match algorithm.to_lowercase().as_str() {
        "ahash" | "average" => HashAlgorithm::AHash,
        "dhash" | "difference" => HashAlgorithm::DHash,
        "phash" | "perceptual" => HashAlgorithm::PHash,
        _ => return Err(pyo3::exceptions::PyValueError::new_err(
            format!("Unknown algorithm: {}", algorithm)
        )),
    };
    
    let groups = find_duplicates_parallel(&paths, algo, threshold)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
    
    Python::with_gil(|py| {
        let result: Vec<HashMap<String, PyObject>> = groups
            .into_iter()
            .filter(|g| g.paths.len() > 1) // Only return actual duplicates
            .map(|g| {
                let mut map = HashMap::new();
                map.insert("paths".to_string(), g.paths.clone().to_object(py));
                map.insert("hash".to_string(), g.hash.to_object(py));
                map.insert("best".to_string(), g.best_path.to_object(py));
                map
            })
            .collect();
        Ok(result)
    })
}

/// Compute hashes for multiple images in parallel.
/// 
/// Args:
///     paths: List of image file paths
///     algorithm: Hash algorithm to use (default: "phash")
/// 
/// Returns:
///     Dictionary mapping file paths to their hash strings.
///     Failed images are excluded from the result.
#[pyfunction]
#[pyo3(signature = (paths, algorithm = "phash"))]
fn compute_hashes_parallel(
    paths: Vec<String>,
    algorithm: &str,
) -> PyResult<HashMap<String, String>> {
    use rayon::prelude::*;
    
    let algo = match algorithm.to_lowercase().as_str() {
        "ahash" | "average" => HashAlgorithm::AHash,
        "dhash" | "difference" => HashAlgorithm::DHash,
        "phash" | "perceptual" => HashAlgorithm::PHash,
        _ => return Err(pyo3::exceptions::PyValueError::new_err(
            format!("Unknown algorithm: {}", algorithm)
        )),
    };
    
    let results: HashMap<String, String> = paths
        .par_iter()
        .filter_map(|path| {
            ImageHash::from_path(path, algo, 8)
                .ok()
                .map(|h| (path.clone(), h.to_hex()))
        })
        .collect();
    
    Ok(results)
}

/// Python module definition
#[pymodule]
fn phash_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_hash, m)?)?;
    m.add_function(wrap_pyfunction!(hamming_distance, m)?)?;
    m.add_function(wrap_pyfunction!(are_similar, m)?)?;
    m.add_function(wrap_pyfunction!(find_duplicate_images, m)?)?;
    m.add_function(wrap_pyfunction!(compute_hashes_parallel, m)?)?;
    
    // Add constants for recommended thresholds
    m.add("THRESHOLD_IDENTICAL", 0)?;
    m.add("THRESHOLD_VERY_SIMILAR", 5)?;
    m.add("THRESHOLD_SIMILAR", 10)?;
    m.add("THRESHOLD_SOMEWHAT_SIMILAR", 15)?;
    
    Ok(())
}
