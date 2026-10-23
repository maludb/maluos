#!/bin/bash
# Visual Studio Code: Microsoft's repository as a deb822 source with its key under /etc/apt/keyrings.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if command -v code >/dev/null; then echo "already installed: $(code --version | head -1)"; exit 0; fi
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor --yes -o /etc/apt/keyrings/packages.microsoft.gpg
chmod 0644 /etc/apt/keyrings/packages.microsoft.gpg
cat > /etc/apt/sources.list.d/vscode.sources <<'SRC'
Types: deb
URIs: https://packages.microsoft.com/repos/code
Suites: stable
Components: main
Architectures: amd64 arm64 armhf
Signed-By: /etc/apt/keyrings/packages.microsoft.gpg
SRC
rm -f /etc/apt/sources.list.d/vscode.list
apt-get update -o Dir::Etc::sourcelist=sources.list.d/vscode.sources -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0
apt-get install -y code
echo "installed: $(code --version | head -1)"
