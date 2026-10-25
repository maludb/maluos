#!/bin/bash
# Everything that needs Ubuntu 26.04 tooling, run as root inside a privileged
# ubuntu:26.04 container (or on a 26.04 host): build the packages, serve them
# from an unsigned flat repo, build the rootfs + squashfs + qcow2, and the ISO
# when the base ISO is present at $BASE_ISO.
# usage: ci/in-container-build.sh [packages|images|iso|all]   (default all)
#   PROFILES="server desktop" builds both image profiles (default: server)
#   LIVE=1 also builds the live rootfs and the live medium for each profile (Phase 11 slice 1)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); cd "$ROOT"
STEP=${1:-all}; PROFILES=${PROFILES:-server}
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends \
    build-essential devscripts debhelper dh-python lintian dpkg-dev gnupg python3 python3-yaml python3-urwid openssl ca-certificates curl \
    mmdebstrap squashfs-tools xorriso qemu-utils dosfstools mtools gdisk rsync fdisk e2fsprogs \
    util-linux mount grub-common \
    composer php-cli php-pgsql nodejs npm python3-venv python3-pip \
    meson ninja-build pkgconf libgtkmm-4.0-dev libgtop2-dev libadwaita-1-dev libjson-glib-dev libcatch2-dev librsvg2-dev libsystemd-dev \
    gsettings-desktop-schemas-dev itstool docbook-to-man desktop-file-utils appstream polkitd \
    xvfb dbus-daemon xauth python3-gi gir1.2-glib-2.0 >/dev/null        # the last two lines: maluos-system-monitor (Phase 13 G1) and its test
export PATH=/usr/sbin:/sbin:$PATH

if [ "$STEP" = packages ] || [ "$STEP" = all ] || [ "$STEP" = images ]; then
    [ -n "$(ls build/*.deb 2>/dev/null)" ] && [ "$STEP" = images ] || scripts/build-packages.sh
fi
if [ "$STEP" = packages ] || [ "$STEP" = all ]; then
    python3 tests/install-plan-test.py          # the installer engine's pure parts (Phase 11 slice 2)
    python3 tests/install-screens-test.py       # the installer's screens driven in a pty (Phase 11 slice 3)
    python3 tests/apple-t2-test.py              # the Apple T2 round: the firmware renamer and importer, the vendored packages' checksums
    python3 tests/gpu-test.py                   # Phase 13 G1: the GPU reader (nvidia-smi, sysfs, chassis, the sharing rule)
    rm -rf build/gsm-root && dpkg-deb -x build/maluos-system-monitor_*_amd64.deb build/gsm-root \
        && tests/system-monitor-local-test.sh build/gsm-root/usr/bin/gnome-system-monitor   # the GPUs tab against a fake session, under Xvfb
fi
[ "$STEP" = packages ] && exit 0

ci/build-flat-repo.sh build/ci-repo build/*.deb vendor/*/*.deb
python3 -m http.server -d build/ci-repo -b 127.0.0.1 8089 >/dev/null 2>&1 &
HTTP=$!; trap 'kill $HTTP 2>/dev/null || true' EXIT
sleep 1
for profile in $PROFILES; do
    REPO_URL=http://127.0.0.1:8089 REPO_FLAT=1 image/build-rootfs.sh -p "$profile"
    image/build-qcow2.sh -p "$profile"
    rm -rf "build/image/maluos-$profile.rootfs"      # the squashfs and the qcow2 are what CI keeps; the tree is disk
done
if [ "${LIVE:-0}" = 1 ]; then
    # Phase 11 slice 1: the live environment, then the medium for each profile (the repo on it is the flat CI one)
    REPO_URL=http://127.0.0.1:8089 REPO_FLAT=1 image/build-rootfs.sh -p live
    rm -rf build/image/maluos-live.rootfs
    for profile in $PROFILES; do
        iso/build-live-iso.sh -p "$profile"
    done
fi
if [ "$STEP" = iso ] || [ "$STEP" = all ]; then
    if [ -f "${BASE_ISO:-/nonexistent}" ]; then
        for profile in $PROFILES; do
            BASE_ISO=$BASE_ISO iso/build-iso.sh -p "$profile"
            xorriso -indev "build/maluos-26.04.1-$profile-amd64.iso" -report_el_torito plain 2>/dev/null | grep 'El Torito boot img'
        done
    else
        echo "BASE_ISO not present; skipping ISO"
    fi
fi
sha256sum build/image/*.qcow2 build/image/*.squashfs build/*.iso 2>/dev/null | tee build/SHA256SUMS || true
