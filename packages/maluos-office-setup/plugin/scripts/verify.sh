#!/bin/bash
# verify.sh: the checks after provisioning, PASS/FAIL per line; exit 1 when any FAIL.
#
#   verify.sh --domain example.com --scheme https --proxy-address 192.168.100.1 [--external]
#   verify.sh --domain example.com --scheme http [--external]
#
# Without --external: the office's own state (units, the kernel's API, the sign-in page by Host header,
# the environment files, name resolution on the office for the scheme). With --external: the names as a
# client would reach them, from this machine: through the proxy under https (needs the proxy's server
# blocks and certificates), at the office's address under http.
. "$(dirname "$(readlink -f "$0")")/lib.sh"
DOMAIN=""; SCHEME=""; PROXY=""; EXTERNAL=0
while [ $# -gt 0 ]; do case "$1" in
  --domain) DOMAIN="$2"; shift 2;; --scheme) SCHEME="$2"; shift 2;; --proxy-address) PROXY="$2"; shift 2;;
  --external) EXTERNAL=1; shift;; *) die "unknown argument $1";; esac; done
[ -n "$DOMAIN" ] && [ -n "$SCHEME" ] || die "usage: verify.sh --domain D --scheme http|https [--proxy-address A] [--external]"
[ "$SCHEME" = https ] && [ -z "$PROXY" ] && note "https without --proxy-address: the self-resolution check is skipped"
require_office
FAILED=0

say "## units"
units=(apache2 maludb-api maludb-os-web maludb-os-records-mcp maludb-os-activity-mcp maludb-os-actions-mcp maludb-os-memory-mcp maludb-os-agent-runner maludb-os-activity-ingest.timer)
inactive=(); for u in "${units[@]}"; do systemctl is-active --quiet "$u" || inactive+=("$u"); done
if [ ${#inactive[@]} -eq 0 ]; then pass "${#units[@]} units active"; else fail "not active: ${inactive[*]}"; fi

say "## the kernel"
c=$(http_code http://127.0.0.1:8080/api/v1/health); [ "$c" = 200 ] && pass "API health 200" || fail "API health HTTP $c"
c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Host: app.$DOMAIN" http://127.0.0.1/login 2>/dev/null || echo 000)
[ "$c" = 200 ] && pass "sign-in page answers for app.$DOMAIN (Host header) 200" || fail "sign-in page for app.$DOMAIN HTTP $c"
if [ -r "$KERNEL_ENV" ] || [ "$(id -u)" -eq 0 ]; then
  url=$(grep -E '^APP_URL=' "$KERNEL_ENV" 2>/dev/null | cut -d= -f2- || true)
  [ "$url" = "$SCHEME://app.$DOMAIN" ] && pass "APP_URL=$url" || fail "APP_URL is '$url', expected $SCHEME://app.$DOMAIN (re-run provision.sh)"
else note "config/.env not readable as $(id -un); APP_URL not checked"; fi
if [ -f "$FIRSTBOOT_DONE" ]; then
  d=$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); k=(s.get("components") or {}).get("maludb-os-core") or {}; print(k.get("domain",""), k.get("scheme",""), k.get("error",""))' "$FIRSTBOOT_DONE" 2>/dev/null || true)
  set -- $d; [ "${1:-}" = "$DOMAIN" ] && [ "${2:-}" = "$SCHEME" ] && [ -z "${3:-}" ] && pass "first-boot state: kernel provisioned for $DOMAIN ($SCHEME)" || fail "first-boot state says domain='${1:-}' scheme='${2:-}' error='${3:-}'"
else fail "no first-boot done file"; fi
if [ "$(id -u)" -eq 0 ]; then
  [ -s /var/lib/maluos/secrets/business-os/admin-password ] && pass "generated admin password file present (root-only; not shown)" || note "no generated admin-password file (a password was given in the plan, or the account predates this run)"
fi

say "## the office's own names ($SCHEME)"
res=$(getent ahostsv4 "app.$DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' | sed 's/ $//')
loop=$(grep -cE "^127\.0\.0\.1[[:space:]].*(^|[[:space:]])(app|os|www)?\.?$DOMAIN([[:space:]]|$)" /etc/hosts 2>/dev/null || true)
case "$SCHEME" in
  https)
    if [ -n "$PROXY" ]; then
      [ "$res" = "$PROXY" ] && pass "app.$DOMAIN resolves to the proxy ($PROXY) on the office" || fail "app.$DOMAIN resolves to '${res:-nothing}', expected the proxy $PROXY (hosts-proxy.sh, or proxy_address + provision.sh)"
      [ "${loop:-0}" = 0 ] && pass "no loopback /etc/hosts line carries the domain's names" || fail "$loop loopback line(s) in /etc/hosts still carry $DOMAIN names"
    fi;;
  http)
    [ "$res" = "127.0.0.1" ] && pass "app.$DOMAIN resolves to loopback on the office" || fail "app.$DOMAIN resolves to '${res:-nothing}', expected 127.0.0.1 (first boot writes the line; provision.sh)";;
esac

if [ "$EXTERNAL" = 1 ]; then
  say "## the names as a client reaches them (from this machine)"
  for n in $(office_names "$DOMAIN"); do
    path=/; case "$n" in app.*) path=/login;; esac
    c=$(http_code "$SCHEME://$n$path" 15)
    case "$c" in
      200|301|302|303|307|308) pass "$SCHEME://$n$path -> $c";;
      502) fail "$SCHEME://$n$path -> 502: the proxy answered but could not reach its upstream (check the upstream address and port on the proxy)";;
      000) fail "$SCHEME://$n$path -> no connection or TLS failure (route, DNS or certificate)";;
      *) fail "$SCHEME://$n$path -> $c";;
    esac
  done
fi
say ""; [ "$FAILED" -eq 0 ] && say "all checks passed" || { say "$FAILED check(s) failed"; exit 1; }
