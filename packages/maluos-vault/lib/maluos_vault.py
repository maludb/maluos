#!/usr/bin/python3
"""maluos-vault: the MaluOS secret vault.

One daemon on a Unix socket. The caller's identity is the kernel-reported
uid of the peer (SO_PEERCRED), mapped to a MaluDB principal (`user:<name>`
unless /etc/maluos/vault.yaml maps the user elsewhere). Secret metadata,
compartments, grants and the ledger live in the tenant schema; secret
values are AES-256-GCM blobs under /var/lib/maluos-vault/blobs, keyed from a
master key that systemd hands the service as an encrypted credential
(LoadCredentialEncrypted=, sealed to the TPM when the host has one).

Wire protocol: HTTP/1.1 + JSON over the socket (see docs/phase6-slice1-vault.md).
"""
import datetime, http.server, json, os, pwd, re, secrets, socket, socketserver, struct, subprocess, sys, threading, time, urllib.parse
import psycopg
from psycopg import sql as pgsql
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

VERSION = "0.4.0"
CONFIG = os.environ.get("MALUOS_VAULT_CONFIG", "/etc/maluos/vault.yaml")
DEFAULTS = {
    "socket": "/run/maluos/vault.sock",
    "hooks_dir": "/etc/maluos/alert-hooks.d",
    "database": "maludb", "tenant": "maluos",
    "pg_host": "/var/run/postgresql", "pg_user": None, "pg_role": None,
    "state_dir": "/var/lib/maluos-vault",
    "brokers": [],            # Linux users allowed to act on behalf of a principal (the gateway)
    "identities": {},         # linux user -> principal ref, when not user:<name>
    "default_lock_mode": "always_unlocked",
}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,119}$")
COMP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,119}$")
KINDS = ("api_key", "token", "password", "generic")
LEVELS = ("use", "read")
LOCK_MODES = ("always_unlocked", "manual", "login")


def log(msg):
    print(f"maluos-vault: {msg}", file=sys.stderr, flush=True)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------- config
class Config:
    def __init__(self):
        self._mtime = None; self.data = dict(DEFAULTS); self.reload()

    def reload(self):
        try:
            st = os.stat(CONFIG)
        except FileNotFoundError:
            self.data = dict(DEFAULTS); return
        if st.st_mtime == self._mtime:
            return
        import yaml
        with open(CONFIG) as f:
            user = yaml.safe_load(f) or {}
        d = dict(DEFAULTS); d.update({k: v for k, v in user.items() if v is not None})
        d["brokers"] = list(d.get("brokers") or []); d["identities"] = dict(d.get("identities") or {})
        self.data, self._mtime = d, st.st_mtime

    def __getitem__(self, k):
        self.reload(); return self.data[k]


CFG = Config()


# ---------------------------------------------------------------- blob store
class Store:
    MAGIC = b"MV1"

    def __init__(self, master, blob_dir):
        if len(master) < 32:
            raise RuntimeError("master key too short")
        self.master, self.dir = master, blob_dir
        os.makedirs(blob_dir, mode=0o700, exist_ok=True)

    def _key(self, salt, ref):
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"maluos-vault secret v1 " + ref.encode()).derive(self.master)

    def put(self, value: bytes) -> str:
        ref = secrets.token_hex(16)
        salt, nonce = os.urandom(16), os.urandom(12)
        ct = AESGCM(self._key(salt, ref)).encrypt(nonce, value, ref.encode())
        tmp = os.path.join(self.dir, ref + ".tmp")
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
            f.write(self.MAGIC + salt + nonce + ct)
        os.rename(tmp, os.path.join(self.dir, ref))
        return ref

    def get(self, ref: str) -> bytes:
        with open(os.path.join(self.dir, ref), "rb") as f:
            blob = f.read()
        if blob[:3] != self.MAGIC:
            raise RuntimeError("bad blob header")
        salt, nonce, ct = blob[3:19], blob[19:31], blob[31:]
        return AESGCM(self._key(salt, ref)).decrypt(nonce, ct, ref.encode())

    def delete(self, ref):
        if ref:
            try:
                os.remove(os.path.join(self.dir, ref))
            except FileNotFoundError:
                pass


def load_master():
    cdir = os.environ.get("CREDENTIALS_DIRECTORY")
    path = os.path.join(cdir, "maluos-vault.key") if cdir else None
    if not path or not os.path.exists(path):
        raise RuntimeError("no master key: expected $CREDENTIALS_DIRECTORY/maluos-vault.key (LoadCredentialEncrypted)")
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------- database
def connect():
    d = CFG.data
    kw = {"dbname": d["database"], "host": d["pg_host"], "autocommit": True,
          "options": f"-c search_path={d['tenant']},maludb_core,public"}
    if d.get("pg_user"):
        kw["user"] = d["pg_user"]
    conn = psycopg.connect(**kw)
    if d.get("pg_role"):
        conn.execute(pgsql.SQL("SET ROLE {}").format(pgsql.Identifier(d["pg_role"])))
    return conn


# ---------------------------------------------------------------- errors
class ApiError(Exception):
    def __init__(self, status, code, message, extra=None):
        super().__init__(message); self.status, self.code, self.message, self.extra = status, code, message, extra or {}


# ---------------------------------------------------------------- caller identity
class Caller:
    def __init__(self, pid, uid, gid):
        self.pid, self.uid, self.gid = pid, uid, gid
        try:
            self.user = pwd.getpwuid(uid).pw_name
        except KeyError:
            self.user = str(uid)
        self.operator = uid == 0
        self.broker = self.user in CFG["brokers"]
        self.process_ref = process_ref(pid)
        self.principal = None      # row dict or None (unenrolled)
        self.ref = CFG["identities"].get(self.user, f"user:{self.user}")
        self.broker_ref = None     # set when acting on behalf of someone

    def resolve(self, cur, on_behalf_of=None):
        if on_behalf_of:
            if not (self.operator or self.broker):
                raise ApiError(403, "not_a_broker", f"{self.user} may not act on behalf of another principal")
            self.broker_ref = self.ref
            self.ref = on_behalf_of
        cur.execute("SELECT principal_ref, principal_kind, home_scope, enabled FROM maludb_principal WHERE principal_ref=%s", (self.ref,))
        row = cur.fetchone()
        if row:
            self.principal = {"ref": row[0], "kind": row[1], "home_scope": row[2], "enabled": row[3]}
            if not row[3]:
                raise ApiError(403, "principal_disabled", f"principal {self.ref} is disabled")
        elif on_behalf_of:
            raise ApiError(404, "unknown_principal", f"no principal {on_behalf_of}")
        return self

    def scopes(self, cur):
        if not self.principal:
            return set()
        s = {self.principal["home_scope"]} if self.principal["home_scope"] else set()
        cur.execute("SELECT scope FROM maludb_principal_scope WHERE principal_ref=%s AND revoked_at IS NULL", (self.ref,))
        s.update(r[0] for r in cur.fetchall())
        return s

    def as_dict(self):
        return {"uid": self.uid, "user": self.user, "pid": self.pid, "process": self.process_ref,
                "principal": self.ref if self.principal else None, "enrolled": bool(self.principal),
                "kind": self.principal["kind"] if self.principal else None,
                "operator": self.operator, "broker": self.broker, "broker_ref": self.broker_ref}


def process_ref(pid):
    comm = unit = None
    try:
        with open(f"/proc/{pid}/comm") as f:
            comm = f.read().strip()
        with open(f"/proc/{pid}/cgroup") as f:
            for line in f:
                path = line.strip().split(":", 2)[-1]
                parts = [p for p in path.split("/") if p]
                if parts:
                    unit = parts[-1]
    except OSError:
        pass
    if comm and unit:
        return f"{comm}@{unit}"
    return comm or unit or None


# ---------------------------------------------------------------- re-authentication (Phase 12 slice 9)
REAUTH_ACTION = os.environ.get("MALUOS_VAULT_REAUTH_ACTION", "com.maluos.vault.reveal")   # the test harness names its own


def polkit_check(pid, action=REAUTH_ACTION, timeout=180):
    """(ok, why): ask polkit whether the calling process may do ACTION, letting the person's session
    agent (GNOME Shell's) ask for their password. The action is auth_self and keeps nothing, so every
    reveal asks. pkcheck talks to polkitd over the system bus; the subject is pid + start time, so a
    reused pid cannot pass. Without polkit on the host (servers), nothing is authorised."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            start = f.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return False, "the calling process is gone"
    if not os.path.exists("/usr/bin/pkcheck"):
        return False, "polkit is not installed on this host"
    try:
        r = subprocess.run(["/usr/bin/pkcheck", "--action-id", action, "--process", f"{pid},{start}", "--allow-user-interaction"],
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, "no answer from the authentication prompt"
    except OSError as e:
        return False, f"pkcheck: {e.__class__.__name__}"
    if r.returncode == 0:
        return True, "polkit"
    why = ((r.stderr or r.stdout).strip().splitlines() or ["not authorised"])[-1][:160]
    return False, why


_has_cause = None


def request_has_cause():
    """Whether maluos_secret_request has the `cause` column (slice 9); hosts provisioned before it keep working without it."""
    global _has_cause
    if _has_cause is None:
        try:
            with connect() as conn:
                row = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name='maluos_secret_request' AND column_name='cause'").fetchone()
            _has_cause = bool(row)
            if not _has_cause:
                log("maluos_secret_request has no `cause` column (schema from before 0.4.0): requests carry no cause until the vault component is re-applied")
        except Exception as e:
            log(f"cause column check: {e.__class__.__name__}"); return False
    return _has_cause


# ---------------------------------------------------------------- vault logic
class Vault:
    def __init__(self, store):
        self.store = store

    # -- ledger
    def ledger(self, cur, event, caller, status, reason=None, secret=None, comp=None, level=None, purpose=None, detail=None):
        cur.execute("""INSERT INTO maluos_ledger (event, principal_ref, linux_user, linux_uid, process_ref, broker_ref,
                         compartment, secret_name, secret_id, grant_level, purpose, status, reason, detail)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (event, caller.ref if (caller.principal or caller.broker_ref) else None, caller.user, caller.uid,
                     caller.process_ref, caller.broker_ref,
                     comp["name"] if comp else None, secret["name"] if secret else None,
                     secret["secret_id"] if secret else None, level, purpose, status, reason,
                     json.dumps(detail) if detail is not None else None))

    def deny(self, cur, event, caller, code, message, status=403, extra=None, **kw):
        self.ledger(cur, event, caller, "denied", reason=code, **kw)
        raise ApiError(status, code, message, extra)

    def reauth(self, cur, caller, purpose=None):
        """Slice 9: ask polkit for the person's password on behalf of a client that is about to do something the
        vault does not see (the Credential Manager's backup runs `maluctl secret export|import` in a terminal).
        Ledgered as vault.reauth, ok or denied. The windows cannot ask polkit themselves: only root or the
        action's owner (this daemon) may ask with user interaction."""
        okk, why = polkit_check(caller.pid)
        if not okk:
            self.deny(cur, "vault.reauth", caller, "reauth_required", f"re-authentication refused: {why}", status=401, purpose=purpose,
                      detail={"reauth": "polkit", "refused": why})
        self.ledger(cur, "vault.reauth", caller, "ok", purpose=purpose, detail={"reauth": "polkit"})
        return {"reauth": "polkit", "purpose": purpose}

    # -- compartments
    def compartment(self, cur, name, create=False, caller=None):
        cur.execute("SELECT compartment_id, name, owner_principal_ref, scope, lock_mode, locked, created_at FROM maluos_compartment WHERE name=%s", (name,))
        r = cur.fetchone()
        if r:
            return self._comp(r)
        if create and caller and caller.principal and name == caller.ref:
            cur.execute("""INSERT INTO maluos_compartment (name, owner_principal_ref, lock_mode) VALUES (%s,%s,%s)
                           RETURNING compartment_id, name, owner_principal_ref, scope, lock_mode, locked, created_at""",
                        (name, caller.ref, CFG["default_lock_mode"]))
            return self._comp(cur.fetchone())
        return None

    @staticmethod
    def _comp(r):
        return {"compartment_id": r[0], "name": r[1], "owner": r[2], "scope": r[3], "lock_mode": r[4], "locked": r[5],
                "created_at": r[6].isoformat() if r[6] else None, "shared": r[2] is None}

    def may_manage(self, caller, comp):
        return caller.operator or (caller.principal is not None and comp["owner"] == caller.ref)

    def visible_compartments(self, cur, caller):
        cur.execute("SELECT compartment_id, name, owner_principal_ref, scope, lock_mode, locked, created_at FROM maluos_compartment ORDER BY owner_principal_ref NULLS FIRST, name")
        out = []
        for r in cur.fetchall():
            c = self._comp(r)
            if caller.operator or c["shared"] or c["owner"] == caller.ref:
                out.append(c)
        return out

    # -- secrets
    SECRET_COLS = "s.secret_id, s.compartment_id, s.name, s.kind, s.provider, s.env_var, s.cred_ref, s.previous_cred_ref, s.grace_until, s.created_by, s.created_at, s.rotated_at, s.expires_at, c.name"

    def _secret(self, r):
        return {"secret_id": r[0], "compartment_id": r[1], "name": r[2], "kind": r[3], "provider": r[4], "env_var": r[5],
                "cred_ref": r[6], "previous_cred_ref": r[7], "grace_until": r[8].isoformat() if r[8] else None,
                "created_by": r[9], "created_at": r[10].isoformat() if r[10] else None,
                "rotated_at": r[11].isoformat() if r[11] else None, "expires_at": r[12].isoformat() if r[12] else None,
                "compartment": r[13], "ref": f"{r[13]}/{r[2]}"}

    def public(self, s):
        return {k: v for k, v in s.items() if k not in ("cred_ref", "previous_cred_ref")}

    def secrets_in(self, cur, comp_id):
        cur.execute(f"SELECT {self.SECRET_COLS} FROM maluos_secret s JOIN maluos_compartment c USING (compartment_id) WHERE s.compartment_id=%s ORDER BY s.name", (comp_id,))
        return [self._secret(r) for r in cur.fetchall()]

    def live_grants(self, cur, secret_id):
        cur.execute("""SELECT grant_id, grantee_kind, grantee_ref, level, budget, expires_at, granted_by, granted_at
                       FROM maluos_secret_grant WHERE secret_id=%s AND revoked_at IS NULL
                         AND (expires_at IS NULL OR expires_at > now()) ORDER BY grant_id""", (secret_id,))
        return [{"grant_id": r[0], "grantee_kind": r[1], "grantee_ref": r[2], "level": r[3], "budget": r[4],
                 "expires_at": r[5].isoformat() if r[5] else None, "granted_by": r[6],
                 "granted_at": r[7].isoformat() if r[7] else None} for r in cur.fetchall()]

    def access(self, cur, caller, secret, comp):
        """(level, why) the caller holds on the secret, or (None, None)."""
        if caller.operator:
            return "read", "operator"
        if caller.principal and comp["owner"] == caller.ref:
            return "read", "owner"
        if not caller.principal:
            return None, None
        best, why = None, None
        scopes = None
        for g in self.live_grants(cur, secret["secret_id"]):
            hit = False
            if g["grantee_kind"] == "principal" and g["grantee_ref"] == caller.ref:
                hit = True
            elif g["grantee_kind"] == "scope":
                if scopes is None:
                    scopes = caller.scopes(cur)
                hit = g["grantee_ref"] in scopes
            if hit and (best is None or (g["level"] == "read" and best == "use")):
                best, why = g["level"], f"grant:{g['grantee_kind']}:{g['grantee_ref']}"
        if best is None and comp["owner"]:
            # FR-15: a user may delegate their keys to an agent, use only, with expiry and budget
            cur.execute("""SELECT delegation_id FROM maluos_delegation WHERE from_principal_ref=%s AND to_principal_ref=%s AND revoked_at IS NULL
                             AND (expires_at IS NULL OR expires_at > now()) AND (secret_id IS NULL OR secret_id=%s) LIMIT 1""",
                        (comp["owner"], caller.ref, secret["secret_id"]))
            if cur.fetchone():
                best, why = "use", f"delegation:{comp['owner']}"
        return best, why

    # -- delegations (FR-15)
    def delegations(self, cur, caller):
        cur.execute("""SELECT d.delegation_id, d.from_principal_ref, d.to_principal_ref, d.secret_id, s.name AS secret_name, c.name AS compartment,
                              d.budget, d.expires_at, d.created_at, d.revoked_at
                         FROM maluos_delegation d LEFT JOIN maluos_secret s ON s.secret_id=d.secret_id LEFT JOIN maluos_compartment c ON c.compartment_id=s.compartment_id
                        WHERE d.revoked_at IS NULL ORDER BY d.delegation_id""")
        rows = []
        for r in cur.fetchall():
            if caller.operator or r[1] == caller.ref or r[2] == caller.ref:
                rows.append({"delegation_id": r[0], "from": r[1], "to": r[2], "secret": f"{r[5]}/{r[4]}" if r[3] else None, "budget": r[6],
                             "expires_at": r[7].isoformat() if r[7] else None, "created_at": r[8].isoformat() if r[8] else None})
        return rows

    def delegate(self, cur, caller, body):
        frm = body.get("from") or caller.ref
        to = str(body.get("to") or "")
        if not to:
            raise ApiError(400, "bad_request", "to (a principal) is required")
        if not caller.operator and (not caller.principal or frm != caller.ref):
            self.deny(cur, "delegation.add", caller, "forbidden", "you may only delegate your own secrets")
        cur.execute("SELECT 1 FROM maludb_principal WHERE principal_ref=%s", (to,))
        if not cur.fetchone():
            raise ApiError(404, "unknown_principal", f"no principal {to}")
        sid = None
        if body.get("secret"):
            secret, comp = self.resolve(cur, caller, body["secret"])
            if comp["owner"] != frm:
                raise ApiError(403, "forbidden", f"{secret['ref']} is not in {frm}'s compartment")
            sid = secret["secret_id"]
        expires = parse_ts(body.get("expires_at"))
        cur.execute("UPDATE maluos_delegation SET revoked_at=now() WHERE from_principal_ref=%s AND to_principal_ref=%s AND secret_id IS NOT DISTINCT FROM %s AND revoked_at IS NULL", (frm, to, sid))
        cur.execute("INSERT INTO maluos_delegation (from_principal_ref, to_principal_ref, secret_id, budget, expires_at) VALUES (%s,%s,%s,%s,%s) RETURNING delegation_id",
                    (frm, to, sid, json.dumps(body["budget"]) if body.get("budget") else None, expires))
        did = cur.fetchone()[0]
        self.ledger(cur, "delegation.add", caller, "ok", detail={"from": frm, "to": to, "secret_id": sid, "expires_at": expires.isoformat() if expires else None, "budget": body.get("budget")})
        return {"delegation_id": did, "from": frm, "to": to, "secret_id": sid}

    def undelegate(self, cur, caller, body):
        frm = body.get("from") or caller.ref
        to = str(body.get("to") or "")
        if not caller.operator and (not caller.principal or frm != caller.ref):
            self.deny(cur, "delegation.revoke", caller, "forbidden", "you may only revoke your own delegations")
        sid = None
        if body.get("secret"):
            secret, _ = self.resolve(cur, caller, body["secret"]); sid = secret["secret_id"]
        cur.execute("UPDATE maluos_delegation SET revoked_at=now() WHERE from_principal_ref=%s AND to_principal_ref=%s AND revoked_at IS NULL" + ("" if sid is None else " AND secret_id=%s"),
                    (frm, to) if sid is None else (frm, to, sid))
        n = cur.rowcount
        self.ledger(cur, "delegation.revoke", caller, "ok" if n else "noop", detail={"from": frm, "to": to, "secret_id": sid})
        return {"revoked": n}

    # -- export / import (FR-18): operators only; every exported value is a logged read
    def export(self, cur, caller, compartment=None):
        if not caller.operator:
            self.deny(cur, "vault.export", caller, "forbidden", "operators only")
        comps = [c for c in self.visible_compartments(cur, caller) if not compartment or c["name"] == compartment]
        out = {"maluos_vault_export": 1, "exported_at": utcnow().isoformat(), "compartments": [], "secrets": [], "grants": [], "delegations": []}
        for c in comps:
            out["compartments"].append({k: c[k] for k in ("name", "owner", "scope", "lock_mode")})
            for sec in self.secrets_in(cur, c["compartment_id"]):
                val = self.store.get(sec["cred_ref"]).decode()
                self.ledger(cur, "secret.read", caller, "ok", reason="export", secret=sec, comp=c, level="read", purpose="export")
                out["secrets"].append({"compartment": c["name"], "name": sec["name"], "kind": sec["kind"], "provider": sec["provider"], "env_var": sec["env_var"],
                                       "expires_at": sec["expires_at"], "value": val})
                for g in self.live_grants(cur, sec["secret_id"]):
                    out["grants"].append({"secret": f"{c['name']}/{sec['name']}", "grantee_kind": g["grantee_kind"], "grantee_ref": g["grantee_ref"], "level": g["level"], "expires_at": g["expires_at"]})
        cur.execute("SELECT from_principal_ref, to_principal_ref, s.name, c.name, d.budget, d.expires_at FROM maluos_delegation d LEFT JOIN maluos_secret s ON s.secret_id=d.secret_id LEFT JOIN maluos_compartment c ON c.compartment_id=s.compartment_id WHERE d.revoked_at IS NULL")
        for r in cur.fetchall():
            out["delegations"].append({"from": r[0], "to": r[1], "secret": f"{r[3]}/{r[2]}" if r[2] else None, "budget": r[4], "expires_at": r[5].isoformat() if r[5] else None})
        self.ledger(cur, "vault.export", caller, "ok", detail={"compartments": len(out["compartments"]), "secrets": len(out["secrets"])})
        return out

    def import_bundle(self, cur, caller, bundle):
        if not caller.operator:
            self.deny(cur, "vault.import", caller, "forbidden", "operators only")
        if not isinstance(bundle, dict) or bundle.get("maluos_vault_export") != 1:
            raise ApiError(400, "bad_bundle", "not a MaluOS vault export")
        n = {"compartments": 0, "secrets": 0, "grants": 0, "delegations": 0}
        for c in bundle.get("compartments") or []:
            if not self.compartment(cur, c["name"]):
                cur.execute("INSERT INTO maluos_compartment (name, owner_principal_ref, scope, lock_mode) VALUES (%s,%s,%s,%s)",
                            (c["name"], c.get("owner"), c.get("scope"), c.get("lock_mode") or CFG["default_lock_mode"]))
                n["compartments"] += 1
        for sec in bundle.get("secrets") or []:
            self.add(cur, caller, {"name": sec["name"], "compartment": sec["compartment"], "kind": sec.get("kind"), "provider": sec.get("provider"),
                                   "env_var": sec.get("env_var"), "expires_at": sec.get("expires_at"), "value": sec["value"], "upsert": True})
            n["secrets"] += 1
        for g in bundle.get("grants") or []:
            secret, comp = self.resolve(cur, caller, g["secret"])
            self.grant(cur, caller, secret, comp, {"grantee_kind": g["grantee_kind"], "grantee_ref": g["grantee_ref"], "level": g["level"], "expires_at": g.get("expires_at")})
            n["grants"] += 1
        for d in bundle.get("delegations") or []:
            self.delegate(cur, caller, {"from": d["from"], "to": d["to"], "secret": d.get("secret"), "budget": d.get("budget"), "expires_at": d.get("expires_at")})
            n["delegations"] += 1
        self.ledger(cur, "vault.import", caller, "ok", detail=n)
        return n

    # -- alerts (FR-44): journal, ledger, memory episode, hooks
    def alert(self, cur, kind, title, detail):
        log(f"ALERT {kind}: {title}")
        cur.execute("INSERT INTO maluos_ledger (event, status, reason, detail, principal_ref) VALUES (%s, 'ok', %s, %s, %s)",
                    (f"alert.{kind}", title[:200], json.dumps(detail), detail.get("principal")))
        try:
            cur.execute("SELECT maluos_record_episode('maluos.alert', %s, %s, %s, 'internal')", (title[:200], json.dumps(detail)[:1000], json.dumps(dict(detail, kind=kind))))
        except Exception as e:
            log(f"alert episode not recorded: {e.__class__.__name__}: {str(e)[:120]}")
        run_hooks(CFG["hooks_dir"], {"source": "maluos-vault", "kind": kind, "title": title, "detail": detail, "ts": utcnow().isoformat()})

    def resolve(self, cur, caller, ref):
        """'compartment/name' or bare 'name' -> (secret, compartment). FR-13 order:
        the caller's own compartment, then compartments it holds grants in."""
        if "/" in ref:
            cname, name = ref.split("/", 1)
            comp = self.compartment(cur, cname)
            if not comp:
                raise ApiError(404, "no_compartment", f"no compartment {cname}")
            cur.execute(f"SELECT {self.SECRET_COLS} FROM maluos_secret s JOIN maluos_compartment c USING (compartment_id) WHERE s.compartment_id=%s AND s.name=%s", (comp["compartment_id"], name))
            r = cur.fetchone()
            if not r:
                raise ApiError(404, "no_secret", f"no secret {ref}")
            return self._secret(r), comp
        cur.execute(f"SELECT {self.SECRET_COLS} FROM maluos_secret s JOIN maluos_compartment c USING (compartment_id) WHERE s.name=%s ORDER BY (c.owner_principal_ref = %s) DESC NULLS LAST, c.name", (ref, caller.ref))
        rows = [self._secret(r) for r in cur.fetchall()]
        if not rows:
            raise ApiError(404, "no_secret", f"no secret named {ref}")
        own = [s for s in rows if s["compartment"] == caller.ref]
        if own:
            return own[0], self.compartment(cur, own[0]["compartment"])
        reachable = []
        for s in rows:
            comp = self.compartment(cur, s["compartment"])
            if self.access(cur, caller, s, comp)[0]:
                reachable.append((s, comp))
        if len(reachable) == 1:
            return reachable[0]
        if not reachable:
            raise ApiError(404, "no_secret", f"no secret named {ref} that you may use")
        raise ApiError(409, "ambiguous", f"{ref} exists in several compartments: " + ", ".join(s["ref"] for s, _ in reachable))

    # -- operations
    def add(self, cur, caller, body):
        name = str(body.get("name") or "")
        if not NAME_RE.match(name):
            raise ApiError(400, "bad_name", "secret names: letters, digits, _ . @ -")
        cname = body.get("compartment") or caller.ref
        if cname == caller.ref and not caller.principal:
            self.deny(cur, "secret.add", caller, "not_enrolled", f"{caller.user} is not an enrolled principal (maluctl principal add user:{caller.user} --kind human)")
        comp = self.compartment(cur, cname, create=True, caller=caller)
        if not comp:
            raise ApiError(404, "no_compartment", f"no compartment {cname}")
        if not self.may_manage(caller, comp):
            self.deny(cur, "secret.add", caller, "forbidden", f"only the owner or an operator may add to {cname}", comp=comp)
        kind = body.get("kind") or "api_key"
        if kind not in KINDS:
            raise ApiError(400, "bad_kind", f"kind must be one of {', '.join(KINDS)}")
        value = body.get("value")
        if not isinstance(value, str) or value == "":
            raise ApiError(400, "no_value", "value is required")
        expires = parse_ts(body.get("expires_at"))
        cur.execute("SELECT secret_id FROM maluos_secret WHERE compartment_id=%s AND name=%s", (comp["compartment_id"], name))
        if cur.fetchone():
            if body.get("upsert"):
                s, _ = self.resolve(cur, caller, f"{cname}/{name}")
                return self.rotate(cur, caller, s, comp, value, body.get("grace_hours", 0), meta=body)
            raise ApiError(409, "exists", f"{cname}/{name} exists (use rotate)")
        ref = self.store.put(value.encode())
        cur.execute("""INSERT INTO maluos_secret (compartment_id, name, kind, provider, env_var, cred_ref, created_by, expires_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING secret_id""",
                    (comp["compartment_id"], name, kind, body.get("provider"), body.get("env_var"), ref, caller.ref, expires))
        sid = cur.fetchone()[0]
        s = {"secret_id": sid, "name": name}
        self.ledger(cur, "secret.add", caller, "ok", secret=s, comp=comp, detail={"kind": kind, "provider": body.get("provider")})
        secret, _ = self.resolve(cur, caller, f"{cname}/{name}")
        return self.public(secret)

    def value(self, cur, caller, secret, comp, mode, purpose, previous=False, cause=None, reauth=None):
        event = "secret.use" if mode == "use" else "secret.read"
        if mode == "use" and not (caller.broker_ref or caller.operator or caller.broker):
            # `use` is the broker's verb: the value goes to the gateway, never to the caller (FR-14).
            self.deny(cur, event, caller, "use_requires_broker", "mode=use is only for brokers; request mode=read", secret=secret, comp=comp)
        level, why = self.access(cur, caller, secret, comp)
        need = "use" if mode == "use" else "read"
        if level is None or (need == "read" and level != "read"):
            # The refusal itself asks the owner: a pending request the owner's desk can answer (slice 3).
            req = self.file_request(cur, caller, secret, comp, need, purpose, cause=cause)
            msg = f"no {need} access to {secret['ref']}" + (f"; grant request #{req} is pending for its owner" if req else "")
            self.deny(cur, event, caller, "forbidden", msg, secret=secret, comp=comp, level=level, extra={"request_id": req} if req else None)
        if comp["locked"]:
            self.deny(cur, event, caller, "locked", f"compartment {comp['name']} is locked", status=423, secret=secret, comp=comp, level=level)
        if secret["expires_at"] and parse_ts(secret["expires_at"]) <= utcnow():
            self.deny(cur, event, caller, "expired", f"{secret['ref']} expired at {secret['expires_at']}", status=410, secret=secret, comp=comp, level=level)
        detail = {}
        if reauth:
            # Slice 9: a reveal from the desk asks the person for their password first (polkit auth_self);
            # the ledger row says so. Only `polkit` exists; anything else is refused.
            if reauth != "polkit":
                raise ApiError(400, "bad_reauth", "reauth must be polkit")
            okk, why = polkit_check(caller.pid)
            if not okk:
                self.deny(cur, event, caller, "reauth_required", f"re-authentication refused: {why}", status=401, secret=secret, comp=comp, level=level,
                          purpose=purpose, detail={"reauth": "polkit", "refused": why})
            detail["reauth"] = "polkit"
        ref = secret["cred_ref"]
        if previous:
            if not secret["previous_cred_ref"] or not secret["grace_until"] or parse_ts(secret["grace_until"]) <= utcnow():
                self.deny(cur, event, caller, "no_previous", "no previous value within its grace window", status=404, secret=secret, comp=comp, level=level)
            ref = secret["previous_cred_ref"]
        try:
            val = self.store.get(ref).decode()
        except Exception as e:
            self.ledger(cur, event, caller, "error", reason="store_error", secret=secret, comp=comp, level=level, purpose=purpose)
            raise ApiError(500, "store_error", f"cannot open secret value: {e.__class__.__name__}")
        if previous:
            detail["previous"] = True
        self.ledger(cur, event, caller, "ok", reason=why, secret=secret, comp=comp, level=level, purpose=purpose, detail=detail or None)
        if previous:
            self.alert(cur, "retired_key", f"retired value of {secret['ref']} presented by {caller.ref or caller.user}",
                       {"principal": caller.ref, "user": caller.user, "process": caller.process_ref, "secret": secret["ref"], "grace_until": secret["grace_until"]})
        return {"ref": secret["ref"], "name": secret["name"], "kind": secret["kind"], "provider": secret["provider"],
                "env_var": secret["env_var"], "value": val, "level": level, "via": why}

    def rotate(self, cur, caller, secret, comp, value, grace_hours=0, meta=None):
        if not self.may_manage(caller, comp):
            self.deny(cur, "secret.rotate", caller, "forbidden", f"only the owner or an operator may rotate {secret['ref']}", secret=secret, comp=comp)
        if not isinstance(value, str) or value == "":
            raise ApiError(400, "no_value", "value is required")
        detail = {}
        if meta and meta.get("reauth"):
            if meta["reauth"] != "polkit":
                raise ApiError(400, "bad_reauth", "reauth must be polkit")
            okk, why = polkit_check(caller.pid)
            if not okk:
                self.deny(cur, "secret.rotate", caller, "reauth_required", f"re-authentication refused: {why}", status=401, secret=secret, comp=comp,
                          detail={"reauth": "polkit", "refused": why})
            detail["reauth"] = "polkit"
        try:
            same = self.store.get(secret["cred_ref"]).decode() == value
        except Exception:
            same = False
        if same:
            return self.public(secret)
        new_ref = self.store.put(value.encode())
        grace = float(grace_hours or 0)
        self.store.delete(secret["previous_cred_ref"])
        prev, until = (secret["cred_ref"], utcnow() + datetime.timedelta(hours=grace)) if grace > 0 else (None, None)
        if not prev:
            self.store.delete(secret["cred_ref"])
        sets, args = ["cred_ref=%s", "previous_cred_ref=%s", "grace_until=%s", "rotated_at=now()"], [new_ref, prev, until]
        for k in ("kind", "provider", "env_var"):
            if meta and meta.get(k) is not None:
                sets.append(f"{k}=%s"); args.append(meta[k])
        if meta and "expires_at" in meta:
            sets.append("expires_at=%s"); args.append(parse_ts(meta.get("expires_at")))
        args.append(secret["secret_id"])
        cur.execute(f"UPDATE maluos_secret SET {', '.join(sets)} WHERE secret_id=%s", args)
        self.ledger(cur, "secret.rotate", caller, "ok", secret=secret, comp=comp, detail=dict(detail, grace_hours=grace))
        s, _ = self.resolve(cur, caller, secret["ref"])
        return self.public(s)

    def delete(self, cur, caller, secret, comp):
        if not self.may_manage(caller, comp):
            self.deny(cur, "secret.delete", caller, "forbidden", f"only the owner or an operator may delete {secret['ref']}", secret=secret, comp=comp)
        cur.execute("DELETE FROM maluos_secret WHERE secret_id=%s", (secret["secret_id"],))
        self.store.delete(secret["cred_ref"]); self.store.delete(secret["previous_cred_ref"])
        self.ledger(cur, "secret.delete", caller, "ok", secret=secret, comp=comp)
        return {"deleted": secret["ref"]}

    def grant(self, cur, caller, secret, comp, body):
        if not self.may_manage(caller, comp):
            self.deny(cur, "grant.add", caller, "forbidden", f"only the owner or an operator may grant {secret['ref']}", secret=secret, comp=comp)
        gk, gr, level = body.get("grantee_kind"), str(body.get("grantee_ref") or ""), body.get("level") or "use"
        if gk not in ("principal", "scope") or not gr:
            raise ApiError(400, "bad_grantee", "grantee_kind principal|scope and grantee_ref are required")
        if level not in LEVELS:
            raise ApiError(400, "bad_level", "level must be use or read")
        if gk == "principal":
            cur.execute("SELECT 1 FROM maludb_principal WHERE principal_ref=%s", (gr,))
            if not cur.fetchone():
                raise ApiError(404, "unknown_principal", f"no principal {gr}")
        expires = parse_ts(body.get("expires_at"))
        cur.execute("UPDATE maluos_secret_grant SET revoked_at=now(), revoked_by=%s WHERE secret_id=%s AND grantee_kind=%s AND grantee_ref=%s AND revoked_at IS NULL",
                    (caller.ref, secret["secret_id"], gk, gr))
        cur.execute("""INSERT INTO maluos_secret_grant (secret_id, grantee_kind, grantee_ref, level, budget, expires_at, granted_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING grant_id""",
                    (secret["secret_id"], gk, gr, level, json.dumps(body["budget"]) if body.get("budget") else None, expires, caller.ref))
        gid = cur.fetchone()[0]
        self.ledger(cur, "grant.add", caller, "ok", secret=secret, comp=comp, level=level,
                    detail={"grantee_kind": gk, "grantee_ref": gr, "expires_at": expires.isoformat() if expires else None})
        return {"grant_id": gid, "secret": secret["ref"], "grantee_kind": gk, "grantee_ref": gr, "level": level}

    def revoke(self, cur, caller, secret, comp, body):
        if not self.may_manage(caller, comp):
            self.deny(cur, "grant.revoke", caller, "forbidden", f"only the owner or an operator may revoke on {secret['ref']}", secret=secret, comp=comp)
        gk, gr = body.get("grantee_kind"), str(body.get("grantee_ref") or "")
        cur.execute("UPDATE maluos_secret_grant SET revoked_at=now(), revoked_by=%s WHERE secret_id=%s AND grantee_kind=%s AND grantee_ref=%s AND revoked_at IS NULL",
                    (caller.ref, secret["secret_id"], gk, gr))
        n = cur.rowcount
        self.ledger(cur, "grant.revoke", caller, "ok" if n else "noop", secret=secret, comp=comp, detail={"grantee_kind": gk, "grantee_ref": gr})
        return {"revoked": n}

    # -- grant requests (Phase 12 slice 3): a refused principal asks, the owner's desk answers
    def file_request(self, cur, caller, secret, comp, level="use", purpose=None, explicit=False, cause=None):
        """Create or bump the pending request of caller for secret. None when it makes no sense:
        unenrolled callers, operators, the owner asking for their own secret. CAUSE (slice 9) is what
        the broker was doing when it was refused: the gateway's model call ({call, model, backend,
        class, task, ts}), kept on the row so the owner's desk can say what asked."""
        if not caller.principal or caller.operator or comp["owner"] == caller.ref:
            return None
        if level not in LEVELS:
            raise ApiError(400, "bad_level", "level must be use or read")
        if not explicit:
            # A refusal does not nag: a request the owner denied in the last day stays denied.
            cur.execute("""SELECT 1 FROM maluos_secret_request WHERE secret_id=%s AND requester_principal_ref=%s AND status='denied'
                             AND decided_at > now() - interval '1 day' LIMIT 1""", (secret["secret_id"], caller.ref))
            if cur.fetchone():
                return None
        if isinstance(cause, dict) and request_has_cause():
            cause = {k: cause[k] for k in ("call", "model", "backend", "class", "task", "ts", "kind", "title") if cause.get(k) is not None}
            cur.execute("""INSERT INTO maluos_secret_request (secret_id, requester_principal_ref, owner_principal_ref, level, purpose, process_ref, cause)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (secret_id, requester_principal_ref) WHERE status = 'pending'
                           DO UPDATE SET last_asked_at = now(), asked_count = maluos_secret_request.asked_count + 1,
                                         purpose = coalesce(EXCLUDED.purpose, maluos_secret_request.purpose),
                                         level = CASE WHEN EXCLUDED.level = 'read' THEN 'read' ELSE maluos_secret_request.level END,
                                         cause = coalesce(EXCLUDED.cause, maluos_secret_request.cause)
                           RETURNING request_id, asked_count""",
                        (secret["secret_id"], caller.ref, comp["owner"], level, purpose, caller.process_ref, json.dumps(cause)))
        else:
            cur.execute("""INSERT INTO maluos_secret_request (secret_id, requester_principal_ref, owner_principal_ref, level, purpose, process_ref)
                           VALUES (%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (secret_id, requester_principal_ref) WHERE status = 'pending'
                           DO UPDATE SET last_asked_at = now(), asked_count = maluos_secret_request.asked_count + 1,
                                         purpose = coalesce(EXCLUDED.purpose, maluos_secret_request.purpose),
                                         level = CASE WHEN EXCLUDED.level = 'read' THEN 'read' ELSE maluos_secret_request.level END
                           RETURNING request_id, asked_count""",
                        (secret["secret_id"], caller.ref, comp["owner"], level, purpose, caller.process_ref))
        rid, n = cur.fetchone()
        self.ledger(cur, "request.add", caller, "ok" if n == 1 else "noop", reason="asked" if explicit else "refused", secret=secret, comp=comp, level=level,
                    purpose=purpose, detail={"request_id": rid, "asked_count": n, "owner": comp["owner"], "cause": cause if isinstance(cause, dict) else None})
        return rid

    REQ_COLS = """r.request_id, r.secret_id, s.name, c.name, r.requester_principal_ref, r.owner_principal_ref, r.level, r.purpose, r.process_ref,
                  r.status, r.created_at, r.last_asked_at, r.asked_count, r.decided_at, r.decided_by, r.grant_id, r.expires_at, p.principal_kind"""

    def req_cols(self):
        return self.REQ_COLS + (", r.cause" if request_has_cause() else ", NULL")

    def _request(self, r):
        return {"request_id": r[0], "secret_id": r[1], "secret": f"{r[3]}/{r[2]}", "compartment": r[3], "requester": r[4], "owner": r[5], "level": r[6],
                "purpose": r[7], "process": r[8], "status": r[9], "created_at": r[10].isoformat() if r[10] else None,
                "last_asked_at": r[11].isoformat() if r[11] else None, "asked_count": r[12], "decided_at": r[13].isoformat() if r[13] else None,
                "decided_by": r[14], "grant_id": r[15], "expires_at": r[16].isoformat() if r[16] else None, "requester_kind": r[17],
                "cause": r[18] if len(r) > 18 and isinstance(r[18], dict) else None}

    def requests(self, cur, caller, status="pending"):
        """What the caller may see: operators everything; otherwise requests they made or must decide."""
        where, args = [], []
        if status and status != "all":
            where.append("r.status=%s"); args.append(status)
        if not caller.operator:
            if not caller.principal:
                return []
            where.append("(r.requester_principal_ref=%s OR r.owner_principal_ref=%s)"); args += [caller.ref, caller.ref]
        cur.execute(f"""SELECT {self.req_cols()} FROM maluos_secret_request r JOIN maluos_secret s USING (secret_id)
                        JOIN maluos_compartment c ON c.compartment_id = s.compartment_id
                        LEFT JOIN maludb_principal p ON p.principal_ref = r.requester_principal_ref
                        {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY r.request_id DESC LIMIT 200""", args)
        return [self._request(r) for r in cur.fetchall()]

    def request_by_id(self, cur, rid):
        cur.execute(f"""SELECT {self.req_cols()} FROM maluos_secret_request r JOIN maluos_secret s USING (secret_id)
                        JOIN maluos_compartment c ON c.compartment_id = s.compartment_id
                        LEFT JOIN maludb_principal p ON p.principal_ref = r.requester_principal_ref WHERE r.request_id=%s""", (rid,))
        r = cur.fetchone()
        if not r:
            raise ApiError(404, "no_request", f"no request #{rid}")
        return self._request(r)

    def decide_request(self, cur, caller, rid, approve, body):
        req = self.request_by_id(cur, rid)
        secret, comp = self.resolve(cur, caller, req["secret"])
        if not self.may_manage(caller, comp):
            self.deny(cur, "request.approve" if approve else "request.deny", caller, "forbidden", f"only the owner of {req['secret']} or an operator decides request #{rid}", secret=secret, comp=comp)
        if req["status"] != "pending":
            raise ApiError(409, "decided", f"request #{rid} is already {req['status']}")
        grant = None
        if approve:
            level = body.get("level") or req["level"]
            grant = self.grant(cur, caller, secret, comp, {"grantee_kind": "principal", "grantee_ref": req["requester"], "level": level,
                                                          "expires_at": body.get("expires_at"), "budget": body.get("budget")})
        cur.execute("UPDATE maluos_secret_request SET status=%s, decided_at=now(), decided_by=%s, grant_id=%s, expires_at=%s WHERE request_id=%s",
                    ("approved" if approve else "denied", caller.ref, grant["grant_id"] if grant else None, parse_ts(body.get("expires_at")) if approve else None, rid))
        self.ledger(cur, "request.approve" if approve else "request.deny", caller, "ok", secret=secret, comp=comp, level=grant["level"] if grant else None,
                    detail={"request_id": rid, "requester": req["requester"], "grant_id": grant["grant_id"] if grant else None, "reason": body.get("reason")})
        return self.request_by_id(cur, rid)

    def set_lock(self, cur, caller, comp, locked):
        if not self.may_manage(caller, comp):
            self.deny(cur, "compartment.lock", caller, "forbidden", f"only the owner or an operator may lock {comp['name']}", comp=comp)
        cur.execute("UPDATE maluos_compartment SET locked=%s WHERE compartment_id=%s", (locked, comp["compartment_id"]))
        self.ledger(cur, "compartment.lock" if locked else "compartment.unlock", caller, "ok", comp=comp)
        return self.compartment(cur, comp["name"])

    def create_compartment(self, cur, caller, body):
        name = str(body.get("name") or "")
        if not COMP_RE.match(name):
            raise ApiError(400, "bad_name", "compartment names: letters, digits, : _ . @ -")
        if self.compartment(cur, name):
            raise ApiError(409, "exists", f"compartment {name} exists")
        mode = body.get("lock_mode") or CFG["default_lock_mode"]
        if mode not in LOCK_MODES:
            raise ApiError(400, "bad_lock_mode", f"lock_mode must be one of {', '.join(LOCK_MODES)}")
        owner = body.get("owner")
        if owner:
            cur.execute("SELECT 1 FROM maludb_principal WHERE principal_ref=%s", (owner,))
            if not cur.fetchone():
                raise ApiError(404, "unknown_principal", f"no principal {owner}")
        if not caller.operator and not (caller.principal and owner == caller.ref):
            self.deny(cur, "compartment.create", caller, "forbidden", "only an operator creates shared compartments")
        cur.execute("INSERT INTO maluos_compartment (name, owner_principal_ref, scope, lock_mode) VALUES (%s,%s,%s,%s)",
                    (name, owner, body.get("scope"), mode))
        comp = self.compartment(cur, name)
        self.ledger(cur, "compartment.create", caller, "ok", comp=comp, detail={"owner": owner, "scope": body.get("scope")})
        return comp

    def ledger_rows(self, cur, caller, q):
        where, args = [], []
        if not caller.operator:
            if not caller.principal:
                return []
            # own rows, rows brokered for me, and the rows of agents I own (maluos_agent, Phase 12 slice 3)
            where.append("(principal_ref=%s OR broker_ref=%s OR principal_ref IN (SELECT principal_ref FROM maluos_agent WHERE owner_principal_ref=%s AND removed_at IS NULL))")
            args += [caller.ref, caller.ref, caller.ref]
        for key, col in (("principal", "principal_ref"), ("secret", "secret_name"), ("compartment", "compartment"),
                         ("event", "event"), ("status", "status"), ("user", "linux_user")):
            if q.get(key):
                where.append(f"{col}=%s"); args.append(q[key])
        if q.get("event_like"):
            where.append("event LIKE %s"); args.append(q["event_like"])
        since = parse_ts(q.get("since"), past=True)
        if since:
            where.append("ts >= %s"); args.append(since)
        limit = min(int(q.get("limit") or 500), 5000)
        cur.execute(f"""SELECT ledger_id, ts, event, principal_ref, linux_user, process_ref, broker_ref, compartment, secret_name,
                               grant_level, purpose, status, reason, backend, model, tokens_in, tokens_out, cost_actual, detail
                        FROM maluos_ledger {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY ledger_id DESC LIMIT %s""", args + [limit])
        cols = ["ledger_id", "ts", "event", "principal_ref", "linux_user", "process_ref", "broker_ref", "compartment", "secret_name",
                "grant_level", "purpose", "status", "reason", "backend", "model", "tokens_in", "tokens_out", "cost_actual", "detail"]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r)); d["ts"] = d["ts"].isoformat()
            if d["cost_actual"] is not None:
                d["cost_actual"] = float(d["cost_actual"])
            out.append(d)
        return out


def run_hooks(hooks_dir, payload):
    """Run every executable in hooks_dir with the alert as JSON on stdin, detached from the request."""
    import glob, subprocess, threading
    exes = [f for f in sorted(glob.glob(os.path.join(hooks_dir, "*"))) if os.access(f, os.X_OK) and os.path.isfile(f)]
    if not exes:
        return
    data = json.dumps(payload).encode()
    def run():
        for exe in exes:
            try:
                subprocess.run([exe], input=data, timeout=15, capture_output=True)
            except Exception as e:
                log(f"alert hook {exe}: {e.__class__.__name__}")
    threading.Thread(target=run, daemon=True).start()


def parse_ts(v, past=False):
    """ISO 8601, or a duration like 30d / 12h: from now (expiries) or ago (past=True, reports)."""
    if v in (None, "", False):
        return None
    if isinstance(v, datetime.datetime):
        return v if v.tzinfo else v.replace(tzinfo=datetime.timezone.utc)
    s = str(v)
    m = re.match(r"^(\d+)([smhdw])$", s)
    if m:
        n, u = int(m.group(1)), m.group(2)
        delta = datetime.timedelta(seconds=n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[u])
        return utcnow() - delta if past else utcnow() + delta
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(400, "bad_timestamp", f"cannot parse time {v!r} (ISO 8601 or 30d/12h)")
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------- HTTP
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"maluos-vault/{VERSION}"
    vault = None

    def address_string(self):
        return "unix"

    def log_message(self, fmt, *args):
        if os.environ.get("MALUOS_VAULT_DEBUG"):
            log(fmt % args)

    def peer(self):
        creds = self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII"))
        pid, uid, gid = struct.unpack("iII", creds)
        return Caller(pid, uid, gid)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n == 0:
            return {}
        if n > 1 << 20:
            raise ApiError(413, "too_large", "body over 1 MiB")
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "bad_json", "body is not JSON")

    def send(self, status, obj):
        data = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):     self.dispatch("GET")
    def do_POST(self):    self.dispatch("POST")
    def do_DELETE(self):  self.dispatch("DELETE")

    def dispatch(self, method):
        try:
            url = urllib.parse.urlsplit(self.path)
            q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
            parts = [urllib.parse.unquote(p) for p in url.path.strip("/").split("/")]
            if parts[:1] != ["v1"]:
                raise ApiError(404, "not_found", "unknown path")
            if parts[1:] == ["health"]:
                return self.send(200, self.health())
            caller = self.peer()
            body = self.body() if method in ("POST", "DELETE") else {}
            with connect() as conn:
                cur = conn.cursor()
                caller.resolve(cur, self.headers.get("X-MaluOS-Principal") or None)
                status, obj = self.route(method, parts[1:], q, body, caller, cur)
            self.send(status, obj)
        except ApiError as e:
            self.send(e.status, dict(e.extra, error=e.code, message=e.message))
        except psycopg.Error as e:
            log(f"database error: {e}")
            self.send(503, {"error": "database", "message": str(e).strip().splitlines()[0][:200]})
        except Exception as e:  # never leak a traceback with a value in it
            log(f"internal error: {e.__class__.__name__}: {e}")
            self.send(500, {"error": "internal", "message": e.__class__.__name__})

    def health(self):
        ok_db = True
        try:
            with connect() as conn:
                conn.execute("SELECT 1 FROM maluos_ledger LIMIT 0")
        except Exception as e:
            ok_db = f"{e.__class__.__name__}"
        return {"ok": ok_db is True, "version": VERSION, "database": ok_db, "store": os.path.isdir(self.vault.store.dir)}

    def route(self, method, p, q, body, caller, cur):
        v = self.vault
        if p == ["whoami"] and method == "GET":
            return 200, caller.as_dict()
        if p == ["compartments"]:
            if method == "GET":
                return 200, {"compartments": v.visible_compartments(cur, caller)}
            if method == "POST":
                return 201, v.create_compartment(cur, caller, body)
        if len(p) == 3 and p[0] == "compartments" and method == "POST" and p[2] in ("lock", "unlock"):
            comp = v.compartment(cur, p[1]) or self.nf(f"no compartment {p[1]}")
            return 200, v.set_lock(cur, caller, comp, p[2] == "lock")
        if p == ["secrets"]:
            if method == "GET":
                return 200, {"secrets": self.list_secrets(cur, caller, q)}
            if method == "POST":
                return 201, v.add(cur, caller, body)
        if len(p) >= 2 and p[0] == "secrets":
            secret, comp = v.resolve(cur, caller, p[1])
            rest = p[2:]
            if not rest and method == "GET":
                level, why = v.access(cur, caller, secret, comp)
                if level is None:
                    v.deny(cur, "secret.read", caller, "forbidden", f"no access to {secret['ref']}", secret=secret, comp=comp)
                out = v.public(secret); out["access"] = {"level": level, "via": why}
                if v.may_manage(caller, comp):
                    out["grants"] = v.live_grants(cur, secret["secret_id"])
                return 200, out
            if not rest and method == "DELETE":
                return 200, v.delete(cur, caller, secret, comp)
            if rest == ["value"] and method == "GET":
                cause = None
                if q.get("cause"):
                    try:
                        cause = json.loads(q["cause"])
                    except ValueError:
                        raise ApiError(400, "bad_cause", "cause must be JSON")
                return 200, v.value(cur, caller, secret, comp, q.get("mode", "read"), q.get("purpose"), q.get("previous") in ("1", "true"),
                                    cause=cause, reauth=q.get("reauth"))
            if rest == ["rotate"] and method == "POST":
                return 200, v.rotate(cur, caller, secret, comp, body.get("value"), body.get("grace_hours", 0), meta=body)
            if rest == ["grants"] and method == "GET":
                if not v.may_manage(caller, comp):
                    raise ApiError(403, "forbidden", "only the owner or an operator lists grants")
                return 200, {"grants": v.live_grants(cur, secret["secret_id"])}
            if rest == ["grants"] and method == "POST":
                return 201, v.grant(cur, caller, secret, comp, body)
            if rest == ["revoke"] and method == "POST":
                return 200, v.revoke(cur, caller, secret, comp, body)
            if rest == ["request"] and method == "POST":
                rid = v.file_request(cur, caller, secret, comp, body.get("level") or "use", body.get("purpose"), explicit=True)
                if rid is None:
                    raise ApiError(400, "no_request", "nothing to ask: you own this secret, are an operator, or are not enrolled")
                return 201, v.request_by_id(cur, rid)
        if p == ["ledger"] and method == "GET":
            return 200, {"events": v.ledger_rows(cur, caller, q)}
        if p == ["requests"] and method == "GET":
            return 200, {"requests": v.requests(cur, caller, q.get("status") or "pending")}
        if len(p) == 3 and p[0] == "requests" and method == "POST" and p[2] in ("approve", "deny"):
            try:
                rid = int(p[1])
            except ValueError:
                raise ApiError(400, "bad_request", "request id must be a number")
            return 200, v.decide_request(cur, caller, rid, p[2] == "approve", body)
        if p == ["delegations"]:
            if method == "GET":
                return 200, {"delegations": v.delegations(cur, caller)}
            if method == "POST":
                return 201, v.delegate(cur, caller, body)
        if p == ["delegations", "revoke"] and method == "POST":
            return 200, v.undelegate(cur, caller, body)
        if p == ["reauth"] and method == "POST":
            return 200, v.reauth(cur, caller, body.get("purpose"))
        if p == ["export"] and method == "GET":
            return 200, v.export(cur, caller, q.get("compartment"))
        if p == ["import"] and method == "POST":
            return 200, v.import_bundle(cur, caller, body.get("bundle"))
        raise ApiError(404, "not_found", f"no route {method} /{'/'.join(p)}")

    @staticmethod
    def nf(msg):
        raise ApiError(404, "not_found", msg)

    def list_secrets(self, cur, caller, q):
        v = self.vault
        out = []
        comps = v.visible_compartments(cur, caller)
        if q.get("compartment"):
            comps = [c for c in comps if c["name"] == q["compartment"]]
            if not comps:
                raise ApiError(404, "no_compartment", f"no compartment {q['compartment']}")
        for c in comps:
            for s in v.secrets_in(cur, c["compartment_id"]):
                level, why = v.access(cur, caller, s, c)
                if level or q.get("all") and caller.operator:
                    d = v.public(s); d["access"] = {"level": level, "via": why}; d["locked"] = c["locked"]
                    out.append(d)
        return out


class UnixHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    address_family = socket.AF_UNIX
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "maluos-vault", 0


def serve(argv):
    import argparse
    ap = argparse.ArgumentParser(description="MaluOS secret vault daemon")
    ap.add_argument("--socket", help="bind this path (default: inherit from systemd, else config)")
    args = ap.parse_args(argv)
    store = Store(load_master(), os.path.join(CFG["state_dir"], "blobs"))
    Handler.vault = Vault(store)
    fds = int(os.environ.get("LISTEN_FDS") or 0)
    if fds and os.environ.get("LISTEN_PID") in (None, str(os.getpid())):
        srv = UnixHTTPServer("", Handler, bind_and_activate=False)
        srv.socket.close()
        srv.socket = socket.socket(fileno=3)
        log(f"serving on inherited socket (activation), tenant {CFG['tenant']}")
    else:
        path = args.socket or CFG["socket"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            os.remove(path)
        srv = UnixHTTPServer(path, Handler)
        os.chmod(path, 0o666)
        log(f"serving on {path}, tenant {CFG['tenant']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve(sys.argv[1:])
