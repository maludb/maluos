"""maluctl estate: this host as a node of its estate (Phase 13 slice 1, docs/phase13-slice1-nodes.md).

A MaluOS server joins the estate the way a desk joins an office: a one-time code the office minted for a node is
exchanged for a node token; the token and an ed25519 node key live in the vault, in the host principal's
compartment (host:<hostname>), stored as the system user maluos-estate; maluos-estate.service heartbeats with the
facts and, every report_s, the report (units, agents, the gateway, vault alerts, updates, disk, memory, load).
A desk does not enrol twice: its desk row is its node record.

  sudo maluctl estate join URL --code CODE [--name NAME] [--kind server|inference|desk] [--hub HOST:PORT] [--no-overlay] [--force]
                                            --kind desk runs `maluctl office enroll` (the desk's enrolment is its node record)
                                            --hub: this host is the estate's hub (the coordinator's own host; one UDP port forwarded to it)
  maluctl estate status [--json]            the enrolment and the last heartbeat; on a desk, its desk enrolment
  maluctl estate report [--json]            what the next report carries (readable without the office)
  maluctl estate heartbeat [--presence online|offline] [--report] [--json]     one heartbeat now (root or maluos-estate)
  maluctl estate nodes [--json] [ID]        the estate as this node (or, on a desk, its owner) may see it
  maluctl estate overlay status|peers [--json]   the estate's network on this host (slice 1b): the interface, the hub, the peers
  sudo maluctl estate overlay up|down|rotate|refresh   by hand (join and leave do it); rotate makes a new key
  sudo maluctl estate leave                 retire the node: the office is told, the units stopped, the secrets removed

Files: /etc/maluos/estate.yaml (no secret), /var/lib/maluos/estate/state.json (the daemon's last outcome),
/var/lib/maluos/overlay/state.json (the overlay service's).
"""
import json, os, pwd, re, socket, subprocess, sys, tempfile, time

sys.path.insert(0, "/usr/lib/maluos")
from maluos_estate import VERSION
from maluos_estate import client as C

MALUCTL = os.environ.get("MALUCTL_BIN", "/usr/bin/maluctl")
VAULT_CONF = os.environ.get("MALUOS_VAULT_CONFIG", "/etc/maluos/vault.yaml")
GATEWAY_CONF = os.environ.get("MALUOS_GATEWAY_CONFIG", "/etc/maluos/gateway.yaml")
NO_UNIT = os.environ.get("MALUOS_ESTATE_NO_UNIT") == "1"
UNIT = "maluos-estate.service"
OVERLAY_UNIT = "maluos-overlay.service"


def opt(args, name, default=None, flag=False):
    if name in args:
        i = args.index(name)
        if flag:
            args.pop(i); return True
        v = args[i + 1]; del args[i:i + 2]; return v
    return False if flag else default


def need_root():
    if os.geteuid() != 0:
        sys.exit("maluctl estate: run with sudo")


def run_as(user, args, input=None, check=True):
    """`maluctl ARGS` as another user (the vault identifies callers by uid), with the test overrides carried along."""
    env = [f"{k}={v}" for k, v in os.environ.items() if k.startswith(("MALUOS_", "MALUCTL_", "PYTHONPATH", "PATH"))]
    cmd = ["runuser", "-u", user, "--", "env", *env, sys.executable, MALUCTL, *args]
    r = subprocess.run(cmd, input=input, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"maluctl {' '.join(args[:2])} as {user}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def maluctl(args, check=True):
    r = subprocess.run([sys.executable, MALUCTL, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"maluctl {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def map_identity(path, user, principal, remove=False):
    """The `identities` map of vault.yaml / gateway.yaml: user -> principal (idempotent; both daemons re-read it)."""
    import yaml
    if not os.path.exists(path):
        return False
    with open(path) as fh:
        conf = yaml.safe_load(fh) or {}
    ids = dict(conf.get("identities") or {})
    if remove:
        if ids.get(user) != principal:
            return False
        ids.pop(user)
    else:
        if ids.get(user) == principal:
            return False
        ids[user] = principal
    conf["identities"] = ids
    head = ""
    with open(path) as fh:
        for line in fh:
            if line.startswith("#"):
                head += line
            else:
                break
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(head)
        yaml.safe_dump(conf, fh, sort_keys=True)
    os.chmod(tmp, 0o644); os.replace(tmp, path)
    return True


def gateway_reload():
    if os.path.exists(os.environ.get("MALUOS_GATEWAY_SOCKET", "/run/maluos/gateway.sock")):
        try:
            maluctl(["gateway", "reload"], check=False)
        except OSError:
            pass


def unit(action, name=UNIT):
    if NO_UNIT or not os.path.exists("/run/systemd/system"):
        return
    r = subprocess.run(["systemctl", action, "--quiet", name] if action != "kill" else ["systemctl", "kill", "-s", "HUP", name], capture_output=True, text=True)
    if r.returncode != 0 and action not in ("stop", "disable", "kill"):
        print(f"  warn: systemctl {action} {name}: {(r.stderr or r.stdout).strip()[-160:]}", file=sys.stderr)


def join(a):
    need_root()
    if not a or a[0].startswith("-"):
        sys.exit("usage: sudo maluctl estate join URL --code CODE [--name NAME] [--kind server|inference|desk]")
    url = a.pop(0).rstrip("/")
    if not url.startswith(("http://", "https://")):
        sys.exit(f"the office URL must start with http:// or https:// ({url})")
    code = opt(a, "--code") or sys.exit("--code CODE: the one-time code the office minted for a node")
    kind = opt(a, "--kind", "server"); name = opt(a, "--name"); force = opt(a, "--force", flag=True)
    hub = opt(a, "--hub"); no_overlay = opt(a, "--no-overlay", flag=True)
    if kind == "desk":
        print("a desk's node record is its desk row: running maluctl office enroll", flush=True)
        os.execv(sys.executable, [sys.executable, MALUCTL, "office", "enroll", url, "--code", code] + (["--name", name] if name else []) + (["--no-overlay"] if no_overlay else []) + a)
    if hub and not re.fullmatch(r"[A-Za-z0-9.-]+:\d{1,5}", hub):
        sys.exit(f"--hub takes HOST:PORT, the hub's endpoint as the spokes dial it (not {hub!r})")
    if kind not in C.KINDS:
        sys.exit(f"--kind must be server, inference or desk (not {kind!r})")
    old = C.read_conf()
    if old and not force:
        sys.exit(f"this host is already node #{(old.get('node') or {}).get('id')} of {old.get('url')}; `sudo maluctl estate leave` first, or --force")
    try:
        pwd.getpwnam(C.USER)
    except KeyError:
        sys.exit(f"no system user {C.USER} (reinstall maluos-estate)")
    hostname = socket.gethostname()
    name = name or hostname
    principal = f"host:{hostname}"
    # 1. the host principal (kind service: the kernel's principal kinds are human, agent and service) and its identity
    maluctl(["principal", "add", principal, "--kind", "service", "--name", hostname, "--home", principal])
    changed = map_identity(VAULT_CONF, C.USER, principal)
    if map_identity(GATEWAY_CONF, C.USER, principal) or changed:
        gateway_reload()
    # 2. the node key: ed25519, made here, the private half straight into the vault as the node, never on disk after
    with tempfile.TemporaryDirectory(prefix="maluos-estate-") as d:
        kp = os.path.join(d, "key")
        r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", principal, "-f", kp], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"ssh-keygen failed: {(r.stderr or r.stdout).strip()[-200:]}")
        priv = open(kp).read(); pub = open(kp + ".pub").read().strip()
        for p in (kp, kp + ".pub"):
            os.remove(p)
    run_as(C.USER, ["secret", "delete", C.SECRET_KEY], check=False)
    run_as(C.USER, ["secret", "add", C.SECRET_KEY, "--kind", "generic", "--provider", "estate", "--stdin"], input=priv)
    # 3. the overlay key (slice 1b): X25519, made here; the private half goes into the vault after the join succeeds
    ov_priv = ov_pub = None
    if not no_overlay:
        from maluos_estate import overlay as OV
        ov_priv, ov_pub = OV.genkey()
    # 4. the join
    body = {"surface": C.SURFACE, "code": code, "kind": kind, "name": name, "principal": principal, "public_key": pub,
            **C.facts(), "components": C.components()}
    if ov_pub:
        body["overlay_public_key"] = ov_pub
    if hub:
        body["overlay_hub"] = {"endpoint": hub}
    try:
        st, r = C.http("POST", url + "/api/v1/estate/join", body)
    except Exception as e:
        sys.exit(f"cannot reach the office at {url}: {str(e)[:160]}")
    if st not in (200, 201):
        sys.exit(f"the office refused the node ({st} {r.get('error') or ''}): {r.get('message') or r}")
    token, node, eps = r.get("token"), r.get("node") or {}, r.get("endpoints") or {}
    if not token or not node.get("id"):
        sys.exit("the office answered without a node token or a node id")
    # 5. the token, into the host principal's compartment, as the node (peer identity: the ledger names the host); the overlay key beside it
    run_as(C.USER, ["secret", "delete", C.SECRET_TOKEN], check=False)
    run_as(C.USER, ["secret", "add", C.SECRET_TOKEN, "--kind", "token", "--provider", "estate", "--env", "MALUOS_ESTATE_TOKEN", "--stdin"], input=token + "\n")
    secrets = {"token": C.SECRET_TOKEN, "key": C.SECRET_KEY}
    if ov_priv:
        run_as(C.USER, ["secret", "delete", C.SECRET_OVERLAY], check=False)
        run_as(C.USER, ["secret", "add", C.SECRET_OVERLAY, "--kind", "generic", "--provider", "estate", "--stdin"], input=ov_priv + "\n")
        secrets["overlay"] = C.SECRET_OVERLAY
    conf = {"surface": r.get("surface", C.SURFACE), "url": url, "office": r.get("office") or {"name": None, "url": url},
            "node": {"id": node.get("id"), "kind": node.get("kind") or kind, "name": node.get("name") or name, "status": node.get("status")},
            "enrolled_by": r.get("enrolled_by") or {}, "endpoints": eps, "heartbeat_s": int(r.get("heartbeat_s") or 60), "report_s": int(r.get("report_s") or 300),
            "principal": principal, "user": C.USER, "secrets": secrets, "public_key": pub,
            "overlay": (r.get("overlay") if ov_priv else None) if r.get("overlay") or not ov_priv else {"pending": True, "role": "hub" if hub else "spoke"},
            "joined_at": C.utc(), "maluos_estate": VERSION}
    if ov_priv and not r.get("overlay"):
        conf["overlay"] = {"role": "hub" if hub else "spoke", "address": None, "hub": None}      # a key sent, no hub yet: the service waits
    C.write_conf(conf)
    try:
        os.makedirs(C.STATE_DIR, exist_ok=True)
        pw = pwd.getpwnam(C.USER); os.chown(C.STATE_DIR, pw.pw_uid, pw.pw_gid)
    except OSError:
        pass
    unit("enable"); unit("restart")
    if ov_priv:
        unit("enable", OVERLAY_UNIT); unit("restart", OVERLAY_UNIT)
    print(f"joined: {conf['node']['kind']} '{conf['node']['name']}' (#{conf['node']['id']}) at {conf['office'].get('name') or url} as {principal}")
    print(f"  token:    vault {principal}/{C.SECRET_TOKEN}; key {principal}/{C.SECRET_KEY} (stored as {C.USER})")
    print(f"  reports:  every {conf['report_s']} s with the heartbeat (every {conf['heartbeat_s']} s): {UNIT}; maluctl estate report shows one")
    print(f"  estate:   maluctl estate nodes")
    print("  overlay:  " + overlay_line(conf))
    return 0


def overlay_line(conf):
    """One line on the host's place on the estate's network, from the enrolment (join) and the service's state."""
    o = conf.get("overlay")
    if o is None:
        return "off (--no-overlay): no address on the estate's network"
    if not o.get("address"):
        return "a key was sent; no hub has joined the estate yet (the service waits: maluctl estate overlay status)"
    from maluos_estate import overlay as OV
    st = OV.read_state() or {}
    where = f"{o['address']}/{o.get('prefix') or 16} as {o.get('name') or '?'}, {o.get('role')}"
    if o.get("role") == "hub":
        where += f" listening on udp {o.get('listen_port') or OV.LISTEN_PORT}"
    elif o.get("hub"):
        where += f" of the hub at {o['hub'].get('endpoint')} ({o['hub'].get('address')})"
    return where + (f"; {OVERLAY_UNIT} configured the interface at {st.get('ts')}" if st.get("configured") else f"; {OVERLAY_UNIT} brings the tunnel up")


def status(a):
    as_json = opt(a, "--json", flag=True)
    conf = C.read_conf()
    desk = C.desk_conf() if not conf else None
    out = {"joined": bool(conf), "conf": C.CONF}
    if conf:
        out.update({k: conf.get(k) for k in ("surface", "url", "office", "node", "enrolled_by", "endpoints", "heartbeat_s", "report_s", "principal", "user", "joined_at", "overlay")})
        out["last_heartbeat"] = C.read_state()
        from maluos_estate import overlay as OV
        out["overlay_state"] = OV.read_state()
        if not NO_UNIT and os.path.exists("/run/systemd/system"):
            out["unit"] = subprocess.run(["systemctl", "is-active", UNIT], capture_output=True, text=True).stdout.strip()
    elif desk:
        out["desk"] = {"office": desk.get("office"), "url": desk.get("url"), "desk": desk.get("desk"), "estate": bool((desk.get("endpoints") or {}).get("estate"))}
    if as_json:
        print(json.dumps(out, indent=2, default=str)); return 0
    if not conf:
        if desk:
            d, o = desk.get("desk") or {}, desk.get("office") or {}
            print(f"this desk is node #{d.get('id')} of {o.get('name') or desk.get('url')} (its desk enrolment: maluctl office status)")
            print("estate:     " + ("the office publishes the estate to this desk's owner: maluctl estate nodes" if out["desk"]["estate"] else "not published to this desk (endpoints.estate)"))
            return 0
        print(f"not joined: sudo maluctl estate join URL --code CODE  (no {C.CONF})"); return 1
    n, o = conf.get("node") or {}, conf.get("office") or {}
    print(f"office:     {o.get('name') or '?'}  {conf.get('url')}  (surface {conf.get('surface')})")
    print(f"node:       {n.get('kind')} '{n.get('name')}'  (#{n.get('id')})  joined {conf.get('joined_at')}")
    print(f"principal:  {conf.get('principal')}  (secrets stored as {conf.get('user')}: {C.SECRET_TOKEN}, {C.SECRET_KEY})")
    print(f"heartbeat:  every {conf.get('heartbeat_s')} s, the report every {conf.get('report_s')} s" + (f"  ({UNIT} {out['unit']})" if out.get("unit") else ""))
    hb = out.get("last_heartbeat")
    if hb:
        print(f"last:       {hb.get('ts')}  {'ok' if hb.get('ok') else 'FAILED'}  presence {hb.get('presence')}" + (f"  ({hb.get('error')})" if hb.get("error") else "")
              + ("  RETIRED by the office (sudo maluctl estate leave)" if hb.get("revoked") else "") + (f"  report {hb['last_report_at']}" if hb.get("last_report_at") else ""))
    else:
        print("last:       no heartbeat yet")
    print("overlay:    " + overlay_line(conf))
    return 0


def report_cmd(a):
    from maluos_estate import report as R
    rep = R.report()
    if opt(a, "--json", flag=True):
        print(json.dumps(rep, indent=None if opt(a, "--compact", flag=True) else 1, default=str)); return 0
    print(R.summary(rep)); return 0


def heartbeat(a):
    as_json = opt(a, "--json", flag=True); presence = opt(a, "--presence", "online"); with_report = opt(a, "--report", flag=True)
    conf = C.read_conf() or sys.exit(f"not joined (no {C.CONF})")
    rep = None
    if with_report:
        from maluos_estate import report as R
        rep = R.report()
    try:
        tok = C.token(conf)
    except Exception as e:
        sys.exit(f"the node token is not readable from the vault as {pwd.getpwuid(os.getuid()).pw_name}: {str(e)[:160]}")
    res = C.heartbeat(conf, tok, presence, rep)
    if res.get("overlay_changed"):
        C.overlay_hint()                      # slice 1b: the overlay service refreshes now
    if as_json:
        print(json.dumps(res, default=str))
    elif res["ok"]:
        n = res["node"] or {}
        print(f"ok: node {n.get('name')} (#{n.get('id')}) {res['presence']} at {res['ts']}" + (" with the report" if rep else ""))
    else:
        print(f"heartbeat failed: {res['error']}" + ("  (retired: sudo maluctl estate leave)" if res["revoked"] else ""), file=sys.stderr)
    return 0 if res["ok"] else 1


def nodes_cmd(a):
    as_json = opt(a, "--json", flag=True)
    node_id = a.pop(0) if a and not a[0].startswith("-") else None
    conf = C.read_conf()
    tok, url, via = None, None, None
    if conf:
        try:
            tok, url, via = C.token(conf), C.endpoint(conf, "nodes"), f"node #{(conf.get('node') or {}).get('id')}"
        except Exception as e:
            err = f"{e.__class__.__name__}: {str(e)[:120]}"
            tok = None
    if tok is None:
        desk = C.desk_conf()
        ep = (desk.get("endpoints") or {}).get("estate") if desk else None
        if desk and ep:
            try:
                from maluos_vault_client import Vault
                tok = os.environ.get("MALUOS_OFFICE_TOKEN") or Vault(os.environ.get("MALUOS_VAULT_SOCKET")).value("office-desk-token", "read", purpose="estate nodes")["value"]
                url, via = ep, f"desk #{(desk.get('desk') or {}).get('id')}"
            except Exception as e:
                sys.exit(f"the desk token is not readable from the vault: {str(e)[:160]}")
        elif desk:
            sys.exit("the office does not publish the estate to this desk (no endpoints.estate: the owner is not a system manager)")
        elif conf:
            sys.exit(f"the node token is not readable from the vault as {pwd.getpwuid(os.getuid()).pw_name} ({err}); run as root or {C.USER}")
        else:
            sys.exit(f"not joined (no {C.CONF}) and not an enrolled desk (no {C.OFFICE_CONF})")
    try:
        st, r = C.nodes(url, tok, node_id)
    except Exception as e:
        sys.exit(f"cannot reach the office: {str(e)[:160]}")
    if st != 200:
        sys.exit(f"the office answered {st} {r.get('error') or ''}: {r.get('message') or ''}")
    if as_json:
        print(json.dumps(r, indent=1, default=str)); return 0
    if node_id:
        n = r.get("node") or r
        print(f"{n.get('kind')} '{n.get('name')}' (#{n.get('id')}) {n.get('presence')} health {n.get('health')}: {n.get('summary') or ''}")
        rep = n.get("report")
        if rep:
            from maluos_estate import report as R
            print(R.summary(rep))
        return 0
    ns, al = r.get("nodes") or [], r.get("alerts") or []
    print(f"estate of {(r.get('office') or {}).get('name') or url} as {via}: {len(ns)} nodes, {sum(1 for x in ns if x.get('presence') == 'online')} online, {sum(1 for x in al if not x.get('cleared_at'))} open alerts")
    for n in ns:
        ov = (n.get("overlay") or {}).get("address")
        print(f"  #{n.get('id'):<4} {n.get('kind') or '':<9} {n.get('name') or '':<20} {n.get('presence') or '':<8} {n.get('health') or '':<8} {(ov or '-'):<15} {n.get('summary') or ''}")
    for x in al:
        print(f"  alert #{x.get('id')} {x.get('node') or '?'}: {x.get('severity')} {x.get('kind')}: {x.get('title')}" + (f"  (cleared {x['cleared_at']})" if x.get("cleared_at") else ""))
    return 0


def leave(a):
    need_root()
    conf = C.read_conf() or sys.exit(f"not joined (no {C.CONF})")
    told = "not told (no token)"
    tok = None
    try:
        tok = run_as(C.USER, ["secret", "show", C.SECRET_TOKEN]).strip() or None
    except Exception:
        tok = None
    unit("disable"); unit("stop")
    if (conf.get("secrets") or {}).get("overlay"):
        from maluos_estate import overlay as OV
        unit("disable", OVERLAY_UNIT); unit("stop", OVERLAY_UNIT)
        try:
            OV.down()
        except Exception as e:
            print(f"  warn: overlay down: {e}", file=sys.stderr)
    if tok:
        try:
            st, r = C.leave(conf, tok)
            told = "told; node retired" if st == 200 else f"answered {st} {r.get('error') or ''}: {r.get('message') or ''}".strip()
        except Exception as e:
            told = f"unreachable ({str(e)[:100]}); retire the node from the office's Estate"
    for s in (C.SECRET_TOKEN, C.SECRET_KEY) + ((C.SECRET_OVERLAY,) if (conf.get("secrets") or {}).get("overlay") else ()):
        try:
            run_as(C.USER, ["secret", "delete", s])
        except Exception as e:
            print(f"  warn: {e}", file=sys.stderr)
    for p in (C.CONF, C.STATE):
        try:
            os.remove(p)
        except OSError:
            pass
    principal = conf.get("principal")
    if principal:
        changed = map_identity(VAULT_CONF, C.USER, principal, remove=True)
        if map_identity(GATEWAY_CONF, C.USER, principal, remove=True) or changed:
            gateway_reload()
    print(f"left {(conf.get('office') or {}).get('name') or conf.get('url')}: the office was {told}; the unit stopped, the token and the key removed"
          + ("; the overlay tunnel down, its key removed" if (conf.get("secrets") or {}).get("overlay") else ""))
    return 0


def overlay_cmd(a):
    """maluctl estate overlay status|peers|up|down|rotate|refresh: the estate's network on this host (slice 1b)."""
    from maluos_estate import overlay as OV
    sub = a.pop(0) if a and not a[0].startswith("-") else "status"
    as_json = opt(a, "--json", flag=True)
    kind, conf = OV.enrolment()
    if sub in ("status", "peers"):
        st = OV.status()
        if as_json:
            print(json.dumps({"enrolment": kind, "overlay": (conf or {}).get("overlay"), "state": st}, indent=1, default=str)); return 0
        if not conf:
            print(f"no enrolment (no {C.CONF}, no {C.OFFICE_CONF}): no overlay"); return 1
        if not st:
            print("overlay:    " + overlay_line(conf)); return 0 if (conf.get("overlay") or {}).get("address") else 1
        if sub == "status":
            print(f"interface:  {st.get('interface') or OV.IFACE}  {'up' if st.get('interface_up', st.get('configured')) else 'down'}  {st.get('address')}/{st.get('prefix')}  {st.get('name') or ''}  ({st.get('role')})")
            h = st.get("hub") or {}
            print("hub:        " + (f"{h.get('endpoint')} ({h.get('address')})" if h else "this host" if st.get("role") == "hub" else "none yet"))
            print(f"refreshed:  {st.get('ts')}  version {st.get('version')}  {len(st.get('peers') or [])} peer(s), {len(st.get('names') or [])} name(s)" + (f"  {st.get('reason')}" if st.get("reason") else ""))
        for p in st.get("peers") or []:
            hs = p.get("last_handshake")
            age = f"handshake {int(time.time()) - hs} s ago" if hs else "no handshake yet"
            print(f"  peer  {p.get('name') or '?':<24} {p.get('address') or '-':<15} {age}" + (f"  rx {p.get('rx')} tx {p.get('tx')}" if p.get("rx") is not None else ""))
        return 0
    if sub == "refresh":
        OV.hint(); print("asked maluos-overlay to refresh now"); return 0
    need_root()
    if not conf:
        sys.exit(f"no enrolment (no {C.CONF}, no {C.OFFICE_CONF})")
    if sub == "down":
        OV.down(); print(f"the {OV.IFACE} interface is down and the names removed (the service brings it back on its next refresh unless stopped)"); return 0
    if sub == "up":
        priv = OV.key_for(kind, conf); tok = OV.token_for(kind, conf)
        try:
            st_, ans = OV.fetch(kind, conf, tok)
        except Exception as e:
            st_, ans = 0, {"error": str(e)[:120]}
        d = OV.reconcile(kind, conf, tok, priv, ans if st_ == 200 else None)
        print(f"{OV.IFACE}: " + (f"{d['address']}/{d['prefix']} {d['role']}, {len(d['peers'] or [])} peer(s)" if d else "not configured (no hub yet, or no overlay for this host)")); return 0
    if sub == "rotate":
        priv, pub = OV.genkey()
        user = C.USER if kind == "node" else (conf.get("owner") or {}).get("login")
        run_as(user, ["secret", "delete", C.SECRET_OVERLAY], check=False)
        run_as(user, ["secret", "add", C.SECRET_OVERLAY, "--kind", "generic", "--provider", "estate", "--stdin"], input=priv + "\n")
        tok = OV.token_for(kind, conf)
        st_, r = C.overlay_key(conf, tok, pub)
        if st_ != 200:
            sys.exit(f"the office refused the new key ({st_} {r.get('error') or ''}): {r.get('message') or r}")
        if kind == "node" and r.get("overlay"):
            conf["overlay"] = r["overlay"]; C.write_conf(conf)
        if NO_UNIT:
            try:
                st_, ans = OV.fetch(kind, conf, tok)
            except Exception:
                st_, ans = 0, None
            OV.reconcile(kind, conf, tok, priv, ans if st_ == 200 else None)
        else:
            unit("kill", OVERLAY_UNIT)
        print(f"rotated: the office has the new key; the tunnel re-keys on the service's refresh ({OVERLAY_UNIT})"); return 0
    sys.exit(f"maluctl estate overlay: status|peers|up|down|rotate|refresh (not {sub!r})")


def main(a):
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    cmd = a.pop(0)
    try:
        if cmd == "join":
            return join(a)
        if cmd == "status":
            return status(a)
        if cmd == "report":
            return report_cmd(a)
        if cmd == "heartbeat":
            return heartbeat(a)
        if cmd == "nodes":
            return nodes_cmd(a)
        if cmd == "leave":
            return leave(a)
        if cmd == "overlay":
            return overlay_cmd(a)
    except RuntimeError as e:
        sys.exit(f"maluctl estate {cmd}: {e}")
    print(__doc__); return 2
