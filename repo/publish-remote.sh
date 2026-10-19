#!/bin/bash
# Mirror the PUBLIC tree (signed by the production key; repo/publish.sh --public)
# to the host behind MALUOS_APT_URL. Refuses a tree signed by any other key.
# Pool first, then dists, so clients never see an index that points at a
# missing file. Then verifies the InRelease over HTTPS.
#
#   MALUOS_REMOTE_RSYNC=user@host:/srv/apt repo/publish-remote.sh
#   MALUOS_REMOTE_S3=s3://bucket [MALUOS_S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com] repo/publish-remote.sh
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
SRC="$MALUOS_PUBLISH_ROOT/$MALUOS_PUBLIC_PREFIX"
test -f "$SRC/dists/$MALUOS_SUITE/InRelease" || { echo "no public tree at $SRC (repo/publish.sh --public first)" >&2; exit 1; }
want=$(gpg --batch --with-colons --list-keys "$MALUOS_PUBLIC_SIGNING_UID" | awk -F: '/^fpr/ {print $10; exit}')
got=$(gpg --batch --status-fd 1 --verify "$SRC/dists/$MALUOS_SUITE/InRelease" 2>/dev/null | awk '/VALIDSIG/ {print $NF; exit}')
[ -n "$want" ] && [ "$got" = "$want" ] || { echo "the public tree is not signed by the production key ($got vs $want); refusing" >&2; exit 1; }
echo "== public tree signed by $MALUOS_PUBLIC_SIGNING_UID"
if [ -n "${MALUOS_REMOTE_RSYNC:-}" ]; then
    rsync -az --info=stats1 "$SRC/pool/" "$MALUOS_REMOTE_RSYNC/pool/"
    rsync -az --info=stats1 "$SRC/bootstrap/" "$MALUOS_REMOTE_RSYNC/bootstrap/"
    rsync -az --delete --info=stats1 "$SRC/dists/" "$MALUOS_REMOTE_RSYNC/dists/"
    rsync -az --delete --info=stats1 "$SRC/pool/" "$MALUOS_REMOTE_RSYNC/pool/"   # prune superseded files after the index is in place
elif [ -n "${MALUOS_REMOTE_S3:-}" ]; then
    ep=(); [ -n "${MALUOS_S3_ENDPOINT:-}" ] && ep=(--endpoint-url "$MALUOS_S3_ENDPOINT")
    aws "${ep[@]}" s3 sync "$SRC/pool/" "$MALUOS_REMOTE_S3/pool/"
    aws "${ep[@]}" s3 sync "$SRC/bootstrap/" "$MALUOS_REMOTE_S3/bootstrap/"
    aws "${ep[@]}" s3 sync --delete "$SRC/dists/" "$MALUOS_REMOTE_S3/dists/" --cache-control "max-age=300"
    aws "${ep[@]}" s3 sync --delete "$SRC/pool/" "$MALUOS_REMOTE_S3/pool/"
else
    echo "set MALUOS_REMOTE_RSYNC=user@host:/path or MALUOS_REMOTE_S3=s3://bucket (and MALUOS_S3_ENDPOINT for R2)" >&2; exit 2
fi
echo "== verifying $MALUOS_APT_URL/dists/$MALUOS_SUITE/InRelease"
if curl -fsS --max-time 20 "$MALUOS_APT_URL/dists/$MALUOS_SUITE/InRelease" | gpg --batch --verify >/dev/null 2>&1; then
    echo "   signed index reachable and verified"
else
    echo "   warning: could not fetch or verify the remote InRelease (DNS, TLS or the key); check $MALUOS_APT_URL" >&2
fi
