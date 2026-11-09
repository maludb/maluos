#!/bin/bash
# provision.sh: re-run first boot for the edited configuration and show what it left.
#
#   provision.sh            sudo maluctl provision --force, output kept in /var/log/maluos-office-setup/, then maluctl status
#   provision.sh --status   maluctl status only
#
# Refuses while maluos-firstboot is still running (a first boot in progress must finish first). Every
# component is idempotent: databases, secrets and hired agents are kept; the environment files, the
# Apache vhosts and /etc/hosts are re-rendered for the new domain; a super-admin with the new email is
# created if no member has it yet. On failure prints the kernel component's lines from the journal.
# Takes minutes; with apps.install set, longer (each application is cloned and built).
. "$(dirname "$(readlink -f "$0")")/lib.sh"
need_root "$@"
require_office
if [ "${1:-}" = "--status" ]; then exec maluctl status; fi
sub=$(systemctl show -p SubState --value maluos-firstboot 2>/dev/null || true)
[ "$sub" = "running" ] && die "maluos-firstboot is still running; wait for it (systemctl show -p SubState --value maluos-firstboot says exited when done)"
mkdir -p "$LOG_DIR"; chmod 750 "$LOG_DIR"
log="$LOG_DIR/provision-$(date -u +%Y%m%dT%H%M%SZ).log"
say "maluctl provision --force  (log: $log)"
set +e
maluctl provision --force 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
set -e
chmod 640 "$log"
if [ "$rc" -ne 0 ]; then
  say ""; say "provision exited $rc. The kernel component's recent journal lines:"
  journalctl -u maluos-firstboot --no-pager 2>/dev/null | grep -i "maludb-os-core" | tail -15 || true
  die "provisioning failed; fix the named step and run provision.sh again (every step is idempotent)" "$rc"
fi
say ""; maluctl status
