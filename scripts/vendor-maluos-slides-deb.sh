#!/bin/bash
# Replace vendor/maluos-slides/*.deb with the MaluOS Slides package found in <dir> (output of
# packaging/linux/package.sh in the maluos-slides repo, dist/release/) and update the README table.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); SRC=${1:?usage: $0 <dir-with-debs>}
rm -f "$ROOT"/vendor/maluos-slides/*.deb
cp "$SRC"/maluos-slides-*-linux-x86_64.deb "$ROOT/vendor/maluos-slides/"
for d in "$ROOT"/vendor/maluos-slides/*.deb; do
    p=$(dpkg-deb -f "$d" Package); v=$(dpkg-deb -f "$d" Version)
    sha=$(sha256sum "$d" | cut -c1-16)
    sed -i "s/^| $p | .* |$/| $p | $v | $sha… |/" "$ROOT/vendor/maluos-slides/README.md"
done
ls -1 "$ROOT"/vendor/maluos-slides/*.deb
