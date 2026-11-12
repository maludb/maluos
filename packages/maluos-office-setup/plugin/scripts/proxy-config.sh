#!/bin/bash
# proxy-config.sh: render the nginx server blocks the TLS proxy needs for this office (the handbook's
# proxy/office.conf with the real names), for the proxy's operator to install. Runs on the office, needs
# no privileges. Nothing is installed anywhere by this script.
#
#   proxy-config.sh --domain example.com --upstream 192.168.100.50 [--upstream-port 80] \
#                   [--cert /etc/letsencrypt/live/example.com/fullchain.pem --key /etc/letsencrypt/live/example.com/privkey.pem] \
#                   [--out /tmp/office-nginx.conf]
. "$(dirname "$(readlink -f "$0")")/lib.sh"
DOMAIN=""; UP=""; PORT=80; CERT=""; KEY=""; OUT=""
while [ $# -gt 0 ]; do case "$1" in
  --domain) DOMAIN="$2"; shift 2;; --upstream) UP="$2"; shift 2;; --upstream-port) PORT="$2"; shift 2;;
  --cert) CERT="$2"; shift 2;; --key) KEY="$2"; shift 2;; --out) OUT="$2"; shift 2;; *) die "unknown argument $1";; esac; done
[ -n "$DOMAIN" ] && [ -n "$UP" ] || die "usage: proxy-config.sh --domain D --upstream OFFICE-ADDRESS [--upstream-port 80] [--cert F --key F] [--out F]"
CERT=${CERT:-/etc/letsencrypt/live/$DOMAIN/fullchain.pem}; KEY=${KEY:-/etc/letsencrypt/live/$DOMAIN/privkey.pem}
names=(); while IFS= read -r n; do [ -n "$n" ] && names+=("$n"); done < <(office_names "$DOMAIN")
kernel=("$DOMAIN" "www.$DOMAIN" "app.$DOMAIN" "os.$DOMAIN")
# an application on a server of its own has its own upstream (maluctl app names --upstreams: NAME<tab>ADDRESS)
declare -A far=()
while IFS=$'\t' read -r n u; do
  [ -n "$n" ] && [ -n "$u" ] && [ "$u" != kernel ] && [ "$u" != "?" ] && far["$n"]="$u"
done < <(maluctl app names --upstreams --domain "$DOMAIN" 2>/dev/null || true)
apps=(); big=()
for n in "${names[@]}"; do
  case " ${kernel[*]} " in *" $n "*) continue;; esac
  [ -n "${far[$n]:-}" ] && continue
  case "$n" in doccloud.*) big+=("$n");; *) apps+=("$n");; esac
done
render() {
cat <<NGX
# nginx: the MaluDB Business OS for $DOMAIN behind this proxy. Rendered $(date -u +%Y-%m-%dT%H:%M:%SZ) by
# maluos-office-setup on the office; TLS is the proxy's (certbot, a wildcard, whatever it already does).
# Upstream: the office at $UP:$PORT (plain HTTP; the office honours X-Forwarded-Proto); an application on a server
# of its own has that server as its upstream.

map \$http_upgrade \$connection_upgrade { default upgrade; '' close; }

upstream office_$(echo "$DOMAIN" | tr '.-' '__') { server $UP:$PORT; keepalive 32; }

# the kernel: the bare name, www, app, os (long-lived agent runs and event streams: no buffering)
server {
    listen 443 ssl http2;
    server_name ${kernel[*]};
    ssl_certificate     $CERT;
    ssl_certificate_key $KEY;
    client_max_body_size 64m;
    location / {
        proxy_pass http://office_$(echo "$DOMAIN" | tr '.-' '__');
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
}
NGX
if [ ${#apps[@]} -gt 0 ]; then cat <<NGX

# the applications: one name each, same upstream
server {
    listen 443 ssl http2;
    server_name ${apps[*]};
    ssl_certificate     $CERT;
    ssl_certificate_key $KEY;
    client_max_body_size 64m;
    location / {
        proxy_pass http://office_$(echo "$DOMAIN" | tr '.-' '__');
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
}
NGX
fi
if [ ${#big[@]} -gt 0 ]; then cat <<NGX

# DocCloud: larger uploads
server {
    listen 443 ssl http2;
    server_name ${big[*]};
    ssl_certificate     $CERT;
    ssl_certificate_key $KEY;
    client_max_body_size 512m;
    location / {
        proxy_pass http://office_$(echo "$DOMAIN" | tr '.-' '__');
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 3600s;
        proxy_request_buffering off;
    }
}
NGX
fi
for n in "${!far[@]}"; do
  size=64m; case "$n" in doccloud.*) size=512m;; esac
  cat <<NGX

# $n: an application on a server of its own (${far[$n]})
server {
    listen 443 ssl http2;
    server_name $n;
    ssl_certificate     $CERT;
    ssl_certificate_key $KEY;
    client_max_body_size $size;
    location / {
        proxy_pass http://${far[$n]}:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
}
NGX
done
cat <<NGX

# http -> https for every name
server {
    listen 80;
    server_name ${names[*]};
    return 301 https://\$host\$request_uri;
}
NGX
}
if [ -n "$OUT" ]; then render > "$OUT"; say "written: $OUT  (names: ${names[*]})"; else render; fi
