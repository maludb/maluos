#!/bin/bash
# Vendor the office setup plugin (github.com/maludb/maluos-office-setup) into packages/maluos-office-setup/plugin
# at a given ref, for the maluos-office-setup package.
# usage: scripts/vendor-maluos-office-setup.sh [ref]   (default: main)
#        MALUOS_OFFICE_SETUP_SRC=/path/to/checkout scripts/vendor-maluos-office-setup.sh   a local tree (the handbook's
#        plugins/maluos-office-setup while the plugin lives there); VENDORED then records the path and its git commit if any
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); REF=${1:-main}
REPO=https://github.com/maludb/maluos-office-setup.git
DEST=$ROOT/packages/maluos-office-setup/plugin
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
if [ -n "${MALUOS_OFFICE_SETUP_SRC:-}" ]; then
    SRC=$MALUOS_OFFICE_SETUP_SRC; ORIGIN=$SRC
    COMMIT=$(git -C "$SRC" log -1 --format=%h -- . 2>/dev/null || true); COMMIT=${COMMIT:-uncommitted}; REF=local
else
    git clone -q --depth 1 --branch "$REF" "$REPO" "$T/src" 2>/dev/null \
        || { git clone -q "$REPO" "$T/src" && git -C "$T/src" checkout -q "$REF"; }
    SRC=$T/src; ORIGIN=$REPO; COMMIT=$(git -C "$SRC" rev-parse --short HEAD)
fi
VERSION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SRC/.claude-plugin/plugin.json")
rm -rf "$DEST"; mkdir -p "$DEST"
rsync -a --exclude .git --exclude __pycache__ --exclude .in_use --exclude dist --exclude packaging "$SRC/" "$DEST/"
printf 'repository: https://github.com/maludb/maluos-office-setup\norigin: %s\nref: %s\ncommit: %s\nversion: %s\nvendored: %s\n' "$ORIGIN" "$REF" "$COMMIT" "$VERSION" "$(date -u +%F)" > "$DEST/VENDORED"
cat "$DEST/VENDORED"
