#!/bin/bash
# Publish the public MaluApps catalogue between releases (Phase 12 slice 9): sign
# docs/site/apps/catalog.json with the production key (the archive signing key, which
# maluos-keyring ships, so `maluctl office apps` on every desk verifies it) and copy
# both files to the download bucket under apps/. The release script does the same
# at every release.
#
#   source ~/.config/maluos/publish.env && scripts/publish-catalog.sh [--dry-run]
set -euo pipefail
cd "$(dirname "$0")/.."
DRY=0; [ "${1:-}" = --dry-run ] && DRY=1
: "${MALUOS_PUBLIC_SIGNING_UID:?set MALUOS_PUBLIC_SIGNING_UID (publish.env)}"
python3 -c 'import json,sys; c=json.load(open("docs/site/apps/catalog.json")); assert isinstance(c.get("apps"), list) and all(a.get("id") for a in c["apps"]), "catalog.json: apps with ids"; print(f"catalogue: {len(c[\"apps\"])} apps, updated {c.get(\"updated\")}")'
OUT=build/apps; mkdir -p "$OUT"; cp docs/site/apps/catalog.json "$OUT/catalog.json"
export GPG_TTY=$(tty 2>/dev/null || true)
gpg --yes --batch --armor --detach-sign -u "$MALUOS_PUBLIC_SIGNING_UID" -o "$OUT/catalog.json.asc" "$OUT/catalog.json"
gpg --batch --verify "$OUT/catalog.json.asc" "$OUT/catalog.json" >/dev/null 2>&1 || { echo "the signature did not verify" >&2; exit 1; }
echo "signed: $OUT/catalog.json.asc"
[ $DRY = 1 ] && { echo "dry run: not uploaded"; exit 0; }
: "${MALUOS_DOWNLOAD_S3:?set MALUOS_DOWNLOAD_S3 (publish.env)}"
ep=(); [ -n "${MALUOS_S3_ENDPOINT:-}" ] && ep=(--endpoint-url "$MALUOS_S3_ENDPOINT")
aws "${ep[@]}" s3 cp "$OUT/catalog.json" "$MALUOS_DOWNLOAD_S3/apps/catalog.json" --cache-control "max-age=300" --content-type application/json
aws "${ep[@]}" s3 cp "$OUT/catalog.json.asc" "$MALUOS_DOWNLOAD_S3/apps/catalog.json.asc" --cache-control "max-age=300" --content-type text/plain
echo "published: ${MALUOS_DOWNLOAD_S3#s3://} apps/catalog.json + .asc"
