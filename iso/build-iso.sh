#!/bin/bash
# Build the MaluOS Server ISO: the Ubuntu Server 26.04.1 live installer
# environment, unchanged, plus the MaluOS root filesystem (built from the
# seeds by image/build-rootfs.sh) as the default install source.
#
# Adds to the stock image:
#   /casper/maluos-server.squashfs        the MaluOS rootfs
#   /casper/maluos-server.cdrom.squashfs  layer with the base ISO's signed-pool cdrom.sources (default, fsimage-layered)
#   /maluos/apt/                 the published MaluOS repository (dists, pool, bootstrap)
#   /maluos/pgdg.sources         PGDG source file (same content as maluos-archive ships)
#   /maluos/nocloud-auto/        unattended autoinstall (user-data, meta-data)
#   /maluos/nocloud-interactive/ guided autoinstall
#   /boot/grub/grub.cfg          MaluOS menu
# and sets the volume id. Boot images (BIOS + UEFI) are replayed from the
# source ISO by xorriso, so the result boots exactly like the original.
#
# usage: iso/build-iso.sh [-i base.iso] [-o out.iso] [--ssh-key FILE] [--test]
#   --test   serial console on the installer kernel, 3 s timeout, automated
#            entry as default (for VM tests; never ship this variant)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"

BASE=${BASE_ISO:-$HOME/iso-cache/ubuntu-26.04.1-live-server-amd64.iso}
OUT=${OUT_ISO:-$ROOT/build/maluos-26.04.1-server-amd64.iso}
SSHKEY=""; TEST=0
while [ $# -gt 0 ]; do
    case "$1" in
        -i) BASE=$2; shift 2 ;;
        -o) OUT=$2; shift 2 ;;
        --ssh-key) SSHKEY=$2; shift 2 ;;
        --test) TEST=1; shift ;;
        *) echo "unknown arg $1" >&2; exit 2 ;;
    esac
done
[ -f "$BASE" ] || { echo "base ISO not found: $BASE" >&2; exit 1; }
[ -d "$MALUOS_PUBLISH_ROOT/dists" ] || { echo "no published repo at $MALUOS_PUBLISH_ROOT; run repo/publish.sh" >&2; exit 1; }
[ -f "$MALUOS_PUBLISH_ROOT/bootstrap/maluos-archive-keyring.gpg" ] || { echo "bootstrap/maluos-archive-keyring.gpg missing; re-run repo/publish.sh" >&2; exit 1; }

STAGE=$(mktemp -d "${TMPDIR:-/var/tmp}/maluos-iso.XXXXXX"); trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/maluos" "$STAGE/boot/grub" "$(dirname "$OUT")"

# --- repository + PGDG source --------------------------------------------
cp -rL "$MALUOS_PUBLISH_ROOT"/{dists,pool,bootstrap} "$STAGE/maluos/apt/" 2>/dev/null || {
    mkdir -p "$STAGE/maluos/apt"; cp -rL "$MALUOS_PUBLISH_ROOT"/{dists,pool,bootstrap} "$STAGE/maluos/apt/"; }
sed -e "s|@MALUOS_SUITE@|$MALUOS_SUITE|g" \
    "$ROOT/packages/maluos-archive/sources/pgdg.sources.in" > "$STAGE/maluos/pgdg.sources"

# --- autoinstall ---------------------------------------------------------
keys="[]"
if [ -n "$SSHKEY" ]; then
    keys=$(python3 -c 'import json,sys; print(json.dumps([l.strip() for l in open(sys.argv[1]) if l.strip()]))' "$SSHKEY")
fi
AUTOINSTALL_DIR=${AUTOINSTALL_DIR:-$ROOT/autoinstall}   # override for experiments
for v in auto interactive; do
    d="$STAGE/maluos/nocloud-$v"; mkdir -p "$d"
    python3 - "$AUTOINSTALL_DIR/server-$v.yaml" "$AUTOINSTALL_DIR/late-commands.yaml" "$keys" "$AUTOINSTALL_DIR/late-commands-$v.yaml" > "$d/user-data" <<'PY'
import os, sys
main, late, keys = open(sys.argv[1]).read(), open(sys.argv[2]).read(), sys.argv[3]
extra = open(sys.argv[4]).read() if os.path.exists(sys.argv[4]) else ""   # profile-specific tail (late-commands-auto.yaml)
main = main.replace("@AUTHORIZED_KEYS@", keys)
late = "\n".join(("  " + l if l.strip() and not l.startswith("#") else "") for l in late.splitlines())
extra = "\n".join(("  " + l if l.strip() and not l.startswith("#") else "") for l in extra.splitlines())
print(main.rstrip() + "\n" + late + "\n" + extra + "\n")
PY
    : > "$d/meta-data"
    # Validate before spending a VM boot on it: well-formed YAML, and every
    # late-command a string or list of strings (subiquity's schema).
    python3 - "$d/user-data" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
a = d["autoinstall"]; assert a.get("version") == 1
bad = [c for c in a.get("late-commands", []) if not (isinstance(c, str) or (isinstance(c, list) and all(isinstance(x, str) for x in c)))]
if bad:
    sys.exit("malformed late-commands (quote strings containing ': '):\n  " + "\n  ".join(map(str, bad)))
PY
    head -1 "$d/user-data" | grep -qx '#cloud-config' || { echo "user-data must start with #cloud-config" >&2; exit 1; }
done

# --- install source: the MaluOS rootfs squashfs ----------------------------
IMG=$ROOT/build/image/maluos-server
[ -f "$IMG.squashfs" ] || { echo "no $IMG.squashfs; run sudo image/build-rootfs.sh" >&2; exit 1; }
mkdir -p "$STAGE/casper"
# Ubuntu 26.04 ISOs sign the on-disc package pool with a one-time key. The
# stock squashfs ships etc/apt/sources.list.d/cdrom.sources with that key
# embedded and subiquity relies on it: without the file it writes an
# unsigned reference to the pool, apt rejects it and the install fails in
# configure_apt. Take the file from the base ISO's squashfs and ship it as a
# squashfs *layer* on top of ours (curtin's fsimage-layered: the name
# maluos-server.cdrom.squashfs stacks on maluos-server.squashfs), so the
# rootfs squashfs stays untouched. Subiquity deletes cdrom.sources from the
# installed system afterwards.
xorriso -osirrox on -indev "$BASE" -extract /casper/ubuntu-server-minimal.squashfs "$STAGE/base.squashfs" >/dev/null 2>&1
unsquashfs -q -n -d "$STAGE/base" "$STAGE/base.squashfs" etc/apt/sources.list.d/cdrom.sources >/dev/null 2>&1
CDROM_SRC=$STAGE/base/etc/apt/sources.list.d/cdrom.sources
[ -s "$CDROM_SRC" ] || { echo "base ISO squashfs has no cdrom.sources; cannot build an installable ISO" >&2; exit 1; }
rm -f "$STAGE/base.squashfs"
mkdir -p "$STAGE/layer/etc/apt/sources.list.d"; cp "$CDROM_SRC" "$STAGE/layer/etc/apt/sources.list.d/"
LAYER_SQUASH=$STAGE/casper/maluos-server.cdrom.squashfs
mksquashfs "$STAGE/layer" "$LAYER_SQUASH" -comp xz -quiet -no-progress -noappend >/dev/null
cp "$IMG.size" "$STAGE/casper/maluos-server.size"
cp "$IMG.manifest" "$STAGE/casper/maluos-server.manifest"
xorriso -osirrox on -indev "$BASE" -extract /casper/install-sources.yaml "$STAGE/casper/install-sources.yaml" >/dev/null 2>&1
chmod u+w "$STAGE/casper/install-sources.yaml"
python3 - "$STAGE/casper/install-sources.yaml" "$(cat "$IMG.size")" <<'PY'
import sys, yaml
path, size = sys.argv[1], int(sys.argv[2])
d = yaml.safe_load(open(path))
for s in d["sources"]:
    s.pop("default", None)
d["sources"].insert(0, {
    "default": True, "id": "maluos-server", "variant": "server", "type": "fsimage-layered",
    "path": "maluos-server.cdrom.squashfs", "size": size, "locale_support": "locale-only",
    "name": {"en": "MaluOS Server"},
    "description": {"en": "MaluOS 26.04: Ubuntu 26.04 base with PostgreSQL 18 and the MaluDB memory core preinstalled."},
})
yaml.safe_dump(d, open(path, "w"), sort_keys=False, allow_unicode=True)
PY

# --- grub ----------------------------------------------------------------
if [ $TEST = 1 ]; then
    # TEST_DEFAULT: 1 = automated entry (default), 0 = guided entry
    sed -e "s/@TIMEOUT@/3/; s/@DEFAULT@/${TEST_DEFAULT:-1}/; s/@EXTRA_ARGS@/console=ttyS0,115200n8 /" "$ROOT/iso/grub.cfg.in"
else
    sed -e 's/@TIMEOUT@/30/; s/@DEFAULT@/0/; s/@EXTRA_ARGS@//' "$ROOT/iso/grub.cfg.in"
fi > "$STAGE/boot/grub/grub.cfg"

# --- md5sum.txt: drop replaced entry, add new files ------------------------
xorriso -osirrox on -indev "$BASE" -extract /md5sum.txt "$STAGE/md5sum.txt" >/dev/null 2>&1
chmod u+w "$STAGE/md5sum.txt"
grep -vE ' ./(boot/grub/grub.cfg|casper/install-sources.yaml)$' "$STAGE/md5sum.txt" > "$STAGE/md5sum.new"
( cd "$STAGE" && find ./boot/grub/grub.cfg ./maluos ./casper -type f -exec md5sum {} + ) >> "$STAGE/md5sum.new"
echo "$(md5sum < "$IMG.squashfs" | cut -d' ' -f1)  ./casper/maluos-server.squashfs" >> "$STAGE/md5sum.new"
mv "$STAGE/md5sum.new" "$STAGE/md5sum.txt"

# --- assemble ------------------------------------------------------------
VOLID="MaluOS 26.04.1 Server amd64"; [ $TEST = 1 ] && VOLID="MaluOS TEST Server amd64"
rm -f "$OUT"
xorriso -indev "$BASE" -outdev "$OUT" \
    -boot_image any replay \
    -volid "$VOLID" \
    -overwrite on \
    -map "$STAGE/maluos" /maluos \
    -map "$IMG.squashfs" /casper/maluos-server.squashfs \
    -map "$LAYER_SQUASH" /casper/maluos-server.cdrom.squashfs \
    -map "$STAGE/casper/maluos-server.size" /casper/maluos-server.size \
    -map "$STAGE/casper/maluos-server.manifest" /casper/maluos-server.manifest \
    -map "$STAGE/casper/install-sources.yaml" /casper/install-sources.yaml \
    -map "$STAGE/boot/grub/grub.cfg" /boot/grub/grub.cfg \
    -map "$STAGE/md5sum.txt" /md5sum.txt \
    -commit 2>&1 | grep -vE '^xorriso : UPDATE|^(Drive|Media) ' || true
ls -la "$OUT"
echo "built $OUT (volid: $VOLID)"
