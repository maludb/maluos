#!/bin/bash
# Phase 2: remaster the Ubuntu Server 26.04.1 ISO into a MaluOS Server ISO.
#
# Adds to the stock image:
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
for v in auto interactive; do
    d="$STAGE/maluos/nocloud-$v"; mkdir -p "$d"
    python3 - "$ROOT/autoinstall/server-$v.yaml" "$ROOT/autoinstall/late-commands.yaml" "$keys" > "$d/user-data" <<'PY'
import sys
main, late, keys = open(sys.argv[1]).read(), open(sys.argv[2]).read(), sys.argv[3]
main = main.replace("@AUTHORIZED_KEYS@", keys)
late = "\n".join(("  " + l if l.strip() and not l.startswith("#") else "") for l in late.splitlines())
print(main.rstrip() + "\n" + late + "\n")
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

# --- grub ----------------------------------------------------------------
if [ $TEST = 1 ]; then
    sed -e 's/@TIMEOUT@/3/; s/@DEFAULT@/1/; s/@EXTRA_ARGS@/console=ttyS0,115200n8 /' "$ROOT/iso/grub.cfg.in"
else
    sed -e 's/@TIMEOUT@/30/; s/@DEFAULT@/0/; s/@EXTRA_ARGS@//' "$ROOT/iso/grub.cfg.in"
fi > "$STAGE/boot/grub/grub.cfg"

# --- md5sum.txt: drop replaced entry, add new files ------------------------
xorriso -osirrox on -indev "$BASE" -extract /md5sum.txt "$STAGE/md5sum.txt" >/dev/null 2>&1
chmod u+w "$STAGE/md5sum.txt"
grep -v ' ./boot/grub/grub.cfg$' "$STAGE/md5sum.txt" > "$STAGE/md5sum.new"
( cd "$STAGE" && find ./boot/grub/grub.cfg ./maluos -type f -exec md5sum {} + ) >> "$STAGE/md5sum.new"
mv "$STAGE/md5sum.new" "$STAGE/md5sum.txt"

# --- assemble ------------------------------------------------------------
VOLID="MaluOS 26.04.1 Server amd64"; [ $TEST = 1 ] && VOLID="MaluOS TEST Server amd64"
rm -f "$OUT"
xorriso -indev "$BASE" -outdev "$OUT" \
    -boot_image any replay \
    -volid "$VOLID" \
    -overwrite on \
    -map "$STAGE/maluos" /maluos \
    -map "$STAGE/boot/grub/grub.cfg" /boot/grub/grub.cfg \
    -map "$STAGE/md5sum.txt" /md5sum.txt \
    -commit 2>&1 | grep -vE '^xorriso : UPDATE|^(Drive|Media) ' || true
ls -la "$OUT"
echo "built $OUT (volid: $VOLID)"
