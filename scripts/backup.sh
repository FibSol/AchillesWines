#!/usr/bin/env bash
# =============================================================================
# Achilles's Wines — SQLite backup → GPG → NAS (ADR-009).
#
# Usage:
#   backup.sh                                    # uses defaults
#   ACHILLES_DB=/data/achilles.db BACKUP_DIR=/mnt/nas/achilles backup.sh
#
# Required:
#   ACHILLES_GPG_PASSPHRASE   symmetric passphrase (never logged)
#
# Optional (with defaults):
#   ACHILLES_DB               /data/achilles.db
#   BACKUP_DIR                /mnt/nas/achilles/backups
#   BACKUP_LOG_DIR            /app/logs
#   BACKUP_RETAIN_DAILY       7
#   BACKUP_RETAIN_WEEKLY      4         (kept iff filename ends in `-weekly`)
#
# Designed to be cron-friendly: every line goes to both stdout and
# logs/backup-YYYYMMDD.log. Exits non-zero on any failure so cron mailers
# (or HA automations) can pick it up.
# =============================================================================

set -euo pipefail

ACHILLES_DB="${ACHILLES_DB:-/data/achilles.db}"
BACKUP_DIR="${BACKUP_DIR:-/mnt/nas/achilles/backups}"
BACKUP_LOG_DIR="${BACKUP_LOG_DIR:-/app/logs}"
RETAIN_DAILY="${BACKUP_RETAIN_DAILY:-7}"
RETAIN_WEEKLY="${BACKUP_RETAIN_WEEKLY:-4}"

TODAY="$(date -u +%Y%m%d)"
NOW="$(date -u +%Y%m%d-%H%M%S)"
DOW="$(date -u +%u)"   # 1=Mon … 7=Sun. We tag weekly backups on Sunday.

LOG_FILE="${BACKUP_LOG_DIR}/backup-${TODAY}.log"
mkdir -p "${BACKUP_LOG_DIR}" "${BACKUP_DIR}"

log() {
  printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}"
}

fail() {
  log "ERROR: $*"
  exit 1
}

# -----------------------------------------------------------------------------
# Preconditions
# -----------------------------------------------------------------------------

[ -n "${ACHILLES_GPG_PASSPHRASE:-}" ] \
  || fail "ACHILLES_GPG_PASSPHRASE is not set — refusing to back up unencrypted"

[ -f "${ACHILLES_DB}" ] \
  || fail "SQLite DB not found at ${ACHILLES_DB}"

command -v sqlite3 >/dev/null 2>&1 || fail "sqlite3 not installed"
command -v gpg     >/dev/null 2>&1 || fail "gpg not installed"

# -----------------------------------------------------------------------------
# 1. Snapshot via SQLite online-backup API (safe with concurrent WAL writers)
# -----------------------------------------------------------------------------

SNAP_BASENAME="achilles-${NOW}"
if [ "${DOW}" = "7" ]; then
  SNAP_BASENAME="${SNAP_BASENAME}-weekly"
fi
SNAP_TMP="$(mktemp -d)/${SNAP_BASENAME}.db"

log "snapshot ${ACHILLES_DB} → ${SNAP_TMP}"
sqlite3 "${ACHILLES_DB}" ".backup '${SNAP_TMP}'" \
  || fail "sqlite3 .backup failed"

SNAP_SIZE="$(stat -c %s "${SNAP_TMP}" 2>/dev/null || stat -f %z "${SNAP_TMP}")"
log "snapshot ok size=${SNAP_SIZE}B"

# -----------------------------------------------------------------------------
# 2. Encrypt symmetric AES-256
# -----------------------------------------------------------------------------

ENC_PATH="${BACKUP_DIR}/${SNAP_BASENAME}.db.gpg"
log "encrypt → ${ENC_PATH}"

# --pinentry-mode loopback is required to read the passphrase from stdin in
# headless environments. --batch suppresses any prompts.
printf '%s' "${ACHILLES_GPG_PASSPHRASE}" \
  | gpg --batch --yes --pinentry-mode loopback \
        --passphrase-fd 0 \
        --cipher-algo AES256 \
        --symmetric \
        --output "${ENC_PATH}" \
        "${SNAP_TMP}" \
  || fail "gpg --symmetric failed"

ENC_SIZE="$(stat -c %s "${ENC_PATH}" 2>/dev/null || stat -f %z "${ENC_PATH}")"
log "encrypt ok size=${ENC_SIZE}B"

# Verify the file decrypts before we trust it.
log "verify decrypt"
printf '%s' "${ACHILLES_GPG_PASSPHRASE}" \
  | gpg --batch --yes --pinentry-mode loopback \
        --passphrase-fd 0 \
        --decrypt "${ENC_PATH}" >/dev/null \
  || fail "gpg --decrypt round-trip failed — backup is unusable"

rm -f "${SNAP_TMP}"

# -----------------------------------------------------------------------------
# 3. Retention: last N daily + last M weekly
# -----------------------------------------------------------------------------

log "retention daily=${RETAIN_DAILY} weekly=${RETAIN_WEEKLY}"

# We pick filenames matching either suffix and sort newest first; anything
# beyond the retention count gets unlinked. find -printf is GNU; fall back to
# stat-formatted ls if needed.
prune() {
  local glob="$1" keep="$2"
  # shellcheck disable=SC2012  # ls is fine for stable basenames here
  ls -1t "${BACKUP_DIR}"/${glob} 2>/dev/null \
    | tail -n +"$((keep + 1))" \
    | while IFS= read -r old; do
        log "prune ${old}"
        rm -f "${old}"
      done
}

prune 'achilles-*-weekly.db.gpg' "${RETAIN_WEEKLY}"
# Daily glob deliberately excludes the *-weekly suffix.
prune 'achilles-2[0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].db.gpg' "${RETAIN_DAILY}"

log "done ${ENC_PATH}"
