# Minimal, production-oriented image for OrbitMind (Phase 0/1).
# Uses the Python 3.12 production baseline (ADR-0002). SQLite by default; no Redis,
# Temporal, or PostgreSQL required for this phase.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime dependencies first (better layer caching).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Bundled sample data + migrations are needed at runtime.
COPY data ./data
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

# Run as a non-root user.
RUN useradd --create-home --uid 10001 orbit \
    && mkdir -p /app/artifacts /app/data \
    && chown -R orbit:orbit /app
USER orbit

ENV ORBITMIND_DATABASE_URL=sqlite:///./data/orbitmind.db \
    ORBITMIND_ARTIFACTS_DIR=/app/artifacts

EXPOSE 8000

# Apply migrations, then serve. (The app also create_all()s on startup as a fallback.)
CMD ["sh", "-c", "alembic upgrade head && uvicorn orbitmind.api.app:app --host 0.0.0.0 --port 8000"]
