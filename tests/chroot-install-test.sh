#!/bin/bash
# Phase 1 acceptance test: on a *clean* Ubuntu 26.04 root filesystem, the
# bootstrap installer must add the MaluOS repository and install
# maluos-server, ending with PostgreSQL 18 and the MaluDB packages present.
#
# Builds a throwaway rootfs with mmdebstrap (needs root), points it at the
# locally served repository (repo/serve.sh must be running), and runs the
# same install-maluos.sh a user would.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

TEST_URL=${TEST_URL:-http://127.0.0.1:$MALUOS_SERVE_PORT}
MIRROR=${MIRROR:-http://archive.ubuntu.com/ubuntu}
WORK=${WORK:-/var/tmp/maluos-chroot-test}
TARGET=${1:-maluos-server}
CHROOT=$WORK/rootfs
TESTBUILD=$WORK/build

curl -fsS "$TEST_URL/dists/$MALUOS_SUITE/Release" >/dev/null \
    || { echo "repository not reachable at $TEST_URL; start repo/serve.sh" >&2; exit 1; }

echo "== building test variant of maluos-archive pointing at $TEST_URL"
rm -rf "$TESTBUILD"; mkdir -p "$TESTBUILD"
cp -a "$ROOT/packages/maluos-archive" "$ROOT/packages/maluos-keyring" "$TESTBUILD/"
for p in maluos-archive maluos-keyring; do
    ( cd "$TESTBUILD/$p" && MALUOS_APT_URL=$TEST_URL dpkg-buildpackage -us -uc -b >/dev/null 2>&1 )
done

echo "== bootstrapping clean $MALUOS_SUITE rootfs in $CHROOT"
rm -rf "$CHROOT"
mmdebstrap --mode=root --variant=apt \
    --include=ca-certificates,curl \
    --components=main,universe \
    "$MALUOS_SUITE" "$CHROOT" "$MIRROR" >"$WORK/mmdebstrap.log" 2>&1 \
    || { tail -20 "$WORK/mmdebstrap.log"; exit 1; }

# Services must not start inside the chroot.
printf '#!/bin/sh\nexit 101\n' > "$CHROOT/usr/sbin/policy-rc.d"; chmod +x "$CHROOT/usr/sbin/policy-rc.d"
cp /etc/resolv.conf "$CHROOT/etc/resolv.conf"
mkdir -p "$CHROOT/bootstrap"
cp "$TESTBUILD"/maluos-keyring_*_all.deb "$CHROOT/bootstrap/maluos-keyring_latest_all.deb"
cp "$TESTBUILD"/maluos-archive_*_all.deb "$CHROOT/bootstrap/maluos-archive_latest_all.deb"
cp "$ROOT/scripts/install-maluos.sh" "$CHROOT/bootstrap/"

# The installer downloads the keyring and archive packages from the repo;
# serve them from the chroot-local copies so the test exercises the
# locally built (test URL) variant rather than the published production one.
cat > "$CHROOT/bootstrap/run.sh" <<RUN
set -e
cd /bootstrap
sed -i 's|curl -fsSL -o "\$tmp/\$p.deb" .*|cp /bootstrap/\${p}_latest_all.deb "\$tmp/\$p.deb"|' install-maluos.sh
MALUOS_APT_URL=$TEST_URL bash install-maluos.sh $TARGET
RUN

echo "== running install-maluos.sh $TARGET inside the chroot"
mount -t proc proc "$CHROOT/proc"
trap 'umount -l "$CHROOT/proc" 2>/dev/null || true' EXIT
chroot "$CHROOT" bash /bootstrap/run.sh >"$WORK/install.log" 2>&1 \
    || { tail -40 "$WORK/install.log"; exit 1; }

echo "== verifying"
fail=0
for p in maluos-keyring maluos-archive maluos-base "$TARGET" postgresql-18 postgresql-18-maludb-core maludb-mc2dbd; do
    if chroot "$CHROOT" dpkg-query -W -f='${Status}\n' "$p" 2>/dev/null | grep -q 'install ok installed'; then
        echo "  ok   $p"
    else
        echo "  FAIL $p"; fail=1
    fi
done
chroot "$CHROOT" apt-cache policy maludb-mc2dbd | grep -q "$TEST_URL" && echo "  ok   maludb-mc2dbd came from $TEST_URL" || { echo "  FAIL origin"; fail=1; }
test -f "$CHROOT/usr/lib/postgresql/18/lib/maludb_core.so" && echo "  ok   maludb_core.so present" || { echo "  FAIL maludb_core.so"; fail=1; }
[ $fail = 0 ] && echo "PASS: $TARGET installs on a clean $MALUOS_SUITE rootfs" || { echo "FAIL (logs in $WORK)"; exit 1; }
