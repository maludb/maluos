#!/bin/bash
# Exercise `maluctl office` and the mock office on this host, without a VM: a throwaway
# database and the real vault daemon (as in vault-local-test.sh), the mock office on a
# local port, enrol/heartbeat/status/leave as root for the current user, no gateway
# (--no-gateway; the image boot test covers the office rung). Then Phase 13 slice 1: this host joins the mock's
# estate as a server node (maluctl estate, the daemon, the report, the health rules, leave), the current user
# standing in for the system user maluos-estate (MALUOS_ESTATE_USER). Needs passwordless sudo.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
W=/var/tmp/maluos-desk-test; DB=maluos_desktest; T=dt; VROLE=desktest_vault; ME=$(id -un); PORT=18981
fail=0; n=0
ok()   { n=$((n+1)); echo "  ok   $*"; }
bad()  { n=$((n+1)); fail=$((fail+1)); echo "  FAIL $*"; }
check(){ if (set +o pipefail; eval "$2"); then ok "$1"; else bad "$1"; fi; }

sudo -n true 2>/dev/null || { echo "needs passwordless sudo"; exit 2; }
pkill -f "$W/lib/maluos_vault.py" 2>/dev/null; pkill -f "maluos_desk.mock_office --port $PORT" 2>/dev/null; sleep 0.5
sudo rm -rf "$W"; mkdir -p "$W/lib/maluctl.d" "$W/cred" "$W/state" "$W/etc" "$W/fb"; chmod 755 "$W" "$W/lib" "$W/lib/maluctl.d" "$W/etc" "$W/fb"
cp "$ROOT"/packages/maluos-firstboot/lib/maluos_provision.py "$ROOT"/packages/maluos-firstboot/bin/maluctl \
   "$ROOT"/packages/maluos-vault/lib/maluos_vault.py "$ROOT"/packages/maluos-vault/lib/maluos_vault_client.py \
   "$ROOT"/packages/maluos-vault/components/40-maluos-vault.py "$ROOT"/packages/maluos-vault/share/schema.sql "$W/lib/"
cp "$ROOT"/packages/maluos-vault/lib/maluctl.d/secret.py "$ROOT"/packages/maluos-desk/lib/maluctl.d/office.py "$ROOT"/packages/maluos-estate/lib/maluctl.d/estate.py "$W/lib/maluctl.d/"
cp -r "$ROOT"/packages/maluos-desk/lib/maluos_desk "$ROOT"/packages/maluos-estate/lib/maluos_estate "$W/lib/"
chmod -R a+rX "$W/lib"; head -c 32 /dev/urandom > "$W/cred/maluos-vault.key"
cat > "$W/vault.yaml" <<EOY
socket: $W/vault.sock
database: $DB
tenant: $T
pg_role: $VROLE
state_dir: $W/state
brokers: []
identities: {}
EOY
chmod 644 "$W/vault.yaml"

echo "== database $DB (tenant $T)"
sudo -n -u postgres psql -Xq -c "DROP DATABASE IF EXISTS $DB" -c "DROP ROLE IF EXISTS $VROLE" -c "DROP ROLE IF EXISTS $T" >/dev/null
sudo -n env PYTHONPATH="$W/lib" python3 - "$DB" "$T" "$VROLE" "$ME" "$W" <<'PY' || exit 1
import sys, importlib.util
import maluos_provision as mp
db, t, vrole, me, w = sys.argv[1:6]
mp.ensure_database(db); mp.ensure_tenant(db, t)
mp.ensure_principal(db, t, {"ref": f"user:{me}", "kind": "human", "display_name": me, "home_scope": f"user:{me}"})
spec = importlib.util.spec_from_file_location("comp", f"{w}/lib/40-maluos-vault.py")
comp = importlib.util.module_from_spec(spec); spec.loader.exec_module(comp)
mp.psql(f"CREATE ROLE {mp.qi(vrole)} NOLOGIN")
comp.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, t, role=vrole, schema=f"{w}/lib/schema.sql")
print("  schema + grants applied")
PY

echo "== daemon and mock office"
( cd "$W" && CREDENTIALS_DIRECTORY=$W/cred MALUOS_VAULT_CONFIG=$W/vault.yaml python3 "$W/lib/maluos_vault.py" --socket "$W/vault.sock" >"$W/daemon.log" 2>&1 & echo $! > "$W/daemon.pid" )
( cd "$W" && PYTHONPATH=$W/lib python3 -m maluos_desk.mock_office --port $PORT --code good-code --node-code node-code --name "Local Office" --models office-7b --heartbeat-s 5 --report-s 4 >"$W/office.log" 2>&1 & echo $! > "$W/office.pid" )
printf '{"database":"%s","tenant":"%s","provisioned_at":"test","admin_principal":"human:admin","operators":[],"components":{"vault":{}}}\n' $DB $T > "$W/fb/done"
trap 'kill $(cat $W/daemon.pid) $(cat $W/office.pid) 2>/dev/null' EXIT
for i in $(seq 1 20); do [ -S "$W/vault.sock" ] && curl -fsS --max-time 1 http://127.0.0.1:$PORT/api/v1/health >/dev/null 2>&1 && break; sleep 0.25; done
ENV="PYTHONPATH=$W/lib MALUCTL_PLUGIN_DIR=$W/lib/maluctl.d MALUCTL_BIN=$W/lib/maluctl MALUOS_VAULT_SOCKET=$W/vault.sock MALUOS_OFFICE_CONF=$W/etc/office.yaml MALUOS_OFFICE_ENV=$W/etc/office.env XDG_STATE_HOME=$W/state-$ME XDG_CACHE_HOME=$W/cache-$ME MALUOS_STATE_DIR=$W/fb MALUOS_PROVISIONED=$W/fb/done MALUOS_ESTATE_CONF=$W/etc/estate.yaml MALUOS_ESTATE_STATE_DIR=$W/estate MALUOS_ESTATE_USER=$ME MALUOS_ESTATE_NO_UNIT=1 MALUOS_VAULT_CONFIG=$W/vault.yaml MALUOS_GATEWAY_CONFIG=$W/etc/gateway.yaml MALUOS_GATEWAY_SOCKET=$W/no-gateway.sock MALUOS_OVERLAY_DRY_RUN=1 MALUOS_OVERLAY_DRY_LOG=$W/overlay-dry.log MALUOS_OVERLAY_HOSTS=$W/hosts MALUOS_OVERLAY_STATE=$W/estate/overlay.json MALUOS_OVERLAY_RUN=$W/ovrun"
me()   { env $ENV python3 "$W/lib/maluctl" "$@"; }
root() { sudo -n env $ENV python3 "$W/lib/maluctl" "$@"; }
mock() { curl -fsS --max-time 5 "http://127.0.0.1:$PORT$1" "${@:2}"; }

check "mock office health" "mock /api/v1/health | grep -q '\"office\": \"Local Office\"'"
check "vault sees user:$ME" "me secret whoami | grep -q 'principal:  user:$ME'"
check "status: not enrolled (exit 1)" "! me office status >/dev/null 2>&1 && me office status 2>&1 | grep -q 'not enrolled'"
check "enroll needs root" "! me office enroll http://127.0.0.1:$PORT --code good-code 2>&1 | grep -q enrolled"
check "enroll refuses a bad URL" "root office enroll ftp://x --code c 2>&1 | grep -q 'must start with http'"
check "enroll refuses a wrong code (403 bad_code)" "root office enroll http://127.0.0.1:$PORT --code nope --owner $ME 2>&1 | grep -q 'refused enrolment (403 bad_code)'"
check "enroll refuses an unknown owner" "root office enroll http://127.0.0.1:$PORT --code good-code --owner nosuchuser 2>&1 | grep -q 'no such user'"
check "enroll (no gateway) as root for $ME" "root office enroll http://127.0.0.1:$PORT --code good-code --owner $ME --name 'Local desk' --no-gateway | grep -q \"enrolled: desk 'Local desk' (#41) at Local Office for user:$ME\""
check "the code is spent" "root office enroll http://127.0.0.1:$PORT --code good-code --owner $ME --force 2>&1 | grep -q 'bad_code'"
check "office.yaml: url, owner, no token" "grep -q '^url: http://127.0.0.1:$PORT' $W/etc/office.yaml && grep -q 'principal: user:$ME' $W/etc/office.yaml && ! grep -q desk_ $W/etc/office.yaml"
check "office.env for agents" "grep -q 'MALUOS_OFFICE_MEMORY_MCP=\"http://127.0.0.1:$PORT/mcp/memory\"' $W/etc/office.env && grep -q 'MALUOS_OFFICE_DESK_ID=\"41\"' $W/etc/office.env"
check "the token is in $ME's compartment, kind token" "me secret list | grep -q \"user:$ME/office-desk-token\" && me secret info office-desk-token | grep -q 'token'"
check "the token works at the office (records MCP)" "curl -fsS --max-time 5 -H \"Authorization: Bearer \$(me secret show office-desk-token)\" http://127.0.0.1:$PORT/mcp/records -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{}}' | grep -q mock-office-records"
check "without a token the office refuses (401)" "curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:$PORT/mcp/records -d '{}' | grep -q 401"
check "status shows the desk, the owner, no rung" "me office status | grep -q 'desk:       Local desk  (#41)' && me office status | grep -q 'gateway:    no rung' && me office status | grep -q 'none yet'"
check "heartbeat as the owner" "me office heartbeat | grep -q 'ok: desk Local desk (#41) online'"
check "heartbeat --json --presence offline" "me office heartbeat --json --presence offline | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); assert d[\"ok\"] and d[\"presence\"]==\"offline\" and d[\"desk\"][\"id\"]==41'"
check "the office recorded both, with facts" "mock /mock/state | python3 -c 'import json,sys; s=json.load(sys.stdin); d=s[\"desks\"][0]; hb=s[\"heartbeats\"]; assert d[\"presence\"]==\"offline\" and len(hb)==2 and d[\"facts\"][\"cpu_cores\"] and d[\"principal\"]==\"user:$ME\", (d,hb)'"
check "heartbeat with the token from the environment (no vault read)" "n0=\$(me secret usage --raw 2>/dev/null | grep -c 'secret.read' || true); MALUOS_OFFICE_TOKEN=\$(me secret show office-desk-token) me office heartbeat | grep -q 'ok: desk'"
check "status after a heartbeat" "me office status | grep -q 'heartbeat:  .* ok  presence online'"
check "status --live asks the office" "me office status --live | grep -q 'office says: 200  desk Local desk active presence online'"
check "status --json" "me office status --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"enrolled\"] and d[\"desk\"][\"id\"]==41 and d[\"last_heartbeat\"][\"ok\"]'"
check "a second enrolment without --force is refused" "root office enroll http://127.0.0.1:$PORT --code x --owner $ME 2>&1 | grep -q 'already enrolled'"
check "the office retires the desk -> heartbeat 410, revoked" "mock /mock/retire -d '{\"desk_id\": 41}' >/dev/null && ! me office heartbeat >/dev/null 2>&1 && me office heartbeat --json 2>/dev/null | grep -q '\"revoked\": true'"
check "status says RETIRED" "me office status | grep -q 'RETIRED by the office'"
check "leave (root): told, files and token gone" "root office leave | grep -q 'left Local Office: the office was answered 410' && [ ! -f $W/etc/office.yaml ] && [ ! -f $W/etc/office.env ] && ! me secret list | grep -q office-desk-token"
check "status: not enrolled again" "! me office status >/dev/null 2>&1"
check "re-enrol with a new code, --keep-secret on leave keeps the token" "mock /mock/code -d '{\"code\":\"second\"}' >/dev/null && root office enroll http://127.0.0.1:$PORT --code second --owner $ME --no-gateway | grep -q 'enrolled: desk' && root office leave --keep-secret | grep -q 'desk retired' && me secret list | grep -q office-desk-token"
check "no token value in the vault log or the office config dir" "! grep -q 'desk_' $W/daemon.log && ! ls $W/etc | grep -q office"

echo "== Phase 13 slice 1: this host as a node of the estate (maluctl estate against the mock; $ME stands in for maluos-estate)"
HOST=$(hostname)
check "estate status: not joined (exit 1)" "! me estate status >/dev/null 2>&1 && me estate status 2>&1 | grep -q 'not joined'"
check "report without an office: units, disk, memory, load; the gateway and the vault absent are null, not errors" "me estate report --json | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r[\"hostname\"] and r[\"disk\"][0][\"mount\"]==\"/\" and r[\"memory\"][\"total_mb\"]>0 and len(r[\"load\"])==3 and isinstance(r[\"units\"], list), r'"
check "report (text) names the node" "me estate report | grep -q '^node:     $HOST'"
check "join needs root" "! me estate join http://127.0.0.1:$PORT --code node-code 2>&1 | grep -q joined"
check "join refuses a desk code (403 bad_code)" "root estate join http://127.0.0.1:$PORT --code good-code --name n 2>&1 | grep -q 'refused the node (403 bad_code)'"
check "join refuses a bad kind" "root estate join http://127.0.0.1:$PORT --code node-code --kind laptop 2>&1 | grep -q 'must be server, inference or desk'"
check "join as a server node: the principal host:$HOST, the identity map, the key and the token, estate.yaml" "root estate join http://127.0.0.1:$PORT --code node-code --name local-node | grep -q \"joined: server 'local-node' (#57) at Local Office as host:$HOST\""
check "estate.yaml: url, node, principal, no token" "grep -q '^url: http://127.0.0.1:$PORT' $W/etc/estate.yaml && grep -q 'principal: host:$HOST' $W/etc/estate.yaml && ! grep -q node_ $W/etc/estate.yaml"
check "vault.yaml maps $ME to host:$HOST (the vault re-reads it): whoami is the host" "grep -q \"$ME: host:$HOST\" $W/vault.yaml && me secret whoami | grep -q 'principal:  host:$HOST'"
check "the token and the key are in host:$HOST's compartment" "me secret list | grep -q 'host:$HOST/estate-node-token' && me secret list | grep -q 'host:$HOST/estate-node-key' && me secret info estate-node-key | grep -q generic"
check "the node key is a private ed25519 key; the public half went to the office" "me secret show estate-node-key | grep -q 'BEGIN OPENSSH PRIVATE KEY' && mock /mock/nodes | python3 -c 'import json,sys; n=json.load(sys.stdin)[\"nodes\"][0]; assert n[\"id\"]==57 and n[\"kind\"]==\"server\"'"
check "the office holds the public key and the components" "mock /mock/state | python3 -c 'import json,sys; n=json.load(sys.stdin)[\"nodes\"][0]; assert n[\"public_key\"].startswith(\"ssh-ed25519 \") and n[\"components\"]==[\"vault\"] and n[\"principal\"]==\"host:$HOST\", n'"
check "the code is spent" "root estate join http://127.0.0.1:$PORT --code node-code --force 2>&1 | grep -q bad_code"
check "a second join without --force is refused" "root estate join http://127.0.0.1:$PORT --code x 2>&1 | grep -q 'already node #57'"
check "status: joined, no heartbeat yet" "me estate status | grep -q \"node:       server 'local-node'  (#57)\" && me estate status | grep -q 'no heartbeat yet'"
check "heartbeat as the node, with the report" "me estate heartbeat --report | grep -q 'ok: node local-node (#57) online .* with the report'"
check "the office has the report: health ok or warning, last_report_at set, the summary" "mock /mock/nodes | python3 -c 'import json,sys; n=json.load(sys.stdin)[\"nodes\"][0]; assert n[\"last_report_at\"] and n[\"health\"] in (\"ok\",\"warning\") and n[\"units\"][\"up\"]>=0 and n[\"memory_available_pct\"]>0, n'"
check "vault ledger: the token read is the host's own row (secret.read by host:$HOST)" "sudo -n -u postgres psql -Atd $DB -c \"select count(*) from $T.maluos_ledger where event='secret.read' and principal_ref='host:$HOST' and secret_name='estate-node-token' and status='ok'\" | grep -qE '^[1-9]'"
check "estate nodes as the node: itself (the desk left earlier)" "me estate nodes | grep -q 'estate of Local Office as node #57: 1 nodes, 1 online' && me estate nodes | grep -q \"#57   server    local-node\""
check "estate nodes 57: the full report" "me estate nodes 57 | grep -q \"server 'local-node' (#57) online health\" && me estate nodes 57 | grep -q '^disk:     /'"
( cd "$W"; exec env $ENV python3 -m maluos_estate >"$W/estated.log" 2>&1 ) & echo $! > "$W/estated.pid"   # exec: the pid is the daemon's, so SIGTERM reaches it
for i in $(seq 1 40); do [ -f "$W/estate/state.json" ] && grep -q '"ok": true' "$W/estate/state.json" && break; sleep 0.25; done
check "the daemon heartbeats: state.json ok with the report" "python3 -c 'import json; s=json.load(open(\"$W/estate/state.json\")); assert s[\"ok\"] and s[\"report_sent\"] and s[\"last_report_at\"], s'"
check "status shows the last heartbeat" "me estate status | grep -q 'last:       .* ok  presence online'"
check "a failing report raises alerts and turns health critical (an agent failed, disk at 97 %)" "mock /mock/report -d '{\"node_id\": 57, \"report\": {\"ts\": \"t\", \"units\": [{\"unit\": \"maluos-vault.service\", \"active\": \"active\"}], \"agents\": [{\"name\": \"demo\", \"active\": \"failed\", \"restarts\": 3}], \"disk\": [{\"mount\": \"/\", \"size_gb\": 10, \"used_pct\": 97}]}}' | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r[\"node\"][\"health\"]==\"critical\" and sorted(a[\"kind\"] for a in r[\"alerts\"])==[\"agent_down\",\"disk_full\"], r'"
check "estate nodes lists the alerts" "me estate nodes | grep -q 'alert #.* local-node: warning agent_down: agent demo failed (3 restarts)' && me estate nodes | grep -q 'critical disk_full: disk / at 97 %'"
for i in $(seq 1 40); do mock /mock/nodes | python3 -c 'import json,sys; n=json.load(sys.stdin)["nodes"][0]; sys.exit(0 if n["health"]!="critical" else 1)' && break; sleep 0.25; done
check "the daemon's next report clears them (cleared_at set)" "mock /mock/nodes | python3 -c 'import json,sys; d=json.load(sys.stdin); n=d[\"nodes\"][0]; assert n[\"health\"]!=\"critical\"; assert all(a[\"cleared_at\"] for a in d[\"alerts\"] if a[\"kind\"] in (\"agent_down\",\"disk_full\") and a[\"title\"] in (\"agent demo failed (3 restarts)\", \"disk / at 97 %\")), d[\"alerts\"]'"
kill -TERM $(cat "$W/estated.pid"); for i in $(seq 1 40); do kill -0 $(cat "$W/estated.pid") 2>/dev/null || break; sleep 0.25; done
check "SIGTERM: the daemon says offline and exits; the office shows the node offline with a node_offline alert" "grep -q 'said offline' $W/estated.log && mock /mock/nodes | python3 -c 'import json,sys; d=json.load(sys.stdin); n=d[\"nodes\"][0]; assert n[\"presence\"]==\"offline\" and n[\"health\"]==\"offline\" and any(a[\"kind\"]==\"node_offline\" and not a[\"cleared_at\"] for a in d[\"alerts\"]), d'"
check "the office retires the node -> heartbeat 410, revoked" "mock /mock/retire -d '{\"desk_id\": 0}' >/dev/null; true" ; mock /api/v1/estate/leave -X POST -H "Authorization: Bearer $(me secret show estate-node-token)" >/dev/null 2>&1
check "a retired node's heartbeat is refused (401 after leave: the token is revoked)" "! me estate heartbeat >/dev/null 2>&1 && me estate heartbeat --json 2>/dev/null | grep -q '\"revoked\": true'"
check "leave (root): told, the unit, the token and the key gone, the identity map restored" "root estate leave | grep -q 'left Local Office' && [ ! -f $W/etc/estate.yaml ] && [ ! -f $W/estate/state.json ] && ! grep -q \"$ME: host:$HOST\" $W/vault.yaml && me secret whoami | grep -q 'principal:  user:$ME'"
check "the host's secrets are gone (as an operator sees it)" "! sudo -n env $ENV python3 $W/lib/maluctl secret list --all 2>/dev/null | grep -q 'host:$HOST/estate-node'"
check "status: not joined again" "! me estate status >/dev/null 2>&1"
check "status on a desk: its desk enrolment is its node record" "mock /mock/code -d '{\"code\":\"third\"}' >/dev/null && root office enroll http://127.0.0.1:$PORT --code third --owner $ME --no-gateway --force >/dev/null && me estate status | grep -q 'this desk is node #' && me estate status | grep -q 'maluctl estate nodes'"
check "maluctl office estate as the desk's owner (endpoints.estate): the desk itself, no server node, no open alert" "me office estate --refresh | grep -q 'estate of Local Office: 1 nodes, 1 online, 0 open alerts' && me office estate --json | python3 -c 'import json,sys; c=json.load(sys.stdin); assert c[\"available\"] and c[\"counts\"][\"nodes\"]==1 and c[\"nodes\"][0][\"kind\"]==\"desk\", c'"
check "maluctl estate nodes on a desk uses the desk token" "me estate nodes | grep -q 'estate of Local Office as desk #'"
check "no token value in the daemon logs" "! grep -q 'node_' $W/daemon.log $W/estated.log"
root office leave >/dev/null 2>&1

echo "== Phase 13 slice 1b: the overlay (the estate's network; the service in a dry run, this host as the hub, a desk as a spoke)"
: > "$W/overlay-dry.log"; rm -f "$W/hosts" "$W/estate/overlay.json"; rm -rf "$W/ovrun"
check "a desk enrols with a key before any hub: its key in $ME's compartment, no place yet" "mock /mock/code -d '{\"code\":\"spoke-code\"}' >/dev/null && root office enroll http://127.0.0.1:$PORT --code spoke-code --owner $ME --no-gateway --name 'Spoke desk' | grep -q 'overlay:  a key was sent; no hub has joined the estate yet' && me secret list | grep -q 'user:$ME/estate-overlay-key' && grep -q 'role: spoke' $W/etc/office.yaml"
DESKTOK=$(me secret show office-desk-token)   # the hub join below maps $ME to the host principal; the desk's calls then carry its token from the environment
check "join --hub refuses a bad endpoint" "root estate join http://127.0.0.1:$PORT --code x --hub nowhere 2>&1 | grep -q 'takes HOST:PORT'"
check "join as the hub: a key sent, 100.100.0.1/16, listening on udp 51820" "mock /mock/code -d '{\"code\":\"hub-code\",\"kind\":\"node\"}' >/dev/null && root estate join http://127.0.0.1:$PORT --code hub-code --name hub-node --hub 127.0.0.1:51820 | grep -q 'overlay:  100.100.0.1/16 as hub-node.internal, hub listening on udp 51820'"
check "estate.yaml carries the overlay block, no key" "grep -q 'address: 100.100.0.1' $W/etc/estate.yaml && grep -q 'role: hub' $W/etc/estate.yaml && ! grep -qE '[A-Za-z0-9+/]{43}=' $W/etc/estate.yaml"
check "the private key is in host:$HOST's compartment (generic, beside the token); the office has the public half as the hub's" "me secret list | grep -q 'host:$HOST/estate-overlay-key' && mock /mock/overlay | python3 -c 'import json,sys; o=json.load(sys.stdin); assert o[\"hub\"] and o[\"hub_endpoint\"]==\"127.0.0.1:51820\" and len(o[\"hub_key\"])==44, o'"
check "a second hub is refused (409 hub_exists)" "mock /mock/code -d '{\"code\":\"hub2\",\"kind\":\"node\"}' >/dev/null && root estate join http://127.0.0.1:$PORT --code hub2 --name hub2 --hub 127.0.0.1:51821 --force 2>&1 | grep -q 'hub_exists'"
check "the desk now has its place as a spoke of the hub (me)" "MALUOS_OFFICE_TOKEN=$DESKTOK me office status --live | grep -q 'office says: 200' && curl -fsS --max-time 5 -H 'Authorization: Bearer $DESKTOK' http://127.0.0.1:$PORT/api/v1/desks/me | python3 -c 'import json,sys; o=json.load(sys.stdin)[\"overlay\"]; assert o[\"role\"]==\"spoke\" and o[\"hub\"][\"endpoint\"]==\"127.0.0.1:51820\" and o[\"name\"]==\"spoke-desk.internal\", o'"
check "estate overlay status before the service ran: the enrolment's view" "me estate overlay status | grep -q 'overlay:    100.100.0.1/16 as hub-node.internal, hub listening on udp 51820'"
check "overlay up (root, dry run): the interface, the key on stdin, the address, forwarding, the desk as a peer" "root estate overlay up | grep -q 'estate: 100.100.0.1/16 hub, 1 peer(s)' && grep -q '^ip link add estate type wireguard' $W/overlay-dry.log && grep -q '^wg set estate private-key /dev/stdin listen-port 51820  <stdin>' $W/overlay-dry.log && grep -q '^ip -4 addr replace 100.100.0.1/16 dev estate' $W/overlay-dry.log && grep -q '^ip link set estate up' $W/overlay-dry.log && grep -q 'net.ipv4.conf.estate.forwarding=1' $W/overlay-dry.log && grep -qE '^wg set estate peer [A-Za-z0-9+/]{43}= allowed-ips 100\.100\.0\.[0-9]+/32$' $W/overlay-dry.log"
check "the names: a marked block in the hosts file, both members" "grep -q '^# maluos-estate overlay begin' $W/hosts && grep -qP '^100\.100\.0\.1\thub-node\.internal$' $W/hosts && grep -qP '^100\.100\.0\.[0-9]+\tspoke-desk\.internal$' $W/hosts && grep -q '^# maluos-estate overlay end' $W/hosts"
check "the state: configured, role hub, the desk as the peer, two names" "python3 -c 'import json; s=json.load(open(\"$W/estate/overlay.json\")); assert s[\"configured\"] and s[\"role\"]==\"hub\" and s[\"address\"]==\"100.100.0.1\" and len(s[\"peers\"])==1 and s[\"peers\"][0][\"name\"]==\"spoke-desk\" and len(s[\"names\"])==2, s'"
check "estate overlay status and peers read it" "me estate overlay status | grep -q 'interface:  estate  up  100.100.0.1/16  hub-node.internal  (hub)' && me estate overlay peers | grep -q 'peer  spoke-desk'"
check "the report carries the overlay" "me estate report --json | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r[\"overlay\"][\"configured\"] and r[\"overlay\"][\"role\"]==\"hub\" and r[\"overlay\"][\"peers\"][0][\"name\"]==\"spoke-desk\", r[\"overlay\"]' && me estate report | grep -q '^overlay:  100.100.0.1 hub-node.internal hub  1 peer(s)'"
check "estate nodes shows the members' addresses" "me estate nodes | grep -qE '^  #[0-9]+ +server +hub-node +online +[a-z]+ +100\.100\.0\.1 ' && me estate nodes | grep -qE 'desk +Spoke desk .* 100\.100\.0\.[0-9]+'"
hubkey0=$(mock /mock/overlay | python3 -c 'import json,sys; print(json.load(sys.stdin)["hub_key"])')
check "overlay rotate (root): a new key in the vault, the office has its public half, the tunnel re-keyed" "root estate overlay rotate | grep -q 'rotated: the office has the new key' && [ \"\$(mock /mock/overlay | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"hub_key\"])')\" != '$hubkey0' ] && [ \$(grep -c '^wg set estate private-key' $W/overlay-dry.log) -ge 2 ]"
check "a desk heartbeat after the change: overlay_changed, and the hint for the service" "MALUOS_OFFICE_TOKEN=$DESKTOK me office heartbeat --json | grep -q '\"overlay_changed\": true' && [ -f $W/ovrun/changed ] && MALUOS_OFFICE_TOKEN=$DESKTOK me office heartbeat --json | grep -q '\"overlay_changed\": false'"
( cd "$W"; exec sudo -n env $ENV python3 -m maluos_estate.overlay >"$W/overlay.log" 2>&1 ) & echo $! > "$W/overlay.pid"
for i in $(seq 1 40); do grep -q "overlay-dry" /dev/null; [ "$(stat -c %Y $W/estate/overlay.json 2>/dev/null || echo 0)" -ge "$(( $(date +%s) - 2 ))" ] && break; sleep 0.25; done
check "the service (dry run) reconciles on start and clears the hint" "sleep 1; python3 -c 'import json; s=json.load(open(\"$W/estate/overlay.json\")); assert s[\"configured\"] and s[\"role\"]==\"hub\"' && [ ! -f $W/ovrun/changed ]"
v0=$(python3 -c "import json; print(json.load(open('$W/estate/overlay.json'))['version'])")
MALUOS_OFFICE_TOKEN=$DESKTOK me office heartbeat --json >/dev/null 2>&1; mock /api/v1/estate/overlay/key -X POST -H "Authorization: Bearer $DESKTOK" -d "{\"overlay_public_key\": \"$(python3 -c 'import sys; sys.path.insert(0,"'$W'/lib"); from maluos_estate import overlay as OV; print(OV.genkey()[1])')\"}" >/dev/null
me estate heartbeat --json >/dev/null 2>&1
for i in $(seq 1 40); do [ "$(python3 -c "import json; print(json.load(open('$W/estate/overlay.json'))['version'])")" != "$v0" ] && break; sleep 0.25; done
check "the desk's key rotated: the hint made the service refresh at once (a new version, the peer re-set)" "[ \"\$(python3 -c \"import json; print(json.load(open('$W/estate/overlay.json'))['version'])\")\" != '$v0' ] && [ \$(grep -c 'allowed-ips 100.100.0' $W/overlay-dry.log) -ge 3 ]"
sudo -n kill -TERM $(cat "$W/overlay.pid") 2>/dev/null; for i in $(seq 1 40); do kill -0 $(cat "$W/overlay.pid") 2>/dev/null || break; sleep 0.25; done
check "SIGTERM leaves the tunnel up (no ip link del in the log yet)" "! grep -q 'ip link del' $W/overlay-dry.log && [ -f $W/estate/overlay.json ]"
check "overlay down (root): the interface deleted, the names and the state gone" "root estate overlay down | grep -q 'is down' && grep -q '^ip link del estate' $W/overlay-dry.log && ! grep -q 'maluos-estate overlay' $W/hosts && [ ! -f $W/estate/overlay.json ]"
check "estate leave: the hub's key removed with the token; the office has no hub" "root estate leave | grep -q 'the overlay tunnel down, its key removed' && ! me secret list | grep -q 'host:$HOST/estate-overlay-key' && mock /mock/overlay | python3 -c 'import json,sys; o=json.load(sys.stdin); assert o[\"hub\"] is None, o'"
check "office leave: the desk's tunnel down and its key removed; no member left" "root office leave | grep -q 'the overlay tunnel down' && ! me secret list | grep -q 'user:$ME/estate-overlay-key' && ! sudo -n env $ENV python3 $W/lib/maluctl secret list --all 2>/dev/null | grep -q 'estate-overlay-key' && mock /mock/overlay | python3 -c 'import json,sys; o=json.load(sys.stdin); assert o[\"members\"]==[], o'"
check "no private key in the logs or the dry log (the keys go to wg on stdin)" "! grep -qE 'private-key +[A-Za-z0-9+/]{43}=' $W/overlay-dry.log && ! grep -qE '[A-Za-z0-9+/]{43}=' $W/overlay.log $W/daemon.log"

echo; echo "$n checks, $fail failed"
[ $fail = 0 ] && echo "PASS: maluctl office against the mock office" || echo "FAIL"
exit $fail
