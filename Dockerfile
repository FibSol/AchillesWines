# syntax=docker/dockerfile:1.7

# =============================================================================
# Achilles's Wines — web container (Next.js 16 + React 19 + better-sqlite3)
# Multi-stage build: deps -> builder -> runner.
# Target: linux/arm64 (Raspberry Pi 5) and linux/amd64 (CI).
# =============================================================================

ARG NODE_VERSION=24

# ---- Stage 1: deps -----------------------------------------------------------
# Native build tools needed because better-sqlite3 compiles from source.
FROM node:${NODE_VERSION}-bookworm-slim AS deps
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        make \
        g++ \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
# `npm ci` is reproducible and respects the lockfile exactly.
RUN npm ci --no-audit --no-fund


# ---- Stage 2: builder --------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS builder
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# next.config.ts sets `output: "standalone"` — produces .next/standalone with
# a minimal node_modules and a server.js entry.
RUN npm run build


# ---- Stage 3: runner ---------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    DATABASE_URL=/data/achilles.db

# Tini gives proper PID-1 signal handling for `docker stop`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 achilles \
    && useradd  --system --uid 1001 --gid achilles --home /app achilles \
    && mkdir -p /data /app/logs \
    && chown -R achilles:achilles /data /app

# Standalone server bundle + static assets + public/.
COPY --from=builder --chown=achilles:achilles /app/.next/standalone ./
COPY --from=builder --chown=achilles:achilles /app/.next/static ./.next/static
COPY --from=builder --chown=achilles:achilles /app/public ./public
# Drizzle migrations + schema needed at runtime if we run `npm run db:migrate`
# from an init container or sidecar later.
COPY --from=builder --chown=achilles:achilles /app/db ./db
COPY --from=builder --chown=achilles:achilles /app/drizzle.config.ts ./drizzle.config.ts

USER achilles
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:'+process.env.PORT+'/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "server.js"]
