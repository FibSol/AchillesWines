# next-session.ps1
# Fires via Claude Code Stop hook after each session.
# If the agent wrote .claude/session-complete, reads NEXT.md, builds the
# next agent prompt, and launches a new claude --enable-auto-mode window.

$projectRoot = Split-Path $PSScriptRoot -Parent
$flagFile    = Join-Path $projectRoot ".claude\session-complete"

if (-not (Test-Path $flagFile)) { exit 0 }

$completedRole = (Get-Content $flagFile -Raw -Encoding UTF8).Trim()
Remove-Item $flagFile -Force

# ── Parse NEXT.md for first uncompleted item ─────────────────────────────────
$nextMd  = Get-Content (Join-Path $projectRoot "NEXT.md") -Raw -Encoding UTF8
$pattern = '(?m)^- \[ \] \*\*([^*]+)\*\* \[([^\]]+)\] (.+)$'
$match   = [regex]::Match($nextMd, $pattern)

if (-not $match.Success) {
    Write-Host "[auto-session] $completedRole finished — no more items in NEXT.md. Sprint complete!"
    exit 0
}

$priority    = $match.Groups[1].Value.Trim()   # e.g. "P1 · 3h"
$role        = $match.Groups[2].Value.Trim()   # e.g. "Odysseus"
$description = $match.Groups[3].Value.Trim()  # e.g. "Page Vintages : heatmap..."
$today       = Get-Date -Format "yyyy-MM-dd"

# ── Role-specific boilerplate ────────────────────────────────────────────────
$roleContext = switch ($role) {
    "Odysseus"  {
        "Stack: Next.js + React 19 + Drizzle + Tailwind v4 + next-intl 4 (FR/EN/NL/DE/ES/IT) + Recharts.`nTheme: Dionysus (aubergine #1A0B2E, coral #FF5C8A, ivory #FAF7F5).`nUse PageShell + glass-card + stat-card classes from globals.css.`nTypeScript strict, no type: any. Run npx tsc --noEmit before finishing."
    }
    "Patroclus" {
        "Python sidecar lives at scraper/. Use pyproject.toml + .venv. Use rich for CLI output.`nDrizzle schema at db/schema.ts. All SQL via better-sqlite3 or Drizzle queries."
    }
    "Cassandra" {
        "Tests use Vitest (npx vitest run). Test files live in tests/.`nAll gates in lib/quality/gates.ts. Identity helpers in lib/identity.ts."
    }
    "Hector"    {
        "You are the Solution Architect.`nUpdate db/schema.ts + write migrations as needed. Document decisions as ADRs in DECISIONS.md."
    }
    "Helena"    {
        "You are the Business Analyst.`nUpdate NEXT.md priorities and DECISIONS.md user stories after each decision."
    }
    default { "" }
}

# ── Build full prompt ────────────────────────────────────────────────────────
$prompt = @"
You are $role on the Achilles's Wines project at C:\Claude\achilles-wines.
IMPORTANT: Do NOT invoke any skills. Do NOT call the Skill tool. Do actual code work only.

$roleContext

Task — $priority: $description

Read NEXT.md carefully — there may be sub-bullets or additional context under this item.
Explore the codebase before writing code (read relevant files first).

When done:
- Append to PROGRESS.md under ## $today with role [$role]:
    - [$role] <what you built> · files: <comma-separated list>
- Tick the item in NEXT.md: change [ ] to [x] and append: ✓ $today
- Write the file .claude\session-complete with the single line: $role
  (this triggers the auto-session launcher for the next step)
"@

# ── Write launcher script and open new window ────────────────────────────────
$launcherFile = Join-Path $projectRoot ".claude\launch-next.ps1"

@"
Set-Location '$($projectRoot -replace "'", "''")'
`$prompt = @'
$($prompt -replace "(?<!')'(?!')", "''")
'@
& "C:\Users\Nicolas\AppData\Roaming\Claude\claude-code\2.1.146\claude.exe" --enable-auto-mode `$prompt
"@ | Set-Content $launcherFile -Encoding UTF8

Write-Host "[auto-session] $completedRole done. Launching next: [$role] $priority — $description"
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -NoExit -File `"$launcherFile`""
