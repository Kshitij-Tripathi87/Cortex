#!/usr/bin/env bash
# Cortex/Nexus service smoke gate (POSIX).
# Detailed authenticated source-ingestion journeys are covered by Playwright E2E.
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
    if [[ "$optional" == "optional" ]]; then
      skip "$name" "unreachable"
    else
      fail "$name" "unreachable"
    fi
  fi
}

url_ok() { curl -sf -o /dev/null -m 10 "$1"; }
tcp_ok() { (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null && exec 3>&-; return $?; }

echo ""
echo "Cortex Nexus Smoke Gate"
echo "======================="
echo ""

if [[ $SKIP_INFRA -eq 0 ]]; then
  check "PostgreSQL" optional tcp_ok localhost 5432
  check "Redis" optional tcp_ok localhost 6379
  check "S3-compatible object storage" optional tcp_ok localhost 8333
fi

check "Nexus API health" required url_ok "$API_URL/healthz"
check "Nexus frontend" optional url_ok "http://localhost:3000"

echo ""
if [[ $FAILED -gt 0 ]]; then
  printf "\033[31mSMOKE GATE FAILED (%s failed, %s skipped)\033[0m\n" "$FAILED" "$SKIPPED"
  exit 1
fi
printf "\033[32mSMOKE GATE PASSED (%s skipped)\033[0m\n" "$SKIPPED"
