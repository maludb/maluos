#!/bin/bash
# Phase 14 slice 1 on this host, without a VM (docs/phase14-database-server.md): a throwaway PostgreSQL 18
# cluster (maludb_core installed) is made a database server by the real first-boot code (role:
# database-server), then an office is provisioned against it over TCP and TLS as the admin role: the tenant,
# the principals, the vault's, the gateway's and the memory face's schemas, a second engine database from the
# template, the kernel's migrations, a service's password login, the kernel installer's remote psql. Proves
# the privilege model: nothing on the office side is a superuser.
#
#   tests/dbserver-local-test.sh          (KEEP=1 keeps the cluster and the work directory)
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
W=/var/tmp/maluos-dbserver-test; CL=maluosp14; PORT=${PORT:-5439}
fail=0; n=0
ok()   { n=$((n+1)); echo "  ok   $*"; }
bad()  { n=$((n+1)); fail=$((fail+1)); echo "  FAIL $*"; }
check(){ if (set +o pipefail; eval "$2"); then ok "$1"; else bad "$1"; fi; }

sudo -n true 2>/dev/null || { echo "needs passwordless sudo"; exit 2; }
[ -f /usr/share/postgresql/18/extension/maludb_core.control ] || { echo "needs PostgreSQL 18 with maludb_core"; exit 2; }
cleanup() { sudo pg_dropcluster --stop 18 $CL 2>/dev/null; sudo rm -rf "/etc/postgresql/18/$CL" "$W"; }   # the drop leaves conf.d (our file in it)
cleanup
sudo mkdir -p "$W"; sudo chmod 755 "$W"; sudo chown "$(id -un)" "$W"
mkdir -p "$W/lib" "$W/srv" "$W/off" "$W/export"
cp "$ROOT"/packages/maluos-firstboot/lib/maluos_provision.py "$ROOT"/packages/maluos-firstboot/bin/maluctl "$W/lib/"
PSQL() { sudo -u postgres env PGCLUSTER=18/$CL psql -XAtq "$@"; }

echo "== a scratch cluster 18/$CL on port $PORT"
sudo pg_createcluster 18 $CL --port "$PORT" --start >/dev/null 2>&1 || { echo "pg_createcluster failed"; exit 1; }

echo "== first boot of the database server (role: database-server)"
cat > "$W/srv/firstboot.yaml" <<EOF
role: database-server
database: maludb
operators: []
listener: {enabled: false}
database_server:
  cluster: 18/$CL
  listen: 127.0.0.1
  clients: [127.0.0.1/32, 192.168.100.0/24]
  names: [db-1.example.com]
EOF
SRV="MALUOS_FIRSTBOOT_CONFIG=$W/srv/firstboot.yaml MALUOS_STATE_DIR=$W/srv/state MALUOS_SECRETS_DIR=$W/srv/secrets MALUOS_DB_SERVER_DIR=$W/srv/etc PYTHONPATH=$W/lib"
sudo env $SRV python3 -c "import maluos_provision as mp, sys; sys.exit(mp.provision(force=True))" > "$W/srv/provision.log" 2>&1
check "the server's provisioning ran to its summary" "sudo test -f $W/srv/state/done"
sudo cat "$W/srv/state/done" > "$W/srv/done.json" 2>/dev/null
check "summary: role database-server, no tenant, the admin, the template, the fingerprint" \
  "python3 -c \"import json; d=json.load(open('$W/srv/done.json')); s=d['database_server']; assert d['role']=='database-server' and d['tenant'] is None and s['admin']=='maluos_admin' and s['template']=='maludb_template' and len(s['fingerprint'])==95 and s['port']==$PORT, d\""
check "the admin role: login, create role, create database, bypass RLS, NOT a superuser" \
  "[ \"\$(PSQL -c \"select rolcanlogin, rolcreaterole, rolcreatedb, rolbypassrls, rolsuper from pg_roles where rolname='maluos_admin'\")\" = 't|t|t|t|f' ]"
check "it administers the engine's roles (maludb_admin, maludb_user, maludb_read with the admin option)" \
  "[ \"\$(PSQL -c \"select count(*) from pg_auth_members a join pg_roles r on r.oid=a.roleid join pg_roles m on m.oid=a.member where m.rolname='maluos_admin' and r.rolname in ('maludb_admin','maludb_user','maludb_read') and a.admin_option\")\" = 3 ]"
check "the MaluDB database is the admin's; the template exists and is a template" \
  "[ \"\$(PSQL -c \"select string_agg(datname || ':' || pg_get_userbyid(datdba) || ':' || datistemplate, ',' order by datname) from pg_database where datname in ('maludb','maludb_template')\")\" = 'maludb:maluos_admin:false,maludb_template:postgres:true' ]"
check "TLS is on with the server's own certificate" "[ \"\$(PSQL -c 'show ssl')\" = on ] && sudo openssl x509 -in $W/srv/etc/server.crt -noout -ext subjectAltName | grep -q 'DNS:db-1.example.com'"
check "the key is the postgres user's alone" "[ \"\$(sudo stat -c '%U %a' $W/srv/etc/server.key)\" = 'postgres 600' ]"
check "pg_hba: one marked block, the clients by address, TLS and a password" \
  "[ \"\$(sudo grep -c 'maluos database-server begin' /etc/postgresql/18/$CL/pg_hba.conf)\" = 1 ] && sudo grep -q '^hostssl all all 192.168.100.0/24 scram-sha-256' /etc/postgresql/18/$CL/pg_hba.conf"
sudo env $SRV python3 -c "import maluos_provision as mp, sys; sys.exit(mp.provision(force=True))" > "$W/srv/provision2.log" 2>&1
check "a second run changes nothing (one block, the same password, no restart logged)" \
  "[ \"\$(sudo grep -c 'maluos database-server begin' /etc/postgresql/18/$CL/pg_hba.conf)\" = 1 ] && ! grep -q 'listening on' $W/srv/provision2.log"
sudo env $SRV MALUCTL_PLUGIN_DIR=/nonexistent python3 "$W/lib/maluctl" db export "$W/export" > "$W/srv/export.log" 2>&1
sudo chown -R "$(id -un)" "$W/export"
check "maluctl db export: the credential (0600), the certificate, the office's block" \
  "[ \"\$(stat -c %a $W/export/db-admin.txt)\" = 600 ] && grep -q 'BEGIN CERTIFICATE' $W/export/db-ca.pem && grep -q 'host: db-1.example.com' $W/export/database-server.yaml && grep -q 'credential: file:' $W/export/database-server.yaml"
check "maluctl status names the role and the certificate" "sudo env $SRV MALUCTL_PLUGIN_DIR=/nonexistent python3 $W/lib/maluctl status | grep -q 'role:        database server'"

echo "== the office, provisioned against it as the admin role"
cat > "$W/off/firstboot.yaml" <<EOF
database: maludb
database_server:
  host: localhost
  port: $PORT
  admin: maluos_admin
  credential: file:$W/export/db-admin.txt
  sslmode: verify-full
  ca: file:$W/export/db-ca.pem
EOF
OFF="MALUOS_FIRSTBOOT_CONFIG=$W/off/firstboot.yaml MALUOS_STATE_DIR=$W/off/state MALUOS_SECRETS_DIR=$W/off/secrets MALUOS_DB_CA=$W/off/ca.pem PYTHONPATH=$W/lib"
sudo env $OFF python3 - "$ROOT" "$W" > "$W/off/provision.log" 2>&1 <<'PY'
import glob, importlib.util, os, sys
import maluos_provision as mp
R, W = sys.argv[1] + "/packages", sys.argv[2]
def comp(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def step(name, fn):
    try:
        r = fn(); print(f"STEP ok {name}" + (f" {r}" if r is not None else ""))
    except Exception as e:
        print(f"STEP FAIL {name}: {str(e)[:400]}")
cfg = mp.load_config(); t = mp.database_target(cfg); mp.prepare_remote(t)
db, tenant = "maludb", "maluos"
step("wait", mp.wait_for_postgres)
step("who", lambda: mp.psql("select current_user || ' super=' || current_setting('is_superuser') || ' tls=' || (select version from pg_stat_ssl where pid = pg_backend_pid())"))
step("database", lambda: mp.ensure_database(db))
step("tenant", lambda: mp.ensure_tenant(db, tenant))
step("principal", lambda: mp.ensure_principal(db, tenant, cfg["admin_principal"]))
step("operators", lambda: mp.ensure_operators(db, tenant, ["alice"]))
v = comp(R + "/maluos-vault/components/40-maluos-vault.py", "v")
step("vault-schema", lambda: v.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, tenant, schema=R + "/maluos-vault/share/schema.sql", psql_file=mp.psql_file))
g = comp(R + "/maluos-gateway/components/45-maluos-gateway.py", "g")
step("gateway-schema", lambda: g.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, tenant, schema=R + "/maluos-gateway/share/schema.sql", psql_file=mp.psql_file))
step("gateway-principal", lambda: g.ensure_engine_principal(mp.psql, mp.exists, mp.qi, mp.ql, db, tenant))
step("gateway-tool", lambda: g.register_tool(mp.psql, mp.exists, mp.qi, mp.ql, db, tenant, "maludb-mc2dbd"))
m = comp(R + "/maluos-memory/components/50-maluos-memory.py", "m")
step("memory-schema", lambda: m.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, tenant))
step("memory-principals", lambda: m.ensure_principals(mp.psql, mp.qi, mp.ql, db, tenant))
step("engine-database", lambda: mp.ensure_maludb_database("maludb_os_memory"))
step("engine-database-again", lambda: mp.ensure_maludb_database("maludb_os_memory"))
step("vault-login", lambda: sorted(mp.service_login("maluos-vault", password_file=W + "/off/vault-pg.password").items()))
def kernel():
    if not mp.exists("SELECT 1 FROM pg_database WHERE datname='maludb_os'"):
        mp.psql('CREATE DATABASE "maludb_os"')
    n = 0
    for f in sorted(glob.glob(R + "/maludb-os-core/upstream/db/*.sql")):
        r = mp.psql_file(f, "maludb_os", check=False)
        if r.returncode != 0:
            raise RuntimeError(os.path.basename(f) + ": " + r.stderr[-300:])
        n += 1
    return n
step("kernel-migrations", kernel)
PY
sudo chown -R "$(id -un)" "$W/off" 2>/dev/null
L="$W/off/provision.log"
check "no step failed" "! grep -q '^STEP FAIL' $L && [ \"\$(grep -c '^STEP ok' $L)\" = 16 ]"
grep '^STEP FAIL' "$L" | cut -c1-300
check "the office's connection: the admin role, not a superuser, TLS 1.3, the certificate verified" "grep -q '^STEP ok who maluos_admin super=off tls=TLSv1.3' $L"
check "the credential and the certificate were taken from the medium once (root-only password and PGPASSFILE)" \
  "[ \"\$(stat -c %a $W/off/secrets/db-admin.password $W/off/secrets/db-admin.pgpass | tr '\n' ' ')\" = '600 600 ' ] && cmp -s $W/export/db-ca.pem $W/off/ca.pem"
check "the tenant: its role, its schema, the memory facades" \
  "[ \"\$(PSQL -d maludb -c \"select count(*) from pg_views where schemaname='maluos' and viewname in ('maludb_principal','maludb_memory')\")\" = 2 ]"
check "principals: the administrator and the operator" \
  "[ \"\$(PSQL -d maludb -c \"select count(*) from maludb_core.\\\"malu\\\$principal\\\" where principal_ref in ('human:admin','user:alice')\")\" = 2 ]"
check "operators get no database role when the data is remote (no superuser outside the database server)" \
  "[ \"\$(PSQL -c \"select count(*) from pg_roles where rolname='alice'\")\" = 0 ] && [ \"\$(PSQL -c \"select count(*) from pg_roles where rolsuper and rolname <> 'postgres'\")\" = 0 ]"
check "the vault's, the gateway's and the memory face's roles and tables" \
  "[ \"\$(PSQL -c \"select count(*) from pg_roles where rolname in ('maluos-vault','maluos-gateway','maluos-memory')\")\" = 3 ] && [ \"\$(PSQL -d maludb -c \"select count(*) from pg_tables where schemaname='maluos' and tablename in ('maluos_secret','maluos_ledger','maluos_backend','maluos_token')\")\" = 4 ]"
check "the gateway's role bypasses RLS (granted by the admin role, which may)" "[ \"\$(PSQL -c \"select rolbypassrls from pg_roles where rolname='maluos-gateway'\")\" = t ]"
check "a second engine database, copied from the template, with the engine in it" \
  "grep -q '^STEP ok engine-database True' $L && grep -q '^STEP ok engine-database-again False' $L && [ \"\$(PSQL -d maludb_os_memory -c \"select count(*) from pg_extension where extname in ('vector','maludb_core')\")\" = 2 ]"
check "the kernel's migrations apply as the admin role (its four roles exist)" \
  "grep -Eq '^STEP ok kernel-migrations [0-9]{3}' $L && [ \"\$(PSQL -c \"select count(*) from pg_roles where rolname in ('app_rw','app_records_ro','app_activity_ro','app_runner')\")\" = 4 ]"
check "a service's login: the keys for its configuration, the password in its own file" \
  "grep -q \"^STEP ok vault-login .*('pg_host', 'localhost').*('pg_password_file'.*('pg_port', $PORT).*('pg_sslmode', 'verify-full').*('pg_user', 'maluos-vault')\" $L && [ \"\$(stat -c %a $W/off/vault-pg.password)\" = 600 ]"
sudo env PYTHONPATH="$ROOT/packages/maluos-memory/lib" python3 - "$W" "$PORT" > "$W/off/service.log" 2>&1 <<'PY'
import sys, psycopg
from maluos_memory.engine import remote_kwargs
W, port = sys.argv[1], int(sys.argv[2])
d = {"pg_port": port, "pg_sslmode": "verify-full", "pg_sslrootcert": W + "/off/ca.pem", "pg_password_file": W + "/off/vault-pg.password"}
with psycopg.connect(dbname="maludb", host="localhost", user="maluos-vault", options="-c search_path=maluos,maludb_core,public", **remote_kwargs(d)) as c:
    print("SERVICE", c.execute("select current_user, (select ssl from pg_stat_ssl where pid = pg_backend_pid()), (select count(*) from maluos_compartment)").fetchone())
try:
    psycopg.connect(dbname="maludb", host="localhost", user="maluos-vault", port=port, sslmode="verify-full", sslrootcert="/etc/ssl/certs/ca-certificates.crt",
                    password=open(W + "/off/vault-pg.password").read().strip(), connect_timeout=10)
    print("WRONGCA connected")
except Exception as e:
    print("WRONGCA refused", str(e)[:80])
try:
    psycopg.connect(dbname="maludb", host="localhost", user="maluos-vault", port=port, sslmode="verify-full", sslrootcert=W + "/off/ca.pem", password="not-it", connect_timeout=10)
    print("WRONGPW connected")
except Exception as e:
    print("WRONGPW refused", str(e)[:80])
PY
check "the service connects with the daemons' own code: its role, TLS, its tables" "grep -q \"^SERVICE ('maluos-vault', True, 0)\" $W/off/service.log"
check "a certificate that is not the server's is refused (verify-full)" "grep -q '^WRONGCA refused' $W/off/service.log"
check "a wrong password is refused" "grep -q '^WRONGPW refused' $W/off/service.log"
check "maluctl db status on the office: where the data is, reached, not a superuser" \
  "sudo env $OFF MALUCTL_PLUGIN_DIR=/nonexistent python3 $W/lib/maluctl db status | tr '\n' ' ' | grep -q 'on the database server localhost:$PORT (verify-full) as maluos_admin.*reached:   yes, as maluos_admin (not a superuser).*TLSv1.3'"
check "maluctl db psql runs a statement there" "[ \"\$(sudo env $OFF MALUCTL_PLUGIN_DIR=/nonexistent python3 $W/lib/maluctl db psql maludb -XAtc 'select current_user')\" = maluos_admin ]"

INST="$ROOT/packages/maludb-os-core/upstream/bin/app_install.php"
if grep -q 'function psql_cmd' "$INST" 2>/dev/null && command -v php >/dev/null; then
  echo "== the kernel's application installer, its database steps against the server"
  cat > "$W/off/installer.php" <<'PHP'
<?php
$src = file_get_contents($argv[1]);
$a = strpos($src, '$DBT = null;'); $b = strpos($src, 'function env_file_read');
function q(string $cmd): array { exec($cmd . ' 2>&1', $out, $code); return [$code, implode("\n", $out)]; }
eval(substr($src, $a, $b - $a));
$DBT = ['host' => 'localhost', 'port' => (int) $argv[3], 'admin' => 'maluos_admin', 'passfile' => $argv[2] . '/off/secrets/db-admin.pgpass', 'sslmode' => 'verify-full', 'ca' => $argv[2] . '/off/ca.pem'];
$r = [];
$r[] = psql("DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'p14app_rw') THEN CREATE ROLE p14app_rw LOGIN; END IF; END \$\$;");
$r[] = psql("CREATE DATABASE p14app OWNER p14app_rw");
file_put_contents($argv[2] . '/off/m1.sql', "CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE TABLE t1 (id serial primary key, v text); GRANT SELECT ON t1 TO p14app_rw;");
$r[] = q(psql_cmd() . ' -v ON_ERROR_STOP=1 -q -d p14app -f ' . escapeshellarg($argv[2] . '/off/m1.sql'));
$r[] = psql("ALTER ROLE p14app_rw WITH LOGIN PASSWORD 'x'");
foreach ($r as $x) { if ($x[0] !== 0) { echo "INSTALLER FAIL {$x[1]}\n"; exit(1); } }
echo "INSTALLER ok " . psql_ro("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='p14app'")[1] . ' env=' . implode(',', array_keys(psql_env())) . "\n";
PHP
  sudo php "$W/off/installer.php" "$INST" "$W" "$PORT" > "$W/off/installer.log" 2>&1
  check "an application's role, its database (owned by the role) and a migration, as the admin role" "grep -q '^INSTALLER ok p14app_rw env=PGHOST,PGPORT,PGUSER,PGPASSFILE,DB_HOST,DB_PORT,PGSSLMODE,PGSSLROOTCERT' $W/off/installer.log"
else
  echo "== (the vendored kernel has no --db-* options yet: the installer's remote steps are not exercised)"
fi

echo "== an application server on the same database server: names of its own (gap 8, docs/phase14-application-servers.md)"
mkdir -p "$W/app"
cat > "$W/app/firstboot.yaml" <<EOF
role: application-server
database: maludb
database_server:
  host: localhost
  port: $PORT
  admin: maluos_admin
  credential: file:$W/export/db-admin.txt
  sslmode: verify-full
  ca: file:$W/export/db-ca.pem
  suffix: App-1
EOF
APP="MALUOS_FIRSTBOOT_CONFIG=$W/app/firstboot.yaml MALUOS_STATE_DIR=$W/app/state MALUOS_SECRETS_DIR=$W/app/secrets MALUOS_DB_CA=$W/app/ca.pem PYTHONPATH=$W/lib"
sudo env $APP python3 - "$ROOT" "$W" > "$W/app/provision.log" 2>&1 <<'PY'
import importlib.util, sys
import maluos_provision as mp
R, W = sys.argv[1] + "/packages", sys.argv[2]
def comp(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def step(name, fn):
    try:
        r = fn(); print(f"STEP ok {name}" + (f" {r}" if r is not None else ""))
    except Exception as e:
        print(f"STEP FAIL {name}: {str(e)[:400]}")
cfg = mp.load_config(); t = mp.database_target(cfg); mp.prepare_remote(t)
db, tenant = mp.platform_db(cfg), "maluos"
step("names", lambda: f"{mp.is_application_server(cfg)} {mp.platform_suffix()} {db} {mp.db_role('maluos-vault')}")
step("database", lambda: mp.ensure_database(db))
step("tenant", lambda: mp.ensure_tenant(db, tenant))
step("principal", lambda: mp.ensure_principal(db, tenant, cfg["admin_principal"]))
v = comp(R + "/maluos-vault/components/40-maluos-vault.py", "v")
step("vault-schema", lambda: v.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, tenant, role=mp.db_role(v.ROLE), schema=R + "/maluos-vault/share/schema.sql", psql_file=mp.psql_file))
g = comp(R + "/maluos-gateway/components/45-maluos-gateway.py", "g")
step("gateway-schema", lambda: g.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, tenant, role=mp.db_role(g.ROLE), schema=R + "/maluos-gateway/share/schema.sql", psql_file=mp.psql_file))
m = comp(R + "/maluos-memory/components/50-maluos-memory.py", "m")
step("memory-schema", lambda: m.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, tenant, role=mp.db_role(m.ROLE)))
step("vault-login", lambda: sorted(mp.service_login("maluos-vault", password_file=W + "/app/vault-pg.password").items()))
step("again", lambda: (v.ensure_schema(mp.psql, mp.exists, mp.qi, mp.ql, db, tenant, role=mp.db_role(v.ROLE), schema=R + "/maluos-vault/share/schema.sql", psql_file=mp.psql_file),
                       sorted(mp.service_login("maluos-vault", password_file=W + "/app/vault-pg.password").items()))[1])
PY
sudo chown -R "$(id -un)" "$W/app" 2>/dev/null
L="$W/app/provision.log"
grep '^STEP FAIL' "$L" | cut -c1-300
check "the application server's first boot against the same server: no step failed" "! grep -q '^STEP FAIL' $L && [ \"\$(grep -c '^STEP ok' $L)\" = 9 ]"
check "its names: the suffix from the plan, a database and roles of its own" "grep -q '^STEP ok names True app_1 maludb_app_1 maluos-vault-app_1' $L"
check "the database maludb_app_1 and the three suffixed roles exist beside the office's" \
  "[ \"\$(PSQL -c \"select count(*) from pg_database where datname in ('maludb','maludb_app_1')\")\" = 2 ] && [ \"\$(PSQL -c \"select string_agg(rolname, ',' order by rolname) from pg_roles where rolname like 'maluos-%'\")\" = 'maluos-gateway,maluos-gateway-app_1,maluos-memory,maluos-memory-app_1,maluos-vault,maluos-vault-app_1' ]"
check "the service's login carries the suffixed role" "grep -q \"^STEP ok vault-login .*('pg_user', 'maluos-vault-app_1')\" $L"
VP() { PGPASSWORD=$(cat "$2") psql -XAtq "host=localhost port=$PORT user=$1 dbname=$3 sslmode=verify-full sslrootcert=$W/export/db-ca.pem connect_timeout=10" -c "$4" 2>&1; }
check "the office's vault still logs in with its own password after the application server's first boot (and its re-run)" \
  "[ \"\$(VP maluos-vault $W/off/vault-pg.password maludb 'select current_user')\" = maluos-vault ]"
check "the application server's vault logs in to its own database with its own password" \
  "[ \"\$(VP maluos-vault-app_1 $W/app/vault-pg.password maludb_app_1 'select current_user')\" = maluos-vault-app_1 ] && ! cmp -s $W/off/vault-pg.password $W/app/vault-pg.password"
check "and reads nothing of the office's vault" \
  "VP maluos-vault-app_1 $W/app/vault-pg.password maludb 'select count(*) from maluos.vault_secret' | grep -qi 'permission denied'"

echo
[ "${KEEP:-0}" = 1 ] || cleanup
echo "$n checks, $fail failed"
[ $fail = 0 ] && echo "PASS: an office provisions against a MaluOS database server without a superuser" || echo "FAIL"
exit $fail
