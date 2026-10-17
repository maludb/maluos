#!/bin/sh
# Runs INSIDE the bootstrap chroot (mmdebstrap customize hook).
# Arguments: MALUOS_REPO_URL (reachable from the chroot), suite.
# Installs the MaluOS repository configuration and the profile packages,
# then cleans the rootfs for imaging.
set -eu
REPO_URL=$1; SUITE=$2
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
APT='apt-get -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold'

printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d; chmod +x /usr/sbin/policy-rc.d
# apt verifies signatures as the _apt user: the keyring must be world-readable
# and outside the 0700 staging directory.
install -d -m 0755 /etc/apt/keyrings
install -m 0644 /tmp/stage/maluos-archive-keyring.gpg /etc/apt/keyrings/maluos-build-keyring.gpg
cat > /etc/apt/sources.list.d/maluos-build.sources <<SRC
Types: deb
URIs: $REPO_URL
Suites: $SUITE
Components: main
Signed-By: /etc/apt/keyrings/maluos-build-keyring.gpg
SRC
apt-get update -q
# PGDG key arrives with postgresql-client-common; maluos-archive then adds pgdg.sources.
$APT install --no-install-recommends postgresql-client-common
$APT install maluos-keyring maluos-archive
apt-get update -q
# shellcheck disable=SC2046
$APT install $(grep -vE '^\s*(#|$)' /tmp/stage/profile.pkgs)

# PostgreSQL cluster port: the build chroot shares the host's network namespace,
# so pg_createcluster skips 5432 when the host runs PostgreSQL. Pin it.
for f in /etc/postgresql/*/main/postgresql.conf; do
    [ -f "$f" ] && sed -i 's/^port = .*/port = 5432/' "$f"
done

# --- clean for imaging ---------------------------------------------------
rm -f /etc/apt/sources.list.d/maluos-build.sources /etc/apt/keyrings/maluos-build-keyring.gpg
sed -i '/^Enabled:/d; $a Enabled: no' /etc/apt/sources.list.d/maluos.sources   # no public mirror yet
apt-get clean
rm -rf /var/lib/apt/lists/*
echo maluos > /etc/hostname
printf '127.0.0.1 localhost\n127.0.1.1 maluos\n\n::1 localhost ip6-localhost ip6-loopback\nff02::1 ip6-allnodes\nff02::2 ip6-allrouters\n' > /etc/hosts
locale-gen en_US.UTF-8 >/dev/null 2>&1 || true
echo 'LANG=C.UTF-8' > /etc/default/locale
: > /etc/machine-id; rm -f /var/lib/dbus/machine-id
rm -f /etc/ssh/ssh_host_*            # regenerated on first boot (cloud-init / ssh-keygen -A)
rm -rf /var/lib/cloud/* /var/log/journal/* /tmp/stage /root/.bash_history
find /var/log -type f -writable -exec truncate -s0 {} + 2>/dev/null || true
rm -f /usr/sbin/policy-rc.d
