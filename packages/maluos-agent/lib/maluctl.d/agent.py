"""maluctl agent: an agent as a system concept.

One command creates everything an agent needs on a MaluOS host, and one
removes it: a Linux system user, a MaluDB principal with scope grants, the
identity mapping for the vault and the gateway, its own vault compartment,
a gateway policy (class, tiers, cloud, egress ceiling, budget), optionally
a gateway token, and a hardened systemd unit (maluos-agent@NAME) that runs
the agent's command as that user with the MaluOS endpoints in its
environment.

  maluctl agent create NAME [--exec CMD] [--name "Display"] [--home SCOPE] [--scope SCOPE:read|write ...]
                     [--class agent] [--tiers a,b] [--backends a,b] [--cloud yes|no] [--egress public|internal|restricted]
                     [--budget usd_per_day=1] [--token] [--sandbox standard|strict] [--no-start]
  maluctl agent list | show NAME
  maluctl agent start|stop|restart|status|logs NAME
  maluctl agent run NAME -- CMD...            run a command as the agent (its identity, its environment)
  maluctl agent remove NAME [--purge]         stop the unit, disable the principal; --purge also deletes the user and its files

The agent's process sees MALUOS_PRINCIPAL, MALUOS_GATEWAY_SOCKET,
MALUOS_VAULT_SOCKET, MALUDB_MC2DBD_URL, OPENAI_BASE_URL (the TCP listener,
when enabled) and, with --token, the gateway token as the credential file
$CREDENTIALS_DIRECTORY/gateway-token.
"""
import json, os, pwd, re, subprocess, sys
sys.path.insert(0, "/usr/lib/maluos")

AGENTS = "/etc/maluos/agents"
HOME = "/var/lib/maluos/agents"
UNIT = "maluos-agent@{}.service"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
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
        names = sorted(f[:-4] for f in os.listdir(AGENTS) if f.endswith(".env")) if os.path.isdir(AGENTS) else []
        if not names:
            print("(no agents; maluctl agent create NAME --exec CMD)"); return 0
        for n in names:
            st = subprocess.run(["systemctl", "is-active", UNIT.format(n)], capture_output=True, text=True).stdout.strip()
            print(f"{n:20} agent:{n:20} user agent-{n:18} unit {st}")
        return 0
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
        for line in open(f"{AGENTS}/{n}.env"):
            if "=" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("=", 1); env[k] = v.strip('"')
        env["HOME"] = f"{HOME}/{n}"
        os.execvpe("runuser", ["runuser", "-u", f"agent-{n}", "--", *a], env)
    if cmd == "create":
        return create(a)
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
    if sandbox not in SANDBOX:
        sys.exit("--sandbox standard|strict")
    mp, st = state()
    db, tenant = st["database"], st["tenant"]
    user = f"agent-{n}"
    ref = f"agent:{n}"
    # 1. the Linux user and its home
    try:
        pwd.getpwnam(user)
    except KeyError:
        sh("adduser", "--system", "--group", "--home", f"{HOME}/{n}", "--no-create-home", "--shell", "/usr/sbin/nologin", user)
    os.makedirs(f"{HOME}/{n}", exist_ok=True)
    u = pwd.getpwnam(user); os.chown(f"{HOME}/{n}", u.pw_uid, u.pw_gid); os.chmod(f"{HOME}/{n}", 0o750)
    # 2. the principal and its scopes
    pre = f"SET ROLE {mp.qi(tenant)}; SET search_path TO {mp.qi(tenant)}, maludb_core, public; "
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
    os.chmod(f"{AGENTS}/{n}.env", 0o644)
    dd = f"/etc/systemd/system/{UNIT.format(n)}.d"
    if SANDBOX[sandbox]:
        os.makedirs(dd, exist_ok=True)
        with open(f"{dd}/sandbox.conf", "w") as f:
            f.write(SANDBOX[sandbox])
    elif os.path.exists(f"{dd}/sandbox.conf"):
        os.remove(f"{dd}/sandbox.conf")
    sh("systemctl", "daemon-reload")
    sh("systemctl", "enable", "--quiet", UNIT.format(n))
    if not nostart:
        sh("systemctl", "restart", UNIT.format(n))
    print(f"agent {n}: user {user}, principal {ref} (home scope {home}{', scopes ' + ', '.join(scopes) if scopes else ''}), "
          f"class {cls}{', token' if tok else ''}, sandbox {sandbox}, unit {UNIT.format(n)} {'started' if not nostart else 'enabled (not started)'}")
    print(f"  exec: {exe or '/usr/lib/maluos/maluos-agent-idle (placeholder; set --exec)'}")
    print(f"  try:  maluctl agent run {n} -- maluctl gateway whoami")
    return 0


def remove(a):
    need_root()
    n = a.pop(0); purge = opt(a, "--purge", flag=True)
    ref, user = f"agent:{n}", f"agent-{n}"
    subprocess.run(["systemctl", "disable", "--now", "--quiet", UNIT.format(n)], check=False)
    for f in (f"{AGENTS}/{n}.env", f"{AGENTS}/{n}.token", f"/etc/systemd/system/{UNIT.format(n)}.d/sandbox.conf"):
        if os.path.exists(f):
            os.remove(f)
    sh("systemctl", "daemon-reload")
    mp, st = state()
    pre = f"SET ROLE {mp.qi(st['tenant'])}; SET search_path TO {mp.qi(st['tenant'])}, maludb_core, public; "
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
