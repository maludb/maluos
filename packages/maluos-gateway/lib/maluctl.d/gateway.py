"""maluctl gateway: the MaluOS inference gateway.

  maluctl gateway status | queue | routes [--limit N] | backends | whoami
  maluctl gateway chat "PROMPT" [--model NAME] [--class C] [--stream]   quick test call
  maluctl gateway catalog                                tiers, aliases, classes, policies
  maluctl gateway backend add NAME --kind ollama_local|ollama_cloud|anthropic|openai|openai_compat|mock --endpoint URL
                    [--secret REF] [--models a,b] [--max-concurrent N] [--keep-alive 30m]
  maluctl gateway price set BACKEND MODEL --input USD/Mtok --output USD/Mtok [--cached USD/Mtok]  |  price list
  maluctl gateway backend enable|disable|rm NAME
  maluctl gateway tier add NAME [--description D]  |  tier rm NAME
  maluctl gateway alias set NAME --backend B --model M [--tier T] [--position N]
  maluctl gateway alias rm NAME [--backend B] [--model M]
  maluctl gateway class set NAME [--priority N] [--weight N] [--max-queue N] [--max-wait S|none] [--fallback-wait S|none]
  maluctl gateway policy set (--default | --principal REF | --scope S) [--class C] [--tiers a,b|all] [--backends a,b|all] [--cloud yes|no]
                    [--egress public|internal|restricted|prohibited] [--ladder b1,b2|none] [--budget usd_per_day=5,usd_per_month=100|none]
  maluctl gateway policy rm (--principal REF | --scope S)
  maluctl gateway token issue --principal REF [--name N] [--expires 90d]   bearer token for the TCP listener
  maluctl gateway token list | revoke ID
  maluctl gateway usage [--since 7d] [--by principal|model|class|backend|user|day] [--raw]
  maluctl gateway ollama install [--version vX.Y.Z] | pull MODEL [--backend B] | warm MODEL [--backend B] | status
  maluctl gateway alerts [--since 7d]                  alert rows (budget, backend down/recovered, usage anomaly, restart)
  maluctl gateway reload

Callers use the gateway at the Unix socket /run/maluos/gateway.sock with any
OpenAI or Ollama client (OPENAI_BASE_URL / OLLAMA_HOST pointing at it through
a TCP listener, or the socket directly), naming a tier (fast, standard,
strong, embed), an alias, or a model.
"""
import datetime, hashlib, http.client, json, os, secrets, socket, sys, urllib.parse
sys.path.insert(0, "/usr/lib/maluos")

SOCKET = os.environ.get("MALUOS_GATEWAY_SOCKET", "/run/maluos/gateway.sock")


class GwError(Exception):
    pass


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path, timeout=600):
        super().__init__("maluos-gateway", timeout=timeout); self.path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(self.timeout); s.connect(self.path); self.sock = s


def api(method, path, body=None, query=None, stream=False, headers=None):
    if query:
        path += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
    c = _UnixConn(SOCKET)
    try:
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", **(headers or {})})
        r = c.getresponse()
    except (FileNotFoundError, ConnectionRefusedError) as e:
        raise GwError(f"gateway socket {SOCKET}: {e.strerror or e} (sudo systemctl status maluos-gateway.socket)")
    if stream:
        return r, c
    raw = r.read(); c.close()
    obj = json.loads(raw) if raw else {}
    if r.status >= 400:
        err = obj.get("error") if isinstance(obj, dict) else None
        msg = err.get("message") if isinstance(err, dict) else (err or raw[:200].decode(errors="replace"))
        extra = {k: v for k, v in (err or {}).items() if k not in ("message", "type", "code")} if isinstance(err, dict) else {}
        raise GwError(f"{msg}" + (f" {json.dumps(extra)}" if extra else ""))
    return obj


def opt(args, name, default=None, flag=False):
    if name in args:
        i = args.index(name)
        if flag:
            args.pop(i); return True
        v = args[i + 1]; del args[i:i + 2]; return v
    return default


def table(rows, cols):
    if not rows:
        print("(none)"); return
    w = [max(len(c), *(len(str(r.get(c) if r.get(c) is not None else "-")) for r in rows)) for c in cols]
    print("  ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
    for r in rows:
        print("  ".join(str(r.get(c) if r.get(c) is not None else "-").ljust(w[i]) for i, c in enumerate(cols)))


# -- admin SQL (root): the catalogue lives in the tenant schema; the gateway reloads it every few seconds
def sql(stmt, db=None):
    import maluos_provision as mp
    if os.geteuid() != 0:
        sys.exit("maluctl gateway: this subcommand needs sudo")
    st = json.load(open(mp.DONE)) if os.path.exists(mp.DONE) else sys.exit("not provisioned")
    pre = f"SET ROLE {mp.qi(st['tenant'])}; SET search_path TO {mp.qi(st['tenant'])}, maludb_core, public; "
    return mp.psql(pre + stmt, st["database"])


def ql(s):
    return "NULL" if s is None else "'" + str(s).replace("'", "''") + "'"


def arr(s):
    if s is None:
        return None
    if s == "all":
        return "NULL"
    return "ARRAY[" + ",".join(ql(x.strip()) for x in s.split(",") if x.strip()) + "]::text[]"


def main(args):
    try:
        return run(list(args))
    except GwError as e:
        print(f"maluctl gateway: {e}", file=sys.stderr); return 1
    except RuntimeError as e:
        print(f"maluctl gateway: {e}", file=sys.stderr); return 1


def run(a):
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    cmd = a.pop(0)
    if cmd == "status":
        st = api("GET", "/v1/maluos/status")
        print(f"gateway:     {st['version']}  up {st['uptime_s']}s  queued {st['queue']['queued']}  running {st['queue']['running']}"
              f"  engine queue {'on' if st['engine_queue']['enabled'] else 'off'} ({st['engine_queue']['inflight']} in flight)")
        for b in st["backends"]:
            h = "healthy" if b["healthy"] else ("down: " + (b.get("error") or "?")) if b["healthy"] is False else "unchecked"
            print(f"backend:     {b['name']}  {b['kind']}  {b['endpoint']}  {h}" + (f"  v{b['version']}" if b.get("version") else "")
                  + (f"  key: vault {b['secret_ref']}" if b.get("secret_ref") else "")
                  + (f"  loaded: {', '.join(m['name'] for m in b['loaded'])}" if b.get("loaded") else "") + ("" if b["enabled"] else "  (disabled)"))
        for name, s in st["schedulers"].items():
            print(f"scheduler:   {name}  capacity {s['capacity']}  resident {s['resident'] or '-'}  " +
                  "  ".join(f"{c}: {v['queued']} queued, wait {v['expected_wait_s']}s" for c, v in s["classes"].items()))
        print("tiers:       " + ("; ".join(f"{t} -> {', '.join(l) or '(none)'}" for t, l in st["catalog"]["tiers"].items()) or "-"))
        if st["catalog"]["aliases"]:
            print("aliases:     " + "; ".join(f"{k} -> {v}" for k, v in st["catalog"]["aliases"].items()))
        return 0
    if cmd == "queue":
        st = api("GET", "/v1/maluos/status")
        rows = [dict(j, backend=n) for n, s in st["schedulers"].items() for j in s["jobs"]]
        table(rows, ["id", "state", "class", "principal", "model", "backend", "kind", "elapsed_s", "waited_s"]); return 0
    if cmd == "routes":
        rows = api("GET", "/v1/maluos/routes", query={"limit": opt(a, "--limit", 30)})["routes"]
        for r in rows:
            ts = datetime.datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
            route = " > ".join(f"{s['backend']}/{s['model']}" + ("" if s.get("taken") else f" (skipped: {s.get('skipped', '-')})") for s in r["route"]) or "-"
            print(f"{ts}  {r['status']:6} {r['principal']:22} {r['requested']:14} {r['class']:11} {route}  "
                  f"{'wait ' + str(r.get('queue_wait_ms')) + 'ms ' if r.get('queue_wait_ms') is not None else ''}"
                  f"{'svc ' + str(r.get('service_ms')) + 'ms ' if r.get('service_ms') else ''}"
                  f"{str(r.get('tokens_in')) + '/' + str(r.get('tokens_out')) + ' tok ' if r.get('tokens_out') else ''}"
                  f"{'$' + format(r['cost'], '.5f') + ' ' if r.get('cost') else ''}{'x' + str(r['attempts']) + ' ' if (r.get('attempts') or 1) > 1 else ''}{r.get('reason') or ''}".rstrip())
        return 0
    if cmd == "backends":
        for b in api("GET", "/v1/maluos/status")["backends"]:
            print(json.dumps(b, indent=1, default=str))
        return 0
    if cmd == "whoami":
        print(json.dumps(api("GET", "/v1/maluos/whoami"), indent=1)); return 0
    if cmd == "chat":
        prompt = a.pop(0) if a and not a[0].startswith("--") else "Say hello in one sentence."
        model = opt(a, "--model", "standard"); cls = opt(a, "--class"); stream = opt(a, "--stream", flag=True)
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": stream}
        if stream:
            body["stream_options"] = {"include_usage": True}
        headers = {"X-MaluOS-Class": cls} if cls else {}
        if not stream:
            r = api("POST", "/v1/chat/completions", body, headers=headers)
            print(r["choices"][0]["message"]["content"])
            print(f"[{r['model']}  {r['usage']['prompt_tokens']}+{r['usage']['completion_tokens']} tokens]", file=sys.stderr); return 0
        r, c = api("POST", "/v1/chat/completions", body, headers=headers, stream=True)
        if r.status >= 400:
            raise GwError(r.read().decode()[:300])
        print(f"[route {r.getheader('X-MaluOS-Route')}]", file=sys.stderr)
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            obj = json.loads(line[6:])
            if obj.get("error"):
                print(f"\nerror: {obj['error'].get('message')}", file=sys.stderr); break
            for ch in obj.get("choices", []):
                sys.stdout.write(ch.get("delta", {}).get("content") or ""); sys.stdout.flush()
            if obj.get("usage"):
                print(f"\n[{obj['usage']['prompt_tokens']}+{obj['usage']['completion_tokens']} tokens]", file=sys.stderr)
        c.close(); print(); return 0
    if cmd == "catalog":
        print("tiers:");    print(sql("SELECT '  ' || t.name || '  ' || coalesce(t.description,'') || '  -> ' || coalesce(string_agg(a.backend || '/' || a.model, ', ' ORDER BY a.position), '(none)') FROM maluos_tier t LEFT JOIN maluos_alias a ON a.tier=t.name AND a.enabled GROUP BY t.name, t.description ORDER BY t.name") or "  (none)")
        print("aliases:");  print(sql("SELECT '  ' || name || ' -> ' || backend || '/' || model || CASE WHEN enabled THEN '' ELSE ' (disabled)' END FROM maluos_alias WHERE tier IS NULL ORDER BY name") or "  (none)")
        print("classes:");  print(sql("SELECT '  ' || name || '  priority ' || priority || '  weight ' || weight || '  max_queue ' || max_queue || '  max_wait ' || coalesce(max_wait_s::text,'-') || '  fallback_wait ' || coalesce(fallback_wait_s::text,'never') FROM maluos_class ORDER BY priority") or "  (none)")
        print("backends:"); print(sql("SELECT '  ' || name || '  ' || kind || '  ' || endpoint || '  ' || capacity::text || CASE WHEN enabled THEN '' ELSE ' (disabled)' END FROM maluos_backend ORDER BY name") or "  (none)")
        print("policies:"); print(sql("SELECT '  ' || subject_kind || CASE WHEN subject_ref='' THEN '' ELSE ' ' || subject_ref END || '  class=' || coalesce(default_class,'-') || '  tiers=' || coalesce(array_to_string(allowed_tiers, ','),'all') || '  backends=' || coalesce(array_to_string(allowed_backends, ','),'all') || '  cloud=' || cloud_allowed || '  egress=' || coalesce(max_egress_sensitivity, '(default)') || '  budget=' || coalesce(budget::text, '-') FROM maluos_policy ORDER BY subject_kind, subject_ref") or "  (none)")
        print("prices:");   print(sql("SELECT '  ' || backend || '/' || model || '  in ' || input_per_mtok || ' out ' || output_per_mtok || ' cached ' || cached_per_mtok || ' ' || currency || '/Mtok' FROM maluos_price ORDER BY 1") or "  (none)")
        return 0
    if cmd == "backend":
        sub, name = a.pop(0), a.pop(0)
        if sub == "add":
            kind = opt(a, "--kind", "ollama_local"); ep = opt(a, "--endpoint") or sys.exit("--endpoint required")
            cloud = kind in ("ollama_cloud", "anthropic", "openai", "openai_compat")
            cap = json.dumps({"max_concurrent": int(opt(a, "--max-concurrent", 8 if cloud else 1))})
            o = {"keep_alive": opt(a, "--keep-alive", "30m")} if not cloud else {}
            models = opt(a, "--models")
            if models:
                o["models"] = [m.strip() for m in models.split(",") if m.strip()]
            secret = opt(a, "--secret")
            sql(f"INSERT INTO maluos_backend (name, kind, endpoint, secret_ref, capacity, options) VALUES ({ql(name)}, {ql(kind)}, {ql(ep)}, {ql(secret)}, {ql(cap)}::jsonb, {ql(json.dumps(o))}::jsonb) "
                f"ON CONFLICT (name) DO UPDATE SET kind=EXCLUDED.kind, endpoint=EXCLUDED.endpoint, secret_ref=EXCLUDED.secret_ref, capacity=EXCLUDED.capacity, options=maluos_backend.options || EXCLUDED.options, enabled=true")
            print(f"backend {name} ({kind}) -> {ep}" + (f"  key: vault {secret}" if secret else "")); api("POST", "/v1/maluos/reload"); return 0
        if sub in ("enable", "disable"):
            sql(f"UPDATE maluos_backend SET enabled={'true' if sub == 'enable' else 'false'} WHERE name={ql(name)}"); api("POST", "/v1/maluos/reload"); print(f"{name} {sub}d"); return 0
        if sub == "rm":
            sql(f"DELETE FROM maluos_backend WHERE name={ql(name)}"); api("POST", "/v1/maluos/reload"); print(f"removed {name}"); return 0
    if cmd == "price":
        sub = a.pop(0)
        if sub == "list":
            print(sql("SELECT backend || '/' || model || '  in ' || input_per_mtok || '  out ' || output_per_mtok || '  cached ' || cached_per_mtok || ' ' || currency || '/Mtok' FROM maluos_price ORDER BY 1") or "(none)"); return 0
        if sub == "set":
            b, m = a.pop(0), a.pop(0); i, o, c = opt(a, "--input", 0), opt(a, "--output", 0), opt(a, "--cached", 0)
            sql(f"INSERT INTO maluos_price (backend, model, input_per_mtok, output_per_mtok, cached_per_mtok, currency) VALUES ({ql(b)}, {ql(m)}, {float(i)}, {float(o)}, {float(c)}, {ql(opt(a, '--currency', 'USD'))}) "
                f"ON CONFLICT (backend, model) DO UPDATE SET input_per_mtok=EXCLUDED.input_per_mtok, output_per_mtok=EXCLUDED.output_per_mtok, cached_per_mtok=EXCLUDED.cached_per_mtok, currency=EXCLUDED.currency, updated_at=now()")
            api("POST", "/v1/maluos/reload"); print(f"price {b}/{m}: in {i} out {o} cached {c} per Mtok"); return 0
    if cmd == "tier":
        sub, name = a.pop(0), a.pop(0)
        if sub == "add":
            sql(f"INSERT INTO maluos_tier (name, description) VALUES ({ql(name)}, {ql(opt(a, '--description'))}) ON CONFLICT (name) DO UPDATE SET description=EXCLUDED.description"); print(f"tier {name}")
        elif sub == "rm":
            sql(f"DELETE FROM maluos_tier WHERE name={ql(name)}"); print(f"removed tier {name}")
        api("POST", "/v1/maluos/reload"); return 0
    if cmd == "alias":
        sub, name = a.pop(0), a.pop(0)
        if sub == "set":
            b = opt(a, "--backend") or sys.exit("--backend required"); m = opt(a, "--model") or sys.exit("--model required")
            tier, pos = opt(a, "--tier"), int(opt(a, "--position", 0))
            sql(f"INSERT INTO maluos_alias (name, tier, backend, model, position) VALUES ({ql(name)}, {ql(tier)}, {ql(b)}, {ql(m)}, {pos}) "
                f"ON CONFLICT (name, backend, model) DO UPDATE SET tier=EXCLUDED.tier, position=EXCLUDED.position, enabled=true")
            print(f"alias {name}" + (f" (tier {tier})" if tier else "") + f" -> {b}/{m}")
        elif sub == "rm":
            b, m = opt(a, "--backend"), opt(a, "--model")
            sql(f"DELETE FROM maluos_alias WHERE name={ql(name)}" + (f" AND backend={ql(b)}" if b else "") + (f" AND model={ql(m)}" if m else "")); print(f"removed alias {name}")
        api("POST", "/v1/maluos/reload"); return 0
    if cmd == "class":
        sub, name = a.pop(0), a.pop(0)
        if sub == "set":
            sets = []
            for o, col in (("--priority", "priority"), ("--weight", "weight"), ("--max-queue", "max_queue"), ("--max-wait", "max_wait_s"), ("--fallback-wait", "fallback_wait_s")):
                v = opt(a, o)
                if v is not None:
                    sets.append(f"{col}=" + ("NULL" if v == "none" else str(int(v))))
            if not sets:
                sys.exit("nothing to set")
            sql(f"INSERT INTO maluos_class (name, priority) VALUES ({ql(name)}, 50) ON CONFLICT (name) DO NOTHING; UPDATE maluos_class SET {', '.join(sets)} WHERE name={ql(name)}")
            print(f"class {name}: {', '.join(sets)}"); api("POST", "/v1/maluos/reload"); return 0
    if cmd == "policy":
        sub = a.pop(0)
        kind, ref = ("default", "") if opt(a, "--default", flag=True) else (("principal", opt(a, "--principal")) if "--principal" in a else ("scope", opt(a, "--scope")))
        if ref is None:
            sys.exit("--default | --principal REF | --scope SCOPE")
        if sub == "rm":
            sql(f"DELETE FROM maluos_policy WHERE subject_kind={ql(kind)} AND subject_ref={ql(ref)}"); api("POST", "/v1/maluos/reload"); print("removed"); return 0
        cls, tiers, backends, cloud = opt(a, "--class"), opt(a, "--tiers"), opt(a, "--backends"), opt(a, "--cloud")
        egress, ladder, budget = opt(a, "--egress"), opt(a, "--ladder"), opt(a, "--budget")
        sets = []
        if cls is not None: sets.append(f"default_class={ql(None if cls == 'none' else cls)}")
        if tiers is not None: sets.append(f"allowed_tiers={arr(tiers)}")
        if backends is not None: sets.append(f"allowed_backends={arr(backends)}")
        if cloud is not None: sets.append(f"cloud_allowed={'true' if cloud in ('yes', 'true', '1') else 'false'}")
        if egress is not None: sets.append(f"max_egress_sensitivity={ql(None if egress == 'none' else egress)}")
        if ladder is not None: sets.append("ladder=" + ("NULL" if ladder == "none" else ql(json.dumps([x.strip() for x in ladder.split(',') if x.strip()])) + "::jsonb"))
        if budget is not None:
            if budget == "none":
                sets.append("budget=NULL")
            else:
                bd = {}
                for kv in budget.split(","):
                    k, v = kv.split("=", 1); bd[k.strip()] = float(v)
                sets.append(f"budget={ql(json.dumps(bd))}::jsonb")
        sql(f"INSERT INTO maluos_policy (subject_kind, subject_ref) VALUES ({ql(kind)}, {ql(ref)}) ON CONFLICT (subject_kind, subject_ref) DO NOTHING; "
            + (f"UPDATE maluos_policy SET {', '.join(sets)}, updated_at=now() WHERE subject_kind={ql(kind)} AND subject_ref={ql(ref)}" if sets else "SELECT 1"))
        api("POST", "/v1/maluos/reload"); print(f"policy {kind} {ref}: {', '.join(sets) or 'created'}"); return 0
    if cmd == "token":
        sub = a.pop(0)
        if sub == "issue":
            p = opt(a, "--principal") or sys.exit("--principal required"); name = opt(a, "--name", "cli"); exp = opt(a, "--expires")
            tok = "mg_" + secrets.token_urlsafe(32); h = hashlib.sha256(tok.encode()).hexdigest()
            expsql = "NULL"
            if exp:
                import re
                m = re.match(r"^(\d+)([hdw])$", exp)
                expsql = f"now() + interval '{int(m.group(1))} {dict(h='hours', d='days', w='weeks')[m.group(2)]}'" if m else ql(exp) + "::timestamptz"
            sql(f"INSERT INTO maluos_token (principal_ref, name, token_hash, created_by, expires_at) VALUES ({ql(p)}, {ql(name)}, {ql(h)}, 'maluctl', {expsql})")
            print(tok); return 0
        if sub == "list":
            print(sql("SELECT token_id || '  ' || principal_ref || '  ' || coalesce(name,'') || '  created ' || created_at::date || '  expires ' || coalesce(expires_at::date::text,'never') || CASE WHEN revoked_at IS NULL THEN '' ELSE '  REVOKED' END || '  last used ' || coalesce(last_used_at::text,'never') FROM maluos_token ORDER BY token_id") or "(none)"); return 0
        if sub == "revoke":
            sql(f"UPDATE maluos_token SET revoked_at=now() WHERE token_id={int(a.pop(0))}"); print("revoked"); return 0
    if cmd == "usage":
        from maluos_vault_client import Vault, VaultError
        since, by, raw = opt(a, "--since", "7d"), opt(a, "--by", "principal"), opt(a, "--raw", flag=True)
        try:
            rows = Vault().ledger(since=since, event="model.call", limit=opt(a, "--limit", 5000))
        except VaultError as e:
            raise GwError(f"ledger via the vault: {e.message}")
        if raw:
            for r in reversed(rows):
                print(f"{r['ts'][:19]}  {r['status']:6} {r.get('principal_ref') or r.get('linux_user') or '-':22} {r.get('model') or '-':20} "
                      f"{str(r.get('tokens_in') or 0) + '/' + str(r.get('tokens_out') or 0):>10}  {r.get('reason') or ''}".rstrip())
            return 0
        key = {"principal": "principal_ref", "model": "model", "backend": "backend", "user": "linux_user", "class": None, "day": None}
        if by not in key:
            sys.exit("--by principal|model|class|backend|user|day")
        agg = {}
        for r in rows:
            k = r["ts"][:10] if by == "day" else (r.get("detail") or {}).get("class", "-") if by == "class" else (r.get(key[by]) or "-")
            d = agg.setdefault(k, {by: k, "calls": 0, "ok": 0, "errors": 0, "denied": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "last": ""})
            d["calls"] += 1; d["ok" if r["status"] == "ok" else "denied" if r["status"] == "denied" else "errors"] += 1
            d["tokens_in"] += r.get("tokens_in") or 0; d["tokens_out"] += r.get("tokens_out") or 0; d["cost"] += r.get("cost_actual") or 0; d["last"] = max(d["last"], r["ts"][:19])
        for d in agg.values():
            d["cost"] = f"{d['cost']:.4f}"
        table(sorted(agg.values(), key=lambda d: d["last"], reverse=True), [by, "calls", "ok", "errors", "denied", "tokens_in", "tokens_out", "cost", "last"])
        print(f"({len(rows)} calls since {since}; --raw for the list)"); return 0
    if cmd == "ollama":
        sub = a.pop(0) if a else "status"
        if sub == "install":
            if os.geteuid() != 0:
                sys.exit("needs sudo")
            os.execvp("/usr/lib/maluos/maluos-ollama-install", ["maluos-ollama-install"] + (["--version", opt(a, "--version")] if "--version" in a else []))
        if sub == "pull":
            model = a.pop(0); r, c = api("POST", "/api/pull", {"model": model, "backend": opt(a, "--backend")}, stream=True)
            if r.status >= 400:
                raise GwError(r.read().decode()[:300])
            last = ""
            for line in r:
                obj = json.loads(line)
                if "error" in obj:
                    print(f"error: {obj['error']}", file=sys.stderr); c.close(); return 1
                st = obj.get("status", "")
                if obj.get("total"):
                    st += f" {100 * obj.get('completed', 0) // obj['total']}%"
                if st != last:
                    print(st); last = st
            c.close(); return 0
        if sub == "warm":
            r = api("POST", "/v1/maluos/warm", {"model": a.pop(0), "backend": opt(a, "--backend")}); print(f"warmed {r['warmed']} on {r['backend']} ({r.get('load_ms')} ms)"); return 0
        if sub == "status":
            st = api("GET", "/v1/maluos/status")
            for b in st["backends"]:
                if b["kind"] in ("ollama_local", "mock"):
                    print(f"{b['name']}: {b['endpoint']}  {'healthy' if b['healthy'] else 'down (' + str(b.get('error')) + ')'}  version {b.get('version') or '?'}")
                    print(f"  models: {', '.join(b['models']) or '(none; maluctl gateway ollama pull MODEL)'}")
                    print(f"  loaded: {', '.join(m['name'] for m in b['loaded']) or '-'}")
            return 0
    if cmd == "alerts":
        from maluos_vault_client import Vault, VaultError
        since = opt(a, "--since", "7d")
        try:
            rows = Vault().ledger(since=since, event_like="alert.%", limit=500)
        except VaultError as e:
            raise GwError(f"ledger via the vault: {e.message}")
        for r in reversed(rows):
            print(f"{r['ts'][:19]}  {r['event'][6:]:18} {r.get('reason') or ''}")
        if not rows:
            print("(no alerts)")
        return 0
    if cmd == "reload":
        print(api("POST", "/v1/maluos/reload")); return 0
    print(__doc__); return 2
