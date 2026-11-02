"""maluctl memory: the memory face of this host (Phase 13 slice 4, docs/phase13-slice4-memory.md).

  maluctl memory status [--json]                         the face: socket, listener, the guest principal, the shared scopes, holders, peers, copies
  maluctl memory facts [--json]                          the memory facts the heartbeat carries (scopes held and shared, ceiling, port)
  maluctl memory whoami                                  who you are to the face: your principal, its read and write scopes
  maluctl memory recall "QUERY" [--scope S]... [--estate] [--classification C] [--limit N] [--kind K]... [--detail] [--as PRINCIPAL] [--json]
  maluctl memory remember "TEXT" --scope S [--kind note|summary|observation|decision|profile] [--title T] [--confidence 0..1]
                                 [--source REF] [--sensitivity public|internal|restricted|prohibited] [--detail JSON] [--occurred-at TS] [--as PRINCIPAL]
  maluctl memory forget ID [--as PRINCIPAL]              tombstone a memory you may write (never a replicated copy)
  maluctl memory usage [--since 1h] [--limit N] [--json] the face's ledger rows: queries answered and asked, never their text
  sudo maluctl memory share SCOPE... [--max CLS]        serve these scopes to the estate (the guest principal's read grants); --max this host's ceiling
  sudo maluctl memory unshare SCOPE...|--all
  sudo maluctl memory expose [--bind overlay|ADDR] [--port 11437]     listen for the estate (the overlay address by default)
  sudo maluctl memory unexpose
  sudo maluctl memory keys                               grant the face a read on this host's signing keys (the node's, the desk owner's), to sign its queries
  sudo maluctl memory sync [--json]                      copy the summaries the rules replicate to this host now (the face does it hourly)
  sudo maluctl memory reload                             re-read /etc/maluos/memory.yaml and the listener
  maluctl memory embed [--json]                          semantic recall (slice 4b): the embedding model, the space, how much is embedded
  sudo maluctl memory embed MODEL [--pull] [--url URL|gateway] [--min-score 0.35]   set the model (pulled through the gateway with --pull); new memories get vectors
  sudo maluctl memory embed --backfill | --probe | --off  vectors for what lacks one; a probe of the model; text recall again
"""
import datetime, http.client, json, os, socket, subprocess, sys

SOCKET = os.environ.get("MALUOS_MEMORY_SOCKET", "/run/maluos/memory.sock")
CONF = os.environ.get("MALUOS_MEMORY_CONFIG", "/etc/maluos/memory.yaml")
ESTATE_CONF = os.environ.get("MALUOS_ESTATE_CONF", "/etc/maluos/estate.yaml")
OFFICE_CONF = os.environ.get("MALUOS_OFFICE_CONF", "/etc/maluos/office.yaml")
MALUCTL = os.environ.get("MALUCTL_BIN", "/usr/bin/maluctl")
FACE_USER = os.environ.get("MALUOS_MEMORY_USER", "maluos-memory")
ESTATE_USER = os.environ.get("MALUOS_ESTATE_USER", "maluos-estate")
SENS = ("public", "internal", "restricted", "prohibited")


class _Conn(http.client.HTTPConnection):
    def __init__(self, path, timeout=60):
        super().__init__("maluos-memory", timeout=timeout); self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(self.timeout); s.connect(self._path); self.sock = s


def api(method, path, body=None, timeout=60):
    if not os.path.exists(SOCKET):
        sys.exit(f"the memory face is not running (no {SOCKET}): systemctl status maluos-memory")
    c = _Conn(SOCKET, timeout)
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    r = c.getresponse(); raw = r.read(); c.close()
    try:
        d = json.loads(raw or b"{}")
    except ValueError:
        d = {"error": {"code": "bad_answer", "message": raw[:200].decode(errors="replace")}}
    if r.status >= 400:
        e = d.get("error") or {}
        sys.exit(f"maluctl memory: {e.get('code') or r.status}: {e.get('message') or ''}")
    return d


def opt(a, name, default=None, flag=False, multi=False):
    vals = []
    i = 0
    while i < len(a):
        if a[i] == name:
            if flag:
                a.pop(i); return True
            if i + 1 >= len(a):
                sys.exit(f"{name} needs a value")
            vals.append(a[i + 1]); del a[i:i + 2]; continue
        if a[i].startswith(name + "="):
            vals.append(a[i][len(name) + 1:]); del a[i]; continue
        i += 1
    if flag:
        return False
    if multi:
        return vals
    return vals[-1] if vals else default


def need_root():
    if os.geteuid() != 0:
        sys.exit("maluctl memory: run with sudo")


def state():
    """The provisioning state (database, tenant) and the firstboot helpers, as `maluctl agent` reads them."""
    sys.path.insert(0, "/usr/lib/maluos")
    import maluos_provision as mp
    try:
        with open(os.environ.get("MALUOS_PROVISIONED", mp.DONE)) as fh:
            st = json.load(fh)
    except OSError:
        sys.exit("this host is not provisioned (no firstboot state)")
    return mp, st


def _yaml(path):
    try:
        import yaml
        with open(path) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def conf_read():
    return _yaml(CONF)


def conf_write(d):
    import yaml
    head = ""
    if os.path.exists(CONF):
        with open(CONF) as fh:
            for line in fh:
                if line.startswith("#"):
                    head += line
                else:
                    break
    tmp = CONF + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(head or "# MaluOS memory face (maluos-memory). database/tenant are set by first boot; tcp by `maluctl memory expose`.\n")
        yaml.safe_dump(d, fh, sort_keys=True)
    os.chmod(tmp, 0o644); os.replace(tmp, CONF)


def run_as(user, args, check=True):
    env = [f"{k}={v}" for k, v in os.environ.items() if k.startswith(("MALUOS_", "MALUCTL_", "PYTHONPATH", "PATH"))]
    r = subprocess.run(["runuser", "-u", user, "--", "env", *env, sys.executable, MALUCTL, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"maluctl {' '.join(args[:2])} as {user}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def since_ts(s):
    if not s:
        return None
    units = {"m": 60, "h": 3600, "d": 86400}
    if s[-1] in units and s[:-1].isdigit():
        t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=int(s[:-1]) * units[s[-1]])
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")
    return s


# -- commands
def status(a):
    as_json = opt(a, "--json", flag=True)
    s = api("GET", "/v1/status")
    if as_json:
        print(json.dumps(s, indent=1)); return 0
    g = s["guest"]
    tcp = s["tcp"]
    print(f"face:      maluos-memory {s['version']} on {s['socket']} (api {s['api_version']}, since {s['started']})")
    bound = f"{tcp['bound'][0]}:{tcp['bound'][1]}" if tcp.get("bound") else ("not listening" + (" (no overlay address yet)" if tcp.get("enabled") else ""))
    print(f"estate:    {'exposed' if tcp.get('enabled') else 'not exposed'}; {bound}" + (f"; overlay {tcp['overlay_address']}" if tcp.get("overlay_address") else ""))
    print(f"guest:     {g['principal']} {'present' if g['present'] else 'MISSING (run first boot or `maluctl memory share`)'}; shared {', '.join(g['shared']) or 'nothing'}; ceiling {g['max_classification']}")
    for src, m in (s.get("memberships") or {}).items():
        k = s["signing_keys"].get(src)
        print(f"{src + ':':<11}{m['node']} as {m['principal']}; signing key {m['key']} {'readable' if k is True else 'NOT readable (sudo maluctl memory keys): ' + str(k)}")
    print(f"holders:   {len(s['holders'])} published to this host" + ("" if not s["holders"] else ": " + "; ".join(f"{h['name'] or h['node']} ({', '.join(h['scopes'])})" for h in s["holders"])))
    print(f"peers:     {len(s['peers'])} may ask this host" + ("" if not s["peers"] else ": " + "; ".join(f"{p['name'] or p['node']} ({', '.join(p['scopes'])})" for p in s["peers"])))
    if s.get("copies"):
        print("copies:    " + "; ".join(f"{c['count']} of {c['scope']} from {c['node']}" for c in s["copies"]))
    e = s.get("embed") or {}
    print("embed:     " + (f"{e['model']} via {e.get('url') or 'gateway'} ({e['embedded']} of {e['total']} memories in {e['space']})" + (f"; last error {e['last_error']}" if e.get("last_error") else "")
                          if e.get("model") else "no model (text recall); `sudo maluctl memory embed MODEL`"))
    return 0


def embed(a):
    """maluctl memory embed [MODEL [--url URL|gateway] [--pull] | --off | --backfill | --probe] [--json]"""
    as_json = opt(a, "--json", flag=True); off = opt(a, "--off", flag=True); backfill = opt(a, "--backfill", flag=True); probe = opt(a, "--probe", flag=True)
    pull = opt(a, "--pull", flag=True); url = opt(a, "--url"); minscore = opt(a, "--min-score")
    model = next((x for x in a if not x.startswith("--")), None)
    if off or model or url or minscore is not None:
        need_root()
        d = conf_read(); e = dict(d.get("embed") or {})
        if off:
            e["model"] = None
        if model:
            if pull:
                r = subprocess.run(["maluctl", "gateway", "ollama", "pull", model], capture_output=True, text=True)
                print((r.stdout or r.stderr).strip()[-300:])
                if r.returncode != 0:
                    sys.exit(f"maluctl memory embed: the pull failed; the model is not set")
            e["model"] = model
        if url:
            e["url"] = url
        if minscore is not None:
            e["min_score"] = float(minscore)
        d["embed"] = e; conf_write(d)
        api("POST", "/v1/reload", {})
        if e.get("model"):
            r = api("POST", "/v1/embed", {"probe": True})
            print(f"embedding: {r['model']} via {e.get('url') or 'gateway'} (dim {r['dim']}, space {r['space']}); vectors for new memories; `sudo maluctl memory embed --backfill` for the rest")
        else:
            print("embedding: off (text recall); the vectors stay for a later `maluctl memory embed MODEL`")
        return 0
    if probe:
        need_root(); r = api("POST", "/v1/embed", {"probe": True}); print(json.dumps(r, indent=1) if as_json else f"probe ok: {r['model']} dim {r['dim']}"); return 0
    if backfill:
        need_root(); r = api("POST", "/v1/embed", {"backfill": True}, timeout=600)
        if as_json:
            print(json.dumps(r, indent=1)); return 0
        print(f"backfill: embedded {r['embedded']}, failed {r['failed']}, remaining {r['remaining']}" + (f"; error {r['error']}" if r.get("error") else "") + (f"; {r['note']}" if r.get("note") else ""))
        return 1 if r.get("failed") else 0
    e = api("GET", "/v1/embed")
    if as_json:
        print(json.dumps(e, indent=1)); return 0
    if not e.get("model"):
        print("embedding: no model (text recall). `sudo maluctl memory embed MODEL [--pull]` sets one, e.g. nomic-embed-text through the gateway"); return 0
    print(f"embedding: {e['model']} via {e.get('url') or 'gateway'}; space {e['space']}; {e['embedded']} of {e['total']} memories embedded; min score {e.get('min_score')}"
          + (f"; dim {e['dim']}, last ok {e['last_ok_at']}" if e.get("dim") else "") + (f"\n  last error {e['last_error_at']}: {e['last_error']}" if e.get("last_error") else ""))
    return 0


def facts(a):
    as_json = opt(a, "--json", flag=True)
    f = api("GET", "/v1/facts")
    if as_json:
        print(json.dumps(f, indent=1)); return 0
    print(f"shared:    {', '.join(f['shared']) or 'nothing'}; ceiling {f['max_classification']}; port {f['port']}; {'exposed' if f.get('exposed') else 'not exposed'}")
    for s in f["scopes"]:
        print(f"  {s['scope']:<14} {s['count']:>5}  " + ", ".join(f"{k} {n}" for k, n in sorted(s['kinds'].items())) + (f"  updated {s['updated_at']}" if s.get("updated_at") else ""))
    if not f["scopes"]:
        print("  (no departmental or enterprise memory on this host yet)")
    return 0


def whoami(a):
    w = api("GET", "/v1/whoami")
    print(f"principal: {w['principal']} ({w['user']}, uid {w['uid']}{', operator' if w['operator'] else ''}){'' if w['enrolled'] else '  NOT a principal of this host'}")
    if w["enrolled"]:
        print(f"reads:     {', '.join(w['read'] or []) or '-'}\nwrites:    {', '.join(w['write'] or []) or '-'}\nceiling:   {w['max_sensitivity']}")
    return 0


def recall(a):
    as_json = opt(a, "--json", flag=True); estate = opt(a, "--estate", flag=True); detail = opt(a, "--detail", flag=True)
    scopes = opt(a, "--scope", multi=True); kinds = opt(a, "--kind", multi=True); cls = opt(a, "--classification", "internal"); limit = int(opt(a, "--limit", "12")); who = opt(a, "--as")
    q = " ".join(x for x in a if not x.startswith("--")).strip() or sys.exit("recall QUERY")
    body = {"query": q, "classification": cls, "limit": limit, "estate": estate, "detail": detail}
    if scopes:
        body["scopes"] = scopes
    if kinds:
        body["kinds"] = kinds
    if who:
        body["as"] = who
    r = api("POST", "/v1/recall", body)
    if as_json:
        print(json.dumps(r, indent=1)); return 0
    print(f"{r['count']} claim(s) for {r['principal']} in {', '.join(r['scopes'])}" + (f"; holders asked {', '.join(r['holders']) or 'none'}" if estate else "")
          + (f"; failed {', '.join(f['holder'] + ' (' + str(f.get('error')) + ')' for f in r['holders_failed'])}" if r.get("holders_failed") else ""))
    for c in r["claims"]:
        src = c.get("source") or {}
        print(f"  #{c['rank']:<3} {c['text'][:160]}")
        print(f"       {c['scope']}  {c['kind']}  {c['sensitivity']}" + (f"  confidence {c['confidence']}" if c.get("confidence") is not None else "")
              + (f"  source {src['ref']}" if src.get("ref") else "") + f"  by {c.get('writer') or '?'}  at {c.get('observed_at') or c.get('recorded_at') or '?'}"
              + f"  holder {c.get('holder')}" + (f"  (copy of {c['origin']['node']}#{c['origin']['id']})" if c.get("origin") else "") + f"  id {c['id']}"
              + (f"  semantic {c['score']}" if c.get("match") == "semantic" else ""))
        if detail and c.get("detail") is not None:
            print(f"       detail {json.dumps(c['detail'])[:300]}")
    return 0


def remember(a):
    scope = opt(a, "--scope"); kind = opt(a, "--kind", "note"); title = opt(a, "--title"); conf = opt(a, "--confidence"); source = opt(a, "--source")
    sens = opt(a, "--sensitivity", "internal"); det = opt(a, "--detail"); occ = opt(a, "--occurred-at"); who = opt(a, "--as")
    text = " ".join(x for x in a if not x.startswith("--")).strip() or sys.exit("remember TEXT --scope SCOPE")
    body = {"text": text, "kind": kind, "sensitivity": sens}
    if scope:
        body["scope"] = scope
    for k, v in (("title", title), ("confidence", conf), ("source", source), ("occurred_at", occ), ("as", who)):
        if v is not None:
            body[k] = v
    if det is not None:
        try:
            body["detail"] = json.loads(det)
        except ValueError:
            sys.exit("--detail is JSON")
    r = api("POST", "/v1/remember", body)
    print(f"remembered #{r['id']} in {r['scope']} ({r['kind']}) as {r['principal']} at {r['recorded_at']}" + (" (with its vector)" if r.get("embedded") else ""))
    return 0


def forget(a):
    who = opt(a, "--as")
    mid = a[0] if a and a[0].isdigit() else sys.exit("forget ID")
    body = {"id": int(mid)}
    if who:
        body["as"] = who
    api("POST", "/v1/forget", body)
    print(f"forgotten #{mid}")
    return 0


def usage(a):
    as_json = opt(a, "--json", flag=True); since = since_ts(opt(a, "--since")); limit = opt(a, "--limit", "100")
    q = f"/v1/usage?limit={int(limit)}" + (f"&since={since}" if since else "")
    r = api("GET", q)
    if as_json:
        print(json.dumps(r, indent=1)); return 0
    for e in r["events"]:
        d = e.get("detail") or {}
        what = {"memory.query": f"peer {d.get('peer')} asked {', '.join(d.get('scopes') or [])} → {d.get('count')} claim(s) (envelope {d.get('envelope')}, originator {d.get('originator')})",
                "memory.recall": f"{', '.join(d.get('scopes') or [])} → {d.get('count')} claim(s)" + (f"; holders {', '.join(d.get('holders') or [])}" if d.get("estate") else " (local)") + (f"; failed {len(d.get('holders_failed') or [])}" if d.get("holders_failed") else ""),
                "memory.remember": f"#{d.get('id')} in {d.get('scope')} ({d.get('kind')}, {d.get('sensitivity')})",
                "memory.forget": f"#{d.get('id')}", "memory.summaries": f"peer {d.get('peer')} pulled {d.get('scope')}: {d.get('count')} summaries",
                "memory.sync": f"{len(d.get('holders') or [])} holder scope(s)"}.get(e["event"], json.dumps(d)[:120])
        print(f"{e['ts']}  {e['event']:<17} {e.get('principal_ref') or '-':<24} {e.get('status')}  {what}")
    if not r["events"]:
        print("no memory events" + (" since then" if since else ""))
    return 0


def _guest_sql(mp, st):
    db, tenant = st["database"], st["tenant"]
    pre = f"SET ROLE {mp.qi(tenant)}; SET search_path TO {mp.qi(tenant)}, maludb_core, public; "
    guest = conf_read().get("guest") or "estate:guest"
    return db, pre, guest


def share(a):
    need_root()
    mx = opt(a, "--max")
    scopes = [s for s in a if not s.startswith("--")]
    if not scopes and mx is None:
        sys.exit("share SCOPE... [--max CLS]")
    if mx is not None and mx not in SENS:
        sys.exit("--max public|internal|restricted|prohibited")
    import re
    for s in scopes:
        if not re.match(r"^(org|dept:[0-9]+)$", s):
            sys.exit(f"{s}: a shareable scope is org or dept:N (personal scopes never cross the estate)")
    mp, st = state()
    db, pre, guest = _guest_sql(mp, st)
    mp.psql(pre + f"SELECT maludb_principal_upsert({mp.ql(guest)}, 'service', 'MaluOS memory face: the estate''s guest (what this host shares)', {mp.ql(guest)}, {mp.ql(mx) if mx else 'NULL'}, true);", db)
    for s in scopes:
        mp.psql(pre + f"SELECT maludb_principal_grant_scope({mp.ql(guest)}, {mp.ql(s)}, 'read');", db)
    api("POST", "/v1/reload")
    f = api("GET", "/v1/facts")
    print(f"shared: {', '.join(f['shared']) or 'nothing'}; ceiling {f['max_classification']}" + ("" if f.get("exposed") else "  (not exposed yet: sudo maluctl memory expose)"))
    _hint()
    return 0


def unshare(a):
    need_root()
    everything = opt(a, "--all", flag=True)
    scopes = [s for s in a if not s.startswith("--")]
    mp, st = state()
    db, pre, guest = _guest_sql(mp, st)
    if everything:
        scopes = api("GET", "/v1/facts")["shared"]
    for s in scopes:
        mp.psql(pre + f"SELECT maludb_principal_revoke_scope({mp.ql(guest)}, {mp.ql(s)});", db)
    api("POST", "/v1/reload")
    f = api("GET", "/v1/facts")
    print(f"shared: {', '.join(f['shared']) or 'nothing'}")
    _hint()
    return 0


def _hint():
    """The estate daemon heartbeats on its own clock; a desk's session too. Nothing to poke: the next heartbeat carries the facts."""
    return None


def expose(a):
    need_root()
    bind = opt(a, "--bind", "overlay"); port = int(opt(a, "--port", "11437"))
    d = conf_read()
    d["tcp"] = {"enabled": True, "host": bind, "port": port}
    conf_write(d)
    r = api("POST", "/v1/reload")
    b = r.get("tcp")
    print(f"exposed: {bind}:{port}" + (f"; listening on {b[0]}:{b[1]}" if b else "; not listening yet (no overlay address: join an estate first)"))
    return 0


def unexpose(a):
    need_root()
    d = conf_read()
    d["tcp"] = {**(d.get("tcp") or {}), "enabled": False}
    conf_write(d)
    api("POST", "/v1/reload")
    print("not exposed")
    return 0


def keys(a):
    """The face signs its own queries with this host's membership keys: a read grant on each to user:maluos-memory."""
    need_root()
    done = []
    e = _yaml(ESTATE_CONF)
    if (e.get("node") or {}).get("id"):
        try:
            run_as(ESTATE_USER, ["secret", "grant", "estate-node-key", "--to", f"user:{FACE_USER}", "--level", "read"])
            done.append(f"{e.get('principal')}/estate-node-key")
        except RuntimeError as ex:
            print(f"  warn: {ex}", file=sys.stderr)
    o = _yaml(OFFICE_CONF)
    owner = (o.get("owner") or {}).get("login")
    if (o.get("desk") or {}).get("id") and owner:
        try:
            run_as(owner, ["secret", "grant", "office-desk-key", "--to", f"user:{FACE_USER}", "--level", "read"])
            done.append(f"{(o.get('owner') or {}).get('principal')}/office-desk-key")
        except RuntimeError as ex:
            print(f"  warn: {ex}", file=sys.stderr)
    api("POST", "/v1/reload")
    print("the face may read: " + (", ".join(done) or "nothing (no membership on this host)"))
    return 0


def sync(a):
    need_root()
    as_json = opt(a, "--json", flag=True)
    r = api("POST", "/v1/sync", {}, timeout=300)
    if as_json:
        print(json.dumps(r, indent=1)); return 0
    if not r["synced"]:
        print("nothing to replicate (no holder lets this host copy a scope's summaries)"); return 0
    for s in r["synced"]:
        print(f"  {s['holder']:<16} {s['scope']:<12} " + (f"written {s.get('written')}, replaced {s.get('replaced')}, removed {s.get('removed')} (version {s.get('version')})" if s.get("ok") else f"FAILED {s.get('error')}: {s.get('message') or ''}"))
    return 0


def reload(a):
    need_root()
    r = api("POST", "/v1/reload")
    print(f"reloaded; listener {r.get('tcp') or 'off'}")
    return 0


def main(args):
    a = list(args)
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    cmd = a.pop(0)
    cmds = {"status": status, "facts": facts, "whoami": whoami, "recall": recall, "remember": remember, "forget": forget, "usage": usage,
            "share": share, "unshare": unshare, "expose": expose, "unexpose": unexpose, "keys": keys, "sync": sync, "reload": reload, "embed": embed}
    if cmd not in cmds:
        print(__doc__); return 2
    try:
        return cmds[cmd](a)
    except RuntimeError as e:
        sys.exit(f"maluctl memory {cmd}: {e}")
