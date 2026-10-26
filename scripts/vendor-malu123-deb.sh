#!/bin/bash
# Replace vendor/malu123/*.deb with the Malu123 package found in <dir> (output of
# packaging/linux/package.sh in the malu123 repo) and update the README table.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); SRC=${1:?usage: $0 <dir-with-debs>}
rm -f "$ROOT"/vendor/malu123/*.deb
cp "$SRC"/malu123-*-linux-x86_64.deb "$ROOT/vendor/malu123/"
for d in "$ROOT"/vendor/malu123/*.deb; do
    p=$(dpkg-deb -f "$d" Package); v=$(dpkg-deb -f "$d" Version)
    sha=$(sha256sum "$d" | cut -c1-16)
    sed -i "s/^| $p | .* |$/| $p | $v | $sha… |/" "$ROOT/vendor/malu123/README.md"
done
ls -1 "$ROOT"/vendor/malu123/*.deb
