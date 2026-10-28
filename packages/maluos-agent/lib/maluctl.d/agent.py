"""maluctl agent: an agent as a system concept.

One command creates everything an agent needs on a MaluOS host, and one
removes it: a Linux system user, a MaluDB principal with scope grants, the
identity mapping for the vault and the gateway, its own vault compartment,
a gateway policy (class, tiers, cloud, egress ceiling, budget), optionally
a gateway token, and a hardened systemd unit (maluos-agent@NAME) that runs
the agent's command as that user with the MaluOS endpoints in its
environment.

  maluctl agent create NAME [--exec CMD] [--name "Display"] [--home SCOPE] [--scope SCOPE:read|write ...]
                     [--capability TAG ...] [--accept-from org|dept:N|user:LOGIN|agent:NAME|node:KIND ...]
                     [--max-classification public|internal|restricted|prohibited] [--approve CLASS|ORIGINATOR ...]
                     [--personal]                        the person's own representative (Phase 13 slice 2)
  maluctl agent policy NAME [set --accept-from ... --max-classification C --approve ... | --clear]
                     [--class agent] [--tiers a,b] [--backends a,b] [--cloud yes|no] [--egress public|internal|restricted]
                     [--budget usd_per_day=1] [--token] [--sandbox standard|strict] [--no-start]
                     [--owner user:NAME | --owner none]   who the agent belongs to (default: the sudo user)
  maluctl agent list [--json] | show NAME
  maluctl agent start|stop|restart|status|logs NAME
  maluctl agent run NAME -- CMD...            run a command as the agent (its identity, its environment)
  maluctl agent card NAME [--json]            what the agent says about itself (its task interface, Phase 12 slice 8)
  maluctl agent send NAME TEXT [--json]       give the agent a task and print its answer as it grows (as its owner, root or itself)
  maluctl agent tasks NAME [--json]           the agent's recent tasks
  maluctl agent remove NAME [--purge]         stop the unit, disable the principal; --purge also deletes the user and its files

Ownership (Phase 12 slice 3): an agent belongs to a person. The owner is
recorded in the registry (maluos_agent in the tenant schema) and in the
agent's env file (MALUOS_AGENT_OWNER); they see the agent's ledger rows and
alerts, their desk shows it as theirs, and a polkit rule lets them start,
stop and restart its unit without an administrator's password. `--owner
none` makes a system agent (operators only).

The agent's process sees MALUOS_PRINCIPAL, MALUOS_GATEWAY_SOCKET,
MALUOS_VAULT_SOCKET, MALUDB_MC2DBD_URL, OPENAI_BASE_URL (the TCP listener,
when enabled) and, with --token, the gateway token as the credential file
$CREDENTIALS_DIRECTORY/gateway-token. On a desk enrolled with an office
(maluctl office) it also sees MALUOS_OFFICE_* from /etc/maluos/office.env:
the office's URL and MCP endpoints, and the vault name of the desk token
the owner may delegate or grant to it.

Tasks (Phase 12 slice 8): an agent that serves maluos_agent_tasks (the
demo agent does) answers tasks on /run/maluos/agents/NAME/tasks.sock
(MALUOS_AGENT_TASKS_SOCKET in its environment; the unit's runtime
directory). The socket admits its owner, root and the agent itself by
peer credentials; the Agents app (maluos-agents) and `maluctl agent
send|tasks|card` are its clients.
"""
import json, os, pwd, re, subprocess, sys, time
sys.path.insert(0, "/usr/lib/maluos")

AGENTS = "/etc/maluos/agents"
HOME = "/var/lib/maluos/agents"
UNIT = "maluos-agent@{}.service"
POLKIT = "/etc/polkit-1/rules.d/60-maluos-agent-{}.rules"
POLKIT_RULE = """// MaluOS: the owner of agent {name} manages its unit from their session (maluctl agent; Phase 12 slice 3).
polkit.addRule(function(action, subject) {{
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        action.lookup("unit") == "{unit}" &&
        ["start", "stop", "restart", "reload-or-restart", "try-restart"].indexOf(action.lookup("verb")) >= 0 &&
        subject.user == "{user}")
        return polkit.Result.YES;
}});
"""
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
MANIFEST = AGENTS + "/{}.manifest.yaml"      # Phase 13 slice 2: what the node registers in the estate's directory
POLICY = AGENTS + "/{}.policy.yaml"          # who may task the agent, on its host
AGENTS_HINT = "/run/maluos/estate/agents-changed"   # touched after create|remove|policy: maluos-estated re-registers at once
CLASSIFICATIONS = ("public", "internal", "restricted", "prohibited")
ACCEPT_RE = re.compile(r"^(org|dept:[0-9]+|user:[a-z_][a-z0-9_-]{0,31}|agent:[a-z][a-z0-9-]{0,30}|node:(desk|server|inference))$")


def read_yaml(path):
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def write_yaml(path, data, mode=0o644):
    import yaml
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        yaml.safe_dump(data, f, sort_keys=True)
    os.chmod(tmp, mode); os.replace(tmp, path)


def agents_hint():
    try:
        os.makedirs(os.path.dirname(AGENTS_HINT), exist_ok=True)
        with open(AGENTS_HINT, "w") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass


def check_accept(rules):
    for r in rules:
        if not ACCEPT_RE.match(r):
            sys.exit(f"--accept-from {r}: org, dept:N, user:LOGIN, agent:NAME or node:desk|server|inference")
    return rules


def check_approve(rules):
    for r in rules:
        if r not in CLASSIFICATIONS and not ACCEPT_RE.match(r):
            sys.exit(f"--approve {r}: a classification or an originator rule")
    return rules
SANDBOX = {
    "standard": "",
    "strict": "[Service]\nIPAddressDeny=any\nIPAddressAllow=localhost\n",
}


def opt(args, name, default=None, flag=False, multi=False):
    out = []
    while name in args:
        i = args.index(name)
        if flag:
            args.pop(i); return True
        v = args[i + 1]; del args[i:i + 2]
        if not multi:
            return v
        out.append(v)
    return out if multi else default


def need_root():
    if os.geteuid() != 0:
        sys.exit("maluctl agent: run with sudo")


def sh(*cmd, check=True, capture=True):
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout.strip() if capture else ""


def state():
    import maluos_provision as mp
    if not os.path.exists(mp.DONE):
        sys.exit("not provisioned (maluctl status)")
    return mp, json.load(open(mp.DONE))


def owner_user(ref):
    """The Linux user behind an owner principal: user:NAME is NAME; anything else has no login here."""
    if ref and ref.startswith("user:"):
        name = ref[5:]
        try:
            pwd.getpwnam(name); return name
        except KeyError:
            return None
    return None


def default_owner(mp, st):
    """The person running sudo, when they are an enrolled principal."""
    su = os.environ.get("SUDO_USER")
    if not su or su == "root":
        return None
    ref = f"user:{su}"
    pre = f"SET ROLE {mp.qi(st['tenant'])}; SET search_path TO {mp.qi(st['tenant'])}, maludb_core, public; "
    return ref if mp.psql(pre + f"SELECT 1 FROM maludb_principal WHERE principal_ref={mp.ql(ref)} AND enabled", st["database"]) == "1" else None


def read_env(n):
    env = {}
    try:
        for line in open(f"{AGENTS}/{n}.env"):
            if "=" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("=", 1); env[k] = v.strip('"')
    except OSError:
        pass
    return env


def yaml_update(path, fn):
    import yaml
    d = {}
    if os.path.exists(path):
        with open(path) as f:
            d = yaml.safe_load(f) or {}
    fn(d)
    with open(path, "w") as f:
        yaml.safe_dump(d, f, sort_keys=True)
    os.chmod(path, 0o644)


def _grow():
    """Print a growing answer: what each poll adds to what is on the terminal already (slice 9: streaming).
    When the final text does not extend the partial one (the handler replaced it), it is printed on its own line."""
    st = {"shown": ""}
    def on_text(text):
        if text.startswith(st["shown"]):
            sys.stdout.write(text[len(st["shown"]):]); sys.stdout.flush(); st["shown"] = text
        else:
            sys.stdout.write(("\n" if st["shown"] and not st["shown"].endswith("\n") else "") + text); sys.stdout.flush(); st["shown"] = text
    def finish(final):
        if final is not None and final != st["shown"]:
            on_text(final)
        if st["shown"] and not st["shown"].endswith("\n"):
            sys.stdout.write("\n"); sys.stdout.flush()
    _grow.finish = finish
    return on_text


def tasks_mod():
    import maluos_agent_tasks
    return maluos_agent_tasks


def main(args):
    try:
        return run(list(args))
    except RuntimeError as e:
        print(f"maluctl agent: {e}", file=sys.stderr); return 1


def run(a):
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    cmd = a.pop(0)
    if cmd == "list":
        as_json = opt(a, "--json", flag=True)
        names = sorted(f[:-4] for f in os.listdir(AGENTS) if f.endswith(".env")) if os.path.isdir(AGENTS) else []
        if as_json:
            out = []
            for n in names:
                env = read_env(n)
                out.append({"name": n, "principal": env.get("MALUOS_PRINCIPAL") or f"agent:{n}", "user": f"agent-{n}", "owner": env.get("MALUOS_AGENT_OWNER"),
                            "exec": env.get("MALUOS_AGENT_EXEC"), "unit": UNIT.format(n),
                            "active": subprocess.run(["systemctl", "is-active", UNIT.format(n)], capture_output=True, text=True).stdout.strip(),
                            "tasks": os.path.exists(f"{tasks_mod().SOCKET_DIR}/{n}/tasks.sock")})
            print(json.dumps(out, indent=1)); return 0
        if not names:
            print("(no agents; maluctl agent create NAME --exec CMD)"); return 0
        for n in names:
            st = subprocess.run(["systemctl", "is-active", UNIT.format(n)], capture_output=True, text=True).stdout.strip()
            print(f"{n:20} agent:{n:20} user agent-{n:18} owner {read_env(n).get('MALUOS_AGENT_OWNER') or '-':20} unit {st}")
        return 0
    if cmd in ("card", "send", "tasks"):
        as_json = opt(a, "--json", flag=True)
        n = a.pop(0) if a else sys.exit(f"{cmd} NAME ...")
        if not NAME_RE.match(n):
            sys.exit("agent names: lowercase letters, digits, hyphens")
        T = tasks_mod()
        c = T.Client.local(n)
        try:
            if cmd == "card":
                d = c.card()
                if as_json:
                    print(json.dumps(d, indent=1)); return 0
                print(f"{d.get('name')}: {d.get('description') or '(no description)'}")
                print(f"capabilities: {', '.join(d.get('capabilities') or []) or '-'}\nprincipal:    {d.get('principal')}\nowner:        {d.get('owner') or '-'}\nprotocol:     {d.get('protocol')}")
                return 0
            if cmd == "send":
                text = " ".join(a).strip() or sys.exit("send NAME TEXT")
                if as_json:
                    t = c.send(text)
                    print(json.dumps(t, indent=1)); return 0 if t.get("state") == "completed" else 1
                t = c.stream(text, on_text=_grow())
                if t.get("state") == "completed":
                    _grow.finish(t["output"]["text"]); return 0
                _grow.finish(None)
                print(f"task {t['id']} {t['state']}: {t.get('error') or ''}", file=sys.stderr); return 1
            rows = c.list()
            if as_json:
                print(json.dumps(rows, indent=1)); return 0
            if not rows:
                print("(no tasks yet)"); return 0
            for t in rows:
                print(f"{t['ts'][:19]}  {t['id']}  {t['state']:9} {t['input']['text'][:50]!r:54} -> {(t.get('output') or {}).get('text', t.get('error') or '')[:60]!r}")
            return 0
        except T.TaskError as e:
            raise RuntimeError(f"agent {n}: {e.message}")
    if cmd in ("start", "stop", "restart", "status"):
        n = a.pop(0); return subprocess.run(["systemctl", cmd, UNIT.format(n)] + (["--no-pager"] if cmd == "status" else [])).returncode
    if cmd == "logs":
        n = a.pop(0); return subprocess.run(["journalctl", "-u", UNIT.format(n), "--no-pager"] + a).returncode
    if cmd == "show":
        n = a.pop(0)
        env = f"{AGENTS}/{n}.env"
        if not os.path.exists(env):
            raise RuntimeError(f"no agent {n}")
        print(open(env).read().rstrip())
        print(f"owner:       {read_env(n).get('MALUOS_AGENT_OWNER') or '(none: a system agent)'}" + ("  (polkit rule for their session)" if os.path.exists(POLKIT.format(n)) else ""))
        print(f"unit:        {UNIT.format(n)} ({subprocess.run(['systemctl', 'is-active', UNIT.format(n)], capture_output=True, text=True).stdout.strip()})")
        print(f"token:       {'yes' if os.path.getsize(f'{AGENTS}/{n}.token') > 0 else 'no'}")
        dd = f"/etc/systemd/system/{UNIT.format(n)}.d/sandbox.conf"
        print(f"sandbox:     {'strict' if os.path.exists(dd) and 'IPAddressDeny' in open(dd).read() else 'standard'}")
        if os.geteuid() == 0:
            mp, st = state()
            pre = f"SET ROLE {mp.qi(st['tenant'])}; SET search_path TO {mp.qi(st['tenant'])}, maludb_core, public; "
            print("principal:   " + (mp.psql(pre + f"SELECT principal_ref || '  ' || principal_kind || '  home=' || coalesce(home_scope,'') || '  enabled=' || enabled FROM maludb_principal WHERE principal_ref={mp.ql('agent:' + n)}", st["database"]) or "(none)"))
            print("scopes:      " + (mp.psql(pre + f"SELECT string_agg(scope || ':' || access_level, ', ') FROM maludb_principal_scope WHERE principal_ref={mp.ql('agent:' + n)} AND revoked_at IS NULL", st["database"]) or "-"))
            print("policy:      " + (mp.psql(pre + f"SELECT 'class=' || coalesce(default_class,'-') || ' tiers=' || coalesce(array_to_string(allowed_tiers, ','),'all') || ' cloud=' || cloud_allowed || ' egress=' || coalesce(max_egress_sensitivity,'(default)') || ' budget=' || coalesce(budget::text,'-') FROM maluos_policy WHERE subject_kind='principal' AND subject_ref={mp.ql('agent:' + n)}", st["database"]) or "(default)"))
        return 0
    if cmd == "run":
        n = a.pop(0)
        if a[:1] == ["--"]:
            a.pop(0)
        if not a:
            sys.exit("run NAME -- CMD...")
        need_root()
        env = dict(os.environ)
        for f in ("/etc/maluos/office.env", f"{AGENTS}/{n}.env"):     # the unit's EnvironmentFile order: the agent's own last
            try:
                for line in open(f):
                    if "=" in line and not line.startswith("#"):
                        k, v = line.rstrip("\n").split("=", 1); env[k] = v.strip('"')
            except OSError:
                pass
        env["HOME"] = f"{HOME}/{n}"
        os.execvpe("runuser", ["runuser", "-u", f"agent-{n}", "--", *a], env)
    if cmd == "create":
        return create(a)
    if cmd == "policy":
        return policy(a)
    if cmd == "personal":
        return personal(a)
    if cmd == "remove":
        return remove(a)
    print(__doc__); return 2


def create(a):
    need_root()
    n = a.pop(0) if a and not a[0].startswith("--") else sys.exit("create NAME ...")
    if not NAME_RE.match(n):
        sys.exit("agent names: lowercase letters, digits, hyphens")
    display = opt(a, "--name", n); home = opt(a, "--home", f"agent:{n}"); scopes = opt(a, "--scope", multi=True)
    cls = opt(a, "--class", "agent"); tiers = opt(a, "--tiers"); backends = opt(a, "--backends"); cloud = opt(a, "--cloud")
    egress = opt(a, "--egress"); budget = opt(a, "--budget"); token = opt(a, "--token", flag=True)
    sandbox = opt(a, "--sandbox", "standard"); nostart = opt(a, "--no-start", flag=True); exe = opt(a, "--exec")
    owner_opt = opt(a, "--owner")
    caps = [c.strip().lower() for c in opt(a, "--capability", multi=True) for c in c.split(",") if c.strip()]
    accept = check_accept([x for x in opt(a, "--accept-from", multi=True) for x in x.split(",") if x])
    approve = check_approve([x for x in opt(a, "--approve", multi=True) for x in x.split(",") if x])
    maxc = opt(a, "--max-classification")
    personal = opt(a, "--personal", flag=True)
    if maxc is not None and maxc not in CLASSIFICATIONS:
        sys.exit("--max-classification public|internal|restricted|prohibited")
    if personal:
        # the person's representative (decision 8): capability personal, its owner only, an internal egress ceiling, a small budget, the personal body
        caps = sorted(set(caps) | {"personal"}); accept = []; egress = egress or "internal"; budget = budget or "1/day"
        exe = exe or "/usr/lib/maluos/maluos-agent-personal.py"
        if owner_opt == "none":
            sys.exit("--personal needs an owner")
    if sandbox not in SANDBOX:
        sys.exit("--sandbox standard|strict")
    mp, st = state()
    db, tenant = st["database"], st["tenant"]
    user = f"agent-{n}"
    ref = f"agent:{n}"
    pre = f"SET ROLE {mp.qi(tenant)}; SET search_path TO {mp.qi(tenant)}, maludb_core, public; "
    if owner_opt in (None, ""):
        owner = default_owner(mp, st)
    elif owner_opt == "none":
        owner = None
    else:
        owner = owner_opt
        if mp.psql(pre + f"SELECT 1 FROM maludb_principal WHERE principal_ref={mp.ql(owner)} AND enabled", db) != "1":
            sys.exit(f"--owner {owner}: no such enabled principal")
    # 1. the Linux user and its home
    try:
        pwd.getpwnam(user)
    except KeyError:
        sh("adduser", "--system", "--group", "--home", f"{HOME}/{n}", "--no-create-home", "--shell", "/usr/sbin/nologin", user)
    os.makedirs(f"{HOME}/{n}", exist_ok=True)
    u = pwd.getpwnam(user); os.chown(f"{HOME}/{n}", u.pw_uid, u.pw_gid); os.chmod(f"{HOME}/{n}", 0o750)
    # 2. the principal and its scopes
    mp.psql(pre + f"SELECT maludb_principal_upsert({mp.ql(ref)}, 'agent', {mp.ql(display)}, {mp.ql(home)}, NULL, true);", db)
    for sc in scopes:
        scope, _, level = sc.partition(":")
        mp.psql(pre + f"SELECT maludb_principal_grant_scope({mp.ql(ref)}, {mp.ql(scope)}, {mp.ql(level or 'read')});", db)
    # 3. identity for the vault and the gateway
    for conf in ("/etc/maluos/vault.yaml", "/etc/maluos/gateway.yaml"):
        if os.path.exists(conf):
            yaml_update(conf, lambda d: d.setdefault("identities", {}).__setitem__(user, ref))
    # 4. the agent's own compartment
    try:
        from maluos_vault_client import Vault, VaultError
        v = Vault()
        if v.available() and ref not in {c["name"] for c in v.compartments()}:
            v.create_compartment(ref, owner=ref)
    except Exception as e:
        print(f"  warning: vault compartment not created: {e}", file=sys.stderr)
    # 5. gateway policy
    pol = ["maluctl", "gateway", "policy", "set", "--principal", ref, "--class", cls]
    for flag, val in (("--tiers", tiers), ("--backends", backends), ("--cloud", cloud), ("--egress", egress), ("--budget", budget)):
        if val is not None:
            pol += [flag, val]
    r = subprocess.run(pol, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  warning: gateway policy not set: {(r.stderr or r.stdout).strip()[-200:]}", file=sys.stderr)
    # 6. token (optional) and the unit's files
    os.makedirs(AGENTS, mode=0o755, exist_ok=True)
    tok_file = f"{AGENTS}/{n}.token"
    tok = ""
    if token:
        r = subprocess.run(["maluctl", "gateway", "token", "issue", "--principal", ref, "--name", f"unit {n}"], capture_output=True, text=True)
        if r.returncode == 0:
            tok = r.stdout.strip()
        else:
            print(f"  warning: token not issued: {(r.stderr or r.stdout).strip()[-200:]}", file=sys.stderr)
    with open(os.open(tok_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(tok)
    tcp = {}
    try:
        import yaml
        with open("/etc/maluos/gateway.yaml") as f:
            tcp = (yaml.safe_load(f) or {}).get("tcp") or {}
    except Exception:
        pass
    with open(f"{AGENTS}/{n}.env", "w") as f:
        f.write(f"# MaluOS agent {n}: read by maluos-agent@{n}.service and `maluctl agent run`\n")
        f.write(f"MALUOS_AGENT={n}\nMALUOS_PRINCIPAL={ref}\nMALUOS_GATEWAY_SOCKET=/run/maluos/gateway.sock\nMALUOS_VAULT_SOCKET=/run/maluos/vault.sock\n")
        f.write("MALUDB_MC2DBD_URL=http://127.0.0.1:5329\n")
        if tcp.get("enabled"):
            f.write(f"OPENAI_BASE_URL=http://{tcp.get('host', '127.0.0.1')}:{tcp.get('port', 11435)}/v1\nOLLAMA_HOST=http://{tcp.get('host', '127.0.0.1')}:{tcp.get('port', 11435)}\n")
        f.write(f"MALUOS_AGENT_EXEC={json.dumps(exe or '/usr/lib/maluos/maluos-agent-idle')}\n")
        if owner:
            f.write(f"MALUOS_AGENT_OWNER={owner}\n")
    os.chmod(f"{AGENTS}/{n}.env", 0o644)
    # 7. the registry row (the vault scopes the owner's ledger view by it) and the owner's polkit rule
    try:
        mp.psql(pre + f"""INSERT INTO maluos_agent (name, principal_ref, owner_principal_ref, exec, sandbox) VALUES ({mp.ql(n)}, {mp.ql(ref)}, {mp.ql(owner) if owner else 'NULL'}, {mp.ql(exe or '')}, {mp.ql(sandbox)})
                          ON CONFLICT (name) DO UPDATE SET principal_ref=EXCLUDED.principal_ref, owner_principal_ref=EXCLUDED.owner_principal_ref, exec=EXCLUDED.exec, sandbox=EXCLUDED.sandbox, removed_at=NULL;""", db)
    except Exception as e:
        print(f"  warning: agent registry row not written (maluos-vault schema missing?): {str(e)[-200:]}", file=sys.stderr)
    # 7b. Phase 13 slice 2: the manifest the node registers in the estate's directory, and the accept policy
    write_yaml(MANIFEST.format(n), {"name": n, "display": display, "description": opt_desc(exe, personal), "capabilities": caps, "owner": owner,
                                    "accept_from": accept, "max_classification": maxc, "approve": approve, "tasks": True, "personal": bool(personal)})
    if not os.path.exists(POLICY.format(n)) or accept or approve or maxc is not None:
        write_yaml(POLICY.format(n), {"accept_from": accept, "max_classification": maxc, "approve": approve})
    agents_hint()
    ou = owner_user(owner)
    if ou:
        os.makedirs(os.path.dirname(POLKIT.format(n)), exist_ok=True)
        with open(POLKIT.format(n), "w") as f:
            f.write(POLKIT_RULE.format(name=n, unit=UNIT.format(n), user=ou))
        os.chmod(POLKIT.format(n), 0o644)
    elif os.path.exists(POLKIT.format(n)):
        os.remove(POLKIT.format(n))
    dd = f"/etc/systemd/system/{UNIT.format(n)}.d"
    if SANDBOX[sandbox]:
        os.makedirs(dd, exist_ok=True)
        with open(f"{dd}/sandbox.conf", "w") as f:
            f.write(SANDBOX[sandbox])
    elif os.path.exists(f"{dd}/sandbox.conf"):
        os.remove(f"{dd}/sandbox.conf")
    if personal:
        personal_delegate(n, owner)
    sh("systemctl", "daemon-reload")
    sh("systemctl", "enable", "--quiet", UNIT.format(n))
    if not nostart:
        sh("systemctl", "restart", UNIT.format(n))
    print(f"agent {n}: user {user}, principal {ref} (home scope {home}{', scopes ' + ', '.join(scopes) if scopes else ''}), "
          f"owner {owner or 'none'}, class {cls}{', token' if tok else ''}, sandbox {sandbox}, unit {UNIT.format(n)} {'started' if not nostart else 'enabled (not started)'}")
    print(f"  exec: {exe or '/usr/lib/maluos/maluos-agent-idle (placeholder; set --exec)'}")
    if caps or accept or approve or maxc:
        print(f"  directory: capabilities {', '.join(caps) or '-'}; accepts from {', '.join(accept) or 'its owner only'}" + (f"; ceiling {maxc}" if maxc else "") + (f"; approve {', '.join(approve)}" if approve else ""))
    if personal:
        print(f"  personal: the desk token and the desk key delegated use-only for a week (maluctl agent personal renew); ask it: maluctl agent send {n} \"ask helper …\"")
    print(f"  try:  maluctl agent run {n} -- maluctl gateway whoami")
    return 0


def opt_desc(exe, personal):
    if personal:
        return "the person's own agent: answers them, and asks other agents in the estate on their behalf"
    return ""


def personal_delegate(n, owner, days=7):
    """The owner's desk token and desk key reach the personal agent use-only, for a week (renewed by the Agents app)."""
    ou = owner_user(owner)
    if not ou:
        print("  warning: the personal agent's owner is not a Linux user here; the desk token is not delegated", file=sys.stderr); return
    import datetime
    exp = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for secret in ("office-desk-token", "office-desk-key"):
        r = subprocess.run(["runuser", "-u", ou, "--", "maluctl", "secret", "delegate", "--to", f"agent:{n}", "--secret", secret, "--expires", exp], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  warning: {secret} not delegated to agent:{n}: {(r.stderr or r.stdout).strip()[-160:]}", file=sys.stderr)


def policy(a):
    """maluctl agent policy NAME [set --accept-from ... --max-classification C --approve ... | --clear]: the accept policy on this host."""
    if not a or a[0].startswith("--"):
        sys.exit("policy NAME [set ...]")
    n = a.pop(0)
    if not os.path.exists(f"{AGENTS}/{n}.env"):
        sys.exit(f"no agent {n}")
    sub = a.pop(0) if a and not a[0].startswith("--") else "show"
    pol = read_yaml(POLICY.format(n))
    if sub == "set" or opt(a, "--clear", flag=True):
        need_root()
        if opt(a, "--clear", flag=True):
            pol = {"accept_from": [], "max_classification": None, "approve": []}
        else:
            if "--accept-from" in a:
                pol["accept_from"] = check_accept([x for x in opt(a, "--accept-from", multi=True) for x in x.split(",") if x and x != "none"])
            if "--approve" in a:
                pol["approve"] = check_approve([x for x in opt(a, "--approve", multi=True) for x in x.split(",") if x and x != "none"])
            if "--max-classification" in a:
                m = opt(a, "--max-classification")
                if m not in CLASSIFICATIONS + ("none",):
                    sys.exit("--max-classification public|internal|restricted|prohibited|none")
                pol["max_classification"] = None if m == "none" else m
        pol = {"accept_from": list(pol.get("accept_from") or []), "max_classification": pol.get("max_classification"), "approve": list(pol.get("approve") or [])}
        write_yaml(POLICY.format(n), pol)
        m = read_yaml(MANIFEST.format(n))
        if m:
            m.update(pol); write_yaml(MANIFEST.format(n), m)
        agents_hint()
    if opt(a, "--json", flag=True):
        print(json.dumps({"agent": n, **{"accept_from": pol.get("accept_from") or [], "max_classification": pol.get("max_classification"), "approve": pol.get("approve") or []}, "manifest": read_yaml(MANIFEST.format(n))}, indent=1)); return 0
    print(f"agent {n}: accepts tasks from {', '.join(pol.get('accept_from') or []) or 'its owner only'}; ceiling {pol.get('max_classification') or 'none'}; "
          f"approve {', '.join(pol.get('approve') or []) or 'nothing (runs what it accepts)'}")
    m = read_yaml(MANIFEST.format(n))
    if m:
        print(f"  directory: {', '.join(m.get('capabilities') or []) or 'no capabilities'}; owner {m.get('owner') or 'none'}")
    return 0


def personal(a):
    """maluctl agent personal renew [NAME]: renew the personal agent's delegations (the Agents app calls it weekly)."""
    sub = a.pop(0) if a else "renew"
    n = a.pop(0) if a and not a[0].startswith("--") else "me"
    env = read_env(n)
    if not env:
        sys.exit(f"no agent {n}")
    if sub != "renew":
        sys.exit("personal renew [NAME]")
    need_root()
    personal_delegate(n, env.get("MALUOS_AGENT_OWNER"))
    print(f"agent {n}: delegations renewed for a week"); return 0


def remove(a):
    need_root()
    n = a.pop(0); purge = opt(a, "--purge", flag=True)
    ref, user = f"agent:{n}", f"agent-{n}"
    subprocess.run(["systemctl", "disable", "--now", "--quiet", UNIT.format(n)], check=False)
    for f in (f"{AGENTS}/{n}.env", f"{AGENTS}/{n}.token", f"/etc/systemd/system/{UNIT.format(n)}.d/sandbox.conf", POLKIT.format(n), MANIFEST.format(n), POLICY.format(n)):
        if os.path.exists(f):
            os.remove(f)
    agents_hint()
    sh("systemctl", "daemon-reload")
    mp, st = state()
    pre = f"SET ROLE {mp.qi(st['tenant'])}; SET search_path TO {mp.qi(st['tenant'])}, maludb_core, public; "
    try:
        mp.psql(pre + f"UPDATE maluos_agent SET removed_at=now() WHERE name={mp.ql(n)};", st["database"])
    except Exception:
        pass
    mp.psql(pre + f"SELECT maludb_principal_upsert({mp.ql(ref)}, 'agent', NULL, NULL, NULL, false);", st["database"])
    mp.psql(pre + f"UPDATE maluos_token SET revoked_at=now() WHERE principal_ref={mp.ql(ref)} AND revoked_at IS NULL;", st["database"])
    for conf in ("/etc/maluos/vault.yaml", "/etc/maluos/gateway.yaml"):
        if os.path.exists(conf):
            yaml_update(conf, lambda d: (d.get("identities") or {}).pop(user, None))
    if purge:
        subprocess.run(["deluser", "--system", user], capture_output=True, check=False)
        subprocess.run(["rm", "-rf", f"{HOME}/{n}"], check=False)
    print(f"agent {n}: unit removed, principal {ref} disabled, tokens revoked" + (", user and files deleted" if purge else " (user kept; --purge deletes it)"))
    return 0
