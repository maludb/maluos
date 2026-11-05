"""The Business OS's applications on a MaluOS office (the maluos-apps proposal, phase 1).

The kernel's own installer, /var/www/bin/app_install.php, does the whole job for one application
from its repository and does it idempotently; what MaluOS adds is calling it at first boot for the
applications firstboot.yaml names (components.maludb-os-core.apps), with --by, --domain and --scheme
taken from the office's own configuration, a marker per application so a re-run does not repeat an
install, and the list of DNS names the office needs (`maluctl app names`). Pure functions where
they can be, so tests/apps-test.py proves them without a kernel: the installer is a runner passed in.

Shared by the first-boot component (60-maludb-os-core.py) and the maluctl plugin (maluctl.d/app.py).
"""
import glob, json, os, re, socket, subprocess, time

WWW = "/var/www"
APPS_DIR = os.environ.get("MALUOS_APPS_DIR", "/srv/apps")
DONE = os.environ.get("MALUOS_FIRSTBOOT_DONE", "/var/lib/maluos/firstboot/done")
KERNEL_ENV = os.environ.get("MALUOS_KERNEL_ENV", f"{WWW}/config/.env")
GIT_SOURCE = "https://github.com/maludb"
DEFAULT_APPS = ["hr", "projects", "helpdesk", "spaces"]
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")          # what app_install.php admits as a catalog_key
APP_TIMEOUT = 3600                                      # one application's clone, build and registration


def repo_url(key, source=GIT_SOURCE):
    """Every application of the OS lives under github.com/maludb as maludb-os-<key>."""
    return f"{source.rstrip('/')}/maludb-os-{key}.git"


def apps_config(apps):
    """The `apps` block of components.maludb-os-core, normalised: install (the keys, in order; the four
    defaults when the key is absent; [] skips the step), ref (key -> git ref) and propose_agents (keys
    whose agents are proposed rather than hired). A key the installer would refuse is refused here."""
    apps = apps or {}
    install = apps.get("install")
    if install is None:
        install = list(DEFAULT_APPS)
    elif isinstance(install, str):
        install = [install]
    install = [str(k).strip().lower() for k in install if str(k).strip()]
    for k in install:
        if not KEY_RE.match(k):
            raise ValueError(f"apps.install: {k!r} is not an application key (lowercase letters, digits and underscores)")
    seen, ordered = set(), []
    for k in install:
        if k not in seen:
            seen.add(k); ordered.append(k)
    ref = {str(k): str(v) for k, v in (apps.get("ref") or {}).items() if v}
    propose = apps.get("propose_agents") or []
    if isinstance(propose, str):
        propose = [propose]
    return {"install": ordered, "ref": ref, "propose_agents": [str(k).strip().lower() for k in propose]}


def install_command(key, admin_email, domain, scheme, ref=None, hire=True, source=GIT_SOURCE):
    """The installer's command line for one application (run as root from /var/www)."""
    cmd = ["php", "bin/app_install.php", "apply", repo_url(key, source), "--by", admin_email, "--domain", domain,
           "--scheme", scheme, "--grant-standing-departments"]
    if hire:
        cmd.append("--hire-agents")
    if ref:
        cmd += ["--ref", ref]
    return cmd


def wait_for_network(host="github.com", port=443, timeout=120, sleep=time.sleep):
    """The clone needs DNS and HTTPS; on some paths first boot runs before the network is up (the unit
    wants network-online.target, which a NoCloud or static-address path may reach early). Resolve the
    host and open a TCP connection to it; True when it answered within the timeout."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection((host, port), timeout=5):
                return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            sleep(3)


def install_apps(cfg, admin_email, domain, scheme, state_dir, www=WWW, run=subprocess.run, log=print,
                 wait=wait_for_network, timeout=APP_TIMEOUT, source=GIT_SOURCE):
    """Install the applications cfg (apps_config's shape) names, in order, with the kernel's installer: a
    marker file per key under state_dir records a completed install, so a re-run (maluctl provision
    --force) reconciles from the markers and only installs what is missing; a failing application is
    logged, its output kept beside the marker as <key>.log, and the next one continues. Returns
    {installed, failed, errors} for the component's summary. Nothing runs when install is empty."""
    result = {"installed": [], "failed": [], "errors": {}}
    keys = cfg["install"]
    if not keys:
        return result
    os.makedirs(state_dir, exist_ok=True)
    pending = [k for k in keys if not os.path.exists(os.path.join(state_dir, k))]
    result["installed"] = [k for k in keys if k not in pending]
    if pending and wait is not None:
        host = repo_url(pending[0], source).split("//", 1)[-1].split("/", 1)[0]
        if not wait(host):
            log(f"warning: {host} is not reachable; the applications' clones will likely fail")
    env = dict(os.environ, HOME="/root", COMPOSER_ALLOW_SUPERUSER="1", COMPOSER_NO_INTERACTION="1",
               GIT_TERMINAL_PROMPT="0", PATH=os.environ.get("PATH", "") + ":/usr/local/bin:/usr/bin:/bin")
    for key in keys:
        if key not in pending:
            continue
        hire = key not in cfg["propose_agents"]
        cmd = install_command(key, admin_email, domain, scheme, ref=cfg["ref"].get(key), hire=hire, source=source)
        logf = os.path.join(state_dir, key + ".log")
        log(f"application {key}: {' '.join(cmd)}")
        try:
            with open(logf, "w") as fh:
                r = run(cmd, cwd=www, stdout=fh, stderr=subprocess.STDOUT, env=env, timeout=timeout)
            if r.returncode != 0:
                raise RuntimeError(f"exit {r.returncode}: " + tail(logf))
        except subprocess.TimeoutExpired:
            result["failed"].append(key); result["errors"][key] = f"timed out after {timeout}s (see {logf})"
            log(f"application {key}: FAILED: {result['errors'][key]}"); continue
        except Exception as e:
            result["failed"].append(key); result["errors"][key] = str(e)[:400]
            log(f"application {key}: FAILED: {result['errors'][key]} (see {logf})"); continue
        with open(os.path.join(state_dir, key), "w") as fh:
            json.dump({"installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": cmd[3],
                       "ref": cfg["ref"].get(key), "agents": "hired" if hire else "proposed"}, fh); fh.write("\n")
        result["installed"].append(key)
        log(f"application {key}: installed")
    result["installed"] = [k for k in keys if k in result["installed"]]
    return result


def tail(path, n=600):
    try:
        s = open(path, errors="replace").read()
    except OSError:
        return ""
    return s[-n:].strip()


def manifests(apps_dir=APPS_DIR):
    """[(key, manifest)] for every /srv/apps/<key>/maludb-os.json, by directory name; a manifest that does
    not parse counts as an empty one (the directory name is still a name the office owes)."""
    out = []
    for path in sorted(glob.glob(os.path.join(apps_dir, "*", "maludb-os.json"))):
        key = os.path.basename(os.path.dirname(path))
        try:
            m = json.load(open(path))
            if not isinstance(m, dict):
                m = {}
        except (OSError, ValueError):
            m = {}
        out.append((key, m))
    return out


def office_names(domain, apps_dir=APPS_DIR):
    """The DNS names an office needs, in the order the proxy's operator reads them: the bare domain, www,
    app, os, and <vhost.label>.<domain> for every installed application (the label is the manifest's
    vhost.label, else its catalog_key, else the directory's name)."""
    names = [domain, f"www.{domain}", f"app.{domain}", f"os.{domain}"]
    for key, m in manifests(apps_dir):
        label = (m.get("vhost") or {}).get("label") or m.get("catalog_key") or key
        names.append(f"{label}.{domain}")
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n); out.append(n)
    return out


def office_domain(done=DONE, kernel_env=KERNEL_ENV):
    """The office's domain: from the first-boot state (components.maludb-os-core.domain), else from the
    kernel's config (APP_HOST = app.<domain>), else None."""
    try:
        st = json.load(open(done))
        d = ((st.get("components") or {}).get("maludb-os-core") or {}).get("domain")
        if d:
            return d
    except (OSError, ValueError, AttributeError):
        pass
    try:
        for line in open(kernel_env):
            line = line.strip()
            if line.startswith("APP_HOST="):
                host = line.split("=", 1)[1].strip().strip('"').strip("'")
                return host[4:] if host.startswith("app.") else host or None
    except OSError:
        pass
    return None
