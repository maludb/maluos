#!/bin/bash
# One-time maintainer setup: signing key, exported public key, aptly repo.
# Safe to re-run; every step is idempotent.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"

if ! gpg --batch --list-secret-keys "$MALUOS_SIGNING_UID" >/dev/null 2>&1; then
    echo "== generating signing key: $MALUOS_SIGNING_UID"
    gpg --batch --gen-key <<KEY
%no-protection
Key-Type: RSA
Key-Length: 4096
Key-Usage: sign
Name-Real: ${MALUOS_SIGNING_UID%% <*}
Name-Email: $(echo "$MALUOS_SIGNING_UID" | sed 's/.*<\(.*\)>/\1/')
Expire-Date: 5y
%commit
KEY
else
    echo "== signing key already present"
fi
gpg --batch --armor --export "$MALUOS_SIGNING_UID" \
    > "$ROOT/packages/maluos-keyring/keys/maluos-archive-keyring.asc"
echo "== public key exported to packages/maluos-keyring/keys/"

if [ ! -f "$HOME/.aptly.conf" ]; then
    cat > "$HOME/.aptly.conf" <<CONF
{
  "rootDir": "$HOME/.aptly",
  "architectures": ["amd64", "arm64", "all"],
  "gpgProvider": "gpg",
  "skipContentsPublishing": false,
  "skipBz2Publishing": true
}
CONF
    echo "== wrote ~/.aptly.conf"
fi

if ! aptly repo show "$MALUOS_APTLY_REPO" >/dev/null 2>&1; then
    aptly repo create -distribution="$MALUOS_SUITE" -component="$MALUOS_COMPONENT" \
        -comment="MaluOS packages for Ubuntu $MALUOS_SUITE" "$MALUOS_APTLY_REPO"
else
    echo "== aptly repo $MALUOS_APTLY_REPO exists"
fi
echo "done. Next: scripts/build-packages.sh && repo/publish.sh"
