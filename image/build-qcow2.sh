#!/bin/bash
# Build a bootable MaluOS disk image (qcow2, BIOS + UEFI) from the rootfs
# produced by image/build-rootfs.sh. cloud-init configures it on first boot.
#
# usage: sudo image/build-qcow2.sh [-p server] [-o build/image] [-s 8G]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROFILE=server; OUT=$ROOT/build/image; SIZE=8G
while [ $# -gt 0 ]; do case "$1" in -p) PROFILE=$2; shift 2;; -o) OUT=$2; shift 2;; -s) SIZE=$2; shift 2;; *) echo "bad arg $1" >&2; exit 2;; esac; done
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
NAME=maluos-$PROFILE; ROOTFS=$OUT/$NAME.rootfs
[ -d "$ROOTFS/usr" ] || { echo "no rootfs at $ROOTFS; run image/build-rootfs.sh" >&2; exit 1; }
RAW=$OUT/$NAME.raw; QCOW=$OUT/$NAME-26.04-amd64.qcow2
MNT=$(mktemp -d)
cleanup() { umount -R "$MNT" 2>/dev/null || true; [ -n "${LOOP:-}" ] && losetup -d "$LOOP" 2>/dev/null || true; rmdir "$MNT" 2>/dev/null || true; }
trap cleanup EXIT

echo "== partitioning $RAW ($SIZE)"
rm -f "$RAW"; truncate -s "$SIZE" "$RAW"
sgdisk -Z "$RAW" >/dev/null
sgdisk -n1:0:+1M  -t1:EF02 -c1:bios_grub \
       -n2:0:+256M -t2:EF00 -c2:ESP \
       -n3:0:0     -t3:8304 -c3:maluos-root "$RAW" >/dev/null
LOOP=$(losetup --find --show --partscan "$RAW")
mkfs.vfat -F32 -n ESP "${LOOP}p2" >/dev/null
mkfs.ext4 -q -L maluos-root "${LOOP}p3"

echo "== copying rootfs"
mount "${LOOP}p3" "$MNT"
rsync -aHAX --numeric-ids "$ROOTFS/" "$MNT/"
mkdir -p "$MNT/boot/efi"; mount "${LOOP}p2" "$MNT/boot/efi"
cat > "$MNT/etc/fstab" <<FSTAB
LABEL=maluos-root  /          ext4  defaults,discard  0 1
LABEL=ESP          /boot/efi  vfat  umask=0077        0 1
FSTAB
mkdir -p "$MNT/etc/default/grub.d"
cat > "$MNT/etc/default/grub.d/50-maluos-image.cfg" <<GRUB
GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0,115200"
GRUB_TIMEOUT=2
GRUB_TERMINAL="console serial"
GRUB_SERIAL_COMMAND="serial --speed=115200"
GRUB

echo "== installing grub (BIOS + UEFI)"
for d in dev dev/pts proc sys run; do mount --bind "/$d" "$MNT/$d"; done
chroot "$MNT" grub-install --target=i386-pc --no-floppy "$LOOP" 2>&1 | grep -viE '^Installing|^Installation finished|^$' || true
# Default (non --removable) install: EFI/ubuntu with shim, grub and the stub
# cfg that the signed grub's embedded config expects, plus (GRUB 2.14 default,
# --no-extra-removable to opt out) the EFI/BOOT fallback for firmware without
# a boot entry. Plain --removable only writes EFI/BOOT, which the signed grub
# ignores and drops to a prompt.
chroot "$MNT" grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu \
       --no-nvram --uefi-secure-boot 2>&1 | grep -viE '^Installing|^Installation finished|^$' || true
test -f "$MNT/boot/efi/EFI/ubuntu/grub.cfg" || { echo "EFI/ubuntu/grub.cfg missing" >&2; exit 1; }
# Booted through the fallback path, the signed grub reads $cmdpath/grub.cfg,
# i.e. EFI/BOOT/grub.cfg. Make sure the stub is there too.
mkdir -p "$MNT/boot/efi/EFI/BOOT"
cp "$MNT/boot/efi/EFI/ubuntu/grub.cfg" "$MNT/boot/efi/EFI/BOOT/grub.cfg"
echo "-- ESP contents:"; ( cd "$MNT/boot/efi" && find . -type f | sort | sed 's/^/   /' )
chroot "$MNT" update-grub 2>&1 | grep -iE "error|warn" || true
umount -R "$MNT"; losetup -d "$LOOP"; LOOP=""

echo "== converting to qcow2"
rm -f "$QCOW"
qemu-img convert -f raw -O qcow2 -c "$RAW" "$QCOW"
rm -f "$RAW"
chown "$(stat -c %u:%g "$ROOT")" "$QCOW"
ls -la "$QCOW"
