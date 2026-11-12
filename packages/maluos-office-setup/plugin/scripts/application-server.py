#!/usr/bin/env python3
"""application-server.py: make this MaluOS server an application server (MaluOS Phase 14 slice 3).

An application server runs the platform services (the vault, the gateway, the memory face, so agents can run
on it) and one or more applications. It runs no Business OS kernel: the kernel is on another server, which
this one reaches at the kernel's "applications' door" (http://KERNEL:8081 on the business's network).

  application-server.py --show
  application-server.py --check --kernel http://kernel.example.lan:8081
  application-server.py --apply --kernel http://kernel.example.lan:8081 --apps hr,projects \\
                        --estate-url https://app.example.com --code-file /root/join-code.txt [--address 192.168.100.21]

--check asks the door for the kernel's health and says, when it cannot, which side to fix: this server's
address is not in the kernel's list (components.maludb-os-core.application_servers there), nothing listens
(the list is empty, so the door was never opened), or the name does not resolve.

--apply runs the same check, then writes into /etc/maluos/firstboot.yaml: role: application-server, the
application_server block (the door, the applications, this server's address) and the enroll block (the
estate's public URL and the one-time join code, read from --code-file so it is never on a command line).
Nothing is provisioned: `maluctl provision --force` (provision.sh) then joins the estate and installs the
applications. The join code must have been minted on the kernel FOR THESE APPLICATIONS:
    sudo -u www-data php /var/www/bin/mint_desk_code.php --email <administrator> --kind server --name <this server> --apps hr,projects
It is valid for fifteen minutes and used once.

Where this server keeps its data is a separate step (database-server.py): its own PostgreSQL, or the
estate's database server, where it gets a database and roles of its own.
"""
import argparse, datetime, json, os, re, shutil, subprocess, sys, urllib.error, urllib.request

PATH = "/etc/maluos/firstboot.yaml"
DONE = "/var/lib/maluos/firstboot/done"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def say(kind, msg): print(f"{kind:<5} {msg}")
def die(msg, code=1): print(f"ERROR {msg}", file=sys.stderr); sys.exit(code)


def need_root(argv):
    if os.geteuid() == 0:
        return
    if subprocess.call(["sudo", "-n", "true"], stderr=subprocess.DEVNULL) == 0:
        os.execvp("sudo", ["sudo", "-n", os.path.realpath(__file__), *argv])
    die(f"needs root: sudo {os.path.realpath(__file__)} {' '.join(argv)}", 97)


def load():
    import yaml
    return (yaml.safe_load(open(PATH).read()) or {}) if os.path.exists(PATH) else {}


def state():
    try:
        return json.load(open(DONE))
    except Exception:
        return {}


def show():
    cfg, st = load(), state()
    role = str(cfg.get("role") or "").strip()
    blk = cfg.get("application_server") if isinstance(cfg.get("application_server"), dict) else {}
    if role != "application-server":
        say("NOTE", f"configured: not an application server (role: {role or 'none: a server with its own kernel, or none yet'})")
    else:
        say("NOTE", f"configured: an application server of the kernel at {blk.get('kernel') or '(no door set)'}; applications: {', '.join(blk.get('apps') or []) or 'none'}")
    ap = st.get("application_server")
    if isinstance(ap, dict):
        say("PASS" if not ap.get("failed") and not ap.get("error") else "FAIL",
            f"provisioned: installed {', '.join(ap.get('installed') or []) or 'nothing'}"
            + (f"; failed {', '.join(ap.get('failed') or [])}" if ap.get("failed") else "") + (f"; {ap.get('error')}" if ap.get("error") else ""))
        if st.get("platform_suffix"):
            say("NOTE", f"its names on the database server carry the suffix {st['platform_suffix']} (database {st.get('database')})")
    elif role == "application-server":
        say("NOTE", "provisioned: not yet (provision.sh)")
    if os.path.exists("/etc/maluos/estate.yaml"):
        say("PASS", "this server is a node of the estate")
    elif role == "application-server":
        say("NOTE", "this server has not joined the estate yet")
    return 0


def check_door(kernel):
    if not re.fullmatch(r"https?://[A-Za-z0-9.\[\]:-]+", kernel):
        say("FAIL", f"--kernel {kernel!r} is not the kernel's door, like http://kernel.example.lan:8081"); return 1
    url = kernel.rstrip("/") + "/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            body = r.read(400).decode("utf-8", "replace")
            if r.status == 200 and '"ok"' in body:
                say("PASS", f"the kernel answers at its applications' door ({kernel})"); return 0
            say("FAIL", f"{url} answered HTTP {r.status}, not the kernel's health"); return 1
    except urllib.error.HTTPError as e:
        say("FAIL", f"{url} answered HTTP {e.code}")
        if e.code == 403:
            say("NOTE", "the door does not admit this server's address. On the kernel server add it to "
                        "components.maludb-os-core.application_servers (configure-kernel.py --application-servers …) and provision again")
        return 1
    except Exception as e:
        msg = str(getattr(e, "reason", e))
        say("FAIL", f"cannot reach {url}: {msg[:200]}")
        low = msg.lower()
        if "refused" in low:
            say("NOTE", "nothing listens there: the kernel opens its door only when components.maludb-os-core.application_servers "
                        "lists at least one server; set it on the kernel server and provision again")
        elif "name or service" in low or "resolution" in low or "nodename" in low:
            say("NOTE", "this server cannot resolve that name: use the kernel server's name on your LAN, or its address")
        elif "timed out" in low or "no route" in low:
            say("NOTE", "no answer: a firewall between the two servers, or a wrong address; the door is port 8081 on the kernel server's LAN address")
        return 1


def top_level_block(lines, key):
    for i, l in enumerate(lines):
        if re.match(rf"^{re.escape(key)}\s*:", l):
            j = i + 1
            while j < len(lines) and (lines[j].strip() == "" or lines[j][0] in " \t"):
                j += 1
            while j > i + 1 and lines[j - 1].strip() == "":
                j -= 1
            return i, j
    return None


def put(lines, key, block):
    ext = top_level_block(lines, key)
    if ext:
        lines[ext[0]:ext[1]] = block
    else:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines += block
    return lines


def apply(a):
    if not os.path.exists(PATH):
        die(f"{PATH} is missing: this is not a MaluOS server")
    cfg, st = load(), state()
    if str(cfg.get("role") or "").strip() == "database-server":
        die("this host is a database server (role: database-server); it runs no application")
    k = (st.get("components") or {}).get("maludb-os-core") or {}
    if k.get("domain") and not k.get("error"):
        die(f"this server runs the Business OS kernel itself (provisioned for {k.get('domain')}): applications install beside it "
            "(components.maludb-os-core.apps), not through another kernel's door")
    apps = [x.strip().lower() for x in (a.apps or "").split(",") if x.strip()]
    bad = [x for x in apps if not KEY_RE.match(x)]
    if bad:
        die("not application keys: " + ", ".join(bad))
    if a.address and not re.fullmatch(r"[0-9A-Fa-f:.]+", a.address):
        die(f"--address {a.address!r} is not an address")
    joined = os.path.exists("/etc/maluos/estate.yaml")
    code = ""
    if not joined:
        if not a.estate_url or not re.fullmatch(r"https?://[A-Za-z0-9.\[\]:-]+/?", a.estate_url):
            die("--estate-url is the kernel's public URL, like https://app.example.com (this server joins the estate there)")
        if not a.code_file or not os.path.isfile(a.code_file):
            die("--code-file: a file holding the one-time join code minted on the kernel for these applications")
        code = open(a.code_file).read().strip()
        if not re.fullmatch(r"[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}", code):
            die(f"{a.code_file} does not hold a join code (like ABCD-EFGH)")
    if check_door(a.kernel) != 0:
        die("the kernel's door did not pass the check: nothing was written")
    lines = open(PATH).read().splitlines()
    lines = put(lines, "role", ["role: application-server"])
    blk = ["# this server runs applications for the kernel at the door below (written by maluos-office-setup)",
           "application_server:", f"  kernel: {a.kernel.rstrip('/')}", f"  apps: [{', '.join(apps)}]"]
    if a.address:
        blk.append(f"  address: {a.address}")
    # the comment line belongs with the block: drop an earlier copy of it
    lines = [l for l in lines if l != blk[0]]
    ext = top_level_block(lines, "application_server")
    if ext:
        lines[ext[0]:ext[1]] = blk[1:]
        lines.insert(ext[0], blk[0])
    else:
        lines = put(lines, "application_server", blk)
    if not joined:
        import socket
        lines = put(lines, "enroll", ["enroll:", "  kind: estate", f"  url: {a.estate_url.rstrip('/')}", f"  code: {code}",
                                     f"  name: {socket.gethostname().split('.')[0]}"])
    new = "\n".join(lines) + "\n"
    try:
        import yaml
        got = yaml.safe_load(new) or {}
        assert got.get("role") == "application-server" and (got.get("application_server") or {}).get("kernel") == a.kernel.rstrip("/")
        assert (got.get("application_server") or {}).get("apps") == apps
    except Exception as e:
        die(f"the edited file would not parse as intended ({e}); nothing was written")
    backup = f"{PATH}.bak-{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    shutil.copy2(PATH, backup)
    os.chmod(backup, 0o600)
    with open(PATH, "w") as f:
        f.write(new)
    if not joined:
        os.chmod(PATH, 0o600)          # it holds the join code until first boot has used it
    say("PASS", f"{PATH}: role application-server, the kernel at {a.kernel.rstrip('/')}, applications {', '.join(apps) or 'none'} (backup {backup})")
    say("NOTE", "the join code is in the file until provisioning uses it (fifteen minutes from its minting); it is blanked afterwards" if not joined
        else "this server is already a node of the estate: its allowance is what its join code named")
    say("NOTE", "nothing is provisioned yet: provision.sh (maluctl provision --force) joins the estate and installs the applications")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--show", action="store_true"); g.add_argument("--check", action="store_true"); g.add_argument("--apply", action="store_true")
    ap.add_argument("--kernel"); ap.add_argument("--apps", default=""); ap.add_argument("--estate-url"); ap.add_argument("--code-file")
    ap.add_argument("--address")
    a = ap.parse_args()
    need_root(sys.argv[1:])
    if a.show:
        return show()
    if not a.kernel:
        die("--kernel is required with --check and --apply")
    return check_door(a.kernel) if a.check else apply(a)


if __name__ == "__main__":
    sys.exit(main())
