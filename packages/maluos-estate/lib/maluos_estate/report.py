"""The node's report: what an operator needs to know about a server, read the way the Desk reads the desk it runs
on (docs/phase13-slice1-nodes.md, "The report"). Units through systemctl, agents from /etc/maluos/agents, the
gateway and the vault over their sockets, updates through `maluctl update status --json`, disk, memory and load
from the kernel. Nothing here needs privileges; nothing in it is a secret, a prompt or ledger detail beyond alert
reasons. A part that cannot be read is null and named in `errors`, so a broken gateway never hides a full disk.
The whole report stays under 32 KB."""
import http.client, json, os, socket, subprocess, time

GW = os.environ.get("MALUOS_GATEWAY_SOCKET", "/run/maluos/gateway.sock")
VAULT = os.environ.get("MALUOS_VAULT_SOCKET", "/run/maluos/vault.sock")
AGENTS = os.environ.get("MALUOS_AGENTS_DIR", "/etc/maluos/agents")
UNITS = ["postgresql@18-main.service", "maludb-mc2dbd.service", "maluos-vault.service", "maluos-gateway.service", "maluos-estate.service"]
MAX_BYTES = 32 * 1024


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path, timeout=10):
        super().__init__("localhost", timeout=timeout); self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); self.sock.settimeout(self.timeout); self.sock.connect(self.path)


def _get(sock, path, query=None):
    if query:
        from urllib.parse import urlencode
        path += "?" + urlencode({k: v for k, v in query.items() if v is not None})
    c = _UnixConn(sock)
    try:
        c.request("GET", path, headers={"Accept": "application/json"})
        r = c.getresponse(); raw = r.read()
        try:
            return r.status, json.loads(raw) if raw else {}
        except ValueError:
            return r.status, {}
    finally:
        c.close()


def _ok(sock, path, query=None, default=None):
    if not os.path.exists(sock):
        return default
    try:
        st, body = _get(sock, path, query)
        return body if st < 400 else default
    except (OSError, http.client.HTTPException):
        return default


def units():
    """The fixed list plus every maluos-agent@ unit present, through systemctl show; units systemd does not know are left out."""
    names = list(UNITS)
    try:
        r = subprocess.run(["systemctl", "list-units", "--no-legend", "--plain", "--all", "maluos-agent@*.service"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            n = line.split()[0] if line.split() else ""
            if n.startswith("maluos-agent@") and n not in names:
                names.append(n)
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    r = subprocess.run(["systemctl", "show", "-p", "Id,LoadState,ActiveState,SubState,NRestarts", "--", *names], capture_output=True, text=True, timeout=15)
    cur = {}
    for line in r.stdout.splitlines() + [""]:
        if not line.strip():
            if cur.get("Id") and cur.get("LoadState") not in (None, "not-found"):
                out.append({"unit": cur["Id"], "active": cur.get("ActiveState"), "sub": cur.get("SubState"), "restarts": int(cur.get("NRestarts") or 0)})
            cur = {}; continue
        k, _, v = line.partition("=")
        cur[k] = v
    return out


def agents(unit_rows=None):
    """Every agent in /etc/maluos/agents joined with its unit's state."""
    by_unit = {u["unit"]: u for u in (unit_rows or [])}
    try:
        names = sorted(f[:-4] for f in os.listdir(AGENTS) if f.endswith(".env"))
    except OSError:
        return []
    out = []
    for n in names:
        a = {"name": n, "principal": f"agent:{n}", "active": "inactive", "sub": "dead", "restarts": 0, "owner": None, "sandbox": "standard"}
        try:
            for line in open(f"{AGENTS}/{n}.env"):
                if line.startswith("MALUOS_PRINCIPAL="):
                    a["principal"] = line.split("=", 1)[1].strip()
                elif line.startswith("MALUOS_AGENT_OWNER="):
                    a["owner"] = line.split("=", 1)[1].strip()
        except OSError:
            pass
        if os.path.exists(f"/etc/systemd/system/maluos-agent@{n}.service.d/sandbox.conf"):
            a["sandbox"] = "strict"
        u = by_unit.get(f"maluos-agent@{n}.service")
        if u:
            a.update({"active": u["active"], "sub": u["sub"], "restarts": u["restarts"]})
        out.append(a)
    return out


def gateway():
    if not os.path.exists(GW):
        return None
    health = _ok(GW, "/v1/maluos/health")
    if health is None:
        return {"ok": False, "error": "the gateway socket did not answer"}
    status = _ok(GW, "/v1/maluos/status", default={}) or {}
    backends = [{"name": b.get("name"), "kind": b.get("kind"), "healthy": bool(b.get("healthy")), "enabled": b.get("enabled", True),
                 "loaded": [m.get("name") for m in b.get("loaded") or []][:8]} for b in status.get("backends") or []]
    if not backends:
        backends = [{"name": n, "healthy": bool(h), "kind": None, "enabled": True, "loaded": []} for n, h in (health.get("backends") or {}).items()]
    return {"ok": bool(health.get("ok")), "version": status.get("version") or health.get("version"), "backends": backends,
            "queue": status.get("queue") or {"queued": 0, "running": 0}, "expected_wait_s": status.get("expected_wait_s") or {},
            "share": (status.get("share") or {}).get("enabled") if isinstance(status.get("share"), dict) else None}


def vault():
    """The vault's health and its open alert rows (alert.% in the ledger; the vault lets a host principal read them)."""
    if not os.path.exists(VAULT):
        return None
    health = _ok(VAULT, "/v1/health")
    if health is None:
        return {"ok": False, "alerts": [], "error": "the vault socket did not answer"}
    rows = _ok(VAULT, "/v1/ledger", {"event_like": "alert.%", "limit": 20}, default={}) or {}
    alerts = [{"id": r.get("ledger_id"), "ts": str(r.get("ts") or "")[:19], "kind": (r.get("event") or "")[6:],
               "principal": r.get("principal_ref"), "title": r.get("reason")} for r in rows.get("events") or []]
    return {"ok": bool(health.get("ok")), "alerts": alerts}


def updates():
    try:
        r = subprocess.run(["maluctl", "update", "status", "--json", "--compact"], capture_output=True, text=True, timeout=90)
        d = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {"error": f"{e.__class__.__name__}: {str(e)[:100]}"}
    return {"pending_count": d.get("pending_count", 0), "security_count": d.get("security_count", 0), "reboot_required": bool(d.get("reboot_required")),
            "lists_refreshed_at": d.get("lists_refreshed_at"), "last_automatic_run_at": d.get("last_automatic_run_at")}


def disk():
    """Real file systems on block devices: mount, size and use."""
    out, seen = [], set()
    try:
        for line in open("/proc/mounts"):
            dev, mount, fstype = line.split()[:3]
            if not dev.startswith("/dev/") or fstype in ("squashfs", "iso9660", "vfat") or mount.startswith(("/snap/", "/boot/efi")):
                continue
            if dev in seen:
                continue
            seen.add(dev)
            try:
                st = os.statvfs(mount)
            except OSError:
                continue
            size = st.f_blocks * st.f_frsize
            if not size:
                continue
            used = size - st.f_bfree * st.f_frsize
            out.append({"mount": mount, "size_gb": round(size / 2 ** 30), "used_pct": round(100 * used / size)})
    except OSError:
        pass
    out.sort(key=lambda d: (d["mount"] != "/", d["mount"]))
    return out[:12]


def memory():
    m = {}
    try:
        for line in open("/proc/meminfo"):
            k, _, v = line.partition(":")
            m[k] = int(v.split()[0]) if v.strip() else 0
    except OSError:
        return None
    return {"total_mb": m.get("MemTotal", 0) // 1024, "available_mb": m.get("MemAvailable", 0) // 1024,
            "swap_used_mb": (m.get("SwapTotal", 0) - m.get("SwapFree", 0)) // 1024}


def load():
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return None


def host():
    h = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "hostname": socket.gethostname(), "cpu_cores": os.cpu_count()}
    try:
        h["boot_id"] = open("/proc/sys/kernel/random/boot_id").read().strip()
    except OSError:
        h["boot_id"] = None
    try:
        h["uptime_s"] = int(float(open("/proc/uptime").read().split()[0]))
    except (OSError, ValueError):
        h["uptime_s"] = None
    return h


def report():
    """The whole report; each part guarded, the errors listed, the size bounded."""
    errors = []
    rep = host()

    def part(name, fn, *args):
        try:
            rep[name] = fn(*args)
        except Exception as e:
            rep[name] = None; errors.append(f"{name}: {e.__class__.__name__}: {str(e)[:100]}")
    part("units", units)
    part("agents", agents, rep.get("units") or [])
    part("gateway", gateway)
    part("vault", vault)
    part("updates", updates)
    part("disk", disk)
    part("memory", memory)
    part("load", load)
    rep["errors"] = errors
    data = json.dumps(rep)
    if len(data) > MAX_BYTES:
        for key, n in (("units", 40), ("agents", 20), ("disk", 6)):
            if isinstance(rep.get(key), list):
                rep[key] = rep[key][:n]
        if isinstance(rep.get("vault"), dict):
            rep["vault"]["alerts"] = (rep["vault"].get("alerts") or [])[:5]
        rep["errors"].append(f"report trimmed from {len(data)} bytes")
    return rep


def summary(rep):
    """One line per part, for `maluctl estate report` without --json."""
    lines = [f"node:     {rep.get('hostname')}  up {rep.get('uptime_s') or 0} s  cores {rep.get('cpu_cores')}  load {rep.get('load')}"]
    us = rep.get("units") or []
    down = [u["unit"] for u in us if u.get("active") != "active"]
    lines.append(f"units:    {len(us) - len(down)} up" + (f", down: {', '.join(down)}" if down else ""))
    ag = rep.get("agents") or []
    lines.append(f"agents:   {len(ag)}" + (": " + ", ".join(f"{a['name']} {a['active']}" for a in ag) if ag else ""))
    g = rep.get("gateway")
    lines.append("gateway:  none" if g is None else f"gateway:  {'ok' if g.get('ok') else 'DOWN'}  {g.get('version') or ''}  backends {sum(1 for b in g.get('backends') or [] if b.get('healthy'))}/{len(g.get('backends') or [])} healthy  queue {g.get('queue')}")
    v = rep.get("vault")
    lines.append("vault:    none" if v is None else f"vault:    {'ok' if v.get('ok') else 'DOWN'}  {len(v.get('alerts') or [])} alert rows")
    u = rep.get("updates") or {}
    lines.append(f"updates:  {u.get('pending_count', '?')} pending ({u.get('security_count', 0)} security)" + (", restart required" if u.get("reboot_required") else "") + (f"  ({u['error']})" if u.get("error") else ""))
    lines.append("disk:     " + ", ".join(f"{d['mount']} {d['used_pct']}% of {d['size_gb']} G" for d in rep.get("disk") or []))
    m = rep.get("memory") or {}
    lines.append(f"memory:   {m.get('available_mb')} of {m.get('total_mb')} MB available, swap used {m.get('swap_used_mb')} MB")
    if rep.get("errors"):
        lines.append("errors:   " + "; ".join(rep["errors"]))
    return "\n".join(lines)
