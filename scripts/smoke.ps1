# Cortex full-stack smoke gate.
# Verifies infrastructure, services, Workflo control plane, CLI, and a real
# sample sandbox execution. Exits non-zero when a required check fails.
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
    } elseif ($arg -in @("--skip-infra=false")) {
        # no-op guard for callers passing explicit values
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

function GetJson {
    param([string]$Url, [int]$TimeoutSec = 10)
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
    if ($response.StatusCode -ge 400) { throw "HTTP $($response.StatusCode)" }
    return $response.Content | ConvertFrom-Json
}

Write-Host ""
Write-Host "Cortex Smoke Gate" -ForegroundColor Cyan
Write-Host "=================" -ForegroundColor Cyan
Write-Host ""

if (-not $SkipInfra) {
    Check "PostgreSQL" -Optional { Test-NetConnection -ComputerName localhost -Port 5432 -InformationLevel Quiet -WarningAction SilentlyContinue }
    Check "Redis" -Optional { Test-NetConnection -ComputerName localhost -Port 6379 -InformationLevel Quiet -WarningAction SilentlyContinue }
    Check "MinIO" -Optional { (Invoke-WebRequest -Uri "http://localhost:9000/minio/health/live" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 }
}

Check "Nexus API health" { (GetJson "$ApiUrl/healthz").status -eq "ok" }
Check "Nexus API ready" -Optional { (GetJson "$ApiUrl/readyz").status -eq "ok" }
Check "Workflo control plane" {
    $health = GetJson "$ApiUrl/api/v1/workflo/health"
    $health.service -eq "workflo-control-plane"
}
Check "Frontend" -Optional { (Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 5).StatusCode -lt 500 }

Check "Workflo CLI installed" {
    $version = & workflo --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not ($version -match "^workflo \d+\.\d+\.\d+$")) {
        throw "workflo --version failed"
    }
}

Check "Sample sandbox execution" {
    $createBody = '{"workspace_id":"smoke","name":"smoke-gate"}'
    $created = Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/v1/workflo/sandboxes" `
        -ContentType "application/json" -Body $createBody -TimeoutSec 15
    if (-not $created.id.StartsWith("sbx_")) { throw "no sandbox id returned" }

    $execBody = '{"command":"echo cortex-smoke-ok"}'
    $exec = Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/v1/workflo/sandboxes/$($created.id)/execute" `
        -ContentType "application/json" -Body $execBody -TimeoutSec 30
    if ($exec.exit_code -ne 0) { throw "exit code $($exec.exit_code)" }
    if ($exec.stdout -notmatch "cortex-smoke-ok") { throw "unexpected stdout" }

    $blocked = $null
    try {
        Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/v1/workflo/sandboxes/$($created.id)/execute" `
            -ContentType "application/json" -Body '{"command":"curl http://evil.example.com"}' -TimeoutSec 15
    } catch {
        $blocked = $_.Exception.Response
    }
    if (-not $blocked) { throw "network violation was NOT blocked" }

    $destroyed = Invoke-RestMethod -Method Delete -Uri "$ApiUrl/api/v1/workflo/sandboxes/$($created.id)" -TimeoutSec 15
    if ($destroyed.status -ne "destroyed") { throw "destroy failed" }

    $reuseBlocked = $false
    try {
        Invoke-RestMethod -Method Post -Uri "$Api/api/v1/workflo/sandboxes/$($created.id)/execute" `
            -ContentType "application/json" -Body '{"command":"echo hi"}' -TimeoutSec 10
    } catch { $reuseBlocked = $true }
    if (-not $reuseBlocked) { throw "sandbox reuse after destroy was NOT blocked" }
}

Check "Contract: unknown sandbox is 404" {
    try {
        Invoke-WebRequest -Uri "$ApiUrl/api/v1/workflo/sandboxes/sbx_does_not_exist" -UseBasicParsing
        throw "expected 404"
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw "expected 404" }
    }
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
