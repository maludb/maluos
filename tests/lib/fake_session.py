#!/usr/bin/python3
"""A fake com.maluos.Session on the session bus for the System Monitor's self-test (Phase 13 G1, G5):
answers GetState with a fixture state (two GPUs, a gateway with a loaded model, the node section with two
lanes, a paired node and two keys, no office) and NodeQueue with a fixture queue (three jobs), so the GPUs,
MaluOS Network and Queue tabs can be exercised without the desktop session.
Usage: fake_session.py [--no-gpu] [--not-operator] [--estate] [--ready FILE]
  --no-gpu        a VM: no GPU, chassis vm, an empty queue
  --not-operator  the user is not an operator of the gateway: no node section, NodeQueue is forbidden
  --estate        an enrolled desk whose office publishes the estate (Phase 13 slice 1): two nodes, one alert; two estate backends from the directory (slice 3)
"""
import json, os, sys
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

XML = """<node><interface name="com.maluos.Session1">
  <method name="GetState"><arg type="s" name="json" direction="out"/></method>
  <method name="NodeQueue"><arg type="s" name="json" direction="out"/></method>
  <method name="Refresh"/>
</interface></node>"""

GPUS = [{"vendor": "nvidia", "index": 0, "model": "NVIDIA GeForce RTX 5090", "uuid": "GPU-1", "pci": "01:00.0", "driver": "595.99.02",
         "vram_mb": 32768, "vram_used_mb": 21000, "busy_pct": 37, "temp_c": 61, "power_w": 310.5, "power_limit_w": 575.0, "compute": "12.0"},
        {"vendor": "amd", "index": 1, "model": "Navi 31 [Radeon RX 7900 XTX]", "uuid": None, "pci": "03:00.0", "driver": "amdgpu",
         "vram_mb": 24560, "vram_used_mb": 512, "busy_pct": 0, "temp_c": 41, "power_w": 18.0, "power_limit_w": None, "compute": None}]

LANES = {"ollama-local": {"kind": "local", "capacity": 2, "running": 1, "queued": 2, "paused": False, "resident": "qwen3:32b", "oldest_queued_ms": 3200, "healthy": True,
                          "classes": {"interactive": {"queued": 0, "expected_wait_ms": 0}, "agent": {"queued": 1, "expected_wait_ms": 4000}, "batch": {"queued": 1, "expected_wait_ms": 9000}}},
         "anthropic": {"kind": "cloud", "capacity": 8, "running": 0, "queued": 0, "paused": True, "resident": None, "oldest_queued_ms": 0, "healthy": True,
                       "classes": {"interactive": {"queued": 0, "expected_wait_ms": 0}, "agent": {"queued": 0, "expected_wait_ms": 0}, "batch": {"queued": 0, "expected_wait_ms": 0}}}}

QUEUE = [{"id": "c-1001", "lane": "ollama-local", "model": "qwen3:32b", "requested_model": "fast", "class": "interactive", "kind": "chat", "principal": "user:me",
          "key": None, "face": "openai", "mode": "sync", "state": "running", "waited_ms": None, "elapsed_ms": 2100, "expected_wait_ms": 0},
         {"id": "c-1002", "lane": "ollama-local", "model": "qwen3:32b", "requested_model": "qwen3:32b", "class": "agent", "kind": "chat", "principal": "agent:research",
          "key": None, "face": "ollama", "mode": "sync", "state": "queued", "waited_ms": 3200, "elapsed_ms": None, "expected_wait_ms": 4000},
         {"id": "c-1003", "lane": "ollama-local", "model": "qwen3:32b", "requested_model": "fast", "class": "batch", "kind": "embed", "principal": "key:desk-7",
          "key": "desk-7", "face": "anthropic", "mode": "async", "state": "queued", "waited_ms": 900, "elapsed_ms": None, "expected_wait_ms": 9000,
          "origin_request": "r-77"}]


def node(no_gpu, operator):
    if not operator:
        return {"available": False, "operator": False}
    return {"available": True, "operator": True, "name": "fake-desk", "id": "n-fake-0001", "version": "0.4.1", "api_version": 1, "uptime_s": 7300,
            "started_at": "2026-10-26T00:00:00Z", "last_manager_seen_at": None,
            "exposed": {"enabled": not no_gpu, "host": "0.0.0.0", "port": 11435},
            "share": {"enabled": not no_gpu, "contribution": "always", "chassis": "vm" if no_gpu else "desktop", "rule": "always" if no_gpu else "opt-in", "configured": not no_gpu, "exposed": not no_gpu},
            "machine": {"hostname": "fake-desk", "os": "MaluOS 26.04 LTS", "arch": "x86_64", "cpu_count": 16, "memory_total": 68719476736, "memory_available": 30000000000, "load_1m": 0.4,
                        "chassis": "vm" if no_gpu else "desktop"},
            "lanes": LANES, "counters": {"jobs": {"admitted": 120, "rejected": 2, "cancelled": 1, "completed": 117}, "async_jobs": {"submitted": 3, "done": 3}},
            "loaded": [{"name": "qwen3:32b", "backend": "ollama-local"}],
            "paired": [{"name": "gpu-1", "endpoint": "http://gpu-1.lan:11435", "healthy": True, "enabled": True, "error": None, "paired": True, "version": "0.4.1", "checked_at": 1,
                        "models": ["llama3.3:70b", "qwen3:32b"], "loaded": ["llama3.3:70b"]}],
            "keys": [{"id": 1, "name": "boot-manager", "kind": "node", "principal": "key:boot-manager", "class": None, "created_at": "2026-10-26T00:00:00", "expires_at": None, "revoked_at": None, "last_used_at": None},
                     {"id": 2, "name": "desk-7", "kind": "inference", "principal": "key:desk-7", "class": "batch", "created_at": "2026-10-26T00:00:00", "expires_at": None, "revoked_at": None, "last_used_at": "2026-10-26T01:00:00"}]}


ESTATE = {"available": True, "fetched_at": 1, "stale": False, "error": None,
          "nodes": [{"id": 57, "kind": "server", "name": "db-1", "hostname": "db-1", "presence": "online", "health": "warning", "summary": "1 agent failed · 3 updates pending (1 security)",
                     "last_seen_at": "2026-10-27T04:00:00Z", "last_report_at": "2026-10-27T03:59:00Z", "units": {"up": 4, "down": 0}, "agents": {"count": 1, "running": 0, "failed": 1},
                     "gateway": {"ok": True, "backends_healthy": 1, "backends": 1, "queued": 0, "running": 0}, "updates": {"pending_count": 3, "security_count": 1, "reboot_required": False},
                     "disk_max_pct": 63, "memory_available_pct": 33, "load1": 0.8},
                    {"id": 42, "kind": "desk", "name": "Ed's desk", "owner": "Edward Honour", "presence": "offline", "health": "offline", "summary": "offline",
                     "last_seen_at": "2026-10-27T01:00:00Z", "last_report_at": None, "units": None, "agents": None, "gateway": None, "updates": None,
                     "disk_max_pct": None, "memory_available_pct": None, "load1": None}],
          "alerts": [{"id": 301, "ts": "2026-10-27T03:59:00Z", "node_id": 57, "node": "db-1", "kind": "agent_down", "severity": "warning", "title": "agent helpdesk failed (3 restarts)", "cleared_at": None},
                     {"id": 299, "ts": "2026-10-27T02:00:00Z", "node_id": 57, "node": "db-1", "kind": "disk_full", "severity": "warning", "title": "disk / at 90 %", "cleared_at": "2026-10-27T03:30:00Z"}],
          "counts": {"nodes": 2, "online": 1, "offline": 1, "alerts": 1}}


def office(estate):
    if not estate:
        return {"enrolled": False}
    return {"enrolled": True, "url": "http://fake.office", "office": {"name": "Fake Office", "url": "http://fake.office"}, "surface": 1,
            "desk": {"id": 42, "name": "Ed's desk", "status": "active"}, "owner": {"principal": "user:me", "display_name": "Edward Honour"},
            "presence": "online", "ok": True, "revoked": False, "agents": [], "apps": None, "estate": ESTATE}


def state(no_gpu, operator, estate=False):
    return {"version": "0.9.0", "ts": 0,
            "host": {"hostname": "fake-desk", "pretty_name": "MaluOS", "variant": "Desktop", "user": "me", "memory": None,
                     "gpus": [] if no_gpu else GPUS, "chassis": "vm" if no_gpu else "desktop", "contribution_rule": "always" if no_gpu else "opt-in"},
            "gateway": {"available": True, "ok": True, "version": "0.4.1", "uptime_s": 10,
                        "backends": [{"name": "ollama-local", "kind": "ollama_local", "healthy": True, "cloud": False, "enabled": True, "error": None, "loaded": ["qwen3:32b"]},
                                     {"name": "anthropic", "kind": "anthropic", "healthy": True, "cloud": True, "enabled": True, "error": None, "loaded": []}],
                        "queue": {"queued": 0 if no_gpu else 2, "running": 0 if no_gpu else 1}, "expected_wait_s": {}, "tiers": {},
                        "share": {"enabled": not no_gpu, "contribution": "always", "chassis": "vm" if no_gpu else "desktop",
                                  "rule": "always" if no_gpu else "opt-in", "configured": not no_gpu, "exposed": False},
                        # Phase 13 slice 3: the rungs the estate's directory gave this gateway (with --estate)
                        "estate": {"self": "desk:41", "editions": ["scheduler"], "place": True, "source": "desk", "version": 7, "fetched_at": "2026-10-29T20:00:00Z",
                                   "backends": [{"name": "estate:gpu-1", "kind": "estate", "node": "inference:57", "label": "gpu-1", "display_name": "GPU 1", "endpoint": "http://100.100.0.2:11435",
                                                 "healthy": True, "enabled": True, "error": None, "remote": True, "estate": True, "models": ["qwen3:8b", "qwen3:32b"], "loaded": [], "class_max": "agent",
                                                 "classification_max": "internal", "priority": 10, "contribution": "always", "shared": True, "directory_wait_s": {"interactive": 1.2}, "directory_queue": {"queued": 0, "running": 1}},
                                                {"name": "estate:ed-s-laptop", "kind": "estate", "node": "desk:12", "label": "ed-s-laptop", "display_name": "Ed's laptop", "endpoint": "http://100.100.0.5:11435",
                                                 "healthy": False, "enabled": True, "error": "not_shared: its owner is at the keyboard", "remote": True, "estate": True, "models": ["qwen3:8b"], "loaded": [], "class_max": "interactive",
                                                 "classification_max": "internal", "priority": 0, "contribution": "idle", "shared": False, "directory_wait_s": {}, "directory_queue": {}}] if estate else [],
                                   "peers": 2 if estate else 0, "peers_version": 3}},
            "me": {"operator": operator}, "node": node(no_gpu, operator), "vault": {}, "agents": [], "alerts": [], "updates": {"available": False}, "office": office(estate)}


def queue(no_gpu, operator):
    if not operator:
        return {"ok": False, "error": "forbidden", "message": "the node API needs a node key or an operator on the socket", "status": 403, "queue": [], "lanes": {}}
    if no_gpu:
        lanes = {k: dict(v, running=0, queued=0, oldest_queued_ms=0, classes={c: {"queued": 0, "expected_wait_ms": 0} for c in v["classes"]}) for k, v in LANES.items()}
        return {"ok": True, "queue": [], "lanes": lanes, "ts": "2026-10-26T02:00:00.000Z"}
    return {"ok": True, "queue": QUEUE, "lanes": LANES, "ts": "2026-10-26T02:00:00.000Z"}


def main(argv):
    no_gpu = "--no-gpu" in argv
    operator = "--not-operator" not in argv
    estate = "--estate" in argv
    ready = argv[argv.index("--ready") + 1] if "--ready" in argv else None
    loop = GLib.MainLoop()
    node_info = Gio.DBusNodeInfo.new_for_xml(XML)

    def on_call(conn, sender, path, iface, method, params, inv):
        if method == "GetState":
            inv.return_value(GLib.Variant("(s)", (json.dumps(state(no_gpu, operator, estate)),)))
        elif method == "NodeQueue":
            inv.return_value(GLib.Variant("(s)", (json.dumps(queue(no_gpu, operator)),)))
        else:
            inv.return_value(None)

    def on_bus(conn, name):
        conn.register_object("/com/maluos/Session", node_info.interfaces[0], on_call, None, None)
        if ready:
            open(ready, "w").write("ready\n")
    Gio.bus_own_name(Gio.BusType.SESSION, "com.maluos.Session", Gio.BusNameOwnerFlags.NONE, on_bus, None, lambda c, n: sys.exit("name lost"))
    loop.run()


if __name__ == "__main__":
    main(sys.argv[1:])
