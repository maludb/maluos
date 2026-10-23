#!/bin/bash
# Google Chrome: Google's .deb from dl.google.com; its postinst adds Google's repository and key,
# so later versions come through apt (and the automatic-updates policy does not cover them: "other").
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if command -v google-chrome >/dev/null; then echo "already installed: $(google-chrome --version)"; exit 0; fi
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
echo "downloading google-chrome-stable_current_amd64.deb"
curl -fsSL -o "$tmp/google-chrome-stable_current_amd64.deb" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt-get install -y "$tmp/google-chrome-stable_current_amd64.deb"
echo "installed: $(google-chrome --version)"
