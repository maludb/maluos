#!/bin/bash
# Codex: nodejs and npm from the Ubuntu archive, then npm install -g @openai/codex (/usr/local).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if command -v codex >/dev/null; then echo "already installed: $(codex --version)"; exit 0; fi
command -v npm >/dev/null || apt-get install -y nodejs npm
npm install -g @openai/codex
echo "installed: $(codex --version)"
