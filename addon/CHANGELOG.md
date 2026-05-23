# Changelog

## 1.0.3

- Add watchdog health check (`http://[HOST]:3000/`) for automatic restart on crash
- Graceful SIGTERM/SIGINT shutdown — both Node.js and Python scraper processes are stopped cleanly
- Add OCI image labels (`org.opencontainers.image.*`, `io.hass.*`) via `build.yaml`
- Add `log_level` option with schema validation

## 1.0.2

- Fix Docker build: switch to `node:22-alpine` and `npm install` (replaces `npm ci`) to resolve lockfile version mismatch
- Remove `playwright` from scraper dependencies (no musl/aarch64 wheel; unused)
- Add `ARG CACHEBUST` to force fresh git clone when version changes

## 1.0.1

- Initial Home Assistant add-on packaging
- Node.js 22 + Python 3 in Alpine container
- `/data` volume mapped for persistent SQLite database
- Scraper job runner starts alongside Next.js web server
