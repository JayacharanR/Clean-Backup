//! Duplicate Detection Module
//!
//! Provides functionality to find duplicate images based on perceptual hashes.

use crate::hash::{HashAlgorithm, ImageHash};
use rayon::prelude::*;
use std::collections::HashMap;

/// Represents a group of duplicate images
#[derive(Debug, Clone)]
pub struct DuplicateGroup {
    /// All file paths in this duplicate group
    pub paths: Vec<String>,
    /// The representative hash for this group
    pub hash: String,
    /// Path to the best (highest resolution) image
    pub best_path: String,
}

/// A hashed image: everything grouping needs, with no further file access.
#[derive(Debug, Clone)]
pub struct ImageInfo {
    pub path: String,
    pub hash: ImageHash,
    /// width * height
    pub resolution: u64,
}

fn hash_one(path: &str, algorithm: HashAlgorithm) -> Result<ImageInfo, String> {
    let (hash, resolution) = ImageHash::from_path_with_resolution(path, algorithm, 8)?;
    Ok(ImageInfo {
        path: path.to_string(),
        hash,
        resolution,
    })
}

/// Hash images in parallel, decoding each file exactly once.
/// Files that cannot be decoded are omitted.
pub fn hash_images_parallel(paths: &[String], algorithm: HashAlgorithm) -> Vec<ImageInfo> {
    paths
        .par_iter()
        .filter_map(|path| hash_one(path, algorithm).ok())
        .collect()
}

/// Find duplicate images from a list of paths
pub fn find_duplicates(
    paths: &[String],
    algorithm: HashAlgorithm,
    threshold: u32,
) -> Result<Vec<DuplicateGroup>, String> {
    let mut images: Vec<ImageInfo> = Vec::new();

    for path in paths {
        match hash_one(path, algorithm) {
            Ok(info) => images.push(info),
            Err(e) => eprintln!("Warning: Failed to hash {}: {}", path, e),
        }
    }

    group_duplicates(images, threshold)
}

/// Find duplicate images using parallel processing
pub fn find_duplicates_parallel(
    paths: &[String],
    algorithm: HashAlgorithm,
    threshold: u32,
) -> Result<Vec<DuplicateGroup>, String> {
    group_duplicates(hash_images_parallel(paths, algorithm), threshold)
}

/// Group already-hashed images by similarity
pub fn group_duplicates(
    images: Vec<ImageInfo>,
    threshold: u32,
) -> Result<Vec<DuplicateGroup>, String> {
    if images.is_empty() {
        return Ok(Vec::new());
    }

    // Union-Find structure for grouping
    let n = images.len();
    let mut parent: Vec<usize> = (0..n).collect();
    let mut rank: Vec<usize> = vec![0; n];

    // Find with path compression
    fn find(parent: &mut [usize], i: usize) -> usize {
        if parent[i] != i {
            parent[i] = find(parent, parent[i]);
        }
        parent[i]
    }

    // Union by rank
    fn union(parent: &mut [usize], rank: &mut [usize], i: usize, j: usize) {
        let pi = find(parent, i);
        let pj = find(parent, j);
        if pi != pj {
            if rank[pi] < rank[pj] {
                parent[pi] = pj;
            } else if rank[pi] > rank[pj] {
                parent[pj] = pi;
            } else {
                parent[pj] = pi;
                rank[pi] += 1;
            }
        }
    }

    // Compare all pairs and union similar images. Standard 64-bit hashes are
    // compared as single words (one XOR + popcount per pair).
    let words: Option<Vec<u64>> = images.iter().map(|image| image.hash.as_u64()).collect();
    match words {
        Some(words) => {
            for i in 0..n {
                let word = words[i];
                for (j, other) in words.iter().enumerate().skip(i + 1) {
                    if (word ^ other).count_ones() <= threshold {
                        union(&mut parent, &mut rank, i, j);
                    }
                }
            }
        }
        None => {
            for i in 0..n {
                for j in (i + 1)..n {
                    if images[i].hash.distance(&images[j].hash) <= threshold {
                        union(&mut parent, &mut rank, i, j);
                    }
                }
            }
        }
    }

    // Group by parent
    let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
    for i in 0..n {
        let root = find(&mut parent, i);
        groups.entry(root).or_default().push(i);
    }

    // Convert to DuplicateGroup
    let result: Vec<DuplicateGroup> = groups
        .into_values()
        .map(|indices| {
            let mut paths: Vec<String> = indices.iter().map(|&i| images[i].path.clone()).collect();

            // Find best (highest resolution) image
            let best_idx = indices
                .iter()
                .max_by_key(|&&i| images[i].resolution)
                .copied()
                .unwrap_or(indices[0]);

            let best_path = images[best_idx].path.clone();
            let hash = images[indices[0]].hash.to_hex();

            // Sort paths for consistent output
            paths.sort();

            DuplicateGroup {
                paths,
                hash,
                best_path,
            }
        })
        .collect();

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn info(path: &str, hex: &str, resolution: u64) -> ImageInfo {
        ImageInfo {
            path: path.to_string(),
            hash: ImageHash::from_hex(hex).unwrap(),
            resolution,
        }
    }

    #[test]
    fn test_empty_input() {
        let result = find_duplicates(&[], HashAlgorithm::PHash, 10).unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn test_groups_precomputed_hashes_and_picks_largest() {
        let images = vec![
            info("small.jpg", "ff00ff00ff00ff00", 100),
            info("large.jpg", "ff00ff00ff00ff01", 400),
            info("other.jpg", "00ff00ff00ff00ff", 900),
        ];
        let mut groups = group_duplicates(images, 2).unwrap();
        groups.sort_by_key(|g| g.paths.len());

        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].paths, vec!["other.jpg"]);
        assert_eq!(groups[1].paths, vec!["large.jpg", "small.jpg"]);
        assert_eq!(groups[1].best_path, "large.jpg");
    }

    #[test]
    fn test_threshold_zero_only_groups_identical_hashes() {
        let images = vec![
            info("a.jpg", "ff00ff00ff00ff00", 1),
            info("b.jpg", "ff00ff00ff00ff00", 2),
            info("c.jpg", "ff00ff00ff00ff01", 3),
        ];
        let groups = group_duplicates(images, 0).unwrap();
        assert_eq!(groups.iter().filter(|g| g.paths.len() == 2).count(), 1);
        assert_eq!(groups.iter().filter(|g| g.paths.len() == 1).count(), 1);
    }
}
