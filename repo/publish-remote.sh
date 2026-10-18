#!/bin/bash
# Mirror the published repository (dists/, pool/, bootstrap/) to the public
# host behind MALUOS_APT_URL. Pool first, then dists, so clients never see an
# index that points at a missing file. Then verifies the InRelease over HTTPS.
#
#   MALUOS_REMOTE_RSYNC=user@host:/srv/apt/maluos repo/publish-remote.sh
#   MALUOS_REMOTE_S3=s3://bucket/maluos            repo/publish-remote.sh   (aws CLI)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/repo/config.env"
SRC="$MALUOS_PUBLISH_ROOT"
test -f "$SRC/dists/$MALUOS_SUITE/InRelease" || { echo "nothing published at $SRC (repo/publish.sh first)" >&2; exit 1; }
if [ -n "${MALUOS_REMOTE_RSYNC:-}" ]; then
    rsync -az --info=stats1 "$SRC/pool/" "$MALUOS_REMOTE_RSYNC/pool/"
    rsync -az --info=stats1 "$SRC/bootstrap/" "$MALUOS_REMOTE_RSYNC/bootstrap/"
    rsync -az --delete --info=stats1 "$SRC/dists/" "$MALUOS_REMOTE_RSYNC/dists/"
    rsync -az --delete --info=stats1 "$SRC/pool/" "$MALUOS_REMOTE_RSYNC/pool/"   # prune superseded files after the index is in place
elif [ -n "${MALUOS_REMOTE_S3:-}" ]; then
    aws s3 sync "$SRC/pool/" "$MALUOS_REMOTE_S3/pool/"
    aws s3 sync "$SRC/bootstrap/" "$MALUOS_REMOTE_S3/bootstrap/"
    aws s3 sync --delete "$SRC/dists/" "$MALUOS_REMOTE_S3/dists/" --cache-control "max-age=300"
    aws s3 sync --delete "$SRC/pool/" "$MALUOS_REMOTE_S3/pool/"
else
    echo "set MALUOS_REMOTE_RSYNC=user@host:/path or MALUOS_REMOTE_S3=s3://bucket/prefix" >&2; exit 2
fi
echo "== verifying $MALUOS_APT_URL/dists/$MALUOS_SUITE/InRelease"
if curl -fsS --max-time 20 "$MALUOS_APT_URL/dists/$MALUOS_SUITE/InRelease" | gpg --batch --verify >/dev/null 2>&1; then
    echo "   signed index reachable and verified"
else
    echo "   warning: could not fetch or verify the remote InRelease (DNS, TLS or the key); check $MALUOS_APT_URL" >&2
fi
