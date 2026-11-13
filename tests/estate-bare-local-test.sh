#!/bin/bash
# Phase 14 slice 4a (docs/phase14-watching-agents.md): a server with no vault and no gateway (a database server)
# joins the estate as a bare node. Against the mock office, from the source tree, with scratch files; needs sudo
# (maluctl estate join and leave are root's). Nothing of the host's own enrolment is touched.
#   tests/estate-bare-local-test.sh
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
D=$(mktemp -d /tmp/estate-bare.XXXXXX); PORT=${PORT:-18093}; fail=0
LIB=$D/lib; mkdir -p "$LIB/maluctl.d" "$D/state" "$D/etc"
cp -r "$ROOT/packages/maluos-estate/lib/maluos_estate" "$LIB/"
cp "$ROOT/packages/maluos-estate/lib/maluctl.d/estate.py" "$LIB/maluctl.d/"
echo '{"role": "database-server", "components": {}, "database_server": {"port": 5432, "clients": ["192.0.2.20"], "tls": true}}' > "$D/done"
ME=$(id -un)
ENVV=(MALUOS_ESTATE_CONF=$D/etc/estate.yaml MALUOS_ESTATE_STATE_DIR=$D/state MALUOS_ESTATE_USER=$ME MALUOS_ESTATE_NO_UNIT=1
      MALUOS_PROVISIONED=$D/done MALUOS_VAULT_CONFIG=$D/etc/vault.yaml MALUOS_GATEWAY_CONFIG=$D/etc/gateway.yaml
      MALUOS_VAULT_SOCKET=$D/no-vault.sock MALUOS_GATEWAY_SOCKET=$D/no-gateway.sock MALUOS_MEMORY_SOCKET=$D/no-memory.sock PYTHONPATH=$LIB PYTHONDONTWRITEBYTECODE=1)
estate() { env "${ENVV[@]}" python3 -c 'import sys, runpy; sys.argv = ["maluctl-estate"] + sys.argv[1:]; m = runpy.run_path(sys.argv.pop(1)); sys.exit(m["main"](sys.argv[1:]))' "$LIB/maluctl.d/estate.py" "$@"; }
sestate() { sudo -n env "${ENVV[@]}" python3 -c 'import sys, runpy; sys.argv = ["maluctl-estate"] + sys.argv[1:]; m = runpy.run_path(sys.argv.pop(1)); sys.exit(m["main"](sys.argv[1:]))' "$LIB/maluctl.d/estate.py" "$@"; }
ok() { echo "  ok   $1"; }; bad() { echo "  FAIL $1"; fail=1; }
cleanup() { [ -n "${MOCK:-}" ] && kill "$MOCK" 2>/dev/null; [ -n "${DAEMON:-}" ] && kill "$DAEMON" 2>/dev/null; sudo -n rm -rf "$D"; }
trap cleanup EXIT

PYTHONPATH=$LIB PYTHONDONTWRITEBYTECODE=1 python3 -m maluos_estate.mock_office --port "$PORT" --node-code bare-code --node-code full-code --name "Mock Estate" --node-heartbeat-s 5 --report-s 5 >"$D/mock.log" 2>&1 & MOCK=$!
for i in $(seq 1 30); do curl -fsS "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1 && break; sleep 0.3; done
URL=http://127.0.0.1:$PORT

out=$(sestate join "$URL" --code full-code --name plain 2>&1); rc=$?
[ $rc != 0 ] && echo "$out" | grep -q 'has no vault.*--bare' && [ ! -e "$D/etc/estate.yaml" ] && ok "a server without a vault is told to join with --bare, and nothing is written" || bad "join without a vault: rc=$rc $out"
out=$(sestate join "$URL" --code bare-code --bare --kind inference 2>&1); rc=$?
[ $rc != 0 ] && echo "$out" | grep -q 'no --kind but server' && ok "--bare takes no other kind" || bad "--bare --kind inference: rc=$rc $out"

out=$(sestate join "$URL" --code bare-code --bare --name db-1 2>&1); rc=$?
TOK=$(sudo -n cat "$D/state/node.token" 2>/dev/null)
[ $rc = 0 ] && echo "$out" | grep -q "a bare node: no vault, no agents" && [ -n "$TOK" ] && ok "joined bare" || bad "bare join: rc=$rc $out"
! echo "$out" | grep -qF "$TOK" && ok "the join's output does not show the token" || bad "the token is in the join's output"
[ "$(stat -c '%a %U' "$D/state/node.token")" = "600 $ME" ] && [ "$(stat -c '%a %U' "$D/state/node.key")" = "600 $ME" ] && [ "$(stat -c '%a' "$D/state")" = 700 ] \
  && ok "the token and the key are 0600 files of the node service's user in a 0700 directory" || bad "file modes: $(stat -c '%a %U %n' "$D/state" "$D/state"/node.* 2>&1 | tr '\n' ' ')"
python3 - "$D/etc/estate.yaml" "$TOK" <<'PY' && ok "estate.yaml: bare, no principal, no vault secrets, no overlay, the bare node's four actions (no reboot), no token in it" || bad "estate.yaml"
import json, sys
raw = open(sys.argv[1]).read()
try:
    c = json.loads(raw)
except ValueError:
    import yaml; c = yaml.safe_load(raw)
assert c.get("bare") is True and c.get("principal") is None and not c.get("secrets") and not c.get("overlay"), c
assert c["actions"]["allow"] == ["apply_updates", "restart_unit", "postgres_cancel", "postgres_terminate"] and c["node"]["name"] == "db-1", c
assert sys.argv[2] not in raw
PY
estate status 2>&1 | grep -q 'a bare node: no vault' && ok "status says it is a bare node" || bad "status: $(estate status 2>&1 | tail -3)"

env "${ENVV[@]}" python3 -m maluos_estate >"$D/daemon.log" 2>&1 & DAEMON=$!
for i in $(seq 1 60); do curl -fsS "$URL/mock/nodes" 2>/dev/null | grep -q '"last_report_at": "2' && break; sleep 0.5; done
NID=$(curl -fsS "$URL/mock/nodes" | python3 -c 'import json,sys; print([n["id"] for n in json.load(sys.stdin)["nodes"] if n["name"] == "db-1"][0])')
curl -fsS -H "Authorization: Bearer $TOK" "$URL/api/v1/estate/nodes/$NID" > "$D/nodes.json"
python3 - "$D/nodes.json" <<'PY' && ok "the node is online with a report: the database server's units only, the database part, no vault or gateway part" || bad "the report: $(head -c 600 "$D/nodes.json")"
import json, sys
d = json.load(open(sys.argv[1]))
def find(x):
    if isinstance(x, dict):
        if x.get("name") == "db-1" and "report" in x:
            return x
        x = list(x.values())
    for y in x if isinstance(x, list) else []:
        r = find(y)
        if r:
            return r
n = find(d)
assert n, list(d)
assert n.get("presence") == "online", n.get("presence")
rep = n.get("report") or {}
units = [u["unit"] for u in rep.get("units") or []]
assert not any("vault" in u or "gateway" in u for u in units), units
assert (rep.get("database") or {}).get("role") == "server", rep.get("database")
assert not rep.get("vault") and not rep.get("gateway"), (rep.get("vault"), rep.get("gateway"))
PY
grep -q '"role": "database-server"' "$D/mock.log" "$D/nodes.json" 2>/dev/null || env "${ENVV[@]}" python3 -c 'from maluos_estate import client as C; assert C.facts()["role"] == "database-server"' \
  && ok "the node's facts carry its role (database-server)" || bad "the role fact"
# Phase 14 slice 4d: the verbs the office may ask of this node (queued as the kernel queues an approved request)
estate actions 2>&1 | grep -q 'apply_updates, restart_unit, postgres_cancel, postgres_terminate' && estate actions 2>&1 | grep -q 'restart_unit may name: postgresql@18-main.service, maludb-mc2dbd.service' \
  && ok "a bare database server allows updates, a restart of its two units, and cancelling or ending a backend" || bad "actions: $(estate actions 2>&1 | tr '\n' ' ')"
( PGAPPNAME=estate-bare-victim psql -qAtX -d postgres -c "select pg_sleep(300)" >/dev/null 2>&1 & )
for i in $(seq 1 20); do VPID=$(psql -AtX -d postgres -c "select pid from pg_stat_activity where application_name = 'estate-bare-victim'" 2>/dev/null); [ -n "$VPID" ] && break; sleep 0.3; done
act() { curl -fsS -H 'Content-Type: application/json' -d "{\"node_id\": $NID, \"action\": \"$1\", \"args\": $2}" "$URL/mock/action" | python3 -c 'import json,sys; print(json.load(sys.stdin)["action"]["id"])'; }
A1=$(act restart_unit '{"unit": "ssh.service"}'); A2=$(act restart_unit '{"unit": "postgresql@18-main.service; reboot"}'); A3=$(act reboot null)
A4=$(act postgres_terminate "{\"pid\": ${VPID:-0}}"); A5=$(act postgres_cancel '{"pid": 4194000}'); A6=$(act postgres_terminate '{"pid": "1; select 1"}')
for i in $(seq 1 90); do curl -fsS "$URL/mock/actions" | python3 -c 'import json,sys; sys.exit(0 if all(a["state"] not in ("queued", "leased") for a in json.load(sys.stdin)["actions"]) else 1)' && break; sleep 1; done
curl -fsS "$URL/mock/actions" > "$D/actions.json"
python3 - "$D/actions.json" "$A1" "$A2" "$A3" "$A4" "$A5" "$A6" <<'PY' && ok "the node's answers: a unit off its list and a unit with a command refused, reboot refused, the backend ended, an unknown pid failed, a pid that is not a number refused" || bad "the actions: $(python3 -c "import json; print([(a['action'], a['state'], a.get('reason'), (a.get('result') or {}).get('error')) for a in json.load(open('$D/actions.json'))['actions']])")"
import json, sys
acts = {a["id"]: a for a in json.load(open(sys.argv[1]))["actions"]}
a1, a2, a3, a4, a5, a6 = (acts[i] for i in sys.argv[2:8])
assert a1["state"] == "refused" and a1["reason"] == "not_allowed" and "actions.units" in a1["result"]["error"], a1
assert a2["state"] == "refused" and a2["reason"] == "not_allowed", a2
assert a3["state"] == "refused" and a3["reason"] == "not_allowed" and "actions.allow" in a3["result"]["error"], a3
assert a4["state"] == "completed" and a4["result"]["ok"] is True and "pg_terminate_backend" in a4["result"]["output"], a4
assert a5["state"] == "failed" and "no client backend" in a5["result"]["error"], a5
assert a6["state"] == "refused" and a6["reason"] == "invalid", a6
PY
[ -z "$(psql -AtX -d postgres -c "select pid from pg_stat_activity where application_name = 'estate-bare-victim'")" ] && ok "the session is gone from the cluster" || bad "the session is still there"
kill "$DAEMON" 2>/dev/null; wait "$DAEMON" 2>/dev/null; DAEMON=
grep -q 'said offline' "$D/daemon.log" && ok "the daemon said offline when stopped" || bad "daemon: $(tail -3 "$D/daemon.log")"
! grep -qF "$TOK" "$D/daemon.log" && ok "the daemon's log does not show the token" || bad "the token is in the daemon's log"

out=$(sestate leave 2>&1); rc=$?
[ $rc = 0 ] && echo "$out" | grep -q 'told; node retired' && [ ! -e "$D/state/node.token" ] && [ ! -e "$D/state/node.key" ] && [ ! -e "$D/etc/estate.yaml" ] \
  && ok "leave: the office told, the token, the key and the enrolment removed" || bad "leave: rc=$rc $out"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" "$URL/api/v1/estate/me")" != 200 ] && ok "the old token is refused" || bad "the old token still works"

[ $fail = 0 ] && echo "PASS: a bare node joins, reports and leaves" || echo "FAIL"
exit $fail
