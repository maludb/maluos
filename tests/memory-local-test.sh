#!/bin/bash
# Exercise the memory face (packages/maluos-memory) on this host, without a VM: a throwaway database and tenant,
# the real vault daemon (for the signing key), the face as the current user with a NOLOGIN role standing in for
# maluos-memory, a hand-written peers and holders cache naming this host as its own peer, and envelopes signed the
# way the hosts sign (maluos_estate.envelope). Covers docs/phase13-slice4-memory.md decisions 1, 2, 4, 5, 6, 8, 9
# and 10 on one host. Needs passwordless sudo and PostgreSQL 18 with maludb_core.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
W=/var/tmp/maluos-memory-test; DB=maluos_memtest; T=mt; VROLE=memtest_vault; FROLE=memtest_face; ME=$(id -un); PORT=18987
fail=0; n=0
ok()   { n=$((n+1)); echo "  ok   $*"; }
bad()  { n=$((n+1)); fail=$((fail+1)); echo "  FAIL $*"; }
check(){ if (set +o pipefail; eval "$2"); then ok "$1"; else bad "$1"; fi; }

sudo -n true 2>/dev/null || { echo "needs passwordless sudo"; exit 2; }
pkill -f "$W/lib/maluos_vault.py" 2>/dev/null; pkill -f "maluos_memory --socket $W/memory.sock" 2>/dev/null; sleep 0.5
sudo rm -rf "$W"; mkdir -p "$W/lib/maluctl.d" "$W/cred" "$W/state" "$W/etc" "$W/fb" "$W/estate-run" "$W/mem-state"; chmod 755 "$W" "$W/lib" "$W/lib/maluctl.d" "$W/etc" "$W/fb" "$W/estate-run"
cp "$ROOT"/packages/maluos-firstboot/lib/maluos_provision.py "$ROOT"/packages/maluos-firstboot/bin/maluctl \
   "$ROOT"/packages/maluos-vault/lib/maluos_vault.py "$ROOT"/packages/maluos-vault/lib/maluos_vault_client.py \
   "$ROOT"/packages/maluos-vault/components/40-maluos-vault.py "$ROOT"/packages/maluos-vault/share/schema.sql \
   "$ROOT"/packages/maluos-memory/components/50-maluos-memory.py "$W/lib/"
cp "$ROOT"/packages/maluos-vault/lib/maluctl.d/secret.py "$ROOT"/packages/maluos-memory/lib/maluctl.d/memory.py "$W/lib/maluctl.d/"
cp -r "$ROOT"/packages/maluos-memory/lib/maluos_memory "$ROOT"/packages/maluos-estate/lib/maluos_estate "$W/lib/"
chmod -R a+rX "$W/lib"; head -c 32 /dev/urandom > "$W/cred/maluos-vault.key"
HOST=$(hostname)
cat > "$W/vault.yaml" <<EOY
socket: $W/vault.sock
database: $DB
tenant: $T
pg_role: $VROLE
state_dir: $W/state
brokers: []
identities: {}
EOY
cat > "$W/memory.yaml" <<EOY
database: $DB
tenant: $T
pg_role: $FROLE
socket: $W/memory.sock
guest: estate:guest
sync_principal: estate:sync
fanout_s: 3
ask_self: true
tcp: {enabled: false, host: 127.0.0.1, port: $PORT}
EOY
cat > "$W/etc/estate.yaml" <<EOY
url: http://127.0.0.1:1
principal: user:$ME
node: {kind: server, id: 57, name: self-node}
overlay: {address: 127.0.0.1, name: self-node}
endpoints: {}
EOY
chmod 644 "$W/vault.yaml" "$W/memory.yaml" "$W/etc/estate.yaml"

echo "== database $DB (tenant $T): the principals, the vault's schema, the face's role"
sudo -n -u postgres psql -Xq -c "DROP DATABASE IF EXISTS $DB" -c "DROP ROLE IF EXISTS $VROLE" -c "DROP ROLE IF EXISTS $FROLE" -c "DROP ROLE IF EXISTS $T" >/dev/null
sudo -n env PYTHONPATH="$W/lib" python3 - "$DB" "$T" "$VROLE" "$FROLE" "$ME" "$W" <<'PY' || exit 1
import sys, importlib.util
import maluos_provision as mp
db, t, vrole, frole, me, w = sys.argv[1:7]
mp.ensure_database(db); mp.ensure_tenant(db, t)
pre = f"SET ROLE {mp.qi(t)}; SET search_path TO {mp.qi(t)}, maludb_core, public; "
mp.psql(pre + f"SELECT maludb_principal_upsert('user:{me}', 'human', '{me}', 'user:{me}', 'restricted', true);", db)
for ref, kind, home, mx in (("agent:hr", "agent", "agent:hr", "restricted"), ("agent:sched", "agent", "agent:sched", "internal"), ("agent:other", "agent", "agent:other", "internal")):
    mp.psql(pre + f"SELECT maludb_principal_upsert('{ref}', '{kind}', '{ref}', '{home}', '{mx}', true);", db)
for ref, scope, level in ((f"user:{me}", "dept:3", "write"), (f"user:{me}", "org", "read"), ("agent:hr", "dept:3", "write"), ("agent:hr", "org", "write"), ("agent:sched", "dept:3", "read"), ("agent:other", "dept:9", "write")):
    mp.psql(pre + f"SELECT maludb_principal_grant_scope('{ref}', '{scope}', '{level}');", db)
spec = importlib.util.spec_from_file_location("comp", f"{w}/lib/40-maluos-vault.py"); comp = importlib.util.module_from_spec(spec); spec.loader.exec_module(comp)
mp.psql(f"CREATE ROLE {mp.qi(vrole)} NOLOGIN"); mp.psql(f"CREATE ROLE {mp.qi(frole)} NOLOGIN")
comp.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, t, role=vrole, schema=f"{w}/lib/schema.sql")
spec = importlib.util.spec_from_file_location("comp50", f"{w}/lib/50-maluos-memory.py"); c50 = importlib.util.module_from_spec(spec); spec.loader.exec_module(c50)
c50.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, t, role=frole)
c50.ensure_principals(mp.psql, mp.qi, mp.ql, db, t)
mp.psql(f"GRANT {mp.qi(frole)} TO {mp.qi(me)}; GRANT {mp.qi(vrole)} TO {mp.qi(me)}")
mp.psql(pre + f"INSERT INTO maluos_agent (name, principal_ref, owner_principal_ref, exec, sandbox) VALUES ('hr', 'agent:hr', 'user:{me}', '/bin/true', 'standard'), ('other', 'agent:other', 'user:nobody', '/bin/true', 'standard');", db)
print("  tenant, principals (user:%s dept:3 write + org read; agent:hr; agent:sched; agent:other), the vault's and the face's schema" % me)
PY
printf '{"database":"%s","tenant":"%s","provisioned_at":"test","admin_principal":"human:admin","operators":[],"components":{"vault":{}}}\n' $DB $T > "$W/fb/done"

echo "== the vault (the signing key) and the face"
( cd "$W" && CREDENTIALS_DIRECTORY=$W/cred MALUOS_VAULT_CONFIG=$W/vault.yaml python3 "$W/lib/maluos_vault.py" --socket "$W/vault.sock" >"$W/vault.log" 2>&1 & echo $! > "$W/vault.pid" )
for i in $(seq 1 20); do [ -S "$W/vault.sock" ] && break; sleep 0.25; done
ENV="PYTHONPATH=$W/lib MALUCTL_PLUGIN_DIR=$W/lib/maluctl.d MALUCTL_BIN=$W/lib/maluctl MALUOS_VAULT_SOCKET=$W/vault.sock MALUOS_VAULT_CONF=$W/vault.yaml MALUOS_MEMORY_SOCKET=$W/memory.sock MALUOS_MEMORY_CONFIG=$W/memory.yaml MALUOS_MEMORY_STATE=$W/mem-state MALUOS_ESTATE_CONF=$W/etc/estate.yaml MALUOS_OFFICE_CONF=$W/etc/office.yaml MALUOS_ESTATE_MEMORY=$W/estate-run/memory.json MALUOS_ESTATE_MEMORY_PEERS=$W/estate-run/memory-peers.json MALUOS_OFFICE_MEMORY=$W/office-run/memory.json MALUOS_OFFICE_MEMORY_PEERS=$W/office-run/memory-peers.json MALUOS_ESTATE_KEYS=$W/estate-run/keys.json MALUOS_PROVISIONED=$W/fb/done MALUOS_STATE_DIR=$W/fb"
me()   { env $ENV python3 "$W/lib/maluctl" "$@"; }
root() { sudo -n env $ENV python3 "$W/lib/maluctl" "$@"; }
# this host's signing key: made the way the hosts make theirs, the private half in the vault as user:$ME/estate-node-key (estate.yaml names user:$ME as the principal)
env $ENV python3 - "$W" <<'PY'
import sys, json
from maluos_estate import envelope as E
w = sys.argv[1]
priv, pub = E.genkey("self-node")
open(f"{w}/node.key", "w").write(priv); open(f"{w}/node.pub", "w").write(pub)
PY
me secret add estate-node-key --kind generic --provider estate --stdin < "$W/node.key" >/dev/null || echo "  warn: secret add: $(me secret add estate-node-key --stdin < $W/node.key 2>&1 | tail -1)"
( cd "$W" && exec env $ENV python3 -m maluos_memory --socket "$W/memory.sock" --no-sync >"$W/face.log" 2>&1 ) & echo $! > "$W/face.pid"
trap 'kill $(cat $W/vault.pid) $(cat $W/face.pid) 2>/dev/null' EXIT
for i in $(seq 1 40); do [ -S "$W/memory.sock" ] && me memory whoami >/dev/null 2>&1 && break; sleep 0.25; done
check "the face answers: whoami is user:$ME with dept:3 (write) and org (read), ceiling restricted" "me memory whoami | grep -q \"principal: user:$ME\" && me memory whoami | grep -q 'writes:    dept:3, user:$ME' && me memory whoami | grep -q 'ceiling:   restricted'"
check "status: not exposed, the guest shares nothing, the node membership with a readable signing key" "me memory status | grep -q 'not exposed' && me memory status | grep -q 'shared nothing' && me memory status | grep -q 'node:      server:57 as user:$ME; signing key user:$ME/estate-node-key readable'"

echo "== writes as principals (decision 8): the home scope, a departmental scope with a write grant, never without"
check "remember into dept:3 as $ME: a note with confidence, source and detail" "me memory remember 'Alex completed forklift training on 2026-09-01' --scope dept:3 --confidence 0.9 --source hr:training/118 --detail '{\"certificate\": \"FL-2231\"}' | grep -q 'remembered #[0-9]* in dept:3 (note) as user:$ME'"
check "remember into dept:9 is refused scope_write" "! me memory remember x --scope dept:9 >/dev/null 2>&1 && me memory remember x --scope dept:9 2>&1 | grep -q 'scope_write'"
check "remember into org (read only) is refused scope_write" "me memory remember x --scope org 2>&1 | grep -q 'scope_write'"
check "remember without --scope lands in the home scope" "me memory remember 'my own note' | grep -q \"in user:$ME (note)\""
check "--as agent:hr (owned by $ME through the registry): a restricted note in dept:3" "me memory remember 'Alex has a lifting restriction until December' --scope dept:3 --sensitivity restricted --as agent:hr | grep -q 'in dept:3 (note) as agent:hr'"
check "--as agent:hr: an org summary (kind summary)" "me memory remember 'Q3 safety: zero incidents, two near misses on the loading dock' --scope org --kind summary --title 'Q3 safety' --as agent:hr | grep -q 'in org (summary) as agent:hr'"
check "--as agent:other (not owned) is refused not_owner" "me memory remember x --scope dept:9 --as agent:other 2>&1 | grep -q 'not_owner'"
check "a restricted note above the writer's internal ceiling (agent:other, as the operator) is refused classification" "root memory remember x --scope dept:9 --sensitivity restricted --as agent:other 2>&1 | grep -q 'classification'"
check "a bad kind is refused invalid" "me memory remember x --scope dept:3 --kind rumour 2>&1 | grep -q 'invalid'"

echo "== local recall (decision 6): claims, the grants, the ceilings, the detail"
check "recall 'forklift' as $ME: one claim from dept:3 with confidence, source, writer and holder server:57, no detail" "me memory recall forklift | grep -q '1 claim(s)' && me memory recall forklift | grep -q 'dept:3  note  internal  confidence 0.9  source hr:training/118  by user:$ME' && me memory recall forklift | grep -q 'holder server:57' && ! me memory recall forklift | grep -q certificate"
check "--detail (a writer of the scope) shows the detail" "me memory recall forklift --detail | grep -q 'detail {\"certificate\": \"FL-2231\"}'"
check "the restricted note is hidden at the default internal classification" "! me memory recall lifting | grep -q 'lifting restriction'"
check "and shown with --classification restricted (within the principal's ceiling)" "me memory recall lifting --classification restricted | grep -q 'lifting restriction' && me memory recall lifting --classification restricted | grep -q 'restricted  by agent:hr'"
check "--scope dept:9 is refused forbidden (not a scope of this principal)" "me memory recall x --scope dept:9 2>&1 | grep -q 'forbidden'"
check "--scope org finds the summary; --kind summary filters" "me memory recall safety --scope org --kind summary | grep -q 'org  summary  internal' && ! me memory recall forklift --kind summary | grep -q forklift"
check "--as agent:sched (dept:3 read, ceiling internal): the note, never the restricted one, not even when asked" "me memory recall forklift --as agent:sched 2>&1 | grep -q 'not_owner' || true; root memory recall forklift --as agent:sched | grep -q 'forklift' && ! root memory recall lifting --as agent:sched --classification restricted | grep -q 'lifting'"
check "the facts: dept:3 holds 2 (note 2), org 1 (summary 1), the home scope never listed, nothing shared" "me memory facts --json | python3 -c 'import json,sys; f=json.load(sys.stdin); s={x[\"scope\"]: x for x in f[\"scopes\"]}; assert set(s)=={\"dept:3\",\"org\"} and s[\"dept:3\"][\"count\"]==2 and s[\"dept:3\"][\"kinds\"]=={\"note\": 2} and s[\"org\"][\"kinds\"]=={\"summary\": 1} and f[\"shared\"]==[] and f[\"port\"]==$PORT, f'"

echo "== sharing and exposing (decision 5): the guest principal's grants are what the host serves"
check "share needs root" "! me memory share dept:3 >/dev/null 2>&1"
check "share refuses a personal scope" "root memory share agent:hr 2>&1 | grep -q 'shareable scope'"
check "sudo maluctl memory share dept:3 org --max internal: the guest reads both; the facts say so" "root memory share dept:3 org --max internal | grep -q 'shared: dept:3, org; ceiling internal' && me memory facts --json | python3 -c 'import json,sys; f=json.load(sys.stdin); assert f[\"shared\"]==[\"dept:3\",\"org\"] and f[\"max_classification\"]==\"internal\"'"
check "expose: the listener on 127.0.0.1:$PORT (the configuration says --bind 127.0.0.1 here; overlay by default)" "root memory expose --bind 127.0.0.1 --port $PORT | grep -q \"listening on 127.0.0.1:$PORT\" && curl -fsS --max-time 3 http://127.0.0.1:$PORT/memory/v1/health | grep -q '\"node\": \"server:57\"'"
# the peers and holders caches the estate daemon would write: this host is its own peer and its own holder (one host plays both sides)
PUB=$(cat "$W/node.pub")
python3 - "$W" "$PUB" "$PORT" <<'PY'
import json, sys
w, pub, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
peers = {"ok": True, "self": "server:57", "version": 3, "fetched_at": "2026-10-31T00:00:00Z", "source": "node", "principal": "user:x", "written_at": "2026-10-31T00:00:00Z",
         "peers": [{"node": "server:57", "id": 57, "kind": "server", "name": "self-node", "address": "127.0.0.1", "public_key": pub,
                    "scopes": [{"scope": "dept:3", "classification_max": "internal", "replicate": True, "priority": 0}, {"scope": "org", "classification_max": "restricted", "replicate": False, "priority": 0}]},
                   {"node": "desk:41", "id": 41, "kind": "desk", "name": "a-desk", "address": "127.0.0.2", "public_key": None, "scopes": [{"scope": "org", "classification_max": "internal", "replicate": False, "priority": 0}]}]}
holders = {"ok": True, "self": "server:57", "version": 3, "fetched_at": "2026-10-31T00:00:00Z", "source": "node", "written_at": "2026-10-31T00:00:00Z",
           "holders": [{"node": "server:57", "id": 57, "kind": "server", "name": "self-node", "address": "127.0.0.1", "port": port, "api_version": 1, "max_classification": "internal",
                        "scopes": [{"scope": "dept:3", "count": 2, "classification_max": "internal", "replicate": True, "priority": 0}, {"scope": "org", "count": 1, "classification_max": "restricted", "replicate": False, "priority": 0}]},
                       {"node": "server:99", "id": 99, "kind": "server", "name": "gone-node", "address": "127.0.0.1", "port": 1, "api_version": 1, "max_classification": "internal",
                        "scopes": [{"scope": "org", "count": 5, "classification_max": "internal", "replicate": False, "priority": 0}]}]}
json.dump(peers, open(f"{w}/estate-run/memory-peers.json", "w")); json.dump(holders, open(f"{w}/estate-run/memory.json", "w"))
PY
chmod 644 "$W/estate-run/"*.json
sed -i 's/^ask_self: true$/ask_self: false/' "$W/memory.yaml"; root memory reload >/dev/null
check "a host never asks itself (ask_self false, the default): self-node is this host, so only gone-node is a holder; the peers stay" "me memory status | grep -q 'holders:   1 published to this host: gone-node (org)' && me memory status | grep -q 'peers:     2 may ask this host'"
sed -i 's/^ask_self: false$/ask_self: true/' "$W/memory.yaml"; root memory reload >/dev/null
check "status lists the holder and the peers from the caches (ask_self true: the one-host proof)" "me memory status | grep -q 'holders:   2 published to this host: self-node (dept:3, org); gone-node (org)' && me memory status | grep -q 'peers:     2 may ask this host: self-node (dept:3, org); a-desk (org)'"

echo "== the estate's gate (decisions 4 and 5): an envelope signed by a peer, verified against the peers cache"
cat > "$W/ask.py" <<'EOA'
import json, os, sys, urllib.request, urllib.error
from maluos_estate import envelope as E
w, port = os.environ["W"], int(os.environ["PORT"])
priv = open(f"{w}/node.key").read()
def envelope(originator, scopes, cls="internal", node="server:57", key=None, life=120, bad=False):
    me = {"principal": originator, "node": node}
    env = E.make(dict(me, kind="agent" if originator.startswith("agent:") else "human"), me, {"node": "server:57"}, "memory",
                 {"scopes": [f"{s}:read" for s in scopes], "classification": cls, "budget": {"usd": 0, "calls": 0}}, life_s=life)
    env = E.sign(env, node, key or priv)
    if bad:
        env["purpose"] = "tampered"
    return env
def call(path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
a = sys.argv[1]
if a == "query":
    scopes = sys.argv[2].split(","); q = sys.argv[3]; cls = sys.argv[4] if len(sys.argv) > 4 else "internal"
    env = envelope("agent:sched", sys.argv[5].split(",") if len(sys.argv) > 5 else scopes, cls if cls != "lowenv" else "internal")
    st, d = call("/memory/v1/query", {"envelope": env, "scopes": scopes, "query": q, "classification": "restricted" if cls == "lowenv" else cls, "limit": 10})
elif a == "replay":
    env = envelope("agent:sched", ["org"])
    call("/memory/v1/query", {"envelope": env, "scopes": ["org"], "query": "safety"})
    st, d = call("/memory/v1/query", {"envelope": env, "scopes": ["org"], "query": "safety"})
elif a == "tampered":
    st, d = call("/memory/v1/query", {"envelope": envelope("agent:sched", ["org"], bad=True), "scopes": ["org"], "query": "safety"})
elif a == "otherkey":
    p2, _ = E.genkey("x")
    st, d = call("/memory/v1/query", {"envelope": envelope("agent:sched", ["org"], key=p2), "scopes": ["org"], "query": "safety"})
elif a == "stranger":
    st, d = call("/memory/v1/query", {"envelope": envelope("agent:sched", ["org"], node="server:77"), "scopes": ["org"], "query": "safety"})
elif a == "noenv":
    st, d = call("/memory/v1/query", {"scopes": ["org"], "query": "safety"})
elif a == "expired":
    st, d = call("/memory/v1/query", {"envelope": envelope("agent:sched", ["org"], life=-200), "scopes": ["org"], "query": "safety"})
elif a == "summaries":
    st, d = call("/memory/v1/summaries", {"envelope": envelope("user:host", [sys.argv[2]]), "scope": sys.argv[2]})
print(st); print(json.dumps(d))
EOA
ask() { (cd "$W" && env $ENV W=$W PORT=$PORT python3 "$W/ask.py" "$@"); }
check "a peer's query on dept:3: the note as a claim (text, scope, confidence, source, writer, holder server:57), no detail, no payload" "ask query dept:3 forklift | tail -1 | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d[\"claims\"][0]; assert d[\"count\"]==1 and d[\"holder\"]==\"server:57\" and c[\"scope\"]==\"dept:3\" and c[\"confidence\"]==0.9 and c[\"source\"][\"ref\"]==\"hr:training/118\" and c[\"writer\"]==\"user:$ME\" and \"detail\" not in c and \"payload\" not in c and d[\"scopes_read\"]==[\"dept:3\"], d'"
check "the restricted note never leaves: asked at internal it is absent" "ask query dept:3 lifting | tail -1 | grep -q '\"count\": 0'"
check "asked at restricted on dept:3 (the peer's ceiling internal): 403 classification" "ask query dept:3 lifting restricted | head -1 | grep -q 403 && ask query dept:3 lifting restricted | tail -1 | grep -q '\"classification\"'"
check "asked at restricted on org (the peer may, the host's ceiling is internal): 403 classification" "ask query org safety restricted | tail -1 | grep -q '\"classification\"'"
check "a request above the envelope's own classification: 403 classification" "ask query org safety lowenv | tail -1 | grep -q '\"classification\"'"
check "dept:9 is not shared: 403 forbidden" "ask query dept:9 x | tail -1 | grep -q 'does not share dept:9'"
check "the envelope's authority covers org only, dept:3 asked: 403 forbidden" "ask query dept:3 forklift internal org | tail -1 | grep -q 'does not cover dept:3'"
check "the same envelope twice: 409 replay" "ask replay | head -1 | grep -q 409"
check "a tampered envelope: 401 bad_signature" "ask tampered | tail -1 | grep -q bad_signature"
check "signed with another key: 401 bad_signature" "ask otherkey | tail -1 | grep -q bad_signature"
check "a node that is not a peer: 403 forbidden" "ask stranger | tail -1 | grep -q 'not a peer'"
check "no envelope: 401 bad_envelope" "ask noenv | tail -1 | grep -q bad_envelope"
check "an expired envelope: 401" "ask expired | head -1 | grep -q 401"
check "the ledger (an operator reads every row): memory.query rows name the peer, the envelope, the originator, the scopes and the count, never the text" "root memory usage --json | python3 -c 'import json,sys; ev=[e for e in json.load(sys.stdin)[\"events\"] if e[\"event\"]==\"memory.query\"]; d=ev[0][\"detail\"]; assert ev and d[\"peer\"]==\"server:57\" and d[\"envelope\"].startswith(\"env_\") and d[\"originator\"]==\"agent:sched\" and \"query\" not in d and \"forklift\" not in json.dumps(d), d'"

echo "== the federated recall (decision 3): --estate asks the holders the directory publishes, with a self-envelope signed by this host"
check "recall --estate: the local claim and the same claim from holder server:57 (gone-node holds no dept:3, so it is not asked)" "me memory recall forklift --scope dept:3 --estate --json | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r[\"holders\"]==[\"server:57\"], r[\"holders\"]; assert r[\"holders_failed\"]==[], r[\"holders_failed\"]; hs={c[\"holder\"]: c for c in r[\"claims\"]}; assert r[\"count\"]==2 and hs[\"server:57\"][\"local\"] in (True, False) and any(c[\"local\"] for c in r[\"claims\"]) and any(not c[\"local\"] for c in r[\"claims\"]), r'"
check "recall --estate as $ME with scope org at restricted: refused by the holder (classification), the local side answers" "me memory recall safety --scope org --estate --classification restricted --json | python3 -c 'import json,sys; r=json.load(sys.stdin); assert any(f[\"holder\"]==\"server:57\" and f[\"error\"]==\"classification\" for f in r[\"holders_failed\"]), r[\"holders_failed\"]; assert any(c[\"local\"] for c in r[\"claims\"])'"

echo "== one host, two memberships (the boot test's desktop): each membership is published the other identity as a holder"
# the desk's key under user:$ME/office-desk-key; office.yaml names desk 41 with $ME as its owner; the desk's caches say server:57 holds dept:3 and org
env $ENV python3 - "$W" <<'PY'
import sys
from maluos_estate import envelope as E
w = sys.argv[1]
priv, pub = E.genkey("a-desk")
open(f"{w}/desk.key", "w").write(priv); open(f"{w}/desk.pub", "w").write(pub)
PY
me secret add office-desk-key --kind generic --provider estate --stdin < "$W/desk.key" >/dev/null
cat > "$W/etc/office.yaml" <<EOY
url: http://127.0.0.1:1
desk: {id: 41, name: a-desk}
owner: {principal: user:$ME, login: $ME}
overlay: {address: 127.0.0.1}
EOY
mkdir -p "$W/office-run"
python3 - "$W" "$PUB" "$(cat $W/desk.pub)" "$PORT" <<'PY'
import json, sys
w, npub, dpub, port = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
sc = lambda rep=False: [{"scope": "dept:3", "classification_max": "internal", "replicate": rep, "priority": 0}, {"scope": "org", "classification_max": "internal", "replicate": False, "priority": 0}]
json.dump({"ok": True, "self": "desk:41", "version": 1, "fetched_at": "2026-10-31T00:00:00Z", "source": "desk", "written_at": "2026-10-31T00:00:00Z",
           "holders": [{"node": "server:57", "id": 57, "kind": "server", "name": "self-node", "address": "127.0.0.1", "port": port, "api_version": 1, "max_classification": "internal", "scopes": sc()}]},
          open(f"{w}/office-run/memory.json", "w"))
json.dump({"ok": True, "self": "desk:41", "version": 1, "fetched_at": "2026-10-31T00:00:00Z", "source": "desk", "written_at": "2026-10-31T00:00:00Z",
           "peers": [{"node": "server:57", "id": 57, "kind": "server", "name": "self-node", "address": "127.0.0.1", "public_key": npub, "scopes": sc()}]},
          open(f"{w}/office-run/memory-peers.json", "w"))
# the node's caches gain the desk: a holder of dept:3 and org at the overlay address the office allocated to the desk's key (dead on
# this host, as on any desktop that is also a node: the face asks its own identities at its own listener), and a peer with its key
h = json.load(open(f"{w}/estate-run/memory.json")); h["holders"].insert(0, {"node": "desk:41", "id": 41, "kind": "desk", "name": "a-desk", "address": "127.0.0.9", "port": 1, "api_version": 1, "max_classification": "internal", "scopes": sc()})
json.dump(h, open(f"{w}/estate-run/memory.json", "w"))
pe = json.load(open(f"{w}/estate-run/memory-peers.json")); pe["peers"] = [x for x in pe["peers"] if x["node"] != "desk:41"] + [{"node": "desk:41", "id": 41, "kind": "desk", "name": "a-desk", "address": "127.0.0.1", "public_key": dpub, "scopes": sc()}]
json.dump(pe, open(f"{w}/estate-run/memory-peers.json", "w"))
PY
chmod 644 "$W/office-run/"*.json "$W/estate-run/"*.json; root memory reload >/dev/null
check "status: both memberships with readable keys; holders from both caches (ask_self true)" "me memory status | grep -q 'desk:41 as user:$ME; signing key user:$ME/office-desk-key readable' && me memory status | grep -q 'holders:   3 published to this host: a-desk (dept:3, org); self-node (dept:3, org); gone-node (org)'"
check "recall --estate asks both identities at this listener (the desk key at server:57, the node key at desk:41, published at a dead address): two remote claims, no failures" "me memory recall forklift --scope dept:3 --estate --json | python3 -c 'import json,sys; r=json.load(sys.stdin); assert sorted(r[\"holders\"])==[\"desk:41\",\"server:57\"] and r[\"holders_failed\"]==[], (r[\"holders\"], r[\"holders_failed\"]); rem=[c for c in r[\"claims\"] if not c[\"local\"]]; assert sorted(c[\"holder\"] for c in rem)==[\"desk:41\",\"server:57\"], rem'"
sed -i 's/^ask_self: true$/ask_self: false/' "$W/memory.yaml"; root memory reload >/dev/null
check "ask_self false: both identities drop out (desk:41 and server:57 are this host); gone-node stays" "me memory status | grep -q 'holders:   1 published to this host: gone-node (org)' && me memory recall forklift --scope dept:3 --estate --json | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r[\"holders\"]==[] and all(c[\"local\"] for c in r[\"claims\"]), r'"
sed -i 's/^ask_self: false$/ask_self: true/' "$W/memory.yaml"; root memory reload >/dev/null
# back to the node-only picture for replication: the desk's caches and membership go
rm -f "$W/office-run/"*.json "$W/etc/office.yaml"; root memory reload >/dev/null

echo "== replication (decision 9): summaries of a scope a rule lets this host copy, with their origin"
check "summaries on dept:3 (replicate on): none (no summary there)" "ask summaries dept:3 | tail -1 | grep -q '\"count\": 0'"
check "summaries on org (replicate off): 403 forbidden" "ask summaries org | tail -1 | grep -q 'may not replicate org'"
root memory share dept:3 org --max internal >/dev/null; me memory remember 'Dock safety summary: two near misses, both at shift change' --scope dept:3 --kind summary --title 'Dock safety' --as agent:hr >/dev/null
check "summaries on dept:3 now carry the summary with a version" "ask summaries dept:3 | tail -1 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"count\"]==1 and d[\"summaries\"][0][\"kind\"]==\"summary\" and d[\"summaries\"][0][\"version\"], d'"
check "sudo maluctl memory sync: the copy written (from server:57, dept:3), the state kept" "root memory sync | grep -qE 'server:57 +dept:3 +written 1, replaced 0, removed 0' && [ -f $W/mem-state/sync.json ]"
check "a recall finds the copy with its origin beside the original" "me memory recall 'dock safety' --scope dept:3 | grep -q '(copy of server:57#'"
check "sync again: nothing new" "root memory sync | grep -qE 'written 0, replaced 0, removed 0'"
CID=$(me memory recall 'dock safety' --scope dept:3 --json | python3 -c 'import json,sys; print([c for c in json.load(sys.stdin)["claims"] if c.get("origin")][0]["id"])')
check "forget on the copy is refused origin" "me memory forget $CID 2>&1 | grep -q 'origin'"
OID=$(me memory recall 'dock safety' --scope dept:3 --json | python3 -c 'import json,sys; print([c for c in json.load(sys.stdin)["claims"] if not c.get("origin")][0]["id"])')
check "forget the original as its writer (agent:hr, owned): gone; sync then removes the copy" "me memory forget $OID --as agent:hr | grep -q forgotten && root memory sync | grep -qE 'removed 1' && ! me memory recall 'dock safety' --scope dept:3 | grep -q 'copy of'"
check "forget by someone without write on the scope is refused" "me memory forget 1 --as agent:sched 2>&1 | grep -q 'not_owner' && root memory forget 1 --as agent:sched 2>&1 | grep -qE 'scope_write|not_found'"

echo "== unshare and unexpose"
check "unshare --all: the guest reads nothing; a peer's query is refused" "root memory unshare --all | grep -q 'shared: nothing' && ask query dept:3 forklift | tail -1 | grep -q 'does not share dept:3'"
check "unexpose: the listener is gone" "root memory unexpose | grep -q 'not exposed' && sleep 1 && ! curl -fsS --max-time 2 http://127.0.0.1:$PORT/memory/v1/health >/dev/null 2>&1"
check "usage (as the person) lists remember and recall rows; an operator's lists query, summaries and sync too; no text in any" "me memory usage | grep -q 'memory.remember' && me memory usage | grep -q 'memory.recall' && root memory usage | grep -q 'memory.query' && root memory usage | grep -q 'memory.sync' && ! root memory usage --json | grep -q forklift"
check "the face's log holds no memory text" "! grep -q 'forklift\|lifting' $W/face.log"

echo; echo "$n checks, $fail failed"; exit $fail
