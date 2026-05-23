# Achilles's Wines

Home wine cellar management — multilingual (FR/EN/NL/DE/ES/IT), price tracking, cellar inventory, and critic ratings.

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. Click **⋮ (overflow menu) → Repositories**.
3. Add `https://github.com/FibSol/AchillesWines` and click **Add**.
4. Find **Achilles's Wines** in the store and click **Install**.

## First start

The add-on runs database migrations automatically on every start — no manual setup required. Your data is stored in `/data/achilles.db`, which persists across restarts and updates.

Open the web interface via **Open Web UI** or navigate to `http://<your-ha-host>:3000`.

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `log_level` | `info` | Logging verbosity: `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal` |

## Port

| Port | Description |
|------|-------------|
| `3000/tcp` | Achilles Wines web interface |

## Data persistence

All application data (wine cellar, prices, ratings, scraper jobs) is stored in `/data/achilles.db`. This directory is managed by the HA Supervisor and survives add-on updates and restarts.

## Scraper jobs

Price and rating scrapers are scheduled automatically and can also be triggered manually from the **Admin → Jobs** page in the web interface. Job history and logs are visible there.

## Support

Report issues at <https://github.com/FibSol/AchillesWines/issues>.
