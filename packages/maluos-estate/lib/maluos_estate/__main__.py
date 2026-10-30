"""maluos-estated: the node's heartbeat (python3 -m maluos_estate, as the system user maluos-estate).

While /etc/maluos/estate.yaml exists: a heartbeat every heartbeat_s with `presence: online` and the facts, the
full report with it every report_s (and with the first one); the outcome in /var/lib/maluos/estate/state.json.
The report is made on a worker thread: a heartbeat waits for it at most half the interval (15 s at most), so a
slow `maluctl update status` or systemctl never delays presence past the office's three-heartbeat sweep; a report
that finishes later goes with a heartbeat of its own at once.
401 or 410 from the office: the node was retired or its token revoked; the daemon keeps trying every
3 × heartbeat_s and `maluctl estate status` says why. Network errors retry at 10 s, 30 s, 60 s, then heartbeat_s.
SIGTERM (shutdown, `maluctl estate leave`, systemctl stop): one `presence: offline`, then exit.
"""
import json, os, signal, subprocess, sys, threading, time

sys.path.insert(0, "/usr/lib/maluos")
from maluos_estate import client as C, report as R

LADDER = (10, 30, 60)
KEYS_EVERY = 300          # the directory's keys are re-read this often (and at once after a bad signature)
INFERENCE_HINT = os.environ.get("MALUOS_ESTATE_INFERENCE_HINT", "/run/maluos/estate/inference-refresh")   # slice 3: `maluctl estate inference --refresh` asks the daemon too
TASK_WAIT_S = 100         # how long a task is waited for before it is reported running and followed up
TASK_MAX_S = 1800


class Inbox:
    """Phase 13 slice 2 (docs/phase13-slice2-delegation.md): this node's inbox at the office, long-polled on its own
    thread. A task is run through the agent's socket with its envelope (the agent verifies it and applies its
    policy); the result, with its provenance, goes back; an action runs only if /etc/maluos/estate.yaml allows it.
    The directory's keys are cached in /run/maluos/estate/keys.json for the agents."""

    def __init__(self, stop, log):
        self.stop, self.log = stop, log
        self.conf, self.tok = None, None
        self.keys_at = 0.0
        self.running = {}          # item id -> thread
        self.state = {"polls": 0, "items": 0, "last_poll_at": None, "last_item_at": None, "error": None, "keys_at": None}

    def set(self, conf, tok):
        self.conf, self.tok = conf, tok

    def node_ref(self):
        n = (self.conf or {}).get("node") or {}
        return f"{n.get('kind')}:{n.get('id')}"

    def refresh_keys(self):
        try:
            from maluos_estate import envelope as E
            st, r = C.keys(self.conf, self.tok)
            if st == 200:
                E.Keys(C.KEYS_CACHE).save(r); self.keys_at = time.time(); self.state["keys_at"] = C.utc()
            else:
                self.log(f"keys: {st} {r.get('error') or ''}: {r.get('message') or ''}")
        except Exception as e:
            self.log(f"keys: {e.__class__.__name__}: {str(e)[:120]}")

    def loop(self):
        while not self.stop.is_set():
            if not self.conf or not self.tok or not (self.conf.get("endpoints") or {}).get("inbox"):
                time.sleep(2); continue
            if time.time() - self.keys_at > KEYS_EVERY:
                self.refresh_keys()
            try:
                st, r = C.inbox(self.conf, self.tok, wait=25)
                self.state["polls"] += 1; self.state["last_poll_at"] = C.utc()
                if st != 200:
                    self.state["error"] = f"{st} {r.get('error') or ''}: {r.get('message') or ''}"
                    self.log(f"inbox: {self.state['error']}"); time.sleep(10 if st in (401, 410) else 5); continue
                self.state["error"] = None
                for item in r.get("items") or []:
                    if item.get("id") in self.running and self.running[item["id"]].is_alive():
                        continue
                    self.state["items"] += 1; self.state["last_item_at"] = C.utc()
                    t = threading.Thread(target=self.run_item, args=(item,), daemon=True); self.running[item["id"]] = t; t.start()
                for k in [k for k, t in self.running.items() if not t.is_alive()]:
                    self.running.pop(k, None)
            except Exception as e:
                self.state["error"] = f"{e.__class__.__name__}: {str(e)[:120]}"
                self.log(f"inbox: {self.state['error']}"); time.sleep(5)

    def post(self, item_id, body):
        for attempt in range(3):
            try:
                st, r = C.inbox_result(self.conf, self.tok, item_id, body)
                if st == 200:
                    return True
                self.log(f"result {item_id}: {st} {r.get('error') or ''}: {r.get('message') or ''}")
                if st in (404, 401, 410):
                    return False
            except Exception as e:
                self.log(f"result {item_id}: {e.__class__.__name__}: {str(e)[:120]}")
            time.sleep(3)
        return False

    def run_item(self, item):
        kind = item.get("kind")
        try:
            if kind == "task":
                self.run_task(item)
            elif kind == "action":
                self.run_action(item)
            else:
                self.post(item["id"], {"refused": "unknown_item", "result": {"error": f"item kind {kind!r} is not known here"}})
        except Exception as e:
            self.log(f"item {item.get('id')}: {e.__class__.__name__}: {str(e)[:160]}")
            self.post(item["id"], {"result": {"state": "failed", "error": f"{e.__class__.__name__}: {str(e)[:200]}"}})

    def run_task(self, item):
        import maluos_agent_tasks as T
        name = item.get("agent") or ""
        env = item.get("envelope") or {}
        parts = ((item.get("message") or {}).get("parts")) or []
        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type", "text") == "text").strip()
        c = T.Client.local(name, timeout=TASK_WAIT_S + 20)
        if not c.available:
            self.log(f"task {item['id']} for {name}: no task socket (the agent is not running)")
            self.post(item["id"], {"refused": "agent_unavailable", "result": {"error": f"agent {name} is not running or serves no task interface"}}); return
        try:
            if item.get("answer"):
                t = c.resume(item["id"], item["answer"], wait=True, timeout=TASK_WAIT_S)
            else:
                t = c.send(text, wait=True, timeout=TASK_WAIT_S, envelope=env, task_id=item["id"])
        except T.TaskError as e:
            reason = e.reason or ("not_waiting" if e.code == -32002 else "failed")
            self.log(f"task {item['id']} for {name}: refused {reason}: {e.message}")
            self.post(item["id"], {"refused": reason, "result": {"error": e.message}}); return
        if t.get("state") in ("submitted", "working"):
            self.post(item["id"], {"result": {"state": "running"}})
            deadline = time.time() + TASK_MAX_S
            while t.get("state") in ("submitted", "working") and time.time() < deadline and not self.stop.is_set():
                time.sleep(2)
                try:
                    t = c.get(item["id"])
                except T.TaskError as e:
                    t = dict(t, state="failed", error=e.message); break
            if t.get("state") in ("submitted", "working"):
                t = dict(t, state="failed", error=f"no answer within {TASK_MAX_S} s")
        prov = t.get("provenance")
        if isinstance(prov, dict) and not prov.get("node"):
            prov["node"] = self.node_ref()
        self.post(item["id"], {"result": {k: t.get(k) for k in ("id", "state", "output", "error", "provenance", "usage", "ask", "answer") if k in t}})

    def run_action(self, item):
        action, agent = item.get("action"), item.get("agent")
        allowed = C.allowed_actions(self.conf)
        if action not in allowed:
            self.log(f"action {item['id']} {action}: not allowed here (actions.allow: {', '.join(allowed)})")
            self.post(item["id"], {"refused": "not_allowed", "result": {"ok": False, "error": f"{action} is not in this node's actions.allow"}}); return
        verb = {"restart_agent": "restart", "start_agent": "start", "stop_agent": "stop"}.get(action)
        if verb:
            if not agent or not (os.path.exists(f"{C.AGENTS_DIR}/{agent}.env") or os.path.exists(f"{C.AGENTS_DIR}/{agent}.manifest.yaml")):
                self.post(item["id"], {"refused": "no_agent", "result": {"ok": False, "error": f"no agent {agent!r} on this node"}}); return
            cmd = ["systemctl", verb, f"maluos-agent@{agent}.service"]
        elif action == "apply_updates":
            cmd = ["systemctl", "start", "maluos-estate-updates.service"]
        elif action == "reboot":
            self.post(item["id"], {"result": {"ok": True, "output": "rebooting"}})
            subprocess.run(["systemctl", "reboot"], capture_output=True, text=True, timeout=30); return
        else:
            self.post(item["id"], {"refused": "unknown_action", "result": {"ok": False, "error": action}}); return
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900 if action == "apply_updates" else 120)
        out = (r.stdout or "").strip()[-2000:]; err = (r.stderr or "").strip()[-400:]
        self.log(f"action {item['id']} {action}{' ' + agent if agent else ''}: {'ok' if r.returncode == 0 else 'failed'} {err}")
        self.post(item["id"], {"result": {"ok": r.returncode == 0, "output": out or f"{' '.join(cmd)}: exit {r.returncode}", "error": err or None}})


def log(msg):
    sys.stderr.write(f"maluos-estated: {msg}\n"); sys.stderr.flush()


def main(argv=None):
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    made = threading.Event()                  # a report is ready on `ready`
    ready = []                                # the worker's report (or None when it failed), at most one

    def pause(seconds):
        """Sleep in short slices: a signal interrupts time.sleep and the handler sets `stop`; a report that
        became ready meanwhile ends the pause so it goes to the office at once."""
        end = time.time() + seconds
        while not stop.is_set() and not made.is_set() and time.time() < end:
            if os.path.exists(C.AGENTS_HINT):
                return                        # slice 2: an agent was created, removed or re-policied: register now
            time.sleep(min(0.5, max(0.0, end - time.time())))

    def make_report():
        try:
            ready.append(R.report())
        except Exception as e:
            log(f"report: {e.__class__.__name__}: {str(e)[:120]}"); ready.append(None)
        made.set()
    tok, fails, last_report, last_conf, worker = None, 0, 0.0, None, None
    inbox = Inbox(stop, log)
    threading.Thread(target=inbox.loop, daemon=True).start()
    manifests_due = True                      # slice 2: the agents are registered with the first heartbeat, each report, and after the hint
    inf_at, peers_at = 0.0, 0.0               # slice 3: when the backends and the peers caches were last written

    def inference_refresh(conf, tok, which):
        nonlocal inf_at, peers_at
        try:
            for name, (st, r) in C.refresh_inference(conf, tok, which).items():
                if st == 200:
                    if name == "backends":
                        inf_at = time.time()
                        log(f"inference: {len(r.get('backends') or [])} backend(s) published to this node (version {r.get('version')}; editions {', '.join(r.get('editions') or []) or 'none'})")
                    else:
                        peers_at = time.time()
                        log(f"inference: {len(r.get('peers') or [])} peer(s) may call this host (version {r.get('version')})")
                else:
                    log(f"inference {name}: {st} {r.get('error') or ''}: {r.get('message') or ''}")
        except Exception as e:
            log(f"inference: {e.__class__.__name__}: {str(e)[:120]}")
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
        if worker is None and time.time() - last_report >= rep_s:
            made.clear(); worker = threading.Thread(target=make_report, daemon=True); worker.start()
        if worker is not None:
            worker.join(timeout=min(hb_s / 2, 15))
            if not worker.is_alive():
                worker = None
        made.clear()                          # cleared before the take: a report made after it ends the pause
        rep = ready.pop() if ready else None  # None when it failed: the next heartbeat starts another
        if C.agents_hint_take():
            manifests_due = True
        agents = C.manifests() if (manifests_due or rep is not None) else None
        inference = C.gateway_inference()         # slice 3: what this host's gateway serves, its queue and its sharing switch
        res = C.heartbeat(conf, tok, "online", rep, agents=agents, inference=inference)
        if res["ok"]:
            fails = 0
            inbox.set(conf, tok)
            if agents is not None:
                manifests_due = False
            if res.get("overlay_changed"):
                C.overlay_hint()                  # slice 1b: the overlay service refreshes now
            # slice 3: the directory's backends (hourly, on inference_changed, on the hint) and the peers (every 5 min, on peers_changed)
            hinted = False
            try:
                os.remove(INFERENCE_HINT); hinted = True
            except OSError:
                pass
            which = []
            if (conf.get("endpoints") or {}).get("inference") and (res.get("inference_changed") or hinted or time.time() - inf_at > C.INFERENCE_REFRESH_S):
                which.append("backends")
            if (conf.get("endpoints") or {}).get("inference") and (res.get("peers_changed") or hinted or time.time() - peers_at > C.PEERS_REFRESH_S):
                which.append("peers")
            if which:
                inference_refresh(conf, tok, which)
            res["inference"] = {"sent": inference is not None, "backends_at": inf_at or None, "peers_at": peers_at or None, "editions": res.get("editions")}
            if rep is not None:
                last_report = time.time(); res["last_report_at"] = res["ts"]
            else:
                prev = C.read_state() or {}
                res["last_report_at"] = prev.get("last_report_at")
            hb_s = int(res.get("heartbeat_s") or hb_s); rep_s = int(res.get("report_s") or rep_s)
            res["inbox"] = dict(inbox.state)
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
