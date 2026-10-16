#!/bin/bash
# Phase 2 acceptance test: the MaluOS ISO boots, installs unattended on an
# empty disk, reboots, and the installed system has the MaluDB stack running.
#
# Runs under QEMU with TCG (software emulation) so it works on hosts without
# KVM, which makes the install slow (tens of minutes). Uses the --test ISO
# variant (serial console, automated entry default) with a throwaway SSH key.
#
# usage: tests/iso-boot-test.sh            (BIOS boot)
#        tests/iso-boot-test.sh --uefi     (OVMF)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-/var/tmp/maluos-iso-test}
UEFI=0; [ "${1:-}" = --uefi ] && UEFI=1
INSTALL_TIMEOUT=${INSTALL_TIMEOUT:-7200}
BOOT_TIMEOUT=${BOOT_TIMEOUT:-900}
SSHPORT=${SSHPORT:-2222}
ACCEL=$([ -w /dev/kvm ] && echo kvm || echo tcg)

mkdir -p "$WORK"; cd "$WORK"
if ss -ltn 2>/dev/null | grep -q ":$SSHPORT "; then
    echo "port $SSHPORT is in use (a previous test VM still running? pkill -x qemu-system-x86)" >&2; exit 1
fi
rm -f install-serial.log boot-serial.log disk.qcow2
[ -f testkey ] || ssh-keygen -q -t ed25519 -N '' -f testkey -C maluos-iso-test
OUT_ISO="$WORK/maluos-test.iso" "$ROOT/iso/build-iso.sh" --test --ssh-key testkey.pub >build-iso.log 2>&1 \
    || { tail -20 build-iso.log; exit 1; }
qemu-img create -q -f qcow2 disk.qcow2 24G

QEMU=(qemu-system-x86_64 -machine q35,accel=$ACCEL -cpu max -smp 4 -m 4096
      -drive file=disk.qcow2,if=virtio,format=qcow2
      -netdev user,id=n0,hostfwd=tcp:127.0.0.1:$SSHPORT-:22 -device virtio-net-pci,netdev=n0
      -display none -monitor none)
if [ $UEFI = 1 ]; then
    cp /usr/share/OVMF/OVMF_VARS_4M.fd vars.fd
    QEMU+=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd
           -drive if=pflash,format=raw,file=vars.fd)
fi

echo "== install phase ($ACCEL, $([ $UEFI = 1 ] && echo UEFI || echo BIOS)); serial -> $WORK/install-serial.log"
start=$(date +%s)
timeout "$INSTALL_TIMEOUT" "${QEMU[@]}" -cdrom maluos-test.iso -boot d -no-reboot \
    -serial file:install-serial.log >qemu-install.log 2>&1 && rc=0 || rc=$?
echo "   installer VM exited rc=$rc after $(( $(date +%s) - start ))s"
grep -q 'MaluOS 26.04' install-serial.log 2>/dev/null || true
if grep -qiE 'autoinstall.*(error|failed)|Traceback|curtin command.*failed' install-serial.log; then
    echo "FAIL: installer reported errors (see $WORK/install-serial.log)"; exit 1
fi
[ $rc = 124 ] && { echo "FAIL: install timed out"; exit 1; }

echo "== boot phase: booting installed disk"
"${QEMU[@]}" -boot c -serial file:boot-serial.log >qemu-boot.log 2>&1 &
QPID=$!
trap 'kill $QPID 2>/dev/null || true' EXIT
ssh_opts=(-p "$SSHPORT" -i testkey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o LogLevel=ERROR)
deadline=$(( $(date +%s) + BOOT_TIMEOUT ))
until ssh "${ssh_opts[@]}" maluos@127.0.0.1 true 2>/dev/null; do
    [ $(date +%s) -lt $deadline ] || { echo "FAIL: no SSH within ${BOOT_TIMEOUT}s"; tail -20 boot-serial.log; exit 1; }
    sleep 10
done

echo "== verifying installed system"
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'bash -s' <<'REMOTE' | tee verify.log
fail=0
for p in maluos-server maluos-base maluos-archive maluos-keyring postgresql-18 postgresql-18-maludb-core maludb-mc2dbd; do
  dpkg-query -W -f='${Status}' $p 2>/dev/null | grep -q 'install ok installed' && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }
done
systemctl is-active --quiet postgresql@18-main && echo "  ok   postgresql@18-main active" || { echo "  FAIL postgresql@18-main"; fail=1; }
sudo -n -u postgres psql -Atc "select 1" >/dev/null 2>&1 && echo "  ok   psql works" || echo "  warn psql not reachable (sudo may need a tty)"
grep -q 'Enabled: no' /etc/apt/sources.list.d/maluos.sources && echo "  ok   network MaluOS source disabled" || { echo "  FAIL maluos.sources"; fail=1; }
sudo -n apt-get update -q >/dev/null 2>&1 && echo "  ok   apt-get update clean" || echo "  warn apt-get update had errors"
cat /etc/maluos-release
exit $fail
REMOTE
rc=${PIPESTATUS[0]}
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'sudo -n poweroff' 2>/dev/null || true
sleep 5
[ "$rc" = 0 ] && echo "PASS: MaluOS ISO installs and boots" || { echo "FAIL (see $WORK)"; exit 1; }
