"""maluctl app: the Business OS's applications on this office (the maluos-apps proposal, phase 1).

  maluctl app names [--json] [--domain DOMAIN]   the DNS names this office needs, one per line: the bare domain,
                                                 www, app, os, and <label>.<domain> for every application installed
                                                 under /srv/apps (its maludb-os.json's vhost.label). What the proxy's
                                                 operator pastes; the first-boot summary and `maluctl status` print
                                                 the same list.

  maluctl app names --upstreams [--domain DOMAIN] the same names with where each is served, "NAME<tab>kernel" or
                                                 "NAME<tab>ADDRESS" for an application on a server of its own: the
                                                 proxy's upstream per name (docs/phase14-application-servers.md)
  sudo maluctl app install KEY [KEY…]            on an APPLICATION SERVER (role: application-server): install the
                                                 applications here and register them with the kernel server at
                                                 application_server.kernel of /etc/maluos/firstboot.yaml. The server
                                                 must be a node of the estate whose join code named them.

The domain comes from the first-boot state (/var/lib/maluos/firstboot/done, components.maludb-os-core),
else from the kernel's config (/var/www/config/.env, APP_HOST). No privileges needed. The applications are
installed at first boot from components.maludb-os-core.apps in /etc/maluos/firstboot.yaml (docs/components.md);
add, update, status, list and remove follow in phase 2.
"""
import json, sys

sys.path.insert(0, "/usr/lib/maluos")


def main(args):
    import maludb_os_apps as A
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    if args[0] == "install":
        return install(A, list(args[1:]))
    if args[0] != "names":
        print(__doc__); return 2
    a = list(args[1:])
    domain = None
    if "--domain" in a:
        i = a.index("--domain")
        if i + 1 >= len(a):
            print("maluctl app names: --domain needs a value", file=sys.stderr); return 2
        domain = a[i + 1]; del a[i:i + 2]
    domain = domain or A.office_domain()
    if not domain:
        print("maluctl app names: no office domain yet (the Business OS kernel is not provisioned; `maluctl status`)", file=sys.stderr)
        return 1
    if "--upstreams" in a:
        ups = A.office_upstreams(domain)
        if "--json" in a:
            print(json.dumps({"domain": domain, "upstreams": [{"name": n, "upstream": u} for n, u in ups]}, indent=1)); return 0
        for n, u in ups:
            print(f"{n}\t{u}")
        return 0
    names = A.office_names(domain)
    if "--json" in a:
        print(json.dumps({"domain": domain, "names": names}, indent=1)); return 0
    for n in names:
        print(n)
    return 0


def install(A, keys):
    """maluctl app install on an application server: the kernel's installer in its host half, for each key."""
    import os
    if os.geteuid() != 0:
        print("maluctl app install: run it with sudo (it writes /srv/apps, Apache and the units)", file=sys.stderr); return 1
    if not keys:
        print("maluctl app install KEY [KEY…]", file=sys.stderr); return 2
    import maluos_provision as mp
    cfg = mp.load_config()
    if not mp.is_application_server(cfg):
        print("maluctl app install: this is not an application server (role: application-server in /etc/maluos/firstboot.yaml). "
              "On the kernel's own server the applications come from components.maludb-os-core.apps.install and `maluctl provision --force`.", file=sys.stderr)
        return 1
    blk = dict(cfg.get("application_server") or {})
    if not blk.get("kernel"):
        print("maluctl app install: application_server.kernel is not set in /etc/maluos/firstboot.yaml (the kernel server's door, http://HOST:8081)", file=sys.stderr); return 1
    blk["apps"] = keys
    t = mp.database_target(cfg)
    if t:
        mp.prepare_remote(t)
    try:
        res = A.install_remote_apps(blk, "/var/lib/maluos/business-os/apps",
                                    database=({**t, "passfile": mp.DB_PGPASS, "ca": mp.DB_CA if t.get("ca") else None} if t else None))
    except Exception as e:
        print(f"maluctl app install: {e}", file=sys.stderr); return 1
    for k in res["installed"]:
        print(f"{k}: installed here and registered with the kernel")
    for k in res["failed"]:
        print(f"{k}: FAILED: {res['errors'].get(k)} (the log: /var/lib/maluos/business-os/apps/{k}.log)", file=sys.stderr)
    return 1 if res["failed"] else 0
