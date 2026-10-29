"""The Mac's Wi-Fi and Bluetooth firmware into a MaluOS root.

Apple's Broadcom firmware is not redistributable, so no medium carries it. The
owner runs firmware.sh (share/firmware.sh, the t2linux script) once in macOS:
it writes firmware-raw.tar.gz, a copy of macOS's /usr/share/firmware, to the
Mac's EFI partition. `import_auto()` finds that file on any FAT partition of
the machine, renames the files the way brcmfmac and hci_bcm4377 want them
(asahi_firmware) and installs them under <root>/lib/firmware/brcm with a
marker file. The live medium does it at boot (maluos-apple-firmware.service),
the installer does it into the target, the installed system does it again at
its first boot if the medium could not. `get-apple-firmware` (the t2linux
script) remains for the other four methods, including the download from
Apple's recovery image when macOS is gone.
"""
import glob, json, os, shutil, subprocess, tarfile, tempfile, time

from . import asahi_firmware

MARKER = "lib/firmware/brcm/.maluos-apple-firmware"
TARBALL = "firmware-raw.tar.gz"
QUIRK_FILES = ("brcmfmac4364b2-pcie.txt", "brcmfmac4364b2-pcie.txcap_blob")   # iMac19,x and iMacPro1,1 (firmware.sh)


def sh(*argv, check=False, timeout=120):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        # the tool is not installed (a build host without pciutils, a container): nothing to report, not an error
        if check:
            raise RuntimeError(f"{argv[0]}: not installed")
        return ""
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(argv)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def dmi(name):
    try:
        return open(f"/sys/class/dmi/id/{name}").read().strip()
    except OSError:
        return ""


def is_apple():
    return dmi("sys_vendor").startswith("Apple")


def fat_partitions():
    """[(path, mountpoint or None)] for the FAT partitions of the machine (an ESP is one), the live medium's excluded."""
    try:
        devs = json.loads(sh("lsblk", "-J", "-o", "PATH,FSTYPE,PARTTYPE,MOUNTPOINTS,TYPE") or "{}").get("blockdevices", [])
    except ValueError:
        return []
    out = []
    def walk(ds):
        for d in ds:
            if d.get("type") == "part" and (d.get("fstype") == "vfat" or (d.get("parttype") or "").lower() == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"):
                mps = [m for m in (d.get("mountpoints") or []) if m]
                out.append((d["path"], mps[0] if mps else None))
            walk(d.get("children") or [])
    walk(devs)
    return out


def find_tarball(log=print):
    """The first FAT partition holding firmware-raw.tar.gz: (device, mountpoint, we_mounted)."""
    for dev, mp in fat_partitions():
        mounted = False
        if not mp:
            mp = tempfile.mkdtemp(prefix="maluos-apple-fw-")
            r = subprocess.run(["mount", "-o", "ro", dev, mp], capture_output=True, text=True)
            if r.returncode:
                os.rmdir(mp)
                continue
            mounted = True
        if os.path.exists(os.path.join(mp, TARBALL)):
            log(f"firmware: {TARBALL} on {dev}")
            return dev, mp, mounted
        if mounted:
            subprocess.run(["umount", mp], capture_output=True)
            os.rmdir(mp)
    return None, None, False


def import_tarball(tar_path, root="/", log=print, source=""):
    """Extract the raw macOS tree, rename, install into <root>/lib/firmware/brcm. Returns the file names."""
    work = tempfile.mkdtemp(prefix="maluos-apple-fw-work-")
    try:
        raw = os.path.join(work, "raw"); os.makedirs(raw)
        subprocess.run(["tar", "--warning=no-unknown-keyword", "-xf", tar_path, "-C", raw], check=True, capture_output=True)
        tree = raw
        if not os.path.isdir(os.path.join(tree, "wifi")):
            hits = glob.glob(os.path.join(raw, "**", "wifi"), recursive=True)
            if not hits:
                raise RuntimeError(f"{tar_path} holds no wifi/ directory (not a copy of macOS's /usr/share/firmware)")
            tree = os.path.dirname(hits[0])
        renamed = os.path.join(work, "firmware-renamed.tar")
        manifest = asahi_firmware.build(tree, renamed)
        dest = os.path.join(root, "lib/firmware/brcm")
        os.makedirs(dest, exist_ok=True)
        names = []
        with tarfile.open(renamed) as tf:
            for m in tf.getmembers():
                names.append(m.name)
            tf.extractall(dest, filter="data")
        for q in QUIRK_FILES:
            if os.path.exists(os.path.join(raw, q)):
                shutil.copy2(os.path.join(raw, q), os.path.join(dest, q)); names.append(q)
        for n in names:
            p = os.path.join(dest, n)
            if os.path.exists(p):
                os.chmod(p, 0o644)
        with open(os.path.join(root, MARKER), "w") as f:
            f.write(f"# Apple Wi-Fi and Bluetooth firmware imported by maluos-apple-firmware on {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
            f.write(f"# source: {source or tar_path}\n")
            f.write("\n".join(sorted(names)) + "\n")
        log(f"firmware: {len([n for n in names if n.startswith('brcmfmac')])} Wi-Fi and {len([n for n in names if n.startswith('brcmbt')])} Bluetooth files into {dest}")
        return names
    finally:
        shutil.rmtree(work, ignore_errors=True)


def reload_drivers(log=print):
    for mod in ("brcmfmac_wcc", "brcmfmac"):
        subprocess.run(["modprobe", "-r", mod], capture_output=True)
    subprocess.run(["modprobe", "brcmfmac"], capture_output=True)
    subprocess.run(["modprobe", "-r", "hci_bcm4377"], capture_output=True)
    subprocess.run(["modprobe", "hci_bcm4377"], capture_output=True)
    log("firmware: brcmfmac and hci_bcm4377 reloaded")


def import_auto(root="/", log=print, reload=True):
    """The EFI-partition method without questions. Returns 0 imported, 2 nothing to import, 1 error."""
    if os.path.exists(os.path.join(root, MARKER)):
        log("firmware: already imported (" + os.path.join(root, MARKER) + ")")
        return 0
    dev, mp, mounted = find_tarball(log)
    if not dev:
        log("firmware: no firmware-raw.tar.gz on any FAT partition; run share/firmware.sh in macOS first, or get-apple-firmware later")
        return 2
    try:
        import_tarball(os.path.join(mp, TARBALL), root=root, log=log, source=f"{dev}:{TARBALL}")
    except Exception as e:   # noqa: BLE001
        log(f"firmware: import failed: {e}")
        return 1
    finally:
        if mounted:
            subprocess.run(["umount", mp], capture_output=True)
            try:
                os.rmdir(mp)
            except OSError:
                pass
    if reload and os.path.realpath(root) == "/":
        reload_drivers(log)
    return 0


def copy_imported(src_root="/", dst_root="/target", log=print):
    """What this system imported, into another root (the live medium into the target)."""
    marker = os.path.join(src_root, MARKER)
    if not os.path.exists(marker):
        return False
    names = [l.strip() for l in open(marker) if l.strip() and not l.startswith("#")]
    dest = os.path.join(dst_root, "lib/firmware/brcm")
    os.makedirs(dest, exist_ok=True)
    n = 0
    for name in names:
        s = os.path.join(src_root, "lib/firmware/brcm", name)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(dest, name), follow_symlinks=False) if not os.path.islink(s) else _copy_link(s, os.path.join(dest, name))
            n += 1
    shutil.copy2(marker, os.path.join(dst_root, MARKER))
    log(f"firmware: {n} files copied into {dest}")
    return True


def _copy_link(s, d):
    if os.path.lexists(d):
        os.remove(d)
    os.symlink(os.readlink(s), d)


def status(root="/"):
    """A few lines: the model, the Broadcom devices, the firmware present, what the kernel said."""
    lines = [f"model: {dmi('product_name') or '?'} ({dmi('sys_vendor') or '?'})"]
    bcm = [l.strip() for l in sh("lspci", "-d", "14e4:").splitlines() if l.strip()]
    lines.append("broadcom devices: " + ("; ".join(bcm) if bcm else "none seen"))
    marker = os.path.join(root, MARKER)
    if os.path.exists(marker):
        names = [l.strip() for l in open(marker) if l.strip() and not l.startswith("#")]
        lines.append(f"imported: {len(names)} files ({marker})")
    else:
        present = sorted(os.path.basename(p) for p in glob.glob(os.path.join(root, "lib/firmware/brcm/brcmfmac*apple*")))
        lines.append("imported: no (" + (f"{len(present)} Apple Wi-Fi files present from elsewhere" if present else "no Apple firmware files") + ")")
    k = [l for l in sh("dmesg").splitlines() if "brcmfmac" in l and ("firmware" in l.lower() or "Firmware" in l)]
    if k:
        lines.append("kernel: " + k[-1].split("] ", 1)[-1].strip())
    return lines
