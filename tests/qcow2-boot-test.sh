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
sudo -n systemd-run --quiet --unit maluos-mock-ollama-2 -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_gateway.mock_ollama --port 11999
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
else echo "  (no maluos-business-os in this image)"; fi
# --- the desktop (Phase 12): GNOME on gdm, the MaluOS identity on the login screen, no snaps
if installed maluos-desktop; then
for p in maluos-desktop maluos-desktop-branding gdm3 gnome-shell ubuntu-session gnome-control-center nautilus ptyxis epiphany-browser; do installed $p && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }; done
for p in snapd firefox update-manager update-notifier ubuntu-release-upgrader-gtk ubuntu-report whoopsie apport; do ! installed $p && echo "  ok   no $p" || { echo "  FAIL $p is installed"; fail=1; }; done
[ "$(systemctl get-default)" = graphical.target ] && echo "  ok   default target graphical" || { echo "  FAIL default target is $(systemctl get-default)"; fail=1; }
systemctl is-active --quiet gdm && echo "  ok   gdm active" || { echo "  FAIL gdm: $(systemctl is-active gdm)"; sudo -n journalctl -u gdm --no-pager | tail -8; fail=1; }
for i in $(seq 1 60); do pgrep -x gnome-shell >/dev/null && break; sleep 5; done   # the greeter under software rendering
pgrep -x gnome-shell >/dev/null && echo "  ok   gnome-shell running as $(ps -o user= -p "$(pgrep -x gnome-shell | head -1)") (the greeter)" || { echo "  FAIL no gnome-shell process"; sudo -n journalctl -b --no-pager | grep -iE 'gnome-shell|gdm' | tail -15; fail=1; }
grep -q '^VARIANT="Desktop"' /etc/os-release && echo "  ok   os-release VARIANT=Desktop" || { echo "  FAIL os-release variant: $(grep ^VARIANT= /etc/os-release)"; fail=1; }
grep -q '^Name=MaluOS' /usr/share/wayland-sessions/ubuntu.desktop && echo "  ok   session entry says MaluOS" || { echo "  FAIL session entry still Ubuntu"; fail=1; }
[ -f /usr/share/backgrounds/maluos/maluos-dark.png ] && [ -f /usr/share/pixmaps/maluos-logo-text.svg ] && [ -f /usr/share/icons/hicolor/scalable/apps/maluos-logo.svg ] && echo "  ok   wallpaper, login logo and distributor icon present" || { echo "  FAIL branding assets missing"; fail=1; }
grep -aq maluos-logo-text /usr/share/glib-2.0/schemas/gschemas.compiled && echo "  ok   gsettings overrides compiled" || { echo "  FAIL gschemas.compiled lacks the MaluOS override"; fail=1; }
logo=$(dbus-run-session -- gsettings get org.gnome.login-screen logo 2>/dev/null); echo "$logo" | grep -q maluos-logo-text && echo "  ok   login screen logo is MaluOS" || { echo "  FAIL login screen logo: ${logo:-unreadable}"; fail=1; }
bg=$(XDG_CURRENT_DESKTOP=ubuntu:GNOME dbus-run-session -- gsettings get org.gnome.desktop.background picture-uri-dark 2>/dev/null); echo "$bg" | grep -q maluos-dark && echo "  ok   session background is the MaluOS wallpaper" || echo "  warn session background: ${bg:-unreadable}"
grep -q 'file:///usr/share/backgrounds/maluos' /usr/share/glib-2.0/schemas/20_maluos-desktop.gschema.override && echo "  ok   desktop override file shipped" || { echo "  FAIL override file"; fail=1; }
systemctl is-active --quiet NetworkManager && echo "  ok   NetworkManager active" || echo "  warn NetworkManager: $(systemctl is-active NetworkManager)"

# --- the agent-aware session (Phase 12 slice 2): auto-login into the MaluOS session, the indicator, the session service
installed maluos-desktop-session && echo "  ok   maluos-desktop-session" || { echo "  FAIL maluos-desktop-session"; fail=1; }
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
sudo -n maluctl agent create desk --exec /usr/lib/maluos/maluos-agent-idle --scope org:read --no-start >/dev/null 2>&1 && echo "  ok   agent desk created, not started" || { echo "  FAIL agent create desk"; fail=1; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.Refresh >/dev/null 2>&1; sleep 4
agent_is() { state | python3 -c "import json,sys; s=json.load(sys.stdin); a=[x for x in s['agents'] if x['name']=='desk']; sys.exit(0 if a and a[0]['active']=='$1' else 1)"; }
agent_is inactive && echo "  ok   session sees agent desk: inactive" || { echo "  FAIL session agents: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["agents"])')"; fail=1; }
sudo -n systemctl start maluos-agent@desk
for i in $(seq 1 15); do agent_is active && break; sleep 2; done
agent_is active && echo "  ok   session saw the unit start (systemd JobRemoved -> refresh)" || { echo "  FAIL session did not see desk start: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["agents"])')"; fail=1; }
sudo -n systemctl stop maluos-agent@desk
for i in $(seq 1 15); do agent_is inactive && break; sleep 2; done
agent_is inactive && echo "  ok   session saw the unit stop" || { echo "  FAIL session did not see desk stop"; fail=1; }
sleep 2; sj=$(sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null)
echo "$sj" | grep -q "notify: Agent desk created" && echo "$sj" | grep -q "notify: Agent desk is running" && echo "$sj" | grep -q "notify: Agent desk stopped" && echo "  ok   notifications: created, running, stopped" || { echo "  FAIL notifications missing:"; echo "$sj" | grep notify | tail -5; fail=1; }
! echo "$sj" | grep -q "notification failed" && echo "  ok   notifications delivered to the shell" || { echo "  FAIL notification delivery:"; echo "$sj" | grep "notification failed" | tail -3; fail=1; }
sudo -n maluctl agent remove desk --purge >/dev/null 2>&1 || true
fi
sudo -n maluctl status | sed 's/^/  maluctl: /'
exit $fail
REMOTE
rc=${PIPESTATUS[0]}
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'sudo -n poweroff' 2>/dev/null || true; sleep 3
[ "$rc" = 0 ] && echo "PASS: $(basename "$IMG") boots and runs the MaluDB stack" || { echo "FAIL (see $WORK)"; exit 1; }
