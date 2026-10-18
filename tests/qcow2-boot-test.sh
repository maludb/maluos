#!/bin/bash
# Boot the MaluOS cloud image under QEMU with a NoCloud seed, log in over SSH
# and verify the MaluDB stack. Works without KVM (slower).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-/var/tmp/maluos-qcow2-test}; SSHPORT=${SSHPORT:-2223}; BOOT_TIMEOUT=${BOOT_TIMEOUT:-1500}
IMG=$(readlink -f "${1:-$ROOT/build/image/maluos-server-26.04-amd64.qcow2}")
UEFI=0; [ "${2:-}" = --uefi ] && UEFI=1
ACCEL=$([ -w /dev/kvm ] && echo kvm || echo tcg)
mkdir -p "$WORK"; cd "$WORK"
ss -ltn | grep -q ":$SSHPORT " && { echo "port $SSHPORT busy" >&2; exit 1; }
[ -f testkey ] || ssh-keygen -q -t ed25519 -N '' -f testkey -C maluos-qcow2-test
cat > user-data <<UD
#cloud-config
hostname: maluos-test
users:
  - name: maluos
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat testkey.pub)
UD
printf 'instance-id: maluos-test-%s\nlocal-hostname: maluos-test\n' "$(date +%s)" > meta-data
cloud-localds seed.iso user-data meta-data
qemu-img create -q -f qcow2 -b "$IMG" -F qcow2 disk.qcow2 20G
QEMU=(qemu-system-x86_64 -machine q35,accel=$ACCEL -cpu max -smp 2 -m 2048
      -drive file=disk.qcow2,if=virtio,format=qcow2 -drive file=seed.iso,if=virtio,format=raw,readonly=on
      -netdev user,id=n0,hostfwd=tcp:127.0.0.1:$SSHPORT-:22 -device virtio-net-pci,netdev=n0
      -display none -monitor none -serial file:boot-serial.log)
if [ $UEFI = 1 ]; then cp /usr/share/OVMF/OVMF_VARS_4M.fd vars.fd
    QEMU+=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd -drive if=pflash,format=raw,file=vars.fd); fi
rm -f boot-serial.log; "${QEMU[@]}" >qemu.log 2>&1 & QPID=$!; trap 'kill $QPID 2>/dev/null || true' EXIT
echo "== booting ($ACCEL, $([ $UEFI = 1 ] && echo UEFI || echo BIOS)); serial -> $WORK/boot-serial.log"
ssh_opts=(-p "$SSHPORT" -i testkey -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o LogLevel=ERROR)
deadline=$(( $(date +%s) + BOOT_TIMEOUT ))
until ssh "${ssh_opts[@]}" maluos@127.0.0.1 true 2>/dev/null; do
    kill -0 $QPID 2>/dev/null || { echo "FAIL: qemu exited"; cat qemu.log; exit 1; }
    [ $(date +%s) -lt $deadline ] || { echo "FAIL: no SSH within ${BOOT_TIMEOUT}s"; tail -20 boot-serial.log; exit 1; }
    sleep 10
done
echo "== verifying"
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'bash -s' <<'REMOTE' | tee verify.log
fail=0
. /etc/os-release; echo "  os: $PRETTY_NAME (ID=$ID VARIANT_ID=${VARIANT_ID:-})"; cat /etc/maluos-release | head -1
for p in maluos-server maluos-base maluos-branding postgresql-18 postgresql-18-maludb-core maludb-mc2dbd linux-generic cloud-init; do
  dpkg-query -W -f='${Status}' $p 2>/dev/null | grep -q 'install ok installed' && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }
done
systemctl is-active --quiet postgresql@18-main && echo "  ok   postgresql@18-main active" || { echo "  FAIL postgresql@18-main"; systemctl status postgresql@18-main --no-pager | tail -5; fail=1; }
sudo -n -u postgres psql -Atc "select version()" | cut -c1-40 | sed 's/^/  pg: /'
sudo -n -u postgres psql -Atc "select 1 from pg_available_extensions where name='maludb_core'" | grep -q 1 && echo "  ok   maludb_core extension available" || { echo "  FAIL maludb_core extension"; fail=1; }
df -h / | tail -1 | awk '{print "  root: " $2 " total, " $4 " free (growpart)"}'
sudo -n apt-get update -q >/dev/null 2>&1 && echo "  ok   apt-get update clean" || echo "  warn apt-get update had errors"
cloud-init status | sed 's/^/  /'
# --- first-boot provisioning (Phase 4)
# A oneshot reports Result=success while it is still activating; wait for it to finish
# (the Business OS migrations take many minutes under emulation).
fb_deadline=$(( $(date +%s) + ${FIRSTBOOT_TIMEOUT:-2400} ))
while [ "$(systemctl is-active maluos-firstboot)" = activating ] && [ $(date +%s) -lt $fb_deadline ]; do sleep 10; done
echo "  firstboot: $(systemctl is-active maluos-firstboot) after wait, result=$(systemctl show -p Result --value maluos-firstboot)"
if [ -f /var/lib/maluos/firstboot/done ] && [ "$(systemctl show -p Result --value maluos-firstboot)" = success ]; then echo "  ok   maluos-firstboot finished successfully"; else echo "  FAIL maluos-firstboot did not finish ($(systemctl is-active maluos-firstboot))"; sudo -n journalctl -u maluos-firstboot --no-pager | grep -v 'migration ' | tail -20; fail=1; fi
sudo -n test -f /var/lib/maluos/firstboot/done && echo "  ok   firstboot done file" || { echo "  FAIL no done file"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select extversion from pg_extension where extname='maludb_core'" | grep -qE '^[0-9]' && echo "  ok   maludb database with maludb_core" || { echo "  FAIL maludb database"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select 1 from pg_namespace where nspname='maluos'" | grep -q 1 && echo "  ok   tenant schema maluos" || { echo "  FAIL tenant schema"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "set role maluos; set search_path to maluos, maludb_core, public; select principal_ref from maludb_principal" | grep -q 'human:admin' && echo "  ok   admin principal" || { echo "  FAIL admin principal"; fail=1; }
systemctl is-active --quiet maludb-mc2dbd && echo "  ok   maludb-mc2dbd active" || { echo "  FAIL maludb-mc2dbd: $(systemctl is-active maludb-mc2dbd)"; sudo -n journalctl -u maludb-mc2dbd --no-pager | tail -8; fail=1; }
curl -fsS --max-time 5 http://127.0.0.1:5329/healthz >/dev/null && echo "  ok   listener /healthz" || { echo "  FAIL listener /healthz"; fail=1; }
tok=$(sudo -n maluctl token 2>/dev/null); [ ${#tok} -ge 32 ] && echo "  ok   listener token present" || { echo "  FAIL token"; fail=1; }
curl -fsS --max-time 5 -H "Authorization: Bearer $tok" -X POST http://127.0.0.1:5329/ -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -q '"tools"' && echo "  ok   MCP tools/list with token" || echo "  warn MCP tools/list did not return tools"
psql -Atd maludb -c "select current_user" 2>/dev/null | grep -q maluos && echo "  ok   operator psql peer login" || echo "  warn operator psql login failed"
# --- MaluDB API component
for p in maluos-api maludb-api; do dpkg-query -W -f='${Status}' $p 2>/dev/null | grep -q 'install ok installed' && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }; done
systemctl is-active --quiet maludb-api && echo "  ok   maludb-api active" || { echo "  FAIL maludb-api: $(systemctl is-active maludb-api)"; sudo -n journalctl -u maludb-api --no-pager | tail -8; fail=1; }
curl -fsS --max-time 5 http://127.0.0.1:8000/health | grep -q ok && echo "  ok   API /health" || { echo "  FAIL API /health"; fail=1; }
atok=$(sudo -n maluctl token api 2>/dev/null); [ "${atok#malu_}" != "$atok" ] && echo "  ok   API token minted" || { echo "  FAIL API token"; fail=1; }
curl -fsS --max-time 10 -H "Authorization: Bearer $atok" http://127.0.0.1:8000/v1/subjects >/dev/null && echo "  ok   API /v1/subjects with token (PostgreSQL 18 query path)" || { echo "  FAIL API /v1/subjects"; sudo -n journalctl -u maludb-api --no-pager | tail -5; fail=1; }
systemctl is-active --quiet maludb-embedding-worker.timer && echo "  ok   embedding sweep timer" || echo "  warn embedding sweep timer not active"
# --- Business OS kernel component
for p in maluos-business-os maludb-os-core; do dpkg-query -W -f='${Status}' $p 2>/dev/null | grep -q 'install ok installed' && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }; done
bosdom=$(sudo -n python3 -c "import json;print(json.load(open('/var/lib/maluos/firstboot/done'))['components']['maludb-os-core'].get('domain',''))" 2>/dev/null)
echo "  bos domain: ${bosdom:-?}"
for u in apache2 maludb-os-web maludb-os-records-mcp maludb-os-activity-mcp maludb-os-actions-mcp maludb-os-memory-mcp maludb-os-agent-runner maludb-os-activity-ingest.timer; do
  systemctl is-active --quiet $u && echo "  ok   $u active" || { echo "  FAIL $u: $(systemctl is-active $u)"; sudo -n journalctl -u $u --no-pager | tail -5; fail=1; }
done
curl -fsS --max-time 10 http://127.0.0.1:8080/api/v1/health | grep -q '"ok"' && echo "  ok   kernel PHP API /api/v1/health" || { echo "  FAIL kernel PHP API"; fail=1; }
# next start takes minutes under emulation; give the front end time to come up behind Apache
for i in $(seq 1 40); do code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 -H "Host: app.$bosdom" http://127.0.0.1/login); [ "$code" = 200 ] && break; sleep 10; done
[ "$code" = 200 ] && echo "  ok   kernel web /login via Apache (200)" || { echo "  FAIL kernel web /login: HTTP $code"; sudo -n journalctl -u maludb-os-web --no-pager | tail -8; fail=1; }
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H "Host: $bosdom" http://127.0.0.1/); [ "$code" = 200 ] && echo "  ok   landing page (200)" || echo "  warn landing page: HTTP $code"
for i in $(seq 1 12); do curl -fsS --max-time 10 http://127.0.0.1:8815/health 2>/dev/null | grep -q '"ok"' && break; sleep 10; done
curl -fsS --max-time 10 http://127.0.0.1:8815/health 2>/dev/null | grep -q '"ok"' && echo "  ok   agent runner /health" || { echo "  warn agent runner /health not ok"; sudo -n journalctl -u maludb-os-agent-runner --no-pager | tail -6; }
sudo -n -u postgres psql -Atd maludb_os -c "select count(*) from members where business_role='super_admin'" | grep -qE '^[1-9]' && echo "  ok   super-admin exists in maludb_os" || { echo "  FAIL super-admin"; fail=1; }
sudo -n -u postgres psql -Atd maludb_os -c "select count(*) from pg_tables where schemaname='public'" | sed 's/^/  kernel tables: /'
sudo -n test -s /var/lib/maluos/secrets/business-os/admin-password && echo "  ok   admin password stored" || echo "  warn no stored admin password"
sudo -n maluctl status | sed 's/^/  maluctl: /'
exit $fail
REMOTE
rc=${PIPESTATUS[0]}
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'sudo -n poweroff' 2>/dev/null || true; sleep 3
[ "$rc" = 0 ] && echo "PASS: cloud image boots and runs the MaluDB stack" || { echo "FAIL (see $WORK)"; exit 1; }
