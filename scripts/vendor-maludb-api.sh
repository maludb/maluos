#!/bin/bash
# Vendor the MaluDB Python API server (github.com/maludb/maludb-python-api-server)
# into packages/maludb-api/upstream at a given ref, for the maludb-api package.
# usage: scripts/vendor-maludb-api.sh [ref]   (default: main)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); REF=${1:-main}
DEST=$ROOT/packages/maludb-api/upstream
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
git clone -q --depth 1 --branch "$REF" https://github.com/maludb/maludb-python-api-server.git "$T/src" 2>/dev/null \
    || { git clone -q https://github.com/maludb/maludb-python-api-server.git "$T/src" && git -C "$T/src" checkout -q "$REF"; }
COMMIT=$(git -C "$T/src" rev-parse --short HEAD); VERSION=$(grep -m1 '^version' "$T/src/pyproject.toml" | cut -d'"' -f2)
rm -rf "$DEST"; mkdir -p "$DEST"
cp -r "$T/src"/{app,config,deploy,docs,tests,pyproject.toml,README.md,LICENSE} "$DEST/"
find "$DEST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
printf 'repository: https://github.com/maludb/maludb-python-api-server\nref: %s\ncommit: %s\nversion: %s\nvendored: %s\n' "$REF" "$COMMIT" "$VERSION" "$(date -u +%F)" > "$DEST/VENDORED"
cat "$DEST/VENDORED"
