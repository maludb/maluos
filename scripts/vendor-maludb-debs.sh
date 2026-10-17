#!/bin/bash
# Replace vendor/maludb/*.deb with the engine packages found in <dir>
# (output of dpkg-buildpackage in maludb-core-26) and update the README table.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); SRC=${1:?usage: $0 <dir-with-debs>}
rm -f "$ROOT"/vendor/maludb/*.deb
cp "$SRC"/postgresql-18-maludb-core_*_amd64.deb "$SRC"/maludb-mc2dbd_*_amd64.deb "$ROOT/vendor/maludb/"
for d in "$ROOT"/vendor/maludb/*.deb; do
    p=$(dpkg-deb -f "$d" Package); v=$(dpkg-deb -f "$d" Version)
    sed -i "s/^| $p | .* |$/| $p | $v |/" "$ROOT/vendor/maludb/README.md"
done
ls -1 "$ROOT"/vendor/maludb/*.deb
