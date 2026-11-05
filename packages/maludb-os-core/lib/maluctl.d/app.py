"""maluctl app: the Business OS's applications on this office (the maluos-apps proposal, phase 1).

  maluctl app names [--json] [--domain DOMAIN]   the DNS names this office needs, one per line: the bare domain,
                                                 www, app, os, and <label>.<domain> for every application installed
                                                 under /srv/apps (its maludb-os.json's vhost.label). What the proxy's
                                                 operator pastes; the first-boot summary and `maluctl status` print
                                                 the same list.

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
    names = A.office_names(domain)
    if "--json" in a:
        print(json.dumps({"domain": domain, "names": names}, indent=1)); return 0
    for n in names:
        print(n)
    return 0
