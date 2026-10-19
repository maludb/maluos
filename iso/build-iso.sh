#!/bin/bash
# Build a MaluOS ISO: the Ubuntu Server 26.04.1 live installer environment,
# unchanged, plus a MaluOS root filesystem (built from the seeds by
# image/build-rootfs.sh -p PROFILE) as the default install source. The
# server and the desktop ISO differ only in that rootfs, the menu text and
# the installed kernel command line (autoinstall/late-commands-PROFILE.yaml).
#
# Adds to the stock image (NAME = maluos-PROFILE):
#   /casper/NAME.squashfs        the MaluOS rootfs
#   /casper/NAME.cdrom.squashfs  layer with the base ISO's signed-pool cdrom.sources (default, fsimage-layered)
#   /maluos/apt/                 the published MaluOS repository (dists, pool, bootstrap)
#   /maluos/pgdg.sources         PGDG source file (same content as maluos-archive ships)
#   /maluos/nocloud-auto/        unattended autoinstall (user-data, meta-data)
#   /maluos/nocloud-interactive/ guided autoinstall
#   /boot/grub/grub.cfg          MaluOS menu
# and sets the volume id. Boot images (BIOS + UEFI) are replayed from the
# source ISO by xorriso, so the result boots exactly like the original.
#
# usage: iso/build-iso.sh [-p server|desktop] [-i base.iso] [-o out.iso] [--ssh-key FILE] [--test]
#   --test   serial console on the installer kernel, 3 s timeout, automated
#            entry as default (for VM tests; never ship this variant)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"

BASE=${BASE_ISO:-$HOME/iso-cache/ubuntu-26.04.1-live-server-amd64.iso}
OUT=""; PROFILE=server
SSHKEY=""; TEST=0
while [ $# -gt 0 ]; do
    case "$1" in
        -p) PROFILE=$2; shift 2 ;;
        -i) BASE=$2; shift 2 ;;
        -o) OUT=$2; shift 2 ;;
        --ssh-key) SSHKEY=$2; shift 2 ;;
        --test) TEST=1; shift ;;
        *) echo "unknown arg $1" >&2; exit 2 ;;
    esac
done
[ -n "$OUT" ] || OUT=${OUT_ISO:-$ROOT/build/maluos-26.04.1-$PROFILE-amd64.iso}
NAME=maluos-$PROFILE
case "$PROFILE" in server) VARIANT=Server ;; desktop) VARIANT=Desktop ;; *) echo "unknown profile $PROFILE" >&2; exit 2 ;; esac
[ -f "$ROOT/autoinstall/late-commands-$PROFILE.yaml" ] || { echo "no autoinstall/late-commands-$PROFILE.yaml" >&2; exit 1; }
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
    python3 - "$AUTOINSTALL_DIR/server-$v.yaml" "$AUTOINSTALL_DIR/late-commands.yaml" "$keys" \
        "$AUTOINSTALL_DIR/late-commands-$PROFILE.yaml" "$AUTOINSTALL_DIR/late-commands-$v.yaml" "$NAME" > "$d/user-data" <<'PY'
import os, sys
main, late, keys, name = open(sys.argv[1]).read(), open(sys.argv[2]).read(), sys.argv[3], sys.argv[6]
def tail(path):   # a profile tail (late-commands-server.yaml) or a variant tail (late-commands-auto.yaml)
    t = open(path).read() if os.path.exists(path) else ""
    return "\n".join(("  " + l if l.strip() and not l.startswith("#") else "") for l in t.splitlines())
main = main.replace("@AUTHORIZED_KEYS@", keys).replace("id: maluos-server", "id: " + name)
late = "\n".join(("  " + l if l.strip() and not l.startswith("#") else "") for l in late.splitlines())
print(main.rstrip() + "\n" + late + "\n" + tail(sys.argv[4]) + "\n" + tail(sys.argv[5]) + "\n")
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
IMG=$ROOT/build/image/$NAME
[ -f "$IMG.squashfs" ] || { echo "no $IMG.squashfs; run sudo image/build-rootfs.sh -p $PROFILE" >&2; exit 1; }
mkdir -p "$STAGE/casper"
# Ubuntu 26.04 ISOs sign the on-disc package pool with a one-time key. The
# stock squashfs ships etc/apt/sources.list.d/cdrom.sources with that key
# embedded and subiquity relies on it: without the file it writes an
# unsigned reference to the pool, apt rejects it and the install fails in
# configure_apt. Take the file from the base ISO's squashfs and ship it as a
# squashfs *layer* on top of ours (curtin's fsimage-layered: the name
# NAME.cdrom.squashfs stacks on NAME.squashfs), so the
# rootfs squashfs stays untouched. Subiquity deletes cdrom.sources from the
# installed system afterwards.
xorriso -osirrox on -indev "$BASE" -extract /casper/ubuntu-server-minimal.squashfs "$STAGE/base.squashfs" >/dev/null 2>&1
unsquashfs -q -n -d "$STAGE/base" "$STAGE/base.squashfs" etc/apt/sources.list.d/cdrom.sources >/dev/null 2>&1
CDROM_SRC=$STAGE/base/etc/apt/sources.list.d/cdrom.sources
[ -s "$CDROM_SRC" ] || { echo "base ISO squashfs has no cdrom.sources; cannot build an installable ISO" >&2; exit 1; }
rm -f "$STAGE/base.squashfs"
mkdir -p "$STAGE/layer/etc/apt/sources.list.d"; cp "$CDROM_SRC" "$STAGE/layer/etc/apt/sources.list.d/"
LAYER_SQUASH=$STAGE/casper/$NAME.cdrom.squashfs
mksquashfs "$STAGE/layer" "$LAYER_SQUASH" -comp xz -quiet -no-progress -noappend >/dev/null
cp "$IMG.size" "$STAGE/casper/$NAME.size"
cp "$IMG.manifest" "$STAGE/casper/$NAME.manifest"
xorriso -osirrox on -indev "$BASE" -extract /casper/install-sources.yaml "$STAGE/casper/install-sources.yaml" >/dev/null 2>&1
chmod u+w "$STAGE/casper/install-sources.yaml"
python3 - "$STAGE/casper/install-sources.yaml" "$(cat "$IMG.size")" "$NAME" "$VARIANT" <<'PY'
import sys, yaml
path, size, name, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
d = yaml.safe_load(open(path))
for s in d["sources"]:
    s.pop("default", None)
desc = {"Server": "MaluOS 26.04: Ubuntu 26.04 base with PostgreSQL 18 and the MaluDB memory core preinstalled.",
        "Desktop": "MaluOS 26.04 Desktop: GNOME workstation with PostgreSQL 18 and the MaluDB memory core preinstalled."}[variant]
# variant stays "server" for both: it selects the installer's screens, not what is installed.
d["sources"].insert(0, {
    "default": True, "id": name, "variant": "server", "type": "fsimage-layered",
    "path": name + ".cdrom.squashfs", "size": size, "locale_support": "locale-only",
    "name": {"en": "MaluOS " + variant}, "description": {"en": desc},
})
yaml.safe_dump(d, open(path, "w"), sort_keys=False, allow_unicode=True)
PY

# --- grub ----------------------------------------------------------------
if [ $TEST = 1 ]; then
    # TEST_DEFAULT: 1 = automated entry (default), 0 = guided entry
    sed -e "s/@TIMEOUT@/3/; s/@DEFAULT@/${TEST_DEFAULT:-1}/; s/@EXTRA_ARGS@/console=ttyS0,115200n8 /" "$ROOT/iso/grub.cfg.in"
else
    sed -e 's/@TIMEOUT@/30/; s/@DEFAULT@/0/; s/@EXTRA_ARGS@//' "$ROOT/iso/grub.cfg.in"
fi | sed -e "s/@VARIANT@/$VARIANT/g" > "$STAGE/boot/grub/grub.cfg"

# --- md5sum.txt: drop replaced entry, add new files ------------------------
xorriso -osirrox on -indev "$BASE" -extract /md5sum.txt "$STAGE/md5sum.txt" >/dev/null 2>&1
chmod u+w "$STAGE/md5sum.txt"
grep -vE ' ./(boot/grub/grub.cfg|casper/install-sources.yaml)$' "$STAGE/md5sum.txt" > "$STAGE/md5sum.new"
( cd "$STAGE" && find ./boot/grub/grub.cfg ./maluos ./casper -type f -exec md5sum {} + ) >> "$STAGE/md5sum.new"
echo "$(md5sum < "$IMG.squashfs" | cut -d' ' -f1)  ./casper/$NAME.squashfs" >> "$STAGE/md5sum.new"
mv "$STAGE/md5sum.new" "$STAGE/md5sum.txt"

# --- assemble ------------------------------------------------------------
VOLID="MaluOS 26.04.1 $VARIANT amd64"; [ $TEST = 1 ] && VOLID="MaluOS TEST $VARIANT amd64"
rm -f "$OUT"
xorriso -indev "$BASE" -outdev "$OUT" \
    -boot_image any replay \
    -volid "$VOLID" \
    -overwrite on \
    -map "$STAGE/maluos" /maluos \
    -map "$IMG.squashfs" /casper/$NAME.squashfs \
    -map "$LAYER_SQUASH" /casper/$NAME.cdrom.squashfs \
    -map "$STAGE/casper/$NAME.size" /casper/$NAME.size \
    -map "$STAGE/casper/$NAME.manifest" /casper/$NAME.manifest \
    -map "$STAGE/casper/install-sources.yaml" /casper/install-sources.yaml \
    -map "$STAGE/boot/grub/grub.cfg" /boot/grub/grub.cfg \
    -map "$STAGE/md5sum.txt" /md5sum.txt \
    -commit 2>&1 | grep -vE '^xorriso : UPDATE|^(Drive|Media) ' || true
ls -la "$OUT"
echo "built $OUT (volid: $VOLID)"
