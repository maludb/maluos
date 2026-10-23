#!/bin/bash
# Build a bootable MaluOS disk image (qcow2, BIOS + UEFI) from the rootfs
# produced by image/build-rootfs.sh. cloud-init configures it on first boot.
#
# usage: sudo image/build-qcow2.sh [-p server|desktop] [-o build/image] [-s 8G]
#   -s   disk size; default: the rootfs size rounded up plus 4 GiB, at least 8G
#        (both profiles fit 8G today); cloud-init grows
#        the root filesystem to the disk it boots from anyway
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROFILE=server; OUT=$ROOT/build/image; SIZE=
while [ $# -gt 0 ]; do case "$1" in -p) PROFILE=$2; shift 2;; -o) OUT=$2; shift 2;; -s) SIZE=$2; shift 2;; *) echo "bad arg $1" >&2; exit 2;; esac; done
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
NAME=maluos-$PROFILE; ROOTFS=$OUT/$NAME.rootfs
[ -d "$ROOTFS/usr" ] || { echo "no rootfs at $ROOTFS; run image/build-rootfs.sh -p $PROFILE" >&2; exit 1; }
if [ -z "$SIZE" ]; then
    bytes=$(cat "$OUT/$NAME.size" 2>/dev/null || du -sb --apparent-size "$ROOTFS" | cut -f1)
    g=$(( (bytes + (1<<30) - 1) / (1<<30) + 4 )); [ $g -lt 8 ] && g=8; SIZE=${g}G
fi
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
# Inside containers devtmpfs does not create the partition nodes; make them.
for sysp in /sys/block/$(basename "$LOOP")/$(basename "$LOOP")p*; do
    [ -e "$sysp" ] || continue
    dev=/dev/$(basename "$sysp")
    if [ ! -e "$dev" ]; then IFS=: read -r maj min < "$sysp/dev"; mknod "$dev" b "$maj" "$min"; fi
done
[ -e "${LOOP}p3" ] || { echo "partition nodes for $LOOP missing" >&2; exit 1; }
mkfs.vfat -F32 -n ESP "${LOOP}p2" >/dev/null
mkfs.ext4 -q -L maluos-root "${LOOP}p3"

echo "== copying rootfs"
mount "${LOOP}p3" "$MNT"
# MALUOS_RSYNC_BWLIMIT (e.g. 60m) throttles the copy: the dev VM's host has frozen and killed the VM under
# sustained writes (docs/phase12-desktop.md, slice 6 status; 2026-10-23 02:11 during this step).
rsync -aHAX --numeric-ids ${MALUOS_RSYNC_BWLIMIT:+--bwlimit=$MALUOS_RSYNC_BWLIMIT} "$ROOTFS/" "$MNT/"
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
# grub-mkconfig falls back to the build-time device name (root=/dev/loopXp3)
# when grub-probe cannot resolve the filesystem UUID, as happens inside
# containers. Pin root= to the UUID and make sure the result never names a
# loop device.
ROOT_UUID=$(blkid -s UUID -o value "${LOOP}p3")
sed -i -E "s|root=/dev/loop[0-9]+p3|root=UUID=$ROOT_UUID|g; s|set root='hd0,gpt3'|search --no-floppy --fs-uuid --set=root $ROOT_UUID|g" "$MNT/boot/grub/grub.cfg"
grep -q "root=UUID=$ROOT_UUID" "$MNT/boot/grub/grub.cfg" || { echo "grub.cfg has no root=UUID=$ROOT_UUID" >&2; exit 1; }
! grep -q '/dev/loop' "$MNT/boot/grub/grub.cfg" || { echo "grub.cfg still references a loop device" >&2; exit 1; }
umount -R "$MNT"; losetup -d "$LOOP"; LOOP=""

echo "== converting to qcow2"
rm -f "$QCOW"
# direct I/O on both sides (no page cache) and, with MALUOS_IMAGE_RATE (e.g. 80M), a rate limit: see the rsync note above
qemu-img convert -t none -T none ${MALUOS_IMAGE_RATE:+-r $MALUOS_IMAGE_RATE} -f raw -O qcow2 -c "$RAW" "$QCOW"
rm -f "$RAW"
chown "$(stat -c %u:%g "$ROOT")" "$QCOW"
ls -la "$QCOW"
