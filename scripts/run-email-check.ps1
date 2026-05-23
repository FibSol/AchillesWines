#Requires -Version 5.1
<#
.SYNOPSIS
    Daily email check for Achilles's Wines — runs all email newsletter scrapers.
    Designed to be called by Windows Task Scheduler at 16:00 daily.

.NOTES
    Registered by: scripts/run-email-check.ps1 itself (see bottom of file).
    Log: C:\Claude\achilles-wines\logs\email-check-<date>.log
#>

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ScraperDir  = Join-Path $ProjectRoot "scraper"
$Python      = Join-Path $ScraperDir ".venv\Scripts\python.exe"
$LogDir      = Join-Path $ProjectRoot "logs"
$LogFile     = Join-Path $LogDir ("email-check-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Write-Log {
    param([string]$Message)
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "=== Achilles email check starting ==="
Write-Log "Project root : $ProjectRoot"
Write-Log "Log          : $LogFile"

if (-not (Test-Path $Python)) {
    Write-Log "ERROR: Python venv not found at $Python"
    exit 1
}

$Sources = @(
    "millesima_email",
    "idealwine_email",
    "lavinia_email",
    "ventealapropriete_email"
)

$Failed = @()

foreach ($source in $Sources) {
    Write-Log "--- Running scraper: $source ---"
    try {
        $output = & $Python -m achilles_scraper.cli run --source $source 2>&1
        $output | ForEach-Object { Write-Log "  $_" }
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            Write-Log "  EXIT CODE: $LASTEXITCODE (scraper reported failure)"
            $Failed += $source
        }
    } catch {
        Write-Log "  EXCEPTION: $_"
        $Failed += $source
    }
}

if ($Failed.Count -gt 0) {
    Write-Log "=== Completed with errors. Failed sources: $($Failed -join ', ') ==="
    exit 1
} else {
    Write-Log "=== All scrapers completed successfully ==="
    exit 0
}
