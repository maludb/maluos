#!/bin/sh
# Runs INSIDE the bootstrap chroot (mmdebstrap customize hook).
# Arguments: MALUOS_REPO_URL (reachable from the chroot), suite, flat (0/1:
# 1 = unsigned flat repository, trusted; used by CI where no signing key exists).
# Installs the MaluOS repository configuration and the profile packages,
# then cleans the rootfs for imaging.
set -eu
REPO_URL=$1; SUITE=$2; FLAT=${3:-0}
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
APT='apt-get -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold'

printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d; chmod +x /usr/sbin/policy-rc.d
if [ "$FLAT" = 1 ]; then
    cat > /etc/apt/sources.list.d/maluos-build.sources <<SRC
Types: deb
URIs: $REPO_URL
Suites: ./
Trusted: yes
SRC
else
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
fi
apt-get update -q
# PGDG key arrives with postgresql-client-common; maluos-archive then adds pgdg.sources.
$APT install --no-install-recommends postgresql-client-common
$APT install maluos-keyring maluos-archive
apt-get update -q
# Third-party repositories a profile needs at build time (maluos-archive-mozilla
# for Firefox): install their source packages first, then refresh apt.
extra=$(grep -oE '^maluos-archive-[a-z0-9-]+' /tmp/stage/profile.pkgs || true)
if [ -n "$extra" ]; then
    # shellcheck disable=SC2086
    $APT install $extra
    apt-get update -q
fi
# shellcheck disable=SC2046
$APT install $(grep -vE '^\s*(#|$)' /tmp/stage/profile.pkgs)

# PostgreSQL cluster port: the build chroot shares the host's network namespace,
# so pg_createcluster skips 5432 when the host runs PostgreSQL. Pin it.
# DKMS modules (the live image's apple-bce and bcm5974 for T2 Macs) for every kernel in the image, whatever
# the build host runs: a module's postinst builds for the running kernel alone
if command -v dkms >/dev/null; then
    for k in /lib/modules/*/build; do [ -d "$k" ] && dkms autoinstall -k "$(basename "$(dirname "$k")")" || true; done
    dkms status || true
fi
for f in /etc/postgresql/*/main/postgresql.conf; do
    [ -f "$f" ] && sed -i 's/^port = .*/port = 5432/' "$f"
done

# --- clean for imaging ---------------------------------------------------
rm -f /etc/apt/sources.list.d/maluos-build.sources /etc/apt/keyrings/maluos-build-keyring.gpg
# maluos.sources (apt.maluos.com, production-signed) stays enabled: installed
# systems take MaluOS updates from there, unattended-upgrades included.
sed -i '/^Enabled:/d' /etc/apt/sources.list.d/maluos.sources
apt-get clean
rm -rf /var/lib/apt/lists/*
echo maluos > /etc/hostname
printf '127.0.0.1 localhost\n127.0.1.1 maluos\n\n::1 localhost ip6-localhost ip6-loopback\nff02::1 ip6-allnodes\nff02::2 ip6-allrouters\n' > /etc/hosts
locale-gen en_US.UTF-8 >/dev/null 2>&1 || true
echo 'LANG=C.UTF-8' > /etc/default/locale
: > /etc/machine-id; rm -f /var/lib/dbus/machine-id
rm -f /etc/ssh/ssh_host_*            # regenerated on first boot (cloud-init / ssh-keygen -A)
rm -rf /var/lib/cloud/* /var/log/journal/* /tmp/stage /root/.bash_history
rm -f /var/lib/systemd/credential.secret   # per-host key for systemd-creds; never shared between images
find /var/log -type f -writable -exec truncate -s0 {} + 2>/dev/null || true
rm -f /usr/sbin/policy-rc.d
