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
for f in "$W/gw.pid" "$W/mock.pid" "$W/vault.pid"; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
pkill -f "maluos_gateway.mock_ollama --port $MOCK" 2>/dev/null; pkill -f "maluos_gateway --socket $W/gw.sock" 2>/dev/null; sleep 0.5
sudo rm -rf "$W"; mkdir -p "$W/lib/maluctl.d" "$W/lib/maluos_gateway" "$W/state"; chmod 755 "$W" "$W/lib" "$W/lib/maluctl.d" "$W/lib/maluos_gateway" "$W/state"
cp packages/maluos-firstboot/lib/maluos_provision.py packages/maluos-firstboot/bin/maluctl packages/maluos-vault/lib/maluos_vault_client.py \
   packages/maluos-gateway/components/45-maluos-gateway.py "$W/lib/"
cp packages/maluos-gateway/lib/maluos_gateway/*.py "$W/lib/maluos_gateway/"
cp packages/maluos-gateway/lib/maluctl.d/gateway.py "$W/lib/maluctl.d/"
cp packages/maluos-vault/share/schema.sql "$W/lib/vault-schema.sql"; cp packages/maluos-gateway/share/schema.sql "$W/lib/gateway-schema.sql"
cp packages/maluos-vault/lib/maluos_vault.py packages/maluos-vault/components/40-maluos-vault.py "$W/lib/"; cp packages/maluos-vault/lib/maluctl.d/secret.py "$W/lib/maluctl.d/"
mkdir -p "$W/vcred" "$W/vstate"; head -c 32 /dev/urandom > "$W/vcred/maluos-vault.key"
cat > "$W/vault.yaml" <<EOF
socket: $W/vault.sock
database: $DB
tenant: $T
pg_role: gwtest_vault
state_dir: $W/vstate
brokers: [$ME]
identities: {postgres: "agent:bot"}
EOF
chmod 644 "$W/vault.yaml"
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
vault_socket: $W/vault.sock
state_dir: $W/gwstate
alerts: {check_s: 2, backend_down_s: 3, backend_down_repeat_s: 60, hooks_dir: $W/hooks, usage_anomaly: {enabled: true, check_s: 2, min_calls: 5, factor: 2}}
health: {cooldown_s: 2, probe_s: 3}
EOF
mkdir -p "$W/gwstate" "$W/hooks"; cat > "$W/hooks/10-record" <<'EOF'
#!/bin/sh
cat >> /var/tmp/maluos-gateway-test/hooks.log; echo >> /var/tmp/maluos-gateway-test/hooks.log
EOF
chmod +x "$W/hooks/10-record"; : > "$W/hooks.log"; chmod 666 "$W/hooks.log"
chmod 644 "$W/gateway.yaml"
printf '{"database":"%s","tenant":"%s","provisioned_at":"test","admin_principal":"human:admin","operators":[],"components":{}}\n' $DB $T > "$W/state/done"

echo "== database $DB (tenant $T)"
sudo -n -u postgres psql -Xq -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" -c "DROP ROLE IF EXISTS $GROLE" -c "DROP ROLE IF EXISTS gwtest_vault" -c "DROP ROLE IF EXISTS $T" 2>&1 | grep -v NOTICE
sudo -n env PYTHONPATH="$W/lib" python3 - "$DB" "$T" "$GROLE" "$ME" "$W" "$MOCK" <<'PY' || exit 1
import sys, importlib.util, subprocess
import maluos_provision as mp
db, t, grole, me, W, mock = sys.argv[1:7]
mp.ensure_database(db); mp.ensure_tenant(db, t)
for ref, kind in ((f"user:{me}", "human"), ("user:nobody", "human"), ("agent:bot", "agent"), ("service:engine", "service")):
    mp.ensure_principal(db, t, {"ref": ref, "kind": kind, "display_name": ref, "home_scope": ref})
pre = f"SET ROLE {mp.qi(t)}; SET search_path TO {mp.qi(t)}, maludb_core, public; "
mp.psql(pre + "SELECT maludb_principal_grant_scope('agent:bot', 'org', 'read');", db)
r = subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", pre, "-f", f"{W}/lib/vault-schema.sql"], capture_output=True, text=True)
assert r.returncode == 0, r.stderr
vspec = importlib.util.spec_from_file_location("vcomp", f"{W}/lib/40-maluos-vault.py"); vcomp = importlib.util.module_from_spec(vspec); vspec.loader.exec_module(vcomp)
if not mp.exists("SELECT 1 FROM pg_roles WHERE rolname='gwtest_vault'"):
    mp.psql("CREATE ROLE gwtest_vault NOLOGIN")
vcomp.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, t, role="gwtest_vault", schema=f"{W}/lib/vault-schema.sql")
spec = importlib.util.spec_from_file_location("comp", f"{W}/lib/45-maluos-gateway.py"); comp = importlib.util.module_from_spec(spec); spec.loader.exec_module(comp)
if not mp.exists(f"SELECT 1 FROM pg_roles WHERE rolname={mp.ql(grole)}"):
    mp.psql(f"CREATE ROLE {mp.qi(grole)} NOLOGIN")
comp.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, t, role=grole, schema=f"{W}/lib/gateway-schema.sql")
sys.path.insert(0, f"{W}/lib")
from maluos_gateway.config import Config
print("  seeded:", comp.seed_catalog(mp.psql, mp.qi, mp.ql, db, t, Config(f"{W}/gateway.yaml")))
comp.register_tool(mp.psql, mp.exists, mp.qi, mp.ql, db, t, "maludb-mc2dbd")
# the mock backend behind the seeded tiers (position 5), plus a plain alias; mock cloud backends behind it
mp.psql(pre + f"""INSERT INTO maluos_backend (name, kind, endpoint, capacity, options) VALUES ('mock', 'mock', 'http://127.0.0.1:{mock}', '{{"max_concurrent": 1}}', '{{"keep_alive": "5m", "keep_warm": ["mock-13b"]}}');
INSERT INTO maluos_backend (name, kind, endpoint, secret_ref, capacity, options) VALUES
  ('anthropic-mock', 'anthropic', 'http://127.0.0.1:{mock}', 'anthropic', '{{"max_concurrent": 4}}', '{{"models": ["claude-mock", "claude-fail"]}}'),
  ('openai-mock', 'openai', 'http://127.0.0.1:{mock}', 'openai', '{{"max_concurrent": 4}}', '{{"models": ["gpt-mock", "embed-mock"]}}'),
  ('ollama-cloud-mock', 'ollama_cloud', 'http://127.0.0.1:{mock}', 'ollama', '{{"max_concurrent": 4}}', '{{"models": ["mock-7b"]}}');
INSERT INTO maluos_alias (name, tier, backend, model, position) VALUES ('fast','fast','mock','mock-7b',5), ('strong','strong','mock','mock-13b',5), ('embed','embed','mock','mock-embed',5), ('chat',NULL,'mock','mock-7b',0),
  ('strong','strong','anthropic-mock','claude-mock',10), ('fast','fast','openai-mock','gpt-mock',10);
INSERT INTO maluos_tier (name, description) VALUES ('cloud', 'cloud only'), ('oai', 'openai mock'), ('oembed', 'openai embeddings'), ('ocloud', 'ollama cloud');
INSERT INTO maluos_alias (name, tier, backend, model, position) VALUES ('cloud','cloud','anthropic-mock','claude-mock',0), ('oai','oai','openai-mock','gpt-mock',0),
  ('oembed','oembed','openai-mock','embed-mock',0), ('ocloud','ocloud','ollama-cloud-mock','mock-7b',0),
  ('flaky',NULL,'mock','mock-fail',0), ('flaky',NULL,'anthropic-mock','claude-mock',1);
INSERT INTO maluos_price (backend, model, input_per_mtok, output_per_mtok, cached_per_mtok) VALUES ('anthropic-mock', 'claude-mock', 3, 15, 0.3), ('openai-mock', '*', 1, 2, 0.1);
INSERT INTO maluos_class (name, priority, weight, max_queue) VALUES ('tiny', 5, 1, 1);""", db)
# the engine side: a provider and an alias named like ours
# model providers/aliases are tenant-scoped by owner_schema (= current_schema); registering needs the engine's admin role
mp.psql(f"SET search_path TO {mp.qi(t)}, maludb_core, public; SELECT maludb_core.register_model_provider('mockprov', 'local_http', 'ollama', NULL, 'internal'); SELECT maludb_core.register_model_alias('chat', 'mockprov', 'mock-7b');", db)
print("  schema, grants, catalogue ready")
PY

echo "== mock ollama + gateway"
PYTHONPATH=$W/lib python3 -m maluos_gateway.mock_ollama --port $MOCK --token-delay 0.005 --models mock-7b,mock-13b,mock-embed,mock-fail >"$W/mock.log" 2>&1 & echo $! > "$W/mock.pid"; disown
CREDENTIALS_DIRECTORY=$W/vcred MALUOS_VAULT_CONFIG=$W/vault.yaml PYTHONPATH=$W/lib python3 "$W/lib/maluos_vault.py" --socket "$W/vault.sock" >"$W/vault.log" 2>&1 & echo $! > "$W/vault.pid"; disown
for i in $(seq 1 20); do [ -S "$W/vault.sock" ] && break; sleep 0.25; done
PYTHONPATH=$W/lib MALUOS_GATEWAY_CONFIG=$W/gateway.yaml python3 -m maluos_gateway --socket "$W/gw.sock" >"$W/gw.log" 2>&1 & echo $! > "$W/gw.pid"; disown
trap 'kill $(cat $W/gw.pid) $(cat $W/mock.pid) $(cat $W/vault.pid) 2>/dev/null' EXIT
for i in $(seq 1 40); do [ -S "$W/gw.sock" ] && curl -sf --unix-socket "$W/gw.sock" http://g/v1/maluos/health >/dev/null && break; sleep 0.25; done
sleep 1.5   # first health probe of the backends
ENV="PYTHONPATH=$W/lib MALUCTL_PLUGIN_DIR=$W/lib/maluctl.d MALUOS_GATEWAY_SOCKET=$W/gw.sock MALUOS_VAULT_SOCKET=$W/vault.sock MALUOS_STATE_DIR=$W/state"
vme()  { env $ENV python3 "$W/lib/maluctl" secret "$@"; }
vroot(){ sudo -n env $ENV python3 "$W/lib/maluctl" secret "$@"; }
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
check "engine call in the ledger as batch, principal service:engine" "SQL \"select class || ' ' || principal_ref || ' ' || task_ref from maluos_ledger where task_ref='model_request:$RID'\" | grep -q 'batch service:engine model_request:$RID'"
RID2=$(SQL "select submit_request('chat', 'cancel me', NULL, NULL, '{\"options\": {\"mock_delay_s\": 6}}', 20000)"); sleep 2; SQL "select cancel_request($RID2)" >/dev/null; sleep 3
check "engine request cancelled while running" "SQL \"select status || ' ' || coalesce((select user_safe_error from maludb_core.\\\"malu\\\$model_response\\\" r where r.request_id=$RID2), '-') from maludb_core.\\\"malu\\\$model_request\\\" where request_id=$RID2\" | grep -q 'cancelled cancelled while running'"

echo "== cloud: credentials, sensitivity, ladders, fallback, budgets"
echo sk-me-anthropic | vme add anthropic --provider anthropic --stdin >/dev/null
vroot compartment create system --scope org >/dev/null 2>&1
echo sk-system-anthropic | vroot add system/anthropic --provider anthropic --stdin >/dev/null; vroot grant system/anthropic --to user:nobody --level use >/dev/null
echo sk-system-openai | vroot add system/openai --provider openai --stdin >/dev/null; vroot grant system/openai --to user:$ME --level use >/dev/null
echo sk-system-ollama | vroot add system/ollama --provider ollama_cloud --stdin >/dev/null; vroot grant system/ollama --to user:$ME --level use >/dev/null
mock reset POST >/dev/null
check "cloud tier via Anthropic with my own key" "chat $U/v1/chat/completions -D - -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"hi cloud\"}]}' | grep -q 'mock claude reply to: hi cloud' && mock stats | J 'd[\"keys\"][-1][\"key\"]' | grep -q '^sk-me-anthropic$'"
check "route header names the cloud rung" "chat $U/v1/chat/completions -D - -o /dev/null -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' | grep -q 'X-MaluOS-Route: anthropic-mock/claude-mock (tier cloud)'"
check "nobody's cloud call uses the granted system key" "Cn -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"n\"}]}' | grep -q 'mock claude' && mock stats | J 'd[\"keys\"][-1][\"key\"]' | grep -q '^sk-system-anthropic$'"
check "vault ledger: secret.use on behalf of user:nobody by the gateway broker" "SQL \"select count(*) from maluos_ledger where event='secret.use' and principal_ref='user:nobody' and broker_ref='user:$ME' and secret_name='anthropic' and status='ok'\" | grep -qE '^[1-9]'"
check "agent without an egress policy cannot send internal data to the cloud (403)" "Cp -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"a\"}]}' | J 'd[\"error\"][\"code\"] + \" \" + d[\"error\"][\"route\"][0][\"skipped\"]' | grep -q 'policy sensitivity:internal>public'"
check "agent with egress internal but no key: no_credential" "rmctl policy set --principal agent:bot --egress internal >/dev/null && Cp -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"a\"}]}' | J 'd[\"error\"][\"route\"][0][\"skipped\"]' | grep -q '^no_credential$'"
check "sensitivity hint restricted never leaves the host" "chat -H 'X-MaluOS-Sensitivity: restricted' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"s\"}]}' | J 'd[\"error\"][\"route\"][0][\"skipped\"]' | grep -q 'sensitivity:restricted>internal'"
check "strong: local rung first" "chat -D - -o /dev/null $U/v1/chat/completions -d '{\"model\":\"strong\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' | grep -q 'X-MaluOS-Route: mock/mock-13b'"
check "prefer cloud hint takes the cloud rung" "chat -H 'X-MaluOS-Prefer: cloud' -D - -o /dev/null $U/v1/chat/completions -d '{\"model\":\"strong\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' | grep -q 'X-MaluOS-Route: anthropic-mock/claude-mock'"
check "local-only hint refuses the cloud-only tier" "chat -H 'X-MaluOS-Local-Only: 1' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' | J 'd[\"error\"][\"route\"][0][\"skipped\"]' | grep -q '^local_only$'"
rmctl class set interactive --fallback-wait 0 >/dev/null
# teach the scheduler that mock-13b takes ~3 s, then keep it busy
for i in 1 2; do chat -H 'X-MaluOS-Class: batch' $U/v1/chat/completions -d '{"model":"mock-13b","options":{"mock_delay_s":3},"messages":[{"role":"user","content":"train"}]}' >/dev/null; done
(chat -H 'X-MaluOS-Class: batch' $U/v1/chat/completions -d '{"model":"mock-13b","options":{"mock_delay_s":3},"messages":[{"role":"user","content":"busy"}]}' >/dev/null) & sleep 0.5
check "fallback to the cloud when the local wait exceeds the class threshold" "chat -H 'X-MaluOS-Class: interactive' -D - -o /dev/null $U/v1/chat/completions -d '{\"model\":\"strong\",\"messages\":[{\"role\":\"user\",\"content\":\"now\"}]}' | grep -q 'X-MaluOS-Route: anthropic-mock/claude-mock'"
check "ledger route records the skipped local rung with the wait" "SQL \"select route::text from maluos_ledger where event='model.call' and tier='strong' and backend='anthropic-mock' order by ledger_id desc limit 1\" | grep -q 'wait_exceeds_fallback'"
wait; rmctl class set interactive --fallback-wait none >/dev/null
check "local failure retried once, then the next rung (attempts 3)" "chat -D - $U/v1/chat/completions -d '{\"model\":\"flaky\",\"messages\":[{\"role\":\"user\",\"content\":\"f\"}]}' > $W/flaky.txt; grep -q 'X-MaluOS-Attempts: 3' $W/flaky.txt && grep -q 'mock claude reply to: f' $W/flaky.txt && SQL \"select attempts || ' ' || backend from maluos_ledger where requested_model='flaky' and status='ok' order by ledger_id desc limit 1\" | grep -q '3 anthropic-mock'"
check "Anthropic streaming through the OpenAI SSE" "chat -N $U/v1/chat/completions -d '{\"model\":\"cloud\",\"stream\":true,\"stream_options\":{\"include_usage\":true},\"messages\":[{\"role\":\"user\",\"content\":\"sse\"}]}' > $W/csse.txt; grep '^data: {' $W/csse.txt | sed 's/^data: //' | python3 -c 'import json,sys; print(\"\".join((json.loads(l)[\"choices\"] or [{\"delta\":{}}])[0][\"delta\"].get(\"content\",\"\") for l in sys.stdin if l.strip()))' | grep -q 'mock claude reply to: sse' && grep -q '\"cached_tokens\": 2' $W/csse.txt"
check "Anthropic tool use translates to OpenAI tool_calls" "chat $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"please call tool\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"lookup\",\"parameters\":{}}}]}' | J 'd[\"choices\"][0][\"finish_reason\"] + \" \" + d[\"choices\"][0][\"message\"][\"tool_calls\"][0][\"function\"][\"name\"] + \" \" + d[\"choices\"][0][\"message\"][\"tool_calls\"][0][\"id\"]' | grep -q 'tool_calls lookup toolu_mock1'"
check "Ollama API served by the cloud rung too" "chat $U/api/chat -d '{\"model\":\"cloud\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"nd\"}]}' | J 'd[\"message\"][\"content\"] + \" \" + str(d[\"done\"]) + \" \" + str(d[\"eval_count\"])' | grep -q 'mock claude reply to: nd True [1-9]'"
check "OpenAI backend non-stream with cached tokens and request id" "chat $U/v1/chat/completions -d '{\"model\":\"oai\",\"messages\":[{\"role\":\"user\",\"content\":\"o\"}]}' | J 'd[\"choices\"][0][\"message\"][\"content\"] + \" \" + str(d[\"usage\"][\"prompt_tokens_details\"][\"cached_tokens\"])' | grep -q 'mock gpt reply to: o 3' && SQL \"select provider_request_id from maluos_ledger where backend='openai-mock' and status='ok' order by ledger_id desc limit 1\" | grep -q req_mock_openai"
check "OpenAI backend streaming" "chat -N $U/v1/chat/completions -d '{\"model\":\"oai\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"os\"}]}' | grep '^data: {' | sed 's/^data: //' | python3 -c 'import json,sys; print(\"\".join((json.loads(l)[\"choices\"] or [{\"delta\":{}}])[0][\"delta\"].get(\"content\",\"\") for l in sys.stdin if l.strip()))' | grep -q 'mock gpt reply to: os'"
check "OpenAI tool calls stream and translate" "chat $U/v1/chat/completions -d '{\"model\":\"oai\",\"messages\":[{\"role\":\"user\",\"content\":\"call tool please\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"lookup\",\"parameters\":{}}}]}' | J 'd[\"choices\"][0][\"message\"][\"tool_calls\"][0][\"id\"]' | grep -q call_mock1"
check "embeddings via the OpenAI backend" "chat $U/v1/embeddings -d '{\"model\":\"oembed\",\"input\":[\"a\",\"b\"]}' | J 'len(d[\"data\"]) == 2 and len(d[\"data\"][1][\"embedding\"]) == 8' | grep -q True && mock stats | J 'd[\"keys\"][-1][\"key\"]' | grep -q sk-system-openai"
check "Ollama cloud backend sends the bearer key" "chat $U/v1/chat/completions -d '{\"model\":\"ocloud\",\"messages\":[{\"role\":\"user\",\"content\":\"oc\"}]}' | grep -q 'mock reply to: oc' && mock stats | J 'd[\"keys\"][-1][\"provider\"] + \" \" + d[\"keys\"][-1][\"key\"]' | grep -q 'ollama sk-system-ollama'"
check "cost_actual recorded for cloud calls" "SQL \"select count(*) from maluos_ledger where backend='anthropic-mock' and status='ok' and cost_actual > 0 and currency='USD'\" | grep -qE '^[1-9]'"
check "budget: first call within the daily limit" "rmctl policy set --principal user:nobody --budget usd_per_day=0.00165 >/dev/null && Cn -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"max_tokens\":100,\"messages\":[{\"role\":\"user\",\"content\":\"b\"}]}' | grep -q 'mock claude'"
check "budget: next call rejected (budget_exceeded)" "sleep 0.2; Cn -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"max_tokens\":100,\"messages\":[{\"role\":\"user\",\"content\":\"b\"}]}' | J 'd[\"error\"][\"code\"]' | grep -q budget_exceeded"
check "policy cloud=no blocks the cloud" "rmctl policy set --principal user:nobody --budget none --cloud no >/dev/null && Cn -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"c\"}]}' | J 'd[\"error\"][\"route\"][0][\"skipped\"]' | grep -q cloud_not_allowed && rmctl policy rm --principal user:nobody >/dev/null"
check "/v1/models lists cloud models as cloud" "C $U/v1/models | J '[m[\"id\"] for m in d[\"data\"] if m.get(\"maluos\",{}).get(\"cloud\")]' | grep -q claude-mock"
check "status shows the cloud backend with its vault key reference" "mctl status | grep -q 'anthropic-mock  anthropic .* healthy  key: vault anthropic'"
check "usage report carries cost" "mctl usage --by backend | grep -E 'anthropic-mock +[0-9]+ .* 0\.[0-9]{4}' >/dev/null"
check "no secret value in the gateway log or ledger" "! grep -rq 'sk-me-anthropic\|sk-system' $W/gw.log && ! sudo -n -u postgres pg_dump -d $DB -n $T --data-only 2>/dev/null | grep -q 'sk-me-anthropic'"

echo "== slice 4: delegation, episodes, alerts, restart accounting, export/import, degradation"
check "delegation: agent uses the user's key (use only)" "vme delegate --to agent:bot --secret anthropic --expires 1h >/dev/null && Cp -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"d\"}]}' | grep -q 'mock claude' && mock stats | J 'd[\"keys\"][-1][\"key\"]' | grep -q '^sk-me-anthropic$'"
check "delegation recorded as the access reason in the vault ledger" "SQL \"select count(*) from maluos_ledger where event='secret.use' and principal_ref='agent:bot' and reason='delegation:user:$ME'\" | grep -qE '^[1-9]'"
check "delegation never grants read" "! sudo -n -u postgres env $ENV python3 $W/lib/maluctl secret show user:$ME/anthropic >/dev/null 2>&1"
check "delegations list" "vme delegations | grep -q 'user:$ME  agent:bot  user:$ME/anthropic'"
check "undelegate -> no_credential again" "vme undelegate --to agent:bot --secret anthropic | grep -q 'revoked 1' && Cp -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"d\"}]}' | J 'd[\"error\"][\"route\"][0][\"skipped\"]' | grep -q '^no_credential$'"
check "a call with a task reference writes a memory episode" "chat -H 'X-MaluOS-Task: ticket-42' $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"t\"}]}' | grep -q 'mock reply' && SQL \"select e.episode_kind || ' ' || (e.payload_jsonb->>'task_ref') from maluos_ledger l join maludb_episode e on e.episode_id=l.episode_id where l.task_ref='ticket-42'\" | grep -q 'maluos.model_call ticket-42'"
check "budget warning raises an alert (ledger, episode, hook)" "rmctl policy set --principal user:nobody --budget usd_per_day=0.0017,warn_at=0.5 >/dev/null && Cn -H 'Content-Type: application/json' $U/v1/chat/completions -d '{\"model\":\"cloud\",\"max_tokens\":100,\"messages\":[{\"role\":\"user\",\"content\":\"w\"}]}' | grep -q 'mock claude' && sleep 0.5 && SQL \"select count(*) from maluos_ledger where event='alert.budget' and principal_ref='user:nobody'\" | grep -qE '^[1-9]' && SQL \"select count(*) from maludb_episode where episode_kind='maluos.alert' and payload_jsonb->>'kind'='budget'\" | grep -qE '^[1-9]' && grep -q '\"kind\": \"budget\"' $W/hooks.log; rmctl policy rm --principal user:nobody >/dev/null"
check "manual alert through the API (operators)" "Cr -H 'Content-Type: application/json' $U/v1/maluos/alert -d '{\"kind\":\"test\",\"title\":\"hello alerts\"}' | grep -q '\"fired\": true' && rmctl alerts | grep -q 'test .*hello alerts'"
check "maluctl secret alerts lists them too (operators see all, users their own)" "vroot alerts | grep -q 'budget' && sudo -n -u nobody env $ENV python3 $W/lib/maluctl secret alerts | grep -q budget && ! vme alerts | grep -q 'hello alerts'"
kill $(cat $W/mock.pid); sleep 1; Cr -X POST $U/v1/maluos/reload >/dev/null; sleep 6
check "backend down beyond the limit -> alert" "SQL \"select count(*) from maluos_ledger where event='alert.backend_down' and detail->>'backend'='mock'\" | grep -qE '^[1-9]'"
check "degradation: local-only work fails with local_unavailable" "chat -H 'X-MaluOS-Local-Only: 1' $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' | J 'd[\"error\"][\"code\"]' | grep -q local_unavailable"
check "degradation: cloud-only tier with no reachable provider -> cloud_unreachable" "chat $U/v1/chat/completions -d '{\"model\":\"cloud\",\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}' | J 'd[\"error\"][\"code\"]' | grep -q cloud_unreachable"
PYTHONPATH=$W/lib python3 -m maluos_gateway.mock_ollama --port $MOCK --token-delay 0.005 --models mock-7b,mock-13b,mock-embed,mock-fail >>"$W/mock.log" 2>&1 & echo $! > "$W/mock.pid"; disown
for i in $(seq 1 30); do curl -sf http://127.0.0.1:$MOCK/api/tags >/dev/null && break; sleep 0.5; done; sleep 1; Cr -X POST $U/v1/maluos/reload >/dev/null; sleep 4
check "backend recovered -> alert" "SQL \"select count(*) from maluos_ledger where event='alert.backend_recovered' and detail->>'backend'='mock'\" | grep -qE '^[1-9]'"
check "backend serves again after recovery" "chat $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"back\"}]}' | grep -q 'mock reply to: back'"
RID3=$(SQL "select submit_request('chat', 'lose me', NULL, NULL, '{\"options\": {\"mock_delay_s\": 8}}', 60000)"); sleep 2.5
kill $(cat $W/gw.pid); sleep 1
PYTHONPATH=$W/lib MALUOS_GATEWAY_CONFIG=$W/gateway.yaml python3 -m maluos_gateway --socket "$W/gw.sock" >>"$W/gw.log" 2>&1 & echo $! > "$W/gw.pid"; disown
for i in $(seq 1 40); do [ -S "$W/gw.sock" ] && curl -sf --unix-socket "$W/gw.sock" http://g/v1/maluos/health >/dev/null && break; sleep 0.25; done; sleep 2
check "restart accounting: the lost engine request is failed as gateway_restart" "SQL \"select status || ' ' || coalesce((select error_class from maludb_core.\\\"malu\\\$model_response\\\" r where r.request_id=$RID3), '-') from maludb_core.\\\"malu\\\$model_request\\\" where request_id=$RID3\" | grep -q 'failed gateway_restart'"
check "restart recorded in the ledger with an alert" "SQL \"select count(*) from maluos_ledger where event='gateway.restart' and detail->'lost' @> '[$RID3]'\" | grep -qE '^[1-9]' && SQL \"select count(*) from maluos_ledger where event='alert.restart_lost_work'\" | grep -qE '^[1-9]'"
check "usage anomaly alert after a burst" "for i in \$(seq 1 6); do chat $U/v1/chat/completions -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"burst\"}]}' >/dev/null; done; sleep 4; SQL \"select count(*) from maluos_ledger where event='alert.usage_anomaly' and principal_ref='user:$ME'\" | grep -qE '^[1-9]'"
echo pw-test > $W/pw.txt
check "vault export (operator) is encrypted and logged" "vroot export $W/export.bin --passphrase-file $W/pw.txt | grep -q 'exported [1-9]' && ! grep -q 'sk-me-anthropic' $W/export.bin && SQL \"select count(*) from maluos_ledger where event='vault.export'\" | grep -qE '^[1-9]'"
check "export refused for non-operators" "! vme export $W/x.bin --passphrase-file $W/pw.txt 2>/dev/null"
check "import restores a deleted secret" "vme delete anthropic >/dev/null && ! vme show anthropic >/dev/null 2>&1 && vroot import $W/export.bin --passphrase-file $W/pw.txt | grep -q imported && [ \"\$(vme show anthropic)\" = sk-me-anthropic ]"
check "import with a wrong passphrase fails" "echo wrong > $W/pw2.txt; ! vroot import $W/export.bin --passphrase-file $W/pw2.txt 2>/dev/null"
check "retired key presented -> alert" "echo sk-me-new | vme rotate anthropic --grace 1h --stdin >/dev/null && vme show anthropic --previous | grep -q sk-me-anthropic && SQL \"select count(*) from maluos_ledger where event='alert.retired_key' and secret_name is null and reason like 'retired value of user:$ME/anthropic%'\" | grep -qE '^[1-9]'"

echo "== ledger"
check "model.call rows carry tokens, wait, process" "SQL \"select count(*) from maluos_ledger where event='model.call' and status='ok' and tokens_out > 0 and queue_wait_ms is not null and process_ref like 'curl@%' and linux_user='$ME'\" | grep -qE '^[1-9]'"
check "denials recorded (policy, 404, max-wait, queue_full)" "SQL \"select string_agg(distinct reason, ',') from maluos_ledger where status in ('denied','error') and event='model.call'\" | grep -q 'policy_tier' && SQL \"select string_agg(distinct reason, ',') from maluos_ledger where status in ('denied','error')\" | grep -q 'queue_full'"
check "gateway role cannot read memory tables" "! sudo -n -u postgres psql -Atd $DB -c \"set role $GROLE; select count(*) from $T.maludb_episode\" 2>/dev/null"
check "gateway role cannot alter the ledger" "! sudo -n -u postgres psql -Atd $DB -c \"set role $GROLE; delete from $T.maluos_ledger\" 2>/dev/null"

echo "== keep-warm"
mock reset POST >/dev/null
check "operator warm loads a model" "rmctl ollama warm mock-13b --backend mock | grep -q 'warmed mock-13b' && mock stats | J 'd[\"warm\"] >= 1' | grep -q True"
check "keep_warm policy applied (status lists loaded mock-13b)" "C $U/v1/maluos/status | J '[m[\"name\"] for b in d[\"backends\"] if b[\"name\"]==\"mock\" for m in b[\"loaded\"]]' | grep -q mock-13b"
check "no internal errors in the gateway log" "! grep -q 'internal error' $W/gw.log"

echo
[ $fail = 0 ] && echo "PASS: $n checks" || { echo "FAIL: $fail of $n checks (logs: $W/gw.log, $W/mock.log)"; exit 1; }
