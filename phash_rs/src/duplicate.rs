//! Duplicate Detection Module
//! 
//! Provides functionality to find duplicate images based on perceptual hashes.

use crate::hash::{HashAlgorithm, ImageHash};
use image::GenericImageView;
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

/// Image info for duplicate detection
#[derive(Debug, Clone)]
struct ImageInfo {
    path: String,
    hash: ImageHash,
    resolution: u64, // width * height
}

/// Find duplicate images from a list of paths
pub fn find_duplicates(
    paths: &[String],
    algorithm: HashAlgorithm,
    threshold: u32,
) -> Result<Vec<DuplicateGroup>, String> {
    // Compute hashes for all images
    let mut images: Vec<ImageInfo> = Vec::new();
    
    for path in paths {
        match ImageHash::from_path(path, algorithm, 8) {
            Ok(hash) => {
                let resolution = get_image_resolution(path).unwrap_or(0);
                images.push(ImageInfo {
                    path: path.clone(),
                    hash,
                    resolution,
                });
            }
            Err(e) => {
                eprintln!("Warning: Failed to hash {}: {}", path, e);
            }
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
    // Compute hashes in parallel
    let images: Vec<ImageInfo> = paths
        .par_iter()
        .filter_map(|path| {
            ImageHash::from_path(path, algorithm, 8).ok().map(|hash| {
                let resolution = get_image_resolution(path).unwrap_or(0);
                ImageInfo {
                    path: path.clone(),
                    hash,
                    resolution,
                }
            })
        })
        .collect();
    
    group_duplicates(images, threshold)
}

/// Group images by similarity
fn group_duplicates(images: Vec<ImageInfo>, threshold: u32) -> Result<Vec<DuplicateGroup>, String> {
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
    
    // Compare all pairs and union similar images
    for i in 0..n {
        for j in (i + 1)..n {
            let dist = images[i].hash.distance(&images[j].hash);
            if dist <= threshold {
                union(&mut parent, &mut rank, i, j);
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

/// Get image resolution (width * height)
fn get_image_resolution(path: &str) -> Result<u64, String> {
    let img = image::open(path).map_err(|e| e.to_string())?;
    let (w, h) = img.dimensions();
    Ok(w as u64 * h as u64)
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_empty_input() {
        let result = find_duplicates(&[], HashAlgorithm::PHash, 10).unwrap();
        assert!(result.is_empty());
    }
}
