# Achilles Wines — dev launcher
# Usage: .\dev.ps1
# Kills any existing Next.js dev server on port 3000, then starts a fresh one.

$ProjectDir = "C:\Claude\achilles-wines"
$Port = 3000

# Kill whatever is on port 3000
$pid3000 = (netstat -ano | Select-String ":$Port " | Select-String "LISTENING" | ForEach-Object { ($_ -split "\s+")[-1] } | Select-Object -First 1)
if ($pid3000) {
    Write-Host "Killing process $pid3000 on port $Port..." -ForegroundColor Yellow
    Stop-Process -Id $pid3000 -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Set-Location $ProjectDir
Write-Host "Starting Achilles Wines dev server..." -ForegroundColor Cyan
npm run dev
