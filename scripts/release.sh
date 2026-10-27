#!/bin/bash
# Cut a dated MaluOS release: VERSION, tag, named artefacts, signed checksums,
# notes from git, the GitHub Release (qcow2 + checksums + notes) and the
# download host (ISO + qcow2 + checksums). Packages keep their own versions;
# the OS release is the date of the build on top of the Ubuntu point release.
#
#   scripts/release.sh [--dry-run] [--no-upload] [--profiles=server|server,desktop] [--stale-ok]
# Re-runnable: an existing tag or GitHub release is reused and the uploads
# resume, so a dropped session is fixed by running it again (in tmux).
# Needs: a clean tree on main, build/maluos-*.iso and build/image/*.qcow2 from
# this tree (image/build-rootfs.sh, build-qcow2.sh, iso/build-iso.sh), gh auth.
# The server ISO and image are required; the desktop pair is released too
# when present (build both with -p desktop).
# Every artefact must come from this tree (the freshness guard below); --stale-ok releases one that is not,
# with its findings printed, for a knowing exception.
# Optional: MALUOS_DOWNLOAD_RSYNC=user@host:/srv/download/maluos for the ISO.
# Run it as `source ~/.config/maluos/publish.env && scripts/release.sh`: without MALUOS_DOWNLOAD_S3 the
# tag and the GitHub Release are made but nothing reaches download.maluos.com (it says so at the end).
# The public MaluApps catalogue (docs/site/apps/catalog.json) is signed and published too (apps/);
# scripts/publish-catalog.sh does only that, between releases.
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
drop_caches_loop() { while :; do sleep 15; sync; sudo -n sh -c 'echo 1 > /proc/sys/vm/drop_caches' 2>/dev/null || true; done; }
ROOT=$(cd "$(dirname "$0")/.." && pwd); cd "$ROOT"
. repo/config.env
DRY=0; UPLOAD=1; RESUME=0; STALE_OK=0
ONLY=""
for a in "$@"; do case "$a" in --dry-run) DRY=1;; --no-upload) UPLOAD=0;; --resume) RESUME=1;; --stale-ok) STALE_OK=1;; --profiles=*) ONLY=${a#--profiles=};; esac; done
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
# The freshness guard: every artefact staged comes from this tree. 26.04.20261027 shipped the 10-24 ISOs
# (gateway 0.3.4) beside that day's images because nothing looked. Two rules per profile, for the ISO and
# the image alike: the manifest (build/image/maluos-P.manifest; /casper/maluos-P.manifest inside the ISO)
# lists every package this tree builds at the version its debian/changelog declares, and the file is
# newer than the last commit that touched packages/, seeds/, image/ or iso/.
tree_versions=$(for d in packages/*/; do v=$(head -1 "$d/debian/changelog" | sed -E 's/.*\(([^)]+)\).*/\1/'); grep -h '^Package:' "$d/debian/control" | awk -v v="$v" '{print $2 "\t" v}'; done)
last_change=$(git log -1 --format=%ct -- packages seeds image iso); last_change_desc=$(git log -1 --format='%h, %cd' --date=format:'%Y-%m-%d %H:%M' -- packages seeds image iso)
stale=()
check_manifest() {   # check_manifest ARTEFACT MANIFEST: the tree's packages at the tree's versions
    local bad; bad=$(awk -F'\t' 'NR==FNR {tree[$1]=$2; next} ($1 in tree) && tree[$1] != $2 {printf "%s %s (the tree has %s)\n", $1, $2, tree[$1]}' <(printf '%s\n' "$tree_versions") "$2")
    [ -z "$bad" ] || while read -r l; do stale+=("$1: $l"); done <<< "$bad"
}
check_age() { [ "$(stat -c %Y "$1")" -ge "$last_change" ] || stale+=("$1: built before the last change to packages/, seeds/, image/ or iso/ ($last_change_desc)"); }
for p in $PROFILES; do
    iso=build/maluos-26.04.1-$p-amd64.iso; qcow=build/image/maluos-$p-26.04-amd64.qcow2; man=build/image/maluos-$p.manifest
    [ -f "$iso" ] && [ -f "$qcow" ] || { echo "no $p ISO or image in build/" >&2; exit 1; }
    if [ -f "$man" ]; then check_manifest "$qcow" "$man"; else stale+=("$qcow: no manifest beside it ($man)"); fi
    check_age "$qcow"
    tmp=$(mktemp -u)
    if xorriso -indev "$iso" -osirrox on -extract "/casper/maluos-$p.manifest" "$tmp" >/dev/null 2>&1; then check_manifest "$iso" "$tmp"; rm -f "$tmp"
    else stale+=("$iso: no /casper/maluos-$p.manifest inside it"); fi
    check_age "$iso"
done
if [ ${#stale[@]} -gt 0 ]; then
    echo "== stale artefacts: a release must come from this tree" >&2; printf '   %s\n' "${stale[@]}" >&2
    echo "   rebuild: repo/publish.sh, then for each profile image/build-rootfs.sh -p P, image/build-qcow2.sh -p P, iso/build-iso.sh -p P" >&2
    if [ $STALE_OK = 1 ]; then echo "   --stale-ok: releasing them anyway" >&2; else exit 1; fi
else echo "== fresh: every artefact carries this tree's package versions and postdates its last package change ($last_change_desc)"; fi
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
    # The public MaluApps catalogue (Phase 12 slice 9): signed by the same key; maluctl office apps verifies it
    # with the archive keyring and refuses it unsigned. Staged beside the images, published under apps/.
    mkdir -p "$OUT/apps"; cp docs/site/apps/catalog.json "$OUT/apps/catalog.json"
    gpg --yes --batch --armor --detach-sign -u "$MALUOS_PUBLIC_SIGNING_UID" -o "$OUT/apps/catalog.json.asc" "$OUT/apps/catalog.json"
    gpgv --keyring packages/maluos-keyring/build/maluos-archive-keyring.gpg "$OUT/apps/catalog.json.asc" "$OUT/apps/catalog.json" >/dev/null 2>&1 \
        || gpg --batch --verify "$OUT/apps/catalog.json.asc" "$OUT/apps/catalog.json" >/dev/null 2>&1 || { echo "catalog.json.asc did not verify" >&2; exit 1; }
    echo "== apps catalogue signed ($OUT/apps/catalog.json.asc)"
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
        aws "${ep[@]}" s3 sync "$OUT/" "$MALUOS_DOWNLOAD_S3/$VERSION/" --cache-control "max-age=86400" --exclude "apps/*"
        printf '%s\n' "$VERSION" > "$OUT/LATEST" && aws "${ep[@]}" s3 cp "$OUT/LATEST" "$MALUOS_DOWNLOAD_S3/LATEST" --cache-control "max-age=300"
        echo "== artefacts on the download bucket under $VERSION/ (LATEST updated)"
        for f in catalog.json catalog.json.asc; do
            aws "${ep[@]}" s3 cp "$OUT/apps/$f" "$MALUOS_DOWNLOAD_S3/apps/$f" --cache-control "max-age=300" --content-type "$([ "$f" = catalog.json ] && echo application/json || echo text/plain)"
        done
        echo "== apps catalogue and its signature on the download bucket under apps/"
    elif [ -n "${MALUOS_DOWNLOAD_RSYNC:-}" ]; then
        rsync -az --info=stats1 "$OUT/" "$MALUOS_DOWNLOAD_RSYNC/$VERSION/"
        echo "== artefacts on the download host under $VERSION/"
    else
        echo "   (set MALUOS_DOWNLOAD_S3 or MALUOS_DOWNLOAD_RSYNC to push the ISO to the download host; it is too large for a GitHub release asset)"
    fi
fi
echo "== done: $OUT"
