#!/bin/bash
# Cut a dated MaluOS release: VERSION, tag, named artefacts, signed checksums,
# notes from git, the GitHub Release (qcow2 + checksums + notes) and the
# download host (ISO + qcow2 + checksums). Packages keep their own versions;
# the OS release is the date of the build on top of the Ubuntu point release.
#
#   scripts/release.sh [--dry-run] [--no-upload] [--profiles=server|server,desktop]
# Re-runnable: an existing tag or GitHub release is reused and the uploads
# resume, so a dropped session is fixed by running it again (in tmux).
# Needs: a clean tree on main, build/maluos-*.iso and build/image/*.qcow2 from
# this tree (image/build-rootfs.sh, build-qcow2.sh, iso/build-iso.sh), gh auth.
# The server ISO and image are required; the desktop pair is released too
# when present (build both with -p desktop).
# Optional: MALUOS_DOWNLOAD_RSYNC=user@host:/srv/download/maluos for the ISO.
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
drop_caches_loop() { while :; do sleep 15; sync; sudo -n sh -c 'echo 1 > /proc/sys/vm/drop_caches' 2>/dev/null || true; done; }
ROOT=$(cd "$(dirname "$0")/.." && pwd); cd "$ROOT"
. repo/config.env
DRY=0; UPLOAD=1; RESUME=0
ONLY=""
for a in "$@"; do case "$a" in --dry-run) DRY=1;; --no-upload) UPLOAD=0;; --resume) RESUME=1;; --profiles=*) ONLY=${a#--profiles=};; esac; done
[ -z "$(git status --porcelain)" ] || { echo "working tree not clean" >&2; exit 1; }
[ "$(git branch --show-current)" = main ] || { echo "release from main" >&2; exit 1; }
BASE=$(grep -oE 'VERSION_ID="[0-9.]+"' packages/maluos-branding/files/share/os-release.server | grep -oE '[0-9.]+')
VERSION="$BASE.$(date -u +%Y%m%d)"
TAG="v$VERSION"
# One release per UTC day: the version is the date. Re-running on the same day re-stages whatever
# is in build/ under the released name and would overwrite the published files; only an interrupted
# upload of the same files should be resumed, and that takes --resume.
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && [ $RESUME = 0 ]; then
    if [ $DRY = 1 ]; then echo "note: $TAG is already released; a real run today needs --resume (same files) or the next UTC day"
    else echo "$TAG is already released. New images wait for the next UTC day (now $(date -u +%H:%M) UTC); to resume an interrupted upload of the same files pass --resume" >&2; exit 1; fi
fi
ISO=build/maluos-26.04.1-server-amd64.iso; QCOW=build/image/maluos-server-26.04-amd64.qcow2
[ -f "$ISO" ] && [ -f "$QCOW" ] || { echo "build the ISO and the cloud image first" >&2; exit 1; }
PROFILES=server
[ -f build/maluos-26.04.1-desktop-amd64.iso ] && [ -f build/image/maluos-desktop-26.04-amd64.qcow2 ] && PROFILES="server desktop"
[ -n "$ONLY" ] && PROFILES=$(echo "$ONLY" | tr , " ")   # --profiles=server ships the server pair even when desktop images are present
OUT=build/release/$VERSION; mkdir -p "$OUT"
gpg --batch --list-secret-keys "$MALUOS_PUBLIC_SIGNING_UID" >/dev/null 2>&1 || { echo "production key not on this host" >&2; exit 1; }
echo "== release $VERSION ($TAG): $PROFILES"
if [ $DRY = 0 ]; then
    # Unlock the production key now, while you are watching the terminal: the agent caches the
    # passphrase (10 min by default) for the real signature after staging. On 2026-10-23 the prompt
    # came after five minutes of staging, drew on a terminal nobody was looking at and expired
    # (pinentry-curses times out after 60 s): "gpg: signing failed: Timeout".
    export GPG_TTY=$(tty); gpg-connect-agent updatestartuptty /bye >/dev/null 2>&1 || true
    echo "== production key: enter the passphrase now (cached for the signature after staging)"
    echo "maluos release $VERSION" | gpg --clearsign -u "$MALUOS_PUBLIC_SIGNING_UID" >/dev/null \
        || { echo "could not unlock the production key; run from an interactive terminal (tmux) and answer the pinentry dialog" >&2; exit 1; }
fi
stage() {   # stage SRC DEST: gentle copy, skipped when DEST is already a complete copy of this SRC (same size, newer)
    if [ -f "$2" ] && [ "$(stat -c %s "$1")" = "$(stat -c %s "$2")" ] && [ "$2" -nt "$1" ]; then echo "   already staged: $2"
    else "$ROOT_DIR/scripts/gentle.py" cp "$1" "$2"; fi
}
files=(); qcows=()
for p in $PROFILES; do
    echo "== staging $p ISO and image into $OUT (several GB at 100 MB/s, takes a while)"
    stage "build/maluos-26.04.1-$p-amd64.iso" "$OUT/maluos-$VERSION-$p-amd64.iso"
    stage "build/image/maluos-$p-26.04-amd64.qcow2" "$OUT/maluos-$VERSION-$p-amd64.qcow2"
    files+=("maluos-$VERSION-$p-amd64.iso" "maluos-$VERSION-$p-amd64.qcow2"); qcows+=("$OUT/maluos-$VERSION-$p-amd64.qcow2")
done
echo "== checksums (reads every file once, 100 MB/s)"
( cd "$OUT" && "$ROOT_DIR/scripts/gentle.py" sum "${files[@]}" > SHA256SUMS )
[ $DRY = 1 ] || echo "== signing SHA256SUMS with the production key (cached passphrase; a second prompt only if staging took over 10 min)"
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
  echo; echo "The ISOs are on the download host; the cloud images and checksums are attached here. Verify SHA256SUMS.gpg with the MaluOS archive key."
} > "$OUT/RELEASE-NOTES.md"
if [ $DRY = 1 ]; then echo "dry run: artefacts in $OUT"; cat "$OUT/RELEASE-NOTES.md"; exit 0; fi
echo "$VERSION" > VERSION
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    echo "== $TAG already tagged; resuming the upload"
else
    git add VERSION && git commit -q -m "Release $VERSION" && git tag -a "$TAG" -m "MaluOS $VERSION" && git push -q origin main "$TAG"
    echo "== tagged $TAG"
fi
if [ $UPLOAD = 1 ]; then
    # The uploads read the staged 13 GB again. Keep the page cache from growing to the VM's
    # full RAM meanwhile (the hypervisor has killed the dev VM at that point; scripts/gentle.py).
    drop_caches_loop & DROP_PID=$!; trap 'kill $DROP_PID 2>/dev/null' EXIT
    assets=("${qcows[@]}" "$OUT/SHA256SUMS" "$OUT/SHA256SUMS.gpg")
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
