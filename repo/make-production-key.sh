#!/bin/bash
# Create the production archive signing key: a passphrase-protected Ed25519
# primary (certify only) with a signing subkey, the public half committed to
# packages/maluos-keyring/keys/ (several keys may coexist there: rotation
# ships the new key signed by the old one). The primary secret key leaves the
# publishing host; only the signing subkey stays for repo/publish.sh.
#
#   repo/make-production-key.sh [YEAR]      (default: this year)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
YEAR=${1:-$(date +%Y)}
UID_="MaluOS Archive Signing Key ($YEAR) <apt@maludb.org>"
KEYS="$ROOT/packages/maluos-keyring/keys"
if gpg --batch --list-secret-keys "$UID_" >/dev/null 2>&1; then
    echo "key already exists: $UID_"
else
    echo "== generating $UID_ (you will be asked for a passphrase; keep it in the password manager)"
    gpg --quick-generate-key "$UID_" ed25519 cert 5y
    FPR=$(gpg --batch --with-colons --list-keys "$UID_" | awk -F: '/^fpr/ {print $10; exit}')
    gpg --quick-add-key "$FPR" ed25519 sign 2y
fi
FPR=$(gpg --batch --with-colons --list-keys "$UID_" | awk -F: '/^fpr/ {print $10; exit}')
gpg --batch --armor --export "$UID_" > "$KEYS/maluos-archive-keyring-$YEAR.asc"
echo "== public key exported: packages/maluos-keyring/keys/maluos-archive-keyring-$YEAR.asc"
echo "   fingerprint: $FPR"
cat <<EOF

Next steps (custody):
  1. Back up the primary secret key OFFLINE (USB in a safe, or the password manager's file vault):
       gpg --armor --export-secret-keys $FPR > maluos-archive-$YEAR-primary.asc   # then wipe it from this host
  2. Keep only the signing subkey on the publishing host:
       gpg --armor --export-secret-subkeys $FPR > subkeys.asc; gpg --delete-secret-keys $FPR; gpg --import subkeys.asc; shred -u subkeys.asc
  3. Sign with it: MALUOS_SIGNING_UID="$UID_" repo/publish.sh   (gpg-agent asks for the passphrase once per session)
  4. Bump packages/maluos-keyring (dch) and publish it, still signed by the OLD key, so clients learn the new key
     before the first release signed with it. See docs/release.md.
EOF
