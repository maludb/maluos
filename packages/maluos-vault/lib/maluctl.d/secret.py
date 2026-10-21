"""maluctl secret: the MaluOS vault from the command line.

  maluctl secret whoami                         who the vault thinks you are
  maluctl secret list [--compartment C] [--all] secrets you may use (--all: every secret, operators)
  maluctl secret add NAME [--compartment C] [--kind api_key|token|password|generic]
                    [--provider P] [--env VAR] [--expires 90d|ISO] [--value-file F | --stdin]
                                                value from a file, stdin, or a hidden prompt
  maluctl secret show NAME [--previous]         print the value (a logged read)
  maluctl secret info NAME                      metadata and grants, no value
  maluctl secret exec NAME [NAME...] -- CMD...  run CMD with each secret in its env var (a logged read)
  maluctl secret rotate NAME [--grace 24h] [--value-file F | --stdin]
  maluctl secret delete NAME
  maluctl secret grant NAME (--to PRINCIPAL | --scope SCOPE) [--level use|read] [--expires 30d]
  maluctl secret revoke NAME (--to PRINCIPAL | --scope SCOPE)
  maluctl secret usage [--since 7d] [--by user|principal|secret|event|day] [--secret N] [--principal R] [--raw]
  maluctl secret delegate --to PRINCIPAL [--secret NAME] [--expires 7d] [--budget usd_per_day=1]
                                                let an agent use your keys (use only, never read)
  maluctl secret undelegate --to PRINCIPAL [--secret NAME]  |  maluctl secret delegations
  maluctl secret export FILE [--compartment C]  encrypted bundle (operators; passphrase prompt or --passphrase-file F)
  maluctl secret import FILE                    restore a bundle (operators)
  maluctl secret alerts [--since 7d]            alert rows from the ledger
  maluctl secret requests [--all]               grant requests you made or must decide (pending; --all: every status)
  maluctl secret request NAME [--level use|read] [--purpose P]   ask the owner for a grant (a refusal files one too)
  maluctl secret approve ID [--level use|read] [--expires 7d] [--budget usd_per_day=1]
  maluctl secret deny ID [--reason R]
  maluctl secret compartment list | create NAME [--owner P] [--scope S] | lock NAME | unlock NAME

NAME is `compartment/name`, or a bare name looked up in your own compartment
first, then in the compartments you hold grants in. Shared compartments
(system, org, ...) are managed by operators (root); your own compartment is
named after your principal (user:<login>) and is yours.
"""
import getpass, os, sys
sys.path.insert(0, "/usr/lib/maluos")
from maluos_vault_client import Vault, VaultError


def opt(args, name, default=None, flag=False):
    if name in args:
        i = args.index(name)
        if flag:
            args.pop(i); return True
        v = args[i + 1]; del args[i:i + 2]; return v
    return default


def read_value(args, prompt):
    f = opt(args, "--value-file")
    if f:
        return open(f).read().rstrip("\n")
    if opt(args, "--stdin", flag=True) or not sys.stdin.isatty():
        return sys.stdin.read().rstrip("\n")
    v = getpass.getpass(prompt)
    if getpass.getpass("again: ") != v:
        sys.exit("values differ")
    return v


def fmt_table(rows, cols):
    if not rows:
        print("(none)"); return
    w = [max(len(c), *(len(str(r.get(c, "") if r.get(c) is not None else "-")) for r in rows)) for c in cols]
    print("  ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
    for r in rows:
        print("  ".join(str(r.get(c) if r.get(c) is not None else "-").ljust(w[i]) for i, c in enumerate(cols)))


def main(args):
    v = Vault()
    try:
        return run(v, list(args))
    except VaultError as e:
        print(f"maluctl secret: {e.message or e.code}", file=sys.stderr)
        if e.code == "unavailable":
            print("  (is maluos-vault.socket active? sudo systemctl status maluos-vault.socket)", file=sys.stderr)
        return 1


def run(v, a):
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    cmd = a.pop(0)
    if cmd == "whoami":
        w = v.whoami()
        print(f"user:       {w['user']} (uid {w['uid']})")
        print(f"principal:  {w['principal'] or '(not enrolled)'}{'  kind=' + w['kind'] if w.get('kind') else ''}")
        print(f"operator:   {'yes' if w['operator'] else 'no'}    broker: {'yes' if w['broker'] else 'no'}")
        print(f"process:    {w.get('process') or '-'}")
        return 0
    if cmd == "list":
        comp, allf = opt(a, "--compartment"), opt(a, "--all", flag=True)
        rows = v.secrets(compartment=comp, all=allf)
        for r in rows:
            r["access"] = (r["access"]["level"] or "-") if r.get("access") else "-"
            r["expires"] = (r.get("expires_at") or "")[:10] or "-"
            r["state"] = "locked" if r.get("locked") else "ok"
        fmt_table(rows, ["ref", "kind", "provider", "env_var", "access", "expires", "state"])
        return 0
    if cmd == "add":
        name = a.pop(0) if a and not a[0].startswith("--") else sys.exit("add NAME ...")
        comp = opt(a, "--compartment"); kind = opt(a, "--kind"); prov = opt(a, "--provider"); env = opt(a, "--env"); exp = opt(a, "--expires")
        upsert = opt(a, "--upsert", flag=True)
        if "/" in name and not comp:
            comp, name = name.split("/", 1)
        value = read_value(a, f"value for {name}: ")
        r = v.add(name, value, compartment=comp, kind=kind, provider=prov, env_var=env, expires_at=exp, upsert=upsert)
        print(f"stored {r['ref']} ({r['kind']}{', ' + r['provider'] if r.get('provider') else ''})"); return 0
    if cmd == "show":
        name = a.pop(0); prev = opt(a, "--previous", flag=True)
        print(v.value(name, "read", purpose=opt(a, "--purpose", "maluctl show"), previous=prev)["value"]); return 0
    if cmd == "info":
        r = v.get(a.pop(0))
        for k in ("ref", "kind", "provider", "env_var", "created_by", "created_at", "rotated_at", "expires_at", "grace_until"):
            print(f"{k + ':':13}{r.get(k) if r.get(k) is not None else '-'}")
        print(f"{'access:':13}{r['access']['level']} via {r['access']['via']}")
        if "grants" in r:
            print("grants:")
            for g in r["grants"] or []:
                print(f"  {g['level']:5} {g['grantee_kind']}:{g['grantee_ref']}" + (f"  until {g['expires_at'][:19]}" if g.get("expires_at") else ""))
            if not r["grants"]:
                print("  (none)")
        return 0
    if cmd == "exec":
        if "--" not in a:
            sys.exit("exec NAME [NAME...] -- CMD...")
        i = a.index("--"); names, cmdv = a[:i], a[i + 1:]
        if not names or not cmdv:
            sys.exit("exec NAME [NAME...] -- CMD...")
        env = dict(os.environ)
        for n in names:
            var = None
            if "=" in n:
                var, n = n.split("=", 1)
            r = v.value(n, "read", purpose=f"exec {os.path.basename(cmdv[0])}")
            var = var or r.get("env_var") or default_env_var(r)
            env[var] = r["value"]
        os.execvpe(cmdv[0], cmdv, env)
    if cmd == "rotate":
        name = a.pop(0); grace = opt(a, "--grace")
        hours = parse_hours(grace) if grace else 0
        value = read_value(a, f"new value for {name}: ")
        r = v.rotate(name, value, grace_hours=hours)
        print(f"rotated {r['ref']}" + (f" (previous value valid until {r['grace_until'][:19]})" if r.get("grace_until") else "")); return 0
    if cmd == "delete":
        print("deleted", v.delete(a.pop(0))["deleted"]); return 0
    if cmd in ("grant", "revoke"):
        name = a.pop(0); to = opt(a, "--to"); scope = opt(a, "--scope")
        if bool(to) == bool(scope):
            sys.exit(f"{cmd} NAME --to PRINCIPAL | --scope SCOPE")
        gk, gr = ("principal", to) if to else ("scope", scope)
        if cmd == "grant":
            r = v.grant(name, gk, gr, level=opt(a, "--level", "use"), expires_at=opt(a, "--expires"))
            print(f"granted {r['level']} on {r['secret']} to {gk} {gr}")
        else:
            r = v.revoke(name, gk, gr); print(f"revoked {r['revoked']} grant(s)")
        return 0
    if cmd == "usage":
        since = opt(a, "--since", "7d"); by = opt(a, "--by", "secret"); raw = opt(a, "--raw", flag=True)
        rows = v.ledger(since=since, secret=opt(a, "--secret"), principal=opt(a, "--principal"), event=opt(a, "--event"),
                        user=opt(a, "--user"), limit=opt(a, "--limit", 5000))
        if raw:
            for r in reversed(rows):
                print(f"{r['ts'][:19]}  {r['event']:18} {r['status']:7} {r.get('principal_ref') or r.get('linux_user') or '-':24} "
                      f"{(r.get('compartment') or '') + '/' + (r.get('secret_name') or '') if r.get('secret_name') else '-':32} "
                      f"{r.get('process_ref') or ''} {r.get('reason') or ''} {r.get('purpose') or ''}".rstrip())
            return 0
        key = {"user": "linux_user", "principal": "principal_ref", "secret": "secret_name", "event": "event",
               "day": "day"}.get(by) or sys.exit("--by user|principal|secret|event|day")
        agg = {}
        for r in rows:
            k = r["ts"][:10] if key == "day" else (r.get(key) or "-")
            if by == "secret" and r.get("secret_name"):
                k = f"{r.get('compartment')}/{r['secret_name']}"
            d = agg.setdefault(k, {by: k, "ok": 0, "denied": 0, "reads": 0, "uses": 0, "last": ""})
            if r["status"] in ("ok", "denied"):
                d[r["status"]] += 1
            if r["status"] == "ok" and r["event"] == "secret.read":
                d["reads"] += 1
            if r["status"] == "ok" and r["event"] == "secret.use":
                d["uses"] += 1
            d["last"] = max(d["last"], r["ts"][:19])
        fmt_table(sorted(agg.values(), key=lambda d: d["last"], reverse=True), [by, "ok", "denied", "reads", "uses", "last"])
        print(f"({len(rows)} events since {since}; --raw for the list)")
        return 0
    if cmd == "delegate":
        to = opt(a, "--to") or sys.exit("--to PRINCIPAL required"); sec = opt(a, "--secret"); exp = opt(a, "--expires"); b = opt(a, "--budget")
        budget = None
        if b:
            budget = {}
            for kv in b.split(","):
                k, val = kv.split("=", 1); budget[k.strip()] = float(val)
        r = v.delegate(to, secret=sec, expires_at=exp, budget=budget, frm=opt(a, "--from"))
        print(f"delegated {r['from']}'s {'secret ' + sec if sec else 'secrets'} to {to} (use only)"); return 0
    if cmd == "undelegate":
        to = opt(a, "--to") or sys.exit("--to PRINCIPAL required")
        print(f"revoked {v.undelegate(to, secret=opt(a, '--secret'), frm=opt(a, '--from'))['revoked']} delegation(s)"); return 0
    if cmd == "delegations":
        rows = v.delegations()
        for r in rows:
            r["secret"] = r.get("secret") or "(all)"; r["expires"] = (r.get("expires_at") or "never")[:19]
        fmt_table(rows, ["from", "to", "secret", "expires", "budget"]); return 0
    if cmd == "export":
        path = a.pop(0); comp = opt(a, "--compartment")
        pw = passphrase(a, confirm=True)
        bundle = v.export(compartment=comp)
        import base64, json as _json
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        salt, nonce = os.urandom(16), os.urandom(12)
        key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(pw.encode())
        ct = AESGCM(key).encrypt(nonce, _json.dumps(bundle).encode(), b"maluos-vault-export-1")
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            _json.dump({"maluos_vault_export_encrypted": 1, "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode(),
                        "data": base64.b64encode(ct).decode()}, f)
        print(f"exported {len(bundle['secrets'])} secret(s) in {len(bundle['compartments'])} compartment(s) to {path} (every value read is in the ledger)"); return 0
    if cmd == "import":
        path = a.pop(0)
        pw = passphrase(a)
        import base64, json as _json
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        env = _json.load(open(path))
        key = Scrypt(salt=base64.b64decode(env["salt"]), length=32, n=2 ** 15, r=8, p=1).derive(pw.encode())
        try:
            bundle = _json.loads(AESGCM(key).decrypt(base64.b64decode(env["nonce"]), base64.b64decode(env["data"]), b"maluos-vault-export-1"))
        except Exception:
            sys.exit("wrong passphrase or damaged file")
        n = v.import_bundle(bundle)
        print(f"imported: {n}"); return 0
    if cmd == "alerts":
        since = opt(a, "--since", "7d")
        for r in reversed(v.ledger(since=since, event_like="alert.%", limit=500)):
            print(f"{r['ts'][:19]}  {r['event'][6:]:16} {r.get('reason') or ''}")
        return 0
    if cmd == "requests":
        rows = v.requests(status="all" if opt(a, "--all", flag=True) else "pending")
        for r in rows:
            r["id"] = r["request_id"]; r["asked"] = (r.get("last_asked_at") or "")[:16]; r["times"] = r.get("asked_count")
            r["purpose"] = (r.get("purpose") or "-")[:40]; r["decided"] = f"{r['status']} by {r['decided_by']}" if r.get("decided_by") else r["status"]
        fmt_table(rows, ["id", "secret", "requester", "level", "purpose", "times", "asked", "decided"]); return 0
    if cmd == "request":
        name = a.pop(0) if a and not a[0].startswith("--") else sys.exit("request NAME ...")
        r = v.ask(name, level=opt(a, "--level", "use"), purpose=opt(a, "--purpose"))
        print(f"request #{r['request_id']} for {r['level']} on {r['secret']} is {r['status']}" + (f" (asked {r['asked_count']} times)" if r.get("asked_count", 1) > 1 else "")); return 0
    if cmd in ("approve", "deny"):
        rid = a.pop(0) if a else sys.exit(f"{cmd} ID")
        if cmd == "approve":
            b = opt(a, "--budget"); budget = None
            if b:
                budget = {}
                for kv in b.split(","):
                    k, val = kv.split("=", 1); budget[k.strip()] = float(val)
            r = v.approve(rid, level=opt(a, "--level"), expires_at=opt(a, "--expires"), budget=budget)
            print(f"approved request #{r['request_id']}: {r['requester']} may {r['level']} {r['secret']}" + (f" until {r['expires_at'][:19]}" if r.get("expires_at") else ""))
        else:
            r = v.deny_request(rid, reason=opt(a, "--reason"))
            print(f"denied request #{r['request_id']} ({r['requester']} on {r['secret']})")
        return 0
    if cmd == "compartment":
        sub = a.pop(0) if a else "list"
        if sub == "list":
            rows = v.compartments()
            for r in rows:
                r["owner"] = r.get("owner") or "(shared)"; r["state"] = "locked" if r["locked"] else "unlocked"
            fmt_table(rows, ["name", "owner", "scope", "lock_mode", "state"]); return 0
        if sub == "create":
            r = v.create_compartment(a.pop(0), owner=opt(a, "--owner"), scope=opt(a, "--scope"), lock_mode=opt(a, "--lock-mode"))
            print(f"created compartment {r['name']}"); return 0
        if sub in ("lock", "unlock"):
            r = v.lock(a.pop(0), sub == "lock"); print(f"{r['name']}: {'locked' if r['locked'] else 'unlocked'}"); return 0
    print(__doc__); return 2


def passphrase(args, confirm=False):
    f = opt(args, "--passphrase-file")
    if f:
        return open(f).read().strip()
    pw = getpass.getpass("passphrase: ")
    if confirm and getpass.getpass("again: ") != pw:
        sys.exit("passphrases differ")
    return pw


def default_env_var(r):
    p = (r.get("provider") or "").lower()
    known = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "ollama": "OLLAMA_API_KEY", "ollama_cloud": "OLLAMA_API_KEY",
             "openrouter": "OPENROUTER_API_KEY", "google": "GOOGLE_API_KEY", "gemini": "GEMINI_API_KEY", "mistral": "MISTRAL_API_KEY",
             "groq": "GROQ_API_KEY", "huggingface": "HF_TOKEN", "github": "GITHUB_TOKEN"}
    if p in known:
        return known[p]
    import re
    return re.sub(r"[^A-Z0-9]+", "_", r["name"].upper()).strip("_") or "SECRET"


def parse_hours(s):
    import re
    m = re.match(r"^(\d+(?:\.\d+)?)([hdw]?)$", s)
    if not m:
        sys.exit("--grace takes hours, e.g. 24h, 7d")
    n, u = float(m.group(1)), m.group(2) or "h"
    return n * {"h": 1, "d": 24, "w": 168}[u]
