#!/bin/bash
# set-provider-key.sh: give the office a provider's API key without the key ever appearing in a command
# line, a transcript or a log. Run it YOURSELF in a terminal: it prompts for the key with echo off. A
# coding agent cannot answer the prompt, which is the point; it can run --status afterwards.
#
#   sudo set-provider-key.sh anthropic|openrouter|openai|deepseek|moonshot|fireworks    -> /etc/business-os/runner.env, restart the agent runner
#   sudo set-provider-key.sh malumail [--mail-from no-reply@example.com]                 -> /var/www/config/.env, restart maludb-os-web
#   sudo set-provider-key.sh <provider> --from-file /path/to/key-file                     read the key from a mode-600 file instead of the prompt
#   set-provider-key.sh --status                                                          which keys are set (never their values); the runner's harnesses
#
# The env file keeps its owner and mode; a backup (mode 600) goes beside it. For providers with a public
# model listing the key is probed before anything is written; Anthropic, OpenRouter and MaluMail are
# checked after the restart through the runner's /health or the service's state.
. "$(dirname "$(readlink -f "$0")")/lib.sh"

status() {
  local f
  say "## provider keys (set / not set; values are never shown)"
  for f in "$RUNNER_ENV" "$KERNEL_ENV"; do
    if [ ! -r "$f" ]; then say "$f: not readable as $(id -un) (run with sudo for the full picture)"; continue; fi
    for k in ANTHROPIC_API_KEY OPENROUTER_API_KEY OPENAI_API_KEY DEEPSEEK_API_KEY MOONSHOT_API_KEY FIREWORKS_API_KEY MALUMAIL_API_KEY MAIL_FROM; do
      v=$(grep -E "^$k=" "$f" 2>/dev/null | head -1 | cut -d= -f2- || true)
      [ -n "$v" ] || continue
      if [ "$k" = MAIL_FROM ]; then say "$(basename "$f"): $k=$v"; else say "$(basename "$f"): $k set"; fi
    done
  done
  say "## the agent runner"
  if out=$(curl -s -m 5 http://127.0.0.1:8815/health 2>/dev/null) && [ -n "$out" ]; then
    python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print("runner ok:", d.get("ok"), "harnesses:", d.get("harnesses"))' <<<"$out" 2>/dev/null || say "runner answered: $out"
  else say "runner /health not answering (systemctl status maludb-os-agent-runner)"; fi
}
[ "${1:-}" = "--status" ] && { status; exit 0; }
PROVIDER="${1:-}"; shift || true
[ -n "$PROVIDER" ] || die "usage: set-provider-key.sh <anthropic|openrouter|openai|deepseek|moonshot|fireworks|malumail> [--from-file F] [--mail-from ADDR] | --status"
need_root "$PROVIDER" "$@"
FROM=""; MAILFROM=""
while [ $# -gt 0 ]; do case "$1" in --from-file) FROM="$2"; shift 2;; --mail-from) MAILFROM="$2"; shift 2;; *) die "unknown argument $1";; esac; done
PROBE=""; UNIT=maludb-os-agent-runner; FILE="$RUNNER_ENV"
case "$PROVIDER" in
  anthropic)  VAR=ANTHROPIC_API_KEY ;;
  openrouter) VAR=OPENROUTER_API_KEY; PROBE=https://openrouter.ai/api/v1/models ;;
  openai)     VAR=OPENAI_API_KEY;     PROBE=https://api.openai.com/v1/models ;;
  deepseek)   VAR=DEEPSEEK_API_KEY;   PROBE=https://api.deepseek.com/models ;;
  moonshot)   VAR=MOONSHOT_API_KEY;   PROBE=https://api.moonshot.ai/v1/models ;;
  fireworks)  VAR=FIREWORKS_API_KEY;  PROBE=https://api.fireworks.ai/inference/v1/models ;;
  malumail)   VAR=MALUMAIL_API_KEY; UNIT=maludb-os-web; FILE="$KERNEL_ENV" ;;
  *) die "unknown provider '$PROVIDER'" ;;
esac
[ -f "$FILE" ] || die "$FILE does not exist: the kernel is not provisioned yet (provision.sh first)"
if [ -n "$FROM" ]; then
  [ -r "$FROM" ] || die "cannot read $FROM"
  KEY=$(tr -d '[:space:]' < "$FROM")
else
  [ -t 0 ] || [ -r /dev/tty ] || die "no terminal to prompt on. Run this script yourself in a terminal (sudo $(readlink -f "$0") $PROVIDER), or give --from-file."
  printf 'Paste the %s key for %s (not echoed), then Enter: ' "$VAR" "$PROVIDER" > /dev/tty
  IFS= read -rs KEY < /dev/tty; printf '\n' > /dev/tty
  KEY=$(printf '%s' "$KEY" | tr -d '[:space:]')
fi
[ ${#KEY} -ge 20 ] || die "that is not an API key (too short). Nothing changed."
if [ -n "$PROBE" ]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 -H "Authorization: Bearer $KEY" "$PROBE" || echo 000)
  [ "$code" = 200 ] || die "$PROVIDER refused the key (HTTP $code on its model listing). Nothing changed."
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
cp -a "$FILE" "$FILE.before-office-setup-$stamp"; chmod 600 "$FILE.before-office-setup-$stamp"
KEY="$KEY" VAR="$VAR" MAILFROM="$MAILFROM" python3 - "$FILE" <<'PY'
import os, sys
path = sys.argv[1]; key, var, mailfrom = os.environ["KEY"], os.environ["VAR"], os.environ.get("MAILFROM", "")
lines = open(path).read().split("\n")
def put(k, v):
    global lines
    done = False; out = []
    for l in lines:
        s = l.lstrip()
        if (s.startswith(k + "=") or (s.startswith("#") and s.lstrip("# ").startswith(k + "="))) and not done:
            out.append(f"{k}={v}"); done = True
        elif s.startswith(k + "="):
            continue
        else:
            out.append(l)
    if not done:
        while out and out[-1] == "": out.pop()
        out.append(f"{k}={v}")
    lines = out
put(var, key)
if mailfrom: put("MAIL_FROM", mailfrom)
st = os.stat(path)
with open(os.open(path, os.O_WRONLY | os.O_TRUNC, st.st_mode & 0o777), "w") as fh:   # same inode: owner and mode kept
    fh.write("\n".join(lines).rstrip("\n") + "\n")
PY
unset KEY
systemctl restart "$UNIT"; sleep 3
systemctl is-active --quiet "$UNIT" || die "$UNIT did not come back; restore $FILE.before-office-setup-$stamp and inspect journalctl -u $UNIT"
say "$VAR set in $FILE (backup $FILE.before-office-setup-$stamp); $UNIT restarted"
case "$PROVIDER" in
  anthropic|openrouter) for _ in 1 2 3 4 5; do out=$(curl -s -m 5 http://127.0.0.1:8815/health 2>/dev/null) && [ -n "$out" ] && break; sleep 2; done
    [ -n "${out:-}" ] && python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print("runner harnesses:", d.get("harnesses"))' <<<"$out" || note "runner /health not answering yet; check set-provider-key.sh --status in a moment";;
  malumail) say "MaluMail key stored; MAIL_FROM is ${MAILFROM:-unchanged}. Send a test invitation from os.<domain> to confirm.";;
  openai) note "an OpenAI key can also serve as MaluDB's embedding model: sudo -u www-data php /var/www/bin/maludb_set_embedder.php --key-file <file> (before memory accumulates).";;
esac
