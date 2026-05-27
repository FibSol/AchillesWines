# Wine-Searcher batch runner
#
# Usage:
#   .\scripts\ws_batch_run.ps1                  # 50 cuvees/batch, 10s pause
#   .\scripts\ws_batch_run.ps1 -BatchSize 100 -PauseSecs 15
#
# Progress is tracked via ops_content_hashes. Safe to stop and restart.

param(
    [int]$BatchSize = 200,
    [int]$PauseSecs = 3
)

Set-Location $PSScriptRoot\..

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding       = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8       = "1"
$env:PYTHONIOENCODING = "utf-8"

$scraper      = "$PSScriptRoot\..\scraper\.venv\Scripts\achilles-scraper"
$python       = "$PSScriptRoot\..\scraper\.venv\Scripts\python.exe"
$remainScript = "$PSScriptRoot\ws_remaining.py"

$batch         = 0
$totalInserted = 0
$totalDlq      = 0
$started       = Get-Date

Write-Host "=== Wine-Searcher batch runner ===" -ForegroundColor Cyan
Write-Host "Batch size : $BatchSize cuvees"
Write-Host "Pause      : $PauseSecs s between batches"
Write-Host "Started    : $started"

$remaining = [int](& $python $remainScript 2>$null)
Write-Host "Queue      : $remaining cuvees remaining"
Write-Host ""

while ($true) {
    if ($remaining -eq 0) {
        Write-Host ""
        Write-Host "=== All cuvees done! ===" -ForegroundColor Cyan
        Write-Host "Total inserted (staging) : $totalInserted"
        Write-Host "Total DLQ                : $totalDlq"
        Write-Host "Batches run              : $batch"
        Write-Host "Total elapsed            : $([math]::Round(((Get-Date)-$started).TotalMinutes,1)) min"
        break
    }

    $batch++
    $elapsedMin = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
    Write-Host "--- Batch $batch  [$elapsedMin min elapsed  $remaining remaining] ---" -ForegroundColor Yellow

    $output = & $scraper run --source wine_searcher --limit $BatchSize 2>&1
    Write-Host $output

    $ins = 0; $dlq = 0
    foreach ($line in $output) {
        if ($line -match 'Inserted.*?(\d+)\s*$') { $ins = [int]$Matches[1] }
        if ($line -match '^\W*DLQ.*?(\d+)\s*$') { $dlq = [int]$Matches[1] }
    }
    $totalInserted += $ins
    $totalDlq      += $dlq

    $remaining = [int](& $python $remainScript 2>$null)

    Write-Host "  batch: inserted=$ins dlq=$dlq | total: inserted=$totalInserted dlq=$totalDlq | remaining=$remaining" -ForegroundColor Green
    Write-Host "  Pausing $PauseSecs s..." -ForegroundColor DarkGray
    Start-Sleep -Seconds $PauseSecs
}
