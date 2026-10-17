#!/bin/bash
# Phase 3: build the MaluOS root filesystem from the seeds, and from it a
# squashfs install source for the ISO plus the inputs for the cloud image.
#
# usage: sudo image/build-rootfs.sh [-p server] [-o build/image]
# needs: repo/serve.sh running (the chroot fetches MaluOS packages from it)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
PROFILE=server; OUT=$ROOT/build/image
while [ $# -gt 0 ]; do case "$1" in -p) PROFILE=$2; shift 2;; -o) OUT=$2; shift 2;; *) echo "bad arg $1" >&2; exit 2;; esac; done
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
MIRROR=${MIRROR:-http://archive.ubuntu.com/ubuntu}
REPO_URL=${REPO_URL:-http://127.0.0.1:$MALUOS_SERVE_PORT}
curl -fsS "$REPO_URL/dists/$MALUOS_SUITE/Release" >/dev/null || { echo "MaluOS repo not reachable at $REPO_URL; start repo/serve.sh" >&2; exit 1; }

NAME=maluos-$PROFILE
ROOTFS=$OUT/$NAME.rootfs
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
cp "$ROOT/image/profiles/$PROFILE.pkgs" "$STAGE/profile.pkgs"
cp "$MALUOS_PUBLISH_ROOT/bootstrap/maluos-archive-keyring.gpg" "$STAGE/"
cp "$ROOT/image/stage-packages.sh" "$STAGE/"
mkdir -p "$OUT"; rm -rf "$ROOTFS"

echo "== bootstrapping $MALUOS_SUITE from $MIRROR into $ROOTFS"
mmdebstrap --mode=root --variant=important \
    --architectures=amd64 \
    --components=main,restricted,universe,multiverse \
    --include=ca-certificates,curl,gnupg \
    --customize-hook="copy-in $STAGE /tmp" \
    --customize-hook="mv \"\$1/tmp/$(basename "$STAGE")\" \"\$1/tmp/stage\"" \
    --customize-hook="chroot \"\$1\" sh /tmp/stage/stage-packages.sh $REPO_URL $MALUOS_SUITE" \
    "$MALUOS_SUITE" "$ROOTFS" \
    "deb $MIRROR $MALUOS_SUITE main restricted universe multiverse" \
    "deb $MIRROR $MALUOS_SUITE-updates main restricted universe multiverse" \
    "deb $MIRROR $MALUOS_SUITE-security main restricted universe multiverse" \
    > "$OUT/$NAME.mmdebstrap.log" 2>&1 || { tail -30 "$OUT/$NAME.mmdebstrap.log"; exit 1; }

echo "== manifest, size, squashfs"
chroot "$ROOTFS" dpkg-query -W -f='${Package}\t${Version}\n' > "$OUT/$NAME.manifest"
du -sb --apparent-size "$ROOTFS" | cut -f1 > "$OUT/$NAME.size"
rm -f "$OUT/$NAME.squashfs"
mksquashfs "$ROOTFS" "$OUT/$NAME.squashfs" -comp xz -b 1M -Xdict-size 100% -noappend -quiet -no-progress
chown "$(stat -c %u:%g "$ROOT")" "$OUT"/$NAME.{manifest,size,squashfs,mmdebstrap.log}
echo "packages: $(wc -l < "$OUT/$NAME.manifest")   uncompressed: $(numfmt --to=iec "$(cat "$OUT/$NAME.size")")   squashfs: $(du -h "$OUT/$NAME.squashfs" | cut -f1)"
grep -E '^(maluos-|postgresql-18|linux-image-generic|cloud-init)' "$OUT/$NAME.manifest"
