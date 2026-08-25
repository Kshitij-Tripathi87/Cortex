#!/usr/bin/env bash
# Cortex full-stack smoke gate (POSIX).
# Mirrors scripts/smoke.ps1. Exits non-zero when a required check fails.
set -u

API_URL="${CORTEX_URL:-http://localhost:8000}"
SKIP_INFRA=0
[[ "${1:-}" == "--skip-infra" ]] && SKIP_INFRA=1

FAILED=0
SKIPPED=0

ok()   { printf "  \033[32m[OK]\033[0m      %s\n" "$1"; }
fail() { printf "  \033[31m[FAIL]\033[0m    %s (%s)\n" "$1" "${2:-}"; FAILED=$((FAILED+1)); }
skip() { printf "  \033[33m[SKIP]\033[0m    %s (%s)\n" "$1" "${2:-}"; SKIPPED=$((SKIPPED+1)); }

check() {
  local name="$1" optional="$2"
  shift 2
  if "$@" >/dev/null 2>&1; then
    ok "$name"
  else
    if [[ "$optional" == "optional" ]]; then skip "$name" "unreachable"; else fail "$name" "unreachable"; fi
  fi
}

url_ok() { curl -sf -o /dev/null -m 10 "$1"; }
tcp_ok() { (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null && exec 3>&-; return $?; }
cli_ok() { workflo --version | grep -Eq '^workflo [0-9]+\.[0-9]+\.[0-9]+$'; }

sandbox_flow() {
  local created exec_json destroyed status
  created=$(curl -sf -X POST "$API_URL/api/v1/workflo/sandboxes" \
    -H 'Content-Type: application/json' \
    -d '{"workspace_id":"smoke","name":"smoke-gate"}') || return 1
  local sid
  sid=$(printf '%s' "$created" | sed -n 's/.*"id":"\(sbx_[^"]*\)".*/\1/p')
  [[ -n "$sid" ]] || return 1

  exec_json=$(curl -sf -X POST "$API_URL/api/v1/workflo/sandboxes/$sid/execute" \
    -H 'Content-Type: application/json' \
    -d '{"command":"echo cortex-smoke-ok"}') || return 1
  printf '%s' "$exec_json" | grep -q '"exit_code":0' || return 1

  # network violation must be blocked (403)
  status=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
    "$API_URL/api/v1/workflo/sandboxes/$sid/execute" \
    -H 'Content-Type: application/json' \
    -d '{"command":"curl http://evil.example.com"}')
  [[ "$status" == "403" ]] || { echo "network violation not blocked ($status)"; return 1; }

  destroyed=$(curl -sf -X DELETE "$API_URL/api/v1/workflo/sandboxes/$sid") || return 1
  printf '%s' "$destroyed" | grep -q '"status":"destroyed"' || return 1

  # reuse after destroy must be blocked (404/403)
  status=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
    "$API_URL/api/v1/workflo/sandboxes/$sid/execute" \
    -H 'Content-Type: application/json' -d '{"command":"echo hi"}')
  [[ "$status" == "403" || "$status" == "404" ]] || { echo "reuse not blocked ($status)"; return 1; }
}

not_found_404() {
  local status
  status=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/api/v1/workflo/sandboxes/sbx_does_not_exist")
  [[ "$status" == "404" ]]
}

echo ""
echo "Cortex Smoke Gate"
echo "================="
echo ""

if [[ $SKIP_INFRA -eq 0 ]]; then
  check "PostgreSQL" optional tcp_ok localhost 5432
  check "Redis" optional tcp_ok localhost 6379
  check "MinIO" optional url_ok "http://localhost:9000/minio/health/live"
fi

check "Nexus API health" required url_ok "$API_URL/healthz"
check "Workflo control plane" required url_ok "$API_URL/api/v1/workflo/health"
check "Frontend" optional url_ok "http://localhost:3000"
check "Workflo CLI installed" required cli_ok
check "Sample sandbox execution" required sandbox_flow
check "Contract: unknown sandbox is 404" required not_found_404

echo ""
if [[ $FAILED -gt 0 ]]; then
  printf "\033[31mSMOKE GATE FAILED (%s failed, %s skipped)\033[0m\n" "$FAILED" "$SKIPPED"
  exit 1
fi
printf "\033[32mSMOKE GATE PASSED (%s skipped)\033[0m\n" "$SKIPPED"
