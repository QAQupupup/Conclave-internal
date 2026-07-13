#Requires -Version 5.1
<#
.SYNOPSIS
  在 Windows 上安装 Conclave 本地提交卡点（pre-commit hooks）。
.DESCRIPTION
  1. 检查并安装 pre-commit（pip 或 pipx）。
  2. 在 .git/hooks 中注册 pre-commit hook。
  3. 提供首次安装提示与手动运行命令。
#>
$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $repoRoot

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# 1. 确保 pre-commit 已安装
if (-not (Test-Command 'pre-commit')) {
    Write-Host "[install-hooks] pre-commit 未找到，尝试通过 pip 安装..." -ForegroundColor Cyan
    if (Test-Command 'python') {
        python -m pip install --user pre-commit
    } elseif (Test-Command 'python3') {
        python3 -m pip install --user pre-commit
    } else {
        Write-Error "未找到 python/python3，请先安装 Python。"
    }
}

# 刷新 PATH（pip --user 安装后需要）
$env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'User') + ';' + [Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' + $env:PATH

if (-not (Test-Command 'pre-commit')) {
    Write-Error "pre-commit 安装失败，请检查 Python/pip 环境。"
}

# 2. 安装 hooks
Write-Host "[install-hooks] 正在安装 pre-commit hooks..." -ForegroundColor Cyan
& pre-commit install
if ($LASTEXITCODE -ne 0) { Write-Error "pre-commit install 失败" }

# 3. 首次运行（可选，缓存环境）
Write-Host "[install-hooks] 首次运行缓存卡点环境（仅检查已修改文件）..." -ForegroundColor Cyan
& pre-commit run --show-diff-on-failure
# 首次运行失败通常是因为仓库本身的问题，不阻断安装

Write-Host "`n[install-hooks] 安装完成。后续每次 `git commit` 都会自动运行卡点。" -ForegroundColor Green
Write-Host "  手动运行全部卡点: pre-commit run --all-files" -ForegroundColor DarkGray
Write-Host "  跳过本次卡点:     git commit --no-verify`n" -ForegroundColor DarkGray
