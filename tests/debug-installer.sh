#!/bin/bash
# Boot the --test ISO under QEMU with the serial console on a unix socket,
# wait for the installer to fail ("Press enter to start a shell"), then run
# diagnostic commands in that shell and capture everything to a log.
# Usage: tests/debug-installer.sh [iso]   (default: /var/tmp/maluos-iso-test/maluos-test.iso)
set -euo pipefail
WORK=${WORK:-/var/tmp/maluos-iso-test}
ISO=${1:-$WORK/maluos-test.iso}
ACCEL=$([ -w /dev/kvm ] && echo kvm || echo tcg)
cd "$WORK"; rm -f debug-serial.log debug.sock; qemu-img create -q -f qcow2 debug-disk.qcow2 24G
qemu-system-x86_64 -machine q35,accel=$ACCEL -cpu max -smp 4 -m 4096 \
  -drive file=debug-disk.qcow2,if=virtio,format=qcow2 -cdrom "$ISO" -boot d -no-reboot \
  -netdev user,id=n0 -device virtio-net-pci,netdev=n0 -display none -monitor none \
  -chardev socket,id=s0,path=debug.sock,server=on,wait=off,logfile=debug-serial.log -serial chardev:s0 &
QPID=$!; trap 'kill $QPID 2>/dev/null || true' EXIT
python3 - "$WORK/debug.sock" "$WORK/debug-serial.log" <<'PY'
import socket, sys, time, re
sock, log = sys.argv[1], sys.argv[2]
s = None
for _ in range(60):
    try: s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(sock); break
    except OSError: time.sleep(1)
s.settimeout(5)
buf = b""
def wait_for(pat, limit):
    global buf
    end = time.time() + limit
    while time.time() < end:
        try: buf += s.recv(65536)
        except socket.timeout: pass
        if re.search(pat, buf[-200000:]): return True
    return False
def run(cmd, settle=8):
    s.sendall((cmd + "\n").encode()); time.sleep(settle)
    try:
        while True: s.recv(65536)
    except socket.timeout: pass
ok = wait_for(rb"Press enter to start a shell|login:", 6000)
print("prompt reached:", ok, flush=True)
if not ok: sys.exit(2)
s.sendall(b"\n"); time.sleep(5)
for cmd in [
    "echo '=== DIAG START'",
    "ls /var/crash/",
    "cat /etc/netplan/*.yaml",
    "ip -br addr; ip route",
    "netplan apply; echo NETPLAN_RC=$?",
    "netplan --debug apply 2>&1 | tail -40",
    "journalctl -u systemd-networkd -u netplan-ovs-cleanup --no-pager | tail -30",
    "grep -m1 -A60 -i 'Traceback' /var/crash/*.crash | head -80",
    "tail -40 /var/log/installer/subiquity-server-debug.log",
    "echo '=== DIAG END'",
]:
    run(cmd, 12)
s.sendall(b"poweroff -f\n")
PY
sleep 5
echo "diagnostics in $WORK/debug-serial.log"
