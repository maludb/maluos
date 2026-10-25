"""GPU facts for a MaluOS host (Phase 13, shared GPUs, slice G1; docs/phase13-shared-gpus.md).

One reader for `maluctl gpu status`, the desktop session's host state (the System Monitor's
GPUs tab reads that) and, later, the estate report. NVIDIA through nvidia-smi when the driver
is installed (the `nvidia` component), AMD and Intel through /sys/class/drm; virtual display
adapters (QEMU, virtio, VMware) are not GPUs and are not listed. The chassis decides the
sharing rule the owner set on 2026-10-25: a server shares always, a dedicated desktop is
opt-in, a laptop is opt-in and shares only while idle.

    status() -> {"gpus": [...], "chassis": "server|desktop|laptop|vm|container|unknown",
                 "contribution_rule": "always|opt-in|opt-in-idle", "nvidia_smi": bool}

Every GPU: vendor, model, index, pci, driver, vram_mb, vram_used_mb, busy_pct, temp_c, power_w,
power_limit_w, compute (NVIDIA's compute capability), uuid; a value the driver does not give
is None. Environment: MALUOS_GPU_SYSFS (the drm class directory, for tests),
MALUOS_NVIDIA_SMI (the binary), MALUOS_CHASSIS (a forced chassis).
"""
import os, shutil, subprocess

SYSFS = os.environ.get("MALUOS_GPU_SYSFS", "/sys/class/drm")
DMI_CHASSIS = "/sys/class/dmi/id/chassis_type"
PCI_IDS = ("/usr/share/misc/pci.ids", "/usr/share/hwdata/pci.ids")
NVIDIA_FIELDS = ("index", "name", "uuid", "pci.bus_id", "driver_version", "memory.total", "memory.used",
                 "utilization.gpu", "temperature.gpu", "power.draw", "power.limit", "compute_cap")
VENDORS = {0x10de: "nvidia", 0x1002: "amd", 0x8086: "intel"}
VIRTUAL_VENDORS = {0x1234, 0x1af4, 0x15ad, 0x1b36, 0x80ee}     # QEMU/bochs, virtio, VMware, Red Hat, VirtualBox
RULES = {"server": "always", "vm": "always", "container": "always", "desktop": "opt-in", "laptop": "opt-in-idle"}
# SMBIOS chassis types (System Enclosure, 7.4.1), the ones hostnamectl maps the same way
DMI_KINDS = {3: "desktop", 4: "desktop", 5: "desktop", 6: "desktop", 7: "desktop", 13: "desktop", 15: "desktop", 16: "desktop",
             34: "desktop", 35: "desktop", 36: "desktop", 8: "laptop", 9: "laptop", 10: "laptop", 11: "laptop", 14: "laptop",
             31: "laptop", 32: "laptop", 17: "server", 23: "server", 28: "server", 29: "server"}


def _pci(v):
    """'00000000:01:00.0' (nvidia-smi) or '0000:03:00.0' (sysfs) -> '01:00.0'; a non-zero domain is kept."""
    if not v:
        return None
    v = v.strip().lower()
    dom, sep, rest = v.partition(":")
    return rest if sep and rest and dom.strip("0") == "" else v


def _num(v):
    if v is None:
        return None
    v = v.strip()
    if not v or v.startswith("[") or v.upper() in ("N/A", "NA"):
        return None
    try:
        return int(v) if v.lstrip("-").isdigit() else float(v)
    except ValueError:
        return None


def nvidia_smi_path():
    return os.environ.get("MALUOS_NVIDIA_SMI") or shutil.which("nvidia-smi")


def nvidia(run=subprocess.run, smi=None):
    """GPUs nvidia-smi reports; [] when the binary or the driver is absent."""
    smi = smi or nvidia_smi_path()
    if not smi:
        return []
    fields = list(NVIDIA_FIELDS)
    for attempt in (0, 1):
        try:
            r = run([smi, "--query-gpu=" + ",".join(fields), "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return []
        if r.returncode == 0:
            break
        if attempt == 0 and "compute_cap" in (r.stderr or "") + (r.stdout or ""):
            fields.remove("compute_cap"); continue          # an older nvidia-smi without that field
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(fields) - 1:
            continue
        row = dict(zip(fields, parts))
        out.append({"vendor": "nvidia", "index": _num(row.get("index")), "model": row.get("name") or "NVIDIA GPU",
                    "uuid": row.get("uuid") or None, "pci": _pci(row.get("pci.bus_id")),
                    "driver": row.get("driver_version") or None, "vram_mb": _num(row.get("memory.total")), "vram_used_mb": _num(row.get("memory.used")),
                    "busy_pct": _num(row.get("utilization.gpu")), "temp_c": _num(row.get("temperature.gpu")),
                    "power_w": _num(row.get("power.draw")), "power_limit_w": _num(row.get("power.limit")),
                    "compute": row.get("compute_cap") or None})
    return out


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _hex(path):
    v = _read(path)
    try:
        return int(v, 16) if v else None
    except ValueError:
        return None


_pci_names = None


def pci_name(vendor, device):
    """'Navi 31 [Radeon RX 7900 XTX]' from pci.ids when it is on the host, else None."""
    global _pci_names
    if _pci_names is None:
        _pci_names = {}
        for p in PCI_IDS:
            if not os.path.exists(p):
                continue
            cur = None
            try:
                with open(p, errors="replace") as f:
                    for line in f:
                        if not line or line[0] == "#":
                            continue
                        if line[0] == "\t":
                            if line[1] != "\t" and cur is not None:
                                did, _, name = line[1:].rstrip("\n").partition("  ")
                                try:
                                    _pci_names[(cur, int(did, 16))] = name.strip()
                                except ValueError:
                                    pass
                        else:
                            vid = line[:4]
                            try:
                                cur = int(vid, 16)
                            except ValueError:
                                cur = None
            except OSError:
                pass
            break
    return _pci_names.get((vendor, device))


def sysfs(root=None, skip_nvidia=False):
    """GPUs under /sys/class/drm/cardN (not the connectors cardN-*); amdgpu gives busy, VRAM, temperature and power."""
    root = root or SYSFS
    out = []
    try:
        names = sorted(n for n in os.listdir(root) if n.startswith("card") and "-" not in n)
    except OSError:
        return out
    for n in names:
        dev = os.path.join(root, n, "device")
        vendor, device = _hex(os.path.join(dev, "vendor")), _hex(os.path.join(dev, "device"))
        if vendor is None or vendor in VIRTUAL_VENDORS:
            continue
        kind = VENDORS.get(vendor, "other")
        if kind == "nvidia" and skip_nvidia:
            continue
        driver = None
        for line in (_read(os.path.join(dev, "uevent"), "") or "").splitlines():
            if line.startswith("DRIVER="):
                driver = line[7:]
        if driver is None:
            try:
                driver = os.path.basename(os.readlink(os.path.join(dev, "driver")))
            except OSError:
                pass
        pci = None
        try:
            pci = os.path.basename(os.path.realpath(dev))
            if ":" not in pci:
                pci = None
        except OSError:
            pass
        g = {"vendor": kind, "index": _num(n[4:]), "model": pci_name(vendor, device) or f"{kind} GPU {vendor:04x}:{(device or 0):04x}",
             "uuid": None, "pci": _pci(pci), "driver": driver, "vram_mb": None, "vram_used_mb": None,
             "busy_pct": None, "temp_c": None, "power_w": None, "power_limit_w": None, "compute": None}
        if driver == "amdgpu" or os.path.exists(os.path.join(dev, "mem_info_vram_total")):
            t, u = _num(_read(os.path.join(dev, "mem_info_vram_total"))), _num(_read(os.path.join(dev, "mem_info_vram_used")))
            g["vram_mb"] = int(t // (1024 * 1024)) if t else None
            g["vram_used_mb"] = int(u // (1024 * 1024)) if u is not None else None
            g["busy_pct"] = _num(_read(os.path.join(dev, "gpu_busy_percent")))
        hw = os.path.join(dev, "hwmon")
        try:
            hwmons = sorted(os.listdir(hw))
        except OSError:
            hwmons = []
        for h in hwmons:
            base = os.path.join(hw, h)
            t = _num(_read(os.path.join(base, "temp1_input")))
            if t is not None and g["temp_c"] is None:
                g["temp_c"] = round(t / 1000)
            p = _num(_read(os.path.join(base, "power1_average"))) or _num(_read(os.path.join(base, "power1_input")))
            if p is not None and g["power_w"] is None:
                g["power_w"] = round(p / 1_000_000, 1)
            cap = _num(_read(os.path.join(base, "power1_cap")))
            if cap is not None and g["power_limit_w"] is None:
                g["power_limit_w"] = round(cap / 1_000_000, 1)
        out.append(g)
    return out


def gpus(run=subprocess.run):
    nv = nvidia(run=run)
    return nv + sysfs(skip_nvidia=bool(nv))


def chassis(run=subprocess.run):
    """server, desktop, laptop, vm, container or unknown: hostnamectl's answer, else the DMI enclosure type."""
    forced = os.environ.get("MALUOS_CHASSIS")
    if forced:
        return forced
    try:
        r = run(["hostnamectl", "chassis"], capture_output=True, text=True, timeout=5)
        c = (r.stdout or "").strip()
        if r.returncode == 0 and c:
            return {"handset": "laptop", "tablet": "laptop", "convertible": "laptop", "watch": "laptop", "embedded": "server"}.get(c, c)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        r = run(["systemd-detect-virt", "--quiet"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return "vm"
    except (OSError, subprocess.SubprocessError):
        pass
    t = _num(_read(DMI_CHASSIS))
    return DMI_KINDS.get(t, "unknown") if t is not None else "unknown"


def contribution_rule(kind):
    return RULES.get(kind, "opt-in")


def share_state(conf, tcp, run=subprocess.run):
    """The gateway's GPU sharing switch resolved against the chassis rule (gateway.yaml `share:` and `tcp:`).

    enabled unset means the rule (a server shares, the others when the owner opts in); contribution unset
    means always, or idle on a laptop; exposed says whether the TCP listener faces the network (slice G2)."""
    conf = conf if isinstance(conf, dict) else {}
    tcp = tcp if isinstance(tcp, dict) else {}
    kind = chassis(run=run); rule = contribution_rule(kind)
    enabled = conf.get("enabled")
    if enabled is None:
        enabled = rule == "always"
    contribution = conf.get("contribution") or ("idle" if rule == "opt-in-idle" else "always")
    host = str(tcp.get("host") or "127.0.0.1")
    return {"enabled": bool(enabled), "contribution": contribution, "chassis": kind, "rule": rule,
            "configured": conf.get("enabled") is not None,
            "exposed": bool(tcp.get("enabled")) and host not in ("127.0.0.1", "localhost", "::1")}


def status(run=subprocess.run):
    kind = chassis(run=run)
    return {"gpus": gpus(run=run), "chassis": kind, "contribution_rule": contribution_rule(kind), "nvidia_smi": bool(nvidia_smi_path())}


def describe(g):
    """One line for a terminal: 'nvidia  NVIDIA GeForce RTX 5090  32768 MB (21000 used)  37 % busy  61 °C  310/575 W  driver 595.99.02'."""
    parts = [g["vendor"], g["model"]]
    if g.get("vram_mb"):
        parts.append(f"{g['vram_mb']} MB" + (f" ({g['vram_used_mb']} used)" if g.get("vram_used_mb") is not None else ""))
    if g.get("busy_pct") is not None:
        parts.append(f"{g['busy_pct']} % busy")
    if g.get("temp_c") is not None:
        parts.append(f"{g['temp_c']} °C")
    if g.get("power_w") is not None:
        parts.append(f"{g['power_w']}" + (f"/{g['power_limit_w']}" if g.get("power_limit_w") else "") + " W")
    if g.get("driver"):
        parts.append(f"driver {g['driver']}")
    if g.get("compute"):
        parts.append(f"compute {g['compute']}")
    return "  ".join(str(p) for p in parts)
