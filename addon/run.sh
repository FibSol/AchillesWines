#!/bin/sh

# /data persists across add-on restarts (mapped by HA Supervisor)
export DATABASE_URL=/data/achilles.db
export NODE_ENV=production
export PORT=3000
export HOSTNAME=0.0.0.0

cd /app

echo "[achilles] Running database migrations..."
npm run db:migrate

echo "[achilles] Starting scraper job runner..."
python -m achilles_scraper.cli run-jobs &
JOB_PID=$!

echo "[achilles] Starting web server on :3000..."
node .next/standalone/server.js &
NODE_PID=$!

# Graceful shutdown — kill both services on SIGTERM
trap 'echo "[achilles] Stopping..."; kill "$JOB_PID" "$NODE_PID" 2>/dev/null; wait; exit 0' TERM INT

# Exit when Node.js exits
wait "$NODE_PID"
