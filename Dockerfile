# syntax=docker/dockerfile:1

# Global ARGs (must be before FROM to use in image references)
ARG UV_VERSION=0.9.22

# UV binary stage
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# Stage 1: Build frontend
FROM node:22-slim AS frontend-builder

ARG PNPM_VERSION=9.15.0
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

WORKDIR /app/frontend

# Copy frontend package files (root + workspace packages)
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
COPY frontend/packages/dashboard/package.json ./packages/dashboard/

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy frontend source
COPY frontend/ ./

# Build frontend
RUN pnpm run build


# Stage 2: Build Python backend
FROM python:3.12-slim AS backend-builder

# Install uv
COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files and README (required by hatchling)
COPY pyproject.toml uv.lock README.md ./

# Install dependencies (without project to cache this layer)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY src/ ./src/

# Install the project itself
RUN uv sync --frozen --no-dev


# Stage 3: Runtime
FROM python:3.12-slim AS runtime

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --system --gid 1001 beadhub \
    && useradd --system --uid 1001 --gid 1001 beadhub

WORKDIR /app

# Copy the virtual environment from backend builder
COPY --from=backend-builder --chown=beadhub:beadhub /app/.venv /app/.venv

# Copy source code
COPY --from=backend-builder --chown=beadhub:beadhub /app/src /app/src

# Copy built frontend from frontend builder
COPY --from=frontend-builder --chown=beadhub:beadhub /app/frontend/dist /app/frontend/dist

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER beadhub

# Default port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the server
CMD ["uvicorn", "beadhub.api:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
