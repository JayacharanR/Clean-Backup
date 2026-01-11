#!/bin/bash
# Build script for phash_rs Rust extension
# This builds the perceptual hashing library and installs it into Python

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔨 Building phash_rs (Rust perceptual hashing library)"
echo "======================================================="

# Check for Rust
if ! command -v cargo &> /dev/null; then
    echo "❌ Rust is not installed!"
    echo ""
    echo "Install Rust with:"
    echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    echo ""
    exit 1
fi

# Check for maturin, install with uv if not found
if ! command -v maturin &> /dev/null; then
    echo "📦 Installing maturin (Rust-Python build tool)..."
    if command -v uv &> /dev/null; then
        uv pip install maturin
    else
        pip install maturin
    fi
fi

echo ""
echo "🦀 Building Rust extension..."

# Build in release mode (development install)
maturin develop --release

echo ""
echo "✅ phash_rs installed successfully!"
echo ""
echo "Test with:"
echo "  python -c \"import phash_rs; print('phash_rs loaded!')\""
