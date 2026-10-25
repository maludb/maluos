"""What the machine has: disks (with their partition tables and free space), the install medium, firmware, memory, CPU, GPU, virtualisation, the Mac.

Everything here reads; nothing writes. `facts()` is the dictionary the steps,
the check and the telemetry document work from.
"""
import glob, json, os, re, subprocess

MIB = 1 << 20
ESP_TYPE = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"


def sh(*argv, timeout=60):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def lsblk():
    out = sh("lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,TRAN,RM,ROTA,MODEL,SERIAL,WWN,PKNAME,FSTYPE,LABEL,MOUNTPOINTS,LOG-SEC")
    try:
        return json.loads(out or "{}").get("blockdevices", [])
    except ValueError:
        return []


def _flatten(devs, out=None):
    out = [] if out is None else out
    for d in devs:
        out.append(d)
        _flatten(d.get("children") or [], out)
    return out


def medium_device(cdrom="/cdrom"):
    """The whole disk the install medium is on (so it is never a target), or None."""
    src = sh("findmnt", "-rn", "-o", "SOURCE", cdrom).strip()
    if not src or not src.startswith("/dev/"):
        return None
    pk = sh("lsblk", "-no", "PKNAME", src).strip().splitlines()
    if pk and pk[0]:
        return "/dev/" + pk[0]
    return src


def disks(cdrom="/cdrom"):
    """Candidate target disks: whole disks, not the medium, not loop/zram/ram, size > 0."""
    medium = medium_device(cdrom)
    out = []
    for d in lsblk():
        if d.get("type") != "disk":
            continue
        name = d.get("name") or ""
        if re.match(r"^(loop|zram|ram|sr|fd)", name):
            continue
        if not d.get("size"):
            continue
        path = d.get("path") or f"/dev/{name}"
        children = _flatten(d.get("children") or [])
        labels = [c.get("label") or "" for c in children] + [d.get("label") or ""]
        is_medium = path == medium or any(l.startswith("MALUOS_") for l in labels) or (d.get("fstype") == "iso9660")
        out.append({
            "path": path, "name": name, "size": int(d.get("size") or 0),
            "bus": (d.get("tran") or ("nvme" if name.startswith("nvme") else "unknown")),
            "removable": bool(d.get("rm")), "rotational": bool(d.get("rota")),
            "model": (d.get("model") or "").strip(), "serial": (d.get("serial") or "").strip(),
            "wwn": d.get("wwn") or "", "medium": is_medium,
            "in_use": any(c.get("mountpoints") and any(c["mountpoints"]) for c in children) or bool(d.get("mountpoints") and any(d["mountpoints"])),
            "sector": int(d.get("log-sec") or 512),
            "table": partition_table(path),
        })
    return out


def partition_table(path):
    """The disk's partition table as sfdisk reports it (bytes): label, parts, the free regions (1 MiB
    aligned, 64 MiB or more), the EFI system partition. For storage.target free (install beside macOS)."""
    try:
        doc = (json.loads(sh("sfdisk", "-J", path) or "{}") or {}).get("partitiontable")
    except ValueError:
        doc = None
    return table_from_sfdisk(doc)


def table_from_sfdisk(doc):
    empty = {"label": "none", "parts": [], "free": [], "esp": None}
    if not doc:
        return empty
    ss = int(doc.get("sectorsize") or 512)
    parts = []
    for p in doc.get("partitions") or []:
        node = p.get("node") or ""
        m = re.search(r"(\d+)$", node)
        parts.append({"n": int(m.group(1)) if m else 0, "node": node, "start": int(p["start"]) * ss, "size": int(p["size"]) * ss,
                      "type": (p.get("type") or "").upper(), "name": p.get("name") or ""})
    label = doc.get("label") or "none"
    free = []
    if label == "gpt":
        cursor = int(doc.get("firstlba") or 2048) * ss
        end = (int(doc.get("lastlba") or 0) + 1) * ss
        for p in sorted(parts, key=lambda p: p["start"]):
            if p["start"] > cursor:
                free.append((cursor, p["start"]))
            cursor = max(cursor, p["start"] + p["size"])
        if end > cursor:
            free.append((cursor, end))
    aligned = []
    for a, b in free:
        start = -(-a // MIB) * MIB
        size = (b - start) // MIB * MIB
        if size >= 64 * MIB:
            aligned.append({"start": start, "size": size})
    esp = next(({"n": p["n"], "node": p["node"], "size": p["size"]} for p in parts if p["type"] == ESP_TYPE), None)
    return {"label": label, "parts": parts, "free": aligned, "esp": esp}


def by_id_names(path):
    names = []
    try:
        for n in os.listdir("/dev/disk/by-id"):
            if os.path.realpath(os.path.join("/dev/disk/by-id", n)) == os.path.realpath(path):
                names.append(n)
    except OSError:
        pass
    return sorted(names)


def resolve_disk(spec, candidates):
    """The plan's storage.disk -> exactly one disk dict, or raise ValueError with what matched."""
    spec = (spec or "").strip()
    usable = [d for d in candidates if not d["medium"]]
    if spec == "first":
        fixed = [d for d in usable if not d["removable"]]
        if not fixed:
            raise ValueError("no fixed disk besides the install medium (disks seen: " + describe(candidates) + ")")
        return fixed[0]
    if spec.startswith("/dev/"):
        real = os.path.realpath(spec)
        for d in candidates:
            if os.path.realpath(d["path"]) == real:
                if d["medium"]:
                    raise ValueError(f"{spec} is the install medium")
                return d
        raise ValueError(f"no disk {spec} (disks seen: {describe(candidates)})")
    matched = []
    if spec.startswith("id:"):
        want = spec[3:].strip()
        matched = [d for d in usable if want in by_id_names(d["path"])]
    elif spec.startswith("serial:"):
        want = spec[7:].strip()
        matched = [d for d in usable if d["serial"] == want]
    elif spec.startswith("model:"):
        want = spec[6:].strip().lower()
        matched = [d for d in usable if want in d["model"].lower()]
    else:
        raise ValueError(f"storage.disk {spec!r}: use first, /dev/..., id:NAME, serial:S or model:TEXT")
    if len(matched) == 1:
        return matched[0]
    if not matched:
        raise ValueError(f"no disk matches {spec} (disks seen: {describe(candidates)})")
    raise ValueError(f"{spec} matches more than one disk: {describe(matched)}")


def describe(ds):
    return ", ".join(f"{d['path']} {d['size'] >> 30}G {d['model'] or d['bus']}{' [medium]' if d.get('medium') else ''}" for d in ds) or "none"


def firmware():
    if os.path.isdir("/sys/firmware/efi"):
        sb = sh("mokutil", "--sb-state").lower()
        state = "on" if "enabled" in sb else ("off" if "disabled" in sb else "unknown")
        return {"mode": "uefi", "secure_boot": state}
    return {"mode": "bios", "secure_boot": "n/a"}


def memory_mb():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def cpu():
    model, cores = "", 0
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name") and not model:
                model = line.split(":", 1)[1].strip()
            if line.startswith("processor"):
                cores += 1
    except OSError:
        pass
    return {"model": re.sub(r"\s+", " ", model), "cores": cores}


def gpu():
    out = sh("lspci", "-d", "::0300") + sh("lspci", "-d", "::0302")
    lines = [l.split(":", 2)[-1].strip() for l in out.splitlines() if l.strip()]
    if not lines:
        return "none"
    l = lines[0].lower()
    for vendor in ("nvidia", "amd", "intel", "qemu", "red hat", "vmware", "virtio", "bochs", "aspeed", "matrox"):
        if vendor in l:
            return vendor.replace("red hat", "virtio")
    return "other"


def virtual():
    v = sh("systemd-detect-virt").strip()
    return v if v and v != "none" else "none"


def dmi(name):
    try:
        return open(f"/sys/class/dmi/id/{name}").read().strip()
    except OSError:
        return ""


# Intel Macs with the T2 chip (2018 on). The bridge device (106b:1801) is the proof; the models are the fallback
# when PCI cannot be read (and what a test machine claims through SMBIOS).
T2_MODELS = ("MacBookPro15,", "MacBookPro16,", "MacBookAir8,", "MacBookAir9,", "Macmini8,", "iMac20,", "iMacPro1,", "MacPro7,")


def apple():
    """The Mac, when this is one: the model, whether it has the T2 chip, whether the bridge device is seen."""
    vendor, model = dmi("sys_vendor"), dmi("product_name")
    if not vendor.startswith("Apple"):
        return {"mac": False, "model": "", "t2": False, "bce": False}
    bce = False
    for dev in glob.glob("/sys/bus/pci/devices/*"):
        try:
            if open(dev + "/vendor").read().strip() == "0x106b" and open(dev + "/device").read().strip() == "0x1801":
                bce = True
        except OSError:
            pass
    return {"mac": True, "model": model, "t2": bce or model.startswith(T2_MODELS), "bce": bce}


def facts(cdrom="/cdrom"):
    fw = firmware()
    return {
        "disks": disks(cdrom), "medium": medium_device(cdrom), "firmware": fw["mode"], "secure_boot": fw["secure_boot"],
        "memory_mb": memory_mb(), "cpu": cpu(), "gpu": gpu(), "virtual": virtual(), "apple": apple(),
    }


def wired_interfaces():
    """[(name, has_link, [ipv4])] for the wired interfaces, lo and wireless excluded."""
    out = []
    try:
        links = json.loads(sh("ip", "-j", "addr") or "[]")
    except ValueError:
        links = []
    for l in links:
        name = l.get("ifname") or ""
        if name == "lo" or name.startswith(("wl", "docker", "veth", "br-", "virbr", "tun", "tap")):
            continue
        if os.path.isdir(f"/sys/class/net/{name}/wireless"):
            continue
        a4 = [a["local"] for a in l.get("addr_info") or [] if a.get("family") == "inet"]
        out.append((name, l.get("operstate") == "UP", a4))
    return out
