# phash_rs - Perceptual Image Hashing Library

Fast perceptual image hashing library written in Rust with Python bindings.

## Features

- **DCT-based pHash** (64-bit), robust to resizing, recompression and format changes
- **Formats:** JPEG, PNG, GIF, BMP, TIFF and WebP (other codecs are not compiled in)
- **One decode per image**: hash and resolution are computed together, and
  grouping works on those results without reopening files
- **Releases the GIL** while hashing, so other Python threads keep running

- **Parallel processing** using Rayon for multi-core systems
- **Pure Python fallback** if Rust extension is unavailable
- **Finds duplicates** even when images differ in resolution or format

## Building

### Prerequisites

1. **Rust** (1.70+):
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```

2. **maturin** (Python-Rust build tool):
   ```bash
   pip install maturin
   ```

### Build & Install

```bash
cd phash_rs
chmod +x build.sh
./build.sh
```

Or manually:

```bash
cd phash_rs
maturin build --release
pip install target/wheels/*.whl
```

### Development Mode

For development (recompiles on import):

```bash
cd phash_rs
maturin develop --release
```

## Usage

### From Python

```python
import phash_rs

# Compute hash of single image
hash = phash_rs.compute_hash("image.jpg")
print(f"Hash: {hash}")

# Compare two images
similar = phash_rs.are_similar("img1.jpg", "img2.jpg", threshold=10)
print(f"Similar: {similar}")

# Find duplicates in a list of images
paths = ["img1.jpg", "img2.jpg", "img3.jpg", "img4.jpg"]
duplicates = phash_rs.find_duplicate_images(paths, threshold=10)
for group in duplicates:
    print(f"Duplicate group: {group['paths']}")
    print(f"Best quality: {group['best']}")

# Batch hash computation (parallel)
hashes = phash_rs.compute_hashes_parallel(paths)

# Hash in batches (e.g. to report progress), then group without re-reading files
hashed = phash_rs.compute_hashes_with_resolution(paths)   # {path: (hash, width*height)}
groups = phash_rs.group_hashes([(p, h, res) for p, (h, res) in hashed.items()], threshold=10)
```

### Using the Python Wrapper

```python
from src.phash import find_duplicates, are_similar, get_backend

# Check which backend is being used
print(f"Using: {get_backend()}")

# Find duplicates in a directory
duplicates = find_duplicates("/path/to/photos", threshold=10)
for group in duplicates:
    print(f"Found {len(group)} duplicates")
    print(f"Keep: {group.best}")
    print(f"Remove: {group.duplicates}")
```

### Using the Duplicate Handler

```python
from src.duplicate_handler import handle_duplicates, print_duplicate_report

# Just report duplicates (no changes)
report = handle_duplicates("/path/to/photos", action="report")
print_duplicate_report(report)

# Move duplicates to a folder
report = handle_duplicates(
    "/path/to/photos",
    duplicates_dir="/path/to/duplicates",
    action="move"
)

# Delete duplicates (keeps best quality)
report = handle_duplicates("/path/to/photos", action="delete")
```

## Threshold Guide

| Threshold | Meaning |
|-----------|---------|
| 0 | Identical (bit-perfect match) |
| 1-5 | Very similar (same image, minor compression) |
| 6-10 | Similar (same image, different quality/size) |
| 11-15 | Somewhat similar (may be same subject) |
| 16+ | Probably different images |

## Algorithm Comparison

| Algorithm | Speed | Accuracy | Best For |
|-----------|-------|----------|----------|
| aHash | Fastest | Good | Exact duplicates |
| dHash | Fast | Better | General duplicate detection |
| pHash | Slower | Best | Robust detection across formats |

## Troubleshooting

### Rust extension not loading

If you see "using pure Python fallback", the Rust extension isn't installed:

```bash
cd phash_rs
./build.sh
```

### Build errors

Make sure you have:
- Rust toolchain installed
- Python development headers (`python3-dev` on Ubuntu)

### Performance

For best performance:
- Use the Rust extension (not Python fallback)
- Use `find_duplicate_images` for batch operations
- Use `threshold=10` as a good default

## Architecture

```
phash_rs/
├── Cargo.toml          # Rust dependencies
├── pyproject.toml      # Python build config
├── build.sh            # Build script
├── src/
│   ├── lib.rs          # PyO3 Python bindings
│   ├── hash.rs         # Hash algorithms (aHash, dHash, pHash)
│   └── duplicate.rs    # Duplicate detection logic
```

## License

MIT
