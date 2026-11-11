#!/bin/bash
# Bring the download page to a release and publish it: docs/site/download.md (source) and
# docs/site/download.html (the page) carry the release number in their links, the verify
# commands and the sizes. Until 2026-11-11 this was a step done by hand after each release
# (docs/release.md), and four releases went by with the page still naming 26.04.20261102.
# scripts/release.sh now runs it: --edit before the release commit, --upload after the files
# are on the bucket.
#
#   source ~/.config/maluos/publish.env && scripts/publish-download-page.sh [--edit|--upload] [VERSION]
#
# --edit    rewrite the two files for VERSION (default: the file VERSION): every mention of the
#           release the page names now, except a "Since 26.04.…" in the prose, which is history;
#           the build date, the release date, and the four sizes (from build/release/VERSION/,
#           or from the download host when the files are not here).
# --upload  copy download.html to the bucket as index.html and download.html and read it back.
# Neither: both. The prose of the page (what a release brings) stays a hand edit.
set -euo pipefail
cd "$(dirname "$0")/.."
EDIT=0; UPLOAD=0; VERSION=""
for a in "$@"; do case "$a" in --edit) EDIT=1;; --upload) UPLOAD=1;; -*) echo "unknown option $a" >&2; exit 2;; *) VERSION=$a;; esac; done
[ $EDIT = 0 ] && [ $UPLOAD = 0 ] && { EDIT=1; UPLOAD=1; }
VERSION=${VERSION:-$(cat VERSION)}
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]{8}$ ]] || { echo "not a release number: $VERSION" >&2; exit 2; }
HOST=${MALUOS_DOWNLOAD_URL:-https://download.maluos.com}
MD=docs/site/download.md; HTML=docs/site/download.html

if [ $EDIT = 1 ]; then
    python3 - "$VERSION" "$HOST" "$MD" "$HTML" <<'PY'
import os, re, sys, urllib.request
version, host, paths = sys.argv[1], sys.argv[2], sys.argv[3:]
day = version.rsplit(".", 1)[1]
date = f"{day[:4]}-{day[4:6]}-{day[6:]}"

def size(name):
    local = f"build/release/{version}/{name}"
    if os.path.isfile(local):
        n = os.path.getsize(local)
    else:
        req = urllib.request.Request(f"{host}/{version}/{name}", method="HEAD", headers={"User-Agent": "maluos-release"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                n = int(r.headers["Content-Length"])
        except Exception as e:
            return None
    return f"{n / 1e9:.1f} GB"

sizes = {f"{p}-amd64.{ext}": size(f"maluos-{version}-{p}-amd64.{ext}") for p in ("server", "desktop") for ext in ("iso", "qcow2")}
if sizes["server-amd64.iso"] is None or sizes["server-amd64.qcow2"] is None:
    sys.exit(f"the server files of {version} are neither in build/release/{version}/ nor on {host}")

for path in paths:
    text = open(path).read()
    m = re.search(r"^(?:<pre><code>)?V=(\d+\.\d+\.\d{8})$", text, re.M)
    if not m:
        sys.exit(f"{path}: no V=… line to read the page's release from")
    old = m.group(1); oldday = old.rsplit(".", 1)[1]
    new = re.sub(r"(?<!Since )" + re.escape(old), version, text)
    new = re.sub(r"\b" + oldday + r"(`?,? the build)", day + r"\1", new)
    new = re.sub(r"released \d{4}-\d{2}-\d{2}", f"released {date}", new)
    for suffix, s in sizes.items():
        if s is None:      # a release without the desktop pair keeps the size it had
            continue
        name = re.escape(f"maluos-{version}-{suffix}")
        new, n = re.subn(r"(" + name + r"[\")][^\n]*?)\d+(?:\.\d+)? GB", lambda k: k.group(1) + s, new, count=1)
        if n != 1:
            sys.exit(f"{path}: no size beside {suffix}")
    left = [l for l in new.splitlines() if old in l and "Since " + old not in l] if old != version else []
    if left:
        sys.exit(f"{path}: {old} still named: {left[0][:120]}")
    if new != text:
        open(path, "w").write(new)
        print(f"{path}: {old} -> {version}, released {date}, " + ", ".join(f"{k} {v}" for k, v in sizes.items() if v))
    else:
        print(f"{path}: already at {version}")
PY
fi

if [ $UPLOAD = 1 ]; then
    grep -q "^<pre><code>V=$VERSION\$" "$HTML" || { echo "$HTML does not name $VERSION; run with --edit first" >&2; exit 1; }
    : "${MALUOS_DOWNLOAD_S3:?set MALUOS_DOWNLOAD_S3 (source ~/.config/maluos/publish.env)}"
    ep=(); [ -n "${MALUOS_S3_ENDPOINT:-}" ] && ep=(--endpoint-url "$MALUOS_S3_ENDPOINT")
    for k in index.html download.html; do
        aws "${ep[@]}" s3 cp "$HTML" "$MALUOS_DOWNLOAD_S3/$k" --content-type "text/html; charset=utf-8" --cache-control "max-age=300" --only-show-errors
    done
    # Read it back through the public name (a query string to pass any cached copy). Not a byte
    # comparison: Cloudflare rewrites the e-mail address of the signing key in the served page.
    for k in index.html download.html; do
        served=$(curl -fsS --max-time 30 "$HOST/$k?v=$VERSION.$(date +%s)")
        if grep -q "^<pre><code>V=$VERSION\$" <<< "$served" && grep -q "href=\"$HOST/$VERSION/maluos-$VERSION-server-amd64.iso\"" <<< "$served"; then echo "== $HOST/$k is the page of $VERSION"
        else echo "$HOST/$k does not name $VERSION (a cache may hold the old page for up to 5 minutes; check again)" >&2; exit 1; fi
    done
fi
