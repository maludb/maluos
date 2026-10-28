#!/bin/bash
# Give the agent runner a model provider's API key — the ledger proxy holds provider keys so no
# agent ever sees one (docs/build-specs/agent-runtime-hermes.md).
#
#   docs/deploy/set-provider-key.sh deepseek|openai|moonshot|fireworks /path/to/file-holding-the-key
#
# The key is read from a file so it never appears in a command line or a shell history, and it is
# never printed. runner.env is backed up (mode 600) to ~/env-backups first; the line is replaced
# if the provider already has a key, appended if not; then the key is checked against the
# provider's free model listing BEFORE the runner is restarted, so a bad key changes nothing.
set -euo pipefail
PROVIDER="${1:-}"; KEYFILE="${2:-}"
ENVFILE=/etc/business-os/runner.env
case "$PROVIDER" in
  deepseek)  VAR=DEEPSEEK_API_KEY;  PROBE=https://api.deepseek.com/models ;;
  openai)    VAR=OPENAI_API_KEY;    PROBE=https://api.openai.com/v1/models ;;
  moonshot)  VAR=MOONSHOT_API_KEY;  PROBE=https://api.moonshot.ai/v1/models ;;
  fireworks) VAR=FIREWORKS_API_KEY; PROBE=https://api.fireworks.ai/inference/v1/models ;;
  *) echo "usage: $0 <deepseek|openai|moonshot|fireworks> <key-file>" >&2; exit 1 ;;
esac
[ -r "$KEYFILE" ] || { echo "Cannot read $KEYFILE" >&2; exit 1; }
KEY="$(tr -d '[:space:]' < "$KEYFILE")"
[ ${#KEY} -ge 20 ] || { echo "That file does not hold an API key." >&2; exit 1; }

CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 20 -H "Authorization: Bearer $KEY" "$PROBE")
[ "$CODE" = "200" ] || { echo "$PROVIDER refused the key (HTTP $CODE on its model listing). Nothing was changed." >&2; exit 1; }

STAMP=$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$HOME/env-backups"; umask 077
sudo cat "$ENVFILE" > "$HOME/env-backups/runner.env.$STAMP"
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
sudo cat "$ENVFILE" | grep -v "^$VAR=" > "$TMP" || true
printf '%s=%s\n' "$VAR" "$KEY" >> "$TMP"
sudo install -m "$(sudo stat -c %a "$ENVFILE")" -o "$(sudo stat -c %U "$ENVFILE")" -g "$(sudo stat -c %G "$ENVFILE")" "$TMP" "$ENVFILE"
sudo systemctl restart maludb-os-agent-runner
sleep 3
systemctl is-active --quiet maludb-os-agent-runner && echo "$PROVIDER key installed ($VAR); runner restarted; backup: ~/env-backups/runner.env.$STAMP" \
  || { echo "The runner did not come back — restore ~/env-backups/runner.env.$STAMP" >&2; exit 1; }
