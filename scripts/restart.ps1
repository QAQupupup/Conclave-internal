# Conclave Safe Restart - Rebuild images and restart services, preserving all persistent data
# Usage:
#   .\scripts\restart.ps1              # Rebuild + restart (recommended)
#   .\scripts\restart.ps1 -NoBuild     # Restart only, no rebuild
#   .\scripts\restart.ps1 -Service backend  # Restart specific service
#
# Data safety: All volumes (PostgreSQL/Qdrant/Redis/Gitea/Workspace) are preserved

param(
    [switch]$NoBuild,
    [string]$Service = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host ""
Write-Host "===== Conclave Safe Restart (Data Preserved) =====" -ForegroundColor Cyan
Write-Host ""

# ---- 1. Check persistent volumes ----
Write-Host "[1/4] Checking persistent volumes..." -ForegroundColor Yellow
$volumes = docker volume ls --filter "name=conclave-dev-" --format "{{.Name}}" 2>$null
if ($volumes) {
    Write-Host "  Volumes to be preserved:" -ForegroundColor Green
    foreach ($v in $volumes) { Write-Host "    - $v" -ForegroundColor Green }
} else {
    Write-Host "  No conclave-dev volumes found (first run will create them)" -ForegroundColor DarkGray
}
Write-Host ""

# ---- 2. Stop containers (preserve volumes) ----
if ($Service) {
    Write-Host "[2/4] Stopping service: $Service (volumes preserved)..." -ForegroundColor Yellow
    docker compose stop $Service
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Stop failed, trying down..." -ForegroundColor Yellow
        docker compose down --remove-orphans
    } else {
        docker compose rm -f $Service 2>$null
    }
} else {
    Write-Host "[2/4] Stopping all containers (volumes preserved)..." -ForegroundColor Yellow
    docker compose down
}
Write-Host ""

# ---- 3. Rebuild images ----
if (-not $NoBuild) {
    Write-Host "[3/4] Rebuilding images (loading latest code)..." -ForegroundColor Yellow
    if ($Service) {
        docker compose build --progress plain $Service
    } else {
        docker compose build --progress plain
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Image build failed! Check code and Dockerfile." -ForegroundColor Red
        Write-Host "To restart without rebuild: .\scripts\restart.ps1 -NoBuild" -ForegroundColor DarkGray
        exit 1
    }
} else {
    Write-Host "[3/4] Skipping image build (-NoBuild)" -ForegroundColor DarkGray
}
Write-Host ""

# ---- 4. Start services ----
Write-Host "[4/4] Starting services..." -ForegroundColor Yellow
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "Start failed! Check: docker compose logs" -ForegroundColor Red
    exit 1
}
Write-Host ""

# ---- Wait for health checks ----
Write-Host "Waiting for services to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 8
docker compose ps
Write-Host ""

Write-Host "===== Restart Complete =====" -ForegroundColor Green
Write-Host ""
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor White
Write-Host "  Backend:  http://localhost:8000" -ForegroundColor White
Write-Host "  Gitea:    http://localhost:3000" -ForegroundColor White
Write-Host ""
Write-Host "  All persistent data preserved." -ForegroundColor Green
Write-Host "  Logs: docker compose logs -f backend" -ForegroundColor DarkGray
Write-Host ""
