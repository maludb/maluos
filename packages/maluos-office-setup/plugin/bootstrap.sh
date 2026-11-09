#!/bin/bash
# bootstrap.sh: steps 1 and 2 of the office configuration, on the office, as the operator (maluos).
#
#   1. install Claude Code for this user (Anthropic's native installer, ~/.local/bin/claude) if missing;
#   2. install this plugin root-owned under /usr/local/share/maluos/claude-plugins/maluos-office-setup
#      (skipped when the maluos-office-setup package already put it under /usr/share/maluos/claude-plugins);
#   3. offer the sudoers rule that lets the plugin's scripts run as root without a password prompt;
#   4. link the launcher as /usr/local/bin/maluos-office-setup.
#
#   From a clone:    git clone https://github.com/maludb/maluos-office-setup && maluos-office-setup/bootstrap.sh
#   Without git:     curl -fsSL https://raw.githubusercontent.com/maludb/maluos-office-setup/main/bootstrap.sh | bash
#   Options:         --no-claude   skip the Claude Code install      --sudoers   (re)install only the sudoers rule
#                    --yes         do not ask before the sudoers rule
# Needs: curl, sudo (interactive: this is your terminal), network access to claude.ai and github.com.
set -euo pipefail
REPO=https://github.com/maludb/maluos-office-setup
PKG_ROOT=/usr/share/maluos/claude-plugins/maluos-office-setup
LOCAL_ROOT=/usr/local/share/maluos/claude-plugins/maluos-office-setup
NO_CLAUDE=0; ONLY_SUDOERS=0; YES=0
for a in "$@"; do case "$a" in --no-claude) NO_CLAUDE=1;; --sudoers) ONLY_SUDOERS=1;; --yes) YES=1;; *) echo "unknown option $a" >&2; exit 2;; esac; done
[ "$(id -u)" -ne 0 ] || { echo "run bootstrap.sh as the operator account (maluos), not as root" >&2; exit 1; }
[ -f /etc/maluos/firstboot.yaml ] || echo "warning: /etc/maluos/firstboot.yaml is missing; this does not look like a MaluOS office. Continuing." >&2

# where is the plugin coming from?
SRC=""
here=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)
if [ -n "$here" ] && [ -f "$here/.claude-plugin/plugin.json" ]; then SRC="$here"; fi

install_sudoers() {
  local root="$1" tmp
  tmp=$(mktemp)
  sed "s|@PLUGIN_ROOT@|$root|" "$root/sudoers/maluos-office-setup" > "$tmp"
  if [ "$YES" = 0 ]; then
    echo; echo "The plugin's scripts need root (maluctl provision, /etc/maluos/firstboot.yaml, /etc/hosts, the env files)."
    echo "Claude Code's shell cannot answer a sudo password prompt, so this rule lets members of the sudo group run"
    echo "exactly these scripts without one:"; echo; sed 's/^/    /' "$tmp"; echo
    read -r -p "Install /etc/sudoers.d/maluos-office-setup? [y/N] " ans < /dev/tty
    case "$ans" in y|Y|yes) ;; *) echo "skipped: run the scripts with sudo yourself when the skill asks, or re-run with --sudoers"; rm -f "$tmp"; return 0;; esac
  fi
  sudo visudo -cf "$tmp" >/dev/null
  sudo install -m 440 -o root -g root "$tmp" /etc/sudoers.d/maluos-office-setup; rm -f "$tmp"
  echo "sudoers rule installed for $root/scripts/*"
}

if [ "$ONLY_SUDOERS" = 1 ]; then
  root=""; for r in "$PKG_ROOT" "$LOCAL_ROOT" "$SRC"; do [ -n "$r" ] && [ -f "$r/.claude-plugin/plugin.json" ] && { root="$r"; break; }; done
  [ -n "$root" ] || { echo "no installed plugin found" >&2; exit 1; }
  install_sudoers "$root"; exit 0
fi

# 1. Claude Code
export PATH="$HOME/.local/bin:$PATH"
if [ "$NO_CLAUDE" = 0 ]; then
  if command -v claude >/dev/null 2>&1; then echo "Claude Code: already installed ($(claude --version 2>/dev/null | head -1))"
  else
    echo "Claude Code: installing with Anthropic's native installer (https://claude.ai/install.sh) for $(id -un) ..."
    curl -fsSL https://claude.ai/install.sh | bash
    export PATH="$HOME/.local/bin:$PATH"
    command -v claude >/dev/null 2>&1 || { echo "claude is not on PATH after the install; open a new shell or add ~/.local/bin to PATH" >&2; exit 1; }
    echo "Claude Code: $(claude --version 2>/dev/null | head -1)"
  fi
fi

# 2. the plugin, root-owned
if [ -f "$PKG_ROOT/.claude-plugin/plugin.json" ]; then
  ROOT="$PKG_ROOT"; echo "plugin: the maluos-office-setup package is installed at $ROOT; using it"
else
  if [ -z "$SRC" ]; then
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    if command -v git >/dev/null 2>&1; then git clone -q --depth 1 "$REPO" "$tmp/src"
    else mkdir -p "$tmp/src"; curl -fsSL "$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$tmp/src" --strip-components=1; fi
    SRC="$tmp/src"
  fi
  sudo install -d -m 755 -o root -g root "$(dirname "$LOCAL_ROOT")"
  sudo rm -rf "$LOCAL_ROOT"
  sudo cp -a "$SRC" "$LOCAL_ROOT"
  sudo chown -R root:root "$LOCAL_ROOT"; sudo chmod -R a+rX,go-w "$LOCAL_ROOT"; sudo chmod 755 "$LOCAL_ROOT"/scripts/*.sh "$LOCAL_ROOT"/scripts/*.py "$LOCAL_ROOT"/bin/*
  ROOT="$LOCAL_ROOT"; echo "plugin: installed at $ROOT (version $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.claude-plugin/plugin.json"))"
fi

# 3. sudoers
install_sudoers "$ROOT"

# 4. the launcher
sudo ln -sfn "$ROOT/bin/maluos-office-setup" /usr/local/bin/maluos-office-setup
echo
echo "Done. Next, in a tmux session (provisioning takes minutes):"
echo "    tmux new -s office"
echo "    maluos-office-setup"
echo "The first run signs you in to Claude Code (a URL to open on your workstation and a code to paste back, or an API key)."
echo "Then the setup skill asks its questions. '/office-check' reports the state at any time."
