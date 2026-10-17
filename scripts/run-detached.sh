#!/bin/bash
# Run a long build or test as a transient systemd unit, independent of any
# terminal, SSH session or Claude Code session. Output goes to
# build/logs/<name>.log; the unit is removed when it exits (--collect).
#
#   scripts/run-detached.sh <name> <command> [args...]
#   scripts/run-detached.sh rootfs sudo image/build-rootfs.sh
#   scripts/run-detached.sh qcow2-uefi tests/qcow2-boot-test.sh build/image/maluos-server-26.04-amd64.qcow2 --uefi
#
# Then: scripts/jobs.sh            (list running jobs)
#       scripts/jobs.sh <name>     (status + tail of its log)
#       scripts/jobs.sh stop <name>
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ $# -ge 2 ] || { sed -n '2,13p' "$0"; exit 2; }
NAME=$1; shift
LOGDIR=$ROOT/build/logs; mkdir -p "$LOGDIR"
LOG=$LOGDIR/$NAME.log
UNIT=maluos-$NAME
if [ "$1" = sudo ]; then shift; AS_ROOT=1; else AS_ROOT=0; fi
# Resolve a relative script path against the repo so --same-dir is not needed.
CMD=$1; shift
case "$CMD" in /*|*/*) [ -x "$ROOT/$CMD" ] && CMD=$ROOT/$CMD ;; esac
: > "$LOG"
props=(--unit="$UNIT" --description="MaluOS job $NAME" --collect --quiet
       --working-directory="$ROOT"
       -p StandardOutput=append:"$LOG" -p StandardError=append:"$LOG"
       --setenv=HOME="$HOME" --setenv=SUDO_USER="${SUDO_USER:-$(id -un)}")
if [ $AS_ROOT = 1 ]; then
    sudo -n systemd-run "${props[@]}" -- "$CMD" "$@"
else
    sudo -n systemd-run "${props[@]}" --uid="$(id -u)" --gid="$(id -g)" -- "$CMD" "$@"
fi
echo "started $UNIT -> $LOG"
