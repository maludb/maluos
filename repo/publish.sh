#!/bin/bash
# Add build/*.deb (and vendor/maludb/*.deb, and any .deb paths given) to the aptly
# repo and (re)publish. Two published trees of the same repository:
#   <publish root>/dists,pool         signed by the development key: image builds, tests
#   <publish root>/public/dists,pool  signed by the production key (--public): what
#                                     repo/publish-remote.sh mirrors to apt.maluos.com
# Bump a package version whenever its content changes; -force-overwrite only
# papers over same-version rebuilds during development.
#   repo/publish.sh [--public] [extra.deb ...]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
BUILD=${BUILD_DIR:-$ROOT/build}
PUBLIC=0; extra=()
for a in "$@"; do case "$a" in --public) PUBLIC=1;; *) extra+=("$a");; esac; done

debs=( "$BUILD"/*.deb "$ROOT"/vendor/maludb/*.deb "${extra[@]}" )
aptly repo add -force-replace "$MALUOS_APTLY_REPO" "${debs[@]}"

publish_tree() {   # prefix ("." for the root) and signing uid
    local prefix=$1 uid=$2 pfx_args=()
    [ "$prefix" = . ] || pfx_args=(-prefix="$prefix")
    if aptly publish list -raw | grep -qx "$prefix $MALUOS_SUITE"; then
        aptly publish update -force-overwrite -gpg-key="$uid" "${pfx_args[@]}" "$MALUOS_SUITE"
    else
        aptly publish repo -force-overwrite -gpg-key="$uid" "${pfx_args[@]}" -distribution="$MALUOS_SUITE" \
            -origin=MaluOS -label=MaluOS "$MALUOS_APTLY_REPO"
    fi
}

stage_bootstrap() {   # bootstrap files beside a published tree
    local boot=$1
    mkdir -p "$boot"
    for p in maluos-keyring maluos-archive; do
        latest=$(ls -1 "$BUILD"/${p}_*_all.deb | sort -V | tail -1)
        cp "$latest" "$boot/"
        ln -sf "$(basename "$latest")" "$boot/${p}_latest_all.deb"
    done
    cp "$ROOT/scripts/install-maluos.sh" "$boot/"
    # every archive key, development and production, so either signature verifies
    gpg --batch --export "$MALUOS_SIGNING_UID" "$MALUOS_PUBLIC_SIGNING_UID" > "$boot/maluos-archive-keyring.gpg" 2>/dev/null \
        || gpg --batch --export "$MALUOS_SIGNING_UID" > "$boot/maluos-archive-keyring.gpg"
}

publish_tree . "$MALUOS_SIGNING_UID"
stage_bootstrap "$MALUOS_PUBLISH_ROOT/bootstrap"
echo "== published $MALUOS_SUITE (development key) to $MALUOS_PUBLISH_ROOT"

if [ $PUBLIC = 1 ]; then
    gpg --batch --list-secret-keys "$MALUOS_PUBLIC_SIGNING_UID" >/dev/null 2>&1 \
        || { echo "no secret key for $MALUOS_PUBLIC_SIGNING_UID on this host (repo/make-production-key.sh)" >&2; exit 1; }
    publish_tree "$MALUOS_PUBLIC_PREFIX" "$MALUOS_PUBLIC_SIGNING_UID"
    stage_bootstrap "$MALUOS_PUBLISH_ROOT/$MALUOS_PUBLIC_PREFIX/bootstrap"
    echo "== published $MALUOS_SUITE (production key) to $MALUOS_PUBLISH_ROOT/$MALUOS_PUBLIC_PREFIX"
fi
aptly repo show -with-packages "$MALUOS_APTLY_REPO" | sed -n '/Packages:/,$p' | tail -n +2 | sort -V | tail -12
