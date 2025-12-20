# OctoLab Backend Dockerfile
# ==========================
#
# Multi-stage build for FastAPI backend with Alembic migrations.
#
# Build: docker build -t octolab-backend ./backend
# Run: docker run -p 8000:8000 --env-file .env.prod octolab-backend

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
# Copy app/ first since pyproject.toml references it for package discovery
COPY pyproject.toml ./
COPY app/ ./app/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for running the app
RUN groupadd -r octolab && useradd -r -g octolab octolab

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Ensure the octolab user can read application files
RUN chown -R octolab:octolab /app

# Create directories that will be mounted as volumes
# These are placeholders - actual paths come from volume mounts
RUN mkdir -p /var/lib/octolab /run/octolab && \
    chown -R octolab:octolab /var/lib/octolab /run/octolab

# Switch to non-root user for running the app
# Note: Some operations (like netd socket access) may require
# the octolab user to be in the octolab group on the host
USER octolab

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command - run uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
