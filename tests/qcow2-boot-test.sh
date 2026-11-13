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
# The server image carries the Business OS kernel but its component ships off (firstboot.yaml
# components.maludb-os-core enabled: false; the installer's First boot screen or the plan turns it
# on). The boot test asks for it the way a plan would, before maluos-firstboot runs (After=cloud-config):
# a bootcmd line, the first of the seed's bootcmd list (BOS_SEED_ON=0 leaves the component off).
DESKTOP_SEED=""; BOOTCMD=""; BOS_SEED_ON=${BOS_SEED_ON:-1}
case "$(basename "$IMG")" in *server*) [ "$BOS_SEED_ON" = 1 ] && BOOTCMD="  - [sh, -c, \"sed -i '/^  maludb-os-core:/,/^  [a-z]/ s/^    enabled: false/    enabled: true/' /etc/maluos/firstboot.yaml\"]
";; esac
# The desktop image logs the test user straight into the MaluOS session, so the shell extension and the
# session service run as a real user (Phase 12 slice 2). The session must not idle-lock during the long
# server checks: GNOME disables extensions on the lock screen. A dconf system database set before gdm starts.
case "$(basename "$IMG")" in *desktop*) DESKTOP_SEED="write_files:
  - path: /etc/gdm3/custom.conf
    content: |
      [daemon]
      AutomaticLoginEnable=true
      AutomaticLogin=maluos
"; BOOTCMD="$BOOTCMD  - [sh, -c, \"mkdir -p /etc/dconf/profile /etc/dconf/db/local.d; printf 'user-db:user\\nsystem-db:local\\n' > /etc/dconf/profile/user; printf '[org/gnome/desktop/session]\\nidle-delay=uint32 0\\n[org/gnome/desktop/screensaver]\\nlock-enabled=false\\n' > /etc/dconf/db/local.d/00-boot-test; dconf update\"]
";; esac
# The Business OS's applications (the maluos-apps proposal, phase 1): with the kernel component on, its default installs
# four applications cloned and built from github.com/maludb at first boot, which takes long under TCG and needs the
# network. The seed sets apps.install: [] unless BOOT_TEST_APPS=1 (the dev host, under KVM): then the first boot installs the
# four defaults, gets two hours more, and the checks below cover each application.
BOOT_TEST_APPS=${BOOT_TEST_APPS:-0}
[ "$BOOT_TEST_APPS" = 1 ] && FIRSTBOOT_TIMEOUT=${FIRSTBOOT_TIMEOUT:-9600}
# The office behind a proxy (docs/phase13-estate-behind-a-proxy.md, part 2): the server seed asks for scheme https with
# proxy_address 10.0.2.2 (QEMU's user-network gateway stands in for the proxy as the VM sees it), so first boot writes the
# kernel's names to it in /etc/hosts and never to loopback; the checks below read the file. BOOT_TEST_PROXY=0 keeps http.
BOOT_TEST_PROXY=${BOOT_TEST_PROXY:-1}; PROXY_ADDR=10.0.2.2
SEEDPY="import os, yaml; p='/etc/maluos/firstboot.yaml'; c=(yaml.safe_load(open(p)) if os.path.exists(p) else None) or {}; k=c.setdefault('components', {}).setdefault('maludb-os-core', {})"
[ "$BOOT_TEST_APPS" = 1 ] || SEEDPY="$SEEDPY; k['apps']={'install': []}"
case "$(basename "$IMG")" in *server*) [ "$BOOT_TEST_PROXY" = 1 ] && SEEDPY="$SEEDPY; k['scheme']='https'; k['proxy_address']='$PROXY_ADDR'";; esac
# The database on another server (docs/phase14-database-server.md, slice 1): after every other check, a second
# PostgreSQL cluster on the same VM is made a database server by the real first-boot code (port 5433, TLS, clients by
# address) and the office is provisioned against it, as the admin role; then the VM's own cluster is stopped and the
# office must still work. The seed leaves a marker for the checks (the heredoc below cannot see this script's
# variables). BOOT_TEST_DBSERVER=0 skips it (about half an hour under TCG).
BOOT_TEST_DBSERVER=${BOOT_TEST_DBSERVER:-1}
case "$(basename "$IMG")" in *server*) [ "$BOOT_TEST_DBSERVER" = 1 ] && SEEDPY="$SEEDPY; c['boot_test']={'database_server': True}";; esac
BOOTCMD="$BOOTCMD  - [python3, -c, \"$SEEDPY; open(p, 'w').write(yaml.safe_dump(c, sort_keys=False))\"]
"
cat > user-data <<UD
#cloud-config
hostname: maluos-test
users:
  - name: maluos
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat testkey.pub)
$DESKTOP_SEED${BOOTCMD:+bootcmd:
$BOOTCMD}
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
# --- Phase 13 G1: the GPU facts (no GPU in CI: an empty list, the chassis a vm, the rule "always")
maluctl gpu status --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['gpus']==[] and d['chassis']=='vm' and d['contribution_rule']=='always', d; print('  ok   maluctl gpu status --json: no GPU, chassis vm, rule always')" || { echo "  FAIL maluctl gpu status: $(maluctl gpu status 2>&1 | tail -2)"; fail=1; }
maluctl gpu status | grep -q '^no GPU on this host (chassis: vm' && echo "  ok   maluctl gpu status (text)" || { echo "  FAIL maluctl gpu status text: $(maluctl gpu status | head -2)"; fail=1; }
# --- the inference gateway (Phase 6 slice 2): real daemon, mock backend (no GPU in CI)
dpkg-query -W -f='${Status}' maluos-gateway 2>/dev/null | grep -q 'install ok installed' && echo "  ok   maluos-gateway" || { echo "  FAIL maluos-gateway"; fail=1; }
systemctl is-active --quiet maluos-gateway.socket && echo "  ok   maluos-gateway.socket active" || { echo "  FAIL maluos-gateway.socket: $(systemctl is-active maluos-gateway.socket)"; sudo -n journalctl -u maluos-gateway --no-pager | tail -8; fail=1; }
maluctl gateway whoami | grep -q '"principal": "user:maluos"' && echo "  ok   gateway identifies the login user (peer credentials)" || { echo "  FAIL gateway whoami"; maluctl gateway whoami; sudo -n journalctl -u maluos-gateway --no-pager | tail -8; fail=1; }
maluctl gateway share | grep -q '^share:       on (by the chassis rule)  contribution always  chassis vm' && echo "  ok   maluctl gateway share: on by the chassis rule (a vm counts as a server), not exposed" || { echo "  FAIL gateway share: $(maluctl gateway share 2>&1)"; fail=1; }
sudo -n maluctl gateway share off >/dev/null 2>&1 && maluctl gateway share | grep -q '^share:       off  contribution always' && sudo -n maluctl gateway share on --when idle >/dev/null 2>&1 && maluctl gateway share | grep -q '^share:       on  contribution idle' && echo "  ok   maluctl gateway share off / on --when idle recorded in gateway.yaml and reported by the status" || { echo "  FAIL gateway share switch: $(maluctl gateway share 2>&1)"; fail=1; }
maluctl gateway status | grep -q 'backend:     ollama-local' && echo "  ok   seeded catalogue: ollama-local backend ($(maluctl gateway status | grep -o 'ollama-local.*' | grep -o 'healthy\|down' | head -1 || echo unchecked), no Ollama installed)" || { echo "  FAIL catalogue not seeded"; maluctl gateway status; fail=1; }
sudo -n maluctl gateway share on --when always >/dev/null 2>&1      # slice 3: `--when idle` contributes only while the session's idle mark is up; the checks below call with keys
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
# Phase 13 G2 (docs/inference-node-api.md): keys, the node API over a live TCP listener, the Anthropic face, an async job, unexpose
NODEKEY=$(sudo -n maluctl gateway key issue --name boot-manager --kind node 2>/dev/null); DESKKEY=$(sudo -n maluctl gateway key issue --name boot-desk --class interactive --cloud-allowed no 2>/dev/null)
[ "${NODEKEY#mg_}" != "$NODEKEY" ] && [ "${DESKKEY#mg_}" != "$DESKKEY" ] && sudo -n maluctl gateway key list | grep -qE 'boot-desk +inference +interactive +no' && echo "  ok   maluctl gateway key issue: a node key and an inference key (principal key:boot-desk with its policy)" || { echo "  FAIL key issue: $(sudo -n maluctl gateway key list 2>&1 | tail -3)"; fail=1; }
sudo -n maluctl gateway expose --bind 127.0.0.1 --port 11435 2>&1 | grep -q 'tcp listener on 127.0.0.1:11435' && curl -s http://127.0.0.1:11435/node/v1/health | grep -q '"ok": true' && echo "  ok   maluctl gateway expose opens the TCP listener live (no restart); /node/v1/health answers without a key" || { echo "  FAIL expose: $(sudo -n maluctl gateway expose --bind 127.0.0.1 --port 11435 2>&1 | tail -2)"; fail=1; }
curl -s -H "Authorization: Bearer $NODEKEY" http://127.0.0.1:11435/node/v1/status | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["api_version"]==1 and len(d["node_id"])==36 and d["machine"]["chassis"]=="vm" and d["lanes"]["ollama-local"]["kind"]=="local" and d["lanes"]["mock"]["kind"]=="local" and d["share"]["enabled"] and d["exposed"]["port"]==11435, d; print("  ok   node API status with the node key: envelope, machine (chassis vm), lanes, the sharing switch")' || { echo "  FAIL node status: $(curl -s -H "Authorization: Bearer $NODEKEY" http://127.0.0.1:11435/node/v1/status | head -c 300)"; fail=1; }
curl -s -H "Authorization: Bearer $DESKKEY" -H 'Content-Type: application/json' http://127.0.0.1:11435/v1/chat/completions -d '{"model":"fast","messages":[{"role":"user","content":"by key"}]}' | grep -q 'mock reply to: by key' && sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='model.call' and principal_ref='key:boot-desk' and detail->>'token'='boot-desk' and status='ok'" | grep -qE '^[1-9]' && echo "  ok   an inference key's call over TCP, ledgered under key:boot-desk" || { echo "  FAIL key call: $(curl -s -H "Authorization: Bearer $DESKKEY" -H 'Content-Type: application/json' http://127.0.0.1:11435/v1/chat/completions -d '{"model":"fast","messages":[{"role":"user","content":"by key"}]}' | head -c 300)"; fail=1; }
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $DESKKEY" http://127.0.0.1:11435/node/v1/status | grep -q 403 && curl -s -H "Authorization: Bearer $NODEKEY" -H 'Content-Type: application/json' http://127.0.0.1:11435/v1/chat/completions -d '{"model":"fast","messages":[{"role":"user","content":"x"}]}' | grep -q node_key && echo "  ok   an inference key cannot open the node API; a node key serves no inference" || { echo "  FAIL key kinds"; fail=1; }
curl -s -H "Authorization: Bearer $NODEKEY" "http://127.0.0.1:11435/node/v1/runs?key=boot-desk" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d["runs"][-1]; assert r["principal"]=="key:boot-desk" and r["face"]=="openai" and r["lane"]=="mock" and r["seq"]>0, r; print("  ok   node API runs: the ledger as run records with since_seq")' || { echo "  FAIL node runs"; fail=1; }
curl -sS --unix-socket /run/maluos/gateway.sock -H 'Content-Type: application/json' http://g/v1/messages -d '{"model":"fast","max_tokens":20,"messages":[{"role":"user","content":"anthropic"}]}' | grep -q '"type": "message"' && curl -sS --unix-socket /run/maluos/gateway.sock -H 'Content-Type: application/json' http://g/v1/messages -d '{"model":"fast","max_tokens":20,"stream":true,"messages":[{"role":"user","content":"anthropic stream"}]}' | grep -q '^event: message_stop' && echo "  ok   the Anthropic face (/v1/messages): a message and the event stream" || { echo "  FAIL anthropic face"; fail=1; }
JID=$(curl -sS --unix-socket /run/maluos/gateway.sock -H 'Content-Type: application/json' -H 'X-Node-Mode: async' http://g/v1/chat/completions -d '{"model":"fast","messages":[{"role":"user","content":"async"}]}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])' 2>/dev/null)
for i in $(seq 1 20); do curl -sS --unix-socket /run/maluos/gateway.sock http://g/v1/jobs/$JID 2>/dev/null | grep -q '"status": "done"' && break; sleep 1; done
curl -sS --unix-socket /run/maluos/gateway.sock http://g/v1/jobs/$JID | grep -q 'mock reply to: async' && maluctl gateway jobs | grep -q "$JID" && echo "  ok   an async job (202, /v1/jobs/ID, the result in the face's shape, maluctl gateway jobs)" || { echo "  FAIL async job $JID: $(curl -sS --unix-socket /run/maluos/gateway.sock http://g/v1/jobs/$JID | head -c 200)"; fail=1; }
sudo -n maluctl gateway node status | grep -q 'lane:        mock  local' && sudo -n maluctl gateway node queue >/dev/null && maluctl gateway share | grep -q 'tcp on 127.0.0.1:11435 only' && echo "  ok   maluctl gateway node status/queue; share reports the listener" || { echo "  FAIL maluctl node: $(sudo -n maluctl gateway node status 2>&1 | tail -2)"; fail=1; }
sudo -n maluctl gateway unexpose 2>&1 | grep -q 'tcp listener off' && ! curl -s -m 2 http://127.0.0.1:11435/node/v1/health >/dev/null 2>&1 && sudo -n maluctl gateway key revoke boot-desk | grep -q revoked && echo "  ok   unexpose closes the listener live; key revoke" || { echo "  FAIL unexpose"; fail=1; }
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
# --- Phase 13 slice 1: a server node of the estate (maluos-estate against the mock office; no desk needed, both profiles)
if installed maluos-estate; then
installed maluos-estate && echo "  ok   maluos-estate" || { echo "  FAIL maluos-estate"; fail=1; }
FAKEPUB=$(python3 -c 'import sys; sys.path.insert(0, "/usr/lib/maluos"); from maluos_estate import overlay as OV; print(OV.genkey()[1])')   # slice 1b: a fake spoke, so the hub under test has a peer
sudo -n systemd-run --quiet --unit maluos-mock-estate -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_estate.mock_office --port 18082 --node-code srv-code --name "Mock Estate" --heartbeat-s 30 --node-heartbeat-s 10 --report-s 10 --overlay-spoke fake=$FAKEPUB
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:18082/api/v1/health >/dev/null 2>&1 && break; sleep 1; done
out=$(sudo -n maluctl estate join http://127.0.0.1:18082 --code srv-code --name srv-node --kind inference --hub 127.0.0.1:51820 2>&1); echo "$out" | grep -q "joined: inference 'srv-node' (#57) at Mock Estate as host:$(hostname)" && echo "  ok   sudo maluctl estate join --kind inference: node #57 as host:$(hostname)" || { echo "  FAIL estate join (server): $out"; fail=1; }
sudo -n -u maluos-estate maluctl secret whoami 2>/dev/null | grep -q "principal:  host:$(hostname)" && sudo -n grep -q "maluos-estate: host:$(hostname)" /etc/maluos/vault.yaml && sudo -n grep -q "maluos-estate: host:$(hostname)" /etc/maluos/gateway.yaml && echo "  ok   vault.yaml and gateway.yaml map maluos-estate to host:$(hostname); the vault identifies it so" || { echo "  FAIL host identity: $(sudo -n -u maluos-estate maluctl secret whoami 2>&1 | head -2)"; fail=1; }
sudo -n -u maluos-estate maluctl estate report --json 2>/dev/null | python3 -c "import json,sys; r=json.load(sys.stdin); assert r['gateway']['ok'] and r['vault']['ok'] and isinstance(r['vault']['alerts'], list) and r['disk'][0]['mount']=='/' and any(u['unit']=='postgresql@18-main.service' and u['active']=='active' for u in r['units']) and not r['errors'], r; print('  ok   the report as the node (maluos-estate): the gateway and the vault answer the host principal, no errors')" || { echo "  FAIL report as the node: $(sudo -n -u maluos-estate maluctl estate report 2>&1 | tail -4)"; fail=1; }
srv_node() { curl -fsS --max-time 5 http://127.0.0.1:18082/mock/nodes | python3 -c "import json,sys; d=json.load(sys.stdin); n=[x for x in d['nodes'] if x['id']==57][0]; a=d['alerts']; sys.exit(0 if ($1) else 1)" 2>/dev/null; }
for i in $(seq 1 30); do srv_node "n['presence']=='online' and n['last_report_at']" && break; sleep 2; done
srv_node "n['presence']=='online' and n['last_report_at'] and n['kind']=='inference' and n['health'] in ('ok','warning') and n['gateway']['ok']" && echo "  ok   the office has the inference node online with its report (maluos-estate.service)" || { echo "  FAIL node at the office: $(curl -s http://127.0.0.1:18082/mock/nodes | head -c 300); $(sudo -n journalctl -u maluos-estate --no-pager | tail -3)"; fail=1; }
sudo -n maluctl estate nodes | grep -q 'estate of Mock Estate as node #57: 1 nodes, 1 online' && echo "  ok   maluctl estate nodes as root: the node sees its estate" || { echo "  FAIL estate nodes: $(sudo -n maluctl estate nodes 2>&1 | tail -2)"; fail=1; }
# slice 1b: this host is the hub of the estate's network; maluos-overlay made the interface, peered the fake spoke, wrote the names
echo "$out" | grep -q 'overlay:  100.100.0.1/16 as srv-node.internal, hub listening on udp 51820' && echo "  ok   join --hub: the overlay key sent, 100.100.0.1/16 as srv-node.internal, the hub" || { echo "  FAIL join --hub overlay line: $(echo "$out" | grep overlay)"; fail=1; }
for i in $(seq 1 30); do ip -br addr show estate 2>/dev/null | grep -q '100.100.0.1/16' && break; sleep 2; done
ip -br addr show estate 2>/dev/null | grep -q '100.100.0.1/16' && systemctl is-active --quiet maluos-overlay && echo "  ok   maluos-overlay.service made the estate interface with 100.100.0.1/16" || { echo "  FAIL overlay interface: $(ip -br addr show estate 2>&1); $(systemctl is-active maluos-overlay); $(sudo -n journalctl -u maluos-overlay --no-pager | tail -5)"; fail=1; }
sudo -n wg show estate 2>/dev/null | grep -q "peer: $FAKEPUB" && sudo -n wg show estate | grep -q 'allowed ips: 100.100.0.2/32' && sudo -n wg show estate | grep -q 'listening port: 51820' && echo "  ok   wg: listening on 51820, the fake spoke peered at 100.100.0.2/32" || { echo "  FAIL wg show: $(sudo -n wg show estate 2>&1 | head -8)"; fail=1; }
[ "$(sysctl -n net.ipv4.conf.estate.forwarding 2>/dev/null)" = 1 ] && echo "  ok   forwarding on the estate interface only" || { echo "  FAIL forwarding: $(sysctl -n net.ipv4.conf.estate.forwarding 2>&1)"; fail=1; }
grep -qP '^100\.100\.0\.1\tsrv-node\.internal$' /etc/hosts && grep -qP '^100\.100\.0\.2\tfake\.internal$' /etc/hosts && getent hosts fake.internal | grep -q 100.100.0.2 && echo "  ok   the names: srv-node.internal and fake.internal resolve (the hosts block)" || { echo "  FAIL hosts block: $(grep -A3 'overlay begin' /etc/hosts)"; fail=1; }
maluctl estate overlay status | grep -q 'interface:  estate  up  100.100.0.1/16  srv-node.internal  (hub)' && maluctl estate overlay peers | grep -q 'peer  fake' && echo "  ok   maluctl estate overlay status and peers" || { echo "  FAIL overlay status: $(maluctl estate overlay status 2>&1 | head -4)"; fail=1; }
sudo -n -u maluos-estate maluctl estate report --json 2>/dev/null | python3 -c "import json,sys; r=json.load(sys.stdin); o=r['overlay']; assert o['configured'] and o['role']=='hub' and o['address']=='100.100.0.1' and o['peers'][0]['name']=='fake', o; print('  ok   the report carries the overlay (configured, hub, the peer)')" || { echo "  FAIL report overlay"; fail=1; }
# the hub endpoint as a setting (docs/phase13-estate-behind-a-proxy.md, decision 2): released (the interface goes, the office has no hub), taken back (the service remakes it, the fake spoke peered, the names back)
sudo -n maluctl estate overlay hub off | grep -q 'released: the estate has no hub' && ! ip link show estate >/dev/null 2>&1 && curl -fsS --max-time 5 http://127.0.0.1:18082/mock/overlay | python3 -c "import json,sys; o=json.load(sys.stdin); assert o['hub'] is None and o['hub_endpoint'] is None, o" && echo "  ok   maluctl estate overlay hub off: the role released at the office, the interface down" || { echo "  FAIL overlay hub off: $(sudo -n maluctl estate overlay hub off 2>&1 | tail -2); $(ip -br link show estate 2>&1); $(curl -s http://127.0.0.1:18082/mock/overlay | head -c 200)"; fail=1; }
sudo -n maluctl estate overlay hub 127.0.0.1:51820 | grep -q 'this host is the hub at 127.0.0.1:51820' || { echo "  FAIL overlay hub claim: $(sudo -n maluctl estate overlay hub 127.0.0.1:51820 2>&1 | tail -2)"; fail=1; }
for i in $(seq 1 30); do ip -br addr show estate 2>/dev/null | grep -q '100.100.0.1/16' && sudo -n wg show estate 2>/dev/null | grep -q "peer: $FAKEPUB" && grep -q 'fake.internal' /etc/hosts && break; sleep 2; done
ip -br addr show estate 2>/dev/null | grep -q '100.100.0.1/16' && sudo -n wg show estate | grep -q 'listening port: 51820' && sudo -n wg show estate | grep -q "peer: $FAKEPUB" && grep -qP '^100\.100\.0\.2\tfake\.internal$' /etc/hosts && maluctl estate overlay status | grep -q 'srv-node.internal  (hub)' && echo "  ok   maluctl estate overlay hub HOST:PORT: the hub again; the service remade the interface, the fake spoke peered, the names back" || { echo "  FAIL overlay hub claim: $(ip -br addr show estate 2>&1); $(sudo -n wg show estate 2>&1 | head -4); $(sudo -n journalctl -u maluos-overlay --no-pager | tail -4)"; fail=1; }
OVKEY=$(sudo -n maluctl gateway key issue --name ov-test --kind node 2>/dev/null)
sudo -n maluctl gateway expose --bind overlay --port 11436 >/dev/null 2>&1 && sudo -n maluctl gateway reload >/dev/null 2>&1
for i in $(seq 1 20); do curl -fsS --max-time 2 -H "Authorization: Bearer $OVKEY" http://100.100.0.1:11436/node/v1/health >/dev/null 2>&1 && break; sleep 1; done
curl -fsS --max-time 3 -H "Authorization: Bearer $OVKEY" http://100.100.0.1:11436/node/v1/health 2>/dev/null | grep -q '"ok"' && ! curl -fsS --max-time 3 http://127.0.0.1:11436/node/v1/health >/dev/null 2>&1 && echo "  ok   maluctl gateway expose --bind overlay: the node API answers on 100.100.0.1 and not on the loopback" || { echo "  FAIL expose --bind overlay: $(curl -sS --max-time 3 -H "Authorization: Bearer $OVKEY" http://100.100.0.1:11436/node/v1/health 2>&1 | head -c 200); $(sudo -n journalctl -u maluos-gateway --no-pager | grep -i 'tcp listener' | tail -2)"; fail=1; }
sudo -n maluctl gateway unexpose >/dev/null 2>&1; sudo -n maluctl gateway reload >/dev/null 2>&1
# slice 2 (both profiles): the daemon registers the node's agents in the directory; a task from the office with a valid envelope runs through the agent's socket and comes back with its provenance; a tampered one is refused by the agent
sudo -n systemd-run --quiet --unit maluos-mock-ollama-4 -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_gateway.mock_ollama --port 11999   # helper is the demo agent: it answers through the gateway, so a rung must be healthy
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:11999/api/tags >/dev/null 2>&1 && break; sleep 1; done
for i in $(seq 1 30); do sudo -n maluctl gateway reload >/dev/null 2>&1; maluctl gateway status | grep -q 'backend:     mock  mock .* healthy' && break; sleep 2; done
sudo -n maluctl agent create helper --exec "/usr/bin/python3 /usr/lib/maluos/maluos-agent-demo.py" --scope org:read --tiers fast --capability chat --accept-from org --max-classification internal >/dev/null 2>&1 \
  && sudo -n grep -q 'accept_from:' /etc/maluos/agents/helper.manifest.yaml && echo "  ok   maluctl agent create helper --capability chat --accept-from org: the manifest and the policy written" || { echo "  FAIL agent create helper: $(sudo -n maluctl agent create helper --exec /bin/true 2>&1 | tail -2)"; fail=1; }
srv_dir() { curl -fsS --max-time 5 http://127.0.0.1:18082/mock/delegation | python3 -c "import json,sys; d=json.load(sys.stdin); ag=[a for a in d['agents'] if a['status']=='active']; sys.exit(0 if ($1) else 1)" 2>/dev/null; }
for i in $(seq 1 45); do srv_dir "any(a['name']=='helper' and a['capabilities']==['chat'] and a['accept_from']==['org'] for a in ag)" && break; sleep 2; done
srv_dir "any(a['name']=='helper' and a['capabilities']==['chat'] and a['accept_from']==['org'] and a['node']['id']==57 for a in ag)" && echo "  ok   the daemon registered helper in the directory (capability chat, accepts org) through the agents hint" || { echo "  FAIL directory: $(curl -s http://127.0.0.1:18082/mock/delegation | head -c 400)"; fail=1; }
sudo -n maluctl estate agents | grep -q 'helper .*srv-node .*chat' && echo "  ok   maluctl estate agents as root (the node token): helper on srv-node" || { echo "  FAIL estate agents: $(sudo -n maluctl estate agents 2>&1 | head -3)"; fail=1; }
sudo -n maluctl estate keys | grep -q '^coordinator' && sudo -n maluctl estate keys | grep -q 'inference:57' && [ -f /run/maluos/estate/keys.json ] && echo "  ok   maluctl estate keys: the coordinator's and this node's; the daemon's cache in /run/maluos/estate/keys.json" || { echo "  FAIL estate keys: $(sudo -n maluctl estate keys 2>&1 | head -3); $(ls -la /run/maluos/estate/ 2>&1)"; fail=1; }
for i in $(seq 1 30); do [ -S /run/maluos/agents/helper/tasks.sock ] && break; sleep 2; done
srv_inj() { curl -fsS --max-time 70 -X POST http://127.0.0.1:18082/mock/task -d "$1" | python3 -c 'import json,sys; t=json.load(sys.stdin)["task"]; print(t["state"], t.get("reason") or "", t["id"], (t.get("provenance") or {}).get("node") or "", (t.get("provenance") or {}).get("agent") or "", len((t.get("provenance") or {}).get("models") or []))' 2>/dev/null; }
r=$(srv_inj '{"agent":"helper","sign":"valid","text":"Say pong.","wait":60}'); echo "$r" | grep -q '^completed  t_[0-9a-f]* inference:57 agent:helper [1-9]' && echo "  ok   a task from the office (a valid envelope): leased to this node, run by helper through the gateway, completed with provenance (inference:57, agent:helper, a model call)" || { echo "  FAIL office task: $r; $(sudo -n journalctl -u maluos-estate --no-pager 2>/dev/null | tail -3); $(sudo -n journalctl -u maluos-agent@helper --no-pager 2>/dev/null | tail -3)"; fail=1; }
TID=$(echo "$r" | awk '{print $2}')
sudo -n maluctl estate tasks "$TID" | grep -q 'completed' && sudo -n maluctl estate tasks "$TID" | grep -q 'chain user:mock > agent:helper; 1 model call' && echo "  ok   maluctl estate tasks ID: the record with its chain" || { echo "  FAIL estate tasks: $(sudo -n maluctl estate tasks "$TID" 2>&1 | head -4)"; fail=1; }
ENVID=$(curl -fsS --max-time 5 http://127.0.0.1:18082/mock/delegation | python3 -c "import json,sys; print([t['envelope_id'] for t in json.load(sys.stdin)['tasks'] if t['id']=='$TID'][0])" 2>/dev/null)
sudo -n maluctl gateway usage --envelope "$ENVID" 2>/dev/null | grep -q 'internal' && sudo -n maluctl gateway usage --envelope "$ENVID" | grep -q '1 call(s) under envelope' && echo "  ok   maluctl gateway usage --envelope: the ledger row of the task's model call, sensitivity internal" || { echo "  FAIL usage --envelope $ENVID: $(sudo -n maluctl gateway usage --envelope "$ENVID" 2>&1 | tail -3)"; fail=1; }
srv_inj '{"agent":"helper","sign":"tampered","text":"x","wait":40}' | grep -q '^refused bad_signature' && sudo -n journalctl -u maluos-agent@helper --no-pager 2>/dev/null | grep -q 'refused (bad_signature)' && echo "  ok   a tampered envelope: the agent refuses bad_signature (in its journal), the office records the refusal" || { echo "  FAIL tampered: $(sudo -n journalctl -u maluos-agent@helper --no-pager 2>/dev/null | tail -3)"; fail=1; }
sudo -n maluctl agent remove helper --purge >/dev/null 2>&1
for i in $(seq 1 45); do srv_dir "not any(a['name']=='helper' for a in ag)" && break; sleep 2; done
srv_dir "not any(a['name']=='helper' for a in ag)" && echo "  ok   agent remove: helper left the directory (the hint)" || { echo "  FAIL directory after remove"; fail=1; }
sudo -n systemctl stop maluos-mock-ollama-4 2>/dev/null
# --- Phase 13 slice 3 (both profiles, the node side; docs/phase13-slice3-inference.md): the heartbeat carries the gateway's facts and the mock publishes them; the join stored the
# inference key the office issued; a fake GPU host the mock publishes becomes a rung of this gateway; a fake peer calls this host over the overlay with its inference key
sudo -n systemd-run --quiet --unit maluos-mock-ollama-7 -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_gateway.mock_ollama --port 11999
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:11999/api/tags >/dev/null 2>&1 && break; sleep 1; done
for i in $(seq 1 30); do sudo -n maluctl gateway reload >/dev/null 2>&1; maluctl gateway status | grep -q 'backend:     mock  mock .* healthy' && break; sleep 2; done
sudo -n maluctl gateway share on --when always >/dev/null 2>&1
sudo -n maluctl gateway expose --bind overlay --port 11436 >/dev/null 2>&1 && sudo -n maluctl gateway reload >/dev/null 2>&1     # the facts report the listener's port (slice 2 left 11436 in the conf)
sudo -n -u maluos-estate maluctl secret list 2>/dev/null | grep -q "host:$(hostname)/estate-inference-key" && sudo -n -u maluos-estate maluctl secret info estate-inference-key 2>/dev/null | grep -q 'user:maluos-gateway' && echo "  ok   the join stored the inference key the office issued beside the node token, with a use grant to the gateway" || { echo "  FAIL inference key: $(sudo -n -u maluos-estate maluctl secret list 2>&1 | tail -3); $(sudo -n -u maluos-estate maluctl secret info estate-inference-key 2>&1 | tail -4)"; fail=1; }
sudo -n maluctl estate heartbeat --json 2>/dev/null | grep -q '"ok": true' || echo "  warn estate heartbeat: $(sudo -n maluctl estate heartbeat 2>&1 | tail -1)"
srv_inf() { curl -fsS --max-time 5 http://127.0.0.1:18082/mock/inference | python3 -c "import json,sys; d=json.load(sys.stdin); f=d['facts'].get('inference:57') or {}; sys.exit(0 if ($1) else 1)" 2>/dev/null; }
for i in $(seq 1 30); do srv_inf "f.get('share') and any(m['name']=='mock-7b' for m in f.get('models') or [])" && break; sleep 2; done
srv_inf "f.get('share') and f.get('port')==11436 and any(m['name']=='mock-7b' for m in f.get('models') or []) and 'interactive' in f.get('expected_wait_s', {})" && echo "  ok   the node's heartbeat carries its gateway's inference facts (share on, port 11436, the mock's models, the expected wait); /mock/inference shows them" || { echo "  FAIL inference facts at the office: $(curl -s http://127.0.0.1:18082/mock/inference | python3 -c 'import json,sys; f=json.load(sys.stdin)["facts"].get("inference:57") or {}; print({k: f.get(k) for k in ("share","contribution","port","exposed","expected_wait_s")}, [m["name"] for m in f.get("models") or []])' 2>&1); $(sudo -n journalctl -u maluos-estate --no-pager | tail -3)"; fail=1; }
PEER=$(curl -fsS --max-time 5 -X POST http://127.0.0.1:18082/mock/peer -d '{"name":"gpu-fake","kind":"inference","address":"100.100.0.9","inference":{"models":[{"name":"qwen3:8b","loaded":true}],"queue":{"queued":0,"running":0},"expected_wait_s":{"interactive":1.2,"agent":3,"batch":10},"share":true,"contribution":"always","port":11435}}')
PEERKEY=$(echo "$PEER" | python3 -c 'import json,sys; print(json.load(sys.stdin)["inference_key"])' 2>/dev/null)
out=$(sudo -n maluctl estate inference --refresh 2>&1); echo "$out" | grep -q 'gpu-fake .*100.100.0.9:11435 .*qwen3:8b' && echo "$out" | grep -q 'peers:     [1-9]' && sudo -n test -f /run/maluos/estate/inference.json && sudo -n test -f /run/maluos/estate/peers.json && echo "  ok   maluctl estate inference --refresh: the directory's backends (gpu-fake at 100.100.0.9:11435) and the peers cached for the gateway under /run/maluos/estate" || { echo "  FAIL estate inference --refresh: $out; $(ls -la /run/maluos/estate/ 2>&1)"; fail=1; }
for i in $(seq 1 20); do maluctl gateway estate 2>/dev/null | grep -q 'estate:gpu-fake' && break; sudo -n maluctl gateway reload >/dev/null 2>&1; sleep 2; done
maluctl gateway estate | grep -q 'backend:     estate:gpu-fake  inference:-100  http://100.100.0.9:11435 .* models qwen3:8b .* ceiling internal' && maluctl gateway estate | grep -q 'peers:       [1-9]' && maluctl gateway status | grep -q 'estate:      inference:57  1 backend(s) from the directory' && echo "  ok   maluctl gateway estate: the rung estate:gpu-fake from the directory (dialled over the overlay with this host's inference key), the peers who may call here" || { echo "  FAIL gateway estate: $(maluctl gateway estate 2>&1 | head -4); $(sudo -n journalctl -u maluos-gateway --no-pager | grep -i estate | tail -3)"; fail=1; }
# the serving side: the fake peer calls this host over the overlay (100.100.0.1:11436, exposed above) with its inference key (the peers cache names it)
for i in $(seq 1 20); do curl -fsS --max-time 2 -H "Authorization: Bearer $PEERKEY" http://100.100.0.1:11436/v1/maluos/whoami >/dev/null 2>&1 && break; sleep 1; done
curl -fsS --max-time 3 -H "Authorization: Bearer $PEERKEY" http://100.100.0.1:11436/v1/maluos/whoami 2>/dev/null | grep -q '"principal": "node:inference:-100"' && echo "  ok   a peer's inference key opens this host over the overlay as node:inference:-100 (verified against the peers cache; no key crossed by hand)" || { echo "  FAIL peer whoami: $(curl -sS --max-time 3 -H "Authorization: Bearer $PEERKEY" http://100.100.0.1:11436/v1/maluos/whoami 2>&1 | head -c 200)"; fail=1; }
curl -s --max-time 60 -H "Authorization: Bearer $PEERKEY" -H 'Content-Type: application/json' -H 'X-MaluOS-Envelope: env_fedcba9876543210' -H 'X-MaluOS-Origin-Request: mg-peer-0001' -H 'X-MaluOS-Origin-Node: 00000000-0000-4000-8000-000000000001' http://100.100.0.1:11436/v1/chat/completions -d '{"model":"fast","messages":[{"role":"user","content":"from a peer"}]}' | grep -q 'mock reply to: from a peer' && sudo -n maluctl gateway usage --envelope env_fedcba9876543210 2>/dev/null | grep -q 'node:inference:-100' && echo "  ok   served for the peer: the ledger row is node:inference:-100's, with the origin request and the envelope (usage --envelope)" || { echo "  FAIL peer call: $(curl -s --max-time 60 -H "Authorization: Bearer $PEERKEY" -H 'Content-Type: application/json' http://100.100.0.1:11436/v1/chat/completions -d '{"model":"fast","messages":[{"role":"user","content":"x"}]}' | head -c 300)"; fail=1; }
curl -s --max-time 10 -H "Authorization: Bearer $PEERKEY" -H 'Content-Type: application/json' -H 'X-MaluOS-Sensitivity: restricted' http://100.100.0.1:11436/v1/chat/completions -d '{"model":"fast","messages":[{"role":"user","content":"x"}]}' | grep -q '"code": "classification"' && echo "  ok   restricted above the peer's ceiling (internal): refused classification on the serving side" || { echo "  FAIL classification refusal"; fail=1; }
curl -s --max-time 10 -H "Authorization: Bearer $PEERKEY" -H 'Content-Type: application/json' http://100.100.0.1:11436/v1/chat/completions -d '{"model":"cloud-only-nope","messages":[{"role":"user","content":"x"}]}' | grep -q 'model_not_found' && echo "  ok   a peer asks for what this host serves, nothing else" || { echo "  FAIL peer unknown model"; fail=1; }
sudo -n maluctl gateway share off >/dev/null 2>&1; sleep 1
curl -s --max-time 10 -H "Authorization: Bearer $PEERKEY" -H 'Content-Type: application/json' http://100.100.0.1:11436/v1/chat/completions -d '{"model":"fast","messages":[{"role":"user","content":"x"}]}' | grep -q '"code": "not_shared"' && echo "  ok   share off: the peer is refused not_shared" || { echo "  FAIL not_shared for the peer"; fail=1; }
sudo -n maluctl gateway share on --when always >/dev/null 2>&1
sudo -n maluctl gateway unexpose >/dev/null 2>&1; sudo -n maluctl gateway reload >/dev/null 2>&1
sudo -n systemctl stop maluos-mock-ollama-7 2>/dev/null
# --- Phase 13 slice 4 (the node side): the memory face on a server; the facts reach the mock; the holders and peers the office publishes
installed maluos-memory && echo "  ok   maluos-memory" || { echo "  FAIL maluos-memory"; fail=1; }
systemctl is-active --quiet maluos-memory.socket && maluctl memory status | grep -q 'shared nothing' && echo "  ok   the memory face is up, sharing nothing" || { echo "  FAIL memory face: $(maluctl memory status 2>&1 | head -3)"; sudo -n journalctl -u maluos-memory --no-pager | tail -5; fail=1; }
sudo -n maluctl memory keys | grep -q 'estate-node-key' && sudo -n maluctl memory expose --bind overlay | grep -q 'listening on 100.100.0.1:11437' && sudo -n maluctl memory share org | grep -q 'shared: org' && echo "  ok   keys, expose on the overlay (100.100.0.1:11437), share org" || { echo "  FAIL memory keys/expose/share: $(sudo -n maluctl memory expose --bind overlay 2>&1 | tail -1)"; fail=1; }
srv_mem() { curl -fsS --max-time 5 http://127.0.0.1:18082/mock/memory | python3 -c "import json,sys; d=json.load(sys.stdin); f=d['facts'].get('inference:57') or {}; sys.exit(0 if ($1) else 1)" 2>/dev/null; }
for i in $(seq 1 30); do srv_mem "f.get('shared')==['org'] and f.get('port')==11437" && break; sleep 2; done
srv_mem "f.get('shared')==['org'] and f.get('port')==11437" && echo "  ok   the node's heartbeat carries the memory facts (shared org, port 11437); /mock/memory shows them" || { echo "  FAIL memory facts at the mock: $(curl -fsS --max-time 5 http://127.0.0.1:18082/mock/memory | head -c 300)"; fail=1; }
sudo -n maluctl agent create keeper --exec /usr/lib/maluos/maluos-agent-idle --scope org:write --no-start >/dev/null 2>&1
sudo -n maluctl memory remember "The plant runs two shifts from November" --scope org --kind summary --as agent:keeper | grep -q 'in org (summary) as agent:keeper' && sudo -n maluctl memory recall shifts --scope org --as agent:keeper | grep -q 'two shifts' && echo "  ok   remember and recall as a server agent (--as, as root)" || { echo "  FAIL remember/recall on the server: $(sudo -n maluctl memory remember x --scope org --as agent:keeper 2>&1 | tail -1)"; fail=1; }
out=$(sudo -n maluctl estate memory --refresh --peers 2>&1); echo "$out" | grep -q 'office: .*org' && echo "$out" | grep -q 'gpu-fake .*inference:-100 .*org' && echo "  ok   sudo maluctl estate memory --refresh: the office's own scopes for the node; the fake peer may ask it for org" || { echo "  FAIL estate memory: $out"; fail=1; }
curl -fsS --max-time 3 http://100.100.0.1:11437/memory/v1/health | grep -q '"shared": \["org"\]' && echo "  ok   the overlay listener says what this host shares" || { echo "  FAIL memory health over the overlay"; fail=1; }
sudo -n maluctl memory usage | grep -q 'memory.remember' && echo "  ok   the face's ledger rows (memory.remember, memory.recall)" || { echo "  FAIL memory usage"; fail=1; }
KID=$(sudo -n maluctl memory recall shifts --scope org --as agent:keeper --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["claims"][0]["id"])' 2>/dev/null)
sudo -n maluctl memory forget "${KID:-0}" --as agent:keeper 2>&1 | grep -q 'forgotten' && echo "  ok   the keeper's summary forgotten (removing the agent keeps its memories)" || { echo "  FAIL forget keeper's row: $(sudo -n maluctl memory forget "${KID:-0}" --as agent:keeper 2>&1 | tail -1)"; fail=1; }
sudo -n maluctl agent remove keeper --purge >/dev/null 2>&1; sudo -n maluctl memory unshare --all >/dev/null 2>&1; sudo -n maluctl memory unexpose >/dev/null 2>&1
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='secret.read' and principal_ref='host:$(hostname)' and secret_name='estate-node-token' and status='ok'" | grep -qE '^[1-9]' && echo "  ok   vault ledger: the token reads are the host principal's own rows" || { echo "  FAIL ledger rows for host:$(hostname)"; fail=1; }
sudo -n maluctl estate leave | grep -q 'node retired' && [ ! -f /etc/maluos/estate.yaml ] && ! systemctl is-active --quiet maluos-estate && ! sudo -n grep -q "maluos-estate:" /etc/maluos/vault.yaml && echo "  ok   sudo maluctl estate leave: retired, the unit stopped, the files gone, the identity map entry removed" || { echo "  FAIL estate leave (server)"; fail=1; }
sudo -n test ! -f /run/maluos/estate/inference.json && sudo -n test ! -f /run/maluos/estate/peers.json && sudo -n test ! -f /run/maluos/estate/memory.json && sudo -n test ! -f /run/maluos/estate/memory-peers.json && { for i in $(seq 1 10); do ! maluctl gateway status | grep -q 'estate:gpu-fake' && break; sleep 2; done; ! maluctl gateway status | grep -q 'estate:gpu-fake'; } && echo "  ok   leave took the directory caches: the estate rung left the gateway" || { echo "  FAIL caches after leave: $(ls -la /run/maluos/estate/ 2>&1); $(maluctl gateway status | grep estate)"; fail=1; }
sudo -n maluctl principal list | grep -q "host:$(hostname)  service" && echo "  ok   the host principal stays (maluctl principal list)" || { echo "  FAIL host principal: $(sudo -n maluctl principal list | grep host)"; fail=1; }
! ip link show estate >/dev/null 2>&1 && ! grep -q 'maluos-estate overlay' /etc/hosts && ! systemctl is-active --quiet maluos-overlay && echo "  ok   leave took the overlay down: no interface, no names, the service stopped" || { echo "  FAIL overlay after leave: $(ip -br link show estate 2>&1); $(systemctl is-active maluos-overlay)"; fail=1; }
sudo -n systemctl stop maluos-mock-estate 2>/dev/null
else echo "  (no maluos-estate in this image)"; fi
# --- MaluDB API component (when the image carries it)
if installed maluos-api; then
for p in maluos-api maludb-api; do dpkg-query -W -f='${Status}' $p 2>/dev/null | grep -q 'install ok installed' && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }; done
systemctl is-active --quiet maludb-api && echo "  ok   maludb-api active" || { echo "  FAIL maludb-api: $(systemctl is-active maludb-api)"; sudo -n journalctl -u maludb-api --no-pager | tail -8; fail=1; }
curl -fsS --max-time 5 http://127.0.0.1:8000/health | grep -q ok && echo "  ok   API /health" || { echo "  FAIL API /health"; fail=1; }
atok=$(sudo -n maluctl token api 2>/dev/null); [ "${atok#malu_}" != "$atok" ] && echo "  ok   API token minted" || { echo "  FAIL API token"; fail=1; }
curl -fsS --max-time 10 -H "Authorization: Bearer $atok" http://127.0.0.1:8000/v1/subjects >/dev/null && echo "  ok   API /v1/subjects with token (PostgreSQL 18 query path)" || { echo "  FAIL API /v1/subjects"; sudo -n journalctl -u maludb-api --no-pager | tail -5; fail=1; }
systemctl is-active --quiet maludb-embedding-worker.timer && echo "  ok   embedding sweep timer" || echo "  warn embedding sweep timer not active"
else echo "  (no maluos-api in this image)"; fi
# --- Business OS kernel component (when the image carries it and the component is on: firstboot.yaml
# components.maludb-os-core.enabled, off as shipped, on from the installer's First boot screen, a plan,
# or this test's seed; a disabled component is skipped by the engine before it is loaded)
bos_on() { sudo -n python3 -c "import yaml,sys; c=yaml.safe_load(open('/etc/maluos/firstboot.yaml')) or {}; sys.exit(0 if (c.get('components') or {}).get('maludb-os-core', {}).get('enabled', True) is not False else 1)" 2>/dev/null; }
if installed maluos-business-os && bos_on; then
for p in maluos-business-os maludb-os-core; do dpkg-query -W -f='${Status}' $p 2>/dev/null | grep -q 'install ok installed' && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }; done
bosdom=$(sudo -n python3 -c "import json;print(json.load(open('/var/lib/maluos/firstboot/done'))['components']['maludb-os-core'].get('domain',''))" 2>/dev/null)
echo "  bos domain: ${bosdom:-?}"
# the office's own names (docs/phase13-estate-behind-a-proxy.md, part 2): under https at the proxy's address in a marked block,
# never on loopback; the summary says where they went
# (these lines run inside the VM: the scheme and the proxy address come from its own firstboot.yaml, not from this script's variables)
bosscheme=$(sudo -n python3 -c "import json;print(json.load(open('/var/lib/maluos/firstboot/done'))['components']['maludb-os-core'].get('scheme',''))" 2>/dev/null)
proxyaddr=$(sudo -n python3 -c "import yaml;print((yaml.safe_load(open('/etc/maluos/firstboot.yaml'))['components']['maludb-os-core']).get('proxy_address',''))" 2>/dev/null)
if [ "$bosscheme" = https ] && [ -n "$proxyaddr" ]; then
grep -qP "^$proxyaddr\tapp\.$bosdom$" /etc/hosts && grep -qP "^$proxyaddr\tos\.$bosdom$" /etc/hosts && grep -qP "^$proxyaddr\t$bosdom$" /etc/hosts && ! grep -qE "^(127\.0\.0\.1|::1).*[[:space:]](app|os|www)\.$bosdom([[:space:]]|$)" /etc/hosts && getent hosts app.$bosdom | grep -q "^$proxyaddr " && echo "  ok   https: the office's names resolve to the proxy's address $proxyaddr (the marked block), none on loopback" || { echo "  FAIL office names under https ($proxyaddr): $(grep -E "$bosdom|business-os names" /etc/hosts)"; fail=1; }
sudo -n python3 -c "import json; h=json.load(open('/var/lib/maluos/firstboot/done'))['components']['maludb-os-core']['hosts']; assert h['mode']=='proxy $proxyaddr' and h['address']=='$proxyaddr', h" 2>/dev/null && echo "  ok   the summary records hosts: proxy $proxyaddr" || { echo "  FAIL summary hosts: $(sudo -n python3 -c "import json; print(json.load(open('/var/lib/maluos/firstboot/done'))['components']['maludb-os-core'].get('hosts'))")"; fail=1; }
else
grep -qE "^127\.0\.0\.1 .*app\.$bosdom" /etc/hosts && ! grep -q 'business-os names begin' /etc/hosts && echo "  ok   http: the office's names on loopback, as before" || { echo "  FAIL office names under http: $(grep "$bosdom" /etc/hosts)"; fail=1; }
fi
for u in apache2 maludb-os-web maludb-os-records-mcp maludb-os-activity-mcp maludb-os-actions-mcp maludb-os-memory-mcp maludb-os-agent-runner maludb-os-activity-ingest.timer; do
  systemctl is-active --quiet $u && echo "  ok   $u active" || { echo "  FAIL $u: $(systemctl is-active $u)"; sudo -n journalctl -u $u --no-pager | tail -5; fail=1; }
done
curl -fsS --max-time 10 http://127.0.0.1:8080/api/v1/health | grep -q '"ok"' && echo "  ok   kernel PHP API /api/v1/health" || { echo "  FAIL kernel PHP API"; fail=1; }
# next start takes minutes under emulation; give the front end time to come up behind Apache
for i in $(seq 1 40); do code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 -H "Host: app.$bosdom" http://127.0.0.1/login); [ "$code" = 200 ] && break; sleep 10; done
[ "$code" = 200 ] && echo "  ok   kernel web /login via Apache (200)" || { echo "  FAIL kernel web /login: HTTP $code"; sudo -n journalctl -u maludb-os-web --no-pager | tail -8; fail=1; }
# the bare name: the starter page (kernel landing-starter/, rendered once by the component), with the office's domain
# in it, saying it is a starter, and its own Bootstrap, htmx and fragment beside it (nothing from another site)
lp=$(curl -s --max-time 10 -H "Host: $bosdom" http://127.0.0.1/)
echo "$lp" | grep -q '<meta name="maluos-landing" content="starter">' && echo "$lp" | grep -q 'This is a starter page' && echo "$lp" | grep -q "app.$bosdom" && ! echo "$lp" | grep -q '__DOMAIN__\|subello' \
  && echo "  ok   landing page: the starter, marked as one, with the office's domain" || { echo "  FAIL landing page is not the starter for $bosdom: $(echo "$lp" | head -c 300 | tr '\n' ' ')"; fail=1; }
lok=1; for f in static/bootstrap.min.css static/bootstrap.bundle.min.js static/htmx.min.js static/site.css partials/contact.html; do
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H "Host: $bosdom" http://127.0.0.1/$f)" = 200 ] || { lok=0; echo "  FAIL landing page file $f"; fail=1; }; done
[ $lok = 1 ] && ! echo "$lp" | grep -qE '(src|href)="https?://[^"]*\.(js|css)' && echo "  ok   landing page: Bootstrap, htmx, site.css and the fragment served from the office, no script or style from another site" || { echo "  FAIL landing page assets"; fail=1; }
sudo -n grep -q '"landing": "starter"' /var/lib/maluos/firstboot/done && echo "  ok   the component reports landing: starter" || { echo "  FAIL landing state in the done file"; fail=1; }
for i in $(seq 1 12); do curl -fsS --max-time 10 http://127.0.0.1:8815/health 2>/dev/null | grep -q '"ok"' && break; sleep 10; done
curl -fsS --max-time 10 http://127.0.0.1:8815/health 2>/dev/null | grep -q '"ok"' && echo "  ok   agent runner /health" || { echo "  warn agent runner /health not ok"; sudo -n journalctl -u maludb-os-agent-runner --no-pager | tail -6; }
sudo -n -u postgres psql -Atd maludb_os -c "select count(*) from members where business_role='super_admin'" | grep -qE '^[1-9]' && echo "  ok   super-admin exists in maludb_os" || { echo "  FAIL super-admin"; fail=1; }
sudo -n -u postgres psql -Atd maludb_os -c "select count(*) from pg_tables where schemaname='public'" | sed 's/^/  kernel tables: /'
sudo -n test -s /var/lib/maluos/secrets/business-os/admin-password && echo "  ok   admin password stored" || echo "  warn no stored admin password"
# --- the applications (the maluos-apps proposal, phase 1; docs/components.md): maluos-apps carries the host tools; the kernel
# component installed components.maludb-os-core.apps.install at first boot. The seed sets install: [] unless BOOT_TEST_APPS=1
# on the host (see the seed), so CI checks the tools, the plugin and the empty step; with the applications on, each one's
# marker, code, kernel row, units and name, and `maluctl app names` with four names plus one per application.
if installed maluos-apps; then
echo "  ok   maluos-apps"
for t in composer pdftotext unzip git; do command -v $t >/dev/null && echo "  ok   $t on the host (maluos-apps)" || { echo "  FAIL $t missing (maluos-apps)"; fail=1; }; done
python3 -c 'import venv, ensurepip' 2>/dev/null && echo "  ok   python3-venv with ensurepip" || { echo "  FAIL python3 -m venv unusable"; fail=1; }
else echo "  FAIL maluos-apps not installed"; fail=1; fi
appsline=$(sudo -n python3 -c "import json; r=json.load(open('/var/lib/maluos/firstboot/done'))['components']['maludb-os-core']; a=r.get('apps') or {}; print(' '.join(a.get('installed') or []) + '|' + ' '.join(a.get('failed') or []) + '|' + ' '.join(r.get('names') or []))" 2>/dev/null)
appsok=${appsline%%|*}; appsrest=${appsline#*|}; appsfail=${appsrest%%|*}; appsnames=${appsrest#*|}
[ -n "$appsnames" ] && echo "  ok   the component's summary carries the office's names: $appsnames" || { echo "  FAIL no names in the component's summary"; fail=1; }
sudo -n maluctl status | grep -q "^names:       $bosdom " && echo "  ok   maluctl status prints the names" || { echo "  FAIL names line missing from maluctl status"; sudo -n maluctl status | tail -4; fail=1; }
[ "$(maluctl app names | head -1)" = "$bosdom" ] && [ "$(maluctl app names | wc -l)" -ge 4 ] && echo "  ok   maluctl app names: $(maluctl app names | tr '\n' ' ')" || { echo "  FAIL maluctl app names: $(maluctl app names 2>&1 | head -3)"; fail=1; }
maluctl app names --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['domain']=='$bosdom' and d['names'][:4]==['$bosdom','www.$bosdom','app.$bosdom','os.$bosdom'], d" 2>/dev/null && echo "  ok   maluctl app names --json: the domain and the four kernel names first" || { echo "  FAIL app names --json"; fail=1; }
appswant=$(sudo -n python3 -c "import yaml; c=yaml.safe_load(open('/etc/maluos/firstboot.yaml')); a=(c['components']['maludb-os-core'].get('apps') or {}); i=a.get('install'); print(' '.join(i) if i is not None else 'hr projects helpdesk spaces')" 2>/dev/null)
if [ -z "$appswant" ]; then
  [ -z "$appsok$appsfail" ] && [ "$(maluctl app names | wc -l)" = 4 ] && echo "  ok   apps.install is empty (the test seed): the step installed nothing, four names" || { echo "  FAIL apps step with install: []: installed='$appsok' failed='$appsfail' names=$(maluctl app names | wc -l)"; fail=1; }
  echo "  (the applications are not installed on this boot: BOOT_TEST_APPS=1 keeps the image's default, hr projects helpdesk spaces, and checks them)"
else
  [ -z "$appsfail" ] && echo "  ok   no application failed at first boot" || { echo "  FAIL applications failed: $appsfail"; for k in $appsfail; do sudo -n tail -6 /var/lib/maluos/business-os/apps/$k.log; done; fail=1; }
  for k in $appswant; do
    echo "$appsok" | tr ' ' '\n' | grep -qx "$k" && sudo -n test -f /var/lib/maluos/business-os/apps/$k && echo "  ok   $k in apps.installed, with its marker" || { echo "  FAIL $k not in apps.installed or no marker"; fail=1; }
    sudo -n test -f /srv/apps/$k/maludb-os.json && echo "  ok   /srv/apps/$k holds the application" || { echo "  FAIL /srv/apps/$k"; fail=1; }
    sudo -n -u postgres psql -Atd maludb_os -c "select status from applications where app_key='$k' and status<>'retired'" | grep -qx active && echo "  ok   application $k active in the kernel" || { echo "  FAIL application $k not active: $(sudo -n -u postgres psql -Atd maludb_os -c "select app_key||' '||status from applications where app_key='$k'" 2>&1)"; fail=1; }
    for u in $(sudo -n python3 -c "import json, os; print(' '.join(os.path.basename(s) for s in json.load(open('/srv/apps/$k/maludb-os.json')).get('services') or []))" 2>/dev/null); do
      systemctl is-active --quiet "$u" && echo "  ok   $u active" || { echo "  FAIL $u: $(systemctl is-active $u)"; sudo -n journalctl -u "$u" --no-pager | tail -4; fail=1; }
    done
    label=$(sudo -n python3 -c "import json; m=json.load(open('/srv/apps/$k/maludb-os.json')); print((m.get('vhost') or {}).get('label') or '$k')" 2>/dev/null)
    maluctl app names | grep -qx "$label.$bosdom" && echo "  ok   maluctl app names lists $label.$bosdom" || { echo "  FAIL $label.$bosdom missing from maluctl app names"; fail=1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -H "Host: $label.$bosdom" http://127.0.0.1/); [ "$code" != 000 ] && [ "$code" -lt 500 ] && echo "  ok   $label.$bosdom answers through Apache ($code)" || { echo "  FAIL $label.$bosdom via Apache: HTTP $code"; fail=1; }
  done
  appsn=$(( 4 + $(echo $appswant | wc -w) )); [ "$(maluctl app names | wc -l)" = "$appsn" ] && echo "  ok   maluctl app names lists $appsn names" || { echo "  FAIL maluctl app names: expected $appsn names, got $(maluctl app names | wc -l)"; fail=1; }
fi
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
# the first sign-in, proved by the office-setup plugin's own check (0.1.1): the administrator's member, the stored
# password against it, the session cookie for the scheme, one real sign-in against the kernel; no password shown
if installed maluos-office-setup; then
  out=$(sudo -n maluctl office-setup admin check 2>&1); rc=$?
  [ $rc = 0 ] && echo "$out" | grep -q 'PASS  a sign-in on this host with the stored password succeeds' && ! echo "$out" | grep -q '^FAIL' \
    && echo "  ok   maluctl office-setup admin check: the first sign-in works with the generated password" || { echo "  FAIL office-setup admin check: $(echo "$out" | grep '^FAIL\|^ERROR' | head -3 | cut -c1-260)"; fail=1; }
  # the public page through the plugin (0.1.3): a working copy, a refused publish, a real one, the component leaving an
  # edited page alone, and the starter restored
  ws=$(mktemp -d)/site
  out=$(sudo -n maluctl office-setup website status 2>&1); echo "$out" | grep -q '^page: *starter' && echo "  ok   office-setup website status: the starter" || { echo "  FAIL website status: $(echo "$out" | head -3 | tr '\n' ' ')"; fail=1; }
  sudo -n maluctl office-setup website checkout "$ws" >/dev/null 2>&1 && [ -w "$ws/index.html" ] && echo "  ok   website checkout: a working copy the operator owns" || { echo "  FAIL website checkout"; fail=1; }
  echo '<?php echo 1;' > "$ws/x.php"
  out=$(sudo -n maluctl office-setup website publish "$ws" 2>&1); rc=$?
  [ $rc != 0 ] && echo "$out" | grep -q 'x.php' && curl -s --max-time 10 -H "Host: $bosdom" http://127.0.0.1/ | grep -q 'content="starter"' && echo "  ok   website publish refuses server-side code and publishes nothing" || { echo "  FAIL publish accepted x.php (rc=$rc)"; fail=1; }
  rm -f "$ws/x.php"; sed -i '/maluos-landing/d; s/<title>.*<\/title>/<title>Boot test bakery<\/title>/' "$ws/index.html"
  out=$(sudo -n maluctl office-setup website publish "$ws" 2>&1); rc=$?
  [ $rc = 0 ] && curl -s --max-time 10 -H "Host: $bosdom" http://127.0.0.1/ | grep -q '<title>Boot test bakery</title>' && sudo -n maluctl office-setup website status 2>&1 | grep -q '^page: *customised' \
    && echo "  ok   website publish: the edited copy is live and reads as customised" || { echo "  FAIL website publish (rc=$rc): $(echo "$out" | tail -3 | tr '\n' ' ')"; fail=1; }
  kept=$(sudo -n python3 -c "
import importlib.util
sp=importlib.util.spec_from_file_location('c','/usr/lib/maluos/components/60-maludb-os-core.py'); m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
print(m.render_landing('$bosdom'))" 2>&1 | tail -1)
  [ "$kept" = kept ] && curl -s --max-time 10 -H "Host: $bosdom" http://127.0.0.1/ | grep -q 'Boot test bakery' && echo "  ok   the component leaves an edited landing page alone" || { echo "  FAIL the component's landing step on an edited page: $kept"; fail=1; }
  sudo -n maluctl office-setup website restore >/dev/null 2>&1 && curl -s --max-time 10 -H "Host: $bosdom" http://127.0.0.1/ | grep -q 'content="starter"' && echo "  ok   website restore: the page before the publish is back" || { echo "  FAIL website restore"; fail=1; }
fi
elif installed maluos-business-os; then
echo "  (the kernel component is off in firstboot.yaml: nothing provisioned, as shipped)"
sudo -n python3 -c "import json,sys; d=json.load(open('/var/lib/maluos/firstboot/done')); sys.exit(1 if 'maludb-os-core' in (d.get('components') or {}) else 0)" 2>/dev/null && echo "  ok   kernel component skipped: not in the done file" || { echo "  FAIL the done file records maludb-os-core although the component is off"; fail=1; }
! systemctl is-active --quiet maludb-os-web && ! sudo -n test -d /var/lib/maluos/secrets/business-os && echo "  ok   no kernel unit running, no kernel secrets" || { echo "  FAIL kernel traces with the component off"; fail=1; }
else echo "  (no maluos-business-os in this image)"; fi
# --- the desktop (Phase 12): GNOME on gdm, the MaluOS identity on the login screen, no snaps
if installed maluos-desktop; then
for p in maluos-desktop maluos-desktop-branding gdm3 gnome-shell ubuntu-session gnome-control-center nautilus ptyxis firefox gnome-software gnome-software-plugin-deb appstream maluos-archive-mozilla; do installed $p && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }; done
# --- the office apps (vendored debs): Malu123 and MaluOS Slides with the shared fonts, their desktop entries, the CLIs answer
for p in malu123 maluos-slides maluos-fonts; do installed $p && echo "  ok   $p" || { echo "  FAIL $p"; fail=1; }; done
for d in /usr/share/applications/org.maluos.slides.desktop; do [ -f $d ] && grep -q '^Categories=.*Office' $d && echo "  ok   $(basename $d) in the Office category" || { echo "  FAIL $d"; fail=1; }; done
v=$(maluos-slides-cli --version 2>/dev/null); echo "$v" | grep -q '^maluos-slides-cli ' && echo "  ok   $v" || { echo "  FAIL maluos-slides-cli --version: $v"; fail=1; }
grep -q 'application/vnd.openxmlformats-officedocument.presentationml.presentation=org.maluos.slides.desktop' /usr/share/applications/mimeinfo.cache && echo "  ok   .pptx opens with MaluOS Slides (mimeinfo.cache)" || { echo "  FAIL .pptx association"; fail=1; }
n=$(ls /usr/share/fonts/truetype/maluos-fonts/*/*.ttf 2>/dev/null | wc -l); [ "$n" -ge 50 ] && fc-list | grep -q 'maluos-fonts/inter/Inter-Regular.ttf' && echo "  ok   maluos-fonts: $n faces, fontconfig sees Inter" || { echo "  FAIL maluos-fonts: $n faces"; fail=1; }
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
# a frozen shell (seen 2026-10-28: gnome-shell's dconf worker spinning inside gjs while the main thread waited on it; every GUI self-test then
# timed out silently): measure the shell's threads first and, when one is hot, record a symbolised backtrace instead of ten empty timeouts
SHELLPID=$(pgrep -u "$uid" -x gnome-shell | head -1)
shell_ns() { cat /proc/$SHELLPID/task/*/schedstat 2>/dev/null | awk '{s+=$1} END{print s+0}'; }
a=$(shell_ns); sleep 3; b=$(shell_ns)
if [ $((b-a)) -gt 2400000000 ]; then
  echo "  warn gnome-shell is hot ($(( (b-a)/30000000 ))% of a core over 3 s); its threads (ns of CPU since start):"
  for t in /proc/$SHELLPID/task/*; do echo "       $(cat $t/comm) $(cut -d' ' -f1 $t/schedstat)"; done
  sudo -n apt-get install -y -q gdb >/dev/null 2>&1
  sudo -n env DEBUGINFOD_URLS=https://debuginfod.ubuntu.com timeout 900 gdb -p "$SHELLPID" -batch -ex "set debuginfod enabled on" -ex "thread apply all bt 16" 2>/dev/null | grep -E "^Thread|^#" | head -140 | cut -c1-200
else
  echo "  ok   gnome-shell idle enough for the GUI self-tests ($(( (b-a)/30000000 ))% of a core over 3 s)"
fi
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-agents --agent local:desk --self-test 2>&1); echo "$out" | grep -q 'self-test ok: Agents: service reachable, 1 local agents, 0 office agents, no office, directory 0, personal agent absent, inbox 0 unread, memory [0-9]* claims, selected local:desk' && echo "  ok   Agents window (WebKitGTK) builds from the live state, the UI reports ready, agent desk selected" || { echo "  FAIL maluos-agents self-test: $(echo "$out" | tail -4)"; fail=1; }
# Phase 13 G1: the forked System Monitor's GPUs tab, from the live session (no GPU: the empty row, chassis vm; share on --when idle set here, as the gateway section did before slice 3)
sudo -n maluctl gateway share on --when idle >/dev/null 2>&1
# slice 3, the idle rule: the session has had no input since it logged in (far past the ten minutes): its idle mark is up and the switch follows it
for i in $(seq 1 20); do [ -f /run/maluos/session/idle ] && break; sleep 3; done
[ -f /run/maluos/session/idle ] && state | python3 -c "import json,sys; i=json.load(sys.stdin)['host']['idle']; assert i['idle'] and i['idle_s']>=600 and not i['lid_closed'] and not i['on_battery'] and not i['media_playing'] and i['since'], i; print('  ok   the idle rule: no input since login, the lid open, on mains, no media playing: the session keeps /run/maluos/session/idle and host.idle says so')" || { echo "  FAIL idle mark: $(ls -la /run/maluos/session/ 2>&1); $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["host"].get("idle"))'); $(sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | grep idle: | tail -3)"; fail=1; }
maluctl gateway share | grep -q '^share:       on  contribution idle .*idle rule: contributing since' && echo "  ok   maluctl gateway share: on, contribution idle, contributing since the mark" || { echo "  FAIL share status with the idle rule: $(maluctl gateway share 2>&1)"; fail=1; }
installed maluos-system-monitor && ! installed gnome-system-monitor && [ -f /usr/share/applications/org.gnome.SystemMonitor.desktop ] && echo "  ok   maluos-system-monitor replaces gnome-system-monitor (same launcher)" || { echo "  FAIL maluos-system-monitor: $(dpkg -l | grep -i system-monitor)"; fail=1; }
for i in $(seq 1 20); do state | python3 -c "import json,sys; sh=json.load(sys.stdin)['gateway']['share']; sys.exit(0 if sh.get('contribution')=='idle' else 1)" 2>/dev/null && break; sleep 3; done     # the session reads the gateway every 20 s
state | python3 -c "import json,sys; s=json.load(sys.stdin); h=s['host']; assert h['gpus']==[] and h['chassis']=='vm' and h['contribution_rule']=='always', h; sh=s['gateway']['share']; assert sh['configured_enabled'] and sh['contribution']=='idle' and sh['configured'] and sh['enabled']==bool((sh.get('idle') or {}).get('idle')), sh; print('  ok   session state carries gpus (none), chassis vm, rule always, and the gateway share switch (on, idle)')" || { echo "  FAIL session gpu state: $(state | python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["host"].get("gpus"), s["host"].get("chassis"), s["gateway"].get("share"))' 2>&1)"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 gnome-system-monitor --maluos-self-test 2>&1); echo "$out" | grep -q 'self-test ok: GPUs: session reachable, 0 gpus, chassis vm, rule always, share on, gateway ok' && echo "  ok   System Monitor (forked) builds, the GPUs tab reads the live session state" || { echo "  FAIL gnome-system-monitor --maluos-self-test: $(echo "$out" | tail -4)"; fail=1; }
# Phase 13 G5: the MaluOS Network and Queue tabs read the node section and NodeQueue of the live session (the login user is an operator)
echo "$out" | grep -qE 'Network: node [a-z0-9-]+, [0-9]+ lanes, 0 paired, 3 keys, socket only; Queue: [0-9]+ jobs \([0-9]+ running, [0-9]+ queued\) in [0-9]+ lanes' && echo "  ok   the Network and Queue tabs report this node (its keys, socket only) and the live queue in the same self-test" || { echo "  FAIL network/queue self-test: $(echo "$out" | grep 'self-test' | tail -1)"; fail=1; }
state | python3 -c "import json,sys; s=json.load(sys.stdin); n=s['node']; assert n['available'] and n['operator'] and n['name'] and n['id'] and 'mock' in n['lanes'] and n['lanes']['mock']['kind']=='local' and not n['exposed']['enabled'], n; ks={k['name']: k for k in n['keys']}; assert set(ks)=={'boot-manager','boot-desk','ov-test'} and ks['boot-manager']['kind']=='node' and ks['boot-desk']['kind']=='inference' and ks['ov-test']['kind']=='node', ks; print('  ok   session state carries the node: operator, lanes (mock local), socket only, the three keys issued earlier (%s)' % n['name'])" || { echo "  FAIL node in state: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin).get("node"))' 2>&1 | head -c 400)"; fail=1; }
nq() { gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.NodeQueue 2>/dev/null | python3 -c "import ast,sys,json; print(json.dumps(json.loads(ast.literal_eval(sys.stdin.read())[0])))"; }
nq | python3 -c "import json,sys; q=json.load(sys.stdin); assert q['ok'] and 'mock' in q['lanes'] and isinstance(q['queue'], list) and not q['lanes']['mock']['paused'], q; print('  ok   NodeQueue over the session bus: the lanes and the queue, mock not paused')" || { echo "  FAIL NodeQueue: $(nq | head -c 300)"; fail=1; }
maluctl gateway node pause mock >/dev/null 2>&1 && nq | python3 -c "import json,sys; q=json.load(sys.stdin); assert q['lanes']['mock']['paused'], q['lanes']; print('  ok   maluctl gateway node pause mock (the Queue tab\'s action) shows in NodeQueue as paused')" || { echo "  FAIL pause via maluctl: $(nq | head -c 200)"; fail=1; }
maluctl gateway node resume mock >/dev/null 2>&1 && nq | python3 -c "import json,sys; q=json.load(sys.stdin); assert not q['lanes']['mock']['paused'], q['lanes']; print('  ok   maluctl gateway node resume mock: not paused again')" || { echo "  FAIL resume via maluctl"; fail=1; }
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
rid=""; for i in $(seq 1 30); do gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.Refresh >/dev/null 2>&1; sleep 3; rid=$(state | python3 -c "import json,sys; s=json.load(sys.stdin); r=[x for x in s['vault'].get('requests') or [] if x['requester']=='agent:desk' and x['mine_to_decide']]; print(r[0]['id'] if r else '')"); [ -n "$rid" ] && break; done   # the refresh is slow under emulation
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
sudo -n systemd-run --quiet --unit maluos-mock-office -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_desk.mock_office --port 18080 --code boot-code --node-code node-code --name "Mock Office" --models office-7b,office-embed --heartbeat-s 30 --node-heartbeat-s 10 --report-s 10
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:18080/api/v1/health >/dev/null 2>&1 && break; sleep 1; done
curl -fsS --max-time 5 http://127.0.0.1:18080/api/v1/health | grep -q '"office": "Mock Office"' && echo "  ok   mock office up" || { echo "  FAIL mock office"; sudo -n journalctl -u maluos-mock-office --no-pager | tail -5; fail=1; }
! sudo -n maluctl office enroll http://127.0.0.1:18080 --code wrong-code >/dev/null 2>&1 && echo "  ok   a wrong code is refused" || { echo "  FAIL enrolment with a wrong code succeeded"; fail=1; }
out=$(sudo -n maluctl office enroll http://127.0.0.1:18080 --code boot-code --name "Test desk" 2>&1); echo "$out" | grep -q "enrolled: desk 'Test desk' (#41) at Mock Office for user:maluos" && echo "  ok   sudo maluctl office enroll (one-time code, the sudo user owns the desk)" || { echo "  FAIL office enroll: $out"; fail=1; }
! sudo -n maluctl office enroll http://127.0.0.1:18080 --code boot-code >/dev/null 2>&1 && echo "  ok   the code cannot be used twice" || { echo "  FAIL code reuse"; fail=1; }
sudo -n grep -q 'registered: true' /etc/maluos/office.yaml && maluctl secret list | grep -q 'office-desk-key' && echo "  ok   slice 2: the desk's signing key made at enrol (office-desk-key in the owner's compartment), registered with the office" || { echo "  FAIL desk key at enrol: $(sudo -n grep -c key /etc/maluos/office.yaml); $(maluctl secret list | grep office)"; fail=1; }
grep -q '^url: http://127.0.0.1:18080$' /etc/maluos/office.yaml && grep -q 'principal: user:maluos' /etc/maluos/office.yaml && ! grep -q 'desk_' /etc/maluos/office.yaml && echo "  ok   /etc/maluos/office.yaml records the office, the owner and no token" || { echo "  FAIL office.yaml: $(cat /etc/maluos/office.yaml | head -c 300)"; fail=1; }
grep -q 'MALUOS_OFFICE_RECORDS_MCP="http://127.0.0.1:18080/mcp/records"' /etc/maluos/office.env && grep -q 'MALUOS_OFFICE_TOKEN_SECRET="office-desk-token"' /etc/maluos/office.env && grep -q 'MALUOS_OFFICE_MEMORY_URL="http://127.0.0.1:18080/api/v1/desks/memory"' /etc/maluos/office.env && grep -q 'MALUOS_OFFICE_MEMORY_MCP="http://127.0.0.1:18080/mcp/memory"' /etc/maluos/office.env && maluctl office status | grep -q 'endpoints:  .*memory_mcp' && echo "  ok   /etc/maluos/office.env names the office's endpoints for agents (the holders view and the Memory MCP among them, slice 4b)" || { echo "  FAIL office.env"; fail=1; }
# slice 7: MaluApps from the office's catalogue (endpoints.apps), the public one unreachable here
MALUOS_APPS_PUBLIC_URL=http://127.0.0.1:1/catalog.json maluctl office apps --refresh > /tmp/apps.txt 2>&1 && [ "$(grep -c ' web    office ' /tmp/apps.txt)" = 4 ] && grep -q '^  helpdesk .*available' /tmp/apps.txt && echo "  ok   maluctl office apps lists the mock office's four apps (public catalogue unreachable, office wins)" || { echo "  FAIL office apps: $(cat /tmp/apps.txt | head -4)"; fail=1; }
MALUOS_APPS_PUBLIC_URL=http://127.0.0.1:1/catalog.json maluctl office apps install helpdesk >/dev/null 2>&1 && grep -q '^Exec=firefox --new-window http://127.0.0.1:18080/apps/helpdesk$' ~/.local/share/applications/maluapp-helpdesk.desktop && maluctl office apps --json --compact | python3 -c "import json,sys; c=json.load(sys.stdin); a=[x for x in c['apps'] if x['id']=='helpdesk'][0]; assert a['installed'] and a['source']=='office', a" && echo "  ok   apps install helpdesk: a launcher opening the office's app in its own Firefox window" || { echo "  FAIL apps install helpdesk"; fail=1; }
MALUOS_APPS_PUBLIC_URL=http://127.0.0.1:1/catalog.json maluctl office apps remove helpdesk >/dev/null 2>&1 && [ ! -f ~/.local/share/applications/maluapp-helpdesk.desktop ] && echo "  ok   apps remove helpdesk takes the launcher away" || { echo "  FAIL apps remove"; fail=1; }
# slice 9: the public catalogue is signed; a throwaway key stands in for the release key (MALUOS_APPS_KEYRING)
export GNUPGHOME=$HOME/.gnupg-cat; mkdir -p "$GNUPGHOME" ~/cat && chmod 700 "$GNUPGHOME"
gpg --batch --quiet --passphrase '' --quick-gen-key "Boot Test Catalogue <cat@test.invalid>" default default never >/dev/null 2>&1 && gpg --batch --export > ~/cat/keyring.gpg
printf '{"schema": 1, "apps": [{"id": "pubtool", "name": "Public Tool", "description": "a public app", "kind": "web", "url": "https://example.invalid/tool", "version": "1"}]}' > ~/cat/catalog.json
gpg --batch --quiet --passphrase '' --armor --detach-sign -o ~/cat/catalog.json.asc ~/cat/catalog.json; unset GNUPGHOME
systemd-run --user --quiet --unit boot-test-catalog python3 -m http.server 18081 --bind 127.0.0.1 --directory "$HOME/cat" 2>/dev/null
for i in $(seq 1 30); do curl -fsS --max-time 2 http://127.0.0.1:18081/catalog.json >/dev/null 2>&1 && break; sleep 1; done   # the server takes a few seconds to listen under TCG
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
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.Refresh >/dev/null 2>&1
for i in $(seq 1 10); do   # the refresh runs in the session's thread; under TCG it can take more than a few seconds
  crid=$(state | python3 -c "import json,sys; s=json.load(sys.stdin); r=[x for x in s['vault'].get('requests') or [] if x['requester']=='user:edward' and x['mine_to_decide'] and (x.get('cause') or {}).get('model')=='office' and x['cause'].get('backend')=='office' and x['cause'].get('call')]; print(r[0]['id'] if r else '')")
  [ -n "$crid" ] && break; sleep 3
done
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
# Phase 13 slice 1: this host joins the mock's estate as a server node beside its desk (one VM is both): the report, the office's health
# rules and alerts, office.estate in the session, the Network tab, a clean offline, leave (docs/phase13-slice1-nodes.md, "Test")
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/code -d '{"code": "desk-x", "kind": "desk"}' >/dev/null; curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/code -d '{"code": "node-x", "kind": "node"}' >/dev/null
! sudo -n maluctl estate join http://127.0.0.1:18080 --code desk-x --name x >/dev/null 2>&1 && ! sudo -n maluctl office enroll http://127.0.0.1:18080 --code node-x --force >/dev/null 2>&1 && echo "  ok   a desk code cannot join a node and a node code cannot enrol a desk (403 bad_code both ways)" || { echo "  FAIL code kinds"; fail=1; }
out=$(sudo -n maluctl estate join http://127.0.0.1:18080 --code node-code --name test-node --hub 127.0.0.1:51820 2>&1); echo "$out" | grep -q "joined: server 'test-node' (#57) at Mock Office as host:$(hostname)" && echo "  ok   sudo maluctl estate join: server 'test-node' (#57) as host:$(hostname)" || { echo "  FAIL estate join: $out"; fail=1; }
[ -f /etc/maluos/estate.yaml ] && ! sudo -n grep -q 'node_' /etc/maluos/estate.yaml && sudo -n -u maluos-estate maluctl secret list 2>/dev/null | grep -q "host:$(hostname)/estate-node-token" && sudo -n -u maluos-estate maluctl secret list 2>/dev/null | grep -q "host:$(hostname)/estate-node-key" && echo "  ok   /etc/maluos/estate.yaml without a token; the token and the key in host:$(hostname)'s compartment, stored as maluos-estate" || { echo "  FAIL estate files/secrets: $(sudo -n -u maluos-estate maluctl secret list 2>&1 | tail -3)"; fail=1; }
for i in $(seq 1 10); do systemctl is-active --quiet maluos-estate && break; sleep 2; done
systemctl is-active --quiet maluos-estate && echo "  ok   maluos-estate.service active (started by join)" || { echo "  FAIL maluos-estate unit: $(systemctl is-active maluos-estate); $(sudo -n journalctl -u maluos-estate --no-pager | tail -3)"; fail=1; }
maluctl estate report --json | python3 -c "import json,sys; r=json.load(sys.stdin); assert r['gateway']['ok'] and r['vault']['ok'] and r['disk'][0]['mount']=='/' and any(u['unit']=='maluos-gateway.service' and u['active']=='active' for u in r['units']) and any(a['name']=='desk' for a in r['agents']) and r['updates']['pending_count'] is not None and r['memory']['total_mb']>0, r; print('  ok   maluctl estate report: units, agents (desk), gateway ok, vault ok, updates, disk, memory')" || { echo "  FAIL estate report: $(maluctl estate report 2>&1 | tail -4)"; fail=1; }
mock_node() { curl -fsS --max-time 5 http://127.0.0.1:18080/mock/nodes | python3 -c "import json,sys; d=json.load(sys.stdin); n=[x for x in d['nodes'] if x['id']==57][0]; a=d['alerts']; sys.exit(0 if ($1) else 1)" 2>/dev/null; }
for i in $(seq 1 30); do mock_node "n['presence']=='online' and n['last_report_at']" && break; sleep 2; done
mock_node "n['presence']=='online' and n['last_report_at'] and n['health'] in ('ok','warning') and n['gateway']['ok'] and n['units']['up']>=4" && echo "  ok   the office has the node online with its report (the daemon's heartbeat, report_s 10)" || { echo "  FAIL node at the office: $(curl -s http://127.0.0.1:18080/mock/nodes | head -c 300)"; fail=1; }
sudo -n cat /var/lib/maluos/estate/state.json | python3 -c "import json,sys; s=json.load(sys.stdin); assert s['ok'] and s['last_report_at'], s" && maluctl estate status | grep -q "node:       server 'test-node'  (#57)" && maluctl estate status | grep -q 'ok  presence online' && echo "  ok   maluctl estate status: the enrolment and the daemon's last heartbeat (state.json)" || { echo "  FAIL estate status: $(maluctl estate status 2>&1)"; fail=1; }
maluctl office estate --refresh --json | python3 -c "import json,sys; c=json.load(sys.stdin); assert c['available'] and c['counts']['nodes']==2 and sorted(n['kind'] for n in c['nodes'])==['desk','server'], c; print('  ok   maluctl office estate as the desk owner (endpoints.estate): the server node and the desk')" || { echo "  FAIL office estate: $(maluctl office estate --refresh 2>&1 | tail -3)"; fail=1; }
sudo -n maluctl estate nodes | grep -q "estate of Mock Office as node #57: 2 nodes" && echo "  ok   maluctl estate nodes as the node (root reads the host's token)" || { echo "  FAIL estate nodes: $(sudo -n maluctl estate nodes 2>&1 | tail -2)"; fail=1; }
estate_in_state() { state | python3 -c "import json,sys; e=(json.load(sys.stdin).get('office') or {}).get('estate') or {}; sys.exit(0 if e.get('available') and ($1) else 1)" 2>/dev/null; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.OfficeAction heartbeat >/dev/null 2>&1
for i in $(seq 1 24); do estate_in_state "e['counts']['nodes']==2 and any(n['id']==57 and n['health'] in ('ok','warning') for n in e['nodes'])" && break; sleep 5; done
estate_in_state "e['counts']['nodes']==2 and any(n['id']==57 and n['health'] in ('ok','warning') for n in e['nodes'])" && echo "  ok   session state: office.estate carries both nodes after the heartbeat" || { echo "  FAIL estate in state: $(state | python3 -c 'import json,sys; print((json.load(sys.stdin).get("office") or {}).get("estate"))' | head -c 300)"; fail=1; }
# slice 1b on the desktop: this host is the hub; the desk enrolled earlier with its key is the hub's spoke, named in /etc/hosts
for i in $(seq 1 30); do ip -br addr show estate 2>/dev/null | grep -q '100.100.0.1/16' && grep -q 'test-desk.internal' /etc/hosts && break; sleep 2; done
ip -br addr show estate 2>/dev/null | grep -q '100.100.0.1/16' && grep -qP '^100\.100\.0\.1\ttest-node\.internal$' /etc/hosts && grep -qP '^100\.100\.0\.[0-9]+\ttest-desk\.internal$' /etc/hosts && echo "  ok   the overlay on the desktop: the hub's interface, the desk's name beside the node's" || { echo "  FAIL desktop overlay: $(ip -br addr show estate 2>&1); $(grep -A4 'overlay begin' /etc/hosts); $(sudo -n journalctl -u maluos-overlay --no-pager | tail -4)"; fail=1; }
sudo -n wg show estate 2>/dev/null | grep -q 'allowed ips: 100.100.0' && echo "  ok   wg: the desk peered on the hub" || { echo "  FAIL wg peers: $(sudo -n wg show estate 2>&1 | head -6)"; fail=1; }
maluctl office estate --refresh --json | python3 -c "import json,sys; c=json.load(sys.stdin); assert all(n.get('overlay') and n['overlay']['address'].startswith('100.100.0.') for n in c['nodes']), c['nodes']; print('  ok   maluctl office estate: both members carry their overlay address')" || { echo "  FAIL estate rows without overlay addresses"; fail=1; }
# --- Phase 13 slice 2 on the desktop: the directory, a task with the desk's envelope, refusals, an approval through the inbox, an operator's action, the personal agent
sudo -n systemd-run --quiet --unit maluos-mock-ollama-5 -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_gateway.mock_ollama --port 11999   # helper is the demo agent: it answers through the gateway, so a rung must be healthy
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:11999/api/tags >/dev/null 2>&1 && break; sleep 1; done
for i in $(seq 1 30); do sudo -n maluctl gateway reload >/dev/null 2>&1; maluctl gateway status | grep -q 'backend:     mock  mock .* healthy' && break; sleep 2; done
sudo -n maluctl agent create helper --exec "/usr/bin/python3 /usr/lib/maluos/maluos-agent-demo.py" --scope org:read --tiers fast --capability chat --accept-from org --max-classification internal >/dev/null 2>&1 \
  && echo "  ok   maluctl agent create helper --capability chat --accept-from org" || { echo "  FAIL agent create helper"; fail=1; }
dsk_dir() { curl -fsS --max-time 5 http://127.0.0.1:18080/mock/delegation | python3 -c "import json,sys; d=json.load(sys.stdin); ag=[a for a in d['agents'] if a['status']=='active']; sys.exit(0 if ($1) else 1)" 2>/dev/null; }
for i in $(seq 1 45); do dsk_dir "any(a['name']=='helper' for a in ag)" && break; sleep 2; done
for i in $(seq 1 60); do maluctl office agents --refresh 2>/dev/null | grep -q 'helper .*test-node' && break; sleep 3; done
maluctl office agents --refresh | grep -q 'helper .*test-node .*chat .*accepts org' && echo "  ok   maluctl office agents: helper on test-node with its capability and accept policy" || { echo "  FAIL office agents: $(maluctl office agents --refresh 2>&1 | head -4)"; fail=1; }
maluctl office agents --capability chat | grep -q helper && ! maluctl office agents --capability chat | grep -q ' desk ' && echo "  ok   the directory by capability: helper, not the idle desk agent" || { echo "  FAIL by capability: $(maluctl office agents --capability chat 2>&1)"; fail=1; }
HELPER=$(maluctl office agents --json | python3 -c 'import json,sys; print([a["id"] for a in json.load(sys.stdin)["agents"] if a.get("agent")=="helper"][0])' 2>/dev/null)
for i in $(seq 1 30); do [ -S /run/maluos/agents/helper/tasks.sock ] && [ -f /run/maluos/estate/keys.json ] && break; sleep 2; done
out=$(maluctl office agent "$HELPER" send Say pong. 2>/tmp/send.err); [ -n "$out" ] && grep -q 'from helper on server:57 · 1 model call(s) · envelope env_' /tmp/send.err && echo "  ok   maluctl office agent send: the desk's envelope, the task through the office to helper on this node, the answer with its provenance" || { echo "  FAIL office agent send: $out; $(cat /tmp/send.err | tail -2); $(sudo -n journalctl -u maluos-estate --no-pager | tail -3)"; fail=1; }
ENVID=$(sed -n 's/.*envelope \(env_[0-9a-f]*\).*/\1/p' /tmp/send.err | head -1); TID=$(sed -n 's/.*· task \(t_[0-9a-f]*\).*/\1/p' /tmp/send.err | head -1)
sudo -n maluctl gateway usage --envelope "$ENVID" 2>/dev/null | grep -q 'internal' && echo "  ok   the model call's ledger row carries the envelope and sensitivity internal" || { echo "  FAIL usage --envelope: $(sudo -n maluctl gateway usage --envelope "$ENVID" 2>&1 | tail -2)"; fail=1; }
maluctl estate tasks "$TID" | grep -q 'chain user:maluos > agent:helper' && echo "  ok   maluctl estate tasks (the desk token): the chain user:maluos > agent:helper" || { echo "  FAIL estate tasks: $(maluctl estate tasks "$TID" 2>&1 | head -3)"; fail=1; }
dsk_inj() { curl -fsS --max-time 70 -X POST http://127.0.0.1:18080/mock/task -d "$1" | python3 -c 'import json,sys; t=json.load(sys.stdin)["task"]; print(t["state"], t.get("reason") or "")' 2>/dev/null; }
dsk_inj '{"agent":"helper","sign":"expired","text":"x","wait":40}' | grep -q '^refused expired' && echo "  ok   /mock/task expired: refused expired" || { echo "  FAIL expired"; fail=1; }
dsk_inj '{"agent":"helper","sign":"valid","text":"once","wait":60}' | grep -q '^completed' && dsk_inj '{"agent":"helper","sign":"replay","text":"again","wait":40}' | grep -q '^refused replay' && echo "  ok   the same nonce twice: refused replay" || { echo "  FAIL replay"; fail=1; }
sudo -n maluctl agent policy helper set --accept-from none >/dev/null 2>&1
dsk_inj '{"agent":"helper","originator":"user:stranger","text":"x","wait":40}' | grep -q '^refused not_accepted' && echo "  ok   maluctl agent policy set --accept-from none: a stranger's task refused not_accepted" || { echo "  FAIL not_accepted: $(sudo -n maluctl agent policy helper)"; fail=1; }
sudo -n maluctl agent policy helper set --accept-from org >/dev/null 2>&1
dsk_inj '{"agent":"helper","classification":"restricted","text":"x","wait":40}' | grep -q '^refused classification' && echo "  ok   restricted to helper (ceiling internal): refused classification" || { echo "  FAIL classification"; fail=1; }
sudo -n journalctl -u maluos-agent@helper --no-pager 2>/dev/null | grep -q 'refused (expired)' && sudo -n journalctl -u maluos-agent@helper --no-pager | grep -q 'refused (replay)' && sudo -n journalctl -u maluos-agent@helper --no-pager | grep -q '(not_accepted)' && echo "  ok   each refusal is in the agent's journal" || { echo "  FAIL agent journal: $(sudo -n journalctl -u maluos-agent@helper --no-pager | grep refused | tail -3)"; fail=1; }
sudo -n maluctl agent policy helper set --approve restricted | grep -q 'approve restricted' && echo "  ok   maluctl agent policy helper set --approve restricted" || { echo "  FAIL policy set"; fail=1; }
out=$(maluctl office agent "$HELPER" send --classification restricted secret stuff 2>&1); echo "$out" | grep -q 'pending_approval' && echo "  ok   a restricted task from the owner parks pending_approval" || { echo "  FAIL pending_approval: $out"; fail=1; }
TID2=$(echo "$out" | sed -n 's/^task \(t_[0-9a-f]*\) pending_approval.*/\1/p' | head -1)
inbox_in_state() { state | python3 -c "import json,sys; i=(json.load(sys.stdin).get('office') or {}).get('inbox') or {}; sys.exit(0 if ($1) else 1)" 2>/dev/null; }
for i in $(seq 1 24); do inbox_in_state "i.get('unread',0)>=1 and any(x['kind']=='decision_needed' for x in i.get('items') or [])" && break; sleep 5; done
inbox_in_state "i.get('unread',0)>=1 and any(x['kind']=='decision_needed' and x.get('task_id')=='$TID2' for x in i.get('items') or [])" && echo "  ok   session state: office.inbox has the decision_needed for the task, unread" || { echo "  FAIL inbox in state: $(state | python3 -c 'import json,sys; print(json.dumps((json.load(sys.stdin).get("office") or {}).get("inbox"))[:300])')"; fail=1; }
sleep 2; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: helper asks to run a restricted task' && echo "  ok   notification: helper asks to run a restricted task" || { echo "  FAIL inbox notification: $(sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | grep notify: | tail -3)"; fail=1; }
IID=$(maluctl office inbox --json | python3 -c 'import json,sys; print([i["id"] for i in json.load(sys.stdin)["items"] if i["kind"]=="decision_needed"][0])' 2>/dev/null)
# the session answers after `maluctl office inbox decide` (two vault reads and the office round trip, up to 60 s under TCG): past gdbus's 25 s default; one call, its output kept
out=$(gdbus call --session --timeout 120 --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.TaskDecide "$IID" approve "go ahead" 2>&1); echo "$out" | grep -q '"ok": true' && echo "  ok   TaskDecide on the bus: approve with a note" || { echo "  FAIL TaskDecide: $(echo "$out" | head -2)"; fail=1; }
for i in $(seq 1 40); do maluctl estate tasks "$TID2" 2>/dev/null | grep -q 'completed' && break; sleep 3; done
maluctl estate tasks "$TID2" | grep -q 'completed' && echo "  ok   the approved task ran and completed (the decision reached the agent as tasks/resume)" || { echo "  FAIL after approve: $(maluctl estate tasks "$TID2" 2>&1 | head -3); $(sudo -n journalctl -u maluos-agent@helper --no-pager | tail -3)"; fail=1; }
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/inbox -d '{"kind":"decision_needed","subject":"Deploy the hotfix tonight?","from":"agent:helpdesk"}' >/dev/null
for i in $(seq 1 24); do inbox_in_state "any(x['subject']=='Deploy the hotfix tonight?' for x in i.get('items') or [])" && break; sleep 5; done
inbox_in_state "any(x['subject']=='Deploy the hotfix tonight?' for x in i.get('items') or [])" && sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: Deploy the hotfix tonight?' && echo "  ok   /mock/inbox: the injected decision reaches the session state and a notification" || { echo "  FAIL injected inbox item"; fail=1; }
IID2=$(maluctl office inbox --json | python3 -c 'import json,sys; print([i["id"] for i in json.load(sys.stdin)["items"] if i["subject"]=="Deploy the hotfix tonight?"][0])' 2>/dev/null)
maluctl office inbox decide "$IID2" deny --note "not now" | grep -q 'decide deny' && curl -fsS --max-time 5 http://127.0.0.1:18080/mock/delegation | python3 -c "import json,sys; i=[x for x in json.load(sys.stdin)['inbox'] if x['id']==$IID2][0]; assert i['status']=='done' and i['decision']=='deny' and i['decision_note']=='not now' and i['answered_by']=='desk:41', i" 2>/dev/null && echo "  ok   maluctl office inbox decide deny --note: the office has the decision, signed by this desk's key" || { echo "  FAIL inbox decide: $(maluctl office inbox --all 2>&1 | tail -3)"; fail=1; }
maluctl office estate action test-node reboot 2>&1 | grep -q 'not_allowed' && echo "  ok   maluctl office estate action test-node reboot: refused not_allowed by the node" || { echo "  FAIL reboot action: $(maluctl office estate action test-node reboot 2>&1 | tail -2)"; fail=1; }
T0=$(systemctl show -p ActiveEnterTimestampMonotonic --value maluos-agent@helper.service)
maluctl office estate action test-node restart_agent helper --wait 60 | grep -q 'restart_agent helper on test-node: completed' && [ "$(systemctl show -p ActiveEnterTimestampMonotonic --value maluos-agent@helper.service)" != "$T0" ] && echo "  ok   maluctl office estate action restart_agent helper: the unit restarted (ActiveEnterTimestamp changed), the result ok" || { echo "  FAIL restart_agent: $(maluctl office estate action test-node restart_agent helper --wait 30 2>&1 | tail -2); $(sudo -n journalctl -u maluos-estate --no-pager | tail -3)"; fail=1; }
maluctl office inbox | grep -q 'result .*restart_agent helper on test-node: completed' && echo "  ok   the action's result is in the inbox" || { echo "  FAIL action result in inbox: $(maluctl office inbox 2>&1 | tail -3)"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-agents --self-test 2>&1); echo "$out" | grep -q 'directory [1-9]' && echo "$out" | grep -q 'personal agent absent' && echo "  ok   maluos-agents --self-test: the directory count, no personal agent yet" || { echo "  FAIL agents self-test: $(echo "$out" | tail -2)"; fail=1; }
sudo -n maluctl agent create me --personal --owner user:maluos >/dev/null 2>&1 && sudo -n grep -q 'personal: true' /etc/maluos/agents/me.manifest.yaml && echo "  ok   maluctl agent create me --personal: the manifest says personal, capability personal" || { echo "  FAIL personal create: $(sudo -n maluctl agent create me --personal --owner user:maluos 2>&1 | tail -2)"; fail=1; }
python3 -c "import sys; sys.path.insert(0, '/usr/lib/maluos'); from maluos_vault_client import Vault; v=Vault(); gs={n: [g for g in v.grants(n) if g.get('grantee_ref')=='agent:me' and g.get('level')=='read' and g.get('expires_at')] for n in ('office-desk-token','office-desk-key')}; assert all(gs.values()), gs" 2>/dev/null && echo "  ok   the desk token and the desk key are granted to agent:me to read, for a week (it presents the token and signs with the key itself: a use-only delegation has no broker for that)" || { echo "  FAIL personal grants: $(maluctl secret info office-desk-token 2>&1 | tail -4)"; fail=1; }
for i in $(seq 1 30); do [ -S /run/maluos/agents/me/tasks.sock ] && break; sleep 2; done
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-agents --agent local:me --self-test 2>&1); echo "$out" | grep -q 'personal agent present (me)' && echo "  ok   maluos-agents --agent local:me --self-test: the personal agent present" || { echo "  FAIL agents self-test (me): $(echo "$out" | tail -2)"; fail=1; }
out=$(maluctl agent send me "ask helper to say pong" 2>&1); echo "$out" | grep -q 'from helper on server:57' && echo "  ok   maluctl agent send me \"ask helper …\": me sends an envelope to helper as the person (chain user:maluos > agent:me) and returns the answer with provenance" || { echo "  FAIL personal ask: $out; $(sudo -n journalctl -u maluos-agent@me --no-pager | tail -3)"; fail=1; }
curl -fsS --max-time 5 http://127.0.0.1:18080/mock/delegation | python3 -c "import json,sys; ts=[t for t in json.load(sys.stdin)['tasks'] if t['sender']['principal']=='agent:me']; assert ts and ts[-1]['state']=='completed' and [h['principal'] for h in ts[-1]['provenance']['chain']]==['user:maluos','agent:me','agent:helper'], ts[-1:]" 2>/dev/null && echo "  ok   the office recorded the personal agent's task: sender agent:me, the chain user:maluos > agent:me > agent:helper" || { echo "  FAIL personal task record"; fail=1; }
sudo -n maluctl agent remove me --purge >/dev/null 2>&1; sudo -n maluctl agent remove helper --purge >/dev/null 2>&1
for i in $(seq 1 45); do dsk_dir "not any(a['name'] in ('helper','me') for a in ag)" && break; sleep 2; done
dsk_dir "not any(a['name'] in ('helper','me') for a in ag)" && echo "  ok   agent remove: helper and me left the directory" || { echo "  FAIL directory after remove"; fail=1; }
# --- Phase 13 slice 3 on the desktop (docs/phase13-slice3-inference.md, "Test"): the loop on one machine. This host is both the desk (#41) and test-node (#57, the hub at
# 100.100.0.1): the desk's gateway rung estate:test-node dials this host's own listener over the overlay with the desk's inference key, and the serving side knows the desk as a peer
sudo -n maluctl gateway share on --when always >/dev/null 2>&1       # G1 set --when idle; the serving side's switch and the idle rule are step 3 below
sudo -n maluctl gateway expose --bind overlay >/dev/null 2>&1 && sudo -n maluctl gateway reload >/dev/null 2>&1       # port 11435, the port the facts report
sudo -n maluctl estate heartbeat --json 2>/dev/null | grep -q '"ok": true' && maluctl office heartbeat --json 2>/dev/null | grep -q '"ok": true' && echo "  ok   both memberships heartbeat with the gateway's facts (the node's and the desk's)" || { echo "  FAIL slice 3 heartbeats: $(sudo -n maluctl estate heartbeat 2>&1 | tail -1); $(maluctl office heartbeat 2>&1 | tail -1)"; fail=1; }
curl -fsS --max-time 5 http://127.0.0.1:18080/mock/inference | python3 -c "import json,sys; d=json.load(sys.stdin); f=d['facts']; assert 'server:57' in f and 'desk:41' in f and f['server:57']['share'] and any(m['name']=='mock-7b' for m in f['server:57']['models']), list(f); m={x['ref']: x for x in d['members']}; assert m['server:57']['published'] and m['desk:41']['published'], m; print('  ok   the office holds both members\' facts and publishes both (shared, online, an overlay address each)')" 2>/dev/null || { echo "  FAIL /mock/inference: $(curl -s http://127.0.0.1:18080/mock/inference | head -c 500)"; fail=1; }
out=$(maluctl office inference --refresh 2>&1); echo "$out" | grep -q 'test-node .*server:57 .*100.100.0.1:11435' && [ -f /run/maluos/office/inference.json ] && echo "  ok   maluctl office inference --refresh: the office publishes test-node to the desk at 100.100.0.1:11435; the cache under /run/maluos/office is the owner's" || { echo "  FAIL office inference: $out; $(ls -la /run/maluos/office/ 2>&1)"; fail=1; }
out=$(sudo -n maluctl estate inference --refresh 2>&1); echo "$out" | grep -q 'test-desk .*desk:41' && echo "  ok   maluctl estate inference --refresh: the node is given the desk's contribution (a desk's GPU serves servers, never other desks)" || { echo "  FAIL estate inference: $out"; fail=1; }
sudo -n maluctl gateway reload >/dev/null 2>&1
for i in $(seq 1 30); do maluctl gateway estate 2>/dev/null | grep -q 'estate:test-node .* healthy' && break; sleep 2; done
maluctl gateway estate | grep -q 'backend:     estate:test-node  server:57  http://100.100.0.1:11435  healthy  models mock-13b, mock-7b, mock-embed' && maluctl gateway estate | grep -q 'this host is server:57 .*node+desk' && echo "  ok   maluctl gateway estate: the rung estate:test-node from the desk's cache beside the node's (one gateway, both memberships), paired with the desk's inference key, healthy over the overlay" || { echo "  FAIL gateway estate: $(maluctl gateway estate 2>&1 | head -5); $(sudo -n journalctl -u maluos-gateway --no-pager | grep -i 'estate' | tail -4)"; fail=1; }
out=$(maluctl gateway chat "over the estate" --model mock-7b --prefer estate --envelope env_abcdef0123456789 2>&1); echo "$out" | grep -q 'mock reply to: over the estate' && echo "  ok   maluctl gateway chat --prefer estate: served through estate:test-node (the desk's rung, the overlay, this host's listener, the mock)" || { echo "  FAIL chat over the estate: $out; $(maluctl gateway routes --limit 2 2>&1)"; fail=1; }
sudo -n maluctl gateway usage --envelope env_abcdef0123456789 2>/dev/null | grep -q '2 call(s) under envelope' && sudo -n maluctl gateway usage --envelope env_abcdef0123456789 | grep -q 'node:desk:41' && echo "  ok   both ledger rows under the envelope: the desk's call (estate:test-node) and the serving row as node:desk:41 with the origin request" || { echo "  FAIL usage --envelope: $(sudo -n maluctl gateway usage --envelope env_abcdef0123456789 2>&1 | tail -4)"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select detail->'peer'->>'node' || ' ' || (detail->>'origin_request') from maluos.maluos_ledger where event='model.call' and principal_ref='node:desk:41' order by ledger_id desc limit 1" | grep -q '^desk:41 mg-' && echo "  ok   the serving row's detail: the peer and the origin request (one request id across the estate)" || { echo "  FAIL serving row detail"; fail=1; }
out=$(maluctl gateway chat "fast over the estate" --model fast --prefer estate 2>&1); echo "$out" | grep -q 'mock reply to: fast over the estate' && sudo -n -u postgres psql -Atd maludb -c "select route::text from maluos.maluos_ledger where event='model.call' and purpose='/v1/chat/completions' and backend='estate:test-node' order by ledger_id desc limit 1" | grep -q 'tier fast via the estate' && echo "  ok   a tier names the estate rung after the catalogue's own (--model fast --prefer estate: tier fast via the estate)" || { echo "  FAIL tier via the estate: $out"; fail=1; }
# restricted content: the caller's own egress policy (internal by default) skips the estate rung first, so the call is served locally (--prefer estate is a preference);
# with the person's egress widened to restricted, the kernel's ceiling on the rung (internal) skips it: classification. The ledger's route says which.
ROUTE_SQL="select route::text from maluos.maluos_ledger where event='model.call' and purpose='/v1/chat/completions' order by ledger_id desc limit 1"
out=$(maluctl gateway chat "secret" --model mock-7b --prefer estate --sensitivity restricted 2>&1); echo "$out" | grep -q 'mock reply to: secret' && sudo -n -u postgres psql -Atd maludb -c "$ROUTE_SQL" | grep -q '"backend": "estate:test-node", "skipped": "sensitivity:restricted>internal"' && sudo -n maluctl gateway policy set --principal user:maluos --egress restricted >/dev/null 2>&1 && sleep 1 && out2=$(maluctl gateway chat "secret again" --model mock-7b --prefer estate --sensitivity restricted 2>&1) && echo "$out2" | grep -q 'mock reply to: secret again' && sudo -n -u postgres psql -Atd maludb -c "$ROUTE_SQL" | grep -q '"backend": "estate:test-node", "skipped": "classification:restricted>internal"' && echo "  ok   restricted content never takes a rung whose ceiling is internal: the person's egress policy skips it first (served locally), with egress widened the kernel's ceiling does (classification)" || { echo "  FAIL restricted over the estate: $out; $out2; $(sudo -n -u postgres psql -Atd maludb -c "$ROUTE_SQL" 2>&1 | cut -c1-500)"; fail=1; }
sudo -n maluctl gateway policy rm --principal user:maluos >/dev/null 2>&1
# step 3: the serving side's switch and the idle rule, seen from the caller
sudo -n maluctl gateway share off >/dev/null 2>&1; sleep 1
for i in 1 2 3 4 5 6; do out=$(maluctl gateway chat "x" --model mock-7b --prefer estate 2>&1); echo "$out" | grep -q 'not_shared\|backend_unavailable' && break; sleep 3; done   # the switch reaches the serving side within a moment, not within the one second above on a slow host
echo "$out" | grep -q 'not_shared\|backend_unavailable' && echo "  ok   share off on the serving side: the call through the estate rung is refused not_shared (the local rung was skipped by --prefer estate)" || { echo "  FAIL not_shared through the rung: $out"; fail=1; }
sudo -n maluctl gateway share on --when idle >/dev/null 2>&1; sleep 1
# the serving side's switch travels by heartbeat and the directory publishes only a sharing node: wait for the rung to be back in the desk's cache
rung_back() { for j in $(seq 1 40); do [ -f /run/maluos/session/idle ] && maluctl gateway status 2>/dev/null | grep -q 'estate:test-node' && return 0; sleep 3; done; return 1; }
rung_back || echo "  info the estate rung did not come back within 2 min: $(maluctl gateway status 2>&1 | grep -c estate:) estate line(s)"
out=$(maluctl gateway chat "while idle" --model mock-7b --prefer estate 2>&1); echo "$out" | grep -q 'mock reply to: while idle' && echo "  ok   share on --when idle with the session's idle mark: shared again" || { echo "  FAIL idle share: $out; $(ls -la /run/maluos/session/ 2>&1)"; fail=1; }
# the mark removed by hand stands for input; the session has seen none and puts it back at its next 30 s poll (it rewrites the file each poll),
# so the removal comes right after a rewrite (the mtime moved) and the call has the whole poll to land in the gap (three tries)
for i in 1 2 3; do
  rung_back; sudo -n rm -f /run/maluos/session/idle; out=$(maluctl gateway chat "x" --model mock-7b --prefer estate 2>&1)
  echo "$out" | grep -q 'not_shared\|backend_unavailable' && break
  sudo -n -u postgres psql -Atd maludb -c "$ROUTE_SQL" | grep -q '"backend": "estate:test-node", "skipped": "not_shared"' && { out="the route: estate:test-node skipped not_shared (the directory already knew)"; break; }
  sleep 5
done
echo "$out" | grep -q 'not_shared\|backend_unavailable' && echo "  ok   the mark gone (input): the next call is refused not_shared (by the serving side, or the directory already said so)" || { echo "  FAIL after the mark: $out; route: $(sudo -n -u postgres psql -Atd maludb -c "$ROUTE_SQL" 2>&1 | head -c 300)"; fail=1; }
for i in $(seq 1 30); do [ -f /run/maluos/session/idle ] && break; sleep 3; done
[ -f /run/maluos/session/idle ] && echo "  ok   the session restores the mark within its next measurement (it has seen no input)" || { echo "  FAIL the session did not restore the idle mark: $(sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | grep idle: | tail -3)"; fail=1; }
echo "  info idle journal: $(sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep 'idle:' | tail -5 | cut -c1-150 | tr '\n' '|')"
sudo -n maluctl gateway share on --when always >/dev/null 2>&1; sleep 1
# the scheduler entitlement: the mock places; the route says placed; without it, plain
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/editions -d '{"scheduler": true}' >/dev/null
sudo -n maluctl estate inference --refresh >/dev/null 2>&1; maluctl office inference --refresh 2>/dev/null | grep -q 'editions scheduler; placement by the kernel' && sudo -n maluctl gateway reload >/dev/null 2>&1 && sleep 1 && maluctl gateway estate | grep -q 'editions scheduler .*placement by the kernel' && echo "  ok   the entitlement reaches the desk's cache and the gateway (editions scheduler, the place URL)" || { echo "  FAIL editions: $(maluctl office inference 2>&1 | head -2); $(maluctl gateway estate 2>&1 | head -1)"; fail=1; }
out=$(maluctl gateway chat "placed" --model mock-7b --prefer estate 2>&1); echo "$out" | grep -q 'mock reply to: placed' && sudo -n -u postgres psql -Atd maludb -c "select route::text || ' ' || coalesce(detail->'placement'->>'reason', '-') from maluos.maluos_ledger where event='model.call' and purpose='/v1/chat/completions' and backend='estate:test-node' order by ledger_id desc limit 1" | grep -q '"taken": true, "reason": "direct placed", "backend": "estate:test-node"}.* placed' && curl -fsS --max-time 5 http://127.0.0.1:18080/mock/inference | python3 -c "import json,sys; p=json.load(sys.stdin)['placements']; assert p and p[-1]['caller']=='desk:41' and p[-1]['backend']=='server:57' and p[-1]['model']=='mock-7b', p" 2>/dev/null && echo "  ok   with the entitlement the gateway asks the office to place the call (its inference key): the office chose server:57, the route says placed" || { echo "  FAIL placement: $out; $(sudo -n -u postgres psql -Atd maludb -c "select route::text || ' ' || coalesce((detail->'placement')::text, '-') from maluos.maluos_ledger where event='model.call' and purpose='/v1/chat/completions' order by ledger_id desc limit 1" 2>&1 | cut -c1-400); $(curl -s http://127.0.0.1:18080/mock/inference | python3 -c 'import json,sys; print(json.load(sys.stdin)["placements"][-2:])' 2>&1); $(sudo -n journalctl -u maluos-gateway --no-pager | grep -i 'place' | tail -3)"; fail=1; }
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/editions -d '{"scheduler": false}' >/dev/null
sudo -n maluctl estate inference --refresh >/dev/null 2>&1; maluctl office inference --refresh >/dev/null 2>&1; sudo -n maluctl gateway reload >/dev/null 2>&1; sleep 1
out=$(maluctl gateway chat "ranked" --model mock-7b --prefer estate 2>&1); echo "$out" | grep -q 'mock reply to: ranked' && sudo -n -u postgres psql -Atd maludb -c "select route::text from maluos.maluos_ledger where event='model.call' and purpose='/v1/chat/completions' and backend='estate:test-node' order by ledger_id desc limit 1" | grep -q '"taken": true, "reason": "direct", "backend": "estate:test-node"' && echo "  ok   Community again: the gateway ranks the estate's rungs itself (the route neither placed nor ranked)" || { echo "  FAIL community route: $out; $(sudo -n -u postgres psql -Atd maludb -c "select route::text from maluos.maluos_ledger where event='model.call' and purpose='/v1/chat/completions' order by ledger_id desc limit 1" 2>&1 | cut -c1-300); $(maluctl gateway estate 2>&1 | head -1)"; fail=1; }
# the session re-reads the gateway every 20 s and the rungs were just reloaded: wait for its view to catch up (run 5 of the chain: a race)
for i in $(seq 1 15); do state | python3 -c "import json,sys; s=json.load(sys.stdin); e=s['gateway']['estate']; b=[x for x in e['backends'] if x['name']=='estate:test-node']; assert b and b[0]['healthy'] and b[0]['node']=='server:57' and 'mock-7b' in b[0]['models'], e; pass" >/dev/null 2>&1 && break; sleep 3; done
state | python3 -c "import json,sys; s=json.load(sys.stdin); e=s['gateway']['estate']; b=[x for x in e['backends'] if x['name']=='estate:test-node']; assert b and b[0]['healthy'] and b[0]['node']=='server:57' and 'mock-7b' in b[0]['models'], e; print('  ok   session state: gateway.estate lists estate:test-node for the Network tab')" 2>/dev/null || { echo "  FAIL estate in the session state: $(state | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["gateway"].get("estate"))[:300])')"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 gnome-system-monitor --maluos-self-test 2>&1); echo "$out" | grep -qE 'Network: node [a-z0-9-]+, [0-9]+ lanes, 0 paired, [0-9]+ keys, exposed, estate 2 nodes \([0-9]+ online, [0-9]+ alerts?\)(, inference [0-9]+ backends? \([0-9]+ queued\))?(, actions)?, [12] estate backends?' && echo "  ok   the Network tab (self-test): the estate's backends beside the paired nodes" || { echo "  FAIL network tab with estate backends: $(echo "$out" | tail -2)"; fail=1; }
# Phase 13 G5b: the tabs' estate half. office.estate.inference in the session's state (the office's inference contract as a system
# manager's desk reads it: test-node's shared GPU with its queue snapshot), read with the heartbeat; the self-test's Estate summary;
# one action through the Network tab's own path (MALUOS_SELF_TEST_ACTION), answered by this node through the mock office
inf_in_state() { state | python3 -c "import json,sys; i=((json.load(sys.stdin).get('office') or {}).get('estate') or {}).get('inference') or {}; b=i.get('backends') or []; sys.exit(0 if i.get('available') and ($1) else 1)" 2>/dev/null; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.OfficeAction heartbeat >/dev/null 2>&1
for i in $(seq 1 24); do inf_in_state "any(x['node']=='server:57' and 'mock-7b' in x['models'] and 'queued' in x['queue'] and 'interactive' in x['expected_wait_s'] for x in b)" && break; sleep 5; done
inf_in_state "any(x['node']=='server:57' and 'mock-7b' in x['models'] and 'queued' in x['queue'] and 'interactive' in x['expected_wait_s'] for x in b) and i['counts']['backends']>=1" && echo "  ok   session state: office.estate.inference lists server:57's shared GPU with its queue snapshot and waits (G5b)" || { echo "  FAIL office.estate.inference in state: $(state | python3 -c "import json,sys; print(json.dumps(((json.load(sys.stdin).get('office') or {}).get('estate') or {}).get('inference'))[:400])" 2>&1)"; fail=1; }
T1=$(systemctl show -p ActiveEnterTimestampMonotonic --value maluos-agent@desk.service)
out=$(WAYLAND_DISPLAY=wayland-0 MALUOS_SELF_TEST_ACTION=test-node:restart_agent:desk timeout 300 gnome-system-monitor --maluos-self-test 2>&1)
echo "$out" | grep -qE 'self-test ok: .*Network: node [a-z0-9-]+, .*estate 2 nodes \([0-9]+ online, [0-9]+ alerts?\), inference [1-9] backends? \([0-9]+ queued\), actions, [12] estate backends?.*; Estate: [1-9] nodes, [0-9]+ queued, [0-9]+ running' && echo "  ok   the Network and Queue tabs (self-test): the estate's shared GPUs with their queue snapshots, the node menus (actions), the Estate summary (G5b)" || { echo "  FAIL G5b self-test summary: $(echo "$out" | grep 'self-test' | tail -2)"; fail=1; }
echo "$out" | grep -qE 'self-test action: restart_agent desk on test-node: action a_[0-9a-f]+ restart_agent desk on test-node: completed' && [ "$(systemctl show -p ActiveEnterTimestampMonotonic --value maluos-agent@desk.service)" != "$T1" ] && echo "  ok   one action from the Network tab's path (MALUOS_SELF_TEST_ACTION): restart_agent desk on test-node completed through the office and the unit restarted (G5b)" || { echo "  FAIL G5b action from the tab: $(echo "$out" | grep -E 'self-test action|maluctl' | tail -2)"; fail=1; }
sudo -n systemctl stop maluos-mock-ollama-5 2>/dev/null
# --- Phase 13 slice 4 on the desktop (docs/phase13-slice4-memory.md, "Test"): the HR scenario on one host, which is desk:41 and server:57 (the hub at
# 100.100.0.1). The face serves the estate on 100.100.0.1:11437; the desk's --estate recall asks this host's own face over the overlay with a self-envelope
# signed by the desk's key; the serving side knows the desk as a peer for its owner's department (dept:3 in the mock) and org
installed maluos-memory && echo "  ok   maluos-memory" || { echo "  FAIL maluos-memory"; fail=1; }
systemctl is-active --quiet maluos-memory.socket && maluctl memory whoami | grep -q 'principal: user:maluos' && echo "  ok   the memory face answers over its socket; the person is user:maluos" || { echo "  FAIL memory face: $(maluctl memory whoami 2>&1 | tail -2)"; sudo -n journalctl -u maluos-memory --no-pager | tail -5; fail=1; }
maluctl memory status | grep -q 'shared nothing' && maluctl memory status | grep -q 'not exposed' && echo "  ok   maluctl memory status: nothing shared, not exposed (the defaults)" || { echo "  FAIL memory status: $(maluctl memory status 2>&1 | head -3)"; fail=1; }
out=$(sudo -n maluctl memory keys 2>&1); echo "$out" | grep -q 'estate-node-key' && echo "$out" | grep -q 'office-desk-key' && maluctl memory status | grep -q 'signing key .*estate-node-key readable' && maluctl memory status | grep -q 'signing key .*office-desk-key readable' && echo "  ok   sudo maluctl memory keys: the face reads both memberships' signing keys (the node's, the desk owner's)" || { echo "  FAIL memory keys: $out; $(maluctl memory status | grep signing)"; fail=1; }
sudo -n maluctl memory expose --bind overlay | grep -q 'listening on 100.100.0.1:11437' && curl -fsS --max-time 3 http://100.100.0.1:11437/memory/v1/health | grep -q '"node": "server:57"' && echo "  ok   sudo maluctl memory expose --bind overlay: the face serves the estate on 100.100.0.1:11437" || { echo "  FAIL memory expose: $(sudo -n maluctl memory expose --bind overlay 2>&1 | tail -1)"; fail=1; }
sudo -n maluctl memory share dept:3 org --max internal | grep -q 'shared: dept:3, org; ceiling internal' && echo "  ok   sudo maluctl memory share dept:3 org: the guest principal reads both (the facts say so)" || { echo "  FAIL memory share: $(sudo -n maluctl memory share dept:3 org 2>&1 | tail -1)"; fail=1; }
mock_mem() { curl -fsS --max-time 5 http://127.0.0.1:18080/mock/memory | python3 -c "import json,sys; d=json.load(sys.stdin); f=d['facts'].get('server:57') or {}; g=d['facts'].get('desk:41') or {}; sys.exit(0 if ($1) else 1)" 2>/dev/null; }
for i in $(seq 1 30); do mock_mem "f.get('shared')==['dept:3','org'] and f.get('port')==11437" && break; sleep 2; done
mock_mem "f.get('shared')==['dept:3','org'] and f.get('port')==11437 and f.get('max_classification')=='internal'" && echo "  ok   the node's heartbeat carries the memory facts (shared dept:3 and org, port 11437, ceiling internal); /mock/memory shows them" || { echo "  FAIL memory facts at the mock: $(curl -fsS --max-time 5 http://127.0.0.1:18080/mock/memory | head -c 400)"; fail=1; }
# step 2: writes as principals. agent hr (owned by the sudo user) writes dept:3 and org; the person (no grant) may not read dept:3
sudo -n maluctl agent create hr --exec "/usr/bin/python3 /usr/lib/maluos/maluos-agent-demo.py" --scope dept:3:write --scope org:write --max-classification restricted --tiers fast --capability hr --no-start >/dev/null 2>&1 \
  && sudo -n -u postgres psql -Atd maludb -c "set role maluos; set search_path to maluos, maludb_core, public; select scope || ':' || access_level from maludb_principal_scope where principal_ref='agent:hr' and revoked_at is null order by 1" | tr '\n' ' ' | grep -q 'dept:3:write org:write' \
  && sudo -n -u postgres psql -Atd maludb -c "set role maluos; set search_path to maluos, maludb_core, public; select max_sensitivity from maludb_principal where principal_ref='agent:hr'" | grep -q '^restricted$' \
  && echo "  ok   maluctl agent create hr --scope dept:3:write --scope org:write --max-classification restricted: the grants as written, the ceiling on the principal" || { echo "  FAIL agent create hr scopes: $(sudo -n -u postgres psql -Atd maludb -c "set role maluos; select scope, access_level from maludb_principal_scope where principal_ref='agent:hr'" 2>&1)"; fail=1; }
maluctl memory remember "Alex completed forklift training on 2026-09-01" --scope dept:3 --confidence 0.9 --source hr:training/118 --detail '{"certificate": "FL-2231"}' --as agent:hr | grep -q 'in dept:3 (note) as agent:hr' && echo "  ok   maluctl memory remember --as agent:hr (its owner): a dept:3 note with confidence, source and detail" || { echo "  FAIL memory remember: $(maluctl memory remember x --scope dept:3 --as agent:hr 2>&1 | tail -1)"; fail=1; }
maluctl memory remember "Alex has a lifting restriction until December" --scope dept:3 --sensitivity restricted --as agent:hr | grep -q 'in dept:3 (note) as agent:hr' && echo "  ok   a restricted note within the agent's ceiling" || { echo "  FAIL restricted note: $(maluctl memory remember x --scope dept:3 --sensitivity restricted --as agent:hr 2>&1 | tail -1)"; fail=1; }
sudo -n maluctl agent create lowhr --exec "/usr/bin/python3 /usr/lib/maluos/maluos-agent-demo.py" --scope dept:3:write --no-start >/dev/null 2>&1
maluctl memory remember x --scope dept:3 --sensitivity restricted --as agent:lowhr 2>&1 | grep -q 'classification' && echo "  ok   a restricted note above an agent's internal ceiling is refused classification" || { echo "  FAIL ceiling on write: $(maluctl memory remember x --scope dept:3 --sensitivity restricted --as agent:lowhr 2>&1 | tail -1)"; fail=1; }
sudo -n maluctl agent remove lowhr --purge >/dev/null 2>&1
! maluctl memory recall lifting --as agent:hr | grep -q 'lifting restriction' && maluctl memory recall lifting --as agent:hr --classification restricted | grep -q 'lifting restriction' && echo "  ok   the restricted note is hidden at internal and shown at restricted (within the agent's ceiling)" || { echo "  FAIL restricted recall: $(maluctl memory recall lifting --as agent:hr --classification restricted 2>&1 | head -2)"; fail=1; }
maluctl memory remember "Q3 safety: zero incidents, two near misses on the loading dock" --scope org --kind summary --title "Q3 safety" --as agent:hr | grep -q 'in org (summary) as agent:hr' && echo "  ok   an org summary (kind summary) as agent:hr" || { echo "  FAIL org summary"; fail=1; }
maluctl memory remember x --scope dept:9 --as agent:hr 2>&1 | grep -q 'scope_write' && echo "  ok   a dept:9 write is refused scope_write (no grant)" || { echo "  FAIL dept:9 write: $(maluctl memory remember x --scope dept:9 --as agent:hr 2>&1 | tail -1)"; fail=1; }
maluctl memory recall forklift --as agent:hr | grep -q 'dept:3  note  internal  confidence 0.9  source hr:training/118  by agent:hr' && maluctl memory recall forklift --as agent:hr --detail | grep -q 'FL-2231' && ! maluctl memory recall forklift --as agent:hr | grep -q FL-2231 && echo "  ok   recall as agent:hr: the claim with its provenance; the detail only on --detail" || { echo "  FAIL recall as hr: $(maluctl memory recall forklift --as agent:hr 2>&1 | head -3)"; fail=1; }
maluctl memory recall forklift --scope dept:3 2>&1 | grep -q 'forbidden' && echo "  ok   the person (no grant on dept:3) is refused forbidden" || { echo "  FAIL person recall: $(maluctl memory recall forklift --scope dept:3 2>&1 | tail -1)"; fail=1; }
# slice 4b: semantic recall. The face embeds through the gateway's socket as user:maluos-memory (the mock Ollama's synonym-aware embeddings: 256 dims).
# The mock Ollama behind the gateway's mock backend was stopped after slice 3 (run 6 of the chain: no eligible backend): started again for this block
sudo -n systemd-run --quiet --unit maluos-mock-ollama-6 -p User=nobody -p Environment=PYTHONPATH=/usr/lib/maluos /usr/bin/python3 -m maluos_gateway.mock_ollama --port 11999
for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:11999/api/tags >/dev/null 2>&1 && break; sleep 1; done
for i in $(seq 1 30); do sudo -n maluctl gateway reload >/dev/null 2>&1; maluctl gateway status | grep -q 'backend:     mock  mock .* healthy' && break; sleep 2; done
sudo -n maluctl memory embed mock-embed 2>&1 | grep -q 'embedding: mock-embed via gateway (dim 256, space memory/mock-embed)' && echo "  ok   sudo maluctl memory embed mock-embed: the face embeds through the gateway (probed, dim 256, space memory/mock-embed)" || { echo "  FAIL memory embed: $(sudo -n maluctl memory embed mock-embed 2>&1 | tail -2)"; sudo -n maluctl gateway status 2>&1 | head -5; fail=1; }
sudo -n maluctl memory embed --backfill | grep -qE 'embedded [1-9], failed 0, remaining 0' && maluctl memory embed | grep -qE '([1-9]) of \1 memories embedded' && echo "  ok   --backfill: the notes written before the model carry vectors now; maluctl memory embed counts them" || { echo "  FAIL backfill: $(sudo -n maluctl memory embed --backfill 2>&1 | tail -1); $(maluctl memory embed 2>&1 | tail -2)"; fail=1; }
maluctl memory recall "lift truck certification" --as agent:hr | grep -q 'forklift training' && maluctl memory recall "lift truck certification" --as agent:hr | grep -qE 'semantic 0\.[0-9]+' && ! maluctl memory recall "lift truck certification" --as agent:hr | grep -q 'lifting restriction' && echo "  ok   recall by meaning: 'lift truck certification' finds the forklift note (semantic, scored); the restricted note stays hidden at internal" || { echo "  FAIL semantic recall: $(maluctl memory recall 'lift truck certification' --as agent:hr 2>&1 | head -3)"; fail=1; }
maluctl memory remember "Sam renewed the forklift certificate" --scope dept:3 --as agent:hr | grep -q '(with its vector)' && maluctl memory recall "lift truck" --as agent:hr | grep -q 'Sam renewed' && echo "  ok   a new memory is embedded as it is written and found by meaning at once" || { echo "  FAIL embed on write: $(maluctl memory recall 'lift truck' --as agent:hr 2>&1 | head -3)"; fail=1; }
SID=$(maluctl memory recall "Sam renewed" --as agent:hr --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["claims"][0]["id"])' 2>/dev/null); maluctl memory forget "${SID:-0}" --as agent:hr >/dev/null 2>&1
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='model.call' and principal_ref='user:maluos-memory'" | grep -qE '^[1-9]' && sudo -n maluctl memory usage --since 1h | grep -q 'memory.embed' && echo "  ok   the gateway's ledger: the embeddings are model calls by user:maluos-memory; the face's ledger has the probe and the backfill" || { echo "  FAIL embed ledger: $(sudo -n -u postgres psql -Atd maludb -c "select event, principal_ref, status, reason from maluos.maluos_ledger where principal_ref='user:maluos-memory' order by ledger_id desc limit 3")"; fail=1; }
sudo -n -u postgres psql -Atd maludb -c "select count(*) from maluos.maluos_ledger where event='model.call' and principal_ref='user:maluos-memory' and detail->>'sensitivity'='restricted'" | grep -qE '^[1-9]' && sudo -n maluctl gateway usage --since 1h 2>/dev/null | grep -q 'user:maluos-memory' && echo "  ok   the restricted note was embedded as a restricted call (the gateway's egress policy and the rungs' ceilings apply: on this host or not at all)" || { echo "  FAIL restricted embed: $(sudo -n -u postgres psql -Atd maludb -c \"select status, detail->>'sensitivity', detail->>'route' from maluos.maluos_ledger where event='model.call' and principal_ref='user:maluos-memory'\" 2>&1 | head -5)"; fail=1; }
sudo -n systemctl stop maluos-mock-ollama-6 2>/dev/null
maluctl memory facts --json | python3 -c "import json,sys; f=json.load(sys.stdin); s={x['scope']: x for x in f['scopes']}; assert s['dept:3']['count']==2 and s['org']['kinds']=={'summary': 1} and 'agent:hr' not in s, f" 2>/dev/null && echo "  ok   maluctl memory facts: dept:3 holds 2, org 1 summary; the personal scope never listed" || { echo "  FAIL memory facts: $(maluctl memory facts 2>&1 | head -3)"; fail=1; }
# step 3: the holders and the peers each membership is published
out=$(maluctl office memory --refresh 2>&1); echo "$out" | grep -q 'test-node .*server:57 .*100.100.0.1:11437' && echo "$out" | grep -q 'dept:3' && ! echo "$out" | grep -q 'dept:9' && [ -f /run/maluos/office/memory.json ] && [ -f /run/maluos/office/memory-peers.json ] && echo "  ok   maluctl office memory --refresh: the office publishes test-node (dept:3, org) to the desk, never dept:9; the caches under /run/maluos/office" || { echo "  FAIL office memory: $out"; fail=1; }
echo "$out" | grep -q 'office: .*self' && echo "$out" | grep -q 'dept:3' && echo "  ok   the office's own scopes for the desk: self, org and the owner's department" || { echo "  FAIL office scopes: $out"; fail=1; }
out=$(sudo -n maluctl estate memory --refresh --peers 2>&1); echo "$out" | grep -q 'test-desk .*desk:41 .*dept:3' && echo "$out" | grep -q 'org' && [ -f /run/maluos/estate/memory-peers.json ] && echo "  ok   sudo maluctl estate memory --refresh: the node is told its peers (the desk, for dept:3 and org, with its key)" || { echo "  FAIL estate memory: $out"; fail=1; }
sudo -n maluctl memory reload >/dev/null 2>&1
# this host is desk:41 and server:57: the desk is published the node as a holder; the desk itself is published to nobody (slice 4b, decision 9: one machine id,
# one face, published as the node); a host never asks itself (ask_self false, the default)
maluctl memory status | grep -q 'holders:   0 published' && maluctl memory status | grep -q 'peers:     [1-9]' && maluctl memory recall forklift --scope dept:3 --estate --as agent:hr --json 2>&1 | python3 -c "import json,sys; r=json.load(sys.stdin); assert r['holders']==[] and r['holders_failed']==[] and all(c['local'] for c in r['claims']), r" 2>/dev/null \
  && echo "  ok   a host never asks itself: server:57 (published through the desk) is not a holder, desk:41 is published to nobody; --estate asks nobody" || { echo "  FAIL self as holder: $(maluctl memory status | grep -E 'holders|peers')"; fail=1; }
sudo -n python3 -c "import yaml; p='/etc/maluos/memory.yaml'; d=yaml.safe_load(open(p)) or {}; d['ask_self']=True; d['fanout_s']=15; open(p,'w').write(yaml.safe_dump(d, sort_keys=True))" && sudo -n maluctl memory reload >/dev/null 2>&1   # fanout_s: two parallel queries at an emulated CPU
maluctl memory status | grep -q 'holders:   1 published to this host: test-node' && maluctl memory status | grep -q 'peers:     [1-9]' && echo "  ok   ask_self: true (the one-host proof): the node identity is a holder now (the desk identity never: one host, one face); the peers from both memberships' caches" || { echo "  FAIL memory status caches: $(maluctl memory status | grep -E 'holders|peers')"; fail=1; }
# step 4: the federated query, as agent hr: this host asks itself over the overlay, server:57 with a self-envelope signed by the desk's key
# (the desk's holders cache); the serving side verifies the desk from its peers cache (the local test asks both ways)
out=$(maluctl memory recall "forklift training" --scope dept:3 --estate --as agent:hr --json 2>&1); err=$(echo "$out" | python3 -c "
import json,sys; r=json.load(sys.stdin); assert r['holders']==['server:57'] and r['holders_failed']==[], (r['holders'], r['holders_failed'])
rem=[c for c in r['claims'] if not c['local']]; assert len(rem)==1 and rem[0]['holder']=='server:57', rem
for c in rem: assert c['scope']=='dept:3' and c['confidence']==0.9 and c['source']['ref']=='hr:training/118' and 'detail' not in c and 'payload' not in c, c
assert any(c['local'] for c in r['claims']) and r['scopes_read']==['dept:3'], r" 2>&1) && echo "  ok   recall --estate: the node identity answered this host's self-envelope signed by the desk key, with the claim (no detail), beside the local one" || { echo "  FAIL recall --estate: $(echo "$err" | tail -1 | head -c 700); output: $(echo "$out" | head -c 300)"; sudo -n journalctl -u maluos-memory --no-pager | tail -5; fail=1; }
maluctl memory recall lifting --scope dept:3 --estate --as agent:hr --json 2>&1 | python3 -c "import json,sys; r=json.load(sys.stdin); assert r['count']==0 and r['holders']==['server:57'], r" 2>/dev/null && echo "  ok   the restricted note never crosses the overlay (asked at internal, the holder answers nothing)" || { echo "  FAIL restricted over estate: $(maluctl memory recall lifting --scope dept:3 --estate --as agent:hr --json 2>&1 | head -c 400)"; fail=1; }
maluctl memory recall x --scope dept:9 --estate --as agent:hr 2>&1 | grep -q 'forbidden' && echo "  ok   --scope dept:9: refused on the caller's side (not a scope of the agent)" || { echo "  FAIL dept:9 estate"; fail=1; }
# step 5: the envelope, signed by hand with the desk's key, straight at the overlay listener
cat > /tmp/memq.py <<'EOP'
import json, sys, urllib.request, urllib.error
sys.path.insert(0, "/usr/lib/maluos")
from maluos_estate import envelope as E
priv = open("/tmp/desk.key").read()
mode = sys.argv[1]
def env(scopes, cls="internal", life=120, node="desk:41"):
    me = {"principal": "user:maluos", "node": node}
    e = E.make(dict(me, kind="human", member_id=1), me, {"node": "server:57"}, "memory", {"scopes": [s + ":read" for s in scopes], "classification": cls, "budget": {"usd": 0, "calls": 0}}, life_s=life)
    return E.sign(e, node, priv)
def call(body):
    req = urllib.request.Request("http://100.100.0.1:11437/memory/v1/query", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
if mode == "ok": st, d = call({"envelope": env(["dept:3"]), "scopes": ["dept:3"], "query": "forklift"})
elif mode == "tampered":
    e = env(["dept:3"]); e["purpose"] = "x"; st, d = call({"envelope": e, "scopes": ["dept:3"], "query": "forklift"})
elif mode == "replay":
    e = env(["org"]); call({"envelope": e, "scopes": ["org"], "query": "safety"}); st, d = call({"envelope": e, "scopes": ["org"], "query": "safety"})
elif mode == "authority": st, d = call({"envelope": env(["org"]), "scopes": ["dept:3"], "query": "forklift"})
elif mode == "expired": st, d = call({"envelope": env(["org"], life=-200), "scopes": ["org"], "query": "safety"})
elif mode == "restricted": st, d = call({"envelope": env(["dept:3"], cls="restricted"), "scopes": ["dept:3"], "query": "lifting", "classification": "restricted"})
print(st, json.dumps(d)[:300])
EOP
maluctl secret show office-desk-key > /tmp/desk.key 2>/dev/null; chmod 600 /tmp/desk.key
python3 /tmp/memq.py ok | grep -q '^200 .*"holder": "server:57"' && python3 /tmp/memq.py tampered | grep -q bad_signature && python3 /tmp/memq.py replay | grep -q '^409' && python3 /tmp/memq.py authority | grep -q 'does not cover dept:3' && python3 /tmp/memq.py expired | grep -q '^401' && python3 /tmp/memq.py restricted | grep -q '"classification"' \
  && echo "  ok   the envelope at the listener: a good one answers; tampered bad_signature, replayed 409, authority not covering forbidden, expired 401, restricted above the peer's ceiling classification" || { echo "  FAIL envelope gate: $(for m in ok tampered replay authority expired restricted; do python3 /tmp/memq.py $m 2>&1 | tail -1; done)"; fail=1; }
rm -f /tmp/desk.key
# step 6: the rules: deny kind:desk on dept:3 at server:57; a replicate rule on org
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/memory -d '{"subject": "kind:desk", "scope": "dept:3", "holder": 57, "allow": false, "note": "no desks on hr dept"}' >/dev/null
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/memory -d '{"subject": "kind:server", "scope": "dept:3", "holder": 41, "allow": false, "note": "and no servers at the desk (the one-host proof)"}' >/dev/null
out=$(maluctl office memory --refresh 2>&1); sudo -n maluctl estate memory --refresh >/dev/null 2>&1; sudo -n maluctl memory reload >/dev/null 2>&1
! echo "$out" | grep -q 'test-node .*dept:3' && echo "$out" | grep -q 'test-node .*org' && echo "  ok   a deny rule (kind:desk, dept:3, server:57): the desk keeps org from test-node, loses dept:3" || { echo "  FAIL deny rule: $out"; fail=1; }
maluctl memory recall forklift --scope dept:3 --estate --as agent:hr --json 2>&1 | python3 -c "import json,sys; r=json.load(sys.stdin); assert r['holders']==[] or any(f['error']=='forbidden' for f in r['holders_failed']), r" 2>/dev/null && echo "  ok   the holders are no longer asked for dept:3 (or refuse forbidden from their peers caches)" || { echo "  FAIL deny over estate: $(maluctl memory recall forklift --scope dept:3 --estate --as agent:hr --json 2>&1 | head -c 400)"; fail=1; }
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/memory -d '{"clear": true}' >/dev/null
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/memory -d '{"subject": "kind:desk", "scope": "org", "holder": 57, "allow": true, "replicate": true, "note": "desks copy the org summaries"}' >/dev/null
maluctl office memory --refresh >/dev/null 2>&1; sudo -n maluctl estate memory --refresh >/dev/null 2>&1; sudo -n maluctl memory reload >/dev/null 2>&1
maluctl office memory | grep -q 'org .*replicate' && echo "  ok   the rule removed and a replicate rule on org added: the desk's view says replicate" || { echo "  FAIL replicate rule: $(maluctl office memory 2>&1 | grep -i org)"; fail=1; }
out=$(sudo -n maluctl memory sync 2>&1); echo "$out" | grep -qE 'server:57 +org +written 1' && echo "  ok   sudo maluctl memory sync: the org summary copied from server:57 (this host, both sides) with its origin" || { echo "  FAIL memory sync: $out"; sudo -n journalctl -u maluos-memory --no-pager | tail -3; fail=1; }
maluctl memory recall safety --scope org --as agent:hr | grep -q '(copy of server:57#' && echo "  ok   a recall finds the copy with its origin beside the original" || { echo "  FAIL copy in recall: $(maluctl memory recall safety --scope org --as agent:hr 2>&1 | head -4)"; fail=1; }
CID=$(maluctl memory recall safety --scope org --as agent:hr --json | python3 -c 'import json,sys; print([c for c in json.load(sys.stdin)["claims"] if c.get("origin")][0]["id"])' 2>/dev/null)
maluctl memory forget "${CID:-0}" --as agent:hr 2>&1 | grep -q 'origin' && echo "  ok   forget on a replicated copy is refused origin" || { echo "  FAIL forget copy: $(maluctl memory forget "${CID:-0}" --as agent:hr 2>&1 | tail -1)"; fail=1; }
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/memory -d '{"clear": true}' >/dev/null
# step 7: the office as a holder, asked by the desk's owner with the desk token
out=$(maluctl office memory recall "office closes" 2>&1); echo "$out" | grep -q 'The office closes at 17:00 on Fridays' && echo "$out" | grep -qi 'coordinator' && echo "  ok   maluctl office memory recall: the office answers from its own memory (holder coordinator)" || { echo "  FAIL office recall: $out"; fail=1; }
maluctl office memory recall x --scope dept:9 2>&1 | grep -q 'forbidden' && maluctl office memory recall x --classification restricted 2>&1 | grep -q 'classification' && echo "  ok   the office refuses a department the owner is not in (forbidden) and restricted above its ceiling (classification)" || { echo "  FAIL office refusals: $(maluctl office memory recall x --scope dept:9 2>&1 | tail -1)"; fail=1; }
curl -fsS --max-time 5 http://127.0.0.1:18080/mock/memory | python3 -c "import json,sys; q=json.load(sys.stdin)['queries']; assert q and q[-1]['member']=='desk:41' and 'query' not in q[-1] and q[-1]['scopes'], q" 2>/dev/null && echo "  ok   the mock logged the query with its scopes and never the text" || { echo "  FAIL mock queries"; fail=1; }
# slice 4b: the office's Memory MCP published to the desk (endpoints.memory_mcp, /mcp/memory): the recall tool with the desk token, answered under the policy
DTOK=$(maluctl secret show office-desk-token 2>/dev/null)
curl -fsS --max-time 10 -X POST http://127.0.0.1:18080/mcp/memory -H "Authorization: Bearer $DTOK" -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"recall","arguments":{"query":"office closes"}}}' 2>/dev/null \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; d=json.loads(r['content'][0]['text']); assert 'org' in d['searched'] and 'self' in d['searched'] and d['desk']==41 and d['holder']=='coordinator' and any('17:00' in x['text'] for x in d['results']), d" 2>/dev/null \
  && curl -fsS --max-time 10 -X POST http://127.0.0.1:18080/mcp/memory -H "Authorization: Bearer $DTOK" -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":8,"method":"tools/list"}' 2>/dev/null | grep -q '"recall"' \
  && echo "  ok   the office's Memory MCP (/mcp/memory, endpoints.memory_mcp): the recall tool with the desk token answers the office's claims for the desk's scopes" || { echo "  FAIL memory mcp: $(curl -s --max-time 10 -X POST http://127.0.0.1:18080/mcp/memory -H "Authorization: Bearer $DTOK" -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"recall","arguments":{"query":"office closes"}}}' 2>&1 | head -c 400)"; fail=1; }
# step 8: a task: the personal agent recalls over the estate under its task's envelope; the task's provenance names the scopes read and the holders
sudo -n maluctl agent create me --personal --owner user:maluos --scope dept:3:read >/dev/null 2>&1
for i in $(seq 1 30); do [ -S /run/maluos/agents/me/tasks.sock ] && break; sleep 2; done
out=$(timeout 120 maluctl agent send me "what do we know about forklift training" 2>&1); echo "$out" | grep -q 'forklift' && echo "$out" | grep -q 'from server:57' && echo "  ok   maluctl agent send me 'what do we know about …': the personal agent answers from memory, naming the holder" || { echo "  FAIL agent memory task: $out"; sudo -n journalctl -u maluos-agent@me --no-pager | tail -5; fail=1; }
maluctl agent tasks me --json 2>/dev/null | python3 -c "import json,sys; ts=[t for t in json.load(sys.stdin) if 'forklift' in t['input']['text']]; p=ts[-1]['provenance']; assert 'dept:3' in p['scopes_read'] and 'server:57' in p.get('holders', []), p" 2>/dev/null && echo "  ok   the task's provenance: scopes_read dept:3, holders server:57" || { echo "  FAIL task provenance: $(maluctl agent tasks me --json 2>&1 | tail -c 400)"; fail=1; }
# step 9: the ledgers and the Agents app
sudo -n maluctl memory usage --since 1h | grep -q 'memory.query' && sudo -n maluctl memory usage --since 1h | grep -q 'memory.recall' && ! sudo -n maluctl memory usage --since 1h --json | grep -q 'forklift' && echo "  ok   sudo maluctl memory usage: the queries answered and asked, the scopes and the counts, never the text" || { echo "  FAIL memory usage: $(sudo -n maluctl memory usage --since 1h 2>&1 | head -3)"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 maluos-agents --agent local:hr --self-test 2>&1); echo "$out" | grep -qE 'self-test ok: .*memory [1-9][0-9]* claims' && echo "  ok   the Agents app's Memory page (self-test): agent hr's claims as its owner" || { echo "  FAIL agents memory self-test: $(echo "$out" | tail -2)"; fail=1; }
state | python3 -c "import json,sys; m=json.load(sys.stdin)['office']['memory']; assert m and m['holders']>=1 and 'org' in m['office_scopes'], m" 2>/dev/null && echo "  ok   session state: office.memory names the holders and the office's scopes" || { echo "  FAIL session office.memory: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin)["office"].get("memory"))')"; fail=1; }
sudo -n maluctl agent remove me --purge >/dev/null 2>&1; sudo -n maluctl agent remove hr --purge >/dev/null 2>&1
sudo -n maluctl memory unshare --all >/dev/null 2>&1; sudo -n maluctl memory unexpose >/dev/null 2>&1
# an agent that keeps failing: the report shows it, the office raises agent_down, the session notifies with Open Estate; removed, it clears
sudo -n maluctl agent create failing --exec /bin/false --scope org:read >/dev/null 2>&1 || echo "  warn agent create failing: $(sudo -n maluctl agent create failing --exec /bin/false --scope org:read 2>&1 | tail -1)"
for i in $(seq 1 90); do mock_node "any(x['kind']=='agent_down' and x['node_id']==57 and not x['cleared_at'] for x in a)" && break; sleep 2; done   # two reports, each a minute under emulation
curl -fsS --max-time 5 http://127.0.0.1:18080/mock/nodes | python3 -c "import json,sys; d=json.load(sys.stdin); a=[x for x in d['alerts'] if x['kind']=='agent_down' and not x['cleared_at']]; n=[x for x in d['nodes'] if x['id']==57][0]; assert a and 'failing' in a[0]['title'] and n['health']=='warning', (a, n['health']); print('  ok   a failing agent: the next report raised agent_down (%s), health warning' % a[0]['title'])" || { echo "  FAIL agent_down: $(curl -s http://127.0.0.1:18080/mock/nodes | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["alerts"], [a for a in d["nodes"][0].get("facts", {})])' | head -c 400)"; fail=1; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.OfficeAction heartbeat >/dev/null 2>&1
for i in $(seq 1 36); do estate_in_state "any(a['kind']=='agent_down' and not a['cleared_at'] for a in e['alerts'])" && break; sleep 5; done
estate_in_state "any(a['kind']=='agent_down' and not a['cleared_at'] for a in e['alerts']) and e['counts']['alerts']>=1" && echo "  ok   session state: the alert under office.estate" || { echo "  FAIL alert in state"; fail=1; }
sleep 2; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: test-node: agent failing' && echo "  ok   notification: test-node: agent failing … (Open Estate)" || { echo "  FAIL estate alert notification"; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | grep 'notify:' | tail -3; fail=1; }
sudo -n maluctl agent remove failing --purge >/dev/null 2>&1
for i in $(seq 1 90); do mock_node "all(x['cleared_at'] for x in a if x['kind']=='agent_down')" && break; sleep 2; done
curl -fsS --max-time 5 http://127.0.0.1:18080/mock/nodes | python3 -c "import json,sys; a=[x for x in json.load(sys.stdin)['alerts'] if x['kind']=='agent_down']; assert a and all(x['cleared_at'] for x in a), a; print('  ok   the agent removed: the next report cleared the alert (cleared_at set)')" || { echo "  FAIL alert clear"; fail=1; }
out=$(WAYLAND_DISPLAY=wayland-0 timeout 300 gnome-system-monitor --maluos-self-test 2>&1); echo "$out" | grep -qE 'Network: node [a-z0-9-]+, .*estate 2 nodes \(2 online, [0-9]+ alerts?\)' && echo "  ok   the Network tab's Estate group: 2 nodes, 2 online, from the live session" || { echo "  FAIL network tab estate: $(echo "$out" | tail -2)"; fail=1; }
sudo -n systemctl stop maluos-estate
mock_node "n['presence']=='offline' and n['health']=='offline'" && echo "  ok   systemctl stop maluos-estate: the office shows the node offline at once (the clean offline)" || { echo "  FAIL offline: $(curl -s http://127.0.0.1:18080/mock/nodes | head -c 200)"; fail=1; }
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.OfficeAction heartbeat >/dev/null 2>&1
for i in $(seq 1 24); do estate_in_state "any(n['id']==57 and n['presence']=='offline' for n in e['nodes'])" && break; sleep 5; done
sleep 2; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: test-node is offline' && echo "  ok   notification: test-node is offline" || { echo "  FAIL offline notification"; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service | grep 'notify:' | tail -2; fail=1; }
sudo -n systemctl start maluos-estate
for i in $(seq 1 15); do mock_node "n['presence']=='online'" && break; sleep 2; done
mock_node "n['presence']=='online' and all(x['cleared_at'] for x in a if x['kind']=='node_offline')" && echo "  ok   started again: online, node_offline cleared" || { echo "  FAIL back online: $(curl -s http://127.0.0.1:18080/mock/nodes | head -c 300)"; fail=1; }
sudo -n maluctl estate leave | grep -q 'left Mock Office: the office was told; node retired' && [ ! -f /etc/maluos/estate.yaml ] && ! systemctl is-active --quiet maluos-estate && ! sudo -n -u maluos-estate maluctl secret list 2>/dev/null | grep -q estate-node && curl -fsS --max-time 5 http://127.0.0.1:18080/mock/state | python3 -c "import json,sys; n=[x for x in json.load(sys.stdin)['nodes'] if x['id']==57][0]; assert n['status']=='retired'" && echo "  ok   sudo maluctl estate leave: told, the unit stopped, the files and the two secrets gone, the node retired" || { echo "  FAIL estate leave: $(sudo -n maluctl estate status 2>&1 | tail -2)"; fail=1; }
! ip link show estate >/dev/null 2>&1 && ! grep -q 'maluos-estate overlay' /etc/hosts && echo "  ok   leave took the desktop's overlay down" || { echo "  FAIL overlay after leave: $(ip -br link show estate 2>&1)"; fail=1; }
maluctl estate status | grep -q 'this desk is node #41 of Mock Office' && echo "  ok   maluctl estate status on a desk: its desk enrolment is its node record" || { echo "  FAIL estate status desk path: $(maluctl estate status 2>&1)"; fail=1; }
curl -fsS --max-time 5 -X POST http://127.0.0.1:18080/mock/retire -d '{"desk_id": 41}' >/dev/null
gdbus call --session --dest com.maluos.Session --object-path /com/maluos/Session --method com.maluos.Session1.OfficeAction heartbeat >/dev/null 2>&1
for i in $(seq 1 24); do office_is retired && break; sleep 5; done
office_is retired && echo "  ok   the office retired the desk: the session sees it (410 on the next heartbeat)" || { echo "  FAIL retired state: $(state | python3 -c 'import json,sys; print(json.load(sys.stdin).get("office"))' | head -c 300)"; fail=1; }
sleep 2; sudo -n journalctl -b --no-pager _SYSTEMD_USER_UNIT=maluos-desktop-session.service 2>/dev/null | grep -q 'notify: The office retired this desk' && echo "  ok   notification: The office retired this desk" || { echo "  FAIL retire notification"; fail=1; }
! maluctl office heartbeat >/dev/null 2>&1 && maluctl office status | grep -q 'RETIRED by the office' && echo "  ok   maluctl office status reports the retirement" || { echo "  FAIL status after retire: $(maluctl office status 2>&1 | tail -2)"; fail=1; }
sudo -n maluctl office leave | grep -q 'left Mock Office' && [ ! -f /etc/maluos/office.yaml ] && [ ! -f /etc/maluos/office.env ] && ! maluctl secret list | grep -q office-desk-token && ! maluctl gateway status | grep -q 'backend:     office' && echo "  ok   sudo maluctl office leave removed the files, the token and the gateway rung" || { echo "  FAIL office leave"; ls /etc/maluos/office.* 2>&1; maluctl secret list; fail=1; }
! maluctl secret list | grep -q 'office-desk-key' && echo "  ok   office leave took the desk key with the token" || { echo "  FAIL desk key after leave"; fail=1; }
! maluctl secret list | grep -q 'estate-inference-key' && [ ! -f /run/maluos/office/inference.json ] && { for i in $(seq 1 10); do ! maluctl gateway status 2>/dev/null | grep -q 'estate:test-node' && break; sleep 2; done; ! maluctl gateway status | grep -q 'estate:test-node'; } && echo "  ok   slice 3 leave: the inference key and the desk's caches went with the enrolment; the rung estate:test-node left the gateway" || { echo "  FAIL slice 3 after office leave: $(maluctl secret list 2>&1 | grep inference); $(ls /run/maluos/office/ 2>&1); $(maluctl gateway status | grep estate)"; fail=1; }
for i in $(seq 1 12); do state | python3 -c "import json,sys; o=json.load(sys.stdin).get('office') or {}; sys.exit(1 if o.get('enrolled') else 0)" && break; sleep 5; done
state | python3 -c "import json,sys; o=json.load(sys.stdin).get('office') or {}; assert not o.get('enrolled'), o" && echo "  ok   session state: no office after leave" || { echo "  FAIL session still enrolled"; fail=1; }
for i in $(seq 1 20); do [ ! -f ~/.local/share/applications/maluos-agent-office-helpdesk.desktop ] && break; sleep 2; done
[ ! -f ~/.local/share/applications/maluos-agent-office-helpdesk.desktop ] && [ ! -f ~/Desktop/Agents/maluos-agent-office-research.desktop ] && [ -f ~/Desktop/Agents/maluos-agent-local-desk.desktop ] && echo "  ok   the office agents' icons went with the enrolment; the local one stays" || { echo "  FAIL icons after leave: $(ls ~/Desktop/Agents 2>&1 | tr '\n' ' ')"; fail=1; }
sudo -n systemctl stop maluos-mock-office 2>/dev/null
maluctl secret delete user:maluos/deskkey >/dev/null 2>&1 || true
sudo -n maluctl agent remove desk --purge >/dev/null 2>&1 || true
fi
# --- Phase 14 slice 1: the office with its database on a MaluOS database server (a second cluster of this VM stands in
# for the server). Last, because it moves the office's data: nothing after it may assume the first cluster.
# ---- application servers (docs/phase14-application-servers.md, slice 3): this VM stands in for both servers. The kernel's
# applications' door is opened on the VM's LAN address for that address; a fixture application is installed by the
# installer's HOST half (--kernel, a node token, no access to the kernel's database), which hands the rest to the kernel
# through the door. BOOT_TEST_APPSERVER=0 skips it.
if installed maluos-business-os && bos_on && [ "${BOOT_TEST_APPSERVER:-1}" = 1 ] && [ -f /var/www/app/features/applications/remote_install.php ]; then
echo "== application servers: the door, the installer's two halves (one VM standing in for two servers)"
LANIP=$(ip -o route get 192.0.2.1 2>/dev/null | sed -n 's/.*src \([^ ]*\).*/\1/p')
ADM=$(sudo -n python3 -c "import yaml; print(yaml.safe_load(open('/etc/maluos/firstboot.yaml'))['components']['maludb-os-core'].get('admin_email',''))" 2>/dev/null)
DOOR="http://$LANIP:8081"
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 $DOOR/api/v1/health)" = 000 ] && echo "  ok   no door before the kernel has a list of application servers" || { echo "  FAIL something answers on $DOOR before the list is set"; fail=1; }
sudo -n python3 -c "
import importlib.util, yaml
p = '/etc/maluos/firstboot.yaml'; c = yaml.safe_load(open(p)); k = c['components']['maludb-os-core']; k['application_servers'] = ['$LANIP']
open(p, 'w').write(yaml.safe_dump(c, sort_keys=False))
sp = importlib.util.spec_from_file_location('c', '/usr/lib/maluos/components/60-maludb-os-core.py'); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
v = open('/var/www/docs/deploy/apache-react-cutover.conf').read().replace('subello.com', '$bosdom')
t, d = m.render_door(v, k); assert d and d['address'] == '$LANIP', d
open('/etc/apache2/sites-available/maludb-os.conf', 'w').write(t)
" 2>/tmp/as-door.err && sudo -n apache2ctl configtest >/tmp/as-apache.log 2>&1 && sudo -n systemctl reload apache2 && sleep 3
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 $DOOR/api/v1/health)" = 200 ] && echo "  ok   the applications' door answers the kernel's health on $LANIP:8081" || { echo "  FAIL the door: $(cat /tmp/as-door.err /tmp/as-apache.log 2>/dev/null | tail -3 | cut -c1-300)"; fail=1; }
dc() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }
[ "$(dc $DOOR/login)" = 403 ] && [ "$(dc $DOOR/settings/desks/code.php)" = 403 ] && [ "$(dc $DOOR/api/v1/session.php)" = 403 ] && [ "$(dc -X POST $DOOR/api/v1/estate/apps/prepare)" = 401 ] \
  && echo "  ok   the door serves its allow-list only (the sign-in page and a kernel handler 403; prepare without a token 401)" || { echo "  FAIL the door's allow-list: login $(dc $DOOR/login), handler $(dc $DOOR/settings/desks/code.php), prepare $(dc -X POST $DOOR/api/v1/estate/apps/prepare)"; fail=1; }
systemctl is-active --quiet maludb-os-actions-reload.path && [ "$(stat -c %U /var/www/mcp/registries)" = www-data ] && echo "  ok   the registries are the web user's and the reload path unit is active" || { echo "  FAIL registries owner or the reload path unit"; fail=1; }
# the join: a server code that names the fixture application, then the node token
CODE=$(sudo -n -u www-data php /var/www/bin/mint_desk_code.php --email "$ADM" --kind server --name boot-app-1 --apps boottest_app 2>/dev/null | grep -oE '^ +[A-Z0-9]{4}-[A-Z0-9]{4}$' | tr -d ' ')
NTOK=$(curl -s --max-time 30 -H 'Content-Type: application/json' -d "{\"code\":\"$CODE\",\"kind\":\"server\",\"name\":\"boot-app-1\",\"facts\":{\"hostname\":\"boot-app-1\"}}" http://127.0.0.1:8080/api/v1/estate/join | python3 -c "import json,sys; print(json.load(sys.stdin).get('token',''))" 2>/dev/null)
[ -n "$CODE" ] && [ -n "$NTOK" ] && echo "  ok   a server code naming the application was minted and a node joined with it" || { echo "  FAIL the code or the join (code ${CODE:+minted}, token ${NTOK:+got})"; fail=1; }
printf '%s\n' "$NTOK" | sudo -n tee /run/boot-app.token >/dev/null; sudo -n chmod 600 /run/boot-app.token
# the fixture: a manifest, a public and an internal vhost, a handler, a migration, an action registry, a skill
F=/tmp/boottest_app; rm -rf $F; mkdir -p $F/html $F/deploy $F/db $F/mcp $F/skills/boottest-basics
cat > $F/maludb-os.json <<'JSON'
{"schema": "maludb-os.application/1", "catalog_key": "boottest_app", "name": "Boot test application", "description": "The boot test's fixture application.",
 "business_area": "Operations", "category": "other", "version": "0.0.1",
 "vhost": {"label": "boottest", "document_root": "html", "internal_port_env": "APP_INTERNAL_PORT"},
 "database": {"suffix": "boottest", "migrations": "db"},
 "env": {"required": ["APP_URL", "DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "APP_INTERNAL_PORT", "ACTION_TOKEN_KEY", "OS_INTERNAL_URL", "MALUDB_API_URL"]},
 "services": [], "endpoints": [], "actions": {"registry": "mcp/action_registry.json"}, "skills": ["skills/boottest-basics"],
 "sso": {"path": "/sso", "logout_path": "/sso/logout"}, "agents": []}
JSON
cat > $F/deploy/apache-boottest_app.conf <<'CONF'
<VirtualHost *:80>
	ServerName {{APP_FQDN}}
	DocumentRoot {{APP_DIR}}/html
	<Directory {{APP_DIR}}/html>
		Require all granted
	</Directory>
	RewriteEngine On
	RewriteRule ^/sso$ /sso.php [L,QSA]
</VirtualHost>
Listen 127.0.0.1:{{APP_INTERNAL_PORT}}
<VirtualHost 127.0.0.1:{{APP_INTERNAL_PORT}}>
	DocumentRoot {{APP_DIR}}/html
	<Directory {{APP_DIR}}/html>
		Require all granted
	</Directory>
</VirtualHost>
CONF
echo '<?php header("Content-Type: application/json"); echo json_encode(["ok" => true, "action_token" => isset($_SERVER["HTTP_X_ACTION_TOKEN"])]);' > $F/html/ping.php
echo '<?php http_response_code(204);' > $F/html/sso.php
echo 'CREATE TABLE IF NOT EXISTS boottest_note (id serial PRIMARY KEY, note text);' > $F/db/001_note.sql
echo '{"actions": {"boottest_ping": {"built": true, "endpoint": "/ping.php", "method": "POST", "params": []}}}' > $F/mcp/action_registry.json
printf -- '---\nname: boottest-basics\ndescription: The boot test fixture skill.\n---\n\n# Boot test basics\n\nNothing to know.\n' > $F/skills/boottest-basics/SKILL.md
MCPSTART=$(systemctl show -p ActiveEnterTimestampMonotonic --value maludb-os-actions-mcp)
( cd /var/www && sudo -n env HOME=/root php bin/app_install.php apply $F --kernel $DOOR --node-token-file /run/boot-app.token --address $LANIP ) > /tmp/as-install.log 2>&1; rc=$?
[ $rc = 0 ] && grep -q "the kernel registered Boot test application" /tmp/as-install.log && grep -q "^---- the kernel's half" /tmp/as-install.log \
  && echo "  ok   the installer's host half ran here and the kernel's half through the door: registered" || { echo "  FAIL the two-halves install (rc=$rc): $(grep -E 'STOP|Fatal|FAIL|refused|Stopped' /tmp/as-install.log | head -4 | cut -c1-300)"; tail -25 /tmp/as-install.log | cut -c1-200; fail=1; }
! grep -q "$NTOK" /tmp/as-install.log && ! sudo -n grep -q "$(sudo -n sed -n 's/^ACTION_TOKEN_KEY=//p' /var/www/config/.env)" /tmp/as-install.log && echo "  ok   the install's output shows no token and no key" || { echo "  FAIL a secret in the install's output"; fail=1; }
AE=/srv/apps/boottest_app/config/.env
sudo -n grep -q "^OS_INTERNAL_URL=$DOOR\$" $AE && sudo -n grep -q "^MALUDB_API_URL=$DOOR/maludb\$" $AE && sudo -n grep -q '^OS_APPLICATION_TOKEN=osapp_' $AE \
  && echo "  ok   the application's config points at the door and carries its application token" || { echo "  FAIL the application's config/.env: $(sudo -n grep -E '^(OS_INTERNAL_URL|MALUDB_API_URL)=' $AE | tr '\n' ' ')"; fail=1; }
APORT=$(sudo -n sed -n 's/^APP_INTERNAL_PORT=//p' $AE); RPORT=$((APORT + 1000))
row=$(sudo -n -u postgres psql -Atd maludb_os -c "select a.status || '|' || coalesce(a.internal_base_url,'') || '|' || l.name || '|' || coalesce(l.node_role,'') || '|' || coalesce(l.node_address,'') from applications a join locations l on l.id = a.location_id where a.app_key = 'boottest_app'")
[ "$row" = "active|http://$LANIP:$RPORT|boot-app-1|application-server|$LANIP" ] && echo "  ok   the kernel has the application active at its node, with the address it posts to ($LANIP:$RPORT)" || { echo "  FAIL the application's row: $row"; fail=1; }
sudo -n python3 -c "import json; r = json.load(open('/var/www/mcp/registries/boottest_app.json')); assert r['base_url'] == 'http://$LANIP:$RPORT' and 'boottest_ping' in r['registry']['actions'], r['base_url']" 2>/dev/null \
  && echo "  ok   the action registry on the kernel carries the application server's relay address" || { echo "  FAIL the registry file"; fail=1; }
for i in $(seq 1 20); do [ "$(systemctl show -p ActiveEnterTimestampMonotonic --value maludb-os-actions-mcp)" != "$MCPSTART" ] && systemctl is-active --quiet maludb-os-actions-mcp && break; sleep 3; done
[ "$(systemctl show -p ActiveEnterTimestampMonotonic --value maludb-os-actions-mcp)" != "$MCPSTART" ] && systemctl is-active --quiet maludb-os-actions-mcp \
  && echo "  ok   the Actions MCP was restarted for the new registry by the path unit (the kernel's half ran as the web user)" || { echo "  FAIL the Actions MCP was not reloaded"; fail=1; }
[ "$(curl -s --max-time 10 -X POST -H 'X-Action-Token: x' http://$LANIP:$RPORT/ping.php)" = '{"ok":true,"action_token":true}' ] && [ "$(dc http://127.0.0.1:$RPORT/ping.php)" = 000 ] \
  && echo "  ok   the relay passes the kernel's address to the application's internal port and listens nowhere else" || { echo "  FAIL the relay: $(curl -s --max-time 10 -X POST http://$LANIP:$RPORT/ping.php | cut -c1-120)"; fail=1; }
ATOK=$(sudo -n sed -n 's/^OS_APPLICATION_TOKEN=//p' $AE)
[ "$(dc -H "Authorization: Bearer $ATOK" $DOOR/api/v1/directory/departments)" = 200 ] && [ "$(dc -H "Authorization: Bearer wrong" $DOOR/api/v1/directory/departments)" = 401 ] \
  && echo "  ok   the application reads the kernel's directory through the door with its token (and not without)" || { echo "  FAIL the directory through the door: $(dc -H "Authorization: Bearer $ATOK" $DOOR/api/v1/directory/departments)"; fail=1; }
[ "$(sudo -n -u postgres psql -Atc "select count(*) from pg_database where datname like '%_boottest'")" = 1 ] && echo "  ok   the application's database was made by the host half" || { echo "  FAIL the application's database"; fail=1; }
sudo -n maluctl app names --upstreams 2>/dev/null | grep -q "^boottest\.$bosdom	$LANIP\$" && sudo -n maluctl app names --upstreams 2>/dev/null | grep -q "^app\.$bosdom	kernel\$" \
  && echo "  ok   maluctl app names --upstreams: the application at its server, the kernel's names at the kernel" || { echo "  FAIL names --upstreams: $(sudo -n maluctl app names --upstreams 2>&1 | tr '\n' ' ' | cut -c1-300)"; fail=1; }
out=$(cd /var/www && sudo -n env HOME=/root php bin/app_install.php apply $F --kernel $DOOR --node-token-file /run/boot-app.token --address $LANIP 2>&1); rc=$?
[ $rc = 0 ] && [ "$(sudo -n -u postgres psql -Atd maludb_os -c "select count(*) from mcp_access_tokens t join applications a on a.id = t.application_id where a.app_key = 'boottest_app' and t.scope = 'application' and t.revoked_at is null" 2>/dev/null)" = 1 ] \
  && echo "  ok   a second run reconciles: still one application token" || { echo "  FAIL the second run (rc=$rc): $(echo "$out" | grep -E 'STOP|Fatal' | head -2 | cut -c1-200)"; fail=1; }
sed -i 's/"catalog_key": "boottest_app"/"catalog_key": "boottest_other"/' $F/maludb-os.json
out=$(cd /var/www && sudo -n env HOME=/root php bin/app_install.php apply $F --kernel $DOOR --node-token-file /run/boot-app.token --address $LANIP 2>&1); rc=$?
[ $rc != 0 ] && echo "$out" | grep -q "join code does not name boottest_other" && ! sudo -n test -d /srv/apps/boottest_other \
  && echo "  ok   an application the join code did not name is refused before anything is installed" || { echo "  FAIL an unnamed application was not refused (rc=$rc)"; fail=1; }
sudo -n rm -f /run/boot-app.token
fi

# --- Phase 14 slice 4a (docs/phase14-watching-agents.md): a server with no vault and no gateway (a database server)
# joins the kernel's estate as a bare node. This VM stands in for it: scratch files beside the host's own (the
# enrolment in /run, the state in its own directory, a first-boot record that says database-server), no vault named.
if installed maluos-business-os && bos_on && installed maluos-estate && [ "${BOOT_TEST_BARE:-1}" = 1 ]; then
echo "== a bare node: a server without a vault joins the estate (the VM standing in for a database server)"
BADM=$(sudo -n python3 -c "import yaml; print(yaml.safe_load(open('/etc/maluos/firstboot.yaml'))['components']['maludb-os-core'].get('admin_email',''))" 2>/dev/null)
BD=/var/lib/maluos/estate-bare; sudo -n install -d -o maluos-estate -g maluos-estate -m 700 $BD
echo '{"role": "database-server", "components": {}, "database_server": {"port": 5432, "clients": ["192.0.2.20"], "tls": true}}' | sudo -n tee /run/bare-done >/dev/null
BENV="MALUOS_ESTATE_CONF=/run/bare-estate.yaml MALUOS_ESTATE_STATE_DIR=$BD MALUOS_PROVISIONED=/run/bare-done MALUOS_VAULT_CONFIG=/run/no-vault.yaml MALUOS_ESTATE_NO_UNIT=1 MALUOS_VAULT_SOCKET=/run/no-vault.sock MALUOS_GATEWAY_SOCKET=/run/no-gateway.sock MALUOS_MEMORY_SOCKET=/run/no-memory.sock"
BCODE=$(sudo -n -u www-data php /var/www/bin/mint_desk_code.php --email "$BADM" --kind server --name boot-db-1 2>/dev/null | grep -oE '^ +[A-Z0-9]{4}-[A-Z0-9]{4}$' | tr -d ' ')
out=$(sudo -n env $BENV maluctl estate join http://127.0.0.1:8080 --code "$BCODE" --name boot-db-1 2>&1); rc=$?
[ $rc != 0 ] && echo "$out" | grep -q 'has no vault.*--bare' && echo "  ok   a join without --bare on a server with no vault is refused with the reason (the code is not used)" || { echo "  FAIL the plain join without a vault (rc=$rc): $(echo "$out" | tail -2 | cut -c1-200)"; fail=1; }
out=$(sudo -n env $BENV maluctl estate join http://127.0.0.1:8080 --code "$BCODE" --bare --name boot-db-1 2>&1); rc=$?
BTOK=$(sudo -n cat $BD/node.token 2>/dev/null)
[ $rc = 0 ] && [ -n "$BTOK" ] && echo "$out" | grep -q 'a bare node: no vault, no agents' && ! echo "$out" | grep -qF "$BTOK" \
  && echo "  ok   the bare join: a node of the kernel's estate, the token not shown" || { echo "  FAIL the bare join (rc=$rc): $(echo "$out" | tail -3 | cut -c1-240)"; fail=1; }
[ "$(sudo -n stat -c '%a %U' $BD/node.token)" = '600 maluos-estate' ] && [ "$(sudo -n stat -c '%a %U' $BD/node.key)" = '600 maluos-estate' ] && ! sudo -n grep -qF "$BTOK" /run/bare-estate.yaml \
  && echo "  ok   the token and the key are 0600 files of the node service's user; the enrolment file carries no token" || { echo "  FAIL the bare node's files: $(sudo -n stat -c '%a %U %n' $BD/node.* 2>&1 | tr '\n' ' ')"; fail=1; }
out=$(sudo -n -u maluos-estate env $BENV maluctl estate heartbeat --report 2>&1); rc=$?
BROW=$(sudo -n -u postgres psql -Atd maludb_os -c "select node_role || '|' || presence || '|' || (report is not null) || '|' || coalesce((select string_agg(u->>'unit', ',') from jsonb_array_elements(report->'units') u), '') || '|' || coalesce(report->'database'->>'role', '') || '|' || (select count(*) from estate_alerts a where a.location_id = l.id and a.cleared_at is null) from locations l where name = 'boot-db-1' and status = 'active'")
[ $rc = 0 ] && echo "$BROW" | grep -q '^database-server|online|true|' && ! echo "$BROW" | grep -q 'vault\|gateway' && echo "$BROW" | grep -q '|server|0$' \
  && echo "  ok   its heartbeat as the node service's user: labelled database-server, the report without the vault and the gateway, the database part, no alert" || { echo "  FAIL the bare node's report (rc=$rc): $BROW | $(echo "$out" | tail -2 | cut -c1-200)"; fail=1; }
sudo -n env $BENV maluctl estate status 2>&1 | grep -q 'a bare node: no vault' && echo "  ok   maluctl estate status says it is a bare node" || { echo "  FAIL bare status: $(sudo -n env $BENV maluctl estate status 2>&1 | tail -3 | cut -c1-200)"; fail=1; }
out=$(sudo -n env $BENV maluctl estate leave 2>&1); rc=$?
[ $rc = 0 ] && echo "$out" | grep -q 'told; node retired' && ! sudo -n test -e $BD/node.token && ! sudo -n test -e /run/bare-estate.yaml \
  && [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Authorization: Bearer $BTOK" http://127.0.0.1:8080/api/v1/estate/me)" = 410 ] \
  && echo "  ok   leave: the node retired at the kernel, the files removed, the old token answers 410" || { echo "  FAIL the bare leave (rc=$rc): $(echo "$out" | tail -2 | cut -c1-200)"; fail=1; }
sudo -n rm -rf $BD /run/bare-done
fi

p14_on() { sudo -n python3 -c "import yaml,sys; c=yaml.safe_load(open('/etc/maluos/firstboot.yaml')) or {}; sys.exit(0 if (c.get('boot_test') or {}).get('database_server') else 1)" 2>/dev/null; }
if installed maluos-business-os && bos_on && p14_on; then
echo "  -- Phase 14: a database server (cluster 18/dbs, port 5433) and the office provisioned against it"
D=/etc/maluos/dbs-test; DP=5433
DBS="MALUOS_FIRSTBOOT_CONFIG=$D/firstboot.yaml MALUOS_STATE_DIR=$D/state MALUOS_SECRETS_DIR=$D/secrets MALUOS_DB_SERVER_DIR=$D/tls"
DPSQL() { sudo -n -u postgres env PGCLUSTER=18/dbs psql -XAtq "$@"; }
sudo -n pg_createcluster 18 dbs --port $DP --start >/dev/null 2>&1
sudo -n mkdir -p $D
printf 'role: database-server\ndatabase: maludb\noperators: []\nlistener: {enabled: false}\ndatabase_server:\n  cluster: 18/dbs\n  listen: 127.0.0.1\n  clients: [127.0.0.1/32]\n' | sudo -n tee $D/firstboot.yaml >/dev/null
sudo -n env $DBS maluctl provision --force > /tmp/p14-server.log 2>&1
DPSQL -c "alter system set log_connections = 'on'" -c "select pg_reload_conf()" >/dev/null 2>&1
sudo -n python3 -c "import json; d=json.load(open('$D/state/done')); s=d['database_server']; assert d['role']=='database-server' and d['tenant'] is None and s['admin']=='maluos_admin' and s['port']==$DP and s['tls']=='self-signed' and len(s['fingerprint'])==95, d" 2>/dev/null \
  && echo "  ok   role: database-server provisioned the second cluster (the admin role, TLS, its fingerprint; no tenant)" || { echo "  FAIL database server provisioning: $(tail -3 /tmp/p14-server.log | cut -c1-300)"; fail=1; }
[ "$(DPSQL -c "select rolcanlogin, rolcreaterole, rolcreatedb, rolbypassrls, rolsuper from pg_roles where rolname='maluos_admin'")" = 't|t|t|t|f' ] \
  && echo "  ok   the admin role creates roles and databases and is not a superuser" || { echo "  FAIL admin role: $(DPSQL -c "select rolcreaterole, rolcreatedb, rolsuper from pg_roles where rolname='maluos_admin'")"; fail=1; }
[ "$(DPSQL -c 'show ssl')" = on ] && sudo -n grep -q '^hostssl all all 127.0.0.1/32 scram-sha-256' /etc/postgresql/18/dbs/pg_hba.conf && [ "$(DPSQL -c "select datistemplate from pg_database where datname='maludb_template'")" = t ] \
  && echo "  ok   TLS on, the client in pg_hba (hostssl, scram), the engine's template database" || { echo "  FAIL server side: ssl=$(DPSQL -c 'show ssl')"; fail=1; }
sudo -n env $DBS maluctl db export /root/dbs-export > /tmp/p14-export.log 2>&1
sudo -n test -s /root/dbs-export/db-admin.txt && sudo -n grep -q 'BEGIN CERTIFICATE' /root/dbs-export/db-ca.pem && [ "$(sudo -n stat -c %a /root/dbs-export/db-admin.txt)" = 600 ] \
  && echo "  ok   maluctl db export wrote the admin credential (0600) and the certificate for the office" || { echo "  FAIL db export: $(cat /tmp/p14-export.log | cut -c1-200)"; fail=1; }
# the office: the block in firstboot.yaml, the kernel's local ledger and markers cleared (its database is a new one), then the real provisioning
# through the office-setup plugin when it has the script (0.1.3): the check with the certificate verified, a wrong password and a
# dead port explained, the refusal on a kernel already provisioned locally, then the block written; by hand otherwise
DSS=/usr/share/maluos/claude-plugins/maluos-office-setup/scripts/database-server.py
if [ -x "$DSS" ]; then
  DA="--host localhost --port $DP --credential /root/dbs-export/db-admin.txt --ca /root/dbs-export/db-ca.pem"
  out=$(sudo -n maluctl office-setup database --check $DA 2>&1); rc=$?
  [ $rc = 0 ] && echo "$out" | grep -q 'PASS  connected to localhost.*the certificate verified' && echo "$out" | grep -q 'PASS  the server has the template' \
    && echo "  ok   office-setup database --check: the admin role over TLS with the certificate verified, the template there" || { echo "  FAIL database --check (rc=$rc): $(echo "$out" | tail -3 | tr '\n' ' ' | cut -c1-300)"; fail=1; }
  echo wrong | sudo -n tee /root/dbs-export/bad.txt >/dev/null
  out=$(sudo -n maluctl office-setup database --check --host localhost --port $DP --credential /root/dbs-export/bad.txt --ca /root/dbs-export/db-ca.pem 2>&1); rc=$?
  out2=$(sudo -n maluctl office-setup database --check --host localhost --port 5999 --credential /root/dbs-export/db-admin.txt --ca /root/dbs-export/db-ca.pem 2>&1); rc2=$?
  [ $rc != 0 ] && echo "$out" | grep -q "is not the role maluos_admin's" && [ $rc2 != 0 ] && echo "$out2" | grep -q 'nothing answers at localhost:5999' && ! echo "$out$out2" | grep -q "$(sudo -n cat /root/dbs-export/db-admin.txt)" \
    && echo "  ok   database --check says which side to fix (a wrong password, nothing listening) and shows no password" || { echo "  FAIL database --check on failures: $(echo "$out" | tail -1 | cut -c1-200) | $(echo "$out2" | tail -1 | cut -c1-200)"; fail=1; }
  out=$(sudo -n maluctl office-setup database --apply $DA 2>&1); rc=$?
  [ $rc != 0 ] && echo "$out" | grep -q 'data-not-moved' && ! sudo -n grep -q '^database_server:' /etc/maluos/firstboot.yaml \
    && echo "  ok   database --apply refuses a kernel already provisioned on its own cluster and writes nothing" || { echo "  FAIL database --apply without --data-not-moved (rc=$rc)"; fail=1; }
  out=$(sudo -n maluctl office-setup database --apply $DA --data-not-moved 2>&1); rc=$?
  [ $rc = 0 ] && sudo -n python3 -c "import yaml; c=yaml.safe_load(open('/etc/maluos/firstboot.yaml')); d=c['database_server']; assert d['host']=='localhost' and d['port']==$DP and d['sslmode']=='verify-full' and c['components'], d" 2>/dev/null \
    && echo "  ok   database --apply wrote the database_server block and kept the rest of firstboot.yaml" || { echo "  FAIL database --apply (rc=$rc): $(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-300)"; fail=1; }
else
sudo -n python3 -c "import yaml; p='/etc/maluos/firstboot.yaml'; c=yaml.safe_load(open(p)) or {}; c['database_server']={'host': 'localhost', 'port': $DP, 'admin': 'maluos_admin', 'credential': 'file:/root/dbs-export/db-admin.txt', 'sslmode': 'verify-full', 'ca': 'file:/root/dbs-export/db-ca.pem'}; open(p, 'w').write(yaml.safe_dump(c, sort_keys=False))"
fi
sudo -n rm -f /var/lib/maluos/business-os/migrations-applied /var/lib/maluos/business-os/hire-installer /var/lib/maluos/business-os/hire-jev
sudo -n maluctl provision --force > /tmp/p14-office.log 2>&1
sudo -n python3 -c "
import json
d = json.load(open('/var/lib/maluos/firstboot/done'))
ds = d['database_server']
assert ds == {'host': 'localhost', 'port': $DP, 'admin': 'maluos_admin', 'sslmode': 'verify-full'}, ds
bad = {k: v for k, v in d['components'].items() if v is not None and ('error' in v or v.get('healthy') is False)}
assert not bad, bad
assert d['listener'] is None, d['listener']
" 2>/tmp/p14-done.err && echo "  ok   the office provisioned against the database server: every component healthy, the summary says where the data is" || { echo "  FAIL office provisioning: $(tail -2 /tmp/p14-done.err | cut -c1-300) | $(grep -i 'FAILED\|warning' /tmp/p14-office.log | tail -3 | cut -c1-300)"; systemctl is-active maludb-api apache2 | tr '\n' ' '; echo "health: $(curl -sS -m 60 -o /tmp/p14-health.out -w '%{http_code} in %{time_total}s' http://127.0.0.1:8080/api/v1/health 2>&1) $(head -c 300 /tmp/p14-health.out 2>/dev/null)"; sudo -n tail -n 12 /var/log/apache2/error.log | cut -c1-400; sudo -n grep -h 'FATAL\|ERROR' /var/log/postgresql/postgresql-18-dbs.log | tail -8 | cut -c1-300; sudo -n grep -h 'maludb-os-core\|kernel' /tmp/p14-office.log | tail -6 | cut -c1-300; fail=1; }
if [ -x "$DSS" ]; then
  sudo -n maluctl office-setup database --show 2>&1 | tr '\n' ' ' | grep -q "provisioned: against localhost:$DP.*PASS  reached:" && sudo -n maluctl office-setup status 2>&1 | grep -q "^data: .*configured: the database server localhost:$DP; provisioned: the database server localhost:$DP" \
    && echo "  ok   office-setup database --show and status: configured and provisioned on the database server, reached" || { echo "  FAIL office-setup database --show: $(sudo -n maluctl office-setup database --show 2>&1 | tr '\n' ' ' | cut -c1-300)"; fail=1; }
fi
sudo -n maluctl status | grep -q "data:        on the database server localhost:$DP (verify-full) as maluos_admin" && echo "  ok   maluctl status: data on the database server" || { echo "  FAIL status line: $(sudo -n maluctl status | sed -n 2,4p)"; fail=1; }
sudo -n maluctl db status | tr '\n' ' ' | grep -q "reached:   yes, as maluos_admin (not a superuser).*TLSv1.3.*maludb_os" && echo "  ok   maluctl db status: reached as the admin role, not a superuser, TLS 1.3, the kernel's database there" || { echo "  FAIL db status: $(sudo -n maluctl db status 2>&1 | tr '\n' ' ' | cut -c1-300)"; fail=1; }
[ "$(stat -c '%a %U' /var/lib/maluos/secrets/db-admin.pgpass 2>/dev/null || sudo -n stat -c '%a %U' /var/lib/maluos/secrets/db-admin.pgpass)" = '600 root' ] && cmp -s <(sudo -n cat /root/dbs-export/db-ca.pem) /etc/maluos/database-server-ca.pem \
  && echo "  ok   the credential is root-only on the office; the certificate is beside its configuration" || { echo "  FAIL credential files"; fail=1; }
[ "$(DPSQL -c "select count(*) from pg_roles where rolsuper and rolname <> 'postgres'")" = 0 ] && [ "$(DPSQL -c "select count(*) from pg_roles where rolname='maluos'")" = 1 ] && [ "$(DPSQL -c "select count(*) from pg_roles where rolname = 'edward'")" = 0 ] \
  && echo "  ok   no superuser but postgres on the database server; the operator has no role there (the tenant has)" || { echo "  FAIL roles on the server: $(DPSQL -c "select string_agg(rolname, ',') from pg_roles where rolsuper")"; fail=1; }
[ "$(DPSQL -c "select string_agg(datname, ',' order by datname) from pg_database where datname in ('maludb','maludb_os','maludb_os_memory')")" = 'maludb,maludb_os,maludb_os_memory' ] && [ "$(DPSQL -d maludb_os -c 'select count(*) > 0 from members')" = t ] \
  && echo "  ok   the kernel's databases are on the database server (its migrations applied there, the super-admin made)" || { echo "  FAIL kernel databases: $(DPSQL -c "select string_agg(datname, ',') from pg_database")"; fail=1; }
p14_conns() { for u in maluos-vault maluos-gateway maluos-memory; do sudo -n grep -q "connection authorized: user=$u .*SSL enabled" /var/log/postgresql/postgresql-18-dbs.log || return 1; done; }
for i in $(seq 1 20); do p14_conns && break; maluctl gateway status >/dev/null 2>&1; maluctl memory whoami >/dev/null 2>&1; sudo -n maluctl secret list >/dev/null 2>&1; sleep 3; done
p14_conns \
  && echo "  ok   the vault, the gateway and the memory face connected there over TLS as their own roles (passwords: a file, the vault)" || { echo "  FAIL service connections: $(sudo -n grep -o 'connection authorized: user=maluos-[a-z]* .*' /var/log/postgresql/postgresql-18-dbs.log | sort -u | cut -c1-90 | tr '\n' ';') | memory: $(maluctl memory whoami 2>&1 | tail -2 | tr '\n' ' ' | cut -c1-300)"; sudo -n journalctl -u maluos-memory --no-pager -n 12 | cut -c1-260; fail=1; }
sudo -n grep -q "^pg_password_file: /var/lib/maluos-vault/pg.password" /etc/maluos/vault.yaml && [ "$(sudo -n stat -c '%a %U' /var/lib/maluos-vault/pg.password)" = '600 maluos-vault' ] && grep -q '^pg_password_ref: system/pg-maluos-gateway-password' /etc/maluos/gateway.yaml && grep -q '^pg_password_ref: system/pg-maluos-memory-password' /etc/maluos/memory.yaml \
  && echo "  ok   vault.yaml names the vault's own password file; the gateway and the memory face name a vault reference" || { echo "  FAIL service configuration: $(grep -h '^pg_' /etc/maluos/gateway.yaml /etc/maluos/memory.yaml | tr '\n' ' ')"; fail=1; }
sudo -n grep -q "^DB_HOST=localhost" /var/www/config/.env && sudo -n grep -q "^DB_PORT=$DP" /var/www/config/.env && sudo -n grep -q '^DB_SSLMODE=verify-full' /var/www/config/.env && sudo -n grep -q "^RUNNER_DB_PORT=$DP" /etc/business-os/runner.env && sudo -n grep -q "^MALUDB_PG_PORT=$DP" /etc/maludb/maludb-api.env \
  && echo "  ok   the kernel, the runner and the MaluDB API are pointed at the database server" || { echo "  FAIL kernel configuration: $(sudo -n grep -h '^DB_HOST\|^DB_PORT\|^RUNNER_DB' /var/www/config/.env /etc/business-os/runner.env | tr '\n' ' ')"; fail=1; }
! systemctl is-enabled --quiet maludb-mc2dbd 2>/dev/null && echo "  ok   no listener on the office (the engine's face stays with the data)" || { echo "  FAIL the office still runs a listener"; fail=1; }
# the proof: the office's own cluster stopped, everything still answers
sudo -n systemctl stop postgresql@18-main
sudo -n systemctl restart maluos-vault maluos-gateway maluos-memory maludb-api apache2 2>/dev/null
for i in $(seq 1 40); do sudo -n maluctl secret list >/dev/null 2>&1 && curl -fsS --max-time 5 http://127.0.0.1:8080/api/v1/health >/dev/null 2>&1 && curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1 && break; sleep 3; done
echo on-the-database-server | sudo -n maluctl secret add system/p14-proof --kind token --stdin >/dev/null 2>&1; [ "$(sudo -n maluctl secret show system/p14-proof 2>/dev/null)" = on-the-database-server ] \
  && echo "  ok   the office's own cluster stopped: the vault stores and returns a secret" || { echo "  FAIL vault without the local cluster: $(sudo -n maluctl secret show system/p14-proof 2>&1 | tail -1 | cut -c1-200)"; fail=1; }
maluctl gateway status 2>/dev/null | grep -qi 'gateway\|backend' && maluctl memory whoami 2>/dev/null | grep -q 'principal: user:maluos' \
  && echo "  ok   the office's own cluster stopped: the gateway and the memory face answer" || { echo "  FAIL gateway or memory face without the local cluster: $(maluctl gateway status 2>&1 | tail -1 | cut -c1-160) | $(maluctl memory whoami 2>&1 | tail -2 | tr '\n' ' ' | cut -c1-300)"; sudo -n journalctl -u maluos-memory --no-pager -n 12 | cut -c1-260; fail=1; }
tok=$(sudo -n cat /var/lib/maluos/secrets/api.token 2>/dev/null); t0=$(date +%s); api_ok=1; for i in 1 2 3 4 5 6; do curl -fsS --max-time 40 -H "Authorization: Bearer $tok" http://127.0.0.1:8000/v1/whoami >/dev/null 2>/tmp/p14-api.err && { api_ok=0; break; }; sleep 5; done; echo "  (the MaluDB API's first answer against the database server: try $i, $(( $(date +%s) - t0 )) s)"
[ $api_ok = 0 ] && echo "  ok   the office's own cluster stopped: the MaluDB API answers for the tenant" || { echo "  FAIL MaluDB API without the local cluster: $(cut -c1-200 /tmp/p14-api.err) | $(curl -s --max-time 40 -o /dev/null -w '%{http_code} %{time_total}s' -H "Authorization: Bearer $tok" http://127.0.0.1:8000/v1/whoami) | health $(curl -s --max-time 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"; sudo -n journalctl -u maludb-api --no-pager -n 25 | cut -c1-260; fail=1; }
[ "$(sudo -n runuser -u www-data -- php -r 'require "/var/www/app/bootstrap.php"; echo db()->query("SELECT current_user || chr(58) || (SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid())")->fetchColumn();' 2>/dev/null)" = 'app_rw:true' ] \
  && echo "  ok   the office's own cluster stopped: the kernel reads its database as app_rw over TLS" || { echo "  FAIL kernel without the local cluster: $(sudo -n runuser -u www-data -- php -r 'require "/var/www/app/bootstrap.php"; echo db()->query("SELECT current_user")->fetchColumn();' 2>&1 | tail -1 | cut -c1-200)"; fail=1; }
sudo -n maluctl estate report 2>/dev/null | grep -q "database: on localhost:$DP (verify-full)" && echo "  ok   the node's report says where its data is" || echo "  warn no database line in the estate report (the node is not enrolled on this boot)"
sudo -n systemctl start postgresql@18-main
fi
sudo -n maluctl status | sed 's/^/  maluctl: /'
exit $fail
REMOTE
rc=${PIPESTATUS[0]}
ssh "${ssh_opts[@]}" maluos@127.0.0.1 'sudo -n poweroff' 2>/dev/null || true; sleep 3
[ "$rc" = 0 ] && echo "PASS: $(basename "$IMG") boots and runs the MaluDB stack" || { echo "FAIL (see $WORK)"; exit 1; }
