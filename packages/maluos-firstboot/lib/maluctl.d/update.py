"""maluctl update: software updates on a MaluOS system.

  maluctl update status [--json]      what is pending and where it comes from, when the
                                      package lists were last refreshed, what installs on
                                      its own, whether a restart is needed
  maluctl update check                refresh the package lists now (apt-get update)
  maluctl update apply [--all] [-y]   install updates now: by default what the automatic
                                      policy covers (security, MaluOS, Mozilla), with --all
                                      every pending update (apt-get full-upgrade)
  maluctl update history [-n N]       the last automatic runs and apt's own history
  maluctl update auto                 the automatic-update switches
  maluctl update auto on|off          automatic updates on (the shipped policy) or off
  maluctl update auto set ORIGIN on|off     security | maluos | mozilla: what the automatic run covers
  maluctl update auto reboot on|off [--at HH:MM]   restart on its own to finish updates (default off)

Updates on MaluOS come from three places: Ubuntu's security pocket, the MaluOS
repository (apt.maluos.com) and Mozilla's repository (Firefox). All three
install on their own through unattended-upgrades (apt-daily-upgrade.timer,
policy in /etc/apt/apt.conf.d/52maluos-unattended-upgrades); other updates
wait for `maluctl update apply --all` or, on the desktop, GNOME Software.
`auto` writes two drop-ins beside the policy, 53maluos-auto (the periodic
switch and the restart keys) and 54maluos-origins (the shipped origins minus
the ones switched off), and never edits the policy itself; with every switch
at its default both drop-ins are removed. The package lists still refresh
daily with automatic updates off, so `apply` has something to install.
`status` and `auto` (reading) need no privileges; `check`, `apply` and
changing `auto` need root.
"""
import json, os, subprocess, sys, time

STAMP_LISTS = "/var/lib/apt/periodic/update-success-stamp"
STAMP_AUTO = "/var/lib/apt/periodic/unattended-upgrades-stamp"
REBOOT = "/var/run/reboot-required"
REBOOT_PKGS = "/var/run/reboot-required.pkgs"
LISTS = "/var/lib/apt/lists"
UU_LOG = "/var/log/unattended-upgrades/unattended-upgrades.log"
APT_HISTORY = "/var/log/apt/history.log"
POLICY = "/etc/apt/apt.conf.d/52maluos-unattended-upgrades"      # shipped by maluos-branding, never edited here
AUTO_CONF = "/etc/apt/apt.conf.d/53maluos-auto"                 # the periodic switch and the restart keys
ORIGINS_CONF = "/etc/apt/apt.conf.d/54maluos-origins"           # the shipped origins minus the ones switched off
AUTO_STATE = "/var/lib/maluos/update-auto.json"                 # what was chosen, when and by whom
ORIGIN_KINDS = ("security", "maluos", "mozilla")


def mtime(path):
    try:
        return int(os.stat(path).st_mtime)
    except OSError:
        return None


def ago(ts):
    if not ts:
        return "never"
    d = int(time.time()) - ts
    if d < 90:
        return f"{d} s ago"
    if d < 5400:
        return f"{d // 60} min ago"
    if d < 172800:
        return f"{d // 3600} h ago"
    return f"{d // 86400} days ago"


def apt_config():
    """The unattended-upgrades policy and the periodic switches, as apt sees them."""
    import apt_pkg
    apt_pkg.init_config()
    c = apt_pkg.config
    return {"allowed_origins": c.value_list("Unattended-Upgrade::Allowed-Origins"),
            "origins_pattern": c.value_list("Unattended-Upgrade::Origins-Pattern"),
            "periodic_update": c.find_i("APT::Periodic::Update-Package-Lists", 0),
            "periodic_upgrade": c.find_i("APT::Periodic::Unattended-Upgrade", 0)}


def source_of(version):
    """Where a candidate version comes from: mozilla, maluos, security, ubuntu or other.
    A version listed by several sources takes the most specific one (the security pocket
    beats the plain archive that also carries it)."""
    rank = {"mozilla": 0, "maluos": 1, "security": 2, "ubuntu": 3, "other": 4}
    best, best_site = None, ""
    for o in version.origins or []:
        site = (o.site or "").lower()
        if site == "packages.mozilla.org":
            kind = "mozilla"
        elif (o.origin or "") == "MaluOS":
            kind = "maluos"
        elif (o.archive or "").endswith("-security"):
            kind = "security"
        elif (o.origin or "") == "Ubuntu":
            kind = "ubuntu"
        elif site or o.origin:
            kind = "other"
        else:
            continue
        if best is None or rank[kind] < rank[best]:
            best, best_site = kind, site
    return best or "other", best_site


def automatic(source, policy):
    """Does the unattended-upgrades policy install from this source?"""
    if not policy.get("periodic_upgrade"):
        return False
    if source == "mozilla":
        return any("packages.mozilla.org" in p for p in policy["origins_pattern"])
    if source == "maluos":
        return any(a.startswith("MaluOS:") for a in policy["allowed_origins"])
    if source == "security":
        return any(a.endswith("-security") for a in policy["allowed_origins"])
    return False


def timer_next(unit):
    try:
        out = subprocess.run(["systemctl", "show", "-p", "NextElapseUSecRealtime", "--value", unit], capture_output=True, text=True, timeout=10).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def status():
    import apt
    policy = apt_config()
    pending = []
    try:
        cache = apt.Cache()
        for p in cache:
            if not p.is_upgradable:
                continue
            src, site = source_of(p.candidate)
            pending.append({"name": p.name, "installed": p.installed.version if p.installed else None, "candidate": p.candidate.version,
                            "source": src, "site": site, "automatic": automatic(src, policy),
                            "security": src == "security" or any((o.archive or "").endswith("-security") for o in p.candidate.origins or [])})
    except Exception as e:  # a half-written cache, or apt busy: report rather than fail
        pending_error = f"{e.__class__.__name__}: {str(e)[:120]}"
    else:
        pending_error = None
    pending.sort(key=lambda x: (not x["security"], x["source"], x["name"]))
    counts = {}
    for p in pending:
        counts[p["source"]] = counts.get(p["source"], 0) + 1
    reboot_pkgs = []
    try:
        reboot_pkgs = [l.strip() for l in open(REBOOT_PKGS) if l.strip()]
    except OSError:
        pass
    lists_ts = mtime(STAMP_LISTS) or mtime(LISTS)
    return {"ts": int(time.time()),
            "pending": pending, "pending_count": len(pending), "pending_error": pending_error,
            "security_count": sum(1 for p in pending if p["security"]),
            "automatic_count": sum(1 for p in pending if p["automatic"]),
            "by_source": counts,
            "lists_refreshed_at": lists_ts, "lists_refreshed": ago(lists_ts),
            "last_automatic_run_at": mtime(STAMP_AUTO), "last_automatic_run": ago(mtime(STAMP_AUTO)),
            "automatic": {"enabled": bool(policy["periodic_update"] and policy["periodic_upgrade"]),
                          "origins": policy["allowed_origins"] + policy["origins_pattern"],
                          "next_refresh": timer_next("apt-daily.timer"), "next_run": timer_next("apt-daily-upgrade.timer")},
            "reboot_required": os.path.exists(REBOOT), "reboot_packages": reboot_pkgs,
            "auto": auto_state(policy)}


def print_status(s):
    print(f"package lists: refreshed {s['lists_refreshed']}")
    a = s["automatic"]; au = s.get("auto") or {}
    off = "" if a["enabled"] else (f" since {au['changed_at'][:16]} by {au['changed_by']}" if au.get("changed_at") else "")
    print(f"automatic:     {'on' if a['enabled'] else 'OFF' + off} · last run {s['last_automatic_run']}" + (f" · next {a['next_run']}" if a.get("next_run") and a["next_run"] != "n/a" else ""))
    print("               origins: " + (", ".join(a["origins"]) or "none") + (f" · switched off: {', '.join(au['disabled'])}" if au.get("disabled") else ""))
    if (au.get("reboot") or {}).get("enabled"):
        print(f"               restarts on its own at {au['reboot'].get('at')} to finish updates")
    if s["pending_error"]:
        print(f"pending:       unknown ({s['pending_error']})")
    elif not s["pending"]:
        print("pending:       nothing; the system is up to date as of the last refresh")
    else:
        print(f"pending:       {s['pending_count']} ({s['security_count']} security, {s['automatic_count']} will install on their own)")
        for p in s["pending"]:
            print(f"  {p['name']:<32} {p['installed'] or '-':<24} -> {p['candidate']:<24} {p['source']}{' (security)' if p['security'] and p['source'] != 'security' else ''}{'' if p['automatic'] else '  manual'}")
    if s["reboot_required"]:
        print("restart:       REQUIRED to finish updates" + (f" ({', '.join(s['reboot_packages'])})" if s["reboot_packages"] else ""))
    else:
        print("restart:       not needed")


def need_root():
    if os.geteuid() != 0:
        print("maluctl update: this needs root (sudo)", file=sys.stderr); sys.exit(1)


def apply(args):
    need_root()
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    yes = "-y" in args or "--yes" in args
    if "--all" in args:
        cmd = ["apt-get", "full-upgrade"] + (["-y"] if yes else [])
        print("apt-get full-upgrade: every pending update", flush=True)
    else:
        cmd = ["unattended-upgrade", "-v"]
        print("unattended-upgrade: the automatic policy's updates (security, MaluOS, Mozilla)", flush=True)
    return subprocess.call(cmd, env=env)


def history(args):
    n = 10
    if "-n" in args:
        n = int(args[args.index("-n") + 1])
    shown = False
    try:
        lines = [l.rstrip("\n") for l in open(UU_LOG)]
        runs = [l for l in lines if "Packages that will be upgraded" in l or "All upgrades installed" in l or "No packages found" in l]
        if runs:
            print("unattended-upgrades:"); shown = True
            for l in runs[-n:]:
                print("  " + l)
    except OSError:
        pass
    try:
        blocks, cur = [], []
        for l in open(APT_HISTORY):
            if l.strip() == "":
                if cur:
                    blocks.append(cur); cur = []
            else:
                cur.append(l.rstrip("\n"))
        if cur:
            blocks.append(cur)
        if blocks:
            print("apt history:"); shown = True
            for b in blocks[-n:]:
                d = dict(l.split(": ", 1) for l in b if ": " in l)
                what = next((k for k in ("Upgrade", "Install", "Remove", "Purge") if k in d), "?")
                items = d.get(what, "")
                print(f"  {d.get('Start-Date', '?')}  {what.lower():<8} {len(items.split('), ')) if items else 0} packages  {d.get('Commandline', '')[:60]}")
    except OSError:
        pass
    if not shown:
        print("no history readable here (the logs are root-only: try sudo)")
    return 0


# ---------------------------------------------------------------- auto: the switches
def _who():
    import pwd
    for var in ("PKEXEC_UID",):
        if os.environ.get(var, "").isdigit():
            try:
                return pwd.getpwuid(int(os.environ[var])).pw_name
            except KeyError:
                pass
    return os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name


def _read_state():
    try:
        with open(AUTO_STATE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return {"enabled": d.get("enabled", True), "disabled": [o for o in d.get("disabled") or [] if o in ORIGIN_KINDS],
            "reboot": {"enabled": bool((d.get("reboot") or {}).get("enabled")), "at": (d.get("reboot") or {}).get("at") or "03:00"},
            "changed_at": d.get("changed_at"), "changed_by": d.get("changed_by")}


def _is_default(st):
    return st["enabled"] and not st["disabled"] and not st["reboot"]["enabled"]


def _shipped_origins():
    """The origins of the shipped policy alone (52maluos-unattended-upgrades), not the effective ones."""
    import apt_pkg
    cfg = apt_pkg.Configuration()
    try:
        apt_pkg.read_config_file(cfg, POLICY)
    except SystemError:
        return [], []
    return cfg.value_list("Unattended-Upgrade::Allowed-Origins"), cfg.value_list("Unattended-Upgrade::Origins-Pattern")


def _origin_kind(entry):
    if "packages.mozilla.org" in entry:
        return "mozilla"
    if entry.startswith("MaluOS:"):
        return "maluos"
    if entry.endswith("-security"):
        return "security"
    return None


def auto_state(policy=None):
    st = _read_state()
    st["managed"] = os.path.exists(AUTO_CONF) or os.path.exists(ORIGINS_CONF)
    if policy is not None:
        st["effective_enabled"] = bool(policy["periodic_upgrade"])
    return st


def _write_auto(st):
    """Write (or remove) the two drop-ins and the state file from ST."""
    if _is_default(st):
        for path in (AUTO_CONF, ORIGINS_CONF, AUTO_STATE):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        return
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    head = ("// MaluOS: written by `maluctl update auto`; do not edit. `maluctl update auto on` with every\n"
            "// origin on and the restart off removes this file and restores the shipped policy (52maluos-unattended-upgrades).\n"
            f"// changed {stamp} by {st['changed_by']}\n")
    body = head + f'APT::Periodic::Unattended-Upgrade "{1 if st["enabled"] else 0}";\n'
    body += f'Unattended-Upgrade::Automatic-Reboot "{"true" if st["reboot"]["enabled"] else "false"}";\n'
    if st["reboot"]["enabled"]:
        body += f'Unattended-Upgrade::Automatic-Reboot-Time "{st["reboot"]["at"]}";\n'
    _atomic(AUTO_CONF, body)
    if st["disabled"]:
        allowed, patterns = _shipped_origins()
        allowed = [a for a in allowed if _origin_kind(a) not in st["disabled"]]
        patterns = [p for p in patterns if _origin_kind(p) not in st["disabled"]]
        text = head + "#clear Unattended-Upgrade::Allowed-Origins;\n#clear Unattended-Upgrade::Origins-Pattern;\n"
        text += "Unattended-Upgrade::Allowed-Origins {\n" + "".join(f'    "{a}";\n' for a in allowed) + "};\n"
        text += "Unattended-Upgrade::Origins-Pattern {\n" + "".join(f'    "{p}";\n' for p in patterns) + "};\n"
        _atomic(ORIGINS_CONF, text)
    else:
        try:
            os.unlink(ORIGINS_CONF)
        except FileNotFoundError:
            pass
    os.makedirs(os.path.dirname(AUTO_STATE), exist_ok=True)
    _atomic(AUTO_STATE, json.dumps({k: st[k] for k in ("enabled", "disabled", "reboot", "changed_at", "changed_by")}, indent=1) + "\n")


def _atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def print_auto(st):
    print(f"automatic updates: {'on' if st['enabled'] else 'OFF'}" + (f" (changed {st['changed_at'][:16]} by {st['changed_by']})" if st.get("changed_at") else " (shipped default)"))
    for k in ORIGIN_KINDS:
        print(f"  {k:<9} {'off' if k in st['disabled'] else 'on'}")
    r = st["reboot"]
    print(f"  restart   {'on, at ' + r['at'] if r['enabled'] else 'off'} (restart on its own to finish updates)")
    if st.get("managed"):
        print(f"  drop-ins: {AUTO_CONF}" + (f", {ORIGINS_CONF}" if os.path.exists(ORIGINS_CONF) else ""))


def auto(args):
    if not args or args[0] in ("status", "show"):
        print_auto(auto_state()); return 0
    need_root()
    st = _read_state()
    cmd = args[0]
    if cmd in ("on", "off"):
        st["enabled"] = cmd == "on"
    elif cmd == "set" and len(args) >= 3 and args[1] in ORIGIN_KINDS and args[2] in ("on", "off"):
        st["disabled"] = [o for o in st["disabled"] if o != args[1]] + ([args[1]] if args[2] == "off" else [])
        st["disabled"] = [o for o in ORIGIN_KINDS if o in st["disabled"]]
    elif cmd == "reboot" and len(args) >= 2 and args[1] in ("on", "off"):
        st["reboot"]["enabled"] = args[1] == "on"
        if "--at" in args:
            at = args[args.index("--at") + 1]
            if not (len(at) == 5 and at[2] == ":" and at[:2].isdigit() and at[3:].isdigit() and int(at[:2]) < 24 and int(at[3:]) < 60):
                print(f"maluctl update auto: --at takes HH:MM, not {at!r}", file=sys.stderr); return 2
            st["reboot"]["at"] = at
    else:
        print("usage: maluctl update auto [on|off | set security|maluos|mozilla on|off | reboot on|off [--at HH:MM]]", file=sys.stderr); return 2
    st["changed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); st["changed_by"] = _who()
    _write_auto(st)
    print_auto(auto_state()); return 0


def main(args):
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.rstrip()); return 0 if args else 2
    cmd, rest = args[0], args[1:]
    if cmd == "status":
        s = status()
        if "--json" in rest:
            print(json.dumps(s, indent=None if "--compact" in rest else 2))
        else:
            print_status(s)
        return 0
    if cmd == "check":
        need_root()
        return subprocess.call(["apt-get", "update"] + (["-q"] if "-q" in rest else []))
    if cmd == "apply":
        return apply(rest)
    if cmd == "history":
        return history(rest)
    if cmd == "auto":
        return auto(rest)
    print(__doc__.rstrip()); return 2
