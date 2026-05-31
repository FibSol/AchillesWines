# Changelog

## 1.1.4 — 2026-05-31

- Fix sidebar setup: use HA Settings → Dashboards → Webpage instead of ingress or panel_iframe (both broken with Next.js asset paths)
- Update install guide Part 10 with correct UI-based approach

## 1.1.3 — 2026-05-31

- Fix 404 on sidebar click: Next.js asset paths break through HA ingress proxy; switch sidebar to `panel_iframe` pointing at `homeassistant.local:3000` (direct port, no path rewriting needed)
- Update install guide Part 10 with correct `panel_iframe` configuration and explanation

## 1.1.2 — 2026-05-31

- Fix "Show in sidebar" toggle missing — ingress config was only present in `ha-addon/config.yaml`, not in the deployed `addon/config.yaml`
- Add `CHANGELOG.md` to addon directory so the Changelog tab renders in HA

## 1.1.1 — 2026-05-31

- Add HA ingress sidebar entry (`ingress: true`, `panel_icon`, `panel_title`) — "Show in sidebar" toggle now appears in the add-on Info tab
- Fix install guide (Part 10) to document automatic ingress sidebar; no manual `panel_iframe` config needed

## 1.0.5

- Add schedule configuration panel on admin/auth page — set cron schedules per scraper from the web UI
- New DB table `ops_scraper_schedule` (migration 0006) stores schedules persistently
- Job runner reads schedules from DB (+ env var overrides) and refreshes live every 60 s — no restart needed
- New API route `GET/PATCH /api/schedules`

## 1.0.4

- Fix APScheduler crash on Alpine: pass explicit `timezone="UTC"` to `BackgroundScheduler` (Alpine has no system timezone data)
- Add `tzdata` to Dockerfile so system timezone is available
- Fix Next.js 16 warning: move `themeColor` from `metadata` to `generateViewport` in root layout

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
