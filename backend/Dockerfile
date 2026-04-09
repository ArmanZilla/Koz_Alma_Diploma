# ──────────────────────────────────────────────────────────────────────
# KozAlma AI — Backend Dockerfile
#
# Multi-stage build for a production-ready FastAPI + ML backend.
# Includes system deps for OpenCV, torch, and Piper TTS.
#
# Usage:
#   docker build -t kozalma-backend .
#   docker run -p 8000:8000 --env-file .env kozalma-backend
# ──────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies required by OpenCV, torch, Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install Python dependencies ──
# Copy requirements first for Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Copy application code ──
COPY app/ ./app/

# ── Create directories for volume mounts ──
RUN mkdir -p weights models

# ── Expose port ──
EXPOSE 8000

# ── Healthcheck ──
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Default command ──
# Use 1 worker for ML (models are loaded in-process).
# For CPU-bound ML inference, multiple workers would duplicate model memory.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
