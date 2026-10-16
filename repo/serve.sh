#!/bin/bash
# Serve the published repository over plain HTTP for local testing.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
echo "serving $MALUOS_PUBLISH_ROOT on http://127.0.0.1:$MALUOS_SERVE_PORT"
exec python3 -m http.server -d "$MALUOS_PUBLISH_ROOT" -b 127.0.0.1 "$MALUOS_SERVE_PORT"
