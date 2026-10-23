"""maluctl tools: the Tools Installer's scripts from a terminal.

  maluctl tools list [--json]     the tools under /usr/share/maluos-tools with their state
  maluctl tools check ID          is it installed (prints the version; exit 1 when not)
  maluctl tools install ID        run the tool's install script: system scope as root (through
                                  pkexec when you are not root), user scope as you; logged
  maluctl tools open ID           start the tool
  maluctl tools log ID            the last install log

A tool is a directory with tool.json (id, name, description, scope system|user,
vendor_url, notice, check, open) and install.sh, idempotent. System-scope logs are
in /var/log/maluos-tools/, user-scope logs in ~/.local/state/maluos-tools/.
"""
import json, os, pwd, subprocess, sys, time

TOOLS_DIR = os.environ.get("MALUOS_TOOLS_DIR", "/usr/share/maluos-tools")
SYSTEM_LOGS = "/var/log/maluos-tools"


def user_logs():
    home = os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state"), "maluos-tools")


def tools():
    out = {}
    try:
        names = sorted(os.listdir(TOOLS_DIR))
    except OSError:
        return out
    for n in names:
        p = os.path.join(TOOLS_DIR, n, "tool.json")
        try:
            with open(p) as f:
                t = json.load(f)
        except (OSError, ValueError):
            continue
        t.setdefault("id", n); t["dir"] = os.path.join(TOOLS_DIR, n)
        t["scope"] = t.get("scope") if t.get("scope") in ("system", "user") else "system"
        out[t["id"]] = t
    return out


def check(t):
    """(installed, version-or-reason)"""
    cmd = t.get("check")
    if not cmd:
        return False, "no check command"
    env = dict(os.environ, PATH=os.environ.get("PATH", "") + ":" + os.path.expanduser("~/.local/bin") + ":/usr/local/bin")
    try:
        r = subprocess.run(["bash", "-o", "pipefail", "-c", cmd], capture_output=True, text=True, timeout=20, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"{e.__class__.__name__}"
    line = (r.stdout.strip() or r.stderr.strip()).splitlines()
    return (r.returncode == 0 and bool(line)), (line[0][:80] if line else "not installed")


def log_path(t):
    return os.path.join(SYSTEM_LOGS if t["scope"] == "system" else user_logs(), t["id"] + ".log")


def state(t):
    ok, ver = check(t)
    lp = log_path(t)
    try:
        log_at = int(os.stat(lp).st_mtime)
    except OSError:
        log_at = None
    return {**{k: v for k, v in t.items() if k != "dir"}, "installed": ok, "version": ver if ok else None, "log": lp, "log_at": log_at}


def install(t):
    if t["scope"] == "system" and os.geteuid() != 0:
        # Root through polkit (com.maluos.admin): pkexec asks the shell's agent, or on a plain terminal, itself.
        print(f"maluctl tools: {t['name']} installs system-wide; asking for an administrator's password (pkexec)", flush=True)
        os.execvp("pkexec", ["pkexec", "maluctl", "tools", "install", t["id"]])
    lp = log_path(t)
    os.makedirs(os.path.dirname(lp), exist_ok=True)
    if t["scope"] == "system":
        os.chmod(os.path.dirname(lp), 0o755)
    script = os.path.join(t["dir"], "install.sh")
    print(f"== {t['name']} ({t['scope']} scope): {script}", flush=True)
    print(f"   {t.get('notice', '')}  {t.get('vendor_url', '')}", flush=True)
    print(f"   log: {lp}", flush=True)
    with open(lp, "a") as log:
        log.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} install {t['id']} ({t['scope']})\n"); log.flush()
        p = subprocess.Popen(["bash", script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=t["dir"])
        for line in p.stdout:
            sys.stdout.write(line); sys.stdout.flush(); log.write(line)
        rc = p.wait()
        log.write(f"=== exit {rc}\n")
    if t["scope"] == "system":
        os.chmod(lp, 0o644)
    if rc != 0:
        print(f"maluctl tools: {t['name']} install failed (exit {rc}); is the network up? see {lp}", file=sys.stderr)
        return rc
    ok, ver = check(t)
    print(f"== {t['name']}: {'installed, ' + ver if ok else 'install script finished but the check did not find it: ' + ver}")
    return 0 if ok else 1


def main(args):
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.rstrip()); return 0 if args else 2
    cmd, rest = args[0], args[1:]
    ts = tools()
    if cmd == "list":
        rows = [state(t) for t in ts.values()]
        if "--json" in rest:
            print(json.dumps(rows, indent=None if "--compact" in rest else 2)); return 0
        if not rows:
            print(f"no tools under {TOOLS_DIR}"); return 0
        for r in rows:
            print(f"{r['id']:<14} {r['name']:<20} {r['scope']:<7} {'installed: ' + r['version'] if r['installed'] else 'not installed'}")
        return 0
    if not rest or rest[0] not in ts:
        print(f"maluctl tools {cmd}: which tool? one of {', '.join(ts) or 'none'}", file=sys.stderr); return 2
    t = ts[rest[0]]
    if cmd == "check":
        ok, ver = check(t); print(f"{t['id']}: {'installed, ' + ver if ok else 'not installed'}"); return 0 if ok else 1
    if cmd == "install":
        return install(t)
    if cmd == "open":
        if not t.get("open"):
            print(f"{t['id']} has no open command", file=sys.stderr); return 1
        env = dict(os.environ, PATH=os.environ.get("PATH", "") + ":" + os.path.expanduser("~/.local/bin") + ":/usr/local/bin")
        subprocess.Popen(["sh", "-c", t["open"]], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return 0
    if cmd == "log":
        lp = log_path(t)
        try:
            sys.stdout.write(open(lp).read())
        except OSError:
            print(f"no log yet at {lp}")
        return 0
    print(__doc__.rstrip()); return 2
