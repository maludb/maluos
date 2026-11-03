#!/bin/bash
# Replace vendor/maluos-fonts/*.deb with the maluos-fonts package found in <dir> (output of
# packaging/linux/fonts-package.sh in the maluos-slides repo, dist/release/) and update the README table.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); SRC=${1:?usage: $0 <dir-with-debs>}
rm -f "$ROOT"/vendor/maluos-fonts/*.deb
cp "$SRC"/maluos-fonts_*_all.deb "$ROOT/vendor/maluos-fonts/"
for d in "$ROOT"/vendor/maluos-fonts/*.deb; do
    p=$(dpkg-deb -f "$d" Package); v=$(dpkg-deb -f "$d" Version)
    sha=$(sha256sum "$d" | cut -c1-16)
    sed -i "s/^| $p | .* |$/| $p | $v | $sha… |/" "$ROOT/vendor/maluos-fonts/README.md"
done
ls -1 "$ROOT"/vendor/maluos-fonts/*.deb
