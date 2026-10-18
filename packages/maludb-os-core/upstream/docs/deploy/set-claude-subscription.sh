#!/bin/bash
# Switch the owner's Claude subscription (Max plan) login ON or OFF for agents on the Claude Code harness — this install only.
# docs/build-specs/claude-subscription-auth.md. READ ITS RISK SECTION FIRST: using a subscription for autonomous agents may breach
# Anthropic's terms, may be throttled or blocked at any time, and could put the whole account at risk. Off unless you run this.
#
#   docs/deploy/set-claude-subscription.sh on /path/to/file-holding-the-setup-token   [--force]
#   docs/deploy/set-claude-subscription.sh off
#   docs/deploy/set-claude-subscription.sh status
#
# The token comes from `claude setup-token` (run where you have a browser), saved to a file (chmod 600, outside the repo) so it never
# appears in a command line or shell history, and is never printed. It goes only into the runner's own env file, mode preserved, and
# the runner's ledger proxy swaps it in for the run's key — no agent ever holds it. Before anything changes, ONE tiny call proves the
# token works with the official CLI; a bad token changes nothing. The runner is restarted, which orphans any run in flight, so the
# script refuses while a run is going unless --force.
set -euo pipefail
ACTION="${1:-}"; ENVFILE=/etc/business-os/runner.env; CLAUDE_BIN="${CLAUDE_BIN:-/opt/claude-agent/bin/claude}"
usage() { echo "usage: $0 on <token-file> [--force] | off | status" >&2; exit 1; }
runs_going() { sudo -n -u postgres psql -d maludb_os -Atc "SELECT count(*) FROM agent_runs WHERE status = 'running'" 2>/dev/null || echo "?"; }

restart_runner() {
  sudo systemctl restart maludb-os-agent-runner; sleep 3
  systemctl is-active --quiet maludb-os-agent-runner || { echo "The runner did not come back — restore ~/env-backups/runner.env.$STAMP" >&2; exit 1; }
}
backup_env() {
  STAMP=$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$HOME/env-backups"; umask 077
  sudo cat "$ENVFILE" > "$HOME/env-backups/runner.env.$STAMP"
}
rewrite_env() {   # rewrite_env <extra lines file or empty> — drops the two subscription lines, appends what it is given
  TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
  sudo cat "$ENVFILE" | grep -vE '^(CLAUDE_CODE_OAUTH_TOKEN|ALLOW_CLAUDE_SUBSCRIPTION)=' > "$TMP" || true
  [ -n "${1:-}" ] && cat "$1" >> "$TMP"
  sudo install -m "$(sudo stat -c %a "$ENVFILE")" -o "$(sudo stat -c %U "$ENVFILE")" -g "$(sudo stat -c %G "$ENVFILE")" "$TMP" "$ENVFILE"
}

case "$ACTION" in
  status)
    if sudo grep -q '^ALLOW_CLAUDE_SUBSCRIPTION=1$' "$ENVFILE" && sudo grep -q '^CLAUDE_CODE_OAUTH_TOKEN=.' "$ENVFILE"; then echo "ON (switch and token present in $ENVFILE)"; else echo "OFF"; fi ;;
  off)
    [ "$(runs_going)" = "0" ] || [ "${2:-}" = "--force" ] || { echo "A run is in flight (or the count could not be read); restarting the runner would orphan it. Wait, or pass --force." >&2; exit 1; }
    backup_env; rewrite_env ""; restart_runner
    echo "Claude subscription use is OFF; token and switch removed; runner restarted. Agents on a Max-plan model are refused by name until it is switched on. Backup: ~/env-backups/runner.env.$STAMP" ;;
  on)
    KEYFILE="${2:-}"; FORCE="${3:-}"
    [ -r "$KEYFILE" ] || { echo "Cannot read '$KEYFILE'." >&2; usage; }
    TOKEN="$(tr -d '[:space:]' < "$KEYFILE")"
    case "$TOKEN" in sk-ant-oat*) ;; *) echo "That file does not hold a Claude setup-token (it should start sk-ant-oat…)." >&2; exit 1 ;; esac
    [ ${#TOKEN} -ge 40 ] || { echo "That token is too short." >&2; exit 1; }
    [ "$(runs_going)" = "0" ] || [ "$FORCE" = "--force" ] || { echo "A run is in flight (or the count could not be read); restarting the runner would orphan it. Wait, or pass --force." >&2; exit 1; }
    # One tiny call, official CLI, scratch dirs, an emptied environment — proves the token BEFORE anything is changed.
    SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT; mkdir -p "$SCRATCH/home" "$SCRATCH/config" "$SCRATCH/cwd"
    OUT=$(cd "$SCRATCH/cwd" && env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$SCRATCH/home" CLAUDE_CONFIG_DIR="$SCRATCH/config" CLAUDE_CODE_OAUTH_TOKEN="$TOKEN" \
          DISABLE_TELEMETRY=1 DISABLE_AUTOUPDATER=1 timeout 90 "$CLAUDE_BIN" -p "Reply with the single word OK" --output-format json --max-turns 1 --tools "" </dev/null 2>&1 || true)
    echo "$OUT" | grep -q '"is_error":false' || { echo "Claude did not accept that token (the official CLI's test call failed). Nothing was changed." >&2; exit 1; }
    backup_env
    LINES=$(mktemp); printf 'ALLOW_CLAUDE_SUBSCRIPTION=1\nCLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TOKEN" > "$LINES"
    rewrite_env "$LINES"; rm -f "$LINES"
    restart_runner
    echo "Claude subscription use is ON: switch and token installed, runner restarted. Max-plan models ('… · Max plan') can now be hired onto and run, one run at a time. Delete $KEYFILE now. Backup: ~/env-backups/runner.env.$STAMP" ;;
  *) usage ;;
esac
