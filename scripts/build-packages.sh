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
    if [ "${SKIP_BUILT:-0}" = 1 ]; then
        ver=$(head -1 "$pkg/debian/changelog" | sed -E 's/.*\(([^)]+)\).*/\1/')
        built=0
        for d in "$BUILD"/*_"${ver}"_*.deb; do
            [ -f "$d" ] || continue
            src=$(dpkg-deb -f "$d" Source 2>/dev/null | cut -d' ' -f1); bin=$(dpkg-deb -f "$d" Package 2>/dev/null)
            if [ "$src" = "$name" ] || { [ -z "$src" ] && [ "$bin" = "$name" ]; }; then built=1; break; fi
        done
        if [ $built = 1 ]; then echo "== $name $ver already built, skipping (SKIP_BUILT=1)"; continue; fi
    fi
    echo "== building $name"
    ( cd "$pkg" && dpkg-buildpackage -us -uc -b >"$BUILD/$name.build.log" 2>&1 ) \
        || { tail -40 "$BUILD/$name.build.log"; exit 1; }
    mv "$ROOT"/packages/*.deb "$ROOT"/packages/*.changes "$ROOT"/packages/*.buildinfo "$BUILD"/
    ( cd "$pkg" && dpkg-buildpackage -T clean >/dev/null 2>&1 ) || true
done
echo "== lintian"
lintian --tag-display-limit 0 "$BUILD"/*.changes || true
ls -1 "$BUILD"/*.deb
