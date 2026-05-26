# =============================================================================
# Achilles's Wines — Dev-to-prod DB migration (Issue #29)
#
# Usage:
#   .\scripts\migrate-dev-to-prod.ps1
#   .\scripts\migrate-dev-to-prod.ps1 --dry-run
#
# What it does:
#   1. Pre-flight: gate check (>= 80% scrapers done), env var, SSH connectivity
#   2. Dump selected tables from data/achilles.db via Python sqlite3 module
#   3. SCP dump to RPi at /tmp/achilles-migration-YYYYMMDD.sql
#   4. SSH: backup prod DB, stop add-on, apply dump, restart, verify row counts
#
# Env vars:
#   ACHILLES_RPI_HOST   Required. RPi IP or hostname (e.g. 192.168.1.x / achilles.local)
#   ACHILLES_RPI_USER   Optional. SSH user (default: pi)
#   ACHILLES_RPI_DB     Optional. Remote DB path (default: /data/achilles.db)
#   ACHILLES_RPI_PORT   Optional. SSH port (default: 22)
#
# Tables migrated (data):
#   dim_producer, dim_appellation, dim_wine, bridge_wine_variety
#   fact_price, fact_rating, fact_vintage_rating
#   staging_price_candidates
#   cellar_locations, cellar_inventory, cellar_consumption
#
# Tables NOT migrated (preserved from prod):
#   dim_source, ops_* tables (scraper config + job history stay on prod)
# =============================================================================

param(
    [switch]$DryRun
)

Set-Location (Split-Path $PSScriptRoot -Parent)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"

# ── Colours ──────────────────────────────────────────────────────────────────
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

# ── Config ────────────────────────────────────────────────────────────────────
$PYTHON   = ".\scraper\.venv\Scripts\python.exe"
$DEV_DB   = ".\data\achilles.db"
$TODAY    = Get-Date -Format "yyyyMMdd"
$DUMP_TMP = [System.IO.Path]::GetTempPath() + "achilles-migration-${TODAY}.sql"
$RPI_DUMP = "/tmp/achilles-migration-${TODAY}.sql"

$RPI_HOST = $env:ACHILLES_RPI_HOST
$RPI_USER = if ($env:ACHILLES_RPI_USER) { $env:ACHILLES_RPI_USER } else { "pi" }
$RPI_DB   = if ($env:ACHILLES_RPI_DB)   { $env:ACHILLES_RPI_DB }   else { "/data/achilles.db" }
$RPI_PORT = if ($env:ACHILLES_RPI_PORT) { $env:ACHILLES_RPI_PORT } else { "22" }
$RPI_BACK = "${RPI_DB}.bak-${TODAY}"

# Tables to export (ORDER MATTERS — FK deps: dim first, then bridge, then fact)
$TABLES = @(
    "dim_producer",
    "dim_appellation",
    "dim_wine",
    "bridge_wine_variety",
    "fact_price",
    "fact_rating",
    "fact_vintage_rating",
    "staging_price_candidates",
    "cellar_locations",
    "cellar_inventory",
    "cellar_consumption"
)

$GATE_PCT = 80   # minimum % of enabled scrapers that must have a 'done' run

if ($DryRun) {
    Write-Host ""
    Write-Host "*** DRY-RUN MODE — no SCP / SSH commands will be executed ***" -ForegroundColor Magenta
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. PRE-FLIGHT CHECKS
# ─────────────────────────────────────────────────────────────────────────────
Write-Header "Pre-flight checks"

# 1a. Dev DB exists
Write-Step "Dev DB at $DEV_DB"
if (-not (Test-Path $DEV_DB)) {
    Abort "Dev DB not found at $DEV_DB — run scrapers first."
}
Write-Ok "$DEV_DB found"

# 1b. Python venv exists
Write-Step "Python venv at $PYTHON"
if (-not (Test-Path $PYTHON)) {
    Abort "Python not found at $PYTHON — run: cd scraper && python -m venv .venv && pip install -e ."
}
Write-Ok "Python venv OK"

# 1c. Gate check: >= GATE_PCT% of enabled scrapers have at least one 'done' run
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

$gateResult = & $PYTHON -c $gatePy 2>&1
$gateExit   = $LASTEXITCODE

if ($gateExit -ne 0) {
    Write-Fail "Gate not met: $gateResult — need >= ${GATE_PCT}% of enabled scrapers with a 'done' run."
    Write-Host "  Run more scrapers via /admin/jobs or: achilles-scraper run --source <key>" -ForegroundColor DarkYellow
    exit 1
}
Write-Ok "Gate passed: $gateResult"

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
Write-Ok "RPI_HOST = $RPI_HOST (user=$RPI_USER port=$RPI_PORT)"

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
    - If password auth, add: -o PasswordAuthentication=yes (but prefer key auth)
    - Test manually: ssh -p $RPI_PORT ${RPI_USER}@${RPI_HOST}

  If you need to set up key auth:
    ssh-keygen -t ed25519 -C "achilles-migration"
    ssh-copy-id -p $RPI_PORT ${RPI_USER}@${RPI_HOST}

"@ -ForegroundColor DarkYellow
        exit 1
    }
    Write-Ok "SSH OK"
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. DUMP DEV TABLES TO SQL FILE
# ─────────────────────────────────────────────────────────────────────────────
Write-Header "Dumping dev DB tables → $DUMP_TMP"

$tableList = ($TABLES | ForEach-Object { "'$_'" }) -join ", "

$dumpPy = @"
import sqlite3, sys, os

db_path   = r'$($DEV_DB -replace "\\", "/")'
out_path  = r'$($DUMP_TMP -replace "\\", "/")'
tables    = [$tableList]

conn = sqlite3.connect(db_path)
cur  = conn.cursor()

lines = []

# Header
lines.append("-- Achilles's Wines — dev-to-prod migration dump")
lines.append("-- Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
lines.append("-- Source DB: " + db_path)
lines.append("-- Tables: " + ", ".join(tables))
lines.append("")
lines.append("PRAGMA foreign_keys = OFF;")
lines.append("BEGIN;")
lines.append("")

total_rows = 0
for table in tables:
    # Count rows
    count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    total_rows += count
    print(f"  {table:<40} {count:>8} rows")
    lines.append(f"-- TABLE: {table}  ({count} rows)")
    lines.append(f"DELETE FROM {table};")

    if count == 0:
        lines.append("")
        continue

    # Fetch all rows
    cur.execute(f"SELECT * FROM {table}")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    col_list = ", ".join(f'"{c}"' for c in cols)

    for row in rows:
        def escape(v):
            if v is None:
                return "NULL"
            if isinstance(v, (int, float)):
                return str(v)
            # Escape single quotes in strings
            return "'" + str(v).replace("'", "''") + "'"
        values = ", ".join(escape(v) for v in row)
        lines.append(f"INSERT INTO {table} ({col_list}) VALUES ({values});")
    lines.append("")

lines.append("COMMIT;")
lines.append("PRAGMA foreign_keys = ON;")
lines.append("")

conn.close()

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

size_kb = os.path.getsize(out_path) // 1024
print(f"\n  Dump written: {out_path}")
print(f"  Total rows  : {total_rows:,}")
print(f"  File size   : {size_kb:,} KB")
"@

Write-Step "Row counts per table:"
& $PYTHON -c $dumpPy
if ($LASTEXITCODE -ne 0) {
    Abort "Python dump failed (exit $LASTEXITCODE)."
}
Write-Ok "Dump complete: $DUMP_TMP"

if ($DryRun) {
    Write-Host ""
    Write-Host "*** DRY-RUN: would SCP $DUMP_TMP → ${RPI_USER}@${RPI_HOST}:${RPI_DUMP}" -ForegroundColor Magenta
    Write-Host "*** DRY-RUN: would backup $RPI_DB → $RPI_BACK on RPi" -ForegroundColor Magenta
    Write-Host "*** DRY-RUN: would stop add-on, apply dump, restart, verify counts" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "Dry run complete. Dump file preserved at: $DUMP_TMP" -ForegroundColor Cyan
    exit 0
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. SCP DUMP TO RPI
# ─────────────────────────────────────────────────────────────────────────────
Write-Header "Copying dump to RPi"
Write-Step "scp $DUMP_TMP → ${RPI_USER}@${RPI_HOST}:${RPI_DUMP}"

scp -P $RPI_PORT "$DUMP_TMP" "${RPI_USER}@${RPI_HOST}:${RPI_DUMP}"
if ($LASTEXITCODE -ne 0) {
    Abort "SCP failed. Rollback: nothing applied yet — prod DB is intact."
}
Write-Ok "Dump uploaded to $RPI_DUMP"

# ─────────────────────────────────────────────────────────────────────────────
# 4. APPLY ON RPI
# ─────────────────────────────────────────────────────────────────────────────
Write-Header "Applying on RPi"

# 4a. Backup prod DB
Write-Step "Backup prod DB: $RPI_DB → $RPI_BACK"
ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" "cp '$RPI_DB' '$RPI_BACK' && echo 'backup ok'"
if ($LASTEXITCODE -ne 0) {
    Abort "Backup failed. Prod DB not modified."
}
Write-Ok "Prod DB backed up to $RPI_BACK"

# 4b. Stop the add-on (tries HA supervisor first, falls back to docker)
Write-Step "Stopping add-on (HA supervisor or docker)"
$stopCmd = @"
set -e
# Try Home Assistant supervisor CLI first (available inside HA OS)
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
    echo 'WARN: could not identify running add-on/service — proceeding anyway'
fi
"@
ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" $stopCmd
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Stop command returned non-zero — the add-on may already be stopped. Continuing."
}
Write-Ok "Add-on stopped (or was already stopped)"

# 4c. Apply the SQL dump
Write-Step "Applying dump to $RPI_DB"
$applyCmd = "sqlite3 '$RPI_DB' < '$RPI_DUMP' && echo 'apply ok'"
ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" $applyCmd
if ($LASTEXITCODE -ne 0) {
    $rollbackMsg = "sqlite3 '$RPI_DB' < /dev/null && cp '$RPI_BACK' '$RPI_DB'"
    Write-Fail "sqlite3 apply failed!"
    Write-Host ""
    Write-Host "  ROLLBACK command (run on RPi):" -ForegroundColor Red
    Write-Host "    ssh ${RPI_USER}@${RPI_HOST} `"cp '$RPI_BACK' '$RPI_DB'`"" -ForegroundColor Red
    Write-Host ""
    exit 1
}
Write-Ok "Dump applied"

# 4d. Restart the add-on
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
    echo 'WARN: could not identify service to restart — start it manually'
fi
"@
ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" $startCmd
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Restart returned non-zero — check add-on status manually."
}
Write-Ok "Add-on restart initiated"

# ─────────────────────────────────────────────────────────────────────────────
# 5. POST-MIGRATION VERIFICATION — row counts on prod
# ─────────────────────────────────────────────────────────────────────────────
Write-Header "Post-migration row counts (prod)"

$verifyCols = ($TABLES | ForEach-Object {
    "SELECT '$_' AS tbl, COUNT(*) AS n FROM $_"
}) -join " UNION ALL "

$verifyCmd = "sqlite3 -separator '|' '$RPI_DB' `"$verifyCols`""
$prodCounts = ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" $verifyCmd 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Warn "Could not query prod DB for row counts (add-on may still be starting)."
    Write-Warn "Verify manually: ssh ${RPI_USER}@${RPI_HOST} `"sqlite3 $RPI_DB 'SELECT COUNT(*) FROM dim_producer'`""
} else {
    Write-Host ""
    Write-Host "  Table                                     Prod rows" -ForegroundColor Cyan
    Write-Host "  -------                                   ---------" -ForegroundColor Cyan
    foreach ($line in ($prodCounts -split "`n")) {
        if ($line -match "^(.+)\|(\d+)$") {
            $tbl = $Matches[1].PadRight(40)
            $cnt = $Matches[2].PadLeft(10)
            Write-Host "  $tbl $cnt" -ForegroundColor Green
        }
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 6. CLEANUP
# ─────────────────────────────────────────────────────────────────────────────
Write-Header "Cleanup"

# Remove local temp dump
if (Test-Path $DUMP_TMP) {
    Remove-Item $DUMP_TMP -Force
    Write-Ok "Local temp dump removed: $DUMP_TMP"
}

# Remove remote dump
ssh -p $RPI_PORT "${RPI_USER}@${RPI_HOST}" "rm -f '$RPI_DUMP' && echo 'remote dump removed'" 2>&1 | ForEach-Object { Write-Ok $_ }

# ─────────────────────────────────────────────────────────────────────────────
# DONE
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Migration complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  RPi backup : $RPI_BACK" -ForegroundColor DarkGray
Write-Host "  RPi DB     : $RPI_DB" -ForegroundColor DarkGray
Write-Host ""
Write-Host "If anything looks wrong, rollback with:" -ForegroundColor DarkYellow
Write-Host "  ssh -p $RPI_PORT ${RPI_USER}@${RPI_HOST} `"cp '$RPI_BACK' '$RPI_DB'`"" -ForegroundColor DarkYellow
Write-Host ""
