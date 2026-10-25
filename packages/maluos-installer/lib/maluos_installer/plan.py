"""The install plan (docs/install-plan.md): schema, defaults, references, redaction.

A plan is a mapping under `maluos-install` with a `version`. Unknown keys are
errors. Every key has a default; some defaults depend on the medium's variant
(server or desktop), so `load()` takes the variant. `file:` and `url:`
references are resolved by `resolve_refs()` once the media and the network are
there; `redact()` gives the copy that may be written to a log.
"""
import copy, json, os, re, subprocess, time, urllib.request

try:
    import yaml
except ImportError:  # the unit test host may lack PyYAML; JSON plans still work
    yaml = None


class PlanError(Exception):
    pass


SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGT]?)(?:i?B)?\s*$", re.I)
UNITS = {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}


def parse_size(s):
    """'50G' -> bytes, as sfdisk reads sizes (binary units). 'all' and 'auto' pass through."""
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return int(s)
    if not isinstance(s, str):
        raise PlanError(f"a size must be a string like 50G, not {s!r}")
    low = s.strip().lower()
    if low in ("all", "auto", "none"):
        return low
    m = SIZE_RE.match(s)
    if not m:
        raise PlanError(f"bad size {s!r} (use a number with K, M, G or T)")
    return int(float(m.group(1)) * UNITS[m.group(2).upper()])


def fmt_size(n):
    for unit, div in (("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10)):
        if n >= div and n % div == 0:
            return f"{n // div}{unit}"
    for unit, div in (("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(n)


# --- the schema ---------------------------------------------------------------
# type: 'bool' | 'int' | 'str' | 'size' | 'list' (of str) | ('enum', [...]) | dict (a nested mapping)
# default: a value, or a callable of the variant ('server'|'desktop')
S = lambda t, d=None, **k: {"type": t, "default": d, **k}
E = lambda vals, d: {"type": ("enum", vals), "default": d}

SCHEMA = {
    "version": S("int", 1),
    "source": {
        "image": S("str", lambda v: f"maluos-{v}"),
        "verify": S("bool", True),
        "repository": E(["media", "none"], "media"),
    },
    "locale": {
        "language": S("str", "en_US.UTF-8"),
        "keyboard": {"layout": S("str", "us"), "variant": S("str", "")},
        "timezone": S("str", "UTC"),
    },
    "network": {
        "mode": E(["dhcp", "static", "none"], "dhcp"),
        "interface": S("str", ""),
        "address": S("str", ""),
        "gateway": S("str", ""),
        "nameservers": S("list", []),
        "search": S("list", []),
        "proxy": S("str", ""),
        "wifi": {"ssid": S("str", ""), "password": S("str", "")},
    },
    "storage": {
        "disk": S("str", ""),
        "target": E(["disk", "free"], "disk"),
        "erase": S("bool", False),
        "layout": E(["direct", "lvm"], "lvm"),
        "root_size": S("size", lambda v: "all"),   # 50G for lvm, filled by fill_defaults
        "filesystem": E(["ext4", "xfs"], "ext4"),
        "encrypt": S("bool", False),
        "passphrase": S("str", ""),
        "swap": S("size", "auto"),
        "esp_size": S("size", "1G"),
        "boot_size": S("size", "2G"),
        "label": S("str", "maluos"),
    },
    "identity": {
        "hostname": S("str", "maluos"),
        "user": {
            "name": S("str", ""),
            "fullname": S("str", ""),
            "password": S("str", ""),
            "ssh_keys": S("list", []),
            "password_change_required": S("bool", False),
        },
        "ssh": {
            "server": S("bool", lambda v: v == "server"),
            "password_auth": S("bool", False),
        },
    },
    "components": {"install": S("list", []), "remove": S("list", [])},
    "firstboot": {
        "tenant": S("str", "maluos"),
        "admin": {"principal": S("str", "human:admin")},
        "components": S("map", {}),
        "enroll": {
            "kind": E(["", "office", "estate"], ""),
            "url": S("str", ""),
            "code": S("str", ""),
            "name": S("str", ""),
        },
        "cloud_init": S("bool", lambda v: v == "server"),
    },
    "bootloader": {
        "mode": E(["auto", "bios", "uefi", "both"], "auto"),
        "secure_boot": E(["auto", "required", "ignore"], "auto"),
        "cmdline": S("str", ""),
        "timeout": S("int", lambda v: 3 if v == "server" else 0),
        "efi_entry": S("str", "MaluOS"),
    },
    "telemetry": {
        "send": S("bool", False),
        "url": S("str", "https://telemetry.maluos.com/v1/install"),
    },
    "finish": {
        "action": E(["reboot", "poweroff", "shell", "none"], "reboot"),
        "eject": S("bool", True),
        "log": S("str", "/var/log/maluos-install/"),
    },
}

SECRET_PATHS = (("identity", "user", "password"), ("storage", "passphrase"),
                ("firstboot", "enroll", "code"), ("network", "wifi", "password"))
REF_PATHS = SECRET_PATHS + (("identity", "user", "ssh_keys"),)


def _is_leaf(node):
    return isinstance(node, dict) and "type" in node and "default" in node


def _default(leaf, variant):
    d = leaf["default"]
    return d(variant) if callable(d) else copy.deepcopy(d)


def _check_type(path, leaf, value):
    t = leaf["type"]
    where = ".".join(path)
    if t == "bool":
        if not isinstance(value, bool):
            raise PlanError(f"{where}: expected true or false, got {value!r}")
    elif t == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise PlanError(f"{where}: expected a whole number, got {value!r}")
    elif t == "str":
        if value is None:
            return ""
        if not isinstance(value, str):
            raise PlanError(f"{where}: expected a string, got {value!r}")
    elif t == "size":
        parse_size(value)
        return value if isinstance(value, str) else str(value)
    elif t == "list":
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise PlanError(f"{where}: expected a list of strings, got {value!r}")
    elif t == "map":
        if not isinstance(value, dict):
            raise PlanError(f"{where}: expected a mapping, got {value!r}")
    elif isinstance(t, tuple) and t[0] == "enum":
        if value is None:
            value = ""
        if value not in t[1]:
            raise PlanError(f"{where}: expected one of {', '.join(repr(x) for x in t[1] if x)}, got {value!r}")
    return value


def _walk(schema, given, variant, path=()):
    """Fill defaults, check types, refuse unknown keys. Returns the filled mapping."""
    if given is None:
        given = {}
    if not isinstance(given, dict):
        raise PlanError(f"{'.'.join(path) or 'plan'}: expected a mapping, got {given!r}")
    out = {}
    for k in given:
        if k not in schema:
            known = ", ".join(sorted(schema))
            raise PlanError(f"unknown key {'.'.join(path + (k,))!r} (known here: {known})")
    for k, node in schema.items():
        if _is_leaf(node):
            if k in given:
                out[k] = _check_type(path + (k,), node, given[k])
            else:
                out[k] = _default(node, variant)
        else:
            out[k] = _walk(node, given.get(k), variant, path + (k,))
    return out


def parse(text):
    """YAML or JSON text -> the raw mapping under maluos-install."""
    text = text.lstrip("﻿")
    try:
        doc = json.loads(text) if text.lstrip().startswith("{") else (yaml.safe_load(text) if yaml else json.loads(text))
    except Exception as e:
        raise PlanError(f"the plan is not valid YAML or JSON: {e}")
    if not isinstance(doc, dict) or "maluos-install" not in doc:
        raise PlanError("the plan must be a mapping with a top-level 'maluos-install' key")
    return doc["maluos-install"]


def fill_defaults(raw, variant="server"):
    """Validate the raw mapping and fill every default. Returns the plan."""
    if not isinstance(raw, dict):
        raise PlanError("maluos-install must be a mapping")
    if "version" not in raw:
        raise PlanError("maluos-install.version is required (1)")
    plan = _walk(SCHEMA, raw, variant)
    if plan["version"] != 1:
        raise PlanError(f"plan version {plan['version']} is not supported (this installer knows version 1)")
    st = plan["storage"]
    if "root_size" not in (raw.get("storage") or {}):
        st["root_size"] = "50G" if st["layout"] == "lvm" else "all"
    if not plan["identity"]["user"]["fullname"]:
        plan["identity"]["user"]["fullname"] = plan["identity"]["user"]["name"]
    if not plan["firstboot"]["enroll"]["name"]:
        plan["firstboot"]["enroll"]["name"] = plan["identity"]["hostname"]
    plan["_variant"] = variant
    return plan


def semantic_errors(plan):
    """What a filled plan still gets wrong, before any machine is looked at."""
    errs = []
    st, idn, net, fb = plan["storage"], plan["identity"], plan["network"], plan["firstboot"]
    if not st["disk"]:
        errs.append("storage.disk is required (first, /dev/..., id:, serial: or model:)")
    if st["target"] == "disk" and st["erase"] is not True:
        errs.append("storage.erase must be true: with storage.target disk the installer erases the whole disk")
    if st["target"] == "free" and st["erase"]:
        errs.append("storage.erase must be false with storage.target free: the existing partitions are kept")
    if st["encrypt"] and not st["passphrase"]:
        errs.append("storage.passphrase is required when storage.encrypt is true")
    rs = parse_size(st["root_size"])
    if rs == "auto" or rs == "none":
        errs.append("storage.root_size must be a size or 'all'")
    elif rs != "all" and rs < 8 << 30:
        errs.append(f"storage.root_size {st['root_size']} is under 8G")
    for key in ("esp_size", "boot_size"):
        v = parse_size(st[key])
        if not isinstance(v, int) or v < 32 << 20:
            errs.append(f"storage.{key} must be a size of at least 32M")
    sw = parse_size(st["swap"])
    if sw == "all":
        errs.append("storage.swap must be a size, auto or none")
    if not idn["user"]["name"]:
        errs.append("identity.user.name is required")
    elif not re.match(r"^[a-z_][a-z0-9_-]{0,31}$", idn["user"]["name"]):
        errs.append(f"identity.user.name {idn['user']['name']!r} is not a valid login")
    if not idn["user"]["password"] and not idn["user"]["ssh_keys"]:
        errs.append("identity.user needs a password or ssh_keys (else nobody can log in)")
    pw = idn["user"]["password"]
    if pw and not (pw.startswith("$") or pw.startswith("plain:") or pw.startswith("file:")):
        errs.append("identity.user.password must be a crypt hash ($6$...), 'plain:' + a password, or 'file:' + a path")
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$", idn["hostname"]):
        errs.append(f"identity.hostname {idn['hostname']!r} is not a valid host name")
    if net["mode"] == "static":
        if not net["address"] or "/" not in net["address"]:
            errs.append("network.address (CIDR) is required for network.mode static")
        if not net["gateway"]:
            errs.append("network.gateway is required for network.mode static")
    if net["wifi"]["ssid"]:
        errs.append("network.wifi is not supported yet (Phase 11 slice 3)")
    if fb["enroll"]["kind"] and not fb["enroll"]["url"]:
        errs.append("firstboot.enroll.url is required with firstboot.enroll.kind")
    if fb["enroll"]["kind"] and not fb["enroll"]["code"]:
        errs.append("firstboot.enroll.code is required with firstboot.enroll.kind")
    img = plan["source"]["image"]
    if "://" in img:
        errs.append("source.image from a URL is not supported yet (the key is reserved)")
    elif "/" in img:
        errs.append("source.image is a name under /maluos/images/, not a path")
    return errs


def load(text, variant="server"):
    """Text -> filled plan, or PlanError with every semantic error in the message."""
    plan = fill_defaults(parse(text), variant)
    errs = semantic_errors(plan)
    if errs:
        raise PlanError("the plan has errors:\n  - " + "\n  - ".join(errs))
    return plan


# --- references ------------------------------------------------------------------
def _get(plan, path):
    node = plan
    for p in path:
        node = node[p]
    return node


def _set(plan, path, value):
    node = plan
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value


def fetch_url(url, timeout=20, retries=(5, 10, 20, 30, 55), log=None):
    """GET url with a retry ladder of about two minutes. Returns the text."""
    last = None
    for i, wait in enumerate((0,) + tuple(retries)):
        if wait:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "maluos-install"}), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            if log:
                log(f"fetching {url}: {e.__class__.__name__}: {e} (attempt {i + 1})")
    raise PlanError(f"could not fetch {url} after two minutes: {last}")


def read_ref(value, media="/cdrom", mounts=None, log=None):
    """Resolve 'file:PATH', 'file:LABEL=NAME:/path' or 'url:URL'; anything else is returned as given."""
    if not isinstance(value, str):
        return value
    if value.startswith("url:"):
        return fetch_url(value[4:].strip(), log=log).strip()
    if value.startswith("file:"):
        spec = value[5:].strip()
        if spec.startswith("LABEL="):
            label, _, rel = spec[6:].partition(":")
            root = (mounts or {}).get(label) or mount_label(label)
            path = os.path.join(root, rel.lstrip("/"))
        elif spec.startswith("/"):
            path = spec
            if not os.path.exists(path) and os.path.exists(os.path.join(media, spec.lstrip("/"))):
                path = os.path.join(media, spec.lstrip("/"))
        else:
            path = os.path.join(media, spec)
        try:
            return open(path).read().strip()
        except OSError as e:
            raise PlanError(f"cannot read {value}: {e}")
    return value


def mount_label(label, base="/run/maluos-install/media"):
    """Mount the filesystem labelled LABEL read-only under base/LABEL; returns the path."""
    path = os.path.join(base, label)
    if os.path.ismount(path):
        return path
    os.makedirs(path, exist_ok=True)
    r = subprocess.run(["mount", "-o", "ro", f"LABEL={label}", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise PlanError(f"no filesystem labelled {label}: {r.stderr.strip()}")
    return path


def resolve_refs(plan, media="/cdrom", log=None):
    """Replace every file:/url: reference in the plan with its content (in place)."""
    for path in REF_PATHS:
        v = _get(plan, path)
        if isinstance(v, list):
            out = []
            for item in v:
                r = read_ref(item, media, log=log)
                if r is item:
                    out.append(item)
                else:  # a file or URL of keys: one per line, comments dropped
                    out.extend(line.strip() for line in r.splitlines() if line.strip() and not line.startswith("#"))
            _set(plan, path, out)
        else:
            _set(plan, path, read_ref(v, media, log=log))
    return plan


def redact(plan):
    """A deep copy with every secret replaced, fit for a log."""
    p = copy.deepcopy(plan)
    for path in SECRET_PATHS:
        if _get(p, path):
            _set(p, path, "<redacted>")
    p.pop("_variant", None)
    return p


def dump(plan):
    """The plan as YAML (or JSON without PyYAML), under maluos-install."""
    doc = {"maluos-install": {k: v for k, v in plan.items() if not k.startswith("_")}}
    if yaml:
        return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    return json.dumps(doc, indent=2) + "\n"
