# Conclave Data Reset - Interactively select what to reset, delete volumes, restart
# Usage:
#   .\scripts\reset-data.ps1                    # Interactive selection
#   .\scripts\reset-data.ps1 -All               # Reset everything
#   .\scripts\reset-data.ps1 -Database          # Reset PostgreSQL + AppData only
#   .\scripts\reset-data.ps1 -Database -Redis   # Reset Database + Redis
#   .\scripts\reset-data.ps1 -All -Force        # Skip confirmation
#
# WARNING: This operation is irreversible!

param(
    [switch]$Force,
    [switch]$All,
    [switch]$Database,
    [switch]$Redis,
    [switch]$Qdrant,
    [switch]$Gitea,
    [switch]$Workspace
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

# Volume mapping (full names include project prefix "conclave-dev_")
$projectName = "conclave-dev"
$volumeMap = [ordered]@{
    "PostgreSQL" = "${projectName}_conclave-dev-pg-data"
    "AppData"    = "${projectName}_conclave-dev-data"
    "Qdrant"     = "${projectName}_conclave-dev-qdrant-data"
    "Redis"      = "${projectName}_conclave-dev-redis-data"
    "Gitea"      = "${projectName}_conclave-dev-gitea-data"
    "Workspace"  = "${projectName}_conclave-dev-workspace"
}

$volumeDesc = @{
    "PostgreSQL" = "Main database (meetings/messages/events)"
    "AppData"    = "SQLite + encryption key"
    "Qdrant"     = "Vector database (document search)"
    "Redis"      = "Cache/session (need re-login after reset)"
    "Gitea"      = "Git repos (agent collaboration)"
    "Workspace"  = "Workspace files"
}

Write-Host ""
Write-Host "===== Conclave Data Reset Tool =====" -ForegroundColor Red
Write-Host ""

# ---- Determine which volumes to reset ----
$selectedKeys = @()

if ($All) {
    $selectedKeys = @($volumeMap.Keys)
} elseif ($Database -or $Redis -or $Qdrant -or $Gitea -or $Workspace) {
    if ($Database) { $selectedKeys += "PostgreSQL"; $selectedKeys += "AppData" }
    if ($Redis)    { $selectedKeys += "Redis" }
    if ($Qdrant)   { $selectedKeys += "Qdrant" }
    if ($Gitea)    { $selectedKeys += "Gitea" }
    if ($Workspace){ $selectedKeys += "Workspace" }
} else {
    # Interactive selection
    Write-Host "Select data to reset (enter numbers, comma-separated):" -ForegroundColor Yellow
    Write-Host ""
    $keys = @($volumeMap.Keys)
    $i = 1
    foreach ($key in $keys) {
        Write-Host ("  {0}. {1} - {2}  (volume: {3})" -f $i, $key, $volumeDesc[$key], $volumeMap[$key])
        $i++
    }
    Write-Host "  0. Reset all"
    Write-Host ""
    $userInput = Read-Host "Selection (e.g. 1,2,4 or 0)"

    if ($userInput -eq "0") {
        $selectedKeys = @($volumeMap.Keys)
    } else {
        $indices = $userInput -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ -match "^\d+$" }
        foreach ($idx in $indices) {
            $n = [int]$idx
            if ($n -ge 1 -and $n -le $keys.Count) {
                $selectedKeys += $keys[$n - 1]
            }
        }
    }
}

if ($selectedKeys.Count -eq 0) {
    Write-Host "No selection made. Exiting." -ForegroundColor Yellow
    exit 0
}

# Get volume names
$targets = @()
foreach ($key in $selectedKeys) {
    $targets += $volumeMap[$key]
}

# ---- Show confirmation ----
Write-Host ""
Write-Host "The following volumes will be DELETED:" -ForegroundColor Red
Write-Host ""
foreach ($key in $selectedKeys) {
    Write-Host ("  - {0}: {1}  (volume: {2})" -f $key, $volumeDesc[$key], $volumeMap[$key]) -ForegroundColor Red
}
Write-Host ""

# Check volume existence
Write-Host "Checking volume status..." -ForegroundColor Yellow
foreach ($vol in $targets) {
    $exists = docker volume inspect $vol 2>$null
    if ($exists) {
        Write-Host "  $vol : exists" -ForegroundColor DarkGray
    } else {
        Write-Host "  $vol : not found (will skip)" -ForegroundColor DarkGray
    }
}
Write-Host ""

# ---- Confirm ----
if (-not $Force) {
    Write-Host "This is irreversible! Deleted data cannot be recovered." -ForegroundColor Red
    Write-Host "To restart without data loss: .\scripts\restart.ps1" -ForegroundColor DarkGray
    Write-Host ""
    $confirm = Read-Host "Type YES to confirm deletion"
    if ($confirm -ne "YES") {
        Write-Host ""
        Write-Host "Cancelled. Data unaffected." -ForegroundColor Yellow
        exit 0
    }
}

# ---- Execute reset ----
Write-Host ""
Write-Host "[1/3] Stopping services..." -ForegroundColor Yellow
docker compose down
Write-Host ""

Write-Host "[2/3] Deleting volumes..." -ForegroundColor Yellow
foreach ($vol in $targets) {
    Write-Host -NoNewline "  Deleting $vol ... "
    docker volume rm $vol 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "deleted" -ForegroundColor Green
    } else {
        Write-Host "not found or skipped" -ForegroundColor DarkGray
    }
}
Write-Host ""

Write-Host "[3/3] Rebuilding and starting services..." -ForegroundColor Yellow
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Start failed! Check: docker compose logs" -ForegroundColor Red
    exit 1
}
Write-Host ""

Start-Sleep -Seconds 8
docker compose ps
Write-Host ""

Write-Host "===== Reset Complete =====" -ForegroundColor Green
Write-Host ""
Write-Host "Reset data:" -ForegroundColor White
foreach ($key in $selectedKeys) {
    Write-Host "  - $key : $($volumeDesc[$key])"
}
Write-Host ""
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor White
Write-Host "  Backend:  http://localhost:8000" -ForegroundColor White
Write-Host "  Gitea:    http://localhost:3000" -ForegroundColor White
Write-Host ""
Write-Host "  Logs: docker compose logs -f backend" -ForegroundColor DarkGray
Write-Host ""
