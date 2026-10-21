#!/bin/bash
# Exercise the vault daemon and `maluctl secret` on this host, without a VM:
# a throwaway database on the local PostgreSQL 18 (maludb_core installed), the
# daemon run as the current user with a test master key, callers = you, root
# (sudo) and nobody (sudo -u). Covers peer-credential identity, compartments,
# grants (principal and scope), rotation with grace, locks, expiry, exec, the
# broker path, the ledger and its append-only rule, and that no value leaks.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
W=/var/tmp/maluos-vault-test; DB=maluos_vaulttest; T=vt; VROLE=vaulttest_vault; ME=$(id -un)
fail=0; n=0
ok()   { n=$((n+1)); echo "  ok   $*"; }
bad()  { n=$((n+1)); fail=$((fail+1)); echo "  FAIL $*"; }
check(){ if (set +o pipefail; eval "$2"); then ok "$1"; else bad "$1"; fi; }

sudo -n true 2>/dev/null || { echo "needs passwordless sudo"; exit 2; }
pkill -f "$W/lib/maluos_vault.py" 2>/dev/null; sleep 0.5
sudo rm -rf "$W"; mkdir -p "$W/lib/maluctl.d" "$W/cred" "$W/state"; chmod 755 "$W" "$W/lib" "$W/lib/maluctl.d"
cp packages/maluos-firstboot/lib/maluos_provision.py packages/maluos-firstboot/bin/maluctl \
   packages/maluos-vault/lib/maluos_vault.py packages/maluos-vault/lib/maluos_vault_client.py \
   packages/maluos-vault/components/40-maluos-vault.py packages/maluos-vault/share/schema.sql "$W/lib/"
cp packages/maluos-vault/lib/maluctl.d/secret.py "$W/lib/maluctl.d/"
chmod -R a+rX "$W/lib"; head -c 32 /dev/urandom > "$W/cred/maluos-vault.key"
cat > "$W/vault.yaml" <<EOF
socket: $W/vault.sock
database: $DB
tenant: $T
pg_role: $VROLE
state_dir: $W/state
brokers: [postgres]
identities: {postgres: "agent:bot"}
EOF
chmod 644 "$W/vault.yaml"

echo "== database $DB (tenant $T)"
sudo -n -u postgres psql -Xq -c "DROP DATABASE IF EXISTS $DB" -c "DROP ROLE IF EXISTS $VROLE" -c "DROP ROLE IF EXISTS $T" >/dev/null
sudo -n env PYTHONPATH="$W/lib" python3 - "$DB" "$T" "$VROLE" "$ME" <<'PY' || exit 1
import sys, importlib.util
import maluos_provision as mp
db, t, vrole, me = sys.argv[1:5]
mp.ensure_database(db); mp.ensure_tenant(db, t)
for ref, kind in ((f"user:{me}", "human"), ("user:nobody", "human"), ("agent:bot", "agent")):
    mp.ensure_principal(db, t, {"ref": ref, "kind": kind, "display_name": ref, "home_scope": ref})
mp.psql(f"SET ROLE {mp.qi(t)}; SET search_path TO {mp.qi(t)}, maludb_core, public; SELECT maludb_principal_grant_scope('agent:bot', 'org', 'read');", db)
spec = importlib.util.spec_from_file_location("comp", "/var/tmp/maluos-vault-test/lib/40-maluos-vault.py")
comp = importlib.util.module_from_spec(spec); spec.loader.exec_module(comp)
mp.psql(f"CREATE ROLE {mp.qi(vrole)} NOLOGIN")
comp.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, t, role=vrole, schema="/var/tmp/maluos-vault-test/lib/schema.sql")
print("  schema + grants applied")
PY

echo "== daemon"
( cd "$W" && CREDENTIALS_DIRECTORY=$W/cred MALUOS_VAULT_CONFIG=$W/vault.yaml MALUOS_VAULT_DEBUG=1 \
    python3 "$W/lib/maluos_vault.py" --socket "$W/vault.sock" >"$W/daemon.log" 2>&1 & echo $! > "$W/daemon.pid" )
trap 'kill $(cat $W/daemon.pid) 2>/dev/null' EXIT
for i in $(seq 1 20); do [ -S "$W/vault.sock" ] && break; sleep 0.25; done
ENV="PYTHONPATH=$W/lib MALUCTL_PLUGIN_DIR=$W/lib/maluctl.d MALUOS_VAULT_SOCKET=$W/vault.sock"
me()     { env $ENV python3 "$W/lib/maluctl" secret "$@"; }
root()   { sudo -n env $ENV python3 "$W/lib/maluctl" secret "$@"; }
nobody() { sudo -n -u nobody env $ENV python3 "$W/lib/maluctl" secret "$@"; }
pgu()    { sudo -n -u postgres env $ENV python3 "$W/lib/maluctl" secret "$@"; }

check "health" "env $ENV python3 -c 'import maluos_vault_client as c; import sys; sys.exit(0 if c.Vault().health()[\"ok\"] else 1)'"
check "whoami as $ME -> user:$ME" "me whoami | grep -q 'principal:  user:$ME'"
check "whoami as root -> operator" "root whoami | grep -q 'operator:   yes'"
check "identity map postgres -> agent:bot (broker)" "pgu whoami | grep -q 'agent:bot' && pgu whoami | grep -q 'broker: yes'"

echo "== two users, same secret name, different values (acceptance test 1)"
check "$ME adds openai" "echo sk-A-111 | me add openai --provider openai --stdin | grep -q 'user:$ME/openai'"
check "nobody adds openai" "echo sk-B-222 | nobody add openai --provider openai --stdin | grep -q 'user:nobody/openai'"
check "$ME reads own value" "[ \"\$(me show openai)\" = sk-A-111 ]"
check "nobody reads own value" "[ \"\$(nobody show openai)\" = sk-B-222 ]"
check "nobody cannot read $ME's key" "! nobody show user:$ME/openai 2>/dev/null"
check "$ME cannot read nobody's key" "me show user:nobody/openai 2>&1 | grep -q 'no .* access\|forbidden'"
check "exec injects OPENAI_API_KEY" "[ \"\$(me exec openai -- sh -c 'echo \$OPENAI_API_KEY')\" = sk-A-111 ]"
check "exec with explicit var" "[ \"\$(me exec MYVAR=openai -- sh -c 'echo \$MYVAR')\" = sk-A-111 ]"

echo "== shared compartment, grants"
check "root creates system compartment" "root compartment create system --scope org | grep -q created"
check "nobody cannot create a shared compartment" "! nobody compartment create shared2 2>/dev/null"
check "root adds system/shared-key" "echo S-333 | root add system/shared-key --kind token --env SHARED --stdin | grep -q system/shared-key"
check "nobody cannot see shared-key yet" "! nobody show shared-key 2>/dev/null"
check "root grants use to user:nobody" "root grant system/shared-key --to user:nobody --level use | grep -q granted"
check "use grant is not read (show denied)" "nobody show shared-key 2>&1 | grep -q 'no read access'"
check "mode=use rejected for non-broker" "sudo -n -u nobody env $ENV python3 -c 'import maluos_vault_client as c
try: c.Vault().use(\"shared-key\"); raise SystemExit(1)
except c.VaultError as e: raise SystemExit(0 if e.code==\"use_requires_broker\" else 2)'"
check "broker uses it on behalf of user:nobody" "sudo -n -u postgres env $ENV python3 -c 'import maluos_vault_client as c
r=c.Vault(on_behalf_of=\"user:nobody\").use(\"shared-key\", purpose=\"test call\"); raise SystemExit(0 if r[\"value\"]==\"S-333\" else 1)'"
check "broker cannot act for an unknown principal" "sudo -n -u postgres env $ENV python3 -c 'import maluos_vault_client as c
try: c.Vault(on_behalf_of=\"user:ghost\").use(\"shared-key\"); raise SystemExit(1)
except c.VaultError as e: raise SystemExit(0 if e.code==\"unknown_principal\" else 2)'"
check "non-broker cannot assert a principal" "env $ENV python3 -c 'import maluos_vault_client as c
try: c.Vault(on_behalf_of=\"user:nobody\").whoami(); raise SystemExit(1)
except c.VaultError as e: raise SystemExit(0 if e.code==\"not_a_broker\" else 2)'"
check "root upgrades grant to read" "root grant system/shared-key --to user:nobody --level read | grep -q 'granted read'"
check "nobody now reads shared-key" "[ \"\$(nobody show shared-key)\" = S-333 ]"
check "bare name resolves through grants" "nobody list | grep -q 'system/shared-key.*read'"
check "root revokes" "root revoke system/shared-key --to user:nobody | grep -q 'revoked 1'"
check "nobody denied again" "! nobody show shared-key 2>/dev/null"
check "scope grant: org -> agent:bot reads" "root grant system/shared-key --scope org --level read >/dev/null && [ \"\$(pgu show shared-key)\" = S-333 ]"
check "scope grant does not reach nobody" "! nobody show shared-key 2>/dev/null"
check "info lists grants for the operator" "root info system/shared-key | grep -q 'read  scope:org'"
check "grant with expiry in the past is inert" "root grant system/shared-key --to user:nobody --level read --expires 1s >/dev/null; sleep 2; ! nobody show shared-key 2>/dev/null"

echo "== rotation, lock, expiry, delete"
check "rotate with grace" "echo sk-A-NEW | me rotate openai --grace 1h --stdin | grep -q 'previous value valid'"
check "new value served" "[ \"\$(me show openai)\" = sk-A-NEW ]"
check "previous value within grace" "[ \"\$(me show openai --previous)\" = sk-A-111 ]"
check "rotate without grace drops previous" "echo sk-A-NEW2 | me rotate openai --stdin >/dev/null && ! me show openai --previous 2>/dev/null"
check "lock own compartment" "me compartment lock user:$ME | grep -q locked"
check "locked -> read refused (423)" "me show openai 2>&1 | grep -q 'is locked'"
check "unlock" "me compartment unlock user:$ME | grep -q unlocked && [ \"\$(me show openai)\" = sk-A-NEW2 ]"
check "nobody cannot lock $ME's compartment" "! nobody compartment lock user:$ME 2>/dev/null"
check "expiry enforced" "echo tmp | me add temp --expires 1s --stdin >/dev/null; sleep 2; me show temp 2>&1 | grep -q expired"
check "delete" "me delete temp | grep -q deleted && ! me info temp 2>/dev/null"
check "add twice -> exists" "echo x | me add openai --stdin 2>&1 | grep -q exists"
check "upsert same value is a no-op rotate" "echo sk-A-NEW2 | me add openai --upsert --stdin | grep -q stored"
check "bad name rejected" "echo x | me add 'bad name!' --stdin 2>&1 | grep -q 'secret names'"
check "unenrolled user refused" "sudo -n -u daemon env $ENV python3 -c 'import maluos_vault_client as c
try: c.Vault().add(\"k\",\"v\"); raise SystemExit(1)
except c.VaultError as e: raise SystemExit(0 if e.code==\"not_enrolled\" else 2)'"

echo "== grant requests and ownership (Phase 12 slice 3)"
check "a refusal files a request for the owner" "nobody show user:$ME/openai 2>&1 | grep -q 'grant request #.* is pending'"
check "$ME sees the pending request" "me requests | grep -q 'user:$ME/openai .*user:nobody .*read'"
check "nobody sees their own request" "nobody requests | grep -q 'user:nobody'"
check "root sees every request" "root requests | grep -q 'user:nobody'"
check "asking again bumps the same request" "nobody request user:$ME/openai --purpose 'need it' | grep -q 'asked [0-9]* times' && [ \"\$(me requests | awk '\$2==\"user:$ME/openai\" && \$3==\"user:nobody\"' | wc -l)\" = 1 ]"
rid=$(me requests | awk '$2=="user:'"$ME"'/openai" && $3=="user:nobody"{print $1}' | head -1)
check "the requester cannot approve" "nobody approve $rid 2>&1 | grep -q 'only the owner'"
check "$ME approves with an expiry" "me approve $rid --expires 1h | grep -q 'user:nobody may read user:$ME/openai until'"
check "nobody now reads the secret" "[ \"\$(nobody show user:$ME/openai)\" = sk-A-NEW2 ]"
check "the request is recorded approved with its grant" "me requests --all | grep -q \"approved by user:$ME\" && sudo -n -u postgres psql -Atd $DB -c \"select count(*) from $T.maluos_secret_request where request_id=$rid and status='approved' and grant_id is not null\" | grep -q 1"
check "approving twice is refused" "me approve $rid 2>&1 | grep -q 'already approved'"
echo d-444 | me add deny-me --stdin >/dev/null
check "refusal on another secret files a second request" "nobody show user:$ME/deny-me 2>&1 | grep -q 'grant request #'"
rid2=$(me requests | awk '/deny-me/{print $1}' | head -1)
check "$ME denies it" "me deny $rid2 --reason no | grep -q 'denied request #$rid2'"
check "a denied request is not re-filed by the next refusal" "nobody show user:$ME/deny-me 2>&1 | grep -q 'no read access' && ! nobody show user:$ME/deny-me 2>&1 | grep -q 'request #' && [ -z \"\$(me requests | grep deny-me)\" ]"
check "an explicit ask after a denial is filed again" "nobody request user:$ME/deny-me | grep -q pending"
check "the owner asking for their own secret is refused" "me request user:$ME/openai 2>&1 | grep -q 'nothing to ask'"
check "request events in the ledger" "me usage --raw | grep -q 'request.approve .*ok' && me usage --raw | grep -q 'request.deny .*ok'"
check "agent rows hidden before ownership" "! me usage --raw | grep -q 'agent:bot'"
sudo -n -u postgres psql -Atqd $DB -c "set role $T; insert into $T.maluos_agent (name, principal_ref, owner_principal_ref) values ('bot', 'agent:bot', 'user:$ME')" >/dev/null
check "the owner sees their agent's ledger rows" "me usage --raw | grep -q 'secret.read .*ok .*agent:bot'"
check "nobody still does not" "! nobody usage --raw | grep -q 'agent:bot'"

echo "== ledger"
check "usage lists my events" "me usage --raw | grep -q 'secret.read .*ok .*user:$ME .*user:$ME/openai'"
check "usage shows denials" "me usage --raw | grep -q 'denied'"
check "nobody sees only own rows" "[ -z \"\$(nobody usage --raw | grep -v 'user:nobody')\" ] && nobody usage --raw | grep -q 'secret.read'"
check "broker row carries both principals" "sudo -n -u postgres psql -Atd $DB -c \"select 1 from $T.maluos_ledger where event='secret.use' and principal_ref='user:nobody' and broker_ref='agent:bot' and purpose='test call'\" | grep -q 1"
check "process_ref recorded" "sudo -n -u postgres psql -Atd $DB -c \"select count(*) from $T.maluos_ledger where process_ref like 'python3@%'\" | grep -qE '^[1-9]'"
check "usage summary by secret" "root usage --by secret | grep -q 'system/shared-key'"
check "ledger append-only for the owner" "! sudo -n -u postgres psql -Atd $DB -c \"set role $T; update $T.maluos_ledger set status='ok' where status='denied'\" 2>/dev/null"
check "ledger append-only for the vault role" "! sudo -n -u postgres psql -Atd $DB -c \"set role $VROLE; delete from $T.maluos_ledger\" 2>/dev/null"
check "vault role cannot read memory tables" "! sudo -n -u postgres psql -Atd $DB -c \"set role $VROLE; select count(*) from $T.maludb_episode\" 2>/dev/null"
check "daily roll-up view" "sudo -n -u postgres psql -Atd $DB -c \"select sum(events) from $T.maluos_ledger_daily\" | grep -qE '^[1-9]'"

echo "== no value leaks"
dump=$(sudo -n -u postgres pg_dump -d $DB -n $T --data-only 2>/dev/null)
for v in sk-A-111 sk-B-222 S-333 sk-A-NEW sk-A-NEW2; do
  check "value $v absent from the database" "! grep -q -- '$v' <<<\"\$dump\""
  check "value $v absent from blobs and daemon log" "! grep -rq -- '$v' $W/state $W/daemon.log"
done
check "blob files are 0600" "[ -z \"\$(find $W/state/blobs -type f ! -perm 0600)\" ]"

echo
[ $fail = 0 ] && echo "PASS: $n checks" || { echo "FAIL: $fail of $n checks (daemon log: $W/daemon.log)"; exit 1; }
