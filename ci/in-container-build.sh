#!/bin/bash
# Everything that needs Ubuntu 26.04 tooling, run as root inside a privileged
# ubuntu:26.04 container (or on a 26.04 host): build the packages, serve them
# from an unsigned flat repo, build the rootfs + squashfs + qcow2, and the ISO
# when the base ISO is present at $BASE_ISO.
# usage: ci/in-container-build.sh [packages|images|iso|all]   (default all)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); cd "$ROOT"
STEP=${1:-all}
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends \
    build-essential devscripts debhelper dh-python lintian dpkg-dev gnupg python3 python3-yaml ca-certificates curl \
    mmdebstrap squashfs-tools xorriso qemu-utils dosfstools gdisk rsync fdisk e2fsprogs \
    util-linux mount grub-common >/dev/null
export PATH=/usr/sbin:/sbin:$PATH

if [ "$STEP" = packages ] || [ "$STEP" = all ] || [ "$STEP" = images ]; then
    [ -n "$(ls build/*.deb 2>/dev/null)" ] && [ "$STEP" = images ] || scripts/build-packages.sh
fi
[ "$STEP" = packages ] && exit 0

ci/build-flat-repo.sh build/ci-repo build/*.deb vendor/maludb/*.deb
python3 -m http.server -d build/ci-repo -b 127.0.0.1 8089 >/dev/null 2>&1 &
HTTP=$!; trap 'kill $HTTP 2>/dev/null || true' EXIT
sleep 1
REPO_URL=http://127.0.0.1:8089 REPO_FLAT=1 image/build-rootfs.sh
image/build-qcow2.sh
if [ "$STEP" = iso ] || [ "$STEP" = all ]; then
    if [ -f "${BASE_ISO:-/nonexistent}" ]; then
        BASE_ISO=$BASE_ISO iso/build-iso.sh
        xorriso -indev build/maluos-26.04.1-server-amd64.iso -report_el_torito plain 2>/dev/null | grep 'El Torito boot img'
    else
        echo "BASE_ISO not present; skipping ISO"
    fi
fi
sha256sum build/image/*.qcow2 build/image/*.squashfs build/*.iso 2>/dev/null | tee build/SHA256SUMS || true
