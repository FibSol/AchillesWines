#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH=/data/options.json
BACKUP_PASSPHRASE=$(bashio::config 'backup_passphrase')
HTTP_PORT=$(bashio::config 'http_port')
LOG_LEVEL=$(bashio::config 'log_level')

bashio::log.info "Starting Achilles's Wines stack on port ${HTTP_PORT}"

# Export for docker-compose
export ACHILLES_HTTP_PORT="${HTTP_PORT}"
export ACHILLES_GPG_PASSPHRASE="${BACKUP_PASSPHRASE}"
export LOG_LEVEL="${LOG_LEVEL}"

cd /achilles

# Pull images or build locally
docker compose up --build -d

# Tail logs
docker compose logs -f
