# ─── Base Image ──────────────────────────────────────────────────
# Python 3.12 slim — minimal image with only what we need.
# slim variant is ~150MB smaller than the full image.
FROM python:3.12-slim

# ─── Build Arguments ─────────────────────────────────────────────
# These can be overridden at build time with --build-arg
ARG APP_DIR=/app

# ─── Security: Non-Root User ─────────────────────────────────────
# Running as root is a security risk. Create a dedicated user.
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home appuser

# ─── System Dependencies ─────────────────────────────────────────
# curl: Required for health check probes (ECS/ALB)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ─── Working Directory ───────────────────────────────────────────
WORKDIR ${APP_DIR}

# ─── Install Python Dependencies ─────────────────────────────────
# Copy requirements first for Docker layer caching.
# Dependencies change rarely, so this layer is cached most of the time.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ─── Copy Application Code ───────────────────────────────────────
# This layer changes most frequently, so it's copied last.
COPY app/ app/

# ─── Ownership ────────────────────────────────────────────────────
RUN chown -R appuser:appuser ${APP_DIR}
USER appuser

# ─── Health Check ─────────────────────────────────────────────────
# Docker/ECS can use this to verify the container is healthy.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ─── Expose Port ──────────────────────────────────────────────────
EXPOSE 8000

# ─── Run the Server ───────────────────────────────────────────────
# Use uvicorn directly for production.
# --host 0.0.0.0 : Listen on all interfaces (required in Docker)
# --port 8000    : Must match EXPOSE and ALB target group
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
