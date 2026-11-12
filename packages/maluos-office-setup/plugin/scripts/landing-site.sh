#!/bin/bash
# landing-site.sh: the office's public page (the bare name and www.), /var/www/landing: static files
# served by Apache, no PHP. First boot puts a starter there (Bootstrap 5.3 + htmx); this script is how
# an edited copy gets published without anyone editing root-owned files in place.
#
#   landing-site.sh status                 where the page is, starter or customised, the backups kept
#   landing-site.sh checkout DIR           copy the live page to DIR (owned by the operator) to work on
#   landing-site.sh publish DIR            check DIR, back the live page up, replace it with DIR
#   landing-site.sh restore [BACKUP]       put the last backup (or the named one) back
#
# publish refuses anything a files-only site should not carry: symlinks, dot files, server-side code,
# a missing index.html, more than 200 MB. The live directory is replaced whole, so a file removed from
# DIR is removed from the site. Ten backups are kept under /var/backups/maluos-landing.
. "$(dirname "$(readlink -f "$0")")/lib.sh"
LIVE=/var/www/landing
BACKUPS=/var/backups/maluos-landing
MAX_MB=200
ALLOWED='html|htm|css|js|mjs|json|txt|xml|webmanifest|ico|png|jpg|jpeg|gif|webp|avif|svg|woff|woff2|ttf|otf|pdf|mp4|webm|md'

kind_of() {  # starter | customised | absent
  [ -f "$1/index.html" ] || { echo absent; return; }
  grep -q '<meta name="maluos-landing" content="starter"' "$1/index.html" && echo starter || echo customised
}
domain_of() { python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(((s.get("components") or {}).get("maludb-os-core") or {}).get("domain",""))' "$FIRSTBOOT_DONE" 2>/dev/null || true; }

check_tree() {  # every reason DIR cannot be published, one per line; nothing when it can
  local dir="$1" f rel ext mb
  [ -f "$dir/index.html" ] || echo "no index.html in $dir"
  while IFS= read -r -d '' f; do
    rel=${f#./}
    if [ -L "$dir/$rel" ]; then echo "symbolic link: $rel"; continue; fi
    case "/$rel" in */.*) echo "dot file or directory: $rel"; continue;; esac
    [ -d "$dir/$rel" ] && continue
    [ -f "$dir/$rel" ] || { echo "not a regular file: $rel"; continue; }
    ext=${rel##*/}; case "$ext" in *.*) ext=${ext##*.};; *) ext="";; esac
    printf '%s' "${ext,,}" | grep -qxE "$ALLOWED" || echo "file type not served by a files-only site: $rel"
  done < <(cd "$dir" && find . -mindepth 1 -print0)
  mb=$(du -sm "$dir" | cut -f1); [ "$mb" -le "$MAX_MB" ] || echo "$mb MB is more than $MAX_MB MB"
}

cmd=${1:-status}; shift || true
case "$cmd" in
  status)
    need_root status "$@"; require_office
    k=$(kind_of "$LIVE"); d=$(domain_of)
    say "directory:  $LIVE"
    say "page:       $k$([ "$k" = starter ] && echo ' (the starter from first boot: it says so on the page and asks search engines not to list it)')"
    [ -n "$d" ] && say "served as:  $d and www.$d"
    [ "$k" != absent ] && say "files:      $(find "$LIVE" -type f | wc -l), $(du -sh "$LIVE" | cut -f1)"
    n=$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
    say "backups:    $n$([ "$n" -gt 0 ] && echo ", the last $(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | tail -1)")"
    ;;
  checkout)
    need_root checkout "$@"; require_office
    dir=${1:-}; [ -n "$dir" ] || die "usage: landing-site.sh checkout DIR"
    [ -f "$LIVE/index.html" ] || die "there is no page at $LIVE (has first boot run? see: maluctl firstboot status)"
    owner=${SUDO_USER:-root}
    if [ -e "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then die "$dir exists and is not empty; choose another directory or empty it first"; fi
    mkdir -p "$dir" && cp -r --no-dereference "$LIVE/." "$dir/"
    chown -R "$owner": "$dir"; chmod -R u+rwX "$dir"
    pass "the live page ($(kind_of "$dir")) copied to $dir, owned by $owner"
    ;;
  publish)
    need_root publish "$@"; require_office
    dir=${1:-}; [ -n "$dir" ] && [ -d "$dir" ] || die "usage: landing-site.sh publish DIR"
    dir=$(readlink -f "$dir")
    case "$dir" in "$LIVE"|"$LIVE"/*|/|/var/www) die "publish from a working copy, not from $dir";; esac
    problems=$(check_tree "$dir")
    if [ -n "$problems" ]; then printf '%s\n' "$problems" | sed 's/^/FAIL  /'; die "nothing was published"; fi
    stamp=$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$BACKUPS"; chmod 700 "$BACKUPS"
    if [ -d "$LIVE" ]; then cp -r --no-dereference "$LIVE" "$BACKUPS/$stamp"; pass "the live page backed up to $BACKUPS/$stamp"; fi
    new="$LIVE.new.$$"; rm -rf "$new"; cp -r --no-dereference "$dir" "$new"
    chown -R root:root "$new"; find "$new" -type d -exec chmod 755 {} +; find "$new" -type f -exec chmod 644 {} +
    old="$LIVE.old.$$"; [ -d "$LIVE" ] && mv "$LIVE" "$old"; mv "$new" "$LIVE"; rm -rf "$old"
    find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | head -n -10 | while read -r b; do rm -rf "${BACKUPS:?}/$b"; done
    pass "published: $(find "$LIVE" -type f | wc -l) files, the page is $(kind_of "$LIVE")"
    d=$(domain_of)
    if [ -n "$d" ]; then
      c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Host: $d" http://127.0.0.1/ 2>/dev/null || echo 000)
      [ "$c" = 200 ] && pass "the office answers for $d with the page (200)" || fail "the office answers for $d with HTTP $c"
    fi
    [ "$(kind_of "$LIVE")" = starter ] && note "the page still carries the starter marker, banner and noindex; remove them when it is ready for the public"
    [ "${FAILED:-0}" -eq 0 ] || exit 1
    ;;
  restore)
    need_root restore "$@"; require_office
    b=${1:-$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort | tail -1)}
    [ -n "$b" ] && [ -d "$BACKUPS/$b" ] || die "no backup to restore${1:+: $1}"
    old="$LIVE.old.$$"; [ -d "$LIVE" ] && mv "$LIVE" "$old"; cp -r --no-dereference "$BACKUPS/$b" "$LIVE"; rm -rf "$old"
    pass "restored $BACKUPS/$b ($(kind_of "$LIVE"))"
    ;;
  *) die "usage: landing-site.sh status | checkout DIR | publish DIR | restore [BACKUP]";;
esac
