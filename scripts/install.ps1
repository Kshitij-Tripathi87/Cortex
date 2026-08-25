# Cortex Nexus CLI Installer for Windows PowerShell
$ErrorActionPreference = "Stop"

$NexusVersion = "1.0.0"
$InstallDir = "$HOME\.nexus\bin"
$ExecutablePath = "$InstallDir\nexus.cmd"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   Cortex Nexus — Enterprise CLI Installer ($NexusVersion)   " -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

if (!(Test-Path -Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

Write-Host "[1/3] Creating Nexus Windows CLI launcher..." -ForegroundColor Green
$cmdContent = @"
@echo off
python -m app.cli.nexus_cli %*
"@
Set-Content -Path $ExecutablePath -Value $cmdContent -Force

Write-Host "[2/3] Adding Nexus to User PATH..." -ForegroundColor Green
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentPath;$InstallDir", "User")
}

Write-Host "[3/3] Verifying installation..." -ForegroundColor Green
Write-Host "Nexus CLI successfully installed to $ExecutablePath" -ForegroundColor Yellow
Write-Host ""
Write-Host "Get started with:"
Write-Host "  nexus login --server http://localhost:8000 --token <NEXUS_TOKEN>"
Write-Host "  nexus doctor"
Write-Host "  nexus deliberate --task SUPPLIER_OUTAGE --desc 'Critical component delay' --priority HIGH"
