#!/bin/bash
# MaluOS client bootstrap: turn a stock Ubuntu 26.04 system into a MaluOS
# system. Installs the keyring and APT source packages, then the requested
# metapackage (default: maluos-server).
#
#   curl -fsSL https://apt.maluos.com/bootstrap/install-maluos.sh | sudo bash
#   MALUOS_APT_URL=http://127.0.0.1:8080 sudo -E bash install-maluos.sh maluos-base
set -euo pipefail
MALUOS_APT_URL=${MALUOS_APT_URL:-https://apt.maluos.com}
TARGET=${1:-maluos-server}

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
. /etc/os-release
[ "${VERSION_CODENAME:-}" = resolute ] || { echo "MaluOS needs Ubuntu 26.04 (resolute), found ${PRETTY_NAME:-unknown}" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for p in maluos-keyring maluos-archive; do
    curl -fsSL -o "$tmp/$p.deb" "$MALUOS_APT_URL/bootstrap/${p}_latest_all.deb"
done
apt-get update -q
apt-get install -y -q --no-install-recommends postgresql-client-common
dpkg -i "$tmp"/maluos-keyring.deb "$tmp"/maluos-archive.deb
apt-get update -q
apt-get install -y -q "$TARGET"
echo "MaluOS: $TARGET installed from $MALUOS_APT_URL"
