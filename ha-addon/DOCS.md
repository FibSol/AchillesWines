# Achilles's Wines — Home Assistant Addon

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Add the URL of this repository (or a local Supervisor store path pointing to `ha-addon/`).
3. Find **Achilles's Wines** in the list and click **Install**.
4. Set the required options (see below) and click **Start**.

## Required environment variables

Set these in your `.env` file on the host, or inject them via HA's addon options / secrets:

| Variable | Purpose |
|---|---|
| `ACHILLES_AUTH_MILLESIMA_USERNAME` | Login for Millesima scraper |
| `ACHILLES_AUTH_MILLESIMA_PASSWORD` | Password for Millesima scraper |
| `ACHILLES_AUTH_IDEALWINE_USERNAME` | Login for iDealwine scraper |
| `ACHILLES_AUTH_IDEALWINE_PASSWORD` | Password for iDealwine scraper |
| `ACHILLES_MAILBOX_HOST` | IMAP host for newsletter ingestion (e.g. imap.gmail.com) |
| `ACHILLES_MAILBOX_PORT` | IMAP port (default 993) |
| `ACHILLES_MAILBOX_USERNAME` | IMAP username |
| `ACHILLES_MAILBOX_PASSWORD` | IMAP app password (never your main password) |
| `ACHILLES_GPG_PASSPHRASE` | Passphrase for encrypted SQLite backups |

## Accessing the UI

Once the addon is running, click **Open Web UI** in the addon page, or navigate to the **Achilles** entry in the HA sidebar (panel icon: `mdi:glass-wine`). The UI is served via HA Ingress on port 3000.

## Backup / restore workflow

**Backup** runs automatically at 04:00 via the HA automation in `ha_integration/automations.yaml`. Encrypted `.db.gpg` files land in the mapped NAS share (`/share/achilles-backups/`). Retention: 7 daily + 4 weekly (Sunday).

**Restore:**
```bash
# From inside the addon container
/achilles/scripts/restore.sh /share/achilles-backups/achilles-YYYYMMDD.db.gpg /data/achilles.db
```
Pass `--force` to overwrite an existing database. The script verifies integrity before swapping.
