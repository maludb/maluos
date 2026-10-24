#!/bin/bash
# Phase 11 slice 1: the live medium boots (BIOS or UEFI) into the MaluOS live
# environment; the installer's console unit, with maluos.test=1, reports the
# medium's facts to the serial console and powers off. The serial log is the
# test: grub's menu, casper mounting the medium, no "Ubuntu" after the firmware's
# own lines, the check-media lines, the power-off.
#
# usage: tests/live-iso-boot-test.sh [--uefi] [-p server|desktop]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-/var/tmp/maluos-live-test}
UEFI=0; PROFILE=server
while [ $# -gt 0 ]; do case "$1" in --uefi) UEFI=1; shift ;; -p) PROFILE=$2; shift 2 ;; *) echo "bad arg $1" >&2; exit 2 ;; esac; done
TIMEOUT=${BOOT_TIMEOUT:-900}
ACCEL=$([ -w /dev/kvm ] && echo kvm || echo tcg)
mkdir -p "$WORK"; cd "$WORK"
LOG=$WORK/live-$PROFILE-$([ $UEFI = 1 ] && echo uefi || echo bios).log
rm -f "$LOG"
echo "== building the --test medium ($PROFILE)"
"$ROOT/iso/build-live-iso.sh" -p "$PROFILE" --test -o "$WORK/maluos-live-test-$PROFILE.iso" > build-live-iso.log 2>&1 || { tail -20 build-live-iso.log; exit 1; }
QEMU=(qemu-system-x86_64 -machine q35,accel=$ACCEL -cpu max -smp 2 -m 3072
      -netdev user,id=n0 -device virtio-net-pci,netdev=n0
      -display none -monitor none -no-reboot)
if [ $UEFI = 1 ]; then
    cp /usr/share/OVMF/OVMF_VARS_4M.fd "$WORK/vars.fd"
    QEMU+=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd -drive if=pflash,format=raw,file="$WORK/vars.fd")
fi
echo "== booting ($ACCEL, $([ $UEFI = 1 ] && echo UEFI || echo BIOS)); serial -> $LOG"
start=$(date +%s)
timeout "$TIMEOUT" "${QEMU[@]}" -cdrom "$WORK/maluos-live-test-$PROFILE.iso" -boot d -serial "file:$LOG" > qemu.log 2>&1 && rc=0 || rc=$?
echo "   VM exited rc=$rc after $(( $(date +%s) - start ))s"
fail=0
chk() { if grep -qE "$2" "$LOG"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }
V=$([ "$PROFILE" = server ] && echo Server || echo Desktop)
chk "grub menu: Start the MaluOS $V installer" "Start the MaluOS $V installer"
chk "the kernel booted (MaluOS 26.04 banner or casper)" "MaluOS 26.04|Begin: Running /scripts/casper|casper"
chk "casper mounted the medium" "medium: /cdrom"
if grep -vE 'Linux version|\(Ubuntu|ubuntu[0-9]|BdsDxe|EFI stub|SecureBoot|Ubuntu-Server|Command line|BOOT_IMAGE|shim|ubuntu-release-upgrader|update-notifier|ubuntu-advantage|archive.ubuntu.com|security.ubuntu.com|EDK II' "$LOG" | grep -qi 'ubuntu'; then
    echo "  FAIL 'Ubuntu' on the console: $(grep -vE 'Linux version|\(Ubuntu|ubuntu[0-9]|BdsDxe|EFI stub|SecureBoot|Command line|BOOT_IMAGE|shim|ubuntu-release-upgrader|update-notifier|ubuntu-advantage|archive.ubuntu.com|security.ubuntu.com|EDK II' "$LOG" | grep -i ubuntu | head -2)"; fail=1
else echo "  ok   no Ubuntu on the console"; fi
chk "live image listed" "live: maluos-live.squashfs [0-9]+ MB"
chk "target image checksum ok" "target: maluos-$PROFILE.squashfs [0-9]+ MB sha256 ok"
chk "kernel reported" "kernel: [0-9]+\.[0-9]+\.[0-9]+-[0-9]+-generic"
chk "initrd carries casper and the spinner theme" "initrd: casper ok, plymouth theme spinner ok"
chk "firmware reported ($([ $UEFI = 1 ] && echo UEFI || echo BIOS))" "firmware: $([ $UEFI = 1 ] && echo 'UEFI, Secure Boot' || echo BIOS)"
chk "network reported with an address" "network: [a-z0-9]+ 10\.0\.2\.[0-9]+"
chk "check-media ok and power-off" "check-media: ok; powering off"
[ $rc = 0 ] && echo "  ok   the VM powered off on its own" || { echo "  FAIL the VM did not power off (rc=$rc)"; fail=1; }
[ $fail = 0 ] && echo "PASS: the $PROFILE live medium boots on $([ $UEFI = 1 ] && echo UEFI || echo BIOS) to the MaluOS live environment" || { echo "FAIL (see $LOG)"; tail -30 "$LOG"; exit 1; }
