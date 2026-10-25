"""storage: the disk erased and laid out, filesystems made, LUKS and LVM when asked, mounted under /target.

GPT always; a 1 MiB BIOS boot partition always; the ESP; /boot as its own
ext4 partition whenever the root is encrypted or on LVM; then the root.

  layout  encrypt  after ESP and BIOS boot                      root device
  direct  false    root                                          /dev/DISKp3
  direct  true     /boot, LUKS2 (rest)                           /dev/mapper/maluos-root
  lvm     false    /boot, PV (rest) -> VG maluos -> LV root      /dev/maluos/root
  lvm     true     /boot, LUKS2 (rest) -> PV maluos-pv -> VG maluos -> LV root

storage.target free (the Apple T2 round) keeps the disk's partitions: the new
partitions go into the largest free region, the disk's own EFI system partition is
shared (mounted, not formatted), no BIOS boot partition is made (UEFI only).

compute_layout() is pure (the unit test drives it); apply() runs the commands.
"""
import os, re

from .. import disks as disksmod
from ..plan import parse_size, fmt_size

MIB = 1 << 20
GIB = 1 << 30
TYPE = {
    "bios": "21686148-6449-6E6F-744E-656564454649",
    "esp": "C12A7328-F81F-11D2-BA4B-00A0C93EC93B",
    "linux": "0FC63DAF-8483-4772-8E79-3D69D8477DE4",
    "root": "4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709",
    "lvm": "E6D6D379-F507-44C2-A23C-238F2A3DF928",
    "luks": "CA7D7CCB-63ED-4C53-861C-1742536059CC",
}
LUKS_OVERHEAD = 32 * MIB   # LUKS2 header and PV metadata, generously
MIN_ROOT = 8 * GIB


def partdev(disk, n):
    """/dev/sda + 3 -> /dev/sda3; /dev/nvme0n1 + 3 -> /dev/nvme0n1p3."""
    return f"{disk}p{n}" if disk[-1].isdigit() else f"{disk}{n}"


def swap_bytes(spec, memory_bytes):
    s = parse_size(spec)
    if s == "none":
        return 0
    if s == "auto":
        return max(min(memory_bytes, 8 * GIB) // MIB * MIB, 0)
    return int(s)


def compute_layout(st, disk_path, disk_bytes, memory_bytes, table=None, sector=512):
    """The plan's storage section + a disk -> partitions, devices, sizes, errors.
    table and sector are the disk's facts (disks.partition_table); storage.target free needs them."""
    errors = []
    esp = parse_size(st["esp_size"]); boot = parse_size(st["boot_size"])
    root_size = parse_size(st["root_size"])
    encrypt, lvm = bool(st["encrypt"]), st["layout"] == "lvm"
    separate_boot = encrypt or lvm
    swap = swap_bytes(st["swap"], memory_bytes)
    free = st.get("target") == "free"
    table = table or {}
    created = []
    if free:
        if table.get("label") != "gpt":
            errors.append(f"{disk_path} has no GPT partition table; storage.target free keeps what is there, so it needs one (or erase the disk)")
        if not table.get("esp"):
            errors.append(f"{disk_path} has no EFI system partition to share; storage.target free needs one (or erase the disk)")
        regions = sorted(table.get("free") or [], key=lambda f: f["size"], reverse=True)
        region = regions[0] if regions else {"start": 0, "size": 0}
        if not regions:
            errors.append(f"{disk_path} has no free space; shrink a partition first (in macOS: Disk Utility, the APFS container) or erase the disk")
        n = max([p["n"] for p in table.get("parts") or []] + [0]) + 1
        parts = []
        cursor = region["start"]
        if separate_boot:
            parts.append({"n": n, "name": "boot", "type": TYPE["linux"], "size": boot, "fs": "ext4", "mount": "/boot", "start": cursor}); n += 1
            cursor += boot
        fixed = sum(p["size"] for p in parts)
        remaining = region["size"] - fixed
    else:
        parts = [{"n": 1, "name": "bios_grub", "type": TYPE["bios"], "size": MIB, "fs": None, "mount": None},
                 {"n": 2, "name": "ESP", "type": TYPE["esp"], "size": esp, "fs": "vfat", "mount": "/boot/efi"}]
        n = 3
        if separate_boot:
            parts.append({"n": n, "name": "boot", "type": TYPE["linux"], "size": boot, "fs": "ext4", "mount": "/boot"}); n += 1
        fixed = sum(p["size"] for p in parts) + 2 * MIB
        remaining = disk_bytes - fixed
        region = None
    luks = lvm_info = None
    if not lvm and not encrypt:
        size = None if root_size == "all" else root_size
        parts.append({"n": n, "name": "root", "type": TYPE["root"], "size": size, "fs": st["filesystem"], "mount": "/"})
        root_dev = partdev(disk_path, n)
        root_bytes = remaining if size is None else size
        if size is not None and size > remaining:
            errors.append(f"root_size {st['root_size']} does not fit: {fmt_size(max(remaining, 0))} left after the ESP")
    elif not lvm and encrypt:
        parts.append({"n": n, "name": "maluos-crypt", "type": TYPE["luks"], "size": None, "fs": "crypto_LUKS", "mount": None})
        luks = {"dev": partdev(disk_path, n), "name": "maluos-root", "label": "maluos-crypt"}
        root_dev = "/dev/mapper/maluos-root"
        root_bytes = remaining - LUKS_OVERHEAD
        if root_size != "all":
            errors.append("root_size is 'all' for layout direct with encrypt (the LUKS volume takes the rest)")
    else:
        if encrypt:
            parts.append({"n": n, "name": "maluos-crypt", "type": TYPE["luks"], "size": None, "fs": "crypto_LUKS", "mount": None})
            luks = {"dev": partdev(disk_path, n), "name": "maluos-pv", "label": "maluos-crypt"}
            pv = "/dev/mapper/maluos-pv"
        else:
            parts.append({"n": n, "name": "maluos-pv", "type": TYPE["lvm"], "size": None, "fs": "LVM2_member", "mount": None})
            pv = partdev(disk_path, n)
        pv_bytes = remaining - LUKS_OVERHEAD
        lv_size = None if root_size == "all" else root_size
        if lv_size is not None and lv_size > pv_bytes:
            lv_size = None   # the plan's default 50G on a smaller disk: take the disk
        lvm_info = {"pv": pv, "vg": "maluos", "lv": "root", "size": lv_size}
        root_dev = "/dev/maluos/root"
        root_bytes = pv_bytes if lv_size is None else lv_size
    if root_bytes < MIN_ROOT:
        where = f"free space {fmt_size(region['size'])}" if free else f"disk {fmt_size(disk_bytes)}"
        errors.append(f"the root would be {fmt_size(max(root_bytes, 0))}; at least 8G is needed ({where})")
    if swap and root_bytes - swap < MIN_ROOT:
        errors.append(f"no room for the {fmt_size(swap)} swap file beside an 8G root; set storage.swap smaller or none")
    if free:
        # every new partition gets an explicit start and size (sfdisk --append must not guess); the last takes the region's rest
        cursor = region["start"]
        for p in parts:
            p["start"] = cursor
            if p["size"] is None:
                p["size"] = max(region["start"] + region["size"] - cursor, 0)
            cursor += p["size"]
        created = [p["n"] for p in parts]
        esp_n = table["esp"]["n"] if table.get("esp") else 0
        esp_dev = table["esp"]["node"] if table.get("esp") else partdev(disk_path, esp_n or 1)
        boot_dev = partdev(disk_path, parts[0]["n"]) if separate_boot else None
    else:
        esp_n, esp_dev = 2, partdev(disk_path, 2)
        boot_dev = partdev(disk_path, 3) if separate_boot else None
    layout = {
        "disk": disk_path, "disk_bytes": disk_bytes, "parts": parts, "root_dev": root_dev, "root_fs": st["filesystem"],
        "root_bytes": root_bytes, "esp_dev": esp_dev, "esp_n": esp_n, "boot_dev": boot_dev,
        "luks": luks, "lvm": lvm_info, "swap_bytes": swap, "label": st["label"], "errors": errors,
        "mode": "free" if free else "disk", "sector": sector, "created": created, "region": region,
        "kept": len(table.get("parts") or []) if free else 0,
    }
    return layout


def sfdisk_script(layout):
    ss = layout.get("sector") or 512
    if layout.get("mode") == "free":   # appended to the existing table: start and size given, in the disk's sectors
        lines = []
        for p in layout["parts"]:
            lines.append(f"start={p['start'] // ss}, size={p['size'] // ss}, type={p['type']}, name=\"{p['name']}\"")
        return "\n".join(lines) + "\n"
    lines = ["label: gpt", "unit: sectors", ""]
    for p in layout["parts"]:
        fields = []
        if p["size"] is not None:
            fields.append(f"size={p['size'] // ss}")
        fields.append(f"type={p['type']}")
        fields.append(f'name="{p["name"]}"')
        lines.append(", ".join(fields))
    return "\n".join(lines) + "\n"


def describe(layout):
    parts = []
    for p in layout["parts"]:
        size = "rest" if p["size"] is None else fmt_size(p["size"])
        parts.append(f"{p['n']}:{p['name']} {size}")
    extra = []
    if layout["luks"]:
        extra.append(f"LUKS2 {layout['luks']['name']}")
    if layout["lvm"]:
        l = layout["lvm"]
        extra.append(f"VG {l['vg']} LV {l['lv']} {'all' if l['size'] is None else fmt_size(l['size'])}")
    extra.append(f"root {layout['root_fs']} on {layout['root_dev']}")
    extra.append("swap " + (fmt_size(layout["swap_bytes"]) + " file" if layout["swap_bytes"] else "none"))
    if layout.get("mode") == "free":
        r = layout.get("region") or {}
        head = (f"{layout['disk']} ({fmt_size(layout['disk_bytes'])}), {layout.get('kept', 0)} partitions kept, "
                f"the EFI partition {layout['esp_dev']} shared; into the free {fmt_size(r.get('size', 0))} at {fmt_size(r.get('start', 0))}: ")
        return head + ", ".join(parts) + "; " + "; ".join(extra)
    return f"{layout['disk']} ({fmt_size(layout['disk_bytes'])}): " + ", ".join(parts) + "; " + "; ".join(extra)


# --- the step ---------------------------------------------------------------------
def _layout(ctx):
    st = ctx.plan["storage"]
    cands = ctx.facts["disks"]
    disk = disksmod.resolve_disk(st["disk"], cands)
    layout = compute_layout(st, disk["path"], disk["size"], ctx.facts["memory_mb"] * MIB, table=disk.get("table"), sector=disk.get("sector", 512))
    layout["disk_info"] = disk
    return layout


def check(ctx):
    try:
        layout = _layout(ctx)
    except ValueError as e:
        return [str(e)]
    ctx.state["storage"] = layout
    errs = list(layout["errors"])
    d = layout["disk_info"]
    if d.get("in_use") and layout["mode"] == "disk":
        errs.append(f"{d['path']} has mounted filesystems; unmount them first (the live system must not be using the target)")
    if layout["mode"] == "free" and ctx.facts.get("firmware") != "uefi":
        errs.append("storage.target free installs beside the existing systems on UEFI only (no BIOS boot partition is made), but the live environment booted with BIOS firmware")
    if ctx.plan["storage"]["encrypt"] and not ctx.plan["storage"]["passphrase"]:
        errs.append("a passphrase is required for an encrypted root")
    # another VG named maluos elsewhere would collide
    if layout["lvm"] and not ctx.dry_run:
        out = disksmod.sh("vgs", "--noheadings", "-o", "vg_name,pv_name")
        for line in out.splitlines():
            f = line.split()
            if len(f) == 2 and f[0] == "maluos" and not f[1].startswith(layout["disk"]):
                errs.append(f"a volume group named maluos already exists on {f[1]}; the installer cannot create a second one")
    if not errs:
        ctx.info(describe(layout))
    return errs


def summary(ctx):
    l = ctx.state.get("storage")
    return "storage: " + (describe(l) if l else "the disk laid out, filesystems made, mounted under /target")


def _release_disk(ctx, disk):
    """Anything the live system holds on the target disk: swap, mounts, LUKS mappings, VGs."""
    for line in disksmod.sh("swapon", "--noheadings", "--show=NAME").splitlines():
        if line.strip().startswith(disk):
            ctx.run(["swapoff", line.strip()], check=False)
    out = disksmod.sh("lsblk", "-rno", "NAME,TYPE,MOUNTPOINTS", disk)
    for line in out.splitlines():
        f = line.split(None, 2)
        if len(f) == 3 and f[2]:
            for mp in f[2].split("\\x0a"):
                if mp and mp != "[SWAP]":
                    ctx.run(["umount", "-l", mp], check=False)
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 2 and f[1] == "crypt":
            ctx.run(["cryptsetup", "close", f[0]], check=False)
    for line in disksmod.sh("pvs", "--noheadings", "-o", "pv_name,vg_name").splitlines():
        f = line.split()
        if len(f) == 2 and f[0].startswith(disk):
            ctx.run(["vgchange", "-an", f[1]], check=False)
            ctx.run(["vgremove", "-ff", "-y", f[1]], check=False)
    out = disksmod.sh("lsblk", "-rno", "NAME,TYPE", disk)
    for line in out.splitlines():
        f = line.split()
        if len(f) == 2 and f[1] == "crypt":
            ctx.run(["cryptsetup", "close", f[0]], check=False)


def _release_created(ctx, layout):
    """A resume of storage.target free: the partitions an earlier attempt appended are deleted first, their LVM and LUKS closed."""
    saved = (ctx.journal.get("state") or {}).get("storage") or {}
    created = saved.get("created") or []
    if not created or saved.get("disk") != layout["disk"]:
        return
    disk = layout["disk"]
    for line in disksmod.sh("lsblk", "-rno", "NAME,TYPE", disk).splitlines():
        f = line.split()
        if len(f) == 2 and f[1] == "crypt":
            ctx.run(["cryptsetup", "close", f[0]], check=False)
    for line in disksmod.sh("pvs", "--noheadings", "-o", "pv_name,vg_name").splitlines():
        f = line.split()
        if len(f) == 2 and f[0].startswith(disk) and f[0] in [partdev(disk, n) for n in created]:
            ctx.run(["vgchange", "-an", f[1]], check=False)
            ctx.run(["vgremove", "-ff", "-y", f[1]], check=False)
    existing = {p["n"] for p in disksmod.partition_table(disk)["parts"]}
    for n in created:
        if n in existing:
            ctx.run(["umount", "-l", partdev(disk, n)], check=False, quiet=True)
            ctx.run(["wipefs", "-a", "-f", partdev(disk, n)], check=False, quiet=True)
            ctx.run(["sfdisk", "--quiet", "--delete", disk, str(n)])
    ctx.run(["udevadm", "settle"], check=False)


def apply(ctx):
    layout = ctx.state.get("storage") or _layout(ctx)
    ctx.state["storage"] = layout
    disk, st = layout["disk"], ctx.plan["storage"]
    free = layout.get("mode") == "free"
    if free:
        with ctx.substep("erase", f"keeping the {layout.get('kept', 0)} partitions of {disk}; the free {fmt_size(layout['region']['size'])} at {fmt_size(layout['region']['start'])} is used"):
            _release_created(ctx, layout)
    else:
        with ctx.substep("erase", f"erasing {disk}"):
            _release_disk(ctx, disk)
            for p in layout["parts"]:
                ctx.run(["wipefs", "-a", "-f", partdev(disk, p["n"])], check=False, quiet=True)
            ctx.run(["wipefs", "-a", "-f", disk])
    with ctx.substep("partition", ("appending to the GPT (" if free else "writing the GPT (") + ", ".join(p["name"] for p in layout["parts"]) + ")"):
        script = sfdisk_script(layout)
        ctx.log_text(script)
        if free:
            ctx.run(["sfdisk", "--append", "--wipe-partitions", "always", "--quiet", disk], input=script)
        else:
            ctx.run(["sfdisk", "--wipe", "always", "--wipe-partitions", "always", "--quiet", disk], input=script)
        ctx.run(["udevadm", "settle"], check=False)
        ctx.run(["blockdev", "--rereadpt", disk], check=False)
        ctx.run(["udevadm", "settle"], check=False)
        if free and not ctx.dry_run:
            now = {p["n"] for p in disksmod.partition_table(disk)["parts"]}
            missing = [n for n in layout["created"] if n not in now]
            if missing:
                raise RuntimeError(f"sfdisk did not append partition(s) {missing} to {disk}")
    with ctx.substep("mkfs-boot", ("the EFI partition shared" if free else "the ESP") + (" and /boot" if layout["boot_dev"] else "")):
        if free:
            fs = disksmod.sh("blkid", "-s", "TYPE", "-o", "value", layout["esp_dev"]).strip() if not ctx.dry_run else "vfat"
            if fs != "vfat":
                raise RuntimeError(f"the EFI partition {layout['esp_dev']} is {fs or 'unformatted'}, not vfat; it cannot be shared")
            ctx.info(f"{layout['esp_dev']} kept as it is (the firmware's and macOS's loaders stay)")
        else:
            ctx.run(["mkfs.vfat", "-F", "32", "-n", "ESP", layout["esp_dev"]])
        if layout["boot_dev"]:
            ctx.run(["mkfs.ext4", "-q", "-F", "-L", "boot", layout["boot_dev"]])
    if layout["luks"]:
        l = layout["luks"]
        with ctx.substep("luks", f"LUKS2 on {l['dev']} (argon2id), opened as {l['name']}"):
            ctx.run(["cryptsetup", "-q", "--batch-mode", "luksFormat", "--type", "luks2", "--pbkdf", "argon2id",
                     "--label", l["label"], "--key-file", "-", l["dev"]], input=st["passphrase"], secret=True)
            ctx.run(["cryptsetup", "open", "--key-file", "-", l["dev"], l["name"]], input=st["passphrase"], secret=True)
    if layout["lvm"]:
        v = layout["lvm"]
        with ctx.substep("lvm", f"PV {v['pv']}, VG {v['vg']}, LV {v['lv']}"):
            ctx.run(["pvcreate", "-ff", "-y", v["pv"]])
            ctx.run(["vgcreate", "-y", v["vg"], v["pv"]])
            if v["size"] is None:
                ctx.run(["lvcreate", "-y", "-l", "100%FREE", "-n", v["lv"], v["vg"]])
            else:
                ctx.run(["lvcreate", "-y", "-L", f"{v['size'] // MIB}m", "-n", v["lv"], v["vg"]])
            ctx.run(["udevadm", "settle"], check=False)
    with ctx.substep("mkfs-root", f"{layout['root_fs']} on {layout['root_dev']} (label {layout['label']})"):
        if layout["root_fs"] == "xfs":
            ctx.run(["mkfs.xfs", "-f", "-q", "-L", layout["label"], layout["root_dev"]])
        else:
            ctx.run(["mkfs.ext4", "-q", "-F", "-L", layout["label"], layout["root_dev"]])
    with ctx.substep("mount", f"mounting under {ctx.target}"):
        _mount_all(ctx, layout)
    if not ctx.dry_run:
        layout["uuids"] = {
            "root": disksmod.sh("blkid", "-s", "UUID", "-o", "value", layout["root_dev"]).strip(),
            "esp": disksmod.sh("blkid", "-s", "UUID", "-o", "value", layout["esp_dev"]).strip(),
            "boot": disksmod.sh("blkid", "-s", "UUID", "-o", "value", layout["boot_dev"]).strip() if layout["boot_dev"] else None,
            "luks": disksmod.sh("blkid", "-s", "UUID", "-o", "value", layout["luks"]["dev"]).strip() if layout["luks"] else None,
        }
        if not layout["uuids"]["root"] or not layout["uuids"]["esp"]:
            raise RuntimeError("blkid found no UUID on the new filesystems")
    else:
        layout["uuids"] = {"root": "<root-uuid>", "esp": "<esp-uuid>", "boot": "<boot-uuid>" if layout["boot_dev"] else None,
                           "luks": "<luks-uuid>" if layout["luks"] else None}
    ctx.journal["state"] = {"storage": {k: v for k, v in layout.items() if k != "disk_info"}}
    ctx.save_journal()


def _mount_all(ctx, layout):
    ctx.run(["mkdir", "-p", ctx.target])
    ctx.run(["mount", layout["root_dev"], ctx.target])
    if layout["boot_dev"]:
        ctx.run(["mkdir", "-p", ctx.tpath("boot")])
        ctx.run(["mount", layout["boot_dev"], ctx.tpath("boot")])
    ctx.run(["mkdir", "-p", ctx.tpath("boot/efi")])
    ctx.run(["mount", layout["esp_dev"], ctx.tpath("boot/efi")])


def ensure_mounted(ctx):
    """On a resume: the layout from the journal, the LUKS and VG opened, everything mounted."""
    saved = (ctx.journal.get("state") or {}).get("storage")
    if not saved:
        raise RuntimeError("the journal has no storage state to resume from")
    ctx.state["storage"] = saved
    if os.path.ismount(ctx.target):
        return
    if saved["luks"]:
        l = saved["luks"]
        if not os.path.exists(f"/dev/mapper/{l['name']}"):
            ctx.run(["cryptsetup", "open", "--key-file", "-", l["dev"], l["name"]], input=ctx.plan["storage"]["passphrase"], secret=True)
    if saved["lvm"]:
        ctx.run(["vgchange", "-ay", saved["lvm"]["vg"]])
    ctx.run(["udevadm", "settle"], check=False)
    _mount_all(ctx, saved)


def release(ctx):
    """Unmount the target in reverse, close LUKS, deactivate the VG (the finish step)."""
    layout = ctx.state.get("storage") or {}
    ctx.umount_chroot()
    for rel in ("boot/efi", "boot", ""):
        p = ctx.tpath(rel) if rel else ctx.target
        if ctx.dry_run or os.path.ismount(p):
            ctx.run(["umount", p], check=False)
    if layout.get("lvm"):
        ctx.run(["vgchange", "-an", layout["lvm"]["vg"]], check=False)
    if layout.get("luks"):
        ctx.run(["cryptsetup", "close", layout["luks"]["name"]], check=False)
