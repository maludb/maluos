#!/bin/bash
# Ollama: the gateway's own installer (pinned release, sha256-checked, user, unit, gateway backend).
set -euo pipefail
if command -v ollama >/dev/null; then echo "already installed: $(ollama --version 2>&1 | head -1)"; exit 0; fi
exec maluctl gateway ollama install
