#!/bin/bash
# The forked System Monitor's MaluOS tabs (Phase 13 G1: GPUs; G5: MaluOS Network, Queue) on this host,
# without a VM: the binary from a meson build (or the installed /usr/bin/gnome-system-monitor), a fake
# com.maluos.Session on a private session bus (tests/lib/fake_session.py), Xvfb for a display,
# `--maluos-self-test` four times (two GPUs with a node, a paired node and a queue; no GPU on a VM
# with an empty queue; an enrolled desk whose office publishes the estate; a user who is not an
# operator), then the session absent (the self-test must fail cleanly).
#   usage: tests/system-monitor-local-test.sh [BINARY]       default: build/gsm/src/gnome-system-monitor
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN=${1:-$ROOT/build/gsm/src/gnome-system-monitor}
fail=0
ok()  { echo "  ok   $*"; }
bad() { fail=$((fail+1)); echo "  FAIL $*"; }
for t in xvfb-run dbus-run-session; do command -v $t >/dev/null || { echo "needs $t"; exit 2; }; done
[ -x "$BIN" ] || { echo "no binary at $BIN (meson setup build/gsm packages/maluos-system-monitor && ninja -C build/gsm)"; exit 2; }
python3 -c "import gi" 2>/dev/null || { echo "needs python3-gi"; exit 2; }
# the gschema must be compiled where the binary looks: the build tree's data dir is not installed, so point GSETTINGS_SCHEMA_DIR at it
SCHEMAS=$(mktemp -d)
if [ -d "$(dirname "$BIN")/../share/glib-2.0/schemas" ]; then   # an unpacked .deb (dpkg-deb -x): the installed layout
    cp "$(dirname "$BIN")"/../share/glib-2.0/schemas/org.gnome.gnome-system-monitor.* "$SCHEMAS"/
else                                                            # a meson build tree: the configured files beside the binary
    cp "$(dirname "$BIN")"/org.gnome.gnome-system-monitor.gschema.xml "$(dirname "$BIN")"/org.gnome.gnome-system-monitor.enums.xml "$SCHEMAS"/ 2>/dev/null
fi
glib-compile-schemas "$SCHEMAS" 2>/dev/null
export GSETTINGS_SCHEMA_DIR=$SCHEMAS GSETTINGS_BACKEND=memory GDK_BACKEND=x11 LANG=C.UTF-8

run_case() {   # name, fake-session args, expected substring
    local name=$1 args=$2 expect=$3 ready out
    ready=$(mktemp -u)
    out=$(dbus-run-session -- bash -c "
        python3 '$ROOT/tests/lib/fake_session.py' $args --ready '$ready' & fs=\$!
        for i in \$(seq 1 50); do [ -f '$ready' ] && break; sleep 0.1; done
        timeout 60 xvfb-run -a -s '-screen 0 1280x800x24' '$BIN' --maluos-self-test 2>&1; rc=\$?
        kill \$fs 2>/dev/null; exit \$rc")
    rc=$?
    rm -f "$ready"
    if [ $rc = 0 ] && echo "$out" | grep -q -- "$expect"; then ok "$name: $(echo "$out" | grep 'self-test' | tail -1)"; else bad "$name (rc $rc): $(echo "$out" | grep -v '^$' | tail -4 | tr '\n' ' ')"; fi
}
echo "== $BIN"
run_case "two GPUs, share on; a node with 2 lanes, 1 paired, 2 keys, exposed; 3 jobs" "" \
    "self-test ok: GPUs: session reachable, 2 gpus, chassis desktop, rule opt-in, share on, gateway ok; Network: node fake-desk, 2 lanes, 1 paired, 2 keys, exposed; Queue: 3 jobs (1 running, 2 queued) in 2 lanes"
run_case "no GPU on a VM; the node on its socket only; an empty queue" "--no-gpu" \
    "self-test ok: GPUs: session reachable, 0 gpus, chassis vm, rule always, share off, gateway ok; Network: node fake-desk, 2 lanes, 1 paired, 2 keys, socket only; Queue: 0 jobs (0 running, 0 queued) in 2 lanes"
run_case "an enrolled desk whose office publishes the estate: two nodes (one offline), one open alert, two estate backends (one not shared) on the Network tab" "--no-gpu --estate" \
    "self-test ok: GPUs: session reachable, 0 gpus, chassis vm, rule always, share off, gateway ok; Network: node fake-desk, 2 lanes, 1 paired, 2 keys, socket only, estate 2 nodes (1 online, 1 alert), 2 estate backends (scheduler); Queue: 0 jobs (0 running, 0 queued) in 2 lanes"
run_case "not an operator: the GPUs tab works, the Network and Queue tabs say so" "--not-operator" \
    "self-test ok: GPUs: session reachable, 2 gpus, chassis desktop, rule opt-in, share on, gateway ok; Network: not an operator; Queue: forbidden (not an operator)"
out=$(dbus-run-session -- timeout 60 xvfb-run -a -s '-screen 0 1280x800x24' "$BIN" --maluos-self-test 2>&1); rc=$?
if [ $rc = 1 ] && echo "$out" | grep -q "self-test FAIL: the MaluOS session service did not answer"; then ok "no session service: the self-test fails cleanly (exit 1) and the tab stays hidden"; else bad "no session (rc $rc): $(echo "$out" | tail -3 | tr '\n' ' ')"; fi
out=$(timeout 60 xvfb-run -a -s "-screen 0 640x480x24" "$BIN" --version 2>&1); echo "$out" | grep -q "49.1" && ok "--version: $out" || bad "--version: $out"
rm -rf "$SCHEMAS"
echo "== $fail failures"; exit $((fail > 0))
