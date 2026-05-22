#!/usr/bin/env bash
# =============================================================================
# Achilles's Wines — restore an encrypted backup produced by backup.sh.
#
# Usage:
#   ACHILLES_GPG_PASSPHRASE=… restore.sh /path/to/achilles-YYYYMMDD-HHMMSS.db.gpg [/target/db.path]
#
# Safety: refuses to overwrite an existing target unless --force is passed.
# =============================================================================

set -euo pipefail

ENC_SRC="${1:-}"
TARGET="${2:-/data/achilles.db}"
FORCE=0
[ "${3:-}" = "--force" ] && FORCE=1

[ -n "${ENC_SRC}" ] || { echo "usage: restore.sh <enc-backup> [target-db] [--force]" >&2; exit 2; }
[ -f "${ENC_SRC}" ] || { echo "no such file: ${ENC_SRC}" >&2; exit 1; }
[ -n "${ACHILLES_GPG_PASSPHRASE:-}" ] || { echo "ACHILLES_GPG_PASSPHRASE not set" >&2; exit 1; }

if [ -e "${TARGET}" ] && [ "${FORCE}" -ne 1 ]; then
  echo "target ${TARGET} exists; pass --force to overwrite" >&2
  exit 1
fi

TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

printf '%s' "${ACHILLES_GPG_PASSPHRASE}" \
  | gpg --batch --yes --pinentry-mode loopback \
        --passphrase-fd 0 \
        --decrypt --output "${TMP}" "${ENC_SRC}"

# Sanity-check it really is a SQLite db before clobbering anything.
if ! sqlite3 "${TMP}" 'PRAGMA integrity_check;' | grep -q '^ok$'; then
  echo "integrity check failed — refusing to install" >&2
  exit 1
fi

mkdir -p "$(dirname "${TARGET}")"
mv "${TMP}" "${TARGET}"
trap - EXIT
echo "restored → ${TARGET}"
