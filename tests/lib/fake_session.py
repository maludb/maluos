#!/usr/bin/python3
"""A fake com.maluos.Session on the session bus for the System Monitor's self-test (Phase 13 G1):
answers GetState with a fixture state (two GPUs, a gateway with a loaded model, no office), so the
GPUs tab can be exercised without the desktop session. Usage: fake_session.py [--no-gpu] [--ready FILE]
"""
import json, os, sys
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

XML = """<node><interface name="com.maluos.Session1">
  <method name="GetState"><arg type="s" name="json" direction="out"/></method>
  <method name="Refresh"/>
</interface></node>"""

GPUS = [{"vendor": "nvidia", "index": 0, "model": "NVIDIA GeForce RTX 5090", "uuid": "GPU-1", "pci": "01:00.0", "driver": "595.99.02",
         "vram_mb": 32768, "vram_used_mb": 21000, "busy_pct": 37, "temp_c": 61, "power_w": 310.5, "power_limit_w": 575.0, "compute": "12.0"},
        {"vendor": "amd", "index": 1, "model": "Navi 31 [Radeon RX 7900 XTX]", "uuid": None, "pci": "03:00.0", "driver": "amdgpu",
         "vram_mb": 24560, "vram_used_mb": 512, "busy_pct": 0, "temp_c": 41, "power_w": 18.0, "power_limit_w": None, "compute": None}]


def state(no_gpu):
    return {"version": "0.7.1", "ts": 0,
            "host": {"hostname": "fake-desk", "pretty_name": "MaluOS", "variant": "Desktop", "user": "me", "memory": None,
                     "gpus": [] if no_gpu else GPUS, "chassis": "vm" if no_gpu else "desktop", "contribution_rule": "always" if no_gpu else "opt-in"},
            "gateway": {"available": True, "ok": True, "version": "0.3.5", "uptime_s": 10,
                        "backends": [{"name": "ollama-local", "kind": "ollama_local", "healthy": True, "cloud": False, "enabled": True, "error": None, "loaded": ["qwen3:32b"]},
                                     {"name": "anthropic", "kind": "anthropic", "healthy": True, "cloud": True, "enabled": True, "error": None, "loaded": []}],
                        "queue": {"queued": 3, "running": 1}, "expected_wait_s": {}, "tiers": {},
                        "share": {"enabled": not no_gpu, "contribution": "always", "chassis": "vm" if no_gpu else "desktop",
                                  "rule": "always" if no_gpu else "opt-in", "configured": not no_gpu, "exposed": False}},
            "me": {}, "vault": {}, "agents": [], "alerts": [], "updates": {"available": False}, "office": {"enrolled": False}}


def main(argv):
    no_gpu = "--no-gpu" in argv
    ready = argv[argv.index("--ready") + 1] if "--ready" in argv else None
    loop = GLib.MainLoop()
    node = Gio.DBusNodeInfo.new_for_xml(XML)

    def on_call(conn, sender, path, iface, method, params, inv):
        if method == "GetState":
            inv.return_value(GLib.Variant("(s)", (json.dumps(state(no_gpu)),)))
        else:
            inv.return_value(None)

    def on_bus(conn, name):
        conn.register_object("/com/maluos/Session", node.interfaces[0], on_call, None, None)
        if ready:
            open(ready, "w").write("ready\n")
    Gio.bus_own_name(Gio.BusType.SESSION, "com.maluos.Session", Gio.BusNameOwnerFlags.NONE, on_bus, None, lambda c, n: sys.exit("name lost"))
    loop.run()


if __name__ == "__main__":
    main(sys.argv[1:])
