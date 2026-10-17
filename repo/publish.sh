#!/bin/bash
# Add build/*.deb (and any .deb paths given as arguments) to the aptly repo.
# Bump a package version whenever its content changes; -force-overwrite only
# papers over same-version rebuilds during development.
# and (re)publish the signed suite. Also stages the bootstrap files
# (keyring + archive .debs and install script) under <publish>/bootstrap/.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
BUILD=${BUILD_DIR:-$ROOT/build}

debs=( "$BUILD"/*.deb "$@" )
aptly repo add -force-replace "$MALUOS_APTLY_REPO" "${debs[@]}"

if aptly publish list -raw | grep -q "^\. $MALUOS_SUITE$"; then
    aptly publish update -force-overwrite -gpg-key="$MALUOS_SIGNING_UID" "$MALUOS_SUITE"
else
    aptly publish repo -force-overwrite -gpg-key="$MALUOS_SIGNING_UID" -distribution="$MALUOS_SUITE" \
        -origin=MaluOS -label=MaluOS "$MALUOS_APTLY_REPO"
fi

boot="$MALUOS_PUBLISH_ROOT/bootstrap"
mkdir -p "$boot"
for p in maluos-keyring maluos-archive; do
    latest=$(ls -1 "$BUILD"/${p}_*_all.deb | sort -V | tail -1)
    cp "$latest" "$boot/"
    ln -sf "$(basename "$latest")" "$boot/${p}_latest_all.deb"
done
cp "$ROOT/scripts/install-maluos.sh" "$boot/"
gpg --batch --export "$MALUOS_SIGNING_UID" > "$boot/maluos-archive-keyring.gpg"
echo "== published $MALUOS_SUITE to $MALUOS_PUBLISH_ROOT"
aptly repo show -with-packages "$MALUOS_APTLY_REPO" | sed -n '/Packages:/,$p'
