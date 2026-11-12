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


def install_command(key, admin_email, domain, scheme, ref=None, hire=True, source=GIT_SOURCE, proxy_address=None):
    """The installer's command line for one application (run as root from /var/www). `proxy_address` (https behind a
    proxy) tells the installer where the application's name goes in /etc/hosts when it does not resolve: the proxy,
    never loopback (an installer before 2026-11-05 ignores the option; office_hosts() fixes the line afterwards)."""
    cmd = ["php", "bin/app_install.php", "apply", repo_url(key, source), "--by", admin_email, "--domain", domain,
           "--scheme", scheme, "--grant-standing-departments"]
    if hire:
        cmd.append("--hire-agents")
    if ref:
        cmd += ["--ref", ref]
    if proxy_address:
        cmd += ["--proxy-address", proxy_address]
    return cmd


# -- the office's names in /etc/hosts (docs/phase13-estate-behind-a-proxy.md, part 2)
HOSTS_BEGIN, HOSTS_END = "# maluos business-os names begin", "# maluos business-os names end"
LOOPBACK = ("127.0.0.1", "::1")


def office_hosts(text, names, address):
    """The /etc/hosts text with the office's names pointed where the office can reach them. Under https behind a proxy
    the names go to `address` (the proxy's address as the office sees it) in a marked block, one line per name, and leave
    every loopback line (first boot under http, the kernel's installer, a hand): nothing on the office serves https on
    loopback. `address` None writes no block and still takes the names off loopback (https without a proxy_address: the
    office is left to DNS). With no names the call only removes a stale block (the http path keeps its loopback lines).
    Returns (new_text, changed); the rest of the file is kept as it is."""
    lines = text.split("\n")
    if HOSTS_BEGIN in lines and HOSTS_END in lines and lines.index(HOSTS_BEGIN) < lines.index(HOSTS_END):
        i, j = lines.index(HOSTS_BEGIN), lines.index(HOSTS_END)
        lines = lines[:i] + lines[j + 1:]
    wanted = [n for n in names if n]
    if wanted:
        kept = []
        for l in lines:
            fields = l.split("#", 1)[0].split()
            if fields and fields[0] in LOOPBACK and any(n in fields[1:] for n in wanted):
                rest = [x for x in fields[1:] if x not in wanted]
                if not rest:
                    continue
                l = fields[0] + "\t" + " ".join(rest)
            kept.append(l)
        lines = kept
    while lines and lines[-1] == "":
        lines.pop()
    if address and wanted:
        lines += [HOSTS_BEGIN] + [f"{address}\t{n}" for n in wanted] + [HOSTS_END]
    new = "\n".join(lines) + "\n"
    return new, new != text


def resolve_address(value, resolver=None):
    """`proxy_address` as given (an IPv4 or IPv6 literal is taken as it is; a host name is resolved once) -> the address
    string, or None with a reason. The resolver is socket.getaddrinfo unless a test passes one."""
    import ipaddress, socket
    if value is None or str(value).strip() == "":
        return None, "absent"
    v = str(value).strip()
    try:
        return str(ipaddress.ip_address(v)), None
    except ValueError:
        pass
    if not re.match(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*$", v):
        return None, f"{v!r} is neither an address nor a host name"
    try:
        infos = (resolver or socket.getaddrinfo)(v, None)
        for fam_first in (socket.AF_INET, socket.AF_INET6):
            for info in infos:
                if info[0] == fam_first:
                    return info[4][0], None
        return None, f"{v} resolves to nothing usable"
    except OSError as e:
        return None, f"{v} does not resolve ({e})"


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
                 wait=wait_for_network, timeout=APP_TIMEOUT, source=GIT_SOURCE, proxy_address=None):
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
        cmd = install_command(key, admin_email, domain, scheme, ref=cfg["ref"].get(key), hire=hire, source=source, proxy_address=proxy_address)
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


def remote_install_command(key, kernel, token_file, ref=None, hire=True, source=GIT_SOURCE, address=None, database=None, proxy_address=None):
    """The installer's command line on an APPLICATION SERVER (docs/phase14-application-servers.md): its host half
    here, the rest asked of the kernel server at its applications' door. `database`: the database server
    ({host, port, admin, passfile, sslmode, ca}) or None for this server's own cluster."""
    cmd = ["php", "bin/app_install.php", "apply", repo_url(key, source), "--kernel", kernel.rstrip("/"),
           "--node-token-file", token_file, "--grant-standing-departments"]
    if hire:
        cmd.append("--hire-agents")
    if ref:
        cmd += ["--ref", ref]
    if address:
        cmd += ["--address", address]
    if proxy_address:
        cmd += ["--proxy-address", proxy_address]
    if database:
        cmd += ["--db-host", str(database["host"]), "--db-port", str(database.get("port") or 5432),
                "--db-admin", str(database["admin"]), "--db-passfile", str(database["passfile"])]
        if database.get("sslmode"):
            cmd += ["--db-sslmode", str(database["sslmode"])]
        if database.get("ca"):
            cmd += ["--db-ca", str(database["ca"])]
    return cmd


def node_token_file(path="/run/maluos/app-install-node.token"):
    """This server's estate node token (the vault holds it; root may read it) in a root-only file for the installer.
    The caller removes it."""
    import sys
    sys.path.insert(0, "/usr/lib/maluos")
    from maluos_estate import client as C
    conf = C.read_conf()
    if not conf:
        raise RuntimeError("this server is not a node of an estate (sudo maluctl estate join URL --code CODE)")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
        fh.write(C.token(conf) + "\n")
    return path


def prepare_apache(run=subprocess.run):
    """An application server has no kernel component to do it: the modules every application's vhost and the
    kernel's relay use, and Apache running."""
    run(["a2enmod", "-q", "rewrite", "proxy", "proxy_http", "headers"], check=False, capture_output=True)
    run(["systemctl", "enable", "--now", "--quiet", "apache2"], check=False, capture_output=True)
    run(["systemctl", "reload-or-restart", "apache2"], check=False, capture_output=True)


def install_remote_apps(blk, state_dir, www=WWW, run=subprocess.run, log=print, wait=wait_for_network,
                        timeout=APP_TIMEOUT, source=GIT_SOURCE, database=None, token_file=None):
    """role: application-server. `blk` is firstboot.yaml's application_server block: kernel (the kernel server's
    applications' door, http://HOST:8081), apps (the catalog keys, in order), and optionally ref, propose_agents,
    address (this server's address as the kernel reaches it) and proxy_address. Markers and logs as install_apps
    keeps them. Returns {installed, failed, errors}."""
    cfg = apps_config({"install": blk.get("apps") or [], "ref": blk.get("ref"), "propose_agents": blk.get("propose_agents")})
    result = {"installed": [], "failed": [], "errors": {}}
    keys = cfg["install"]
    if not keys:
        return result
    kernel = str(blk.get("kernel") or "")
    if not re.match(r"^https?://[A-Za-z0-9.\[\]:-]+$", kernel):
        raise ValueError(f"application_server.kernel: {kernel!r} is not the kernel server's door (http://HOST:8081)")
    os.makedirs(state_dir, exist_ok=True)
    pending = [k for k in keys if not os.path.exists(os.path.join(state_dir, k))]
    result["installed"] = [k for k in keys if k not in pending]
    if not pending:
        return result
    if wait is not None:
        host = repo_url(pending[0], source).split("//", 1)[-1].split("/", 1)[0]
        if not wait(host):
            log(f"warning: {host} is not reachable; the applications' clones will likely fail")
    prepare_apache(run)
    made = token_file is None
    token_file = token_file or node_token_file()
    env = dict(os.environ, HOME="/root", COMPOSER_ALLOW_SUPERUSER="1", COMPOSER_NO_INTERACTION="1",
               GIT_TERMINAL_PROMPT="0", PATH=os.environ.get("PATH", "") + ":/usr/local/bin:/usr/bin:/bin")
    try:
        for key in pending:
            hire = key not in cfg["propose_agents"]
            cmd = remote_install_command(key, kernel, token_file, ref=cfg["ref"].get(key), hire=hire, source=source,
                                         address=blk.get("address"), database=database, proxy_address=blk.get("proxy_address"))
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
                json.dump({"installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": cmd[3], "kernel": kernel,
                           "ref": cfg["ref"].get(key), "agents": "hired" if hire else "proposed"}, fh); fh.write("\n")
            result["installed"].append(key)
            log(f"application {key}: installed here and registered with the kernel at {kernel}")
    finally:
        if made:
            try: os.remove(token_file)
            except OSError: pass
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
