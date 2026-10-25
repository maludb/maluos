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
#   /maluos/apt/extra/                 Ubuntu packages for the apple-t2 component the image lacks (iso/extra-pool.py)
#   /maluos/apple/firmware.sh          the t2linux script a Mac owner runs in macOS (the Wi-Fi firmware onto the EFI partition)
#   /maluos/plan/PROFILE-unattended.yaml   the unattended plan (slice 2); test.yaml with --test-install
#   /maluos/catalog.yaml               the components the medium can install (iso/catalog.py)
#   /EFI/boot/{bootx64.efi,grubx64.efi,mmx64.efi}   also in the appended ESP (GPT partition 2)
#
# usage: iso/build-live-iso.sh [-p server|desktop] [-o out.iso] [--ssh-key FILE] [--test | --test-install | --test-ssh]
#   --test          the serial-console entry is the default with a 3 s timeout and maluos.test=1
#                   (the installer unit reports the medium and powers off); never ship it
#   --test-install  (slice 2) the default entry installs from /maluos/plan/test.yaml: the profile's
#                   unattended plan with the --ssh-key as the user's key, the SSH server on, the serial
#                   console; maluos.test=1 makes the console unit power off after a failure
#   --test-ssh      (slice 2) the default entry boots the live environment with maluos.ssh=media and no
#                   plan, for the remote-install test
#   --ssh-key FILE  the public key for maluos.ssh=media (/maluos/ssh/authorized_keys) and the test plan
# The plans (iso/plans/PROFILE-unattended.yaml) and the catalogue (iso/catalog.py) go onto the medium and
# every plan is checked with maluos-install --check before the image is assembled.
# The output is build/maluos-26.04.1-PROFILE-amd64.live.iso until slice 4 renames it.
# All boot assets come out of the live squashfs, so the host needs only xorriso,
# squashfs-tools, dosfstools and mtools.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
OUT=""; PROFILE=server; SSHKEY=""; TEST=0; TESTINSTALL=0; TESTSSH=0
while [ $# -gt 0 ]; do
    case "$1" in
        -p) PROFILE=$2; shift 2 ;;
        -o) OUT=$2; shift 2 ;;
        --ssh-key) SSHKEY=$2; shift 2 ;;
        --test) TEST=1; shift ;;
        --test-install) TESTINSTALL=1; shift ;;
        --test-ssh) TESTSSH=1; shift ;;
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
for t in xorriso unsquashfs mkfs.vfat mcopy mmd python3; do command -v $t >/dev/null || { echo "need $t (xorriso, squashfs-tools, dosfstools, mtools, python3)" >&2; exit 1; }; done
python3 -c 'import yaml' 2>/dev/null || { echo "need python3-yaml (the plans are checked with the installer's own code)" >&2; exit 1; }
INSTALLER=$ROOT/packages/maluos-installer/bin/maluos-install
[ $TESTINSTALL = 1 ] && [ -z "$SSHKEY" ] && { echo "--test-install needs --ssh-key FILE" >&2; exit 1; }
[ $TESTSSH = 1 ] && [ -z "$SSHKEY" ] && { echo "--test-ssh needs --ssh-key FILE" >&2; exit 1; }

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
# the Apple T2 round: the Ubuntu packages the apple-t2 component needs beyond the image, and the script for macOS
if [ "${MALUOS_NO_EXTRA_POOL:-0}" = 1 ]; then echo "   extra pool skipped (MALUOS_NO_EXTRA_POOL=1): the apple-t2 component will not install offline"
else python3 "$ROOT/iso/extra-pool.py" --manifest "$IMG/maluos-$PROFILE.manifest" --squashfs "$TARGET" --out "$S/maluos/apt/extra" \
        --index "$S/maluos/apt/dists/$MALUOS_SUITE/$MALUOS_COMPONENT/binary-amd64/Packages" --seed "$ROOT/seeds/apple-t2.seed" | sed 's/^/   /'
fi
mkdir -p "$S/maluos/apple"; cp "$ROOT/packages/maluos-apple-t2-support/share/firmware.sh" "$S/maluos/apple/firmware.sh"
cat > "$S/maluos/apple/README.txt" <<'TXT'
Intel Macs with the T2 chip (2018 and later): run firmware.sh in macOS first
(Terminal: bash /Volumes/<this medium>/maluos/apple/firmware.sh, choose 1).
It copies the Mac's Wi-Fi and Bluetooth firmware to the EFI partition; the
MaluOS installer imports it from there. Then: Startup Security Utility
(Command-R at power-on, Utilities menu): Security "No Security", external
media allowed; shrink the APFS container in Disk Utility if macOS stays;
hold Option at power-on and choose "EFI Boot" to start this medium.
docs/phase11-apple-t2.md in the MaluOS repository has the whole guide.
TXT
if [ -n "$SSHKEY" ]; then
    mkdir -p "$S/maluos/ssh"; cp "$SSHKEY" "$S/maluos/ssh/authorized_keys"      # maluos.ssh=media reads it
fi

# --- the plans and the catalogue (slice 2) ----------------------------------
echo "== plans and catalogue"
rm -f "$S/maluos/plan/.keep"
cp "$ROOT/iso/plans/$PROFILE-unattended.yaml" "$S/maluos/plan/$PROFILE-unattended.yaml"
python3 "$ROOT/iso/catalog.py" "$ROOT/seeds" "$ROOT/packages/maluos-meta/debian/descriptions" \
    "$S/maluos/apt/dists/$MALUOS_SUITE/$MALUOS_COMPONENT/binary-amd64/Packages" "$IMG/maluos-$PROFILE.manifest" > "$S/maluos/catalog.yaml"
if [ $TESTINSTALL = 1 ] || [ $TESTSSH = 1 ]; then
    # the test plan: the unattended plan with the test key, the SSH server on, the serial console, telemetry off;
    # no forced password change (sshd refuses a non-interactive command for an expired password, and the test
    # drives the installed system over SSH). TEST_PLAN_LAYOUT, TEST_PLAN_FS and TEST_PLAN_ENCRYPT (a passphrase)
    # in the environment pick another of the four layouts; TEST_PLAN_TARGET=free installs into the free space.
    SSHKEY_TEXT=$(cat "$SSHKEY") python3 - "$S/maluos/plan/$PROFILE-unattended.yaml" "$S/maluos/plan/test.yaml" <<'PY'
import os, sys, yaml
src, dst = sys.argv[1:3]
doc = yaml.safe_load(open(src)); p = doc["maluos-install"]
p.setdefault("identity", {}).setdefault("user", {})["ssh_keys"] = [os.environ["SSHKEY_TEXT"].strip()]
p["identity"]["user"]["password_change_required"] = False
p["identity"].setdefault("ssh", {})["server"] = True
st = p.setdefault("storage", {})
if os.environ.get("TEST_PLAN_LAYOUT"):
    st["layout"] = os.environ["TEST_PLAN_LAYOUT"]; st.pop("root_size", None)
if os.environ.get("TEST_PLAN_FS"):
    st["filesystem"] = os.environ["TEST_PLAN_FS"]
if os.environ.get("TEST_PLAN_ENCRYPT"):
    st["encrypt"] = True; st["passphrase"] = os.environ["TEST_PLAN_ENCRYPT"]; st.pop("root_size", None)
if os.environ.get("TEST_PLAN_TARGET") == "free":   # beside the kept partitions (the Apple T2 round); the disk must have an ESP and free space
    st["target"] = "free"; st["erase"] = False
bl = p.setdefault("bootloader", {}); cl = bl.get("cmdline", "")
if "ttyS0" not in cl: bl["cmdline"] = (cl + " console=tty1 console=ttyS0,115200").strip()
p["telemetry"] = {"send": False}; p["finish"] = {"action": "reboot"}
open(dst, "w").write("# The install test's plan (iso/build-live-iso.sh --test-install); never on release media.\n" + yaml.safe_dump(doc, sort_keys=False))
PY
fi
for plan in "$S"/maluos/plan/*.yaml; do
    echo "   check $(basename "$plan")"
    "$INSTALLER" --plan "$plan" --check --no-hardware --media "$S" > "$STAGE/check-$(basename "$plan").log" 2>&1 \
        || { cat "$STAGE/check-$(basename "$plan").log"; echo "the plan $(basename "$plan") does not check against this medium" >&2; exit 1; }
done
echo "   $(ls "$S/maluos/plan" | tr '\n' ' ')· catalogue: $(grep -c '^  - name:' "$S/maluos/catalog.yaml") components"

# --- identity and menu -------------------------------------------------------
ANYTEST=$(( TEST | TESTINSTALL | TESTSSH ))
VOLID="MALUOS_${BASEVER}_$(echo "$VARIANT" | tr '[:lower:]' '[:upper:]')"; [ $ANYTEST = 1 ] && VOLID="MALUOS_TEST_$(echo "$VARIANT" | tr '[:lower:]' '[:upper:]')"
echo "MaluOS $BASEVER $VARIANT amd64$([ $ANYTEST = 1 ] && echo ' (test)')" > "$S/.disk/info"
SERIAL_CFG="serial --unit=0 --speed=115200\nterminal_input serial console\nterminal_output serial console"
if [ $TEST = 1 ]; then
    # the menu on the serial line too (the test reads it there); noprompt: casper's "remove the medium, press ENTER" on shutdown is skipped
    sed -e "s/@TIMEOUT@/3/; s/@DEFAULT@/1/; s/@EXTRA_ARGS@/maluos.test=1 noprompt /; s/@TEST_ARGS@//" -e "s/@SERIAL@/$SERIAL_CFG/" "$ROOT/iso/grub-live.cfg.in"
elif [ $TESTINSTALL = 1 ]; then
    # entry 4 (the test install) is the default: the test plan, the serial console, power off after a failure
    sed -e "s/@TIMEOUT@/3/; s/@DEFAULT@/4/; s/@EXTRA_ARGS@//; s/@TEST_ARGS@/maluos.test=1 noprompt /" -e "s/@SERIAL@/$SERIAL_CFG/" "$ROOT/iso/grub-live.cfg.in"
elif [ $TESTSSH = 1 ]; then
    # entry 1 (the serial console) is the default with maluos.ssh=media and no plan
    sed -e "s/@TIMEOUT@/3/; s/@DEFAULT@/1/; s/@EXTRA_ARGS@/maluos.ssh=media noprompt /; s/@TEST_ARGS@//" -e "s/@SERIAL@/$SERIAL_CFG/" "$ROOT/iso/grub-live.cfg.in"
else
    sed -e 's/@TIMEOUT@/30/; s/@DEFAULT@/0/; s/@EXTRA_ARGS@//; s/@TEST_ARGS@//; s/@SERIAL@//' "$ROOT/iso/grub-live.cfg.in"
fi | sed -e "s/@VARIANT@/$VARIANT/g; s/@PROFILE@/$PROFILE/g" > "$S/boot/grub/grub.cfg"

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
