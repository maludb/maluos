"""maluos-estated: the node's heartbeat (python3 -m maluos_estate, as the system user maluos-estate).

While /etc/maluos/estate.yaml exists: a heartbeat every heartbeat_s with `presence: online` and the facts, the
full report with it every report_s (and with the first one); the outcome in /var/lib/maluos/estate/state.json.
401 or 410 from the office: the node was retired or its token revoked; the daemon keeps trying every
3 × heartbeat_s and `maluctl estate status` says why. Network errors retry at 10 s, 30 s, 60 s, then heartbeat_s.
SIGTERM (shutdown, `maluctl estate leave`, systemctl stop): one `presence: offline`, then exit.
"""
import os, signal, sys, threading, time

sys.path.insert(0, "/usr/lib/maluos")
from maluos_estate import client as C, report as R

LADDER = (10, 30, 60)


def log(msg):
    sys.stderr.write(f"maluos-estated: {msg}\n"); sys.stderr.flush()


def main(argv=None):
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    def pause(seconds):
        """Sleep in short slices: a signal interrupts time.sleep and the handler sets `stop`."""
        end = time.time() + seconds
        while not stop.is_set() and time.time() < end:
            time.sleep(min(0.5, max(0.0, end - time.time())))
    tok, fails, last_report, last_conf = None, 0, 0.0, None
    while not stop.is_set():
        conf = C.read_conf()
        if not conf:
            log("no enrolment (/etc/maluos/estate.yaml): nothing to do"); return 0
        if conf.get("url") != (last_conf or {}).get("url"):
            tok, last_report = None, 0.0
        last_conf = conf
        hb_s = int(conf.get("heartbeat_s") or 60); rep_s = int(conf.get("report_s") or 300)
        if tok is None:
            try:
                tok = C.token(conf)
            except Exception as e:
                fails += 1
                C.write_state({"ts": C.utc(), "ok": False, "presence": "online", "revoked": False, "node": None,
                               "error": f"the node token is not readable from the vault: {e.__class__.__name__}: {str(e)[:120]}"})
                log(f"token: {e.__class__.__name__}: {str(e)[:120]}")
                pause(LADDER[min(fails, len(LADDER)) - 1]); continue
        with_report = time.time() - last_report >= rep_s
        rep = None
        if with_report:
            try:
                rep = R.report()
            except Exception as e:
                log(f"report: {e.__class__.__name__}: {str(e)[:120]}")
        res = C.heartbeat(conf, tok, "online", rep)
        if res["ok"]:
            fails = 0
            if rep is not None:
                last_report = time.time(); res["last_report_at"] = res["ts"]
            else:
                prev = C.read_state() or {}
                res["last_report_at"] = prev.get("last_report_at")
            hb_s = int(res.get("heartbeat_s") or hb_s); rep_s = int(res.get("report_s") or rep_s)
            C.write_state(res)
            pause(hb_s)
        elif res["revoked"]:
            C.write_state(res)
            log(f"retired or revoked: {res['error']}")
            pause(3 * hb_s)
        else:
            fails += 1
            if res["error"] and res["error"].startswith("401"):
                tok = None
            C.write_state(res)
            log(f"heartbeat failed ({fails}): {res['error']}")
            pause(LADDER[fails - 1] if fails <= len(LADDER) else hb_s)
    conf = C.read_conf()
    if conf and tok:
        res = C.heartbeat(conf, tok, "offline", timeout=8)
        log("said offline" if res["ok"] else f"offline heartbeat failed: {res['error']}")
        res["last_report_at"] = (C.read_state() or {}).get("last_report_at")
        C.write_state(res)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
