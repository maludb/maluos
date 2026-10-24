#!/bin/bash
# Boot a MaluOS cloud image (server or desktop) under QEMU with a NoCloud
# seed, log in over SSH and verify the MaluDB stack; the checks for the API,
# the Business OS kernel and the desktop run when the image carries them.
# Works without KVM (slower).
#   usage: tests/qcow2-boot-test.sh [image.qcow2] [--uefi]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-/var/tmp/maluos-qcow2-test}; SSHPORT=${SSHPORT:-2223}; BOOT_TIMEOUT=${BOOT_TIMEOUT:-1500}
IMG=$(readlink -f "${1:-$ROOT/build/image/maluos-server-26.04-amd64.qcow2}")
UEFI=0; [ "${2:-}" = --uefi ] && UEFI=1
# The desktop image runs a GNOME greeter under software rendering: more memory and cores.
case "$(basename "$IMG")" in *desktop*) MEM=${MEM:-3072}; SMP=${SMP:-4} ;; *) MEM=${MEM:-2048}; SMP=${SMP:-2} ;; esac
ACCEL=$([ -w /dev/kvm ] && echo kvm || echo tcg)
mkdir -p "$WORK"; cd "$WORK"
ss -ltn | grep -q ":$SSHPORT " && { echo "port $SSHPORT busy" >&2; exit 1; }
[ -f testkey ] || ssh-keygen -q -t ed25519 -N '' -f testkey -C maluos-qcow2-test
# The desktop image logs the test user straight into the MaluOS session, so the
# shell extension and the session service run as a real user (Phase 12 slice 2).
# The session must not idle-lock during the long server checks: GNOME disables
# extensions on the lock screen. A dconf system database set before gdm starts.
DESKTOP_SEED=""
case "$(basename "$IMG")" in *desktop*) DESKTOP_SEED="write_files:
  - path: /etc/gdm3/custom.conf
    content: |
      [daemon]
      AutomaticLoginEnable=true
      AutomaticLogin=maluos
bootcmd:
  - [sh, -c, \"mkdir -p /etc/dconf/profile /etc/dconf/db/local.d; printf 'user-db:user\\nsystem-db:local\\n' > /etc/dconf/profile/user; printf '[org/gnome/desktop/session]\\nidle-delay=uint32 0\\n[org/gnome/desktop/screensaver]\\nlock-enabled=false\\n' > /etc/dconf/db/local.d/00-boot-test; dconf update\"]
";; esac
cat > user-data <<UD
#cloud-config
hostname: maluos-test
users:
  - name: maluos
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat testkey.pub)
$DESKTOP_SEED
UD
printf 'instance-id: maluos-test-%s\nlocal-hostname: maluos-test\n' "$(date +%s)" > meta-data
cloud-localds seed.iso user-data meta-data
qemu-img create -q -f qcow2 -b "$IMG" -F qcow2 disk.qcow2 20G
QEMU=(qemu-system-x86_64 -machine q35,accel=$ACCEL -cpu max -smp $SMP -m $MEM
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
installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'; }
. /etc/os-release; echo "  os: $PRETTY_NAME (ID=$ID ID_LIKE=${ID_LIKE:-})"; cat /etc/maluos-release | head -1
[ "$ID" = maluos ] && [ "$NAME" = MaluOS ] && echo "$ID_LIKE" | grep -q ubuntu && echo "  ok   os-release identifies MaluOS (ID_LIKE ubuntu)" || { echo "  FAIL os-release"; fail=1; }
lsb_release -a 2>/dev/null | grep -q 'Distributor ID:.*MaluOS' && ! lsb_release -a 2>/dev/null | grep -qi ubuntu && echo "  ok   lsb_release says MaluOS" || { echo "  FAIL lsb_release"; lsb_release -a; fail=1; }
! grep -qi ubuntu /etc/issue /etc/issue.net /etc/legal /etc/lsb-release && echo "  ok   issue, legal and lsb-release carry no Ubuntu branding" || { echo "  FAIL branding files"; fail=1; }
sudo -n run-parts /etc/update-motd.d 2>/dev/null > /tmp/motd.txt; ! grep -qi 'ubuntu\|esm\|pro ' /tmp/motd.txt && grep -q MaluOS /tmp/motd.txt && echo "  ok   motd carries no Ubuntu, Pro or ESM text" || { echo "  FAIL motd"; cat /tmp/motd.txt; fail=1; }
sudo -n grep -m1 '^menuentry' /boot/grub/grub.cfg | grep -q MaluOS && echo "  ok   GRUB menu names MaluOS" || { echo "  FAIL grub distributor"; sudo -n grep -m1 '^menuentry' /boot/grub/grub.cfg; fail=1; }
sudo -n apt-get -s upgrade 2>&1 | grep -qi 'expanded security\|ubuntu pro' && { echo "  FAIL apt prints Pro advertising"; fail=1; } || echo "  ok   apt output has no Pro advertising"
systemctl is-enabled ua-timer.timer 2>/dev/null | grep -q masked && echo "  ok   Pro client timers masked" || echo "  warn Pro client timer not masked"
for p in maluos-server maluos-base maluos-branding postgresql-18 postgresql-18-maludb-core maludb-mc2dbd linux-generic cloud-init; do
  dpkg-query -W -f='${Status}' $p 2>/dev/null | grep -q 'install ok installed' && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }
done
systemctl is-active --quiet postgresql@18-main && echo "  ok   postgresql@18-main active" || { echo "  FAIL postgresql@18-main"; systemctl status postgresql@18-main --no-pager | tail -5; fail=1; }
sudo -n -u postgres psql -Atc "select version()" | cut -c1-40 | sed 's/^/  pg: /'
sudo -n -u postgres psql -Atc "select 1 from pg_available_extensions where name='maludb_core'" | grep -q 1 && echo "  ok   maludb_core extension available" || { echo "  FAIL maludb_core extension"; fail=1; }
df -h / | tail -1 | awk '{print "  root: " $2 " total, " $4 " free (growpart)"}'
sudo -n apt-get update -q >/dev/null 2>&1 && echo "  ok   apt-get update clean" || echo "  warn apt-get update had errors"
# --- updates (Phase 12 slice 5, every variant): unattended-upgrades with the MaluOS policy, the public repository enabled, maluctl update
installed unattended-upgrades && echo "  ok   unattended-upgrades installed" || { echo "  FAIL unattended-upgrades missing"; fail=1; }
grep -q '"MaluOS:resolute"' /etc/apt/apt.conf.d/52maluos-unattended-upgrades && grep -q 'site=packages.mozilla.org' /etc/apt/apt.conf.d/52maluos-unattended-upgrades && echo "  ok   unattended-upgrades policy: security, MaluOS, Mozilla" || { echo "  FAIL unattended-upgrades policy"; fail=1; }
systemctl is-enabled --quiet apt-daily-upgrade.timer && systemctl is-enabled --quiet apt-daily.timer && echo "  ok   apt-daily timers enabled" || { echo "  FAIL apt-daily timers: $(systemctl is-enabled apt-daily.timer apt-daily-upgrade.timer | tr '\n' ' ')"; fail=1; }
! grep -q '^Enabled: no' /etc/apt/sources.list.d/maluos.sources && grep -q 'apt.maluos.com' /etc/apt/sources.list.d/maluos.sources && echo "  ok   maluos.sources enabled (apt.maluos.com)" || { echo "  FAIL maluos.sources: $(grep -E '^(URIs|Enabled)' /etc/apt/sources.list.d/maluos.sources | tr '\n' ' ')"; fail=1; }
maluctl update status > /tmp/upd.txt 2>&1 && grep -q '^pending:' /tmp/upd.txt && grep -q '^restart:' /tmp/upd.txt && echo "  ok   maluctl update status (no privileges): $(grep '^pending:' /tmp/upd.txt | cut -c16-70)" || { echo "  FAIL maluctl update status: $(tail -2 /tmp/upd.txt)"; fail=1; }
maluctl update status --json --compact | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['automatic']['enabled'], d['automatic']; assert any(o.startswith('MaluOS:') for o in d['automatic']['origins']) and any('packages.mozilla.org' in o for o in d['automatic']['origins']), d['automatic']['origins']; assert d['reboot_required'] is False, d; print('  ok   maluctl update status --json: automatic on, origins include MaluOS and Mozilla, no restart due')" || { echo "  FAIL maluctl update status --json"; fail=1; }
sudo -n maluctl update history >/dev/null 2>&1 && echo "  ok   maluctl update history (root)" || { echo "  FAIL maluctl update history"; fail=1; }
# --- slice 7: maluctl update auto writes drop-ins beside the shipped policy and never edits it
pol_sha=$(sha256sum /etc/apt/apt.conf.d/52maluos-unattended-upgrades | cut -c1-64)
sudo -n maluctl update auto off >/dev/null 2>&1 && [ "$(apt-config dump 2>/dev/null | grep -c 'APT::Periodic::Unattended-Upgrade "0"')" = 1 ] && [ -f /etc/apt/apt.conf.d/53maluos-auto ] && echo "  ok   maluctl update auto off: APT::Periodic::Unattended-Upgrade 0 through 53maluos-auto" || { echo "  FAIL update auto off: $(apt-config dump | grep Periodic::Unattended | tr '\n' ' ')"; fail=1; }
maluctl update status --json --compact | python3 -c "import json,sys; d=json.load(sys.stdin); a=d['auto']; assert not d['automatic']['enabled'] and a['changed_by'] and a['changed_at'] and a['managed'], a; print('  ok   status reports automatic off since %s by %s' % (a['changed_at'][:16], a['changed_by']))" || { echo "  FAIL status after auto off"; fail=1; }
sudo -n maluctl update auto set mozilla off >/dev/null 2>&1 && maluctl update status --json --compact | python3 -c "import json,sys; d=json.load(sys.stdin); o=d['automatic']['origins']; assert not any('mozilla' in x for x in o) and any(x.startswith('MaluOS:') for x in o) and any(x.endswith('-security') for x in o), o; assert d['auto']['disabled']==['mozilla']; print('  ok   auto set mozilla off: effective origins drop Mozilla, keep security and MaluOS (54maluos-origins)')" || { echo "  FAIL auto set mozilla off"; fail=1; }
sudo -n maluctl update auto reboot on --at 04:30 >/dev/null 2>&1 && apt-config dump | grep -q 'Unattended-Upgrade::Automatic-Reboot-Time "04:30"' && echo "  ok   auto reboot on --at 04:30" || { echo "  FAIL auto reboot"; fail=1; }
! sudo -n maluctl update auto reboot on --at 25:00 >/dev/null 2>&1 && echo "  ok   a bad restart time is refused" || { echo "  FAIL bad time accepted"; fail=1; }
sudo -n maluctl update auto on >/dev/null 2>&1 && sudo -n maluctl update auto set mozilla on >/dev/null 2>&1 && sudo -n maluctl update auto reboot off >/dev/null 2>&1
[ ! -f /etc/apt/apt.conf.d/53maluos-auto ] && [ ! -f /etc/apt/apt.conf.d/54maluos-origins ] && ! sudo -n test -f /var/lib/maluos/update-auto.json && [ "$(sha256sum /etc/apt/apt.conf.d/52maluos-unattended-upgrades | cut -c1-64)" = "$pol_sha" ] && echo "  ok   every switch at its default removes the drop-ins; the shipped policy is byte for byte what it was" || { echo "  FAIL drop-ins or policy after restoring defaults: $(ls /etc/apt/apt.conf.d/5[34]* 2>&1)"; fail=1; }
maluctl update status --json --compact | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['automatic']['enabled'] and any('mozilla' in x for x in d['automatic']['origins']) and not d['auto']['managed'], d['auto']; print('  ok   status back to the shipped policy')" || { echo "  FAIL status after restoring defaults"; fail=1; }
# the policy ships in every variant; polkit itself (pkaction) only comes with the desktop, so registration is checked there
if command -v pkaction >/dev/null; then pkaction 2>/dev/null | grep -q '^com.maluos.admin$' && echo "  ok   polkit action com.maluos.admin registered (pkexec maluctl)" || { echo "  FAIL polkit action com.maluos.admin not registered"; fail=1; }
else [ -f /usr/share/polkit-1/actions/com.maluos.maluctl.policy ] && echo "  ok   polkit action file shipped (no polkit on this variant)" || { echo "  FAIL polkit action file missing"; fail=1; }; fi
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
# --- the vault (Phase 6 slice 1)
dpkg-query -W -f='${Status}' maluos-vault 2>/dev/null | grep -q 'install ok installed' && echo "  ok   maluos-vault" || { echo "  FAIL maluos-vault"; fail=1; }
systemctl is-active --quiet maluos-vault.socket && echo "  ok   maluos-vault.socket active" || { echo "  FAIL maluos-vault.socket: $(systemctl is-active maluos-vault.socket)"; sudo -n journalctl -u maluos-vault --no-pager | tail -8; fail=1; }
sudo -n test -s /var/lib/maluos-vault/master.cred && echo "  ok   master key credential sealed ($(sudo -n python3 -c "import json;print(json.load(open('/var/lib/maluos/firstboot/done'))['components']['maluos-vault'].get('sealing','?'))" 2>/dev/null))" || { echo "  FAIL no master.cred"; fail=1; }
maluctl secret whoami | grep -q 'principal:  user:maluos' && echo "  ok   login user is principal user:maluos (peer credentials)" || { echo "  FAIL vault whoami"; maluctl secret whoami; sudo -n journalctl -u maluos-vault --no-pager | tail -8; fail=1; }
sudo -n maluctl secret whoami | grep -q 'operator:   yes' && echo "  ok   root is an operator" || { echo "  FAIL root operator"; fail=1; }
sudo -n maluctl secret list --all | grep -q 'system/mc2dbd-token' && echo "  ok   listener token imported into system compartment" || { echo "  FAIL mc2dbd-token not in vault"; sudo -n maluctl secret list --all; fail=1; }
sudo -n maluctl secret list --all | grep -q 'system/maludb-api-token' && echo "  ok   API token stored by its component" || echo "  warn API token not in vault"
sudo -n maluctl secret list --all | grep -q 'system/business-os-admin-password' && echo "  ok   Business OS admin password stored by its component" || echo "  warn BOS admin password not in vault"
echo sk-test-maluos | maluctl secret add openai --provider openai --stdin >/dev/null && [ "$(maluctl secret show openai)" = sk-test-maluos ] && echo "  ok   user secret add/show round trip" || { echo "  FAIL user secret round trip"; fail=1; }
[ "$(maluctl secret exec openai -- sh -c 'echo $OPENAI_API_KEY')" = sk-test-maluos ] && echo "  ok   maluctl secret exec injects OPENAI_API_KEY" || { echo "  FAIL secret exec"; fail=1; }
sudo -n useradd -m -s /bin/bash edward 2>/dev/null; sudo -n maluctl principal add user:edward --kind human --name edward --home user:edward >/dev/null
echo sk-test-edward | sudo -n -u edward maluctl secret add openai --provider openai --stdin >/dev/null
[ "$(sudo -n -u edward maluctl secret show openai)" = sk-test-edward ] && echo "  ok   second user has their own openai key" || { echo "  FAIL edward's key"; fail=1; }
! sudo -n -u edward maluctl secret show user:maluos/openai >/dev/null 2>&1 && echo "  ok   edward cannot read maluos's key" || { echo "  FAIL cross-user read allowed"; fail=1; }
echo S-shared | sudo -n maluctl secret add system/shared-test --kind token --stdin >/dev/null; sudo -n maluctl secret grant system/shared-test --to user:edward --level read >/dev/null
[ "$(sudo -n -u edward maluctl secret show shared-test)" = S-shared ] && echo "  ok   shared secret via grant" || { echo "  FAIL shared grant"; fail=1; }
maluctl secret usage --raw | grep -q 'secret.read .*ok .*user:maluos' && echo "  ok   ledger records reads" || { echo "  FAIL ledger reads"; maluctl secret usage --raw | tail -3; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where status='denied' and principal_ref='user:edward'" | grep -qE '^[1-9]' && echo "  ok   denial recorded in maluos_ledger" || { echo "  FAIL denial not in ledger"; fail=1; }
! sudo -n journalctl -u maluos-vault --no-pager | grep -q 'sk-test' && ! sudo -n -u postgres pg_dump -d maludb -n maluos --data-only 2>/dev/null | grep -q 'sk-test' && echo "  ok   no secret value in the journal or the database" || { echo "  FAIL secret value leaked"; fail=1; }
sudo -n maluctl status | grep -q 'component:   maluos-vault  ok' && echo "  ok   maluctl status shows the vault component" || echo "  warn vault component line missing from maluctl status"
# --- the inference gateway (Phase 6 slice 2): real daemon, mock backend (no GPU in CI)
dpkg-query -W -f='${Status}' maluos-gateway 2>/dev/null | grep -q 'install ok installed' && echo "  ok   maluos-gateway" || { echo "  FAIL maluos-gateway"; fail=1; }
systemctl is-active --quiet maluos-gateway.socket && echo "  ok   maluos-gateway.socket active" || { echo "  FAIL maluos-gateway.socket: $(systemctl is-active maluos-gateway.socket)"; sudo -n journalctl -u maluos-gateway --no-pager | tail -8; fail=1; }
maluctl gateway whoami | grep -q '"principal": "user:maluos"' && echo "  ok   gateway identifies the login user (peer credentials)" || { echo "  FAIL gateway whoami"; maluctl gateway whoami; sudo -n journalctl -u maluos-gateway --no-pager | tail -8; fail=1; }
maluctl gateway status | grep -q 'backend:     ollama-local' && echo "  ok   seeded catalogue: ollama-local backend ($(maluctl gateway status | grep -o 'ollama-local.*' | grep -o 'healthy\|down' | head -1 || echo unchecked), no Ollama installed)" || { echo "  FAIL catalogue not seeded"; maluctl gateway status; fail=1; }
sudo -n systemd-run --quiet --unit maluos-mock-ollama -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_gateway.mock_ollama --port 11999
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:11999/api/tags >/dev/null 2>&1 && break; sleep 1; done   # slow under emulation
sudo -n maluctl gateway backend add mock --kind mock --endpoint http://127.0.0.1:11999 >/dev/null && sudo -n maluctl gateway alias set fast --tier fast --backend mock --model mock-7b --position 9 >/dev/null \
  && sudo -n maluctl gateway alias set embed --tier embed --backend mock --model mock-embed --position 9 >/dev/null && echo "  ok   mock backend and aliases added through maluctl" || { echo "  FAIL adding the mock backend"; fail=1; }
for i in $(seq 1 30); do maluctl gateway status | grep -q 'backend:     mock  mock .* healthy' && break; sudo -n maluctl gateway reload >/dev/null 2>&1; sleep 2; done
maluctl gateway status | grep -q 'backend:     mock  mock .* healthy' && echo "  ok   mock backend healthy" || { echo "  FAIL mock backend not healthy"; maluctl gateway status; fail=1; }
maluctl gateway chat "hello from the image" --model fast 2>/dev/null | grep -q 'mock reply to: hello from the image' && echo "  ok   chat through tier fast (unhealthy ollama-local rung skipped)" || { echo "  FAIL gateway chat"; maluctl gateway chat "hello" --model fast; maluctl gateway routes | tail -3; fail=1; }
curl -sS --unix-socket /run/maluos/gateway.sock -H 'Content-Type: application/json' http://g/v1/chat/completions -d '{"model":"fast","stream":true,"stream_options":{"include_usage":true},"messages":[{"role":"user","content":"stream"}]}' | grep -q '"completion_tokens"' && echo "  ok   OpenAI streaming with usage over the socket" || { echo "  FAIL OpenAI streaming"; fail=1; }
curl -sS --unix-socket /run/maluos/gateway.sock -H 'Content-Type: application/json' http://g/api/chat -d '{"model":"fast","messages":[{"role":"user","content":"nd"}]}' | tail -1 | grep -q '"done": true' && echo "  ok   Ollama API over the socket" || { echo "  FAIL Ollama API"; fail=1; }
curl -sS --unix-socket /run/maluos/gateway.sock -H 'Content-Type: application/json' http://g/v1/embeddings -d '{"model":"embed","input":"e"}' | grep -q '"embedding"' && echo "  ok   embeddings" || { echo "  FAIL embeddings"; fail=1; }
sudo -n -u edward maluctl gateway chat "edward here" --model fast 2>/dev/null | grep -q 'mock reply' && sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='model.call' and principal_ref='user:edward' and status='ok' and tokens_out > 0" | grep -qE '^[1-9]' && echo "  ok   second user's call attributed in the ledger" || { echo "  FAIL ledger attribution"; fail=1; }
maluctl gateway usage --by principal 2>/dev/null | grep -q 'user:maluos' && echo "  ok   maluctl gateway usage (ledger via the vault)" || { echo "  FAIL gateway usage"; maluctl gateway usage --by principal; fail=1; }
sudo -n -u postgres psql -qAtd maludb -c "set search_path to maluos, maludb_core, public; select maludb_core.register_model_provider('mockprov','local_http','ollama',NULL,'internal'); select maludb_core.register_model_alias('fast','mockprov','mock-7b');" >/dev/null 2>&1
erid=$(sudo -n -u postgres psql -qAtd maludb -c "set search_path to maluos, maludb_core, public; select submit_request('fast', 'Hello engine', NULL, NULL, '{}', 30000)")
for i in $(seq 1 30); do est=$(sudo -n -u postgres psql -qAtd maludb -c "set search_path to maluos, maludb_core, public; select request_status($erid)"); [ "$est" = succeeded ] && break; sleep 1; done
[ "$est" = succeeded ] && sudo -n -u postgres psql -qAtd maludb -c "set search_path to maluos, maludb_core, public; select output_text from get_response($erid)" | grep -q 'mock reply to: Hello engine' && echo "  ok   engine model request drained through the gateway" || { echo "  FAIL engine queue (status $est)"; sudo -n journalctl -u maluos-gateway --no-pager | grep -i engine | tail -5; fail=1; }
curl -fsS --max-time 10 -H "Authorization: Bearer $tok" -X POST http://127.0.0.1:5329/ -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"maluos.model_status","arguments":{}}}' | grep -q '"expected_wait_s"' && echo "  ok   MCP tool maluos.model_status on the listener" || { echo "  FAIL MCP model_status"; curl -sS --max-time 10 -H "Authorization: Bearer $tok" -X POST http://127.0.0.1:5329/ -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"maluos.model_status","arguments":{}}}' | head -c 400; echo; fail=1; }
# --- slice 3: a cloud rung (the mock's Anthropic emulation) with a key from the vault, the sensitivity gate, cost
echo sk-image-anthropic | sudo -n maluctl secret add system/anthropic --provider anthropic --stdin >/dev/null && sudo -n maluctl secret grant system/anthropic --to user:maluos --level use >/dev/null
sudo -n maluctl gateway backend add anthropic-mock --kind anthropic --endpoint http://127.0.0.1:11999 --secret anthropic --models claude-mock >/dev/null
sudo -n maluctl gateway tier add cloud >/dev/null; sudo -n maluctl gateway alias set cloud --tier cloud --backend anthropic-mock --model claude-mock >/dev/null
sudo -n maluctl gateway price set anthropic-mock claude-mock --input 3 --output 15 >/dev/null; sleep 2
maluctl gateway chat "hello cloud" --model cloud 2>/dev/null | grep -q 'mock claude reply to: hello cloud' && echo "  ok   cloud rung through the vault-held key (Anthropic API emulated)" || { echo "  FAIL cloud rung"; maluctl gateway chat "hello cloud" --model cloud; maluctl gateway routes | head -3; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='secret.use' and principal_ref='user:maluos' and broker_ref='user:maluos-gateway' and secret_name='anthropic'" | grep -qE '^[1-9]' && echo "  ok   vault ledger: key used by the gateway on the caller's behalf" || { echo "  FAIL secret.use row"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='model.call' and backend='anthropic-mock' and status='ok' and cost_actual > 0" | grep -qE '^[1-9]' && echo "  ok   cloud call costed in the ledger" || { echo "  FAIL cost_actual"; fail=1; }
curl -sS --unix-socket /run/maluos/gateway.sock -H 'Content-Type: application/json' -H 'X-MaluOS-Sensitivity: restricted' http://g/v1/chat/completions -d '{"model":"cloud","messages":[{"role":"user","content":"secret"}]}' | grep -q 'sensitivity:restricted' && echo "  ok   restricted content never routes to the cloud" || { echo "  FAIL sensitivity gate"; fail=1; }
! sudo -n -u edward maluctl gateway chat "x" --model cloud >/dev/null 2>&1 && echo "  ok   a user without a key grant cannot use the cloud rung" || { echo "  FAIL ungranted cloud use"; fail=1; }
# --- slice 4: delegation, task episodes, alerts, export
echo sk-image-own | maluctl secret add anthropic --provider anthropic --stdin >/dev/null && maluctl secret delegate --to user:edward --secret anthropic --expires 1h >/dev/null
sudo -n -u edward maluctl gateway chat "delegated" --model cloud 2>/dev/null | grep -q 'mock claude' && sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='secret.use' and principal_ref='user:edward' and reason='delegation:user:maluos'" | grep -qE '^[1-9]' && echo "  ok   delegated key used by another principal (use only)" || { echo "  FAIL delegation"; sudo -n -u edward maluctl gateway chat "delegated" --model cloud; maluctl secret delegations; fail=1; }
curl -sS --unix-socket /run/maluos/gateway.sock -H 'Content-Type: application/json' -H 'X-MaluOS-Task: boot-test' http://g/v1/chat/completions -d '{"model":"fast","messages":[{"role":"user","content":"task"}]}' >/dev/null
sudo -n -u postgres psql -Atd maludb -c "set role maluos; set search_path to maluos, maludb_core, public; select count(*) from maludb_episode where episode_kind='maluos.model_call' and payload_jsonb->>'task_ref'='boot-test'" | grep -qE '^[1-9]' && echo "  ok   task-bearing call recorded as a memory episode" || { echo "  FAIL task episode"; fail=1; }
sudo -n curl -sS --unix-socket /run/maluos/gateway.sock -H 'Content-Type: application/json' http://g/v1/maluos/alert -d '{"kind":"boot","title":"boot test alert"}' | grep -q '"fired": true' && sudo -n maluctl gateway alerts | grep -q 'boot test alert' && sudo -n -u postgres psql -Atd maludb -c "set role maluos; set search_path to maluos, maludb_core, public; select count(*) from maludb_episode where episode_kind='maluos.alert'" | grep -qE '^[1-9]' && echo "  ok   alerts reach the ledger, memory and maluctl" || { echo "  FAIL alerts"; sudo -n maluctl gateway alerts; fail=1; }
echo bootpw > /tmp/pw.txt; sudo -n maluctl secret export /tmp/vault-export.bin --passphrase-file /tmp/pw.txt | grep -q exported && sudo -n maluctl secret import /tmp/vault-export.bin --passphrase-file /tmp/pw.txt | grep -q imported && echo "  ok   vault export and import round trip" || { echo "  FAIL vault export/import"; fail=1; }
sudo -n test -f /var/lib/maluos-gateway/engine-inflight.json && echo "  ok   restart accounting state present" || echo "  warn no engine-inflight.json yet"
! sudo -n journalctl -u maluos-gateway --no-pager | grep -q 'sk-image-anthropic' && echo "  ok   no key value in the gateway journal" || { echo "  FAIL key leaked"; fail=1; }
! sudo -n journalctl -u maluos-gateway --no-pager | grep -q 'internal error' && echo "  ok   no internal errors in the gateway journal" || { echo "  FAIL gateway internal errors"; sudo -n journalctl -u maluos-gateway --no-pager | grep 'internal error' | tail -3; fail=1; }
sudo -n maluctl status | grep -q 'component:   maluos-gateway  ok' && echo "  ok   maluctl status shows the gateway component" || echo "  warn gateway component line missing from maluctl status"
sudo -n systemctl stop maluos-mock-ollama 2>/dev/null
# --- agents as system entities (maluos-agent); the mock backend is started again for the demo agent
dpkg-query -W -f='${Status}' maluos-agent 2>/dev/null | grep -q 'install ok installed' && echo "  ok   maluos-agent" || { echo "  FAIL maluos-agent"; fail=1; }
sudo -n systemd-run --quiet --unit maluos-mock-ollama-2 -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_gateway.mock_ollama --port 11999 --token-delay 0.15   # slow enough that a streamed answer shows its partial text first (slice 9)
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:11999/api/tags >/dev/null 2>&1 && break; sleep 1; done
for i in $(seq 1 30); do sudo -n maluctl gateway reload >/dev/null 2>&1; maluctl gateway status | grep -q 'backend:     mock  mock .* healthy' && break; sleep 2; done
sudo -n maluctl agent create research --exec "/usr/bin/python3 /usr/lib/maluos/maluos-agent-demo.py" --scope org:read --tiers fast,standard --budget usd_per_day=1 --token --sandbox strict >/dev/null \
  && echo "  ok   maluctl agent create research" || { echo "  FAIL agent create"; sudo -n maluctl agent create research --exec /bin/true; fail=1; }
getent passwd agent-research >/dev/null && echo "  ok   agent user exists" || { echo "  FAIL agent user"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "set role maluos; set search_path to maluos, maludb_core, public; select principal_kind || ' ' || (select string_agg(scope || ':' || access_level, ',') from maludb_principal_scope s where s.principal_ref='agent:research' and revoked_at is null) from maludb_principal where principal_ref='agent:research'" | grep -q 'agent org:read' && echo "  ok   principal agent:research with scope org:read" || { echo "  FAIL agent principal"; fail=1; }
sudo -n maluctl agent run research -- maluctl gateway whoami | grep -q '"principal": "agent:research"' && echo "  ok   the agent's identity reaches the gateway (identities map)" || { echo "  FAIL agent identity"; sudo -n maluctl agent run research -- maluctl gateway whoami; fail=1; }
sudo -n maluctl agent run research -- maluctl secret whoami | grep -q 'principal:  agent:research' && echo "  ok   the agent's identity reaches the vault" || { echo "  FAIL agent vault identity"; fail=1; }
for i in $(seq 1 30); do sudo -n journalctl -u maluos-agent@research --no-pager 2>/dev/null | grep -q 'answer: mock reply' && break; sleep 2; done
sudo -n journalctl -u maluos-agent@research --no-pager | grep -q 'answer: mock reply' && echo "  ok   demo agent unit called the gateway as itself" || { echo "  FAIL demo agent"; sudo -n journalctl -u maluos-agent@research --no-pager | tail -5; fail=1; }
# slice 8: the agent's task interface (maluos_agent_tasks on the unit's runtime directory)
for i in $(seq 1 15); do sudo -n test -S /run/maluos/agents/research/tasks.sock && break; sleep 2; done
sudo -n test -S /run/maluos/agents/research/tasks.sock && echo "  ok   the demo agent serves its task socket" || { echo "  FAIL no task socket: $(sudo -n ls -la /run/maluos/agents/ 2>&1 | tail -3)"; fail=1; }
sudo -n maluctl agent card research | grep -q 'capabilities: chat' && echo "  ok   maluctl agent card research (agent/card)" || { echo "  FAIL agent card: $(sudo -n maluctl agent card research 2>&1 | tail -2)"; fail=1; }
sudo -n maluctl agent send research "ping from the boot test" 2>/dev/null | grep -q 'mock reply' && echo "  ok   maluctl agent send: a task answered through the gateway (tasks/send)" || { echo "  FAIL agent send: $(sudo -n maluctl agent send research ping 2>&1 | tail -2)"; fail=1; }
[ "$(sudo -n maluctl agent tasks research | grep -c completed)" = 1 ] && echo "  ok   maluctl agent tasks lists the task as completed (tasks/list)" || { echo "  FAIL agent tasks: $(sudo -n maluctl agent tasks research 2>&1 | tail -2)"; fail=1; }
# slice 9: answers stream (tasks/send without waiting, tasks/get while it works): the demo agent's partial line, then the answer
out=$(sudo -n maluctl agent send research "stream check" 2>&1); echo "$out" | grep -q '^working on: stream check' && echo "$out" | grep -q 'mock reply to: stream check' && echo "  ok   maluctl agent send streams: partial text (working on: …) before the final answer" || { echo "  FAIL agent send streaming: $out"; fail=1; }
# slice 9: re-authentication before a reveal; from a shell without a polkit agent (SSH) or without polkit (servers) it is refused
echo reauth-value | maluctl secret add reauthtest --stdin >/dev/null 2>&1
maluctl secret show reauthtest --reauth 2>&1 | grep -q 're-authentication refused' && echo "  ok   maluctl secret show --reauth without a polkit agent is refused (reauth_required)" || { echo "  FAIL reauth refusal: $(maluctl secret show reauthtest --reauth 2>&1 | tail -1)"; fail=1; }
[ "$(maluctl secret show reauthtest 2>/dev/null)" = reauth-value ] && echo "  ok   a plain show still reads it (no re-authentication asked)" || { echo "  FAIL plain show"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='secret.read' and secret_name='reauthtest' and status='denied' and reason='reauth_required'" | grep -qE '^[1-9]' && echo "  ok   ledger: the refused reveal is a denied secret.read with reason reauth_required" || { echo "  FAIL reauth ledger row"; fail=1; }
maluctl secret delete reauthtest >/dev/null 2>&1 || true
sudo -n -u edward maluctl agent card research 2>&1 | grep -q 'may not talk to this agent' && echo "  ok   another user is refused by the task socket (peer credentials)" || { echo "  FAIL task socket admitted another user: $(sudo -n -u edward maluctl agent card research 2>&1 | tail -1)"; fail=1; }
sudo -n maluctl agent list --json | python3 -c "import json,sys; a=[x for x in json.load(sys.stdin) if x['name']=='research'][0]; assert a['tasks'] and a['active']=='active', a; print('  ok   maluctl agent list --json marks the agent as accepting tasks')" || { echo "  FAIL agent list --json"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='model.call' and principal_ref='agent:research' and status='ok' and process_ref like 'python3@maluos-agent@research.service' and class='agent'" | grep -qE '^[1-9]' && echo "  ok   ledger: agent call attributed to the unit, class agent" || { echo "  FAIL agent ledger row"; sudo -n -u postgres psql -Atd maludb -c "select principal_ref, process_ref, class, status from maluos.maluos_ledger where principal_ref='agent:research' order by ledger_id desc limit 3"; fail=1; }
sudo -n maluctl gateway catalog | grep -q 'principal agent:research  class=agent  tiers=fast,standard' && echo "  ok   gateway policy for the agent" || { echo "  FAIL agent policy"; sudo -n maluctl gateway catalog | grep research; fail=1; }
sudo -n test -s /etc/maluos/agents/research.token && echo "  ok   gateway token delivered as a credential" || { echo "  FAIL agent token"; fail=1; }
sudo -n maluctl agent show research | grep -q 'sandbox:     strict' && echo "  ok   strict sandbox drop-in" || { echo "  FAIL sandbox"; fail=1; }
sudo -n maluctl agent remove research >/dev/null && ! systemctl is-active --quiet maluos-agent@research && sudo -n -u postgres psql -Atd maludb -c "set role maluos; set search_path to maluos, maludb_core, public; select enabled from maludb_principal where principal_ref='agent:research'" | grep -q f && echo "  ok   agent remove: unit stopped, principal disabled" || { echo "  FAIL agent remove"; fail=1; }
sudo -n systemctl stop maluos-mock-ollama-2 2>/dev/null
# --- MaluDB API component (when the image carries it)
if installed maluos-api; then
for p in maluos-api maludb-api; do dpkg-query -W -f='${Status}' $p 2>/dev/null | grep -q 'install ok installed' && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }; done
systemctl is-active --quiet maludb-api && echo "  ok   maludb-api active" || { echo "  FAIL maludb-api: $(systemctl is-active maludb-api)"; sudo -n journalctl -u maludb-api --no-pager | tail -8; fail=1; }
curl -fsS --max-time 5 http://127.0.0.1:8000/health | grep -q ok && echo "  ok   API /health" || { echo "  FAIL API /health"; fail=1; }
atok=$(sudo -n maluctl token api 2>/dev/null); [ "${atok#malu_}" != "$atok" ] && echo "  ok   API token minted" || { echo "  FAIL API token"; fail=1; }
curl -fsS --max-time 10 -H "Authorization: Bearer $atok" http://127.0.0.1:8000/v1/subjects >/dev/null && echo "  ok   API /v1/subjects with token (PostgreSQL 18 query path)" || { echo "  FAIL API /v1/subjects"; sudo -n journalctl -u maludb-api --no-pager | tail -5; fail=1; }
systemctl is-active --quiet maludb-embedding-worker.timer && echo "  ok   embedding sweep timer" || echo "  warn embedding sweep timer not active"
else echo "  (no maluos-api in this image)"; fi
# --- Business OS kernel component (when the image carries it)
if installed maluos-business-os; then
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
# desk enrolment, the office half (kernel db/187; docs/desk-enrolment.md): the endpoints through Apache's allow-list on the
# person face, a code minted for the super-admin, the whole exchange a MaluOS desk makes, and the presence job in the crontab
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Host: app.$bosdom" -H 'Content-Type: application/json' -X POST http://127.0.0.1/api/v1/desks/enroll -d '{"surface":1,"code":"ZZZZ-ZZZZ"}')
[ "$code" = 403 ] && echo "  ok   /api/v1/desks/enroll served through Apache; a wrong code is 403" || { echo "  FAIL desks/enroll via Apache: HTTP $code"; fail=1; }
bosadmin=$(sudo -n -u postgres psql -Atd maludb_os -c "select email from members where business_role='super_admin' and status='active' order by id limit 1")
deskcode=$(cd /var/www && sudo -n -u www-data php bin/mint_desk_code.php --email "$bosadmin" --name "Boot test desk" 2>/dev/null | grep -oE '[A-Z2-9]{4}-[A-Z2-9]{4}' | head -1)
[ -n "$deskcode" ] && echo "  ok   bin/mint_desk_code.php minted a code for $bosadmin" || { echo "  FAIL mint_desk_code: $(cd /var/www && sudo -n -u www-data php bin/mint_desk_code.php --email "$bosadmin" 2>&1 | tail -2)"; fail=1; }
dcall() { curl -s --max-time 30 -H "Host: app.$bosdom" -H 'Content-Type: application/json' -H "Authorization: Bearer $2" -X "$1" "http://127.0.0.1$3" ${4:+-d "$4"}; }
enr=$(dcall POST "" /api/v1/desks/enroll "{\"surface\":1,\"code\":\"$deskcode\",\"principal\":\"user:maluos\",\"hostname\":\"boot-test\",\"os_platform\":\"linux\",\"os_release\":\"MaluOS test\",\"app_version\":\"maluos-desk 0.1.1\",\"mcp_surface_version\":\"1\",\"cpu_cores\":4,\"memory_mb\":2048,\"storage_gb\":8,\"machine_id\":\"0123456789abcdef0123456789abcdef\"}")
desktok=$(echo "$enr" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['desk']['name']=='Boot test desk' and d['desk']['status']=='active' and d['endpoints']['records'].endswith('/mcp/records') and d['endpoints']['models'] is None; print(d['token'])" 2>/dev/null)
[ -n "$desktok" ] && echo "  ok   a desk enrolled with the code: token issued, records endpoint published, no model endpoint yet" || { echo "  FAIL desk enrol: $(echo "$enr" | head -c 300)"; fail=1; }
dcall POST "$desktok" /api/v1/desks/heartbeat '{"surface":1,"presence":"online","facts":{"cpu_cores":4}}' | grep -q '"presence":"online"' && sudo -n -u postgres psql -Atd maludb_os -c "select presence from locations where kind='desk' and name='Boot test desk'" | grep -q online && echo "  ok   heartbeat: the desk is online in the estate" || { echo "  FAIL desk heartbeat"; fail=1; }
dcall GET "$desktok" /api/v1/desks/me | grep -q '"name":"Boot test desk"' && echo "  ok   desks/me with the desk token" || { echo "  FAIL desks/me"; fail=1; }
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Host: app.$bosdom" -H "Authorization: Bearer $desktok" http://127.0.0.1/api/v1/me)" = 401 ] && echo "  ok   the desk token is refused on /api/v1/me (one scope per surface)" || { echo "  FAIL desk token accepted on /api/v1/me"; fail=1; }
dcall POST "$desktok" /api/v1/desks/leave '{"surface":1}' | grep -q '"status":"retired"' && [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Host: app.$bosdom" -H "Authorization: Bearer $desktok" http://127.0.0.1/api/v1/desks/me)" = 410 ] && echo "  ok   desks/leave retired the desk; its token answers 410" || { echo "  FAIL desks/leave"; fail=1; }
sudo -n crontab -u www-data -l 2>/dev/null | grep -q desk_presence && echo "  ok   the desk presence job is in www-data's crontab" || { echo "  FAIL desk_presence cron missing"; fail=1; }
else echo "  (no maluos-business-os in this image)"; fi
# --- the desktop (Phase 12): GNOME on gdm, the MaluOS identity on the login screen, no snaps
if installed maluos-desktop; then
for p in maluos-desktop maluos-desktop-branding gdm3 gnome-shell ubuntu-session gnome-control-center nautilus ptyxis firefox gnome-software gnome-software-plugin-deb appstream maluos-archive-mozilla; do installed $p && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }; done
for p in snapd gnome-software-plugin-snap gnome-software-plugin-flatpak update-manager update-notifier ubuntu-release-upgrader-gtk ubuntu-report whoopsie apport; do ! installed $p && echo "  ok   no $p" || { echo "  FAIL $p is installed"; fail=1; }; done
# --- slice 5: Firefox from Mozilla's repository, GNOME Software with the deb plugin only
fv=$(dpkg-query -W -f='${Version}' firefox 2>/dev/null); echo "$fv" | grep -qv snap && dpkg-query -W -f='${Maintainer}' firefox | grep -qi mozilla && echo "  ok   firefox $fv is Mozilla's deb, not the snap shim" || { echo "  FAIL firefox version $fv / $(dpkg-query -W -f='${Maintainer}' firefox)"; fail=1; }
[ -f /etc/apt/sources.list.d/mozilla.sources ] && [ -s /usr/share/keyrings/packages.mozilla.org.gpg ] && [ -f /etc/apt/preferences.d/maluos-mozilla ] && echo "  ok   mozilla.sources, its keyring and the pin are installed" || { echo "  FAIL Mozilla apt configuration"; fail=1; }
pol=$(apt-cache policy firefox 2>/dev/null); echo "$pol" | grep -q 'packages.mozilla.org' && echo "$pol" | grep -A1 'Candidate' | grep -qv snap && echo "  ok   apt prefers packages.mozilla.org for firefox (pin 1000; Ubuntu's shim pinned out)" || echo "  warn apt policy for firefox: $(echo "$pol" | grep -E 'Candidate|Installed' | tr '\n' ' ') (no network to Mozilla?)"
grep -q 'download-updates-notify=false' /usr/share/glib-2.0/schemas/30_maluos-session.gschema.override && echo "  ok   GNOME Software leaves the updates notification to the session" || { echo "  FAIL gnome-software override"; fail=1; }
[ -f /usr/share/applications/firefox.desktop ] && grep -q 'x-scheme-handler/http=.*firefox.desktop' /usr/share/applications/ubuntu-mimeapps.list && echo "  ok   Firefox is the session's default browser (ubuntu-mimeapps.list)" || { echo "  FAIL default browser"; fail=1; }
[ "$(systemctl get-default)" = graphical.target ] && echo "  ok   default target graphical" || { echo "  FAIL default target is $(systemctl get-default)"; fail=1; }
systemctl is-active --quiet gdm && echo "  ok   gdm active" || { echo "  FAIL gdm: $(systemctl is-active gdm)"; sudo -n journalctl -u gdm --no-pager | tail -8; fail=1; }
for i in $(seq 1 60); do pgrep -x gnome-shell >/dev/null && break; sleep 5; done   # the greeter under software rendering
pgrep -x gnome-shell >/dev/null && echo "  ok   gnome-shell running as $(ps -o user= -p "$(pgrep -x gnome-shell | head -1)") (the greeter)" || { echo "  FAIL no gnome-shell process"; sudo -n journalctl -b --no-pager | grep -iE 'gnome-shell|gdm' | tail -15; fail=1; }
grep -q '^VARIANT="Desktop"' /etc/os-release && echo "  ok   os-release VARIANT=Desktop" || { echo "  FAIL os-release variant: $(grep ^VARIANT= /etc/os-release)"; fail=1; }
grep -q '^Name=MaluOS' /usr/share/wayland-sessions/ubuntu.desktop && echo "  ok   session entry says MaluOS" || { echo "  FAIL session entry still Ubuntu"; fail=1; }
[ -f /usr/share/backgrounds/maluos/maluos-dark.png ] && [ -f /usr/share/pixmaps/maluos-logo-text.png ] && [ -f /usr/share/icons/hicolor/128x128/apps/maluos-logo.png ] && echo "  ok   wallpaper, login logo and distributor icon present" || { echo "  FAIL branding assets missing"; fail=1; }
# --- slice 7: power defaults that keep agents alive, the dock, the Upgrade Manager
gs() { XDG_CURRENT_DESKTOP=$1 dbus-run-session -- gsettings get "$2" "$3" 2>/dev/null; }
[ "$(gs ubuntu:GNOME org.gnome.desktop.session idle-delay)" = "uint32 0" ] && [ "$(gs ubuntu:GNOME org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type)" = "'nothing'" ] && [ "$(gs ubuntu:GNOME org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type)" = "'nothing'" ] && echo "  ok   session power defaults: screen blank never, no automatic suspend on mains or battery" || { echo "  FAIL session power defaults: $(gs ubuntu:GNOME org.gnome.desktop.session idle-delay) $(gs ubuntu:GNOME org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type) $(gs ubuntu:GNOME org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type)"; fail=1; }
[ "$(gs GNOME-Greeter:GNOME org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type)" = "'nothing'" ] && echo "  ok   the login screen does not suspend an idle desk" || { echo "  FAIL greeter suspend: $(gs GNOME-Greeter:GNOME org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type)"; fail=1; }
fav=$(gs ubuntu:GNOME org.gnome.shell favorite-apps); echo "$fav" | grep -q "com.maluos.Desk.desktop" && echo "$fav" | grep -q "com.maluos.UpgradeManager.desktop" && echo "$fav" | grep -q "firefox.desktop" && echo "  ok   the dock pins Firefox, the Desk and the Upgrade Manager" || { echo "  FAIL favorite-apps: $fav"; fail=1; }
[ -f /usr/share/applications/com.maluos.UpgradeManager.desktop ] && grep -q '^Exec=maluos-desk --window updates' /usr/share/applications/com.maluos.UpgradeManager.desktop && echo "  ok   Upgrade Manager launcher installed" || { echo "  FAIL Upgrade Manager launcher"; fail=1; }
echo "$fav" | grep -q "com.maluos.ToolsInstaller.desktop" && [ -f /usr/share/applications/com.maluos.ToolsInstaller.desktop ] && echo "$fav" | grep -q "com.maluos.CredentialManager.desktop" && [ -f /usr/share/applications/com.maluos.CredentialManager.desktop ] && echo "$fav" | grep -q "com.maluos.MaluApps.desktop" && [ -f /usr/share/applications/com.maluos.MaluApps.desktop ] && echo "  ok   Tools Installer, Credential Manager and MaluApps pinned, launchers installed" || { echo "  FAIL Tools Installer launcher/pin"; fail=1; }
installed maluos-tools && [ "$(maluctl tools list 2>/dev/null | wc -l)" = 5 ] && maluctl tools list | grep -q '^google-chrome .*not installed' && echo "  ok   maluctl tools lists the five tools (Chrome, VS Code, Claude Code, Codex, Ollama)" || { echo "  FAIL maluctl tools list: $(maluctl tools list 2>&1 | head -3)"; fail=1; }
maluctl tools list --json --compact | python3 -c "
import json,sys,os; rows=json.load(sys.stdin); assert len(rows)==5, rows
for r in rows: assert r['scope'] in ('system','user') and r['check'] and r['notice'] and r['vendor_url'] and os.access('/usr/share/maluos-tools/%s/install.sh' % r['id'], os.X_OK), r
assert [r['id'] for r in rows if r['scope']=='user']==['claude-code'], rows
print('  ok   every tool has a scope, a check, a notice, a vendor URL and an executable install.sh (Claude Code per user, the rest system-wide)')" || { echo "  FAIL tool definitions"; fail=1; }
! maluctl tools check codex >/dev/null 2>&1 && echo "  ok   a tool that is not installed checks as such (exit 1)" || { echo "  FAIL tools check codex"; fail=1; }
! maluctl tools check nosuch >/dev/null 2>&1 && echo "  ok   an unknown tool is refused" || { echo "  FAIL tools check nosuch"; fail=1; }
grep -aq maluos-logo-text /usr/share/glib-2.0/schemas/gschemas.compiled && echo "  ok   gsettings overrides compiled" || { echo "  FAIL gschemas.compiled lacks the MaluOS override"; fail=1; }
logo=$(dbus-run-session -- gsettings get org.gnome.login-screen logo 2>/dev/null); echo "$logo" | grep -q maluos-logo-text && echo "  ok   login screen logo is MaluOS" || { echo "  FAIL login screen logo: ${logo:-unreadable}"; fail=1; }
bg=$(XDG_CURRENT_DESKTOP=ubuntu:GNOME dbus-run-session -- gsettings get org.gnome.desktop.background picture-uri-dark 2>/dev/null); echo "$bg" | grep -q maluos-dark && echo "  ok   session background is the MaluOS wallpaper" || echo "  warn session background: ${bg:-unreadable}"
grep -q 'file:///usr/share/backgrounds/maluos' /usr/share/glib-2.0/schemas/20_maluos-desktop.gschema.override && echo "  ok   desktop override file shipped" || { echo "  FAIL override file"; fail=1; }
systemctl is-active --quiet NetworkManager && echo "  ok   NetworkManager active" || echo "  warn NetworkManager: $(systemctl is-active NetworkManager)"

# --- the agent-aware session (Phase 12 slice 2): auto-login into the MaluOS session, the indicator, the session service
installed maluos-desktop-session && echo "  ok   maluos-desktop-session" || { echo "  FAIL maluos-desktop-session"; fail=1; }
installed maluos-agents && echo "  ok   maluos-agents" || { echo "  FAIL maluos-agents"; fail=1; }
gs=$(dpkg-query -W -f='${Version}' gnome-shell | cut -d. -f1)
grep -q "\"$gs\"" /usr/share/gnome-shell/extensions/maluos-session@maluos.com/metadata.json && echo "  ok   extension declares shell version $gs" || { echo "  FAIL extension metadata lacks shell version $gs"; fail=1; }
grep -q "maluos-session@maluos.com" /usr/share/glib-2.0/schemas/30_maluos-session.gschema.override && echo "  ok   extension enabled for the MaluOS session (override)" || { echo "  FAIL session override"; fail=1; }
uid=$(id -u); export XDG_RUNTIME_DIR=/run/user/$uid DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus
for i in $(seq 1 90); do loginctl list-sessions --no-legend 2>/dev/null | grep -qE "maluos +seat0" && [ -S /run/user/$uid/bus ] && systemctl --user is-active --quiet graphical-session.target 2>/dev/null && break; sleep 5; done
loginctl list-sessions --no-legend | grep -qE "maluos +seat0" && systemctl --user is-active --quiet graphical-session.target && echo "  ok   auto-login: maluos has a graphical session on seat0" || { echo "  FAIL no graphical session for maluos"; loginctl list-sessions --no-legend; sudo -n journalctl -u gdm --no-pager | tail -5; fail=1; }
[ "$(gsettings get org.gnome.desktop.screensaver lock-enabled 2>/dev/null)" = false ] && echo "  ok   test session does not idle-lock (dconf system db from the seed)" || { echo "  warn idle lock not disabled; unlocking"; loginctl unlock-session "$(loginctl list-sessions --no-legend | awk '/seat0/{print $1}')" 2>/dev/null; gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.SetActive false >/dev/null 2>&1; }
extinfo() { gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Extensions.GetExtensionInfo maluos-session@maluos.com 2>&1; }
for i in $(seq 1 60); do extinfo | grep -q "'state': <1\.0>" && break; sleep 5; done
info=$(extinfo)
echo "$info" | grep -q "'state': <1\.0>" && echo "  ok   maluos-session extension enabled in the user's shell" || { echo "  FAIL extension state: $(echo "$info" | grep -o "'state': <[^>]*>\|'error': <[^>]*>" | head -2 | tr '\n' ' ')"; sudo -n journalctl -b --no-pager _UID=$uid 2>/dev/null | grep -i "maluos-session\|extension" | tail -8; fail=1; }
for i in $(seq 1 12); do systemctl --user is-active --quiet maluos-desktop-session && break; sleep 5; done
systemctl --user is-active --quiet maluos-desktop-session && echo "  ok   session service active (user unit, D-Bus activated by the extension)" || { echo "  FAIL session service: $(systemctl --user is-active maluos-desktop-session)"; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | tail -8; fail=1; }
state() { gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.GetState 2>/dev/null | python3 -c "import ast,sys,json; print(json.dumps(json.loads(ast.literal_eval(sys.stdin.read())[0])))"; }
state | python3 -c "
import json,sys; s=json.load(sys.stdin)
assert s['gateway']['available'] and s['gateway']['ok'], s['gateway']
assert s['vault']['available'] and s['vault']['enrolled'] and s['vault']['principal']=='user:maluos', s['vault']
assert s['me']['enrolled'] and s['me']['principal']=='user:maluos', s['me']
assert s['host']['memory'] and s['host']['memory']['tenant'], s['host']
assert s['host']['variant']=='Desktop', s['host']
print('  ok   session state: gateway ok (%d backends), vault and gateway see user:maluos, memory tenant %s' % (len(s['gateway']['backends']), s['host']['memory']['tenant']))" || { echo "  FAIL session state: $(state | head -c 400)"; fail=1; }
# slice 5: the session's view of updates (read in its own thread; the apt cache takes minutes to open under
# emulation, so wait for the first reading), and UpdateAction refresh
upd_avail() { state | python3 -c "import json,sys; u=json.load(sys.stdin).get('updates') or {}; sys.exit(0 if u.get('available') else 1)"; }
for i in $(seq 1 60); do upd_avail && break; sleep 10; done
state | python3 -c "
import json,sys; s=json.load(sys.stdin); u=s.get('updates') or {}
assert u.get('available'), u
assert u['automatic'].get('enabled') and u['reboot_required'] is False, u
print('  ok   session state carries updates: %d pending (%d security, %d automatic), lists refreshed %s' % (u['pending_count'], u['security_count'], u['automatic_count'], u.get('lists_refreshed')))" || { echo "  FAIL session updates state: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin).get("updates"))' | head -c 300)"; fail=1; }
read0=$(state | python3 -c "import json,sys; print((json.load(sys.stdin).get('updates') or {}).get('read_at') or 0)")
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.UpdateAction refresh >/dev/null 2>&1
for i in $(seq 1 60); do state | python3 -c "import json,sys; u=json.load(sys.stdin)['updates']; sys.exit(0 if u.get('available') and u['read_at'] > $read0 else 1)" && break; sleep 10; done
state | python3 -c "import json,sys; u=json.load(sys.stdin)['updates']; assert u.get('available') and u['read_at'] > $read0, u" && echo "  ok   UpdateAction refresh re-reads maluctl update status (in the updates thread)" || { echo "  FAIL UpdateAction refresh"; fail=1; }
state | python3 -c "import json,sys; s=json.load(sys.stdin); assert s['gateway']['ok'] and s['vault']['enrolled'], 'stale'" && echo "  ok   the poll loop kept publishing meanwhile" || { echo "  FAIL session state stale during the updates read"; fail=1; }
sudo -n maluctl agent create desk --exec /usr/lib/maluos/maluos-agent-idle --scope org:read --no-start >/dev/null 2>&1 && echo "  ok   agent desk created, not started" || { echo "  FAIL agent create desk"; fail=1; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.Refresh >/dev/null 2>&1; sleep 4
agent_is() { state | python3 -c "import json,sys; s=json.load(sys.stdin); a=[x for x in s['agents'] if x['name']=='desk']; sys.exit(0 if a and a[0]['active']=='$1' else 1)"; }
agent_is inactive && echo "  ok   session sees agent desk: inactive" || { echo "  FAIL session agents: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["agents"])')"; fail=1; }
sudo -n systemctl start maluos-agent@desk
for i in $(seq 1 15); do agent_is active && break; sleep 2; done
agent_is active && echo "  ok   session saw the unit start (systemd JobRemoved -> refresh)" || { echo "  FAIL session did not see desk start: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["agents"])')"; fail=1; }
# slice 8: the agent icons (the session runs maluos-agents --sync when the set of agents changes) and the Agents app
for i in $(seq 1 20); do [ -f ~/.local/share/applications/maluos-agent-local-desk.desktop ] && break; sleep 2; done
grep -q '^Exec=maluos-agents --agent local:desk$' ~/.local/share/applications/maluos-agent-local-desk.desktop 2>/dev/null && echo "  ok   launcher for agent desk written by the session (maluos-agents --sync)" || { echo "  FAIL agent launcher: $(ls ~/.local/share/applications/ 2>&1 | tr '\n' ' ')"; fail=1; }
[ -f ~/Desktop/Agents/maluos-agent-local-desk.desktop ] && echo "  ok   ~/Desktop/Agents holds the same launcher" || { echo "  FAIL Desktop/Agents: $(ls ~/Desktop/Agents 2>&1)"; fail=1; }
gsettings get org.gnome.desktop.app-folders folder-children 2>/dev/null | grep -q "'maluos-agents'" && gsettings get org.gnome.desktop.app-folders.folder:/org/gnome/desktop/app-folders/folders/maluos-agents/ apps 2>/dev/null | grep -q 'maluos-agent-local-desk.desktop' && echo "  ok   the Agents app folder in the grid lists the launcher" || { echo "  FAIL app folder: $(gsettings get org.gnome.desktop.app-folders folder-children 2>&1)"; fail=1; }
maluctl agent card desk 2>&1 | grep -q 'does not accept tasks' && echo "  ok   maluctl agent card desk: the idle agent serves no task interface (clean refusal)" || { echo "  FAIL agent card desk: $(maluctl agent card desk 2>&1 | tail -1)"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-agents --agent local:desk --self-test 2>&1); echo "$out" | grep -q 'self-test ok: Agents: service reachable, 1 local agents, 0 office agents, no office, selected local:desk' && echo "  ok   Agents window (WebKitGTK) builds from the live state, the UI reports ready, agent desk selected" || { echo "  FAIL maluos-agents self-test: $(echo "$out" | tail -4)"; fail=1; }
sudo -n systemctl stop maluos-agent@desk
for i in $(seq 1 15); do agent_is inactive && break; sleep 2; done
agent_is inactive && echo "  ok   session saw the unit stop" || { echo "  FAIL session did not see desk stop"; fail=1; }
sleep 2; sj=$(sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null)
echo "$sj" | grep -q "notify: Agent desk created" && echo "$sj" | grep -q "notify: Agent desk is running" && echo "$sj" | grep -q "notify: Agent desk stopped" && echo "  ok   notifications: created, running, stopped" || { echo "  FAIL notifications missing:"; echo "$sj" | grep notify | tail -5; fail=1; }
! echo "$sj" | grep -q "notification failed" && echo "  ok   notifications delivered to the shell" || { echo "  FAIL notification delivery:"; echo "$sj" | grep "notification failed" | tail -3; fail=1; }
# --- slice 3: ownership, the owner's polkit rule, vault grant requests answered from the session, the Desk window
sudo -n maluctl agent show desk | grep -q 'owner:       user:maluos' && echo "  ok   agent desk is owned by the sudo user by default" || { echo "  FAIL agent owner: $(sudo -n maluctl agent show desk | grep owner)"; fail=1; }
sudo -n test -f /etc/polkit-1/rules.d/60-maluos-agent-desk.rules && echo "  ok   polkit rule for the owner's session" || { echo "  FAIL no polkit rule"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select owner_principal_ref from maluos.maluos_agent where name='desk' and removed_at is null" | grep -q 'user:maluos' && echo "  ok   registry row maluos_agent with the owner" || { echo "  FAIL registry row"; fail=1; }
systemctl start maluos-agent@desk 2>/tmp/pk.err && sleep 2 && systemctl is-active --quiet maluos-agent@desk && systemctl stop maluos-agent@desk && echo "  ok   the owner starts and stops the agent without sudo (polkit rule)" || { echo "  FAIL owner unit control: $(cat /tmp/pk.err)"; fail=1; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.Refresh >/dev/null 2>&1; sleep 4
state | python3 -c "import json,sys; s=json.load(sys.stdin); a=[x for x in s['agents'] if x['name']=='desk'][0]; assert a['mine'] and a['owner']=='user:maluos', a; print('  ok   session marks desk as yours (owner user:maluos)')" || { echo "  FAIL session ownership"; fail=1; }
echo desk-secret-value | maluctl secret add deskkey --stdin >/dev/null && echo "  ok   user secret deskkey stored" || { echo "  FAIL secret add"; fail=1; }
sudo -n maluctl agent run desk -- maluctl secret show user:maluos/deskkey 2>&1 | grep -q 'grant request #' && echo "  ok   the agent's refusal files a grant request" || { echo "  FAIL refusal did not file a request: $(sudo -n maluctl agent run desk -- maluctl secret show user:maluos/deskkey 2>&1)"; fail=1; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.Refresh >/dev/null 2>&1; sleep 4
rid=$(state | python3 -c "import json,sys; s=json.load(sys.stdin); r=[x for x in s['vault'].get('requests') or [] if x['requester']=='agent:desk' and x['mine_to_decide']]; print(r[0]['id'] if r else '')")
[ -n "$rid" ] && echo "  ok   session sees the pending request #$rid for the user's secret" || { echo "  FAIL session requests: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["vault"].get("requests"))')"; fail=1; }
sleep 2; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: Agent desk asks for user:maluos/deskkey' && echo "  ok   notification: Agent desk asks for user:maluos/deskkey" || { echo "  FAIL request notification missing"; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | grep notify | tail -3; fail=1; }
[ -n "$rid" ] && gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.RequestDecide "$rid" approve 7d | grep -q approved && echo "  ok   RequestDecide approve over the session bus" || { echo "  FAIL RequestDecide"; fail=1; }
maluctl secret info user:maluos/deskkey | grep -q 'read  principal:agent:desk' && echo "  ok   the grant exists for agent:desk" || { echo "  FAIL grant missing: $(maluctl secret info user:maluos/deskkey | tail -3)"; fail=1; }
[ "$(sudo -n maluctl agent run desk -- maluctl secret show user:maluos/deskkey 2>/dev/null)" = desk-secret-value ] && echo "  ok   the agent now reads the key" || { echo "  FAIL agent still refused"; fail=1; }
maluctl secret requests --all | grep -q 'approved by user:maluos' && echo "  ok   maluctl secret requests shows the decision" || { echo "  FAIL requests listing"; fail=1; }
# slice 9: a reveal with re-authentication; polkit authorises a root subject without a prompt, so the allowed path is checked as root
[ -f /usr/share/polkit-1/actions/com.maluos.vault.policy ] && grep -q '<allow_active>auth_self</allow_active>' /usr/share/polkit-1/actions/com.maluos.vault.policy && echo "  ok   polkit action com.maluos.vault.reveal shipped (auth_self: the person's own password)" || { echo "  FAIL vault polkit action"; fail=1; }
[ "$(sudo -n maluctl secret show user:maluos/deskkey --reauth 2>/dev/null)" = desk-secret-value ] && echo "  ok   a reveal with --reauth as root passes polkit (uid 0 is authorised) and prints the value" || { echo "  FAIL root reveal with reauth: $(sudo -n maluctl secret show user:maluos/deskkey --reauth 2>&1 | tail -1)"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='secret.read' and secret_name='deskkey' and status='ok' and linux_uid=0 and detail->>'reauth'='polkit'" | grep -qE '^[1-9]' && echo "  ok   ledger: the reveal carries detail.reauth = polkit" || { echo "  FAIL reauth ledger detail"; sudo -n -u postgres psql -Atd maludb -c "select linux_uid, status, reason, detail from maluos.maluos_ledger where secret_name='deskkey' order by ledger_id desc limit 3"; fail=1; }
# slice 9: an agent over budget notifies its owner by name (the alert row names the agent and carries the owner);
# the mock backend is started again so a rung exists for the call to be budgeted against
sudo -n systemd-run --quiet --unit maluos-mock-ollama-3 -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_gateway.mock_ollama --port 11999
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:11999/api/tags >/dev/null 2>&1 && break; sleep 1; done
for i in $(seq 1 30); do sudo -n maluctl gateway reload >/dev/null 2>&1; maluctl gateway status | grep -q 'backend:     mock  mock .* healthy' && break; sleep 2; done
sudo -n maluctl gateway price set mock '*' --input 999999 --output 999999 >/dev/null 2>&1 && sudo -n maluctl gateway policy set --principal agent:desk --budget usd_per_day=0.001 >/dev/null 2>&1
sudo -n systemctl start maluos-agent@desk; sleep 1
sudo -n maluctl agent run desk -- maluctl gateway chat "budget check" --model fast 2>&1 | grep -q 'budget.*exhausted' && echo "  ok   agent desk over its budget: the call is refused (budget_exceeded)" || { echo "  FAIL budget refusal: $(sudo -n maluctl agent run desk -- maluctl gateway chat 'budget check' --model fast 2>&1 | tail -1)"; echo "       prices: $(sudo -n maluctl gateway price list 2>&1 | tr '\n' ' ')"; echo "       policy: $(sudo -n maluctl gateway catalog 2>&1 | grep 'agent:desk')"; echo "       route: $(maluctl gateway routes 2>&1 | head -2 | tr '\n' ' ')"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='alert.budget_exceeded' and principal_ref='agent:desk' and detail->>'agent'='desk' and detail->>'owner'='user:maluos'" | grep -qE '^[1-9]' && echo "  ok   the alert row names the agent and carries its owner (user:maluos)" || { echo "  FAIL alert row: $(sudo -n -u postgres psql -Atd maludb -c "select reason, detail from maluos.maluos_ledger where event like 'alert.%' order by ledger_id desc limit 2")"; fail=1; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.Refresh >/dev/null 2>&1; sleep 5
sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: Agent desk: budget exhausted (day)' && echo "  ok   notification: Agent desk: budget exhausted (day), to the owner" || { echo "  FAIL owner budget notification"; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | grep -i 'notify\|alert' | tail -4; fail=1; }
state | python3 -c "import json,sys; s=json.load(sys.stdin); a=[x for x in s['alerts'] if x.get('agent')=='desk' and x.get('owner')=='user:maluos' and x['kind']=='budget_exceeded']; assert a, s['alerts'][:3]; print('  ok   session state lists the alert under the agent (alerts[].agent, owner)')" || { echo "  FAIL alert in state"; fail=1; }
sudo -n maluctl gateway policy set --principal agent:desk --budget none >/dev/null 2>&1; sudo -n maluctl gateway price set mock '*' --input 0 --output 0 >/dev/null 2>&1
sudo -n systemctl stop maluos-agent@desk; sudo -n systemctl stop maluos-mock-ollama-3 2>/dev/null
[ -f /usr/share/applications/com.maluos.Desk.desktop ] && [ -x /usr/bin/maluos-desk ] && echo "  ok   MaluOS Desk installed" || { echo "  FAIL maluos-desk missing"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-desk --self-test 2>&1); echo "$out" | grep -q 'self-test ok: MaluOS Desk: service reachable' && echo "  ok   MaluOS Desk window builds from the live state (GTK 4 on the session's Wayland display)" || { echo "  FAIL maluos-desk self-test: $(echo "$out" | tail -3)"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-desk --window updates --self-test 2>&1); echo "$out" | grep -q 'self-test ok: Upgrade Manager: service reachable.*pages updates, automatic, history, release.*automatic updates on' && echo "  ok   Upgrade Manager window builds from the live state (switches read automatic updates on)" || { echo "  FAIL upgrade manager self-test: $(echo "$out" | tail -3)"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-desk --window tools --self-test 2>&1); echo "$out" | grep -q 'self-test ok: Tools Installer: service reachable' && echo "  ok   Tools Installer window builds from the live state" || { echo "  FAIL tools installer self-test: $(echo "$out" | tail -3)"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-desk --window vault --self-test 2>&1); echo "$out" | grep -q 'self-test ok: Credential Manager: service reachable' && echo "  ok   Credential Manager window builds from the live state" || { echo "  FAIL credential manager self-test: $(echo "$out" | tail -3)"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-desk --window apps --self-test 2>&1); echo "$out" | grep -q 'self-test ok: MaluApps: service reachable' && echo "  ok   MaluApps window builds from the live state" || { echo "  FAIL maluapps self-test: $(echo "$out" | tail -3)"; fail=1; }
# --- slice 6: desk enrolment against a mock office (the contract in docs/desk-enrolment.md)
installed maluos-desk && echo "  ok   maluos-desk" || { echo "  FAIL maluos-desk"; fail=1; }
sudo -n systemd-run --quiet --unit maluos-mock-office -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_desk.mock_office --port 18080 --code boot-code --name "Mock Office" --models office-7b,office-embed --heartbeat-s 30
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:18080/api/v1/health >/dev/null 2>&1 && break; sleep 1; done
curl -fsS --max-time 5 http://127.0.0.1:18080/api/v1/health | grep -q '"office": "Mock Office"' && echo "  ok   mock office up" || { echo "  FAIL mock office"; sudo -n journalctl -u maluos-mock-office --no-pager | tail -5; fail=1; }
! sudo -n maluctl office enroll http://127.0.0.1:18080 --code wrong-code >/dev/null 2>&1 && echo "  ok   a wrong code is refused" || { echo "  FAIL enrolment with a wrong code succeeded"; fail=1; }
out=$(sudo -n maluctl office enroll http://127.0.0.1:18080 --code boot-code --name "Test desk" 2>&1); echo "$out" | grep -q "enrolled: desk 'Test desk' (#41) at Mock Office for user:maluos" && echo "  ok   sudo maluctl office enroll (one-time code, the sudo user owns the desk)" || { echo "  FAIL office enroll: $out"; fail=1; }
! sudo -n maluctl office enroll http://127.0.0.1:18080 --code boot-code >/dev/null 2>&1 && echo "  ok   the code cannot be used twice" || { echo "  FAIL code reuse"; fail=1; }
grep -q '^url: http://127.0.0.1:18080$' /etc/maluos/office.yaml && grep -q 'principal: user:maluos' /etc/maluos/office.yaml && ! grep -q 'desk_' /etc/maluos/office.yaml && echo "  ok   /etc/maluos/office.yaml records the office, the owner and no token" || { echo "  FAIL office.yaml: $(cat /etc/maluos/office.yaml | head -c 300)"; fail=1; }
grep -q 'MALUOS_OFFICE_RECORDS_MCP="http://127.0.0.1:18080/mcp/records"' /etc/maluos/office.env && grep -q 'MALUOS_OFFICE_TOKEN_SECRET="office-desk-token"' /etc/maluos/office.env && echo "  ok   /etc/maluos/office.env names the office's endpoints for agents" || { echo "  FAIL office.env"; fail=1; }
# slice 7: MaluApps from the office's catalogue (endpoints.apps), the public one unreachable here
MALUOS_APPS_PUBLIC_URL=http://127.0.0.1:1/catalog.json maluctl office apps --refresh > /tmp/apps.txt 2>&1 && [ "$(grep -c ' web    office ' /tmp/apps.txt)" = 4 ] && grep -q '^  helpdesk .*available' /tmp/apps.txt && echo "  ok   maluctl office apps lists the mock office's four apps (public catalogue unreachable, office wins)" || { echo "  FAIL office apps: $(cat /tmp/apps.txt | head -4)"; fail=1; }
MALUOS_APPS_PUBLIC_URL=http://127.0.0.1:1/catalog.json maluctl office apps install helpdesk >/dev/null 2>&1 && grep -q '^Exec=firefox --new-window http://127.0.0.1:18080/apps/helpdesk$' ~/.local/share/applications/maluapp-helpdesk.desktop && maluctl office apps --json --compact | python3 -c "import json,sys; c=json.load(sys.stdin); a=[x for x in c['apps'] if x['id']=='helpdesk'][0]; assert a['installed'] and a['source']=='office', a" && echo "  ok   apps install helpdesk: a launcher opening the office's app in its own Firefox window" || { echo "  FAIL apps install helpdesk"; fail=1; }
MALUOS_APPS_PUBLIC_URL=http://127.0.0.1:1/catalog.json maluctl office apps remove helpdesk >/dev/null 2>&1 && [ ! -f ~/.local/share/applications/maluapp-helpdesk.desktop ] && echo "  ok   apps remove helpdesk takes the launcher away" || { echo "  FAIL apps remove"; fail=1; }
# slice 9: the public catalogue is signed; a throwaway key stands in for the release key (MALUOS_APPS_KEYRING)
export GNUPGHOME=$HOME/.gnupg-cat; mkdir -p "$GNUPGHOME" ~/cat && chmod 700 "$GNUPGHOME"
gpg --batch --quiet --passphrase '' --quick-gen-key "Boot Test Catalogue <cat@test.invalid>" default default never >/dev/null 2>&1 && gpg --batch --export > ~/cat/keyring.gpg
printf '{"schema": 1, "apps": [{"id": "pubtool", "name": "Public Tool", "description": "a public app", "kind": "web", "url": "https://example.invalid/tool", "version": "1"}]}' > ~/cat/catalog.json
gpg --batch --quiet --passphrase '' --armor --detach-sign -o ~/cat/catalog.json.asc ~/cat/catalog.json; unset GNUPGHOME
systemd-run --user --quiet --unit boot-test-catalog python3 -m http.server 18081 --bind 127.0.0.1 --directory "$HOME/cat" 2>/dev/null; sleep 1
catapps() { MALUOS_APPS_PUBLIC_URL=http://127.0.0.1:18081/catalog.json MALUOS_APPS_KEYRING=$HOME/cat/keyring.gpg maluctl office apps --json --compact --refresh 2>/dev/null; }
catapps | python3 -c "import json,sys; c=json.load(sys.stdin); a=[x for x in c['apps'] if x['id']=='pubtool']; assert a and a[0]['source']=='public' and a[0]['available'] and not c.get('errors'), (c.get('errors'), [x['id'] for x in c['apps']]); print('  ok   a public catalogue with a good signature is accepted (gpgv against the keyring)')" || { echo "  FAIL signed catalogue: $(catapps | head -c 300)"; fail=1; }
sed -i 's/Public Tool/Evil Tool/' ~/cat/catalog.json
catapps | python3 -c "import json,sys; c=json.load(sys.stdin); assert any('signature invalid' in e and 'refused' in e for e in c.get('errors') or []), c.get('errors'); assert not any(x.get('name')=='Evil Tool' for x in c['apps']); print('  ok   a tampered catalogue is refused (signature invalid) and its apps are not listed')" || { echo "  FAIL tampered catalogue: $(catapps | head -c 300)"; fail=1; }
rm -f ~/cat/catalog.json.asc
catapps | python3 -c "import json,sys; c=json.load(sys.stdin); assert any('unsigned' in e for e in c.get('errors') or []), c.get('errors'); print('  ok   an unsigned catalogue is refused')" || { echo "  FAIL unsigned catalogue: $(catapps | head -c 300)"; fail=1; }
systemctl --user stop boot-test-catalog 2>/dev/null; rm -rf ~/cat ~/.gnupg-cat; rm -f ~/.cache/maluos-apps/catalog.json
maluctl secret list | grep -q 'user:maluos/office-desk-token' && [ "$(maluctl secret show office-desk-token | cut -c1-5)" = desk_ ] && echo "  ok   the desk token is in the owner's vault compartment (kind token)" || { echo "  FAIL desk token in the vault: $(maluctl secret list)"; fail=1; }
maluctl office status | grep -q 'desk:       Test desk  (#41)' && maluctl office status | grep -q 'gateway:    backend office, tier office, --model office' && echo "  ok   maluctl office status" || { echo "  FAIL office status: $(maluctl office status 2>&1)"; fail=1; }
for i in $(seq 1 30); do maluctl gateway status | grep -q 'backend:     office  openai_compat .* healthy' && break; sudo -n maluctl gateway reload >/dev/null 2>&1; sleep 2; done
maluctl gateway status | grep -q 'backend:     office  openai_compat .* healthy' && echo "  ok   the office is a healthy rung of this desk's gateway" || { echo "  FAIL office backend: $(maluctl gateway status | grep 'backend:')"; fail=1; }
maluctl gateway chat "hello office" --model office 2>/dev/null | grep -q 'office reply to: hello office' && echo "  ok   chat through --model office (the desk token applied by the gateway)" || { echo "  FAIL office chat"; maluctl gateway chat "hello office" --model office; maluctl gateway routes | head -3; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='secret.use' and principal_ref='user:maluos' and broker_ref='user:maluos-gateway' and secret_name='office-desk-token'" | grep -qE '^[1-9]' && echo "  ok   vault ledger: the desk token used by the gateway on the owner's behalf" || { echo "  FAIL secret.use row for the desk token"; fail=1; }
curl -fsS --max-time 5 http://127.0.0.1:18080/mock/state | python3 -c "import json,sys; s=json.load(sys.stdin); c=s['chats']; assert c and c[-1]['desk_id']==41 and c[-1]['model']=='office-7b', c; print('  ok   the mock office ledgered the call for desk #41 (%s)' % c[-1]['model'])" || { echo "  FAIL mock chats"; fail=1; }
! sudo -n -u edward maluctl gateway chat "x" --model office >/dev/null 2>&1 && echo "  ok   another user cannot use the desk's office rung (no token, no delegation)" || { echo "  FAIL ungranted office use"; fail=1; }
# slice 9: that refusal filed a grant request for the owner with its cause (the call), the owner decides it with parameters
maluctl secret requests | grep -E 'office-desk-token +user:edward +use .* office@office' >/dev/null && echo "  ok   the gateway's refused lookup filed a request for user:maluos from user:edward with its cause (--model office)" || { echo "  FAIL request with cause: $(maluctl secret requests 2>&1 | tail -2)"; fail=1; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.Refresh >/dev/null 2>&1; sleep 4
crid=$(state | python3 -c "import json,sys; s=json.load(sys.stdin); r=[x for x in s['vault'].get('requests') or [] if x['requester']=='user:edward' and x['mine_to_decide'] and (x.get('cause') or {}).get('model')=='office' and x['cause'].get('backend')=='office' and x['cause'].get('call')]; print(r[0]['id'] if r else '')")
[ -n "$crid" ] && echo "  ok   session state: request #$crid carries its cause (model office, backend office, the call id)" || { echo "  FAIL cause in state: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["vault"].get("requests"))' | head -c 300)"; fail=1; }
sleep 2; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: Principal edward asks for user:maluos/office-desk-token — for --model office (office) at ' && echo "  ok   notification names the call: for --model office (office) at HH:MM" || { echo "  FAIL cause notification"; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | grep 'notify: Principal' | tail -2; fail=1; }
[ -n "$crid" ] && gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.RequestDecide "$crid" approve '{"expires": "30d", "level": "use", "budget": {"usd_per_day": 10}}' | grep -q approved && echo "  ok   RequestDecide with parameters (use, a month, 10 USD/day) over the session bus" || { echo "  FAIL RequestDecide with parameters"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select level || ' ' || (budget->>'usd_per_day') || ' ' || (g.expires_at > now() + interval '29 days')::text from maluos.maluos_secret_grant g join maluos.maluos_secret s using (secret_id) where s.name='office-desk-token' and g.grantee_ref='user:edward' and g.revoked_at is null" | grep -q '^use 10 true$' && echo "  ok   the vault holds the grant with level use, a budget of 10 a day and a month's expiry" || { echo "  FAIL grant parameters: $(sudo -n -u postgres psql -Atd maludb -c "select g.level, g.budget, g.expires_at from maluos.maluos_secret_grant g join maluos.maluos_secret s using (secret_id) where s.name='office-desk-token' and g.grantee_ref='user:edward' and g.revoked_at is null")"; fail=1; }
sudo -n -u edward maluctl gateway chat "edward at the office" --model office 2>/dev/null | grep -q 'office reply to: edward at the office' && echo "  ok   the granted person now reaches the office's models through the owner's token" || { echo "  FAIL granted office use: $(sudo -n -u edward maluctl gateway chat x --model office 2>&1 | tail -1)"; fail=1; }
maluctl secret revoke office-desk-token --to user:edward >/dev/null 2>&1
maluctl secret delegate --to agent:desk --secret office-desk-token --expires 1h >/dev/null && sudo -n maluctl gateway policy set --principal agent:desk --cloud yes --egress internal >/dev/null \
  && sudo -n maluctl agent run desk -- maluctl gateway chat "agent at the office" --model office 2>/dev/null | grep -q 'office reply to: agent at the office' && echo "  ok   a delegated agent (egress internal) reaches the office's models through the gateway" || { echo "  FAIL agent delegation to the office rung"; sudo -n maluctl agent run desk -- maluctl gateway chat "agent" --model office; fail=1; }
sudo -n maluctl agent run desk -- sh -c 'echo "$MALUOS_OFFICE_URL $MALUOS_OFFICE_DESK_ID"' | grep -q '^http://127.0.0.1:18080 41$' && echo "  ok   the agent's environment carries the office (office.env)" || { echo "  FAIL agent office env: $(sudo -n maluctl agent run desk -- env | grep MALUOS_OFFICE)"; fail=1; }
maluctl secret grant office-desk-token --to agent:desk --level read >/dev/null 2>&1; sudo -n maluctl agent run desk -- sh -c 'curl -fsS --max-time 5 -H "Authorization: Bearer $(maluctl secret show office-desk-token)" -H "Content-Type: application/json" "$MALUOS_OFFICE_RECORDS_MCP" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"office.ping\",\"arguments\":{}}}"' 2>/dev/null | grep -q 'pong from Mock Office (records) for person@mock.office at desk #41' && echo "  ok   an agent granted read on the token reaches the office's records MCP as the owner" || { echo "  FAIL agent MCP call to the office"; fail=1; }
maluctl office heartbeat | grep -q 'ok: desk Test desk (#41) online' && echo "  ok   maluctl office heartbeat as the owner" || { echo "  FAIL office heartbeat: $(maluctl office heartbeat 2>&1)"; fail=1; }
office_is() { state | python3 -c "import json,sys; o=json.load(sys.stdin).get('office') or {}; sys.exit(0 if o.get('enrolled') and o.get('presence')=='$1' else 1)"; }
for i in $(seq 1 24); do office_is online && break; sleep 5; done
office_is online && state | python3 -c "import json,sys; o=json.load(sys.stdin)['office']; assert o['desk']['id']==41 and o['office']['name']=='Mock Office' and o['gateway']=='office' and o['endpoints']['records'] and o['endpoints']['models']==['office-7b','office-embed'], o; print('  ok   session state: office %s, desk #%d online, --model %s' % (o['office']['name'], o['desk']['id'], o['gateway']))" || { echo "  FAIL session office state: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin).get("office"))' | head -c 400)"; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | grep office | tail -5; fail=1; }
# slice 8: the office's agents (endpoints.agents), their task interface and activity, the icons and the Agents app
maluctl office agents --refresh 2>&1 | grep -q '^  helpdesk .*helpdesk.triage' && [ "$(maluctl office agents | grep -c online)" = 2 ] && echo "  ok   maluctl office agents lists the mock office's two agents" || { echo "  FAIL office agents: $(maluctl office agents 2>&1 | tail -3)"; fail=1; }
maluctl office agent helpdesk send "hello from the desk" 2>/dev/null | grep -q '^office agent helpdesk reply to: hello from the desk$' && echo "  ok   maluctl office agent helpdesk send: a task to an office agent with the desk token" || { echo "  FAIL office agent send: $(maluctl office agent helpdesk send hello 2>&1 | tail -2)"; fail=1; }
maluctl office agent helpdesk activity 2>/dev/null | grep -q 'task .* completed: hello from the desk' && echo "  ok   maluctl office agent helpdesk activity shows the task" || { echo "  FAIL office agent activity: $(maluctl office agent helpdesk activity 2>&1 | tail -2)"; fail=1; }
# slice 9: the office's page for an agent, requested with the desk token as the Agents app does, signs the person in
curl -s --max-time 5 -H "Authorization: Bearer $(maluctl secret show office-desk-token)" http://127.0.0.1:18080/agents/helpdesk | grep -q 'signed in as person@mock.office at desk #41' && echo "  ok   the office's agent page answers \"signed in as person@mock.office\" to the desk token" || { echo "  FAIL office page sign-in"; fail=1; }
curl -s --max-time 5 http://127.0.0.1:18080/agents/helpdesk | grep -q 'not signed in' && echo "  ok   without the token the page is anonymous" || { echo "  FAIL anonymous office page"; fail=1; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.OfficeAction heartbeat >/dev/null 2>&1
for i in $(seq 1 24); do state | python3 -c "import json,sys; o=json.load(sys.stdin).get('office') or {}; sys.exit(0 if len(o.get('agents') or [])==2 else 1)" && break; sleep 5; done
state | python3 -c "import json,sys; o=json.load(sys.stdin)['office']; a=o.get('agents') or []; assert sorted(x['id'] for x in a)==['helpdesk','research'], a; print('  ok   session state carries the office agents after the heartbeat')" || { echo "  FAIL office agents in state: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["office"].get("agents_error"))')"; fail=1; }
state | python3 -c "import json,sys; o=json.load(sys.stdin)['office']; p=o.get('apps') or {}; assert p.get('count')==4, p; print('  ok   session re-read the MaluApps catalogue after the heartbeat: %d apps (office.apps)' % p['count'])" || { echo "  FAIL office.apps in state: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["office"].get("apps"))')"; fail=1; }
for i in $(seq 1 20); do [ -f ~/.local/share/applications/maluos-agent-office-helpdesk.desktop ] && break; sleep 2; done
grep -q '^Exec=maluos-agents --agent office:helpdesk$' ~/.local/share/applications/maluos-agent-office-helpdesk.desktop 2>/dev/null && [ -f ~/Desktop/Agents/maluos-agent-office-research.desktop ] && echo "  ok   launchers for the office agents written (grid folder and ~/Desktop/Agents)" || { echo "  FAIL office agent launchers: $(ls ~/.local/share/applications/ | grep maluos-agent | tr '\n' ' ')"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-agents --self-test 2>&1); echo "$out" | grep -q 'self-test ok: Agents: service reachable, 1 local agents, 2 office agents at Mock Office' && echo "  ok   Agents window lists the local and the office agents" || { echo "  FAIL maluos-agents self-test with the office: $(echo "$out" | tail -4)"; fail=1; }
curl -fsS --max-time 5 http://127.0.0.1:18080/mock/state | python3 -c "import json,sys; s=json.load(sys.stdin); d=[x for x in s['desks'] if x['id']==41][0]; hb=[h for h in s['heartbeats'] if h['desk_id']==41]; assert d['presence']=='online' and len(hb)>=2 and d['facts'].get('cpu_cores'), (d, hb); print('  ok   the office sees the desk online (%d heartbeats, facts: %s cores, %s MB)' % (len(hb), d['facts'].get('cpu_cores'), d['facts'].get('memory_mb')))" || { echo "  FAIL office presence"; fail=1; }
sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: This desk joined Mock Office' && echo "  ok   notification: This desk joined Mock Office" || { echo "  FAIL join notification"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-desk --self-test 2>&1); echo "$out" | grep -q 'office Mock Office' && echo "  ok   MaluOS Desk renders the Office group" || { echo "  FAIL desk self-test office line: $(echo "$out" | tail -2)"; fail=1; }
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/retire -d '{"desk_id": 41}' >/dev/null
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.OfficeAction heartbeat >/dev/null 2>&1
for i in $(seq 1 24); do office_is retired && break; sleep 5; done
office_is retired && echo "  ok   the office retired the desk: the session sees it (410 on the next heartbeat)" || { echo "  FAIL retired state: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin).get("office"))' | head -c 300)"; fail=1; }
sleep 2; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: The office retired this desk' && echo "  ok   notification: The office retired this desk" || { echo "  FAIL retire notification"; fail=1; }
! maluctl office heartbeat >/dev/null 2>&1 && maluctl office status | grep -q 'RETIRED by the office' && echo "  ok   maluctl office status reports the retirement" || { echo "  FAIL status after retire: $(maluctl office status 2>&1 | tail -2)"; fail=1; }
sudo -n maluctl office leave | grep -q 'left Mock Office' && [ ! -f /etc/maluos/office.yaml ] && [ ! -f /etc/maluos/office.env ] && ! maluctl secret list | grep -q office-desk-token && ! maluctl gateway status | grep -q 'backend:     office' && echo "  ok   sudo maluctl office leave removed the files, the token and the gateway rung" || { echo "  FAIL office leave"; ls /etc/maluos/office.* 2>&1; maluctl secret list; fail=1; }
for i in $(seq 1 12); do state | python3 -c "import json,sys; o=json.load(sys.stdin).get('office') or {}; sys.exit(1 if o.get('enrolled') else 0)" && break; sleep 5; done
state | python3 -c "import json,sys; o=json.load(sys.stdin).get('office') or {}; assert not o.get('enrolled'), o" && echo "  ok   session state: no office after leave" || { echo "  FAIL session still enrolled"; fail=1; }
for i in $(seq 1 20); do [ ! -f ~/.local/share/applications/maluos-agent-office-helpdesk.desktop ] && break; sleep 2; done
[ ! -f ~/.local/share/applications/maluos-agent-office-helpdesk.desktop ] && [ ! -f ~/Desktop/Agents/maluos-agent-office-research.desktop ] && [ -f ~/Desktop/Agents/maluos-agent-local-desk.desktop ] && echo "  ok   the office agents' icons went with the enrolment; the local one stays" || { echo "  FAIL icons after leave: $(ls ~/Desktop/Agents 2>&1 | tr '\n' ' ')"; fail=1; }
sudo -n systemctl stop maluos-mock-office 2>/dev/null
maluctl secret delete user:maluos/deskkey >/dev/null 2>&1 || true
sudo -n maluctl agent remove desk --purge >/dev/null 2>&1 || true
fi
sudo -n maluctl status | sed 's/^/  maluctl: /'
exit $fail
REMOTE
rc=${PIPESTATUS[0]}
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'sudo -n poweroff' 2>/dev/null || true; sleep 3
[ "$rc" = 0 ] && echo "PASS: $(basename "$IMG") boots and runs the MaluDB stack" || { echo "FAIL (see $WORK)"; exit 1; }
