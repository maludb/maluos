"""maluos-overlay: the estate's own network on this host (Phase 13 slice 1b, docs/phase13-slice1b-overlay.md).

The service (`python3 -m maluos_estate.overlay`, maluos-overlay.service as root with CAP_NET_ADMIN) reads whichever
enrolment exists (/etc/maluos/estate.yaml for a node, /etc/maluos/office.yaml for a desk), takes the WireGuard
private key and the token from the vault, makes the `estate` interface with the address the office gave at join,
peers it with the hub (or, on the hub, with every spoke), keeps a marked block of names in /etc/hosts
(NAME.internal), and reconciles all of that from GET endpoints.overlay every refresh_s, at once when a heartbeat
said overlay_changed (the hint file) or on SIGHUP. SIGTERM leaves the tunnel up; `maluctl estate overlay down`
and `leave` take it down.

Dry run (tests): MALUOS_OVERLAY_DRY_RUN=1 appends every ip/wg/sysctl command to MALUOS_OVERLAY_DRY_LOG instead of
running it; MALUOS_OVERLAY_HOSTS and MALUOS_OVERLAY_STATE point the hosts block and the state elsewhere.
"""
import base64, ipaddress, json, os, re, signal, subprocess, sys, threading, time

sys.path.insert(0, "/usr/lib/maluos")
from maluos_estate import client as C

IFACE = os.environ.get("MALUOS_OVERLAY_IFACE", "estate")
STATE = os.environ.get("MALUOS_OVERLAY_STATE", "/var/lib/maluos/overlay/state.json")   # its own directory: systemd re-owns a StateDirectory to its unit's user
HOSTS = os.environ.get("MALUOS_OVERLAY_HOSTS", "/etc/hosts")
RUN = os.environ.get("MALUOS_OVERLAY_RUN", "/run/maluos/overlay")
HINT = os.path.join(RUN, "changed")
DRY = os.environ.get("MALUOS_OVERLAY_DRY_RUN") == "1"
DRY_LOG = os.environ.get("MALUOS_OVERLAY_DRY_LOG", os.path.join(os.path.dirname(STATE), "overlay-dry.log"))
KEEPALIVE = 25
LISTEN_PORT = 51820
BEGIN, END = "# maluos-estate overlay begin", "# maluos-estate overlay end"
LADDER = (10, 30, 60)


def log(msg):
    sys.stderr.write(f"maluos-overlay: {msg}\n"); sys.stderr.flush()


def sh(args, input=None, check=True, quiet=False):
    """Run ip/wg/sysctl; in a dry run, record the command instead (a read-only `wg show` answers nothing)."""
    if DRY:
        with open(DRY_LOG, "a") as f:
            f.write(" ".join(args) + ("  <stdin>" if input is not None else "") + "\n")
        return ""
    r = subprocess.run(args, input=input, capture_output=True, text=True)
    if r.returncode != 0 and check:
        raise RuntimeError(f"{' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[-200:]}")
    return r.stdout


# -- keys: X25519, the WireGuard key pair, made here (the private half goes straight into the vault)
def genkey():
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    k = X25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(priv).decode(), base64.b64encode(pub).decode()


def pubkey(priv_b64):
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    k = X25519PrivateKey.from_private_bytes(base64.b64decode(priv_b64))
    return base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def valid_key(k):
    return isinstance(k, str) and re.fullmatch(r"[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=", k) is not None


# -- the enrolment this host has: a node's or a desk's
def enrolment():
    conf = C.read_conf()
    if conf:
        return "node", conf
    conf = C.desk_conf()
    if conf:
        return "desk", conf
    return None, None


def principal_of(kind, conf):
    return conf.get("principal") if kind == "node" else (conf.get("owner") or {}).get("principal")


def vault_value(ref, purpose):
    from maluos_vault_client import Vault
    return Vault(os.environ.get("MALUOS_VAULT_SOCKET")).value(ref, "read", purpose=purpose)["value"]


def token_for(kind, conf):
    if kind == "node":
        return C.token(conf)
    t = os.environ.get("MALUOS_OFFICE_TOKEN")
    return t or vault_value(f"{principal_of(kind, conf)}/{C.OFFICE_SECRET}", "overlay refresh")


def key_for(kind, conf):
    k = os.environ.get("MALUOS_OVERLAY_KEY")
    return k or vault_value(f"{principal_of(kind, conf)}/{C.SECRET_OVERLAY}", "the overlay tunnel")


def overlay_url(kind, conf):
    ep = (conf.get("endpoints") or {}).get("overlay")
    return ep or conf["url"].rstrip("/") + ("/api/v1/estate/overlay" if kind == "node" else "/api/v1/desks/overlay")


def fetch(kind, conf, tok, timeout=15):
    return C.http("GET", overlay_url(kind, conf), token=tok, timeout=timeout, agent=f"maluos-overlay/{C.VERSION}")


# -- what the interface should look like
def desired(conf, answer=None):
    """From the enrolment's overlay block (the join) and the office's latest answer: None when this host has no place
    on the overlay yet (no hub, opted out)."""
    o = conf.get("overlay") or {}
    a = answer or {}
    self_ = a.get("self") or {}
    address = self_.get("address") or o.get("address")
    hub = a.get("hub") if "hub" in a else o.get("hub")
    role = self_.get("role") or o.get("role") or ("hub" if hub is None and o.get("role") == "hub" else "spoke")
    if not address or (role == "spoke" and not hub):
        return None
    prefix = int(o.get("prefix") or 16)
    net = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
    if role == "hub":
        hub = None                            # the hub has no hub: its peers are the spokes
    return {"address": address, "prefix": prefix, "network": str(net), "role": role, "name": self_.get("name") or o.get("name"),
            "listen_port": int(o.get("listen_port") or LISTEN_PORT) if role == "hub" else None,
            "hub": hub, "peers": a.get("peers") if a else ([hub] if hub else []), "names": a.get("names") or [], "version": a.get("version")}


def current_peers():
    if DRY:
        st = read_state() or {}
        return {p["public_key"] for p in st.get("peers") or []}
    out = sh(["wg", "show", IFACE, "peers"], check=False)
    return {l.strip() for l in out.splitlines() if l.strip()}


def iface_exists():
    if DRY:
        return bool(read_state())
    return subprocess.run(["ip", "link", "show", IFACE], capture_output=True).returncode == 0


def apply(d, priv):
    """Make the interface match `d`; idempotent. Returns the peers configured."""
    if not iface_exists():
        sh(["ip", "link", "add", IFACE, "type", "wireguard"])
    args = ["wg", "set", IFACE, "private-key", "/dev/stdin"]
    if d["role"] == "hub":
        args += ["listen-port", str(d["listen_port"])]
    sh(args, input=priv + "\n")
    sh(["ip", "-4", "addr", "replace", f"{d['address']}/{d['prefix']}", "dev", IFACE])
    sh(["ip", "link", "set", IFACE, "up"])
    want = {}
    if d["role"] == "hub":
        for p in d["peers"] or []:
            if valid_key(p.get("public_key")) and p.get("address"):
                want[p["public_key"]] = ["allowed-ips", f"{p['address']}/32"]
        sh(["sysctl", "-q", "-w", f"net.ipv4.conf.{IFACE}.forwarding=1"], check=False)
    else:
        h = d["hub"]
        if valid_key(h.get("public_key")):
            want[h["public_key"]] = ["endpoint", h["endpoint"], "allowed-ips", d["network"], "persistent-keepalive", str(KEEPALIVE)]
    for pub in current_peers() - set(want):
        sh(["wg", "set", IFACE, "peer", pub, "remove"], check=False)
    for pub, rest in want.items():
        sh(["wg", "set", IFACE, "peer", pub, *rest])
    hosts_block(d["names"] or ([{"name": p.get("name"), "address": p.get("address")} for p in (d["peers"] or []) if p.get("name")]))
    return want


def down():
    if iface_exists():
        sh(["ip", "link", "del", IFACE], check=False)
    hosts_block([])
    try:
        os.remove(STATE)
    except OSError:
        pass


# -- names: a marked block in /etc/hosts
def hosts_block(names):
    try:
        cur = open(HOSTS).read() if os.path.exists(HOSTS) else ""
    except OSError as e:
        log(f"hosts: {e}"); return
    lines = cur.split("\n")
    if BEGIN in lines and END in lines:
        i, j = lines.index(BEGIN), lines.index(END)
        lines = lines[:i] + lines[j + 1:]
    while lines and lines[-1] == "":
        lines.pop()
    block = []
    for n in names:
        if n.get("address") and n.get("name") and re.fullmatch(r"[a-z0-9-]{1,63}(\.internal)?", n["name"]):
            label = n["name"] if n["name"].endswith(".internal") else n["name"] + ".internal"
            block.append(f"{n['address']}\t{label}")
    new = "\n".join(lines + ([BEGIN] + block + [END] if block else [])) + "\n"
    if new != cur:
        # In place (the unit may write this one file and not its directory): a short write of a small file.
        with open(HOSTS, "w") as f:
            f.write(new)


# -- the state the commands and the report read
def read_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return None


def write_state(st):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f, indent=1, default=str)
        os.chmod(tmp, 0o644); os.replace(tmp, STATE)
    except OSError as e:
        log(f"state: {e}")


def handshakes():
    """public key -> (latest handshake unix time, rx, tx) from `wg show IFACE dump`."""
    out = {}
    if DRY:
        return out
    for line in sh(["wg", "show", IFACE, "dump"], check=False).splitlines()[1:]:
        f = line.split("\t")
        if len(f) >= 7:
            out[f[0]] = (int(f[4] or 0), int(f[5] or 0), int(f[6] or 0))
    return out


def status():
    """For `maluctl estate overlay status`: the state file plus live handshakes when `wg` can be asked (root)."""
    st = read_state() or {}
    if st and os.geteuid() == 0 and not DRY:
        hs = handshakes()
        for p in st.get("peers") or []:
            h = hs.get(p.get("public_key"))
            p["last_handshake"] = h[0] if h else None; p["rx"] = h[1] if h else None; p["tx"] = h[2] if h else None
        st["interface_up"] = iface_exists()
    return st


def hint():
    """A heartbeat said overlay_changed: ask the service to refresh now (any user; the directory is 1777)."""
    try:
        os.makedirs(RUN, exist_ok=True)
        with open(HINT, "w") as f:
            f.write(C.utc() + "\n")
    except OSError:
        pass


def gateway_reload():
    if os.path.exists(os.environ.get("MALUOS_GATEWAY_SOCKET", "/run/maluos/gateway.sock")) and not DRY:
        subprocess.run([sys.executable, os.environ.get("MALUCTL_BIN", "/usr/bin/maluctl"), "gateway", "reload"], capture_output=True)


# -- one reconciliation: the enrolment, the office's answer, the interface, the state
def reconcile(kind, conf, tok, priv, answer=None):
    d = desired(conf, answer)
    if d is None:
        write_state({"ts": C.utc(), "role": (conf.get("overlay") or {}).get("role"), "address": (conf.get("overlay") or {}).get("address"),
                     "configured": False, "reason": "no hub yet" if (conf.get("overlay") or {}).get("address") else "no overlay for this host",
                     "peers": [], "names": [], "version": (answer or {}).get("version")})
        return None
    had = bool(read_state() and (read_state() or {}).get("configured"))
    want = apply(d, priv)
    peers = [p for p in (d["peers"] or []) if p.get("public_key") in want]
    if d["role"] == "spoke":
        peers = [{"name": (d["hub"] or {}).get("name") or "hub", "address": (d["hub"] or {}).get("address"), "public_key": (d["hub"] or {}).get("public_key"), "endpoint": (d["hub"] or {}).get("endpoint")}]
    hs = handshakes()
    for p in peers:
        h = hs.get(p.get("public_key"))
        p["last_handshake"] = h[0] if h and h[0] else None
    write_state({"ts": C.utc(), "role": d["role"], "address": d["address"], "prefix": d["prefix"], "name": d["name"], "listen_port": d["listen_port"],
                 "hub": d["hub"], "configured": True, "peers": peers, "names": d["names"], "version": d.get("version"), "interface": IFACE})
    if not had:
        gateway_reload()      # a gateway exposed with --bind overlay can bind now
    return d


def main(argv=None):
    stop, hup = threading.Event(), threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGHUP, lambda *_: hup.set())
    try:
        os.makedirs(RUN, exist_ok=True); os.chmod(RUN, 0o1777)
    except OSError:
        pass

    def pause(seconds):
        end = time.time() + seconds
        while not stop.is_set() and not hup.is_set() and time.time() < end:
            if os.path.exists(HINT):
                return
            time.sleep(min(2.0, max(0.0, end - time.time())))
    fails, last, tok, priv, last_kind = 0, 0.0, None, None, None
    while not stop.is_set():
        hup.clear()
        try:
            os.remove(HINT)
        except OSError:
            pass
        kind, conf = enrolment()
        if not conf:
            if last_kind:
                log("the enrolment is gone: taking the tunnel down"); down()
            else:
                log("no enrolment (estate.yaml or office.yaml): nothing to do")
            return 0
        if kind != last_kind:
            tok = priv = None; last_kind = kind
        if (conf.get("overlay") or {}).get("address") is None and not (conf.get("overlay") or {}):
            write_state({"ts": C.utc(), "configured": False, "reason": "this host joined without an overlay key", "peers": [], "names": []})
            pause(300); continue
        try:
            priv = priv or key_for(kind, conf)
            tok = tok or token_for(kind, conf)
        except Exception as e:
            fails += 1
            log(f"vault: {e.__class__.__name__}: {str(e)[:120]}")
            pause(LADDER[min(fails, len(LADDER)) - 1]); continue
        try:
            st, ans = fetch(kind, conf, tok)
        except Exception as e:
            st, ans = 0, {"error": f"{e.__class__.__name__}: {str(e)[:120]}"}
        refresh_s = 60
        if st == 200:
            fails = 0
            try:
                reconcile(kind, conf, tok, priv, ans)
            except Exception as e:
                log(f"apply: {e.__class__.__name__}: {str(e)[:160]}")
            refresh_s = int(ans.get("refresh_s") or 60)
        else:
            fails += 1
            if st in (401, 410):
                tok = None
            log(f"office: {st} {ans.get('error') or ''} {ans.get('message') or ''}".strip())
            if priv and not (read_state() or {}).get("configured"):
                try:
                    reconcile(kind, conf, tok, priv, None)     # the join's block alone: the hub as given, until the office answers
                except Exception as e:
                    log(f"apply: {e.__class__.__name__}: {str(e)[:160]}")
            refresh_s = LADDER[fails - 1] if fails <= len(LADDER) else 60
        pause(refresh_s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
