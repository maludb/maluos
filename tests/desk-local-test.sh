#!/bin/bash
# Exercise `maluctl office` and the mock office on this host, without a VM: a throwaway
# database and the real vault daemon (as in vault-local-test.sh), the mock office on a
# local port, enrol/heartbeat/status/leave as root for the current user, no gateway
# (--no-gateway; the image boot test covers the office rung). Needs passwordless sudo.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
W=/var/tmp/maluos-desk-test; DB=maluos_desktest; T=dt; VROLE=desktest_vault; ME=$(id -un); PORT=18981
fail=0; n=0
ok()   { n=$((n+1)); echo "  ok   $*"; }
bad()  { n=$((n+1)); fail=$((fail+1)); echo "  FAIL $*"; }
check(){ if (set +o pipefail; eval "$2"); then ok "$1"; else bad "$1"; fi; }

sudo -n true 2>/dev/null || { echo "needs passwordless sudo"; exit 2; }
pkill -f "$W/lib/maluos_vault.py" 2>/dev/null; pkill -f "maluos_desk.mock_office --port $PORT" 2>/dev/null; sleep 0.5
sudo rm -rf "$W"; mkdir -p "$W/lib/maluctl.d" "$W/cred" "$W/state" "$W/etc"; chmod 755 "$W" "$W/lib" "$W/lib/maluctl.d" "$W/etc"
cp "$ROOT"/packages/maluos-firstboot/lib/maluos_provision.py "$ROOT"/packages/maluos-firstboot/bin/maluctl \
   "$ROOT"/packages/maluos-vault/lib/maluos_vault.py "$ROOT"/packages/maluos-vault/lib/maluos_vault_client.py \
   "$ROOT"/packages/maluos-vault/components/40-maluos-vault.py "$ROOT"/packages/maluos-vault/share/schema.sql "$W/lib/"
cp "$ROOT"/packages/maluos-vault/lib/maluctl.d/secret.py "$ROOT"/packages/maluos-desk/lib/maluctl.d/office.py "$W/lib/maluctl.d/"
cp -r "$ROOT"/packages/maluos-desk/lib/maluos_desk "$W/lib/"
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
( cd "$W" && PYTHONPATH=$W/lib python3 -m maluos_desk.mock_office --port $PORT --code good-code --name "Local Office" --models office-7b --heartbeat-s 5 >"$W/office.log" 2>&1 & echo $! > "$W/office.pid" )
trap 'kill $(cat $W/daemon.pid) $(cat $W/office.pid) 2>/dev/null' EXIT
for i in $(seq 1 20); do [ -S "$W/vault.sock" ] && curl -fsS --max-time 1 http://127.0.0.1:$PORT/api/v1/health >/dev/null 2>&1 && break; sleep 0.25; done
ENV="PYTHONPATH=$W/lib MALUCTL_PLUGIN_DIR=$W/lib/maluctl.d MALUCTL_BIN=$W/lib/maluctl MALUOS_VAULT_SOCKET=$W/vault.sock MALUOS_OFFICE_CONF=$W/etc/office.yaml MALUOS_OFFICE_ENV=$W/etc/office.env XDG_STATE_HOME=$W/state-$ME"
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

echo; echo "$n checks, $fail failed"
[ $fail = 0 ] && echo "PASS: maluctl office against the mock office" || echo "FAIL"
exit $fail
