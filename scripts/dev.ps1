# Single-command local dev launcher for Windows
param (
    [string]$Action = "dev"
)

$rootDir = Split-Path -Parent $PSScriptRoot
Set-Location $rootDir

if ($Action -eq "test") {
    python run.py test --suite nexus
} elseif ($Action -eq "regression") {
    python run.py test --suite regression
} elseif ($Action -eq "doctor") {
    python run.py doctor
} elseif ($Action -eq "build") {
    python run.py build
} else {
    python run.py dev
}
