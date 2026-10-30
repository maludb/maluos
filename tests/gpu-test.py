#!/usr/bin/python3
"""The GPU reader's pure parts (Phase 13, shared GPUs, slice G1), no GPU, no root: nvidia-smi's CSV
through a fake runner, /sys/class/drm through a temporary tree (an amdgpu card with its numbers, a
virtual display adapter skipped, an Intel card with none), the chassis mapping and the sharing rule,
the gateway's share state resolution, and `maluctl gpu status --json` through the plugin.

  python3 tests/gpu-test.py
"""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "packages/maluos-firstboot/lib")
sys.path.insert(0, LIB)
import maluos_gpu  # noqa: E402

SMI = ("0, NVIDIA GeForce RTX 5090, GPU-abc, 00000000:01:00.0, 595.99.02, 32768, 21000, 37, 61, 310.50, 575.00, 12.0\n"
       "1, NVIDIA RTX A6000, GPU-def, 00000000:41:00.0, 595.99.02, 49140, 0, 0, 33, [N/A], 300.00, 8.6\n")


class FakeRun:
    def __init__(self, out="", rc=0, err="", reject_compute=False):
        self.out, self.rc, self.err, self.reject, self.calls = out, rc, err, reject_compute, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        class R: pass
        r = R()
        if self.reject and any("compute_cap" in a for a in argv):
            r.returncode, r.stdout, r.stderr = 1, "", 'Field "compute_cap" is not a valid field to query.'
            return r
        r.returncode, r.stdout, r.stderr = self.rc, self.out.replace(", 12.0", "").replace(", 8.6", "") if self.reject else self.out, self.err
        return r


class Nvidia(unittest.TestCase):
    def test_parses_csv(self):
        g = maluos_gpu.nvidia(run=FakeRun(SMI), smi="/fake/nvidia-smi")
        self.assertEqual(len(g), 2)
        a = g[0]
        self.assertEqual((a["vendor"], a["index"], a["model"], a["driver"]), ("nvidia", 0, "NVIDIA GeForce RTX 5090", "595.99.02"))
        self.assertEqual((a["vram_mb"], a["vram_used_mb"], a["busy_pct"], a["temp_c"]), (32768, 21000, 37, 61))
        self.assertEqual((a["power_w"], a["power_limit_w"], a["compute"], a["pci"]), (310.5, 575.0, "12.0", "01:00.0"))
        self.assertIsNone(g[1]["power_w"], "[N/A] reads as None")

    def test_old_smi_without_compute_cap(self):
        run = FakeRun(SMI, reject_compute=True)
        g = maluos_gpu.nvidia(run=run, smi="/fake/nvidia-smi")
        self.assertEqual(len(run.calls), 2, "retried without compute_cap")
        self.assertEqual(len(g), 2); self.assertIsNone(g[0]["compute"])

    def test_no_binary(self):
        os.environ.pop("MALUOS_NVIDIA_SMI", None)
        self.assertEqual(maluos_gpu.nvidia(run=FakeRun(SMI), smi=None if not maluos_gpu.nvidia_smi_path() else "/nonexistent/x") or [], [] if not maluos_gpu.nvidia_smi_path() else maluos_gpu.nvidia(run=FakeRun(SMI), smi="/nonexistent/x"))

    def test_driver_absent(self):
        self.assertEqual(maluos_gpu.nvidia(run=FakeRun("", rc=9, err="NVIDIA-SMI has failed"), smi="/fake/nvidia-smi"), [])


def put(path, value):
    with open(path, "w") as f:
        f.write(str(value) + "\n")


def sysfs_tree(base):
    def card(name, vendor, device, driver, extra=None, hwmon=None):
        d = os.path.join(base, name, "device"); os.makedirs(d)
        put(os.path.join(d, "vendor"), vendor); put(os.path.join(d, "device"), device)
        put(os.path.join(d, "uevent"), f"DRIVER={driver}\nPCI_SLOT_NAME=0000:03:00.0")
        for k, v in (extra or {}).items():
            put(os.path.join(d, k), v)
        if hwmon:
            h = os.path.join(d, "hwmon", "hwmon4"); os.makedirs(h)
            for k, v in hwmon.items():
                put(os.path.join(h, k), v)
    card("card0", "0x1234", "0x1111", "bochs-drm")                                             # QEMU: not a GPU
    card("card1", "0x1002", "0x744c", "amdgpu", {"mem_info_vram_total": 25753026560, "mem_info_vram_used": 536870912, "gpu_busy_percent": 12},
         {"temp1_input": 41000, "power1_average": 18000000, "power1_cap": 339000000})
    os.makedirs(os.path.join(base, "card1-DP-1"))                                              # a connector, skipped
    card("card2", "0x8086", "0x7d55", "xe")
    card("card3", "0x10de", "0x2b85", "nvidia")                                                # when nvidia-smi handled it, skipped


class Sysfs(unittest.TestCase):
    def test_tree(self):
        with tempfile.TemporaryDirectory() as d:
            sysfs_tree(d)
            g = maluos_gpu.sysfs(root=d, skip_nvidia=True)
            self.assertEqual([x["vendor"] for x in g], ["amd", "intel"])
            a = g[0]
            self.assertEqual((a["driver"], a["vram_mb"], a["vram_used_mb"], a["busy_pct"], a["temp_c"], a["power_w"], a["power_limit_w"]),
                             ("amdgpu", 24560, 512, 12, 41, 18.0, 339.0))
            self.assertTrue("7900" in a["model"] or a["model"].startswith("amd GPU 1002:744c"), a["model"])
            self.assertIsNone(g[1]["busy_pct"]); self.assertEqual(g[1]["driver"], "xe")
            g = maluos_gpu.sysfs(root=d, skip_nvidia=False)
            self.assertEqual([x["vendor"] for x in g], ["amd", "intel", "nvidia"], "nouveau/nvidia without nvidia-smi still listed")

    def test_missing_root(self):
        self.assertEqual(maluos_gpu.sysfs(root="/nonexistent/drm"), [])


class Chassis(unittest.TestCase):
    def test_hostnamectl(self):
        for word, want in (("laptop", "laptop"), ("desktop", "desktop"), ("server", "server"), ("vm", "vm"), ("convertible", "laptop")):
            os.environ.pop("MALUOS_CHASSIS", None)
            self.assertEqual(maluos_gpu.chassis(run=FakeRun(word + "\n")), want)

    def test_forced_and_rules(self):
        os.environ["MALUOS_CHASSIS"] = "laptop"
        try:
            self.assertEqual(maluos_gpu.chassis(), "laptop")
        finally:
            del os.environ["MALUOS_CHASSIS"]
        self.assertEqual([maluos_gpu.contribution_rule(k) for k in ("server", "vm", "desktop", "laptop", "unknown")],
                         ["always", "always", "opt-in", "opt-in-idle", "opt-in"])

    def test_dmi_fallback(self):
        self.assertEqual(maluos_gpu.DMI_KINDS[9], "laptop"); self.assertEqual(maluos_gpu.DMI_KINDS[3], "desktop"); self.assertEqual(maluos_gpu.DMI_KINDS[23], "server")


class Plugin(unittest.TestCase):
    def test_maluctl_gpu_status_json(self):
        with tempfile.TemporaryDirectory() as d:
            sysfs_tree(d)
            env = dict(os.environ, MALUOS_GPU_SYSFS=d, MALUOS_CHASSIS="desktop", PYTHONPATH=LIB, MALUOS_NVIDIA_SMI="/nonexistent/nvidia-smi")
            code = ("import sys, importlib.util; spec = importlib.util.spec_from_file_location('gpu', %r); m = importlib.util.module_from_spec(spec); "
                    "spec.loader.exec_module(m); sys.exit(m.main(sys.argv[1:]))") % os.path.join(LIB, "maluctl.d/gpu.py")
            r = subprocess.run([sys.executable, "-c", code, "status", "--json"], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            st = json.loads(r.stdout)
            self.assertEqual(st["chassis"], "desktop"); self.assertEqual(st["contribution_rule"], "opt-in")
            self.assertEqual([g["vendor"] for g in st["gpus"]], ["amd", "intel", "nvidia"])
            r = subprocess.run([sys.executable, "-c", code, "status"], capture_output=True, text=True, env=env)
            self.assertIn("gpu 1:  amd", r.stdout); self.assertIn("rule: shares when its owner opts in (a dedicated desktop)", r.stdout)


class GatewayShare(unittest.TestCase):
    """The sharing switch resolved against the chassis rule (maluos_gpu.share_state, what the gateway's status reports)."""
    def test_resolution(self):
        os.environ["MALUOS_CHASSIS"] = "laptop"
        try:
            st = maluos_gpu.share_state({"enabled": None, "contribution": None}, {"enabled": True, "host": "0.0.0.0"})
            self.assertEqual((st["enabled"], st["contribution"], st["rule"], st["configured"], st["exposed"]), (False, "idle", "opt-in-idle", False, True))
            st = maluos_gpu.share_state({"enabled": True}, {"enabled": True, "host": "127.0.0.1"}, idle_file="/nonexistent/idle")
            # a laptop's switch on, contribution idle by the rule: on as configured, off until the session's idle mark (slice 3)
            self.assertEqual((st["enabled"], st["configured_enabled"], st["contribution"], st["configured"], st["exposed"]), (False, True, "idle", True, False))
            st = maluos_gpu.share_state({"enabled": True, "contribution": "always"}, None)
            self.assertEqual(st["contribution"], "always")
            os.environ["MALUOS_CHASSIS"] = "server"
            st = maluos_gpu.share_state(None, {"enabled": False})
            self.assertEqual((st["enabled"], st["contribution"], st["rule"], st["exposed"]), (True, "always", "always", False))
            # Phase 13 slice 3, the idle rule: contribution idle follows the session's idle mark
            with tempfile.TemporaryDirectory() as d:
                mark = os.path.join(d, "idle")
                st = maluos_gpu.share_state({"enabled": True, "contribution": "idle"}, None, idle_file=mark)
                self.assertEqual((st["enabled"], st["configured_enabled"], st["idle"]["idle"]), (False, True, False))
                with open(mark, "w") as f:
                    json.dump({"since": "2026-10-29T17:00:00Z", "user": "ed", "idle_s": 900}, f)
                st = maluos_gpu.share_state({"enabled": True, "contribution": "idle"}, None, idle_file=mark)
                self.assertEqual((st["enabled"], st["idle"]["idle"], st["idle"]["since"], st["idle"]["user"]), (True, True, "2026-10-29T17:00:00Z", "ed"))
                st = maluos_gpu.share_state({"enabled": True, "contribution": "always"}, None, idle_file=mark)
                self.assertEqual((st["enabled"], st["idle"]), (True, None))
            os.environ["MALUOS_CHASSIS"] = "desktop"
            st = maluos_gpu.share_state({}, {})
            self.assertEqual((st["enabled"], st["contribution"], st["rule"]), (False, "always", "opt-in"))
        finally:
            del os.environ["MALUOS_CHASSIS"]


if __name__ == "__main__":
    unittest.main(verbosity=1)
