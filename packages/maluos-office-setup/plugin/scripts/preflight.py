#!/usr/bin/env python3
"""preflight.py: what state is this office in?  (also the completion report)

  preflight.py            JSON: first boot, the kernel's configuration and state, names, services, health,
                          providers (present/absent only, never a value), virtualisation, a phase assessment
  preflight.py --human    the same, readable
  preflight.py --report   the completion summary for the operator (markdown), topology-aware; exit 1 when
                          anything that the chosen topology needs is not in place

Reads root-only files when run as root (the sudoers rule covers it); degrades to "unknown" otherwise.
Never prints a secret: for every key or password it reports only whether one is set.
"""
import json, os, re, socket, subprocess, sys, urllib.request

FIRSTBOOT_YAML = "/etc/maluos/firstboot.yaml"
FIRSTBOOT_DONE = "/var/lib/maluos/firstboot/done"
KERNEL_COMPONENT = "/usr/lib/maluos/components/60-maludb-os-core.py"
RUNNER_ENV = "/etc/business-os/runner.env"
KERNEL_ENV = "/var/www/config/.env"
ADMIN_PW = "/var/lib/maluos/secrets/business-os/admin-password"
UNITS = ["apache2", "maludb-api", "maludb-os-web", "maludb-os-records-mcp", "maludb-os-activity-mcp",
         "maludb-os-actions-mcp", "maludb-os-memory-mcp", "maludb-os-agent-runner", "maludb-os-activity-ingest.timer"]
SECRET_KEYS = ("admin_password", "anthropic_api_key", "openrouter_api_key", "malumail_api_key")


def run(*cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


def read(path):
    try:
        return open(path).read()
    except OSError:
        return None


def http(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def dpkg_versions(*pkgs):
    out = {}
    for p in pkgs:
        rc, o, _ = run("dpkg-query", "-W", "-f=${Version} ${db:Status-Status}", p)
        out[p] = o.split()[0] if rc == 0 and o.endswith("installed") else None
    return out


def kernel_config():
    text = read(FIRSTBOOT_YAML)
    if text is None:
        return None, "unreadable"
    try:
        import yaml
        cfg = yaml.safe_load(text) or {}
    except Exception as e:
        return None, f"yaml error: {e}"
    block = ((cfg.get("components") or {}).get("maludb-os-core")) or {}
    public = {k: block.get(k) for k in ("enabled", "domain", "scheme", "admin_email", "admin_name", "proxy_address", "apps")}
    public["secrets_set"] = {k: bool(block.get(k)) for k in SECRET_KEYS}
    return public, None


def firstboot_state():
    st = {}
    _, sub, _ = run("systemctl", "show", "-p", "SubState", "--value", "maluos-firstboot")
    _, act, _ = run("systemctl", "show", "-p", "ActiveState", "--value", "maluos-firstboot")
    _, res, _ = run("systemctl", "show", "-p", "Result", "--value", "maluos-firstboot")
    st["unit"] = {"active_state": act or None, "sub_state": sub or None, "result": res or None}
    st["running"] = sub == "running"
    st["done_file"] = os.path.exists(FIRSTBOOT_DONE)
    done = read(FIRSTBOOT_DONE)
    st["summary"] = None
    if done:
        try:
            d = json.loads(done)
            comps = d.get("components") or {}
            failed = {k: v.get("error") for k, v in comps.items() if isinstance(v, dict) and "error" in v}
            core = comps.get("maludb-os-core") if isinstance(comps.get("maludb-os-core"), dict) else None
            st["summary"] = {"provisioned_at": d.get("provisioned_at"), "components": sorted(comps), "failed": failed,
                             "kernel": None if not core else {
                                 "domain": core.get("domain"), "scheme": core.get("scheme"), "urls": core.get("urls"),
                                 "error": core.get("error"), "admin_email": core.get("admin_email"),
                                 "apps": core.get("apps"), "names": core.get("names")}}
        except ValueError:
            st["summary"] = {"error": "done file is not JSON"}
    return st


def hosts_for(domain):
    text = read("/etc/hosts") or ""
    lines = [l for l in text.splitlines() if domain and domain in l]
    loopback = [l for l in lines if re.match(r"^\s*127\.0\.0\.1\b", l)]
    marked = "# BEGIN maluos-office-setup names" in text or "maluos-office-setup" in text
    component_marked = bool(re.search(r"maludb-os-core|maluos-firstboot", text))
    resolved = None
    if domain:
        try:
            resolved = sorted({a[4][0] for a in socket.getaddrinfo(f"app.{domain}", 80, socket.AF_INET)})
        except socket.gaierror:
            resolved = []
    return {"lines": lines, "loopback_lines": loopback, "app_resolves_to": resolved,
            "plugin_block": marked, "component_block": component_marked}


def services():
    out = {}
    for u in UNITS:
        _, o, _ = run("systemctl", "is-active", u)
        out[u] = o or "unknown"
    return out


def health(domain):
    code, body = http("http://127.0.0.1:8080/api/v1/health")
    rc, hostcode, _ = run("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "10",
                          "-H", f"Host: app.{domain}", "http://127.0.0.1/login") if domain else (1, "", "")
    rcode, rbody = http("http://127.0.0.1:8815/health")
    harnesses = None
    if rcode == 200:
        try:
            harnesses = json.loads(rbody).get("harnesses")
        except ValueError:
            harnesses = "unparseable"
    return {"api_health_http": code, "login_via_host_header_http": hostcode or None,
            "runner_health_http": rcode, "runner_harnesses": harnesses}


def env_has(path, key):
    text = read(path)
    if text is None:
        return None
    for line in text.splitlines():
        if line.startswith(key + "="):
            return len(line.split("=", 1)[1].strip()) > 0
    return False


def providers():
    return {"anthropic": env_has(RUNNER_ENV, "ANTHROPIC_API_KEY"), "openrouter": env_has(RUNNER_ENV, "OPENROUTER_API_KEY"),
            "openai": env_has(RUNNER_ENV, "OPENAI_API_KEY"), "malumail": env_has(KERNEL_ENV, "MALUMAIL_API_KEY"),
            "mail_from_set": env_has(KERNEL_ENV, "MAIL_FROM"), "readable": read(RUNNER_ENV) is not None}


def virt():
    _, v, _ = run("systemd-detect-virt")
    _, qga, _ = run("systemctl", "is-active", "qemu-guest-agent")
    return {"type": v or "none", "qemu_guest_agent": qga or "unknown"}


def network():
    _, a, _ = run("ip", "-br", "-4", "address")
    addrs = [l.split() for l in a.splitlines() if l and not l.startswith("lo ")]
    _, r, _ = run("ip", "route", "show", "default")
    return {"addresses": [{"iface": x[0], "address": x[2]} for x in addrs if len(x) >= 3], "default_route": r or None}


def apps_state():
    out = []
    for d in sorted(os.listdir("/srv/apps")) if os.path.isdir("/srv/apps") else []:
        m = read(f"/srv/apps/{d}/maludb-os.json")
        label = d
        if m:
            try:
                j = json.loads(m); label = (j.get("vhost") or {}).get("label") or j.get("catalog_key") or d
            except ValueError:
                pass
        out.append({"key": d, "label": label})
    return out


def assess(cfg, fb, hosts, hc, svc, prov):
    a = {}
    k = (fb.get("summary") or {}).get("kernel") if fb.get("summary") else None
    a["on_office"] = os.path.exists(FIRSTBOOT_YAML) and os.path.isdir("/usr/lib/maluos")
    a["firstboot_running"] = fb["running"]
    a["firstboot_finished"] = fb["done_file"] and not fb["running"]
    a["firstboot_failed_components"] = (fb.get("summary") or {}).get("failed") or {}
    a["kernel_enabled"] = bool(cfg and cfg.get("enabled"))
    a["domain_chosen"] = bool(cfg and cfg.get("domain") and cfg["domain"] != "maluos.local")
    a["provisioned_for_domain"] = bool(k and cfg and k.get("domain") == cfg.get("domain") and k.get("scheme") == cfg.get("scheme") and not k.get("error"))
    a["units_all_active"] = all(v == "active" for v in svc.values())
    a["api_healthy"] = hc["api_health_http"] == 200
    a["login_answers"] = hc["login_via_host_header_http"] == "200"
    scheme = cfg.get("scheme") if cfg else None
    pa = cfg.get("proxy_address") if cfg else None
    if scheme == "https":
        a["self_resolution_ok"] = bool(pa) and hosts["app_resolves_to"] == [pa] and not hosts["loopback_lines"]
    elif scheme == "http":
        a["self_resolution_ok"] = hosts["app_resolves_to"] == ["127.0.0.1"]
    else:
        a["self_resolution_ok"] = None
    a["claude_agents_possible"] = prov.get("anthropic") is True
    a["jev_possible"] = prov.get("openrouter") is True
    a["mail_possible"] = prov.get("malumail") is True
    return a


def collect():
    cfg, cfg_err = kernel_config()
    fb = firstboot_state()
    domain = (cfg or {}).get("domain")
    hosts = hosts_for(domain)
    hc = health(domain)
    svc = services()
    prov = providers()
    data = {
        "packages": dpkg_versions("maluos-firstboot", "maludb-os-core", "maluos-apps", "maluos-business-os"),
        "component": {"present": os.path.exists(KERNEL_COMPONENT),
                      "supports_proxy_address": os.path.exists(KERNEL_COMPONENT) and "proxy_address" in (read(KERNEL_COMPONENT) or ""),
                      "supports_apps": os.path.exists(KERNEL_COMPONENT) and "maludb_os_apps" in (read(KERNEL_COMPONENT) or "")},
        "firstboot": fb, "kernel_config": cfg, "kernel_config_error": cfg_err,
        "hosts": hosts, "services": svc, "health": hc, "providers": prov,
        "admin_password_file": os.path.exists(ADMIN_PW) if os.geteuid() == 0 else "unknown (not root)",
        "apps_installed": apps_state(), "virt": virt(), "network": network(), "root": os.geteuid() == 0,
    }
    data["assessment"] = assess(cfg or {}, fb, hosts, hc, svc, prov)
    return data


def human(d):
    a, c = d["assessment"], d["kernel_config"] or {}
    fb = d["firstboot"]
    print(f"packages:        " + ", ".join(f"{k} {v or 'absent'}" for k, v in d["packages"].items()))
    print(f"component:       proxy_address {'native' if d['component']['supports_proxy_address'] else 'NOT supported (hosts block by script)'}; "
          f"apps.install {'supported' if d['component']['supports_apps'] else 'ignored on this release'}")
    print(f"first boot:      {fb['unit']['sub_state']} ({fb['unit']['active_state']}, result {fb['unit']['result']}); done file {'present' if fb['done_file'] else 'absent'}")
    if fb.get("summary"):
        s = fb["summary"]
        print(f"                 provisioned {s.get('provisioned_at')}; failed components: {s.get('failed') or 'none'}")
        if s.get("kernel"):
            print(f"                 kernel provisioned for {s['kernel'].get('domain')} ({s['kernel'].get('scheme')}); error: {s['kernel'].get('error') or 'none'}")
    print(f"configuration:   enabled={c.get('enabled')} domain={c.get('domain')} scheme={c.get('scheme')} proxy_address={c.get('proxy_address')}")
    print(f"                 admin {c.get('admin_email')} / {c.get('admin_name')}; apps {c.get('apps')}; secrets in yaml: "
          + ", ".join(k for k, v in (c.get('secrets_set') or {}).items() if v) if c else "configuration: unreadable")
    print(f"names:           app.{c.get('domain')} -> {d['hosts']['app_resolves_to']}; loopback lines {len(d['hosts']['loopback_lines'])}; plugin block {d['hosts']['plugin_block']}")
    inactive = [k for k, v in d["services"].items() if v != "active"]
    print(f"services:        {len(d['services']) - len(inactive)}/{len(d['services'])} active" + (f"; not active: {', '.join(inactive)}" if inactive else ""))
    h = d["health"]
    print(f"health:          API {h['api_health_http']}; login via Host header {h['login_via_host_header_http']}; runner {h['runner_health_http']} harnesses {h['runner_harnesses']}")
    p = d["providers"]
    print(f"providers:       anthropic {p['anthropic']}, openrouter {p['openrouter']}, openai {p['openai']}, malumail {p['malumail']} (readable: {p['readable']})")
    print(f"virtualisation:  {d['virt']['type']}; qemu-guest-agent {d['virt']['qemu_guest_agent']}")
    print(f"addresses:       " + ", ".join(f"{x['iface']} {x['address']}" for x in d["network"]["addresses"]))
    print(f"apps installed:  {', '.join(x['key'] for x in d['apps_installed']) or 'none'}")
    print("assessment:      " + "; ".join(f"{k}={v}" for k, v in a.items()))


def report(d):
    a, c, h = d["assessment"], d["kernel_config"] or {}, d["health"]
    scheme, domain, pa = c.get("scheme"), c.get("domain"), c.get("proxy_address")
    topo = {"https": "external HTTPS proxy", "http": "private network, HTTP"}.get(scheme, "undecided")
    ok = lambda b: "ok" if b else ("not checked" if b is None else "NOT OK")
    bad = 0
    def row(name, good, detail=""):
        nonlocal bad
        if good is False: bad += 1
        print(f"| {name} | {ok(good)} | {detail} |")
    print(f"# Office configuration summary\n")
    print(f"Topology: **{topo}**. Domain: `{domain}`. Kernel URLs: `{scheme}://app.{domain}`, `{scheme}://os.{domain}`.\n")
    print("| Check | State | Detail |\n|---|---|---|")
    row("First boot finished", a["firstboot_finished"], f"unit {d['firstboot']['unit']['sub_state']}")
    row("No failed first-boot component", not a["firstboot_failed_components"], ", ".join(a["firstboot_failed_components"]) or "")
    row("Kernel configured for the domain", a["kernel_enabled"] and a["domain_chosen"], f"enabled={c.get('enabled')}")
    row("Kernel provisioned for the domain", a["provisioned_for_domain"], "done file agrees with firstboot.yaml" if a["provisioned_for_domain"] else "re-run provision.sh")
    row("Units active", a["units_all_active"], ", ".join(k for k, v in d["services"].items() if v != "active") or f"{len(d['services'])} active")
    row("Kernel API healthy", a["api_healthy"], f"HTTP {h['api_health_http']}")
    row("Sign-in page answers (Host header)", a["login_answers"], f"HTTP {h['login_via_host_header_http']}")
    if scheme == "https":
        row("Office resolves its names to the proxy", a["self_resolution_ok"], f"app.{domain} -> {d['hosts']['app_resolves_to']} (proxy {pa})")
        row("Names reachable through the proxy", None, "verify.sh --external says; needs the proxy's server blocks and certificates")
    elif scheme == "http":
        row("Office resolves its names to loopback", a["self_resolution_ok"], f"app.{domain} -> {d['hosts']['app_resolves_to']}")
        row("LAN clients resolve the names to the office", None, "test from a second machine: curl -sI http://app." + str(domain) + "/login")
    row("Claude agents can run (Anthropic key)", a["claude_agents_possible"], "" if a["claude_agents_possible"] else "deferred: no Claude agent runs until set (/office-providers)")
    row("JEV / system_one agents (OpenRouter key)", a["jev_possible"], "" if a["jev_possible"] else "deferred: eval grading and the two system_one agents unavailable")
    row("Invitations by mail (MaluMail key)", a["mail_possible"], "" if a["mail_possible"] else "deferred: invitations print a link (php bin/invitation_link.php)")
    if d["virt"]["type"] in ("kvm", "qemu"):
        row("Guest agent on the VM", d["virt"]["qemu_guest_agent"] == "active", d["virt"]["qemu_guest_agent"])
    apps = d["apps_installed"]
    print(f"\nApplications installed beside the kernel: {', '.join(x['key'] for x in apps) or 'none (stage 2, 12-applications.md)'}.")
    print(f"Names the proxy or the LAN DNS must carry: " + ", ".join(([domain, f'www.{domain}', f'app.{domain}', f'os.{domain}'] if domain else []) + [f"{x['label']}.{domain}" for x in apps]) + ".")
    print(f"\nFirst sign-in: `{scheme}://app.{domain}` as `{c.get('admin_email')}`; the generated password is in `{ADMIN_PW}` (root-only; read it yourself with sudo, change it on the profile page).")
    if bad:
        print(f"\n**{bad} check(s) not in place. The configuration is not complete.**")
        return 1
    print("\nEvery automated check for this topology is in place. The sign-in through a browser and any 'not checked' row remain the operator's confirmation.")
    return 0


if __name__ == "__main__":
    d = collect()
    if "--human" in sys.argv:
        human(d)
    elif "--report" in sys.argv:
        sys.exit(report(d))
    else:
        print(json.dumps(d, indent=1, default=str))
