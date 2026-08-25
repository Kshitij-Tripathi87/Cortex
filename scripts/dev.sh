#!/usr/bin/env bash
# Single-command local dev launcher for macOS & Linux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

ACTION="${1:-dev}"

case "$ACTION" in
    test)
        python3 run.py test --suite nexus
        ;;
    regression)
        python3 run.py test --suite regression
        ;;
    doctor)
        python3 run.py doctor
        ;;
    build)
        python3 run.py build
        ;;
    *)
        python3 run.py dev
        ;;
esac
