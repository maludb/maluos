#!/bin/bash
# Shared by every script in this directory. Source it; do not run it.
# shellcheck disable=SC2034  # the variables are used by the scripts that source this file
set -euo pipefail

FIRSTBOOT_YAML=/etc/maluos/firstboot.yaml
FIRSTBOOT_DONE=/var/lib/maluos/firstboot/done
KERNEL_COMPONENT=/usr/lib/maluos/components/60-maludb-os-core.py
RUNNER_ENV=/etc/business-os/runner.env
KERNEL_ENV=/var/www/config/.env
LOG_DIR=/var/log/maluos-office-setup
HOSTS_BEGIN="# BEGIN maluos-office-setup names"
HOSTS_END="# END maluos-office-setup names"

say()  { printf '%s\n' "$*"; }
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; FAILED=$(( ${FAILED:-0} + 1 )); }
note() { printf 'NOTE  %s\n' "$*"; }
die()  { printf 'ERROR %s\n' "$*" >&2; exit "${2:-1}"; }

# Re-run this script as root through sudo -n. The plugin's bootstrap installs a sudoers drop-in that
# allows exactly the scripts of this directory without a password; without it, the operator runs
# the script with sudo in their own terminal.
need_root() {
  [ "$(id -u)" -eq 0 ] && return 0
  if sudo -n true 2>/dev/null; then
    exec sudo -n "$(readlink -f "$0")" "$@"
  fi
  die "needs root. Either run: sudo $(readlink -f "$0") $*  — or install the plugin's sudoers rule (bootstrap.sh --sudoers)." 97
}

on_office() { [ -f "$FIRSTBOOT_YAML" ] && [ -d /usr/lib/maluos ]; }
require_office() { on_office || die "this is not a MaluOS office: $FIRSTBOOT_YAML or /usr/lib/maluos is missing. Run the scripts on the office itself."; }

# proxy_address support arrived in maluos-firstboot 0.1.16 (release 26.04.20261106); before that the
# component only wrote loopback lines and the names had to be pointed at the proxy by hand.
component_supports_proxy_address() { [ -f "$KERNEL_COMPONENT" ] && grep -q "proxy_address" "$KERNEL_COMPONENT"; }
component_supports_apps() { [ -f "$KERNEL_COMPONENT" ] && grep -q "maludb_os_apps" "$KERNEL_COMPONENT"; }

# The names the office needs: maluctl app names when the plugin exists, else the four kernel names.
office_names() {
  local domain="$1"
  if maluctl app names --domain "$domain" >/dev/null 2>&1; then
    maluctl app names --domain "$domain"
  else
    printf '%s\n' "$domain" "www.$domain" "app.$domain" "os.$domain"
    local m label
    for m in /srv/apps/*/maludb-os.json; do
      [ -f "$m" ] || continue
      label=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print((m.get("vhost") or {}).get("label") or m.get("catalog_key") or "")' "$m" 2>/dev/null || true)
      [ -n "$label" ] && printf '%s\n' "$label.$domain"
    done
  fi
}

http_code() { curl -s -o /dev/null -w '%{http_code}' -m "${2:-10}" "$1" 2>/dev/null || echo 000; }
