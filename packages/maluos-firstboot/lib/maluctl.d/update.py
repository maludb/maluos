"""maluctl update: software updates on a MaluOS system.

  maluctl update status [--json]      what is pending and where it comes from, when the
                                      package lists were last refreshed, what installs on
                                      its own, whether a restart is needed
  maluctl update check                refresh the package lists now (apt-get update)
  maluctl update apply [--all] [-y]   install updates now: by default what the automatic
                                      policy covers (security, MaluOS, Mozilla), with --all
                                      every pending update (apt-get full-upgrade)
  maluctl update history [-n N]       the last automatic runs and apt's own history

Updates on MaluOS come from three places: Ubuntu's security pocket, the MaluOS
repository (apt.maluos.com) and Mozilla's repository (Firefox). All three
install on their own through unattended-upgrades (apt-daily-upgrade.timer,
policy in /etc/apt/apt.conf.d/52maluos-unattended-upgrades); other updates
wait for `maluctl update apply --all` or, on the desktop, GNOME Software.
`status` needs no privileges; `check` and `apply` need root.
"""
import json, os, subprocess, sys, time

STAMP_LISTS = "/var/lib/apt/periodic/update-success-stamp"
STAMP_AUTO = "/var/lib/apt/periodic/unattended-upgrades-stamp"
REBOOT = "/var/run/reboot-required"
REBOOT_PKGS = "/var/run/reboot-required.pkgs"
LISTS = "/var/lib/apt/lists"
UU_LOG = "/var/log/unattended-upgrades/unattended-upgrades.log"
APT_HISTORY = "/var/log/apt/history.log"


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
            "reboot_required": os.path.exists(REBOOT), "reboot_packages": reboot_pkgs}


def print_status(s):
    print(f"package lists: refreshed {s['lists_refreshed']}")
    a = s["automatic"]
    print(f"automatic:     {'on' if a['enabled'] else 'OFF'} · last run {s['last_automatic_run']}" + (f" · next {a['next_run']}" if a.get("next_run") and a["next_run"] != "n/a" else ""))
    print("               origins: " + (", ".join(a["origins"]) or "none"))
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
    print(__doc__.rstrip()); return 2
