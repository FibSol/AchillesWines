# syntax=docker/dockerfile:1.7

# =============================================================================
# Achilles's Wines — Python scraper sidecar
# Polls ops_job_queue in the shared SQLite DB and runs scrapers.
# Target: linux/arm64 (RPi 5) and linux/amd64 (CI).
# =============================================================================

ARG PYTHON_VERSION=3.12

# ---- Stage 1: builder --------------------------------------------------------
# Wheels for httpx[http2], selectolax (Cython), playwright base, rapidfuzz.
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
WORKDIR /build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY achilles_scraper ./achilles_scraper

# Build wheels into /wheels so the runner stage doesn't need a compiler.
RUN pip install --upgrade pip wheel \
    && pip wheel --wheel-dir /wheels .


# ---- Stage 2: runner ---------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runner
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=/data/achilles.db

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tini \
        ca-certificates \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 achilles \
    && useradd  --system --uid 1001 --gid achilles --home /app achilles \
    && mkdir -p /data /app/logs \
    && chown -R achilles:achilles /data /app

# Install pre-built wheels — no compiler in the runtime image.
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels achilles-scraper \
    && rm -rf /wheels

USER achilles

# Health: the runner is alive iff it can open the shared SQLite DB.
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD sqlite3 "${DATABASE_URL}" "SELECT 1" >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["achilles-scraper", "run-jobs"]
