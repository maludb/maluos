#!/bin/bash
# Phase 11 slice 1: assemble the MaluOS installer medium from scratch (nothing
# replayed from Ubuntu's ISO): our live rootfs (image/build-rootfs.sh -p live),
# its kernel and initrd (casper, plymouth and the MaluOS splash inside), our grub
# menu, the BIOS El Torito image and the hybrid MBR from grub-pc-bin, an ESP
# with Ubuntu's signed shim and grub (the Secure Boot chain), the target image
# beside the live one under /maluos/images with its checksum, and the on-media
# repository as today. Boots from a DVD and from a USB stick written with dd,
# on BIOS, UEFI and UEFI with Secure Boot.
#
#   /.disk/info                        "MaluOS 26.04.1 Server amd64"
#   /boot/grub/{grub.cfg,fonts,i386-pc}  the menu, the font, the BIOS boot image and modules
#   /casper/{vmlinuz,initrd,maluos-live.squashfs,.size,.manifest}
#   /maluos/images/maluos-PROFILE.{squashfs,size,manifest}   the target (casper never sees it)
#   /maluos/SHA256SUMS                 the images, the kernel and the initrd
#   /maluos/apt/                       the published MaluOS repository (dists, pool, bootstrap)
#   /maluos/plan/                      the unattended plans (slice 2; empty now)
#   /EFI/boot/{bootx64.efi,grubx64.efi,mmx64.efi}   also in the appended ESP (GPT partition 2)
#
# usage: iso/build-live-iso.sh [-p server|desktop] [-o out.iso] [--ssh-key FILE] [--test]
#   --test   the serial-console entry is the default with a 3 s timeout and maluos.test=1
#            (the installer unit reports to the console and powers off); never ship it
# The output is build/maluos-26.04.1-PROFILE-amd64.live.iso until slice 4 renames it.
# All boot assets come out of the live squashfs, so the host needs only xorriso,
# squashfs-tools, dosfstools and mtools.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
OUT=""; PROFILE=server; SSHKEY=""; TEST=0
while [ $# -gt 0 ]; do
    case "$1" in
        -p) PROFILE=$2; shift 2 ;;
        -o) OUT=$2; shift 2 ;;
        --ssh-key) SSHKEY=$2; shift 2 ;;
        --test) TEST=1; shift ;;
        *) echo "unknown arg $1" >&2; exit 2 ;;
    esac
done
case "$PROFILE" in server) VARIANT=Server ;; desktop) VARIANT=Desktop ;; *) echo "unknown profile $PROFILE" >&2; exit 2 ;; esac
BASEVER=$(grep -oE 'VERSION_ID="[0-9.]+"' "$ROOT/packages/maluos-branding/files/share/os-release.server" | grep -oE '[0-9.]+')
[ -n "$OUT" ] || OUT=${OUT_ISO:-$ROOT/build/maluos-$BASEVER-$PROFILE-amd64.live.iso}
IMG=$ROOT/build/image
LIVE=$IMG/maluos-live.squashfs; TARGET=$IMG/maluos-$PROFILE.squashfs
[ -f "$LIVE" ] || { echo "no $LIVE; run sudo image/build-rootfs.sh -p live" >&2; exit 1; }
[ -f "$TARGET" ] || { echo "no $TARGET; run sudo image/build-rootfs.sh -p $PROFILE" >&2; exit 1; }
[ -d "$MALUOS_PUBLISH_ROOT/dists" ] || { echo "no published repo at $MALUOS_PUBLISH_ROOT; run repo/publish.sh" >&2; exit 1; }
for t in xorriso unsquashfs mkfs.vfat mcopy mmd; do command -v $t >/dev/null || { echo "need $t (xorriso, squashfs-tools, dosfstools, mtools)" >&2; exit 1; }; done

STAGE=$(mktemp -d "${TMPDIR:-/var/tmp}/maluos-live-iso.XXXXXX"); trap 'rm -rf "$STAGE"' EXIT
S=$STAGE/iso; mkdir -p "$S/.disk" "$S/boot/grub/fonts" "$S/boot/grub/i386-pc" "$S/casper" "$S/maluos/images" "$S/maluos/plan" "$S/EFI/boot" "$(dirname "$OUT")"

# --- the boot assets, out of the live rootfs ---------------------------------
echo "== boot assets from $LIVE"
unsquashfs -q -n -d "$STAGE/live" "$LIVE" 'boot/vmlinuz-*' 'boot/initrd.img-*' usr/lib/grub/i386-pc usr/lib/shim/shimx64.efi usr/lib/shim/mmx64.efi \
    usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed usr/share/grub/unicode.pf2 >/dev/null
KVER=$(ls "$STAGE/live/boot/" | sed -n 's/^vmlinuz-//p' | sort -V | tail -1)
[ -n "$KVER" ] && [ -f "$STAGE/live/boot/initrd.img-$KVER" ] || { echo "the live rootfs has no kernel and initrd under /boot" >&2; exit 1; }
cp "$STAGE/live/boot/vmlinuz-$KVER" "$S/casper/vmlinuz"; cp "$STAGE/live/boot/initrd.img-$KVER" "$S/casper/initrd"
chmod 644 "$S/casper/vmlinuz" "$S/casper/initrd"
PCDIR=$STAGE/live/usr/lib/grub/i386-pc
[ -f "$PCDIR/eltorito.img" ] && [ -f "$PCDIR/boot_hybrid.img" ] || { echo "grub-pc-bin in the live rootfs lacks eltorito.img/boot_hybrid.img" >&2; exit 1; }
cp "$PCDIR"/*.mod "$PCDIR"/*.lst "$PCDIR/eltorito.img" "$S/boot/grub/i386-pc/" 2>/dev/null
cp "$STAGE/live/usr/share/grub/unicode.pf2" "$S/boot/grub/fonts/unicode.pf2"
SHIM=$STAGE/live/usr/lib/shim/shimx64.efi; MM=$STAGE/live/usr/lib/shim/mmx64.efi; GCD=$STAGE/live/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed
[ -f "$SHIM" ] && [ -f "$MM" ] && [ -f "$GCD" ] || { echo "the live rootfs lacks shim-signed or grub-efi-amd64-signed" >&2; exit 1; }
# The signed CD grub (gcdx64) finds the medium by /.disk/info itself and loads /boot/grub/grub.cfg, as on Ubuntu's media.
cp "$SHIM" "$S/EFI/boot/bootx64.efi"; cp "$GCD" "$S/EFI/boot/grubx64.efi"; cp "$MM" "$S/EFI/boot/mmx64.efi"
cat > "$S/EFI/boot/grub.cfg" <<'G'
search --set=root --file /.disk/info
set prefix=($root)/boot/grub
configfile $prefix/grub.cfg
G
echo "   kernel $KVER, initrd $(du -h "$S/casper/initrd" | cut -f1), grub-pc $(ls "$PCDIR"/*.mod | wc -l) modules, shim + signed grub"

# --- the images --------------------------------------------------------------
echo "== images"
ln -s "$LIVE" "$S/casper/maluos-live.squashfs"
cp "$IMG/maluos-live.size" "$S/casper/maluos-live.size"; cp "$IMG/maluos-live.manifest" "$S/casper/maluos-live.manifest"
ln -s "$TARGET" "$S/maluos/images/maluos-$PROFILE.squashfs"
cp "$IMG/maluos-$PROFILE.size" "$S/maluos/images/"; cp "$IMG/maluos-$PROFILE.manifest" "$S/maluos/images/"
# paths relative to /maluos, as the installer reads them (26.04's sha256sum is uutils: no -L, so resolve the links)
( cd "$S/maluos" && for f in ../casper/maluos-live.squashfs ../casper/vmlinuz ../casper/initrd "images/maluos-$PROFILE.squashfs"; do
      printf '%s  %s\n' "$(sha256sum "$(readlink -f "$f")" | cut -d' ' -f1)" "$f"; done ) > "$S/maluos/SHA256SUMS"
: > "$S/maluos/plan/.keep"

# --- the repository ----------------------------------------------------------
mkdir -p "$S/maluos/apt"; cp -rL "$MALUOS_PUBLISH_ROOT"/{dists,pool,bootstrap} "$S/maluos/apt/"
sed -e "s|@MALUOS_SUITE@|$MALUOS_SUITE|g" "$ROOT/packages/maluos-archive/sources/pgdg.sources.in" > "$S/maluos/pgdg.sources"
if [ -n "$SSHKEY" ]; then
    mkdir -p "$S/maluos/ssh"; cp "$SSHKEY" "$S/maluos/ssh/authorized_keys"      # slice 2's maluos.ssh= reads it
fi

# --- identity and menu -------------------------------------------------------
VOLID="MALUOS_${BASEVER}_$(echo "$VARIANT" | tr '[:lower:]' '[:upper:]')"; [ $TEST = 1 ] && VOLID="MALUOS_TEST_$(echo "$VARIANT" | tr '[:lower:]' '[:upper:]')"
echo "MaluOS $BASEVER $VARIANT amd64$([ $TEST = 1 ] && echo ' (test)')" > "$S/.disk/info"
if [ $TEST = 1 ]; then
    # the menu on the serial line too (the test reads it there); noprompt: casper's "remove the medium, press ENTER" on shutdown is skipped
    sed -e "s/@TIMEOUT@/3/; s/@DEFAULT@/1/; s/@EXTRA_ARGS@/maluos.test=1 noprompt /" -e "s/@SERIAL@/serial --unit=0 --speed=115200\nterminal_input serial console\nterminal_output serial console/" "$ROOT/iso/grub-live.cfg.in"
else
    sed -e 's/@TIMEOUT@/30/; s/@DEFAULT@/0/; s/@EXTRA_ARGS@//; s/@SERIAL@//' "$ROOT/iso/grub-live.cfg.in"
fi | sed -e "s/@VARIANT@/$VARIANT/g" > "$S/boot/grub/grub.cfg"

# --- the ESP image -----------------------------------------------------------
EFIIMG=$STAGE/efi.img
mkfs.vfat -C -n ESP "$EFIIMG" 5120 >/dev/null
mmd -i "$EFIIMG" ::/EFI ::/EFI/boot
for f in bootx64.efi grubx64.efi mmx64.efi grub.cfg; do mcopy -i "$EFIIMG" "$S/EFI/boot/$f" "::/EFI/boot/$f"; done
EFISECTORS=$(( $(stat -c %s "$EFIIMG") / 512 ))

# --- assemble ----------------------------------------------------------------
echo "== xorriso -as mkisofs ($VOLID)"
rm -f "$OUT"
xorriso -as mkisofs -r -V "$VOLID" -J -joliet-long -l -iso-level 3 -follow-links \
    --grub2-mbr "$PCDIR/boot_hybrid.img" --protective-msdos-label -partition_cyl_align off -partition_offset 16 --mbr-force-bootable \
    -append_partition 2 28732ac11ff8d211ba4b00a0c93ec93b "$EFIIMG" -appended_part_as_gpt -iso_mbr_part_type a2a0d0ebe5b9334487c068b6b72699c7 \
    -c /boot.catalog -b /boot/grub/i386-pc/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
    -eltorito-alt-boot -e '--interval:appended_partition_2:all::' -no-emul-boot -boot-load-size "$EFISECTORS" \
    -o "$OUT" "$S" 2>&1 | grep -vE '^xorriso : UPDATE|^(Drive|Media) |^xorriso : NOTE : -as mkisofs' || true
xorriso -indev "$OUT" -report_el_torito plain 2>/dev/null | grep -E 'El Torito boot img|Boot record' | sed 's/^/   /'
ls -la "$OUT"
echo "built $OUT (volid: $VOLID; $(cat "$S/.disk/info"))"
