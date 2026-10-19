#!/bin/bash
# Cut a dated MaluOS release: VERSION, tag, named artefacts, signed checksums,
# notes from git, the GitHub Release (qcow2 + checksums + notes) and the
# download host (ISO + qcow2 + checksums). Packages keep their own versions;
# the OS release is the date of the build on top of the Ubuntu point release.
#
#   scripts/release.sh [--dry-run] [--no-upload]
# Re-runnable: an existing tag or GitHub release is reused and the uploads
# resume, so a dropped session is fixed by running it again (in tmux).
# Needs: a clean tree on main, build/maluos-*.iso and build/image/*.qcow2 from
# this tree (image/build-rootfs.sh, build-qcow2.sh, iso/build-iso.sh), gh auth.
# Optional: MALUOS_DOWNLOAD_RSYNC=user@host:/srv/download/maluos for the ISO.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); cd "$ROOT"
. repo/config.env
DRY=0; UPLOAD=1
for a in "$@"; do case "$a" in --dry-run) DRY=1;; --no-upload) UPLOAD=0;; esac; done
[ -z "$(git status --porcelain)" ] || { echo "working tree not clean" >&2; exit 1; }
[ "$(git branch --show-current)" = main ] || { echo "release from main" >&2; exit 1; }
BASE=$(grep -oE 'VERSION_ID="[0-9.]+"' packages/maluos-branding/files/usr/lib/os-release | grep -oE '[0-9.]+')
VERSION="$BASE.$(date -u +%Y%m%d)"
TAG="v$VERSION"
ISO=build/maluos-26.04.1-server-amd64.iso; QCOW=build/image/maluos-server-26.04-amd64.qcow2
[ -f "$ISO" ] && [ -f "$QCOW" ] || { echo "build the ISO and the cloud image first" >&2; exit 1; }
OUT=build/release/$VERSION; mkdir -p "$OUT"
gpg --batch --list-secret-keys "$MALUOS_PUBLIC_SIGNING_UID" >/dev/null 2>&1 || { echo "production key not on this host" >&2; exit 1; }
echo "== release $VERSION ($TAG)"
cp -f "$ISO" "$OUT/maluos-$VERSION-server-amd64.iso"
cp -f "$QCOW" "$OUT/maluos-$VERSION-server-amd64.qcow2"
( cd "$OUT" && sha256sum maluos-$VERSION-server-amd64.iso maluos-$VERSION-server-amd64.qcow2 > SHA256SUMS )
if [ $DRY = 0 ]; then
    ( cd "$OUT" && gpg --yes --clearsign -u "$MALUOS_PUBLIC_SIGNING_UID" -o SHA256SUMS.gpg SHA256SUMS )   # production key: asks for the passphrase
    gpg --batch --verify "$OUT/SHA256SUMS.gpg" >/dev/null 2>&1 || { echo "SHA256SUMS.gpg did not verify" >&2; exit 1; }
fi
LAST=$(git describe --tags --abbrev=0 2>/dev/null || true)
{
  echo "# MaluOS $VERSION"
  echo; echo "Ubuntu $BASE base (resolute), built $(date -u +%Y-%m-%d) from $(git rev-parse --short HEAD)."
  echo; echo "## Packages"; echo; awk -F'\t' '/^(maluos-|maludb-|postgresql-18-maludb)/ {print "- " $1 " " $2}' build/image/maluos-server.manifest
  echo; echo "## Changes${LAST:+ since $LAST}"; echo; git log --no-merges --format='- %s' ${LAST:+$LAST..}HEAD | head -60
  echo; echo "## Files"; echo; echo '```'; cat "$OUT/SHA256SUMS"; echo '```'
  echo; echo "The ISO (4.7 GB) is on the download host; the cloud image and checksums are attached here. Verify SHA256SUMS.gpg with the MaluOS archive key."
} > "$OUT/RELEASE-NOTES.md"
echo "$VERSION" > VERSION
if [ $DRY = 1 ]; then echo "dry run: artefacts in $OUT"; cat "$OUT/RELEASE-NOTES.md"; exit 0; fi
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    echo "== $TAG already tagged; resuming the upload"
else
    git add VERSION && git commit -q -m "Release $VERSION" && git tag -a "$TAG" -m "MaluOS $VERSION" && git push -q origin main "$TAG"
    echo "== tagged $TAG"
fi
if [ $UPLOAD = 1 ]; then
    assets=("$OUT/maluos-$VERSION-server-amd64.qcow2" "$OUT/SHA256SUMS" "$OUT/SHA256SUMS.gpg")
    if gh release view "$TAG" >/dev/null 2>&1; then
        gh release upload "$TAG" --clobber "${assets[@]}"
        echo "== GitHub release assets refreshed"
    else
        gh release create "$TAG" --title "MaluOS $VERSION" --notes-file "$OUT/RELEASE-NOTES.md" "${assets[@]}"
        echo "== GitHub release created"
    fi
    if [ -n "${MALUOS_DOWNLOAD_S3:-}" ]; then
        ep=(); [ -n "${MALUOS_S3_ENDPOINT:-}" ] && ep=(--endpoint-url "$MALUOS_S3_ENDPOINT")
        aws "${ep[@]}" s3 sync "$OUT/" "$MALUOS_DOWNLOAD_S3/$VERSION/" --cache-control "max-age=86400"
        printf '%s\n' "$VERSION" > "$OUT/LATEST" && aws "${ep[@]}" s3 cp "$OUT/LATEST" "$MALUOS_DOWNLOAD_S3/LATEST" --cache-control "max-age=300"
        echo "== artefacts on the download bucket under $VERSION/ (LATEST updated)"
    elif [ -n "${MALUOS_DOWNLOAD_RSYNC:-}" ]; then
        rsync -az --info=stats1 "$OUT/" "$MALUOS_DOWNLOAD_RSYNC/$VERSION/"
        echo "== artefacts on the download host under $VERSION/"
    else
        echo "   (set MALUOS_DOWNLOAD_S3 or MALUOS_DOWNLOAD_RSYNC to push the ISO to the download host; it is too large for a GitHub release asset)"
    fi
fi
echo "== done: $OUT"
