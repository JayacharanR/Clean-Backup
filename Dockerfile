# ── Stage 1: Rust Builder ───────────────────────────────────────────────
FROM rust:slim as rust-builder

WORKDIR /build
# Install build dependencies if needed (e.g. for maturin or setuptools-rust)
RUN apt-get update && apt-get install -y python3 python3-pip python3-venv curl

COPY phash_rs/ phash_rs/
WORKDIR /build/phash_rs
# Compile the rust extension (outputs a .so or .pyd)
# We use maturin to build a wheel, which makes it easy to install in the python image
RUN pip install maturin --break-system-packages
RUN maturin build --release -o dist

# ── Stage 2: Frontend Builder ───────────────────────────────────────────
FROM node:20-slim as frontend-builder

WORKDIR /build/web
# Copy package manifests first for caching
COPY web/package.json web/package-lock.json* ./
RUN npm ci

# Copy the rest of the frontend source
COPY web/ ./
RUN npm run build

# ── Stage 3: Python Runtime ─────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for OpenCV and ONNX
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies list and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy and install the compiled rust extension from Stage 1
COPY --from=rust-builder /build/phash_rs/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Download ONNX models so they are baked into the image
# This ensures full offline capability without runtime downloads
COPY src/classify/models/download_models.py src/classify/models/
RUN python src/classify/models/download_models.py

# Copy frontend static build from Stage 2
COPY --from=frontend-builder /build/web/dist ./web/dist

# Copy the rest of the application source
COPY . .

# Set up non-root user
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/data/db /app/data/cache /app/data/config /data/media \
    && chown -R appuser:appuser /app /data/media

USER appuser

# Expose the default port
EXPOSE 8080

# Environment variables with sane defaults
ENV CLEAN_BACKUP_MEDIA_PATH=/data/media
ENV CLEAN_BACKUP_DB_PATH=/app/data/db/clean_backup.sqlite
ENV CLEAN_BACKUP_CONFIG_DIR=/app/data/config
ENV CLEAN_BACKUP_PORT=8080
ENV CLEAN_BACKUP_LOG_LEVEL=info

# Flask entrypoint
CMD ["python", "main.py", "--web"]
