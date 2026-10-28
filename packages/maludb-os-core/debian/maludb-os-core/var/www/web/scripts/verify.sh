#!/usr/bin/env bash
# verify.sh <member-id> [--shots dir] <path>...  — throwaway PHP session for that member, removed afterwards.
# verify.sh <member-id> --probe <script.mjs> [args…] — the same session, handed to an interaction probe
#   (the script gets the session id as its first argument).
set -uo pipefail
cd "$(dirname "$0")/.."
MEMBER="$1"; shift
SP=/var/lib/php/sessions; SID="verify$(openssl rand -hex 12)"
printf 'member_id|i:%s;member_role|s:6:"member";csrf_token|s:8:"fixtoken";' "$MEMBER" | sudo -n -u www-data tee "$SP/sess_$SID" >/dev/null
trap 'sudo -n -u www-data rm -f "$SP/sess_$SID"' EXIT
if [ "${1:-}" = "--probe" ]; then PROBE="$2"; shift 2; timeout 600 node "$PROBE" "$SID" "$@"; exit $?; fi
timeout 600 node scripts/verify.mjs "$SID" "$@"
