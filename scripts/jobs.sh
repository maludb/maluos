#!/bin/bash
# List, inspect or stop jobs started by scripts/run-detached.sh.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
case "${1:-}" in
    "")  systemctl list-units --no-legend --all 'maluos-*' | awk '{print $1, $3, $4}'; 
         echo; echo "logs: $ROOT/build/logs/"; ls -1t "$ROOT/build/logs" 2>/dev/null | head ;;
    stop) sudo -n systemctl stop "maluos-$2" && echo "stopped maluos-$2" ;;
    *)   systemctl status "maluos-$1" --no-pager 2>&1 | head -5 || true
         echo "--- $ROOT/build/logs/$1.log"; tail -n "${2:-20}" "$ROOT/build/logs/$1.log" ;;
esac
