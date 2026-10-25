#!/usr/bin/python3
"""The Apple T2 round's pure parts, no root, no Mac: the firmware renamer on a tree shaped like
macOS's /usr/share/firmware, the import of a firmware-raw.tar.gz into a root with the marker,
the copy into another root, and the component's unit conditions.

  python3 tests/apple-t2-test.py
"""
import os, subprocess, sys, tarfile, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages/maluos-apple-t2-support/lib"))
from maluos_apple_t2 import asahi_firmware, firmware as fw   # noqa: E402

PKG = os.path.join(ROOT, "packages/maluos-apple-t2-support")


def fake_macos_tree(base):
    """wifi/C-4364__s-B3 with a platform's files, bluetooth/ with one chip, as firmware.sh tars them."""
    w = os.path.join(base, "wifi/C-4364__s-B3"); os.makedirs(w)
    for name, data in (("kauai-X3__m-4388.trx", b"TRX" * 100), ("kauai-X3__m-4388.clmb", b"CLM" * 50), ("kauai-X3__m-4388.txcb", b"TXC" * 20),
                       ("P-kauai-X3__m-4388.txt", b"macaddr=00:11:22:33:44:55\nboardtype=0x0860\n")):
        open(os.path.join(w, name), "wb").write(data)
    os.makedirs(os.path.join(base, "wifi/C-4364__s-B3/perf")); open(os.path.join(base, "wifi/C-4364__s-B3/perf/x.trx"), "wb").write(b"skip")
    b = os.path.join(base, "bluetooth"); os.makedirs(b)
    for name, data in (("BCM4364B3_002.004.002.0048.0000_PCIE_macOS_GEN.bin", b"BTFW" * 30), ("BCM4364B3_002.004.002.0048.0000_PCIE_macOS_GEN.ptb", b"PTB" * 10)):
        open(os.path.join(b, name), "wb").write(data)


class Renamer(unittest.TestCase):
    def test_wifi_and_bluetooth_files(self):
        with tempfile.TemporaryDirectory() as d:
            fake_macos_tree(d)
            out = os.path.join(d, "renamed.tar")
            manifest = asahi_firmware.build(d, out)
            names = tarfile.open(out).getnames()
        wifi = [n for n in names if n.startswith("brcmfmac4364b3-pcie.apple")]
        self.assertEqual(len(wifi), 4, names)
        self.assertTrue(any(n.endswith(".bin") for n in wifi) and any(n.endswith(".txt") for n in wifi))
        self.assertTrue(any(n.endswith(".clm_blob") for n in wifi) and any(n.endswith(".txcap_blob") for n in wifi))
        self.assertTrue(any(n.startswith("brcmbt4364b3-apple,gen") and n.endswith(".bin") for n in names), names)
        self.assertFalse(any("perf" in n for n in names))
        self.assertTrue(any(l.startswith("FILE ") for l in manifest))


class Import(unittest.TestCase):
    def test_tarball_into_a_root_then_copied(self):
        with tempfile.TemporaryDirectory() as d:
            tree = os.path.join(d, "tree"); os.makedirs(tree); fake_macos_tree(tree)
            tgz = os.path.join(d, fw.TARBALL)
            subprocess.run(["tar", "-czf", tgz, "-C", tree, "."], check=True)
            root = os.path.join(d, "root"); os.makedirs(root)
            log = []
            names = fw.import_tarball(tgz, root=root, log=log.append, source="test")
            brcm = os.path.join(root, "lib/firmware/brcm")
            self.assertTrue(os.path.exists(os.path.join(root, fw.MARKER)))
            for n in names:
                self.assertTrue(os.path.lexists(os.path.join(brcm, n)), n)
            marker = open(os.path.join(root, fw.MARKER)).read()
            self.assertIn("source: test", marker)
            self.assertTrue(any("Wi-Fi" in l for l in log))
            # the live medium's set into a target root
            other = os.path.join(d, "target"); os.makedirs(other)
            self.assertTrue(fw.copy_imported(root, other, log=log.append))
            self.assertTrue(os.path.exists(os.path.join(other, fw.MARKER)))
            self.assertEqual(sorted(os.listdir(os.path.join(other, "lib/firmware/brcm"))), sorted(os.listdir(brcm)))
            self.assertFalse(fw.copy_imported(os.path.join(d, "nothing"), other))
            # status reads the marker
            self.assertTrue(any(l.startswith("imported: ") and "files" in l for l in fw.status(root)))

    def test_not_a_firmware_tree(self):
        with tempfile.TemporaryDirectory() as d:
            junk = os.path.join(d, "junk"); os.makedirs(junk); open(os.path.join(junk, "x"), "w").write("x")
            tgz = os.path.join(d, "firmware-raw.tar.gz"); subprocess.run(["tar", "-czf", tgz, "-C", junk, "."], check=True)
            with self.assertRaises(RuntimeError):
                fw.import_tarball(tgz, root=os.path.join(d, "r"))


class Package(unittest.TestCase):
    def test_units_are_gated_to_apple(self):
        for f in ("systemd/maluos-apple-firmware.service", "systemd/apple-only.conf", "systemd/t2fanrd-apple-only.conf"):
            text = open(os.path.join(PKG, f)).read()
            self.assertIn('ConditionFirmware=smbios-field(sys_vendor = "Apple Inc.")', text, f)
        self.assertIn('add_drivers+=" apple-bce "', open(os.path.join(PKG, "dracut/50-maluos-apple-t2.conf")).read())
        inst = open(os.path.join(PKG, "debian/install")).read()
        for unit in ("tiny-dfr.service.d", "t2fanrd.service.d"):
            self.assertIn(unit, inst)
        self.assertIn("ConditionPathExistsGlob=/sys/devices/platform/applesmc.*", open(os.path.join(PKG, "systemd/t2fanrd-apple-only.conf")).read())

    def test_seed_and_catalogue(self):
        seed = [l.split("#")[0].strip() for l in open(os.path.join(ROOT, "seeds/apple-t2.seed")) if l.split("#")[0].strip()]
        for must in ("maluos-apple-t2-support", "apple-bce-dkms", "dkms", "linux-headers-generic", "mesa-vulkan-drivers"):
            self.assertIn(must, seed)
        self.assertIn("?tiny-dfr", seed)
        desc = open(os.path.join(ROOT, "packages/maluos-meta/debian/descriptions")).read()
        self.assertIn("apple-t2|Apple T2 Mac support|", desc)
        live = open(os.path.join(ROOT, "image/profiles/live.pkgs")).read()
        self.assertIn("apple-bce-dkms", live)

    def test_vendor_checksums(self):
        vdir = os.path.join(ROOT, "vendor/apple-t2")
        import hashlib, re
        rows = re.findall(r"^\| ([a-z0-9-]+) \| (\S+) \|.*\| ([0-9a-f]{64}) \|$", open(os.path.join(vdir, "README.md")).read(), re.M)
        self.assertEqual(len(rows), 8)
        for name, ver, sha in rows:
            cands = [f for f in os.listdir(vdir) if f.startswith(f"{name}_{ver}_") and f.endswith(".deb")]
            self.assertEqual(len(cands), 1, (name, ver))
            self.assertEqual(hashlib.sha256(open(os.path.join(vdir, cands[0]), "rb").read()).hexdigest(), sha, name)


if __name__ == "__main__":
    unittest.main(verbosity=1)
