#!/bin/bash
# Exercise the inference gateway on this host without a VM or a GPU: a
# throwaway database, the mock Ollama backend, the gateway as the current user
# (socket + TCP), callers = you, root, nobody and postgres (mapped to agent:bot).
# Covers both API families, tiers/aliases/direct models, policy, the scheduler
# (priority, fairness, concurrency cap, expected wait, max-wait and queue-full
# rejections, cancel on disconnect), tokens on TCP, the ledger, the engine
# queue drain, the MCP status table, catalogue reload, keep-warm.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
W=/var/tmp/maluos-gateway-test; DB=maluos_gwtest; T=gt; GROLE=gwtest_gateway; ME=$(id -un)
MOCK=11999; TCP=11998
fail=0; n=0
ok()   { n=$((n+1)); echo "  ok   $*"; }
bad()  { n=$((n+1)); fail=$((fail+1)); echo "  FAIL $*"; }
check(){ if (set +o pipefail; eval "$2"); then ok "$1"; else bad "$1"; fi; }
J()    { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

sudo -n true 2>/dev/null || { echo "needs passwordless sudo"; exit 2; }
for f in "$W/gw.pid" "$W/mock.pid"; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
pkill -f "maluos_gateway.mock_ollama --port $MOCK" 2>/dev/null; pkill -f "maluos_gateway --socket $W/gw.sock" 2>/dev/null; sleep 0.5
sudo rm -rf "$W"; mkdir -p "$W/lib/maluctl.d" "$W/lib/maluos_gateway" "$W/state"; chmod 755 "$W" "$W/lib" "$W/lib/maluctl.d" "$W/lib/maluos_gateway" "$W/state"
cp packages/maluos-firstboot/lib/maluos_provision.py packages/maluos-firstboot/bin/maluctl packages/maluos-vault/lib/maluos_vault_client.py \
   packages/maluos-gateway/components/45-maluos-gateway.py "$W/lib/"
cp packages/maluos-gateway/lib/maluos_gateway/*.py "$W/lib/maluos_gateway/"
cp packages/maluos-gateway/lib/maluctl.d/gateway.py "$W/lib/maluctl.d/"
cp packages/maluos-vault/share/schema.sql "$W/lib/vault-schema.sql"; cp packages/maluos-gateway/share/schema.sql "$W/lib/gateway-schema.sql"
chmod -R a+rX "$W/lib"
cat > "$W/gateway.yaml" <<EOF
socket: $W/gw.sock
tcp: {enabled: true, host: 127.0.0.1, port: $TCP}
database: $DB
tenant: $T
pg_role: $GROLE
identities: {postgres: "agent:bot"}
catalog_reload_s: 2
status_publish_s: 2
engine_queue: {enabled: true, poll_s: 1, class: batch}
ollama: {url: "http://127.0.0.1:11434", keep_alive: 5m, max_concurrent: 1}
EOF
chmod 644 "$W/gateway.yaml"
printf '{"database":"%s","tenant":"%s","provisioned_at":"test","admin_principal":"human:admin","operators":[],"components":{}}\n' $DB $T > "$W/state/done"

echo "== database $DB (tenant $T)"
sudo -n -u postgres psql -Xq -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" -c "DROP ROLE IF EXISTS $GROLE" -c "DROP ROLE IF EXISTS $T" 2>&1 | grep -v NOTICE
sudo -n env PYTHONPATH="$W/lib" python3 - "$DB" "$T" "$GROLE" "$ME" "$W" "$MOCK" <<'PY' || exit 1
import sys, importlib.util, subprocess
import maluos_provision as mp
db, t, grole, me, W, mock = sys.argv[1:7]
mp.ensure_database(db); mp.ensure_tenant(db, t)
for ref, kind in ((f"user:{me}", "human"), ("user:nobody", "human"), ("agent:bot", "agent")):
    mp.ensure_principal(db, t, {"ref": ref, "kind": kind, "display_name": ref, "home_scope": ref})
pre = f"SET ROLE {mp.qi(t)}; SET search_path TO {mp.qi(t)}, maludb_core, public; "
mp.psql(pre + "SELECT maludb_principal_grant_scope('agent:bot', 'org', 'read');", db)
r = subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", pre, "-f", f"{W}/lib/vault-schema.sql"], capture_output=True, text=True)
assert r.returncode == 0, r.stderr
spec = importlib.util.spec_from_file_location("comp", f"{W}/lib/45-maluos-gateway.py"); comp = importlib.util.module_from_spec(spec); spec.loader.exec_module(comp)
if not mp.exists(f"SELECT 1 FROM pg_roles WHERE rolname={mp.ql(grole)}"):
    mp.psql(f"CREATE ROLE {mp.qi(grole)} NOLOGIN")
comp.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, t, role=grole, schema=f"{W}/lib/gateway-schema.sql")
sys.path.insert(0, f"{W}/lib")
from maluos_gateway.config import Config
print("  seeded:", comp.seed_catalog(mp.psql, mp.qi, mp.ql, db, t, Config(f"{W}/gateway.yaml")))
comp.register_tool(mp.psql, mp.exists, mp.qi, mp.ql, db, t, "maludb-mc2dbd")
# the mock backend behind the seeded tiers (position 5), plus a plain alias
mp.psql(pre + f"""INSERT INTO maluos_backend (name, kind, endpoint, capacity, options) VALUES ('mock', 'mock', 'http://127.0.0.1:{mock}', '{{"max_concurrent": 1}}', '{{"keep_alive": "5m", "keep_warm": ["mock-13b"]}}');
INSERT INTO maluos_alias (name, tier, backend, model, position) VALUES ('fast','fast','mock','mock-7b',5), ('strong','strong','mock','mock-13b',5), ('embed','embed','mock','mock-embed',5), ('chat',NULL,'mock','mock-7b',0);
INSERT INTO maluos_class (name, priority, weight, max_queue) VALUES ('tiny', 5, 1, 1);""", db)
# the engine side: a provider and an alias named like ours
# model providers/aliases are tenant-scoped by owner_schema (= current_schema); registering needs the engine's admin role
mp.psql(f"SET search_path TO {mp.qi(t)}, maludb_core, public; SELECT maludb_core.register_model_provider('mockprov', 'local_http', 'ollama', NULL, 'internal'); SELECT maludb_core.register_model_alias('chat', 'mockprov', 'mock-7b');", db)
print("  schema, grants, catalogue ready")
PY

echo "== mock ollama + gateway"
PYTHONPATH=$W/lib python3 -m maluos_gateway.mock_ollama --port $MOCK --token-delay 0.005 >"$W/mock.log" 2>&1 & echo $! > "$W/mock.pid"; disown
PYTHONPATH=$W/lib MALUOS_GATEWAY_CONFIG=$W/gateway.yaml python3 -m maluos_gateway --socket "$W/gw.sock" >"$W/gw.log" 2>&1 & echo $! > "$W/gw.pid"; disown
trap 'kill $(cat $W/gw.pid) $(cat $W/mock.pid) 2>/dev/null' EXIT
for i in $(seq 1 40); do [ -S "$W/gw.sock" ] && curl -sf --unix-socket "$W/gw.sock" http://g/v1/maluos/health >/dev/null && break; sleep 0.25; done
sleep 1.5   # first health probe of the backends
ENV="PYTHONPATH=$W/lib MALUCTL_PLUGIN_DIR=$W/lib/maluctl.d MALUOS_GATEWAY_SOCKET=$W/gw.sock MALUOS_STATE_DIR=$W/state"
C()      { curl -sS --max-time 60 --unix-socket "$W/gw.sock" "$@"; }
Cr()     { sudo -n curl -sS --max-time 60 --unix-socket "$W/gw.sock" "$@"; }
Cn()     { sudo -n -u nobody curl -sS --max-time 60 --unix-socket "$W/gw.sock" "$@"; }
Cp()     { sudo -n -u postgres curl -sS --max-time 60 --unix-socket "$W/gw.sock" "$@"; }
mctl()   { env $ENV python3 "$W/lib/maluctl" gateway "$@"; }
rmctl()  { sudo -n env $ENV python3 "$W/lib/maluctl" gateway "$@"; }
mock()   { curl -sS http://127.0.0.1:$MOCK/mock/$1 ${2:+-X POST}; }
SQL()    { sudo -n -u postgres psql -qAtd $DB -c "set search_path to $T, maludb_core, public; $1"; }
chat()   { C -H 'Content-Type: application/json' "$@"; }
U=http://g

check "health" "C $U/v1/maluos/health | J 'd[\"ok\"]' | grep -q True"
check "whoami as $ME -> user:$ME via socket" "C $U/v1/maluos/whoami | grep -q '\"principal\": \"user:$ME\"'"
check "identity map postgres -> agent:bot" "Cp $U/v1/maluos/whoami | grep -q '\"principal\": \"agent:bot\"'"
check "root is operator" "Cr $U/v1/maluos/whoami | grep -q '\"operator\": true'"
check "mock backend healthy, ollama-local down" "C $U/v1/maluos/status | J '[ (b[\"name\"], b[\"healthy\"]) for b in d[\"backends\"]]' | grep -q \"('mock', True)\" && C $U/v1/maluos/status | J '[ (b[\"name\"], b[\"healthy\"]) for b in d[\"backends\"]]' | grep -q \"('ollama-local', False)\""

echo "== OpenAI API"
check "chat via tier fast -> mock-7b (unhealthy rung skipped)" "chat $U/v1/chat/completions -D $W/h.txt -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"hello there\"}]}' | J 'd[\"choices\"][0][\"message\"][\"content\"]' | grep -q 'mock reply to: hello there' && grep -q 'X-MaluOS-Route: mock/mock-7b (tier fast)' $W/h.txt"
check "usage tokens present" "chat $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"count me\"}]}' | J 'd[\"usage\"][\"completion_tokens\"] > 0 and d[\"usage\"][\"prompt_tokens\"] > 0' | grep -q True"
check "alias chat -> mock-7b" "chat $U/v1/chat/completions -D $W/h.txt -d '{\"model\":\"chat\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' >/dev/null && grep -q 'mock/mock-7b (alias)' $W/h.txt"
check "direct model name mock-13b" "chat $U/v1/chat/completions -D $W/h.txt -d '{\"model\":\"mock-13b\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' >/dev/null && grep -q 'mock/mock-13b (direct)' $W/h.txt"
check "unknown model -> 404" "chat -o /dev/null -w '%{http_code}' $U/v1/chat/completions -d '{\"model\":\"nope\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' | grep -q 404"
check "streaming SSE with usage and [DONE]" "chat -N $U/v1/chat/completions -d '{\"model\":\"fast\",\"stream\":true,\"stream_options\":{\"include_usage\":true},\"messages\":[{\"role\":\"user\",\"content\":\"stream me\"}]}' > $W/sse.txt; grep -q 'chat.completion.chunk' $W/sse.txt && grep -q '\"finish_reason\": \"stop\"' $W/sse.txt && grep -q '\"completion_tokens\"' $W/sse.txt && tail -c 20 $W/sse.txt | grep -q DONE"
check "streamed content reassembles" "grep '^data: {' $W/sse.txt | sed 's/^data: //' | python3 -c 'import json,sys; print(\"\".join((json.loads(l)[\"choices\"] or [{\"delta\":{}}])[0][\"delta\"].get(\"content\",\"\") for l in sys.stdin if l.strip()))' | grep -q 'mock reply to: stream me'"
check "tool calls translate" "chat $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"please call tool now\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"lookup\",\"parameters\":{}}}]}' | J 'd[\"choices\"][0][\"finish_reason\"] + \" \" + d[\"choices\"][0][\"message\"][\"tool_calls\"][0][\"function\"][\"name\"]' | grep -q 'tool_calls lookup'"
check "response_format json_object" "chat $U/v1/chat/completions -d '{\"model\":\"fast\",\"response_format\":{\"type\":\"json_object\"},\"messages\":[{\"role\":\"user\",\"content\":\"j\"}]}' | J 'json.loads(d[\"choices\"][0][\"message\"][\"content\"])[\"reply\"]' | grep -q 'mock reply'"
check "embeddings via tier embed" "chat $U/v1/embeddings -d '{\"model\":\"embed\",\"input\":[\"a b\",\"c\"]}' | J 'len(d[\"data\"]) == 2 and len(d[\"data\"][0][\"embedding\"]) == 8 and d[\"usage\"][\"prompt_tokens\"] == 3' | grep -q True"
check "/v1/models lists tiers, aliases, models" "C $U/v1/models | J 'sorted(m[\"id\"] for m in d[\"data\"])' | grep -q \"'chat'.*'embed'.*'fast'.*'mock-13b'.*'mock-7b'.*'mock-embed'.*'standard'.*'strong'\""
check "/v1/models/fast is a tier with a ladder" "C $U/v1/models/fast | J 'd[\"maluos\"][\"kind\"] + \" \" + \",\".join(d[\"maluos\"][\"ladder\"])' | grep -q 'tier ollama-local/llama3.2:3b,ollama-local/qwen2.5:3b,mock/mock-7b'"

echo "== Ollama API"
check "/api/chat streams NDJSON to done with counts" "chat -N $U/api/chat -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"nd\"}]}' | tail -1 | J 'd[\"done\"] and d[\"eval_count\"] > 0 and d[\"model\"] == \"mock-7b\"' | grep -q True"
check "/api/generate non-stream" "chat $U/api/generate -d '{\"model\":\"chat\",\"prompt\":\"gen\",\"stream\":false}' | J 'd[\"response\"]' | grep -q 'mock reply to: gen'"
check "/api/embed" "chat $U/api/embed -d '{\"model\":\"embed\",\"input\":\"e\"}' | J 'len(d[\"embeddings\"][0])' | grep -q 8"
check "/api/embeddings legacy" "chat $U/api/embeddings -d '{\"model\":\"embed\",\"prompt\":\"e\"}' | J 'len(d[\"embedding\"])' | grep -q 8"
check "/api/tags includes tiers and mock models" "C $U/api/tags | J 'sorted(m[\"name\"] for m in d[\"models\"])' | grep -q \"'fast'\" && C $U/api/tags | grep -q 'mock-7b:latest'"
check "/api/show through the alias" "chat $U/api/show -d '{\"model\":\"chat\"}' | J 'd[\"maluos\"][\"model\"]' | grep -q mock-7b"
check "/api/version answers" "C $U/api/version | grep -q maluos"
check "/api/ps lists loaded models" "C $U/api/ps | grep -q 'mock-7b'"
check "/api/pull refused for non-operators" "chat -o /dev/null -w '%{http_code}' $U/api/pull -d '{\"model\":\"new-model\"}' | grep -q 403"
check "/api/pull as operator adds a model" "Cr -H 'Content-Type: application/json' $U/api/pull -d '{\"model\":\"new-model\",\"backend\":\"mock\"}' | grep -q success && sleep 0.5 && C $U/v1/models | grep -q new-model"

echo "== scheduler"
mock reset POST >/dev/null
for t in b1 b2 b3; do (chat -H 'X-MaluOS-Class: batch' $U/v1/chat/completions -d "{\"model\":\"fast\",\"options\":{\"mock_delay_s\":1.2,\"tag\":\"$t\"},\"messages\":[{\"role\":\"user\",\"content\":\"$t\"}]}" >/dev/null) & sleep 0.15; done
sleep 0.3; chat -H 'X-MaluOS-Class: interactive' $U/v1/chat/completions -d '{"model":"fast","options":{"mock_delay_s":0.3,"tag":"i1"},"messages":[{"role":"user","content":"i1"}]}' >/dev/null; wait
check "concurrency cap 1 respected" "mock stats | J 'd[\"max_running\"]' | grep -q '^1$'"
check "interactive overtakes queued batch work" "mock stats | J '\",\".join(o[\"tag\"] for o in d[\"order\"])' | grep -q '^b1,i1,b2,b3$'"
mock reset POST >/dev/null
for t in m1 m2 m3 m4; do (chat -H 'X-MaluOS-Class: agent' $U/v1/chat/completions -d "{\"model\":\"fast\",\"options\":{\"mock_delay_s\":0.8,\"tag\":\"$t\"},\"messages\":[{\"role\":\"user\",\"content\":\"$t\"}]}" >/dev/null) & sleep 0.1; done
sleep 0.2; (Cn -H 'Content-Type: application/json' -H 'X-MaluOS-Class: agent' $U/v1/chat/completions -d '{"model":"fast","options":{"mock_delay_s":0.3,"tag":"n1"},"messages":[{"role":"user","content":"n1"}]}' >/dev/null) & wait
check "fairness: the second principal is served next" "mock stats | J '\",\".join(o[\"tag\"] for o in d[\"order\"])' | grep -q '^m1,n1,m2'"
(chat -H 'X-MaluOS-Class: batch' $U/v1/chat/completions -d '{"model":"fast","options":{"mock_delay_s":3},"messages":[{"role":"user","content":"long"}]}' >/dev/null) & sleep 0.4
(chat -H 'X-MaluOS-Class: batch' $U/v1/chat/completions -d '{"model":"fast","options":{"mock_delay_s":1},"messages":[{"role":"user","content":"q2"}]}' >/dev/null) & sleep 0.3
check "expected wait > 0 while busy" "C $U/v1/maluos/status | J 'd[\"expected_wait_s\"][\"batch\"] > 0' | grep -q True"
check "queue shows a queued and a running job" "mctl queue | grep -q queued && mctl queue | grep -q running"
check "max-wait hint rejected with expected wait (503 wait_exceeds)" "chat -H 'X-MaluOS-Max-Wait: 0.01' -H 'X-MaluOS-Class: batch' $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' | J 'd[\"error\"][\"code\"] + \" \" + str(d[\"error\"][\"expected_wait_s\"] > 0)' | grep -q 'wait_exceeds True'"
wait
(chat -H 'X-MaluOS-Class: tiny' $U/v1/chat/completions -d '{"model":"fast","options":{"mock_delay_s":2},"messages":[{"role":"user","content":"t1"}]}' >/dev/null) & sleep 0.4
(chat -H 'X-MaluOS-Class: tiny' $U/v1/chat/completions -d '{"model":"fast","options":{"mock_delay_s":0.2},"messages":[{"role":"user","content":"t2"}]}' >/dev/null) & sleep 0.3
check "queue_full for a class at its limit" "chat -H 'X-MaluOS-Class: tiny' $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"t3\"}]}' | J 'd[\"error\"][\"code\"]' | grep -q queue_full"
wait
mock reset POST >/dev/null
curl -sN --unix-socket "$W/gw.sock" -H 'Content-Type: application/json' $U/v1/chat/completions -d '{"model":"fast","stream":true,"options":{"mock_delay_s":6},"messages":[{"role":"user","content":"cancel me"}]}' >/dev/null 2>&1 & CPID=$!; sleep 0.8; kill $CPID; sleep 1.2
check "client disconnect aborts the backend call" "mock stats | J 'd[\"aborted\"] >= 1 and d[\"running\"] == 0' | grep -q True"
check "cancelled call in the ledger" "SQL \"select count(*) from maluos_ledger where event='model.call' and error_class='cancelled'\" | grep -qE '^[1-9]'"
check "gateway free again after the cancel" "chat $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"after\"}]}' | grep -q 'mock reply'"

echo "== policy, tokens, classes"
check "policy: nobody limited to tier fast" "rmctl policy set --principal user:nobody --tiers fast >/dev/null && sleep 0.3 && Cn -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"strong\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' | grep -q 403"
check "policy: allowed tier still works" "Cn -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}]}' | grep -q 'mock reply'"
check "policy: default class for agents is agent" "Cp -H 'Content-Type: application/json' $U/v1/chat/completions -D - -o /dev/null -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"a\"}]}' | grep -q 'X-MaluOS-Class: agent'"
check "policy rm" "rmctl policy rm --principal user:nobody | grep -q removed"
check "TCP without token -> 401" "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$TCP/v1/models | grep -q 401"
TOK=$(rmctl token issue --principal user:nobody --name test --expires 1d); check "token issued" "[ \"\${TOK#mg_}\" != \"$TOK\" ]"
check "TCP with token -> user:nobody" "curl -s -H \"Authorization: Bearer $TOK\" http://127.0.0.1:$TCP/v1/maluos/whoami | grep -q '\"principal\": \"user:nobody\"' && curl -s -H \"Authorization: Bearer $TOK\" http://127.0.0.1:$TCP/v1/maluos/whoami | grep -q '\"via\": \"token\"'"
check "TCP chat with token logged to that principal" "curl -s -H \"Authorization: Bearer $TOK\" -H 'Content-Type: application/json' http://127.0.0.1:$TCP/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"tcp\"}]}' | grep -q 'mock reply' && SQL \"select count(*) from maluos_ledger where event='model.call' and principal_ref='user:nobody' and process_ref like 'tcp:%'\" | grep -qE '^[1-9]'"
check "token list and revoke" "rmctl token list | grep -q 'user:nobody  test' && rmctl token revoke 1 | grep -q revoked && sleep 31 && curl -s -o /dev/null -w '%{http_code}' -H \"Authorization: Bearer $TOK\" http://127.0.0.1:$TCP/v1/models | grep -q 401"

echo "== catalogue, status, CLI"
check "alias set reloads the catalogue" "rmctl alias set newalias --backend mock --model mock-13b >/dev/null && C $U/v1/models | grep -q newalias"
check "class set" "rmctl class set agent --max-queue 150 | grep -q max_queue && SQL \"select max_queue from maluos_class where name='agent'\" | grep -q 150"
check "maluctl gateway status" "mctl status | grep -q 'backend:     mock' && mctl status | grep -q 'scheduler:   mock'"
check "maluctl gateway routes" "mctl routes | grep -q 'mock/mock-7b'"
check "maluctl gateway chat" "mctl chat 'cli hello' --model fast 2>/dev/null | grep -q 'mock reply to: cli hello'"
check "maluctl gateway chat --stream" "mctl chat 'cli stream' --model fast --stream 2>/dev/null | grep -q 'mock reply to: cli stream'"
check "maluctl gateway catalog" "rmctl catalog | grep -q 'fast' && rmctl catalog | grep -q 'interactive  priority 0'"
check "status published for the MCP tool" "SQL \"select (now() - updated_at) < interval '15 seconds' and status ? 'expected_wait_s' from maluos_gateway_status\" | grep -q t"
check "MCP tool registered" "SQL \"select 1 from maludb_core.\\\"malu\\\$mc2db_tool\\\" where tool_name='maluos.model_status'\" | grep -q 1"
check "resident model tracked" "C $U/v1/maluos/status | J 'd[\"schedulers\"][\"mock\"][\"resident\"]' | grep -q mock"
check "service time stats learned" "C $U/v1/maluos/status | J 'd[\"schedulers\"][\"mock\"][\"models\"][\"mock-7b\"][\"n\"] > 3' | grep -q True"

echo "== engine queue"
RID=$(SQL "select submit_request('chat', 'Hello engine', NULL, NULL, '{\"temperature\": 0.1}', 20000)")
for i in $(seq 1 20); do st=$(SQL "select request_status($RID)"); [ "$st" = succeeded ] && break; sleep 0.5; done
check "engine request drained to succeeded" "[ \"$st\" = succeeded ]"
check "engine response text and tokens" "SQL \"select output_text || ' ' || prompt_tokens || ' ' || adapter_name from get_response($RID)\" | grep -q 'mock reply to: Hello engine [1-9][0-9]* maluos-gateway'"
check "engine call in the ledger as batch" "SQL \"select class || ' ' || principal_ref || ' ' || task_ref from maluos_ledger where task_ref='model_request:$RID'\" | grep -q 'batch engine:queue model_request:$RID'"
RID2=$(SQL "select submit_request('chat', 'cancel me', NULL, NULL, '{}', 20000)"); SQL "select cancel_request($RID2)" >/dev/null; sleep 2
check "cancelled engine request is not run" "SQL \"select status from maludb_core.\\\"malu\\\$model_request\\\" where request_id=$RID2\" | grep -q cancelled"

echo "== ledger"
check "model.call rows carry tokens, wait, process" "SQL \"select count(*) from maluos_ledger where event='model.call' and status='ok' and tokens_out > 0 and queue_wait_ms is not null and process_ref like 'curl@%' and linux_user='$ME'\" | grep -qE '^[1-9]'"
check "denials recorded (policy, 404, max-wait, queue_full)" "SQL \"select string_agg(distinct reason, ',') from maluos_ledger where status in ('denied','error') and event='model.call'\" | grep -q 'policy_tier' && SQL \"select string_agg(distinct reason, ',') from maluos_ledger where status in ('denied','error')\" | grep -q 'queue_full'"
check "gateway role cannot read memory tables" "! sudo -n -u postgres psql -Atd $DB -c \"set role $GROLE; select count(*) from $T.maludb_episode\" 2>/dev/null"
check "gateway role cannot alter the ledger" "! sudo -n -u postgres psql -Atd $DB -c \"set role $GROLE; delete from $T.maluos_ledger\" 2>/dev/null"

echo "== keep-warm"
for i in $(seq 1 25); do w=$(mock stats | J 'd["warm"]'); [ "$w" -ge 1 ] && break; sleep 1; done
check "keep_warm loaded mock-13b" "[ \"$w\" -ge 1 ]"
check "no internal errors in the gateway log" "! grep -q 'internal error' $W/gw.log"

echo
[ $fail = 0 ] && echo "PASS: $n checks" || { echo "FAIL: $fail of $n checks (logs: $W/gw.log, $W/mock.log)"; exit 1; }
