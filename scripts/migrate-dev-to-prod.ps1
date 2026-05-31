# =============================================================================
# Achilles's Wines - Full-DB dev-to-prod copy (Issue #29)
#
# !!! IMPORTANT - READ docs/DEPLOY-HA.md FIRST !!!
# The SSH/SCP *apply* logic in this script assumes it can reach /data/achilles.db
# directly over SSH. That does NOT work for the real Home Assistant deployment:
# Achilles runs as an HA add-on whose /data is isolated from the SSH add-on
# container, and external SSH auth to the box is unreliable. The proven procedure
# (VACUUM INTO snapshot -> LAN HTTP pull -> docker-helper swap inside the add-on
# data dir) lives in docs/DEPLOY-HA.md. The snapshot-building step below is still
# correct and reusable; the apply phase is kept only for a hypothetical
# direct-SSH host.
#
# Copies the ENTIRE dev SQLite database to the Home Assistant Raspberry Pi,
# replacing the prod DB file wholesale. Dev is the single source of truth:
# this overwrites EVERYTHING on prod, including dim_source and all ops_* tables
# (scraper registry + job history). If you need a surgical, data-only copy that
# preserves prod's scraper state, use git history for the previous table-by-table
# version of this script.
#
# Usage:
#   .\scripts\migrate-dev-to-prod.ps1
#   .\scripts\migrate-dev-to-prod.ps1 -DryRun
#   .\scripts\migrate-dev-to-prod.ps1 -SkipGate     # bypass the >=80% scraper gate
#
# What it does:
#   1. Pre-flight: dev DB, Python venv, scraper gate, env var, SSH connectivity
#   2. VACUUM INTO a clean single-file snapshot (folds in WAL, defragments)
#   3. integrity_check the snapshot, then gzip it
#   4. SCP the .gz to the RPi /tmp
#   5. SSH: stop add-on, backup prod DB, gunzip+swap into place, clear stale WAL,
#      restart add-on
#   6. Verify: integrity_check + row counts on prod
#   7. Cleanup local + remote temp files
#
# Env vars:
#   ACHILLES_RPI_HOST   Required. RPi IP or hostname (e.g. 192.168.1.x / achilles.local)
#   ACHILLES_RPI_USER   Optional. SSH user (default: pi)
#   ACHILLES_RPI_DB     Optional. Remote DB path (default: /data/achilles.db)
#   ACHILLES_RPI_PORT   Optional. SSH port (default: 22)
#
# Why VACUUM INTO and not a plain copy:
#   The dev DB runs in WAL mode - recent writes live in achilles.db-wal. Copying
#   the bare .db file would ship a torn/stale database. VACUUM INTO produces a
#   consistent, defragmented single file that is safe to take while the DB is open.
#
# Why a full-file copy is safe across architectures:
#   The SQLite on-disk format is platform-independent, so a Windows-built file
#   loads fine on the ARM Pi. No better-sqlite3 rebuild is needed. The Drizzle
#   migration ledger (__drizzle_migrations) travels with the file, so the add-on's
#   boot-time `npm run db:migrate` is a no-op.
# =============================================================================

param(
    [switch]$DryRun,
    [switch]$SkipGate
)

Set-Location (Split-Path $PSScriptRoot -Parent)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"

# -- Colours ------------------------------------------------------------------
function Write-Header  { param($msg) Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Step    { param($msg) Write-Host "  >> $msg" -ForegroundColor Yellow }
function Write-Ok      { param($msg) Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn    { param($msg) Write-Host "  WARN $msg" -ForegroundColor DarkYellow }
function Write-Fail    { param($msg) Write-Host "`n  FAIL $msg" -ForegroundColor Red }

function Abort {
    param($msg)
    Write-Fail $msg
    Write-Host ""
    exit 1
}

# Run a Python script via a temp .py file. Passing source through `python -c`
# in Windows PowerShell 5.1 strips embedded double-quotes, so we write the
# script to disk and execute the file instead. Returns the captured output;
# sets $script:PyExit to the exit code.
function Invoke-Python {
    param([string]$Source)
    $tmpPy = [System.IO.Path]::GetTempPath() + "achilles-py-" + [System.Guid]::NewGuid().ToString("N") + ".py"
    try {
        [System.IO.File]::WriteAllText($tmpPy, $Source, (New-Object System.Text.UTF8Encoding($false)))
        $out = & $PYTHON $tmpPy 2>&1
        $script:PyExit = $LASTEXITCODE
        return $out
    } finally {
        if (Test-Path $tmpPy) { Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue }
    }
}

# -- Config --------------------------------------------------------------------
$PYTHON    = ".\scraper\.venv\Scripts\python.exe"
$DEV_DB    = ".\data\achilles.db"
$TODAY     = Get-Date -Format "yyyyMMdd-HHmmss"
$SNAP_TMP  = [System.IO.Path]::GetTempPath() + "achilles-snapshot-${TODAY}.db"
$GZ_TMP    = "${SNAP_TMP}.gz"
$RPI_GZ    = "/tmp/achilles-snapshot-${TODAY}.db.gz"

$RPI_HOST = $env:ACHILLES_RPI_HOST
$RPI_USER = if ($env:ACHILLES_RPI_USER) { $env:ACHILLES_RPI_USER } else { "pi" }
$RPI_DB   = if ($env:ACHILLES_RPI_DB)   { $env:ACHILLES_RPI_DB }   else { "/data/achilles.db" }
$RPI_PORT = if ($env:ACHILLES_RPI_PORT) { $env:ACHILLES_RPI_PORT } else { "22" }
$RPI_BACK = "${RPI_DB}.bak-${TODAY}"

$GATE_PCT = 80   # minimum % of enabled scrapers that must have a 'done' run

# Tables verified post-copy (for the row-count report only - the whole file is copied)
$VERIFY_TABLES = @(
    "dim_source", "dim_producer", "dim_appellation", "dim_variety", "dim_wine",
    "bridge_wine_variety", "fact_price", "fact_rating", "fact_vintage_rating",
    "staging_price_candidates",
    "cellar_locations", "cellar_inventory", "cellar_consumption"
)

if ($DryRun) {
    Write-Host ""
    Write-Host "*** DRY-RUN MODE - snapshot is built locally, but no SCP / SSH runs ***" -ForegroundColor Magenta
}

# -----------------------------------------------------------------------------
# 1. PRE-FLIGHT CHECKS
# -----------------------------------------------------------------------------
Write-Header "Pre-flight checks"

# 1a. Dev DB exists
Write-Step "Dev DB at $DEV_DB"
if (-not (Test-Path $DEV_DB)) {
    Abort "Dev DB not found at $DEV_DB - run scrapers first."
}
$devSizeMb = [math]::Round((Get-Item $DEV_DB).Length / 1MB, 1)
Write-Ok "$DEV_DB found ($devSizeMb MB)"

# 1b. Python venv exists
Write-Step "Python venv at $PYTHON"
if (-not (Test-Path $PYTHON)) {
    Abort "Python not found at $PYTHON - run: cd scraper && python -m venv .venv && pip install -e ."
}
Write-Ok "Python venv OK"

# 1c. Gate check: >= GATE_PCT% of enabled scrapers have at least one 'done' run
if ($SkipGate) {
    Write-Warn "Scraper gate check SKIPPED (-SkipGate)"
} else {
    Write-Step "Scraper gate check (>= ${GATE_PCT}% done)"
    $gatePy = @"
import sqlite3, sys
db = sqlite3.connect(r'$($DEV_DB -replace "\\", "/")')
cur = db.cursor()
total = cur.execute("SELECT COUNT(*) FROM dim_source WHERE enabled=1").fetchone()[0]
done  = cur.execute("""
    SELECT COUNT(DISTINCT source_key)
    FROM ops_job_queue
    WHERE status='done' AND source_key IS NOT NULL
""").fetchone()[0]
db.close()
pct = (done / total * 100) if total > 0 else 0
print(f"{done}/{total} ({pct:.1f}%)")
sys.exit(0 if pct >= $GATE_PCT else 1)
"@
    $gateResult = Invoke-Python $gatePy
    $gateExit   = $script:PyExit
    if ($gateExit -ne 0) {
        Write-Fail "Gate not met: $gateResult - need >= ${GATE_PCT}% of enabled scrapers with a 'done' run."
        Write-Host "  Run more scrapers, or bypass with -SkipGate if you really mean to copy now." -ForegroundColor DarkYellow
        exit 1
    }
    Write-Ok "Gate passed: $gateResult"
}

# 1d. RPI_HOST env var
Write-Step "ACHILLES_RPI_HOST env var"
if (-not $RPI_HOST) {
    Write-Fail "ACHILLES_RPI_HOST is not set."
    Write-Host @"

  Set it before running this script:
    `$env:ACHILLES_RPI_HOST = "192.168.1.X"   # or achilles.local
  Then re-run:
    .\scripts\migrate-dev-to-prod.ps1

"@ -ForegroundColor DarkYellow
    exit 1
}
Write-Ok "RPI_HOST = $RPI_HOST (user=$RPI_USER port=$RPI_PORT db=$RPI_DB)"

# 1e. SSH connectivity
Write-Step "SSH connectivity to ${RPI_USER}@${RPI_HOST}:${RPI_PORT}"
if ($DryRun) {
    Write-Warn "[dry-run] Skipping SSH connectivity test"
} else {
    $sshTest = ssh -p $RPI_PORT -o BatchMode=yes -o ConnectTimeout=10 `
                   -o StrictHostKeyChecking=accept-new `
                   "${RPI_USER}@${RPI_HOST}" "echo OK" 2>&1
    if ($LASTEXITCODE -ne 0 -or $sshTest -notmatch "OK") {
        Write-Fail "Cannot SSH to ${RPI_USER}@${RPI_HOST}:${RPI_PORT}"
        Write-Host @"

  Possible fixes:
    - Make sure your SSH key is in ~/.ssh/authorized_keys on the RPi.
    - Or run: ssh-copy-id ${RPI_USER}@${RPI_HOST}
    - Test manually: ssh -p $RPI_PORT ${RPI_USER}@${RPI_HOST}

"@ -ForegroundColor DarkYellow
        exit 1
    }
    Write-Ok "SSH OK"
}

# -----------------------------------------------------------------------------
# 2. BUILD A CLEAN SNAPSHOT (VACUUM INTO) + INTEGRITY CHECK + GZIP
# -----------------------------------------------------------------------------
Write-Header "Building clean snapshot"
Write-Step "VACUUM INTO -> $SNAP_TMP  (this can take a minute on a 1.5 GB DB)"

$snapPy = @"
import sqlite3, sys, os, gzip, shutil

dev_db  = r'$($DEV_DB -replace "\\", "/")'
snap    = r'$($SNAP_TMP -replace "\\", "/")'
gz      = r'$($GZ_TMP -replace "\\", "/")'

# Clean any leftover from a previous run
for p in (snap, gz):
    if os.path.exists(p):
        os.remove(p)

# 1) VACUUM INTO - consistent, defragmented single-file snapshot (folds in WAL).
snap_sql = snap.replace("'", "''")
src = sqlite3.connect(dev_db)
src.execute(f"VACUUM INTO '{snap_sql}'")
src.close()

# 2) integrity_check on the snapshot - never ship a corrupt file.
chk = sqlite3.connect(snap)
res = chk.execute("PRAGMA integrity_check").fetchone()[0]
chk.close()
if res != "ok":
    print(f"INTEGRITY FAILED: {res}", file=sys.stderr)
    sys.exit(2)
print("  integrity_check: ok")

snap_mb = os.path.getsize(snap) / (1024*1024)
print(f"  snapshot size  : {snap_mb:,.1f} MB")

# 3) gzip for transfer.
with open(snap, "rb") as fin, gzip.open(gz, "wb", compresslevel=6) as fout:
    shutil.copyfileobj(fin, fout, length=8*1024*1024)
gz_mb = os.path.getsize(gz) / (1024*1024)
print(f"  gzipped size   : {gz_mb:,.1f} MB")

# Drop the uncompressed snapshot - we only ship the .gz.
os.remove(snap)
print(f"  gz ready       : {gz}")
"@

Invoke-Python $snapPy | ForEach-Object { Write-Host "  $_" }
if ($script:PyExit -ne 0) {
    Abort "Snapshot/integrity/gzip step failed (exit $script:PyExit). Prod DB untouched."
}
Write-Ok "Snapshot built and verified: $GZ_TMP"

if ($DryRun) {
    Write-Host ""
    Write-Host "*** DRY-RUN: would SCP $GZ_TMP -> ${RPI_USER}@${RPI_HOST}:${RPI_GZ}" -ForegroundColor Magenta
    Write-Host "*** DRY-RUN: would stop add-on, backup $RPI_DB -> $RPI_BACK" -ForegroundColor Magenta
    Write-Host "*** DRY-RUN: would gunzip+swap into $RPI_DB, clear -wal/-shm, restart, verify" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "Dry run complete. Snapshot preserved at: $GZ_TMP" -ForegroundColor Cyan
    exit 0
}

# -----------------------------------------------------------------------------
# 3. SCP SNAPSHOT TO RPI
# -----------------------------------------------------------------------------
Write-Header "Copying snapshot to RPi"
Write-Step "scp $GZ_TMP -> ${RPI_USER}@${RPI_HOST}:${RPI_GZ}"

scp -P $RPI_PORT "$GZ_TMP" "${RPI_USER}@${RPI_HOST}:${RPI_GZ}"
if ($LASTEXITCODE -ne 0) {
    Abort "SCP failed. Rollback: nothing applied yet - prod DB is intact."
}
Write-Ok "Snapshot uploaded to $RPI_GZ"

# -----------------------------------------------------------------------------
# 4. STOP ADD-ON, BACKUP, SWAP, RESTART
# -----------------------------------------------------------------------------
Write-Header "Applying on RPi"

# 4a. Stop the add-on (HA supervisor first, docker/systemctl fallbacks)
Write-Step "Stopping add-on (HA supervisor or docker)"
$stopCmd = @"
if command -v ha >/dev/null 2>&1; then
    ha addons stop achilles_wines && echo 'stopped via ha CLI'
elif command -v hassio >/dev/null 2>&1; then
    hassio addons stop achilles_wines && echo 'stopped via hassio CLI'
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'addon_local_achilles_wines'; then
    docker stop addon_local_achilles_wines && echo 'stopped via docker (HA addon)'
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'achilles-web'; then
    docker stop achilles-web achilles-scraper achilles-nginx 2>/dev/null; echo 'stopped via docker-compose stack'
elif systemctl is-active --quiet achilles 2>/dev/null; then
    sudo systemctl stop achilles && echo 'stopped via systemctl'
else
    echo 'WARN: could not identify running add-on/service - proceeding anyway'
fi
"@
ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" $stopCmd
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Stop command returned non-zero - the add-on may already be stopped. Continuing."
}
Write-Ok "Add-on stopped (or was already stopped)"

# 4b. Backup prod DB (now quiescent), swap in the new file, clear stale WAL/SHM.
Write-Step "Backup prod DB, swap in snapshot, clear stale WAL/SHM"
$applyCmd = @"
set -e
if [ -f '$RPI_DB' ]; then
    cp '$RPI_DB' '$RPI_BACK'
    echo "backup ok: $RPI_BACK"
else
    echo "no existing prod DB to back up (fresh install)"
fi
gunzip -c '$RPI_GZ' > '${RPI_DB}.new'
# Stale WAL/SHM from the OLD db must not linger against the NEW file.
rm -f '${RPI_DB}-wal' '${RPI_DB}-shm'
mv '${RPI_DB}.new' '$RPI_DB'
chmod 644 '$RPI_DB'
echo "swap ok"
"@
ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" $applyCmd
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Swap failed!"
    Write-Host ""
    Write-Host "  ROLLBACK (run on RPi):" -ForegroundColor Red
    Write-Host "    ssh -p $RPI_PORT ${RPI_USER}@${RPI_HOST} `"cp '$RPI_BACK' '$RPI_DB' && rm -f '${RPI_DB}-wal' '${RPI_DB}-shm'`"" -ForegroundColor Red
    Write-Host "  Then restart the add-on from the HA UI." -ForegroundColor Red
    Write-Host ""
    exit 1
}
Write-Ok "Prod DB replaced (backup at $RPI_BACK)"

# 4c. Restart the add-on
Write-Step "Restarting add-on"
$startCmd = @"
set -e
if command -v ha >/dev/null 2>&1; then
    ha addons start achilles_wines && echo 'started via ha CLI'
elif command -v hassio >/dev/null 2>&1; then
    hassio addons start achilles_wines && echo 'started via hassio CLI'
elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q 'addon_local_achilles_wines'; then
    docker start addon_local_achilles_wines && echo 'started via docker (HA addon)'
elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q 'achilles-web'; then
    docker start achilles-web achilles-scraper achilles-nginx 2>/dev/null; echo 'started via docker-compose stack'
elif systemctl list-units --type=service 2>/dev/null | grep -q achilles; then
    sudo systemctl start achilles && echo 'started via systemctl'
else
    echo 'WARN: could not identify service to restart - start it manually'
fi
"@
ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" $startCmd
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Restart returned non-zero - check add-on status manually."
}
Write-Ok "Add-on restart initiated"

# -----------------------------------------------------------------------------
# 5. POST-COPY VERIFICATION - integrity + row counts on prod
# -----------------------------------------------------------------------------
Write-Header "Post-copy verification (prod)"

Write-Step "integrity_check on $RPI_DB"
$integ = ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" "sqlite3 '$RPI_DB' 'PRAGMA integrity_check;'" 2>&1
if ($LASTEXITCODE -eq 0 -and $integ -match "ok") {
    Write-Ok "integrity_check: ok"
} else {
    Write-Warn "integrity_check did not return ok (got: $integ). Investigate before trusting prod."
}

$verifyCols = ($VERIFY_TABLES | ForEach-Object {
    "SELECT '$_' AS tbl, COUNT(*) AS n FROM $_"
}) -join " UNION ALL "
$verifyCmd  = "sqlite3 -separator '|' '$RPI_DB' `"$verifyCols`""
$prodCounts = ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" $verifyCmd 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Warn "Could not query prod DB for row counts (add-on may still be starting)."
} else {
    Write-Host ""
    Write-Host "  Table                                     Prod rows" -ForegroundColor Cyan
    Write-Host "  -------                                   ---------" -ForegroundColor Cyan
    foreach ($line in ($prodCounts -split "`n")) {
        if ($line -match "^(.+)\|(\d+)\s*$") {
            $tbl = $Matches[1].PadRight(40)
            $cnt = $Matches[2].PadLeft(10)
            Write-Host "  $tbl $cnt" -ForegroundColor Green
        }
    }
}

# -----------------------------------------------------------------------------
# 6. CLEANUP
# -----------------------------------------------------------------------------
Write-Header "Cleanup"
if (Test-Path $GZ_TMP) {
    Remove-Item $GZ_TMP -Force
    Write-Ok "Local temp snapshot removed: $GZ_TMP"
}
ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" "rm -f '$RPI_GZ' && echo 'remote snapshot removed'" 2>&1 | ForEach-Object { Write-Ok $_ }

# -----------------------------------------------------------------------------
# DONE
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "Full-DB copy complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  RPi backup : $RPI_BACK" -ForegroundColor DarkGray
Write-Host "  RPi DB     : $RPI_DB" -ForegroundColor DarkGray
Write-Host ""
Write-Host "If anything looks wrong, rollback with:" -ForegroundColor DarkYellow
Write-Host "  ssh -p $RPI_PORT ${RPI_USER}@${RPI_HOST} `"cp '$RPI_BACK' '$RPI_DB' && rm -f '${RPI_DB}-wal' '${RPI_DB}-shm'`"" -ForegroundColor DarkYellow
Write-Host "  then restart the add-on from the HA UI." -ForegroundColor DarkYellow
Write-Host ""
