# Clean-Backup

**An intelligent, high-performance media organization automation tool featuring perceptual deduplication and hybrid Python-Rust architecture.**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![Rust](https://img.shields.io/badge/Rust-Enabled-orange) ![License](https://img.shields.io/badge/License-MIT-green)

## 📖 Overview

**Clean-Backup** is a sophisticated CLI utility designed to solve the chaos of unorganized digital media libraries. Unlike traditional organizers that rely solely on file names or modification dates, Clean-Backup employs deep metadata extraction and **perceptual hashing algorithms** to intelligently sort, categorize, and deduplicate assets.

Core engineering highlights include a **hybrid architecture** where performance-critical image analysis is offloaded to a custom **Rust** module (`phash_rs`), ensuring rapid processing of large libraries while maintaining Python's ease of use.

## 🚀 Key Technical Features

### 📂 Temporal Asset Organization
*   **Metadata-Driven Sorting**: Extracts embedded EXIF `DateTimeOriginal` (images) and container metadata (videos) to restructure files into a standardized `Year/Month` hierarchy.
*   **Smart Fallbacks**: Heuristic fallback mechanism handles missing metadata by analyzing file system stats.
*   **Cross-Format Support**: Native handling for HEIC (Apple), RAW formats (RAF), and standard web formats.

### 🔍 Perceptual Deduplication (pHash)
*   **Beyond Checksums**: Uses Perceptual Hashing (pHash) rather than binary checksums (MD5/SHA), allowing detection of "visual" duplicates even if the file has been resized, re-compressed, or converted to a different format.
*   **Rust Acceleration**: Integrated highly concurrent Rust extension for computing image hashes using DCT-based pHash algorithm, offering significant speed improvements over pure Python implementations.
*   **Cross-Directory Scanning**: Prevents importing duplicates by scanning both the source queue and the existing destination library.

### 🏷️ Name-Based Duplicate Detection
*   **OS-Specific Patterns**: Detects duplicate files based on common naming conventions used by Windows, macOS, and Linux when creating copies.
*   **Pattern Matching**: Identifies patterns like ` (1)`, ` - Copy`, ` copy`, `(Copy)`, and other OS-generated duplicate suffixes.
*   **Optional Feature**: Can be enabled independently or combined with perceptual hashing for comprehensive duplicate detection.

### ⚙️ Configurable Heuristics
*   **Tunable Sensitivity**: User-configurable Hamming distance threshold allows fine-tuning between "Exact Match" (strict) and "Visual Similarity" (loose/aggressive) modes.
*   **Persistent Configuration**: Settings are serialized and persisted between sessions.

### ↩️ Transactional Undo/Rollback
*   **Safety First**: Every file operation (Move/Copy) is logged in a persistent "Journal" transaction file.
*   **Session-Based Revert**: Allows full rollback of previous sessions, returning files to their original sources and effectively handling directory cleanup.
*   **Crash Recovery**: Journals are written immediately, ensuring "Undo" capability persists even after program restart.

## 🛠️ Architecture

The project follows a modular architecture:

*   **`src/organiser.py`**: Core logic for file system operations and metadata parsing.
*   **`src/undo_manager.py`**: Handles transaction logging and rollback logic.
*   **`src/duplicate_handler.py`**: Manages duplicate detection workflows and reporting.
*   **`src/phash.py`**: Bridge interface between Python and the underlying Rust engine.
*   **`phash_rs/`**: Rust crate providing high-performance implementation of perceptual hashing algorithm (pHash using DCT).

## 💻 Tech Stack

*   **Languages**: Python 3.12+, Rust (2021 Edition)
*   **Libraries**: 
    *   `Pillow` / `pillow-heif`: Image processing and HEIC support.
    *   `hachoir`: Video metadata extraction.
    *   `maturin`: Bridge for building Rust binaries as Python modules.

## 📥 Installation

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/JayacharanR/Clean-Backup.git
    cd Clean-Backup
    ```

2.  **Environment Setup**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    ```

    *(Note: To enable Rust acceleration, ensure the `phash_rs` module is built and installed in your environment.)*

## 🕹️ Usage

Execute the entry point:

```bash
python main.py
```

The interactive CLI provides three modes:

### Mode 1: Organize Files by Date
Scans a source directory and migrates files to a destination according to `YYYY/Month` structure.
*   **Operations**: Move or Copy.
*   **Duplicate Detection**: 
    *   **Perceptual Hashing**: Optional scan to skip incoming files that visually match existing assets.
    *   **Name-Based Detection**: Optional check for OS-generated duplicate names (e.g., `file (1).jpg`, `file - Copy.jpg`).
*   **Smart Behavior**: Keeps highest quality version when duplicates are detected; skips lower quality duplicates during organization.

### Mode 2: Deduplication Utility
A standalone tool to audit folders for duplicates.
*   **Actions**: Report, Move, Copy, or Delete duplicates.
*   **Space Recovery**: Calculates potential disk space savings.

### Mode 3: Configure Sensitivity
Adjust the strictness of the duplicate detection algorithm.
*   **Exact (0-2)**: Detects only identical or near-identical images.
*   **Standard (5-7)**: Recommended. Handles format changes and minor resizing.
*   **Aggressive (10+)**: Detects cropped or heavily edited variations.

### Mode 4: Undo Last Operation
A safety net for accidental operations.
*   **Lists Recent Sessions**: Shows a history of organization or deduplication runs.
*   **Rollback**: Moves files back to their original locations and cleans up empty year/month folders created by the tool.

## 📊 Performance & Logging

*   **Comprehensive Reporting**: Generates statistical summaries of operations (Files scanned, duplicates skipped, data moved).
*   **Audit Logs**: Detailed execution logs stored in `logs/` for debugging and verification.

## 🔬 How Perceptual Duplicate Detection Works

### Understanding Mode 1 Behavior

When you enable perceptual hashing in **Mode 1** (Organize Files by Date), the system:

1. 📂 Scans the **SOURCE** directory for images
2. 📂 Scans the **DESTINATION** directory for existing images  
3. 🔍 Identifies duplicate groups across **BOTH** directories using pHash
4. 🎯 Selects the **BEST quality** image (highest resolution) from each group
5. ⏭️  **SKIPS** moving/copying the duplicates

### Important Behaviors

**If duplicate exists in DESTINATION:**
* All source duplicates are **SKIPPED**
* Nothing is copied or moved
* Files remain in source (not organized)

**If duplicates only exist in SOURCE:**
* System keeps the best quality version
* Skips lower quality duplicates
* Only the best file is organized into destination

### Common Misconceptions

❌ **"Perceptual hashing isn't detecting duplicates"**  
→ Mode 1 **SKIPS** duplicates (leaves them in source). It doesn't move them to a "Duplicates" folder.  
→ Check logs at `logs/backup_YYYYMMDD.log` for entries like "Skipping perceptual duplicate".

❌ **"No files were organized"**  
→ If duplicates already exist in destination from a previous run, source files are correctly skipped.  
→ This is the expected behavior preventing duplicate imports.

### Mode 1 vs Mode 2

| Feature | Mode 1: Organize by Date | Mode 2: Find Duplicates |
|---------|-------------------------|------------------------|
| **Purpose** | Organize files into YYYY/Month structure | Audit and manage duplicates |
| **Duplicate Handling** | Skips duplicates during organization | Moves/copies/deletes duplicates to a folder |
| **Use Case** | Initial library setup, ongoing imports | One-time duplicate cleanup |

### Verifying It's Working

To confirm perceptual hashing is functioning:

1. Place duplicate images in source directory (test with `s/`)
2. Run Mode 1 with perceptual hashing enabled
3. Check the summary output: `"🔍 X perceptual duplicates detected (skipped)"`
4. Review logs: `tail -30 logs/backup_$(date +%Y%m%d).log | grep -i duplicate`
5. Duplicates should show "Skipping perceptual duplicate: filename"

For moving duplicates to a dedicated folder, use **Mode 2** instead.

## 🤝 Contributing

Open source contributions are welcome. Please ensure tests are added for new metadata parsers or logic changes.

1.  Fork the repo.
2.  Create a feature branch (`git checkout -b feature/NewAlgo`).
3.  Commit changes.
4.  Push and create a Pull Request.

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---
*Built by [JayacharanR](https://github.com/JayacharanR)*
