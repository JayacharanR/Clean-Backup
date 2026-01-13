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
*   **Rust Acceleration**: Integrated highly concurrent Rust extension for computing image hashes, offering significant speed improvements over pure Python implementations.
*   **Cross-Directory Scanning**: Prevents importing duplicates by scanning both the source queue and the existing destination library.

### ⚙️ Configurable Heuristics
*   **Tunable Sensitivity**: User-configurable Hamming distance threshold allows fine-tuning between "Exact Match" (strict) and "Visual Similarity" (loose/aggressive) modes.
*   **Persistent Configuration**: Settings are serialized and persisted between sessions.

## 🛠️ Architecture

The project follows a modular architecture:

*   **`src/organiser.py`**: Core logic for file system operations and metadata parsing.
*   **`src/duplicate_handler.py`**: Manages duplicate detection workflows and reporting.
*   **`src/phash.py`**: Bridge interface between Python and the underlying Rust engine.
*   **`phash_rs/`**: Rust crate providing high-performance implementation of perceptual hashing algorithms (DHash/pHash).

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
*   **Pre-flight Check**: Optional perceptual scan to skip incoming files that visually match existing assets.

### Mode 2: Deduplication Utility
A standalone tool to audit folders for duplicates.
*   **Actions**: Report, Move, Copy, or Delete duplicates.
*   **Space Recovery**: Calculates potential disk space savings.

### Mode 3: Configure Sensitivity
Adjust the strictness of the duplicate detection algorithm.
*   **Exact (0-2)**: Detects only identical or near-identical images.
*   **Standard (5-7)**: Recommended. Handles format changes and minor resizing.
*   **Aggressive (10+)**: Detects cropped or heavily edited variations.

## 📊 Performance & Logging

*   **Comprehensive Reporting**: Generates statistical summaries of operations (Files scanned, duplicates skipped, data moved).
*   **Audit Logs**: Detailed execution logs stored in `logs/` for debugging and verification.

## 🤝 Contributing

Open source contributions are welcome. Please ensure tests are added for new metadata parsers or logic changes.

1.  Fork the repo.
2.  Create a feature branch (`git checkout -b feature/NewAlgo`).
3.  Commit changes.
4.  Push and create a Pull Request.

## 📄 License

Distributed under the MIT License. See ICENSE` for more information.

---
*Built by [JayacharanR](https://gthub.com/JayacharanR)*
