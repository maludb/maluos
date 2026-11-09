#!/bin/bash
# vm-guest.sh: on a KVM/QEMU guest (Proxmox and most hosting VMs) install and start the QEMU guest agent so
# the hypervisor's UI shows the guest's address and can shut it down cleanly. On physical hardware or
# another hypervisor it does nothing and says so.
#
#   vm-guest.sh            detect; install on kvm/qemu
#   vm-guest.sh --check    detect only
. "$(dirname "$(readlink -f "$0")")/lib.sh"
virt=$(systemd-detect-virt 2>/dev/null || echo none)
say "virtualisation: $virt"
case "$virt" in
  kvm|qemu) ;;
  none) say "physical hardware: no guest integration to install"; exit 0 ;;
  *) say "hypervisor '$virt': this script knows only the QEMU guest agent; nothing installed"; exit 0 ;;
esac
if [ "${1:-}" = "--check" ]; then say "qemu-guest-agent: $(systemctl is-active qemu-guest-agent 2>/dev/null || echo not-installed)"; exit 0; fi
need_root "$@"
if systemctl is-active --quiet qemu-guest-agent; then say "qemu-guest-agent already active"; exit 0; fi
DEBIAN_FRONTEND=noninteractive apt-get install -y -q qemu-guest-agent
systemctl enable --now qemu-guest-agent
sleep 1; say "qemu-guest-agent: $(systemctl is-active qemu-guest-agent)"
