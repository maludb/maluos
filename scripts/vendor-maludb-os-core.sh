#!/bin/bash
# Vendor the Business OS kernel (github.com/maludb/maludb-os-core)
# into packages/maludb-os-core/upstream at a given ref, for the maludb-os-core package.
# usage: scripts/vendor-maludb-os-core.sh [ref]   (default: main)
#        MALUOS_KERNEL_REPO=/home/maludb/maludb-os-core scripts/vendor-maludb-os-core.sh d7ebcfa   a commit not pushed yet (the
#        local clone); the VENDORED file still names the GitHub repository, so the commit must reach it before a release
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); REF=${1:-main}
REPO=${MALUOS_KERNEL_REPO:-https://github.com/maludb/maludb-os-core.git}
DEST=$ROOT/packages/maludb-os-core/upstream
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
git clone -q --depth 1 --branch "$REF" "$REPO" "$T/src" 2>/dev/null \
    || { git clone -q "$REPO" "$T/src" && git -C "$T/src" checkout -q "$REF"; }
COMMIT=$(git -C "$T/src" rev-parse --short HEAD); VERSION=$(git -C "$T/src" log -1 --format=%cd --date=format:%Y.%m.%d)
rm -rf "$DEST"; mkdir -p "$DEST"
rsync -a --exclude .git --exclude node_modules --exclude "web/.next" --exclude "mcp/venv" --exclude "config/.env" "$T/src/" "$DEST/"
find "$DEST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
printf 'repository: https://github.com/maludb/maludb-os-core\nref: %s\ncommit: %s\nversion: %s\nvendored: %s\n' "$REF" "$COMMIT" "$VERSION" "$(date -u +%F)" > "$DEST/VENDORED"
cat "$DEST/VENDORED"
