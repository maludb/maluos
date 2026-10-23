#!/bin/bash
# Claude Code: Anthropic's native installer, per user (no root): ~/.local/bin/claude.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
if command -v claude >/dev/null; then echo "already installed: $(claude --version)"; exit 0; fi
curl -fsSL https://claude.ai/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
echo "installed: $(claude --version)"
