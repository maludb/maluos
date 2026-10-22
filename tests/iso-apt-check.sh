#!/bin/bash
# Replicates subiquity's configure_apt step against the ISO's install source
# without booting anything: mount the ISO, overlay its MaluOS squashfs, bind
# the ISO at /cdrom, then run apt-get update inside like the installer does.
# This is the step that failed on the first external install (unsigned pool).
# usage: sudo tests/iso-apt-check.sh [iso]      (server or desktop ISO)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ISO=$(readlink -f "${1:-$ROOT/build/maluos-26.04.1-server-amd64.iso}")
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
W=$(mktemp -d /var/tmp/maluos-apt-check.XXXXXX)
cleanup() { for m in "$W"/m/dev "$W"/m/proc "$W"/m/cdrom "$W"/m "$W"/sq2 "$W"/sq "$W"/cdrom; do umount -l "$m" 2>/dev/null || true; done; rm -rf "$W"; }
trap cleanup EXIT
mkdir -p "$W"/{cdrom,sq,sq2,upper,work,m}
mount -o loop,ro "$ISO" "$W/cdrom"
SQ=$(ls "$W"/cdrom/casper/maluos-*.squashfs | grep -v '\.cdrom\.squashfs$' | head -1)
[ -n "$SQ" ] || { echo "no maluos-*.squashfs on the ISO" >&2; exit 1; }
echo "install source: $(basename "$SQ")"
mount -o loop,ro "$SQ" "$W/sq"
lower="$W/sq"
if [ -f "${SQ%.squashfs}.cdrom.squashfs" ]; then
    mount -o loop,ro "${SQ%.squashfs}.cdrom.squashfs" "$W/sq2"; lower="$W/sq2:$W/sq"
fi
mount -t overlay overlay -o lowerdir="$lower",upperdir="$W/upper",workdir="$W/work" "$W/m"
mkdir -p "$W/m/cdrom"; mount --bind "$W/cdrom" "$W/m/cdrom"
mount --bind /dev "$W/m/dev"; mount --bind /proc "$W/m/proc"
cp --remove-destination /etc/resolv.conf "$W/m/etc/resolv.conf"
if [ -f "$W/m/etc/apt/sources.list.d/cdrom.sources" ]; then
    echo "cdrom.sources present (new-style ISO): pool signed by the embedded one-time key"
else
    echo "no cdrom.sources: installer would write an unsigned file:///cdrom source"
    [ -f "$W/m/etc/apt/sources.list" ] && mv "$W/m/etc/apt/sources.list" "$W/m/etc/apt/sources.list.d/original.list"
    printf 'deb [check-date=no] file:///cdrom resolute main restricted\n' > "$W/m/etc/apt/sources.list"
fi
# Offline, as curtin sees the target: the installer's apt config leaves only the ISO
# source active until the install is done, so nothing may be fetched from the network here.
mkdir -p "$W/m/etc/apt/off"
for f in "$W/m"/etc/apt/sources.list "$W/m"/etc/apt/sources.list.d/*; do
    case "$(basename "$f")" in cdrom.sources|original.list) ;; *) [ -e "$f" ] && mv "$f" "$W/m/etc/apt/off/" ;; esac
done
rm -rf "$W/m/var/lib/apt/lists"
if chroot "$W/m" apt-get update 2>&1 | grep -vE '^(Get|Hit|Ign):' | tail -8; test "${PIPESTATUS[0]}" = 0; then
    if chroot "$W/m" apt-cache policy | grep -q 'file:/cdrom'; then
        echo "PASS: apt in the install source accepts the ISO pool ($(chroot "$W/m" apt-cache policy | grep -c 'file:/cdrom') cdrom index entries)"
    else
        echo "FAIL: ISO pool not indexed"; exit 1
    fi
    # curtin installs what the chosen storage layout and boot mode need into the target
    # (install_missing_packages); with the network sources off that means: already in the
    # image, or in the ISO pool. The first external desktop install died on lvm2.
    NEED="lvm2 cryptsetup mdadm btrfs-progs xfsprogs e2fsprogs efibootmgr grub-efi-amd64-signed shim-signed grub-pc"
    if out=$(chroot "$W/m" apt-get install -s $NEED 2>&1); then
        echo "PASS: curtin's storage and boot packages are in the image or the ISO pool ($(echo "$out" | grep -c '^Inst ') to install from the pool)"
    else
        echo "FAIL: a package curtin may need is not installable in the install source:"; echo "$out" | grep -E '^E:|no installation candidate' | head -5; exit 1
    fi
else
    echo "FAIL: apt-get update failed in the install source"; exit 1
fi
# The image also carries network sources (apt.maluos.com, packages.mozilla.org since
# slice 5). Should the installer leave them active on a machine without a route out,
# apt-get update must still succeed: unreachable hosts are warnings, not errors.
for f in "$W/m"/etc/apt/off/*; do [ -e "$f" ] && mv "$f" "$W/m/etc/apt/sources.list.d/"; done
if chroot "$W/m" apt-get update -o Acquire::http::Proxy=http://127.0.0.1:9 -o Acquire::https::Proxy=http://127.0.0.1:9 >/dev/null 2>&1; then
    echo "PASS: apt-get update still succeeds with the network sources enabled but unreachable ($(ls "$W/m"/etc/apt/sources.list.d/ | tr '\n' ' '))"
else
    echo "FAIL: an unreachable network source makes apt-get update fail (the installer would abort offline)"; exit 1
fi
