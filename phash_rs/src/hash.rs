//! Perceptual Hash Implementation (pHash)
//! 
//! Implements DCT-based perceptual hashing for robust duplicate detection
//! that is resistant to resizing, format changes, and minor edits.

use image::{DynamicImage, imageops::FilterType};
use std::path::Path;

/// Hash algorithm type (only pHash supported)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HashAlgorithm {
    /// Perceptual Hash - most robust, uses DCT
    PHash,
}

/// Represents a perceptual hash of an image
#[derive(Debug, Clone)]
pub struct ImageHash {
    /// The hash bits stored as bytes
    bits: Vec<u8>,
    /// Original hash size (width/height of comparison grid)
    #[allow(dead_code)]
    size: usize,
}

impl ImageHash {
    /// Compute hash from an image file path
    pub fn from_path<P: AsRef<Path>>(path: P, algorithm: HashAlgorithm, hash_size: usize) -> Result<Self, String> {
        let img = image::open(path.as_ref())
            .map_err(|e| format!("Failed to open image: {}", e))?;
        
        Ok(Self::from_image(&img, algorithm, hash_size))
    }
    
    /// Compute hash from a loaded image (uses pHash)
    pub fn from_image(img: &DynamicImage, _algorithm: HashAlgorithm, hash_size: usize) -> Self {
        Self::compute_phash(img, hash_size)
    }
    
    /// Parse hash from hex string
    pub fn from_hex(hex: &str) -> Result<Self, String> {
        let hex = hex.trim();
        if hex.len() % 2 != 0 {
            return Err("Invalid hex string length".to_string());
        }
        
        let bits: Result<Vec<u8>, _> = (0..hex.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&hex[i..i+2], 16))
            .collect();
        
        let bits = bits.map_err(|e| format!("Invalid hex: {}", e))?;
        let size = (bits.len() * 8).isqrt();
        
        Ok(Self { bits, size })
    }
    
    /// Convert hash to hex string
    pub fn to_hex(&self) -> String {
        self.bits.iter().map(|b| format!("{:02x}", b)).collect()
    }
    
    /// Compute Hamming distance to another hash
    pub fn distance(&self, other: &ImageHash) -> u32 {
        self.bits
            .iter()
            .zip(other.bits.iter())
            .map(|(a, b)| (a ^ b).count_ones())
            .sum()
    }
    
    /// Perceptual Hash (pHash)
    /// 
    /// 1. Reduce to 32x32 grayscale
    /// 2. Apply DCT (Discrete Cosine Transform)
    /// 3. Keep top-left low frequencies
    /// 4. Compare to median
    fn compute_phash(img: &DynamicImage, hash_size: usize) -> Self {
        // Use larger size for DCT
        let dct_size = 32;
        
        let gray = img.grayscale();
        let resized = gray.resize_exact(
            dct_size as u32,
            dct_size as u32,
            FilterType::Lanczos3,
        );
        
        // Convert to f64 matrix
        let pixels: Vec<f64> = resized
            .to_luma8()
            .pixels()
            .map(|p| p.0[0] as f64)
            .collect();
        
        // Apply 2D DCT
        let dct = Self::dct_2d(&pixels, dct_size);
        
        // Extract top-left coefficients (excluding DC component)
        let mut coeffs = Vec::with_capacity(hash_size * hash_size);
        for y in 0..hash_size {
            for x in 0..hash_size {
                if x == 0 && y == 0 {
                    continue; // Skip DC component
                }
                coeffs.push(dct[y * dct_size + x]);
            }
        }
        
        // Compute median
        let mut sorted = coeffs.clone();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let median = sorted[sorted.len() / 2];
        
        // Generate hash
        let hash_bits: Vec<bool> = dct[..hash_size * hash_size]
            .iter()
            .enumerate()
            .filter(|(i, _)| *i != 0) // Skip DC
            .map(|(_, &v)| v > median)
            .collect();
        
        // Pad to hash_size * hash_size bits
        let mut padded = hash_bits;
        padded.insert(0, false); // DC component placeholder
        while padded.len() < hash_size * hash_size {
            padded.push(false);
        }
        padded.truncate(hash_size * hash_size);
        
        let bits = Self::bools_to_bytes(&padded);
        Self { bits, size: hash_size }
    }
    
    /// 2D Discrete Cosine Transform
    fn dct_2d(pixels: &[f64], size: usize) -> Vec<f64> {
        // Precompute cosine table
        let cos_table: Vec<f64> = (0..size)
            .flat_map(|u| {
                (0..size).map(move |x| {
                    ((2 * x + 1) as f64 * u as f64 * std::f64::consts::PI / (2.0 * size as f64)).cos()
                })
            })
            .collect();
        
        // Apply 1D DCT to rows
        let mut temp = vec![0.0; size * size];
        for y in 0..size {
            for u in 0..size {
                let mut sum = 0.0;
                for x in 0..size {
                    sum += pixels[y * size + x] * cos_table[u * size + x];
                }
                let cu = if u == 0 { 1.0 / 2.0_f64.sqrt() } else { 1.0 };
                temp[y * size + u] = sum * cu * (2.0 / size as f64).sqrt();
            }
        }
        
        // Apply 1D DCT to columns
        let mut result = vec![0.0; size * size];
        for x in 0..size {
            for v in 0..size {
                let mut sum = 0.0;
                for y in 0..size {
                    sum += temp[y * size + x] * cos_table[v * size + y];
                }
                let cv = if v == 0 { 1.0 / 2.0_f64.sqrt() } else { 1.0 };
                result[v * size + x] = sum * cv * (2.0 / size as f64).sqrt();
            }
        }
        
        result
    }
    
    /// Convert boolean slice to packed bytes
    fn bools_to_bytes(bools: &[bool]) -> Vec<u8> {
        bools
            .chunks(8)
            .map(|chunk| {
                chunk
                    .iter()
                    .enumerate()
                    .fold(0u8, |acc, (i, &bit)| {
                        if bit { acc | (1 << (7 - i)) } else { acc }
                    })
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_hex_roundtrip() {
        let hex = "abcdef0123456789";
        let hash = ImageHash::from_hex(hex).unwrap();
        assert_eq!(hash.to_hex(), hex);
    }
    
    #[test]
    fn test_hamming_distance() {
        let h1 = ImageHash::from_hex("ff00ff00").unwrap();
        let h2 = ImageHash::from_hex("ff00ff00").unwrap();
        assert_eq!(h1.distance(&h2), 0);
        
        let h3 = ImageHash::from_hex("ff00ff01").unwrap();
        assert_eq!(h1.distance(&h3), 1);
    }
}
