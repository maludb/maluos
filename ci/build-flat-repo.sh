#!/bin/bash
# Build an unsigned flat apt repository from .deb files (CI has no signing key).
# usage: ci/build-flat-repo.sh <outdir> <deb>...
set -euo pipefail
OUT=${1:?outdir}; shift
rm -rf "$OUT"; mkdir -p "$OUT"; cp "$@" "$OUT/"
( cd "$OUT" && dpkg-scanpackages --multiversion . /dev/null > Packages 2>/dev/null && gzip -k -f Packages
  { echo "Origin: MaluOS-CI"; echo "Label: MaluOS-CI"; echo "Suite: ./"; echo "Architectures: amd64 all"
    echo "Date: $(date -Ru)"; echo "MD5Sum:"
    for f in Packages Packages.gz; do printf ' %s %d %s\n' "$(md5sum < $f | cut -d' ' -f1)" "$(stat -c %s $f)" "$f"; done
    echo "SHA256:"
    for f in Packages Packages.gz; do printf ' %s %d %s\n' "$(sha256sum < $f | cut -d' ' -f1)" "$(stat -c %s $f)" "$f"; done
  } > Release )
echo "flat repo at $OUT: $(grep -c '^Package:' "$OUT/Packages") packages"
