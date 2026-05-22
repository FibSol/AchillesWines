# Backups

Daily encrypted backups of `data/achilles.db` to NAS, with weekly snapshots kept longer. See ADR-009 for the design rationale.

## Files

| File                 | Purpose                                                          |
|----------------------|------------------------------------------------------------------|
| `scripts/backup.sh`  | Snapshot via SQLite online-backup API, encrypt GPG, prune old.   |
| `scripts/restore.sh` | Decrypt + integrity-check + install over a target DB.            |

## Required environment

| Variable                    | Required | Default                       | Notes                            |
|-----------------------------|----------|-------------------------------|----------------------------------|
| `ACHILLES_GPG_PASSPHRASE`   | yes      | —                             | Symmetric passphrase, never logged. |
| `ACHILLES_DB`               | no       | `/data/achilles.db`           | Source SQLite DB.                |
| `BACKUP_DIR`                | no       | `/mnt/nas/achilles/backups`   | Where encrypted files land.      |
| `BACKUP_LOG_DIR`            | no       | `/app/logs`                   | Cron-friendly log destination.   |
| `BACKUP_RETAIN_DAILY`       | no       | `7`                           | Daily snapshots to keep.         |
| `BACKUP_RETAIN_WEEKLY`      | no       | `4`                           | Weekly snapshots to keep (Sunday). |

## Scheduling — host cron (RPi)

```cron
# /etc/cron.d/achilles-backup — runs nightly at 02:15 UTC
15 2 * * *  root  source /etc/achilles/backup.env && /opt/achilles/scripts/backup.sh
```

`/etc/achilles/backup.env` (chmod 600, owned root):

```bash
ACHILLES_GPG_PASSPHRASE=...
ACHILLES_DB=/var/lib/docker/volumes/achilles-data/_data/achilles.db
BACKUP_DIR=/mnt/nas/achilles/backups
```

## Scheduling — Home Assistant automation

```yaml
# configuration.yaml shell_command
shell_command:
  achilles_backup: >-
    docker exec -e ACHILLES_GPG_PASSPHRASE='{{ states('input_text.achilles_gpg') }}'
    achilles-scraper bash /opt/achilles/scripts/backup.sh
```

The scraper container already has `sqlite3` + writes to `/data` + `/app/logs`. We just need to bind `scripts/` into it (see `docker-compose.yml` to add the mount when wiring this up).

## Restore

```bash
ACHILLES_GPG_PASSPHRASE=... \
  ./scripts/restore.sh /mnt/nas/achilles/backups/achilles-20260522-021500.db.gpg
```

`restore.sh` decrypts, runs `PRAGMA integrity_check`, then atomically moves the file into place. It refuses to overwrite an existing target without `--force`.

## Filename convention

- Daily: `achilles-YYYYMMDD-HHMMSS.db.gpg`
- Weekly (Sunday): `achilles-YYYYMMDD-HHMMSS-weekly.db.gpg`

Retention pruning is suffix-aware so the two retention windows don't collide.
