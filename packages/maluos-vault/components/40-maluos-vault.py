"""MaluOS first-boot component: the secret vault (maluos-vault).

Runs after the core provisioning and before the other components, so they can
store their credentials in it. Creates the master key credential (sealed by
systemd-creds: TPM when present, host key otherwise), the vault's PostgreSQL
role, the tenant-schema tables (compartments, secrets, grants, ledger), the
shared `system` compartment, starts the socket and imports the listener token.
"""
import json, os, pwd, subprocess, sys, time

STATE = "/var/lib/maluos-vault"
CRED = os.path.join(STATE, "master.cred")
ROLE = "maluos-vault"
SCHEMA = "/usr/share/maluos-vault/schema.sql"
CONF = "/etc/maluos/vault.yaml"
DAEMON = "/usr/lib/maluos/maluos_vault.py"
TABLES = ("maluos_compartment", "maluos_secret", "maluos_secret_grant", "maluos_delegation")
SEQUENCES = ("maluos_compartment_compartment_id_seq", "maluos_secret_secret_id_seq", "maluos_secret_grant_grant_id_seq",
             "maluos_delegation_delegation_id_seq", "maluos_ledger_ledger_id_seq")


def provision(ctx):
    log, psql, exists, qi, ql = ctx["log"], ctx["psql"], ctx["exists"], ctx["qi"], ctx["ql"]
    db, tenant = ctx["db"], ctx["tenant"]
    if not os.path.exists(DAEMON):
        return None
    try:
        uid, gid = pwd.getpwnam(ROLE).pw_uid, pwd.getpwnam(ROLE).pw_gid
    except KeyError:
        raise RuntimeError(f"system user {ROLE} missing (package postinst did not run?)")

    # 1. master key credential, once per installation
    os.makedirs(STATE, mode=0o700, exist_ok=True); os.chown(STATE, uid, gid); os.chmod(STATE, 0o700)
    if not os.path.exists(CRED):
        r = subprocess.run(["systemd-creds", "encrypt", "--name=maluos-vault.key", "-", CRED],
                           input=os.urandom(32), capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(f"systemd-creds encrypt failed: {r.stderr.decode().strip()}")
        os.chown(CRED, 0, 0); os.chmod(CRED, 0o600)
        log(f"vault: master key sealed to {CRED} ({'TPM2 + host key' if has_tpm() else 'host key'})")

    # 2. database role and schema
    ensure_schema(psql, exists, qi, ql, db, tenant)
    log(f"vault: schema in {tenant}, grants to {ROLE}")

    # 3. configuration
    import yaml
    cfg = {}
    if os.path.exists(CONF):
        with open(CONF) as f:
            cfg = yaml.safe_load(f) or {}
    want = dict(cfg); want.update({"database": db, "tenant": tenant})
    if want != cfg:
        with open(CONF, "w") as f:
            f.write("# MaluOS vault (maluos-vault). database/tenant are set by first boot.\n"
                    "# brokers: Linux users allowed to act on behalf of a principal (the gateway).\n"
                    "# identities: map a Linux user to a principal other than user:<name>.\n")
            yaml.safe_dump(want, f, sort_keys=True)
        os.chmod(CONF, 0o644)

    # 4. start
    subprocess.run(["systemctl", "enable", "--quiet", "maluos-vault.socket"], check=False)
    subprocess.run(["systemctl", "start", "maluos-vault.socket"], check=False)
    subprocess.run(["systemctl", "restart", "maluos-vault.service"], check=False)
    sys.path.insert(0, "/usr/lib/maluos")
    from maluos_vault_client import Vault, VaultError
    v = Vault()
    healthy = False
    for _ in range(30):
        try:
            if v.health().get("ok"):
                healthy = True; break
        except VaultError:
            pass
        time.sleep(1)
    if not healthy:
        log("warning: vault not healthy (journalctl -u maluos-vault)")
        return {"healthy": False, "socket": v.socket_path}

    # 5. shared compartment and the listener token
    names = {c["name"] for c in v.compartments()}
    if "system" not in names:
        v.create_compartment("system", scope="org"); log("vault: created shared compartment system")
    imported = 0
    tok = "/var/lib/maluos/secrets/mc2dbd.token"
    if os.path.exists(tok):
        v.add("mc2dbd-token", open(tok).read().strip(), compartment="system", kind="token", provider="maludb-mc2dbd",
              env_var="MALUDB_MC2DBD_TOKEN", upsert=True); imported += 1
    log(f"vault healthy at {v.socket_path}; {imported} system secret(s) imported")
    return {"healthy": True, "socket": v.socket_path, "role": ROLE, "credential": CRED,
            "sealing": "tpm2+host" if has_tpm() else "host", "imported": imported}


def ensure_schema(psql, exists, qi, ql, db, tenant, role=ROLE, schema=SCHEMA):
    """Vault role, tenant-schema objects (as the tenant) and the role's grants. Idempotent."""
    if not exists(f"SELECT 1 FROM pg_roles WHERE rolname={ql(role)}"):
        psql(f"CREATE ROLE {qi(role)} LOGIN")
    r = subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", db,
                        "-c", f"SET ROLE {qi(tenant)}; SET search_path TO {qi(tenant)}, maludb_core, public;", "-f", schema],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"vault schema failed: {r.stderr.strip()[-400:]}")
    t, rl = qi(tenant), qi(role)
    psql(f"GRANT CONNECT ON DATABASE {qi(db)} TO {rl}", db)
    # The principal facades are owned by the extension owner (enable_memory_schema
    # is SECURITY DEFINER), so a superuser grants them; the tenant grants its own tables.
    psql(f"""GRANT USAGE ON SCHEMA maludb_core TO {rl};
             GRANT SELECT ON maludb_core."malu$principal", maludb_core."malu$principal_scope" TO {rl};
             GRANT USAGE ON SCHEMA {t} TO {rl};
             GRANT SELECT ON {t}.maludb_principal, {t}.maludb_principal_scope TO {rl};""", db)
    psql(f"""SET ROLE {t};
             GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(f'{t}.{x}' for x in TABLES)} TO {rl};
             GRANT SELECT, INSERT ON {t}.maluos_ledger TO {rl};
             GRANT EXECUTE ON FUNCTION {t}.maluos_record_episode(text, text, text, jsonb, text) TO {rl};
             GRANT USAGE, SELECT ON {', '.join(f'{t}.{s}' for s in SEQUENCES)} TO {rl};""", db)


def has_tpm():
    r = subprocess.run(["systemd-analyze", "has-tpm2"], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip().startswith("yes")
