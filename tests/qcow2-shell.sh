#!/bin/bash
# Boot the cloud image under QEMU with the test seed, run a command over SSH
# as the maluos user, print its output, power off. For ad-hoc diagnosis.
# usage: tests/qcow2-shell.sh [image] -- <command...>
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-/var/tmp/maluos-qcow2-shell}; SSHPORT=${SSHPORT:-2225}; BOOT_TIMEOUT=${BOOT_TIMEOUT:-1500}
IMG=$ROOT/build/image/maluos-server-26.04-amd64.qcow2
[ "${1:-}" != "--" ] && { IMG=$(readlink -f "$1"); shift; }
[ "${1:-}" = "--" ] && shift
CMD=${*:-'maluctl status'}
ACCEL=$([ -w /dev/kvm ] && echo kvm || echo tcg)
mkdir -p "$WORK"; cd "$WORK"
[ -f testkey ] || ssh-keygen -q -t ed25519 -N '' -f testkey -C maluos-qcow2-shell
printf '#cloud-config\nhostname: maluos-shell\nusers:\n  - name: maluos\n    sudo: ALL=(ALL) NOPASSWD:ALL\n    shell: /bin/bash\n    ssh_authorized_keys:\n      - %s\n' "$(cat testkey.pub)" > user-data
printf 'instance-id: maluos-shell-%s\nlocal-hostname: maluos-shell\n' "$(date +%s)" > meta-data
cloud-localds seed.iso user-data meta-data
qemu-img create -q -f qcow2 -b "$IMG" -F qcow2 disk.qcow2 20G
qemu-system-x86_64 -machine q35,accel=$ACCEL -cpu max -smp 2 -m 2048 \
  -drive file=disk.qcow2,if=virtio,format=qcow2 -drive file=seed.iso,if=virtio,format=raw,readonly=on \
  -netdev user,id=n0,hostfwd=tcp:127.0.0.1:$SSHPORT-:22 -device virtio-net-pci,netdev=n0 \
  -display none -monitor none -serial file:boot-serial.log >qemu.log 2>&1 & QPID=$!; trap 'kill $QPID 2>/dev/null || true' EXIT
ssh_opts=(-p "$SSHPORT" -i testkey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o LogLevel=ERROR)
deadline=$(( $(date +%s) + BOOT_TIMEOUT ))
until ssh "${ssh_opts[@]}" maluos@127.0.0.1 true 2>/dev/null; do
    kill -0 $QPID 2>/dev/null || { echo "qemu exited"; exit 1; }
    [ $(date +%s) -lt $deadline ] || { echo "no SSH within ${BOOT_TIMEOUT}s"; exit 1; }
    sleep 10
done
# first boot may still be provisioning: wait for the done file
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'for i in $(seq 1 60); do [ -f /var/lib/maluos/firstboot/done ] && break; sleep 5; done' || true
echo "=== $CMD"
ssh "${ssh_opts[@]}" maluos@127.0.0.1 "$CMD" || true
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'sudo -n poweroff' 2>/dev/null || true; sleep 3
