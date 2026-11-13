# Cortex Nexus service smoke gate.
# Detailed authenticated source-ingestion journeys are covered by Playwright E2E.
param(
    [string]$ApiUrlParam = "",
    [switch]$SkipInfra
)

$ErrorActionPreference = "Stop"

foreach ($arg in $args) {
    if ($arg -in @("--skip-infra", "-skip-infra", "/skip-infra")) {
        $SkipInfra = $true
    } elseif ($arg -like "http*") {
        $ApiUrlParam = $arg
    }
}

$ApiUrl = if ($ApiUrlParam) { $ApiUrlParam } else { $env:CORTEX_URL }
if (-not $ApiUrl -or $ApiUrl -notlike "http*") { $ApiUrl = "http://localhost:8000" }

$results = New-Object System.Collections.Generic.List[string]
$failed = 0
$skipped = 0

function Check {
    param([string]$Name, [scriptblock]$Test, [switch]$Optional)
    try {
        & $Test | Out-Null
        $results.Add("OK      $Name") | Out-Null
        Write-Host "  [OK]      $Name" -ForegroundColor Green
    } catch {
        if ($Optional) {
            $script:skipped++
            $results.Add("SKIP    $Name") | Out-Null
            Write-Host "  [SKIP]    $Name ($($_.Exception.Message))" -ForegroundColor DarkYellow
        } else {
            $script:failed++
            $results.Add("FAIL    $Name") | Out-Null
            Write-Host "  [FAIL]    $Name ($($_.Exception.Message))" -ForegroundColor Red
        }
    }
}

Write-Host ""
Write-Host "Cortex Nexus Smoke Gate" -ForegroundColor Cyan
Write-Host "=======================" -ForegroundColor Cyan
Write-Host ""

if (-not $SkipInfra) {
    Check "PostgreSQL" -Optional {
        Test-NetConnection -ComputerName localhost -Port 5432 -InformationLevel Quiet -WarningAction SilentlyContinue
    }
    Check "Redis" -Optional {
        Test-NetConnection -ComputerName localhost -Port 6379 -InformationLevel Quiet -WarningAction SilentlyContinue
    }
    Check "S3-compatible object storage" -Optional {
        Test-NetConnection -ComputerName localhost -Port 8333 -InformationLevel Quiet -WarningAction SilentlyContinue
    }
}

Check "Nexus API health" {
    (Invoke-WebRequest -Uri "$ApiUrl/healthz" -UseBasicParsing -TimeoutSec 10).StatusCode -eq 200
}
Check "Nexus frontend" -Optional {
    (Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 10).StatusCode -lt 500
}

Write-Host ""
foreach ($entry in $results) { Write-Host "  $entry" }
Write-Host ""
if ($failed -gt 0) {
    Write-Host "SMOKE GATE FAILED ($failed failed, $skipped skipped)" -ForegroundColor Red
    exit 1
}
Write-Host "SMOKE GATE PASSED ($skipped skipped)" -ForegroundColor Green
exit 0
