#!/bin/bash
# hosts-proxy.sh: on a release whose kernel component does not know proxy_address (maluos-firstboot before
# 0.1.16), point the office's own names at the TLS proxy in /etc/hosts, in a marked block, and take them
# off any loopback line. Idempotent. Not needed when the component is native: there, proxy_address in
# firstboot.yaml and provision.sh do it.
#
#   hosts-proxy.sh --domain example.com --proxy-address 192.168.100.1     write or refresh the block
#   hosts-proxy.sh --domain example.com --remove                           remove the block (loopback lines are not restored)
. "$(dirname "$(readlink -f "$0")")/lib.sh"
need_root "$@"
DOMAIN=""; PROXY=""; REMOVE=0
while [ $# -gt 0 ]; do case "$1" in
  --domain) DOMAIN="$2"; shift 2;; --proxy-address) PROXY="$2"; shift 2;; --remove) REMOVE=1; shift;; *) die "unknown argument $1";; esac; done
[ -n "$DOMAIN" ] || die "usage: hosts-proxy.sh --domain D (--proxy-address A | --remove)"
[ "$REMOVE" = 1 ] || [ -n "$PROXY" ] || die "give --proxy-address or --remove"
if component_supports_proxy_address && [ "$REMOVE" = 0 ]; then
  note "this release's kernel component knows proxy_address: prefer configure-kernel.py --proxy-address and provision.sh; writing the block anyway"
fi
names=$(office_names "$DOMAIN" | tr '\n' ' ' | sed 's/ $//')
cp -a /etc/hosts "/etc/hosts.before-office-setup-$(date -u +%Y%m%dT%H%M%SZ)"
python3 - "$DOMAIN" "$PROXY" "$REMOVE" "$HOSTS_BEGIN" "$HOSTS_END" $names <<'PY'
import re, sys
domain, proxy, remove, begin, end, *names = sys.argv[1:]
text = open("/etc/hosts").read()
lines = text.split("\n")
# drop an existing block
out, skipping = [], False
for l in lines:
    if l.strip() == begin: skipping = True; continue
    if l.strip() == end: skipping = False; continue
    if not skipping: out.append(l)
lines = out
if remove != "1":
    # take the names off every loopback line (what first boot wrote), dropping a line left with no names
    nameset = set(names)
    fixed = []
    for l in lines:
        if re.match(r"^\s*127\.0\.0\.1\s", l) and not l.lstrip().startswith("#"):
            parts = l.split()
            keep = [parts[0]] + [p for p in parts[1:] if p not in nameset and not p.endswith("." + domain) and p != domain]
            if len(keep) == 1: continue
            l = " ".join(keep)
        fixed.append(l)
    lines = fixed
    while lines and lines[-1] == "": lines.pop()
    lines += [begin, f"{proxy} " + " ".join(names), end]
open("/etc/hosts", "w").write("\n".join(lines).rstrip("\n") + "\n")
PY
if [ "$REMOVE" = 1 ]; then say "removed the maluos-office-setup block from /etc/hosts"; else
  say "/etc/hosts now carries, pointed at $PROXY: $names"
  getent ahostsv4 "app.$DOMAIN" | awk '{print $1}' | sort -u | sed 's/^/app.'"$DOMAIN"' -> /'
fi
