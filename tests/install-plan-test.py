#!/usr/bin/python3
"""Unit tests for the installer engine's pure parts (Phase 11 slice 2): the plan schema,
the four layouts on disks of 16, 64 and 2000 GB, the fit refusals, the redaction and the
telemetry document; the Apple T2 round's storage.target free and the Mac facts. No root, no disk, no VM: runs in the packages workflow.

  python3 tests/install-plan-test.py
"""
import json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages/maluos-installer/lib"))

from maluos_installer import plan as P, engine, telemetry          # noqa: E402
from maluos_installer.steps import storage as S                     # noqa: E402

GIB = 1 << 30
MINIMAL = """
maluos-install:
  version: 1
  storage: {disk: first, erase: true}
  identity: {user: {name: ed, password: "plain:secret"}}
"""


def load(text, variant="server"):
    return P.load(text, variant)


class Schema(unittest.TestCase):
    def test_defaults_server(self):
        p = load(MINIMAL)
        self.assertEqual(p["source"]["image"], "maluos-server")
        self.assertEqual(p["storage"]["layout"], "lvm")
        self.assertEqual(p["storage"]["root_size"], "50G")
        self.assertTrue(p["identity"]["ssh"]["server"])
        self.assertTrue(p["firstboot"]["cloud_init"])
        self.assertEqual(p["bootloader"]["timeout"], 3)
        self.assertEqual(p["finish"]["action"], "reboot")
        self.assertEqual(p["identity"]["user"]["fullname"], "ed")
        self.assertEqual(p["firstboot"]["enroll"]["name"], "maluos")

    def test_defaults_desktop(self):
        p = load(MINIMAL, "desktop")
        self.assertEqual(p["source"]["image"], "maluos-desktop")
        self.assertFalse(p["identity"]["ssh"]["server"])
        self.assertFalse(p["firstboot"]["cloud_init"])
        self.assertEqual(p["bootloader"]["timeout"], 0)

    def test_direct_root_size_all(self):
        p = load(MINIMAL.replace("erase: true", "erase: true, layout: direct"))
        self.assertEqual(p["storage"]["root_size"], "all")

    def test_unknown_key(self):
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL + "  storgae: {}\n")
        self.assertIn("unknown key 'storgae'", str(cm.exception))
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL.replace("erase: true", "erase: true, encrpyt: true"))
        self.assertIn("storage.encrpyt", str(cm.exception))

    def test_types_and_enums(self):
        with self.assertRaises(P.PlanError):
            load(MINIMAL.replace("erase: true", "erase: yes please"))
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL.replace("erase: true", "erase: true, layout: zfs"))
        self.assertIn("storage.layout", str(cm.exception))
        with self.assertRaises(P.PlanError):
            load(MINIMAL.replace("version: 1", "version: 2"))
        with self.assertRaises(P.PlanError):
            load(MINIMAL.replace("version: 1", "version: one"))

    def test_semantic_errors(self):
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL.replace("erase: true", "erase: false"))
        self.assertIn("erase must be true", str(cm.exception))
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL.replace("erase: true", "erase: true, encrypt: true"))
        self.assertIn("passphrase", str(cm.exception))
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL.replace('password: "plain:secret"', 'password: "secret"'))
        self.assertIn("crypt hash", str(cm.exception))
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL.replace("erase: true", "erase: true, root_size: 4G"))
        self.assertIn("under 8G", str(cm.exception))
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL + "  network: {mode: static, address: 10.0.0.5/24}\n")
        self.assertIn("gateway", str(cm.exception))
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL + "  firstboot: {enroll: {kind: office, url: https://x}}\n")
        self.assertIn("enroll.code", str(cm.exception))
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL + "  network: {wifi: {ssid: home, password: x}}\n")
        self.assertIn("not supported yet", str(cm.exception))

    def test_json_plan(self):
        doc = {"maluos-install": {"version": 1, "storage": {"disk": "first", "erase": True},
                                  "identity": {"user": {"name": "ed", "ssh_keys": ["ssh-ed25519 AAAA ed"]}}}}
        p = load(json.dumps(doc))
        self.assertEqual(p["identity"]["user"]["ssh_keys"], ["ssh-ed25519 AAAA ed"])

    def test_sizes(self):
        self.assertEqual(P.parse_size("50G"), 50 * GIB)
        self.assertEqual(P.parse_size("512M"), 512 << 20)
        self.assertEqual(P.parse_size("1.5G"), int(1.5 * GIB))
        self.assertEqual(P.parse_size("all"), "all")
        self.assertEqual(P.parse_size("2T"), 2 << 40)
        with self.assertRaises(P.PlanError):
            P.parse_size("fifty")
        self.assertEqual(P.fmt_size(50 * GIB), "50G")
        self.assertEqual(P.fmt_size(1536 << 20), "1536M")

    def test_example_plans_from_the_repo(self):
        for name in ("server-unattended.yaml", "desktop-unattended.yaml"):
            p = load(open(os.path.join(ROOT, "iso/plans", name)).read(), name.split("-")[0])
            self.assertTrue(p["identity"]["user"]["password_change_required"])
            self.assertFalse(p["telemetry"]["send"])

    def test_install_plan_doc_examples(self):
        """The two examples in docs/install-plan.md parse (the second with its file: references unresolved)."""
        text = open(os.path.join(ROOT, "docs/install-plan.md")).read()
        blocks = [b.split("```", 1)[0] for b in text.split("```yaml")[1:]]
        plans = [b for b in blocks if "maluos-install:" in b and "identity:" in b]
        self.assertGreaterEqual(len(plans), 2)
        for b in plans:
            b = b.replace('"$6$…"', '"$6$abc"')
            p = P.fill_defaults(P.parse(b), "desktop")
            self.assertEqual(P.semantic_errors(p), [], b)


class Refs(unittest.TestCase):
    def test_file_refs_and_redaction(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "plans"))
            open(os.path.join(d, "plans/pass.txt"), "w").write("open sesame\n")
            open(os.path.join(d, "plans/code.txt"), "w").write("ABCD-EFGH\n")
            open(os.path.join(d, "plans/keys"), "w").write("# keys\nssh-ed25519 AAAA one\n\nssh-rsa BBBB two\n")
            p = load(MINIMAL.replace("erase: true", "erase: true, encrypt: true, passphrase: 'file:plans/pass.txt'")
                     + "  firstboot: {enroll: {kind: office, url: https://x, code: 'file:plans/code.txt'}}\n"
                     + "  identity: {user: {name: ed, password: 'plain:secret', ssh_keys: ['file:plans/keys', 'ssh-ed25519 CCCC three']}}\n")
            P.resolve_refs(p, media=d)
            self.assertEqual(p["storage"]["passphrase"], "open sesame")
            self.assertEqual(p["firstboot"]["enroll"]["code"], "ABCD-EFGH")
            self.assertEqual(p["identity"]["user"]["ssh_keys"], ["ssh-ed25519 AAAA one", "ssh-rsa BBBB two", "ssh-ed25519 CCCC three"])
            r = P.redact(p)
            self.assertEqual(r["storage"]["passphrase"], "<redacted>")
            self.assertEqual(r["firstboot"]["enroll"]["code"], "<redacted>")
            self.assertEqual(r["identity"]["user"]["password"], "<redacted>")
            self.assertEqual(p["storage"]["passphrase"], "open sesame", "redact must not touch the original")
            dumped = P.dump(r)
            self.assertNotIn("open sesame", dumped); self.assertNotIn("ABCD", dumped); self.assertNotIn("secret", dumped)
            self.assertIn("maluos-install:", dumped)

    def test_missing_file_ref(self):
        p = load(MINIMAL.replace("erase: true", "erase: true, encrypt: true, passphrase: 'file:/nowhere/pass.txt'"))
        with self.assertRaises(P.PlanError):
            P.resolve_refs(p, media="/nonexistent")


def st(**k):
    base = {"disk": "first", "erase": True, "layout": "lvm", "root_size": "50G", "filesystem": "ext4", "encrypt": False,
            "passphrase": "", "swap": "auto", "esp_size": "1G", "boot_size": "2G", "label": "maluos"}
    base.update(k)
    return base


class Layouts(unittest.TestCase):
    MEM = 4 * GIB

    def test_direct_plain(self):
        for gb in (16, 64, 2000):
            l = S.compute_layout(st(layout="direct", root_size="all"), "/dev/sda", gb * GIB, self.MEM)
            self.assertEqual(l["errors"], [], (gb, l["errors"]))
            self.assertEqual([p["name"] for p in l["parts"]], ["bios_grub", "ESP", "root"])
            self.assertEqual(l["root_dev"], "/dev/sda3")
            self.assertIsNone(l["boot_dev"]); self.assertIsNone(l["luks"]); self.assertIsNone(l["lvm"])
            self.assertEqual(l["swap_bytes"], 4 * GIB)
            self.assertAlmostEqual(l["root_bytes"] / GIB, gb - 1 - 2 / 1024, delta=0.01)

    def test_direct_encrypted(self):
        for gb in (16, 64, 2000):
            l = S.compute_layout(st(layout="direct", root_size="all", encrypt=True, passphrase="x"), "/dev/nvme0n1", gb * GIB, self.MEM)
            self.assertEqual(l["errors"], [], (gb, l["errors"]))
            self.assertEqual([p["name"] for p in l["parts"]], ["bios_grub", "ESP", "boot", "maluos-crypt"])
            self.assertEqual(l["boot_dev"], "/dev/nvme0n1p3")
            self.assertEqual(l["luks"], {"dev": "/dev/nvme0n1p4", "name": "maluos-root", "label": "maluos-crypt"})
            self.assertEqual(l["root_dev"], "/dev/mapper/maluos-root")
            self.assertIsNone(l["lvm"])

    def test_lvm_plain(self):
        for gb in (16, 64, 2000):
            l = S.compute_layout(st(), "/dev/sda", gb * GIB, self.MEM)
            self.assertEqual(l["errors"], [], (gb, l["errors"]))
            self.assertEqual([p["name"] for p in l["parts"]], ["bios_grub", "ESP", "boot", "maluos-pv"])
            self.assertEqual(l["lvm"]["pv"], "/dev/sda4")
            self.assertEqual(l["root_dev"], "/dev/maluos/root")
            if gb == 16:
                self.assertIsNone(l["lvm"]["size"], "50G on a 16 GB disk takes the disk")
            else:
                self.assertEqual(l["lvm"]["size"], 50 * GIB)
                self.assertEqual(l["root_bytes"], 50 * GIB)

    def test_lvm_encrypted(self):
        l = S.compute_layout(st(encrypt=True, passphrase="x", filesystem="xfs"), "/dev/vda", 64 * GIB, self.MEM)
        self.assertEqual(l["errors"], [])
        self.assertEqual([p["name"] for p in l["parts"]], ["bios_grub", "ESP", "boot", "maluos-crypt"])
        self.assertEqual(l["luks"]["name"], "maluos-pv")
        self.assertEqual(l["lvm"]["pv"], "/dev/mapper/maluos-pv")
        self.assertEqual(l["root_fs"], "xfs")

    def test_fit_refusals(self):
        l = S.compute_layout(st(layout="direct", root_size="all"), "/dev/sda", 8 * GIB, self.MEM)
        self.assertTrue(any("at least 8G" in e for e in l["errors"]), l["errors"])
        l = S.compute_layout(st(layout="direct", root_size="100G"), "/dev/sda", 64 * GIB, self.MEM)
        self.assertTrue(any("does not fit" in e for e in l["errors"]), l["errors"])
        l = S.compute_layout(st(layout="direct", root_size="all", swap="16G"), "/dev/sda", 20 * GIB, self.MEM)
        self.assertTrue(any("swap" in e for e in l["errors"]), l["errors"])
        l = S.compute_layout(st(layout="direct", root_size="20G", encrypt=True, passphrase="x"), "/dev/sda", 64 * GIB, self.MEM)
        self.assertTrue(any("root_size is 'all'" in e for e in l["errors"]), l["errors"])

    def test_swap(self):
        self.assertEqual(S.swap_bytes("auto", 2 * GIB), 2 * GIB)
        self.assertEqual(S.swap_bytes("auto", 64 * GIB), 8 * GIB)
        self.assertEqual(S.swap_bytes("none", 64 * GIB), 0)
        self.assertEqual(S.swap_bytes("1G", 64 * GIB), GIB)

    def test_sfdisk_script(self):
        l = S.compute_layout(st(), "/dev/sda", 64 * GIB, self.MEM)
        s = S.sfdisk_script(l)
        self.assertIn("label: gpt", s)
        self.assertIn(f"size={(1 << 20) // 512}, type={S.TYPE['bios']}", s)
        self.assertIn(f"type={S.TYPE['lvm']}, name=\"maluos-pv\"", s)
        self.assertEqual(s.strip().splitlines()[-1].count("size="), 0, "the last partition takes the rest")
        self.assertIn("64G", S.describe(l))

    def test_partdev(self):
        self.assertEqual(S.partdev("/dev/sda", 3), "/dev/sda3")
        self.assertEqual(S.partdev("/dev/nvme0n1", 3), "/dev/nvme0n1p3")
        self.assertEqual(S.partdev("/dev/mmcblk0", 2), "/dev/mmcblk0p2")


class FakeCtx:
    def __init__(self, plan, facts, state):
        self.plan, self.facts, self.state = plan, facts, state
        self.started = 1000.0
    def log_tail(self, n=40):
        return ["$ chpasswd -e", "useradd ed", "grub-install failed"]


class Telemetry(unittest.TestCase):
    def test_document(self):
        import time
        plan = load(MINIMAL + "  components: {install: [maluos-api]}\n  locale: {language: en_GB.UTF-8, keyboard: {layout: gb}, timezone: Europe/London}\n")
        facts = {"disks": [{"path": "/dev/sda", "size": 256 * GIB, "bus": "nvme", "model": "Samsung 990", "serial": "S123", "medium": False},
                           {"path": "/dev/sr0", "size": 3 * GIB, "bus": "sata", "model": "QEMU DVD", "serial": "", "medium": True}],
                 "firmware": "uefi", "secure_boot": "on", "memory_mb": 65536, "cpu": {"model": "AMD EPYC 7313", "cores": 16},
                 "gpu": "none", "virtual": "kvm"}
        layout = S.compute_layout(plan["storage"], "/dev/sda", 256 * GIB, 64 * GIB)
        ctx = FakeCtx(plan, facts, {"storage": layout, "image": {"variant": "server"}})
        ctx.started = time.time() - 412
        doc = telemetry.document(ctx, outcome="ok")
        self.assertEqual(doc["v"], 1)
        self.assertEqual(doc["variant"], "server")
        self.assertEqual(doc["layout"], {"kind": "lvm", "filesystem": "ext4", "encrypt": False, "target": "disk", "disk_gb": 256, "root_gb": 50, "swap_gb": 8.0})
        self.assertEqual(doc["hardware"]["disks"], [{"bus": "nvme", "gb": 256}], "the medium is left out, models and serials never appear")
        self.assertEqual(doc["hardware"]["cores"], 16); self.assertTrue(doc["hardware"]["secure_boot"])
        self.assertEqual(doc["locale"], {"language": "en_GB", "keyboard": "gb", "timezone": "Europe/London"})
        self.assertEqual(doc["components"], ["maluos-api", "maluos-server"])
        self.assertIn(doc["duration_s"], (412, 413))
        self.assertIsNone(doc["failure"])
        text = json.dumps(doc)
        for never in ("ed\"", "maluos\"", "Samsung", "S123", "secret", "10.0."):
            self.assertNotIn(f'"{never}', text)
        self.assertNotIn("hostname", text)
        fail = telemetry.document(ctx, outcome="failed", failure={"step": "bootloader", "sub": "grub-bios", "error": "grub-install failed (rc=1)"})
        self.assertEqual(fail["failure"]["step"], "bootloader")
        self.assertEqual(fail["failure"]["log_tail"][0], "<redacted line>")
        self.assertEqual(fail["failure"]["log_tail"][2], "grub-install failed")


class Journal(unittest.TestCase):
    def test_substep_resume(self):
        plan = load(MINIMAL)
        with tempfile.TemporaryDirectory() as d:
            ctx = engine.Context(plan, {"disks": [], "firmware": "bios", "secure_boot": "n/a", "memory_mb": 1024}, run_dir=d, json_out=False)
            ctx.step = "configure"
            ran = []
            with ctx.substep("a") as go:
                if go: ran.append("a")
            try:
                with ctx.substep("b") as go:
                    if go: raise RuntimeError("boom")
            except engine.StepFailed as e:
                self.assertEqual((e.step, e.sub), ("configure", "b"))
            self.assertEqual(ctx.sub_state("configure", "a"), "ok")
            self.assertEqual(ctx.sub_state("configure", "b"), "fail")
            # a new context on the same run dir sees the journal and skips a
            ctx2 = engine.Context(plan, ctx.facts, run_dir=d)
            ctx2.step = "configure"
            with ctx2.substep("a") as go:
                self.assertFalse(go)
            with ctx2.substep("b") as go:
                self.assertTrue(go)
            self.assertEqual(ctx2.sub_state("configure", "b"), "ok")
            self.assertTrue(os.path.exists(os.path.join(d, "install.log")))
            events = [json.loads(l) for l in open(os.path.join(d, "install.log")) if l.startswith("{")]
            self.assertTrue(any(e["state"] == "fail" or e["state"] == "ok" for e in events))


# --- the Apple T2 round: storage.target free, the Mac facts ------------------------------------
MIB = 1 << 20
APFS = "7C3457EF-0000-11AA-AA11-00306543ECAC"
MAC_TABLE = {"label": "gpt",
             "parts": [{"n": 1, "node": "/dev/nvme0n1p1", "start": 20 * MIB, "size": 300 * MIB, "type": S.TYPE["esp"], "name": "EFI"},
                       {"n": 2, "node": "/dev/nvme0n1p2", "start": 320 * MIB, "size": 400 * GIB, "type": APFS, "name": "Macintosh HD"}],
             "free": [{"start": 320 * MIB + 400 * GIB, "size": 600 * GIB}],
             "esp": {"n": 1, "node": "/dev/nvme0n1p1", "size": 300 * MIB}}
FREE_PLAN = """
maluos-install:
  version: 1
  storage: {disk: first, target: free, erase: false}
  identity: {user: {name: ed, password: "plain:secret"}}
"""


class FreeSpace(unittest.TestCase):
    def layout(self, text=FREE_PLAN, table=MAC_TABLE, sector=4096, **st):
        p = load(text)
        p["storage"].update(st)
        return S.compute_layout(p["storage"], "/dev/nvme0n1", 1000 * GIB, 32 * GIB, table=table, sector=sector)

    def test_plan_rules(self):
        self.assertEqual(load(FREE_PLAN)["storage"]["target"], "free")
        with self.assertRaises(P.PlanError) as cm:
            load(FREE_PLAN.replace("erase: false", "erase: true"))
        self.assertIn("storage.erase must be false", str(cm.exception))
        with self.assertRaises(P.PlanError) as cm:
            load(MINIMAL.replace("erase: true", "erase: false"))
        self.assertIn("storage.erase must be true", str(cm.exception))

    def test_lvm_in_the_free_space(self):
        l = self.layout()
        self.assertEqual(l["errors"], [])
        self.assertEqual(l["mode"], "free")
        self.assertEqual([p["n"] for p in l["parts"]], [3, 4])            # /boot and the PV after the two kept partitions
        self.assertEqual(l["created"], [3, 4])
        self.assertEqual(l["esp_n"], 1); self.assertEqual(l["esp_dev"], "/dev/nvme0n1p1")
        self.assertEqual(l["boot_dev"], "/dev/nvme0n1p3")
        self.assertEqual(l["parts"][0]["start"], 320 * MIB + 400 * GIB)
        self.assertEqual(l["parts"][1]["start"], 320 * MIB + 400 * GIB + 2 * GIB)
        self.assertEqual(l["parts"][1]["size"], 600 * GIB - 2 * GIB)      # the PV takes the rest of the region
        self.assertEqual(l["lvm"]["size"], 50 * GIB)
        self.assertEqual(l["kept"], 2)
        self.assertNotIn("bios_grub", [p["name"] for p in l["parts"]])
        self.assertNotIn("ESP", [p["name"] for p in l["parts"]])

    def test_sfdisk_script_appends_in_the_disk_sectors(self):
        l = self.layout()
        script = S.sfdisk_script(l)
        self.assertNotIn("label:", script)
        lines = script.strip().splitlines()
        self.assertEqual(len(lines), 2)
        start = (320 * MIB + 400 * GIB) // 4096
        self.assertTrue(lines[0].startswith(f"start={start}, size={2 * GIB // 4096}, type={S.TYPE['linux']}"), lines[0])
        self.assertIn('name="maluos-pv"', lines[1])
        # the erase layout counts in the disk's sectors too (an Apple NVMe has 4096-byte sectors)
        e = S.compute_layout(load(MINIMAL)["storage"], "/dev/nvme0n1", 1000 * GIB, 32 * GIB, sector=4096)
        self.assertIn(f"size={MIB // 4096}, type={S.TYPE['bios']}", S.sfdisk_script(e))
        self.assertEqual(e["mode"], "disk"); self.assertEqual(e["esp_n"], 2); self.assertEqual(e["created"], [])

    def test_direct_and_encrypted_in_the_free_space(self):
        l = self.layout(layout="direct", root_size="all")
        self.assertEqual(l["errors"], [])
        self.assertEqual([p["name"] for p in l["parts"]], ["root"])
        self.assertEqual(l["root_dev"], "/dev/nvme0n1p3")
        self.assertEqual(l["parts"][0]["size"], 600 * GIB)
        l = self.layout(layout="direct", root_size="all", encrypt=True, passphrase="x" * 10)
        self.assertEqual(l["errors"], [])
        self.assertEqual([p["name"] for p in l["parts"]], ["boot", "maluos-crypt"])
        self.assertEqual(l["luks"]["dev"], "/dev/nvme0n1p4")

    def test_refusals(self):
        l = self.layout(table={**MAC_TABLE, "free": []})
        self.assertTrue(any("no free space" in e for e in l["errors"]), l["errors"])
        l = self.layout(table={**MAC_TABLE, "esp": None})
        self.assertTrue(any("no EFI system partition" in e for e in l["errors"]))
        l = self.layout(table={**MAC_TABLE, "label": "dos"})
        self.assertTrue(any("no GPT" in e for e in l["errors"]))
        l = self.layout(table={**MAC_TABLE, "free": [{"start": 320 * MIB + 400 * GIB, "size": 6 * GIB}]})
        self.assertTrue(any("at least 8G" in e for e in l["errors"]), l["errors"])
        self.assertIn("2 partitions kept", S.describe(self.layout()))

    def test_table_from_sfdisk_json(self):
        from maluos_installer import disks as D
        doc = {"label": "gpt", "sectorsize": 4096, "firstlba": 6, "lastlba": 244190639,   # a 1 TB Apple NVMe
               "partitions": [{"node": "/dev/nvme0n1p1", "start": 10, "size": 76800, "type": S.TYPE["esp"], "name": "EFI"},
                              {"node": "/dev/nvme0n1p2", "start": 76810, "size": 100000000, "type": APFS, "name": "Macintosh HD"}]}
        t = D.table_from_sfdisk(doc)
        self.assertEqual(t["label"], "gpt"); self.assertEqual(t["esp"]["n"], 1)
        self.assertEqual(t["parts"][1]["start"], 76810 * 4096)
        self.assertEqual(len(t["free"]), 1)
        self.assertEqual(t["free"][0]["start"] % MIB, 0)
        self.assertGreater(t["free"][0]["size"], 500 * GIB)
        self.assertEqual(D.table_from_sfdisk(None), {"label": "none", "parts": [], "free": [], "esp": None})
        # the fake facts of the build host carry a table too, so a free-space plan checks on the build host
        self.assertTrue(D.T2_MODELS[0].startswith("MacBookPro15"))

    def test_run_env_overrides(self):
        # sub_components passes DEBIAN_FRONTEND itself; the merge must not raise (it did, in the first apple round)
        with tempfile.TemporaryDirectory() as d:
            ctx = engine.Context(load(MINIMAL), {"disks": []}, run_dir=d, dry_run=False)
            ctx.step = "configure"
            out = ctx.run([sys.executable, "-c", "import os; print(os.environ['DEBIAN_FRONTEND'], os.environ['LC_ALL'])"], env={"DEBIAN_FRONTEND": "noninteractive"})
            self.assertEqual(out.strip(), "noninteractive C.UTF-8")

    def test_telemetry_names_the_mac(self):
        plan = load(FREE_PLAN)
        facts = {"disks": [], "memory_mb": 32768, "cpu": {"model": "i9", "cores": 12}, "gpu": "amd", "firmware": "uefi",
                 "secure_boot": "off", "virtual": "none", "apple": {"mac": True, "model": "MacBookPro15,1", "t2": True, "bce": True}}
        with tempfile.TemporaryDirectory() as d:
            ctx = engine.Context(plan, facts, run_dir=d, dry_run=True)
            doc = telemetry.document(ctx)
        self.assertEqual(doc["hardware"]["model"], "MacBookPro15,1")
        self.assertEqual(doc["layout"]["target"], "free")


if __name__ == "__main__":
    unittest.main(verbosity=1)
