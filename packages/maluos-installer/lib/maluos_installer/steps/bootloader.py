"""bootloader: the target's own grub, run in the chroot. BIOS to the disk; UEFI with Secure Boot to the ESP.

The EFI directory stays `ubuntu`: Ubuntu's signed grub has that prefix built
in and reads its stub grub.cfg there (a path, not a surface; see the qcow2
build). Only the NVRAM entry carries the plan's label (`MaluOS`), written with
efibootmgr and put first. EFI/BOOT/BOOTX64.EFI is written too, for a disk
that moves or a firmware without entries.
"""
import os, re

from .. import disks as disksmod


def mode(ctx):
    m = ctx.plan["bootloader"]["mode"]
    if m == "auto":
        return ctx.facts["firmware"]
    return m


def check(ctx):
    errs = []
    m = mode(ctx)
    fw = ctx.facts["firmware"]
    if m == "uefi" and fw != "uefi":
        errs.append("bootloader.mode uefi, but the live environment booted with BIOS firmware (no efivars to write)")
    if m == "bios" and fw == "uefi":
        ctx.warn("bootloader.mode bios on a UEFI machine: the firmware must boot in legacy mode")
    if ctx.plan["storage"].get("target") == "free" and m in ("bios", "both"):
        errs.append(f"bootloader.mode {m} with storage.target free: no BIOS boot partition is made beside the kept partitions; use uefi (or auto on a UEFI machine)")
    sb = ctx.plan["bootloader"]["secure_boot"]
    if sb == "required" and ctx.facts["secure_boot"] != "on":
        errs.append(f"bootloader.secure_boot required, but Secure Boot is {ctx.facts['secure_boot']}")
    if not ctx.dry_run and fw == "uefi" and not os.path.isdir("/sys/firmware/efi/efivars"):
        errs.append("UEFI firmware but no efivarfs: cannot write a boot entry")
    return errs


def summary(ctx):
    m = mode(ctx)
    what = {"bios": "grub for BIOS", "uefi": "shim and grub for UEFI", "both": "grub for BIOS and shim and grub for UEFI"}[m]
    return f"bootloader: {what}; Secure Boot: Ubuntu's signed shim and grub (state {ctx.facts['secure_boot']}); entry {ctx.plan['bootloader']['efi_entry']}"


def _grub_quiet(out):
    return "\n".join(l for l in out.splitlines() if l.strip() and not re.match(r"^(Installing|Installation finished)", l))


def apply(ctx):
    layout = ctx.state["storage"]
    m = mode(ctx)
    ctx.mount_chroot()
    if m in ("bios", "both") and layout.get("mode") != "free":
        with ctx.substep("grub-bios", f"grub-install --target=i386-pc {layout['disk']}") as go:
            if go:
                ctx.run(["grub-install", "--target=i386-pc", "--no-floppy", layout["disk"]], chroot=True)
    if m in ("uefi", "both"):
        with ctx.substep("grub-efi", "grub-install --target=x86_64-efi (signed shim and grub, EFI/ubuntu and EFI/BOOT)") as go:
            if go:
                ctx.run(["grub-install", "--target=x86_64-efi", "--efi-directory=/boot/efi", "--bootloader-id=ubuntu",
                         "--no-nvram", "--uefi-secure-boot"], chroot=True)
                if not ctx.dry_run:
                    if not os.path.exists(ctx.tpath("boot/efi/EFI/ubuntu/grub.cfg")):
                        raise RuntimeError("grub-install left no EFI/ubuntu/grub.cfg on the ESP")
                    os.makedirs(ctx.tpath("boot/efi/EFI/BOOT"), exist_ok=True)
                ctx.run(["cp", ctx.tpath("boot/efi/EFI/ubuntu/grub.cfg"), ctx.tpath("boot/efi/EFI/BOOT/grub.cfg")])
                for f in ("shimx64.efi", "grubx64.efi", "mmx64.efi"):
                    if ctx.dry_run or os.path.exists(ctx.tpath(f"boot/efi/EFI/ubuntu/{f}")):
                        ctx.run(["cp", ctx.tpath(f"boot/efi/EFI/ubuntu/{f}"), ctx.tpath(f"boot/efi/EFI/BOOT/{'BOOTX64.EFI' if f == 'shimx64.efi' else f}")], check=False)
        if ctx.facts["firmware"] == "uefi":
            label = ctx.plan["bootloader"]["efi_entry"]
            with ctx.substep("efi-entry", f"NVRAM entry {label!r} first in the boot order") as go:
                if go:
                    _efi_entry(ctx, layout, label)
        else:
            ctx.info("BIOS-booted live environment: no NVRAM entry written (EFI/BOOT/BOOTX64.EFI will boot the disk on UEFI)")
    with ctx.substep("update-grub", "update-grub in the target") as go:
        if go:
            out = ctx.run(["update-grub"], chroot=True)
            if not ctx.dry_run:
                cfg = open(ctx.tpath("boot/grub/grub.cfg")).read()
                u = layout["uuids"]["root"]
                if f"root=UUID={u}" not in cfg and f"root={layout['root_dev']}" not in cfg and "root=/dev/mapper" not in cfg:
                    raise RuntimeError("grub.cfg names no root the installed system will have")
                if "/dev/loop" in cfg:
                    raise RuntimeError("grub.cfg references a loop device")


def _efi_entry(ctx, layout, label):
    out = disksmod.sh("efibootmgr")
    ctx.log_text(out)
    # drop stale entries with our label or grub-install's default label for this disk
    for line in out.splitlines():
        m = re.match(r"^Boot([0-9A-Fa-f]{4})\*?\s+(.*?)\t", line + "\t")
        if m and m.group(2).strip() in (label, "ubuntu") and "shimx64.efi" in line.lower():
            ctx.run(["efibootmgr", "-q", "-b", m.group(1), "-B"], check=False)
    mac = bool((ctx.facts.get("apple") or {}).get("mac"))
    r = ctx.run(["efibootmgr", "-q", "-c", "-d", layout["disk"], "-p", str(layout.get("esp_n") or 2), "-L", label, "-l", r"\EFI\ubuntu\shimx64.efi"],
                check=not mac)
    after = disksmod.sh("efibootmgr")
    ctx.log_text(after)
    if mac and not ctx.dry_run and label not in after:
        # Apple's firmware keeps its own list; the disk still boots from EFI/BOOT/BOOTX64.EFI through the Startup Manager
        ctx.warn(f"the Mac's firmware did not take the {label} entry; hold Option at power-on and choose \"EFI Boot\" once, then it is remembered")
        return
    if not ctx.dry_run:
        order = re.search(r"^BootOrder:\s*(.*)$", after, re.M)
        first = order.group(1).split(",")[0].strip() if order else ""
        if first and f"Boot{first}" in after and label not in after.split(f"Boot{first}", 1)[1].splitlines()[0]:
            ctx.warn(f"the firmware did not put {label} first in BootOrder ({order.group(1) if order else '?'})")
