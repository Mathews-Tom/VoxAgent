# .dockerignore should include:
#   .git
#   .venv
#   __pycache__
#   *.pyc
#   *.pyo
#   .pytest_cache
#   .mypy_cache
#   .ruff_cache
#   tests/
#   widget/
#   *.md
#   .env*
#   !.env.example

# ─── Stage 1: builder ────────────────────────────────────────────────────────

FROM python:3.12-slim AS builder

# System deps required to build C extensions (asyncpg, lxml, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY pyproject.toml ./
# uv.lock is copied if it exists; without it uv resolves fresh
COPY uv.lock* ./

# Install production deps into an isolated venv
RUN uv sync --frozen --no-dev

# Copy source and migrations
COPY voxagent/ ./voxagent/
COPY migrations/ ./migrations/

# ─── Stage 2: runtime ────────────────────────────────────────────────────────

FROM python:3.12-slim AS runtime

LABEL maintainer="AetherForge <aetherforge@druk.dev>"

# Runtime shared libraries only (no compiler, no headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the populated virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source and database migrations
COPY --from=builder /app/voxagent ./voxagent/
COPY --from=builder /app/migrations ./migrations/
COPY --from=builder /app/pyproject.toml ./

# Put the venv on PATH so all executables (uvicorn, voxagent CLI) are found
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# Default: run the FastAPI server.
# Override CMD to run the LiveKit agent worker:
#   docker run ... python -m voxagent.main
CMD ["uvicorn", "voxagent.server.app:app", "--host", "0.0.0.0", "--port", "8080"]
