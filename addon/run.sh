#!/bin/sh
set -e

# /data persists across add-on restarts (mapped by HA Supervisor)
export DATABASE_URL=/data/achilles.db

cd /app

echo "[achilles] Running database migrations..."
npm run db:migrate

echo "[achilles] Starting scraper job runner..."
DATABASE_URL=/data/achilles.db python -m achilles_scraper.cli run-jobs &

echo "[achilles] Starting web server on :3000..."
exec node .next/standalone/server.js
