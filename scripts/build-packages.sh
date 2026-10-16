#!/bin/bash
# Build every source package under packages/ into build/ and run lintian.
# Environment: MALUOS_APT_URL / MALUOS_SUITE override the archive package's
# baked-in repository location (see repo/config.env).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
export MALUOS_APT_URL MALUOS_SUITE
BUILD=${BUILD_DIR:-$ROOT/build}
mkdir -p "$BUILD"

"$ROOT/scripts/gen-meta-control.sh"
test -s "$ROOT/packages/maluos-keyring/keys/maluos-archive-keyring.asc" \
    || { echo "missing public key; run repo/init.sh first" >&2; exit 1; }

for pkg in "$ROOT"/packages/*/; do
    name=$(basename "$pkg")
    echo "== building $name"
    ( cd "$pkg" && dpkg-buildpackage -us -uc -b >"$BUILD/$name.build.log" 2>&1 ) \
        || { tail -40 "$BUILD/$name.build.log"; exit 1; }
    mv "$ROOT"/packages/*.deb "$ROOT"/packages/*.changes "$ROOT"/packages/*.buildinfo "$BUILD"/
    ( cd "$pkg" && dpkg-buildpackage -T clean >/dev/null 2>&1 ) || true
done
echo "== lintian"
lintian --tag-display-limit 0 "$BUILD"/*.changes || true
ls -1 "$BUILD"/*.deb
