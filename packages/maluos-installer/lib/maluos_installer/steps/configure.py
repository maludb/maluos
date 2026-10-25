"""configure: writes files into the target; runs commands only in the target's chroot.

Sub-steps, each journaled and idempotent: swap, fstab (and crypttab), hostname,
locale, network, identity, apt, components, apple (the Mac's firmware), firstboot,
grub, initrd, machine-id.

The Apple T2 round: on a T2 Mac the apple-t2 component is added when the medium
carries it, the kernel gets the options t2linux documents, the initrd is rebuilt
with the bridge driver, and the Mac's Wi-Fi and Bluetooth firmware is imported.
"""
import glob, json, os, re, shlex, uuid

from .. import disks as disksmod
from ..plan import fmt_size

try:
    import yaml
except ImportError:
    yaml = None


def variant(ctx):
    return (ctx.state.get("image") or {}).get("variant") or ("desktop" if "desktop" in ctx.plan["source"]["image"] else "server")


def check(ctx):
    errs = []
    comps = ctx.plan["components"]
    cat = catalog(ctx)
    if comps["install"] or comps["remove"]:
        if cat is None:
            errs.append("components are asked for but the medium has no /maluos/catalog.yaml")
        else:
            names = {c["name"] for c in cat}
            for c in comps["install"] + comps["remove"]:
                if c not in names:
                    errs.append(f"component {c!r} is not on this medium (catalogue: {', '.join(sorted(names))})")
    ap = ctx.facts.get("apple") or {}
    if ap.get("t2"):
        entry = next((c for c in (cat or []) if c["name"] == APPLE_COMPONENT), None)
        if entry is None:
            ctx.warn(f"Apple {ap.get('model') or 'Mac'} with the T2 chip, but this medium has no {APPLE_COMPONENT} component: "
                     "the installed system will have no internal keyboard, trackpad or audio")
        elif APPLE_COMPONENT in comps["remove"]:
            ctx.warn(f"Apple {ap.get('model')}: the plan removes {APPLE_COMPONENT}; the internal keyboard, trackpad and audio will not work")
        elif APPLE_COMPONENT not in comps["install"] and not entry.get("in_image"):
            comps["install"].append(APPLE_COMPONENT)
            ctx.info(f"Apple {ap.get('model')} with the T2 chip: the {APPLE_COMPONENT} component is added (keyboard, trackpad, Touch Bar, audio, firmware import)")
    net = ctx.plan["network"]
    if net["mode"] == "static" and net["interface"]:
        if not any(n == net["interface"] for n, _, _ in disksmod.wired_interfaces()):
            ctx.warn(f"network.interface {net['interface']} is not an interface of this machine (the name is written as given)")
    tz = ctx.plan["locale"]["timezone"]
    if tz != "auto" and not os.path.exists(f"/usr/share/zoneinfo/{tz}"):
        errs.append(f"locale.timezone {tz!r} is not a known zone")
    return errs


def summary(ctx):
    idn = ctx.plan["identity"]
    return f"configure: host {idn['hostname']}, user {idn['user']['name']}, {variant(ctx)} image, firstboot tenant {ctx.plan['firstboot']['tenant']}"


APPLE_COMPONENT = "maluos-apple-t2"
T2_KERNEL_OPTIONS = "intel_iommu=on iommu=pt pm_async=off"   # what t2linux documents for every T2 Mac


def apple_t2(ctx):
    """True when the installed system is for a T2 Mac: the component is in the plan, or the machine is one."""
    return APPLE_COMPONENT in ctx.plan["components"]["install"] or bool((ctx.facts.get("apple") or {}).get("t2"))


def catalog(ctx):
    p = os.path.join(ctx.media, "maluos/catalog.yaml")
    if not os.path.exists(p) or not yaml:
        return None
    try:
        doc = yaml.safe_load(open(p)) or {}
    except Exception:
        return None
    return doc.get("components") or []


# --- the sub-steps -----------------------------------------------------------------------
def sub_swap(ctx, layout):
    n = layout["swap_bytes"]
    if not n:
        ctx.info("no swap file (storage.swap none)")
        return
    ctx.run(["fallocate", "-l", str(n), ctx.tpath("swap.img")])
    ctx.run(["chmod", "600", ctx.tpath("swap.img")])
    ctx.run(["mkswap", "-q", ctx.tpath("swap.img")])


def sub_fstab(ctx, layout):
    u = layout["uuids"]
    fs = layout["root_fs"]
    opts = "defaults" + (",discard" if fs == "ext4" else "")
    lines = ["# /etc/fstab: written by the MaluOS installer.", f"UUID={u['root']}  /  {fs}  {opts}  0 1"]
    if layout["boot_dev"]:
        lines.append(f"UUID={u['boot']}  /boot  ext4  defaults  0 2")
    lines.append(f"UUID={u['esp']}  /boot/efi  vfat  umask=0077  0 1")
    if layout["swap_bytes"]:
        lines.append("/swap.img  none  swap  sw  0 0")
    ctx.write("/etc/fstab", "\n".join(lines) + "\n")
    if layout["luks"]:
        l = layout["luks"]
        ctx.write("/etc/crypttab", f"{l['name']} UUID={u['luks']} none luks,discard\n", mode=0o600)


def sub_hostname(ctx):
    h = ctx.plan["identity"]["hostname"]
    ctx.write("/etc/hostname", h + "\n")
    ctx.write("/etc/hosts", f"127.0.0.1 localhost\n127.0.1.1 {h}\n\n::1 ip6-localhost ip6-loopback\nff02::1 ip6-allnodes\nff02::2 ip6-allrouters\n")


def sub_locale(ctx):
    loc = ctx.plan["locale"]
    lang = loc["language"]
    ctx.run(["locale-gen", lang], chroot=True, check=False)
    ctx.write("/etc/default/locale", f"LANG={lang}\n")
    kb = loc["keyboard"]
    ctx.write("/etc/default/keyboard", f'XKBMODEL="pc105"\nXKBLAYOUT="{kb["layout"]}"\nXKBVARIANT="{kb["variant"]}"\nXKBOPTIONS=""\nBACKSPACE="guess"\n')
    tz = loc["timezone"]
    if tz == "auto":
        tz = "UTC"   # geolocation comes with the network screen (slice 3)
    ctx.run(["ln", "-sf", f"/usr/share/zoneinfo/{tz}", ctx.tpath("etc/localtime")])
    ctx.write("/etc/timezone", tz + "\n")
    if ctx.texists("/usr/sbin/dpkg-reconfigure") or ctx.dry_run:
        ctx.run(["dpkg-reconfigure", "-f", "noninteractive", "tzdata"], chroot=True, check=False)


def renderer(ctx):
    if ctx.dry_run and not os.path.isdir(ctx.target):
        return "NetworkManager" if variant(ctx) == "desktop" else "networkd"
    return "NetworkManager" if ctx.texists("/usr/sbin/NetworkManager") else "networkd"


def netplan_doc(net, rend):
    if net["mode"] == "none":
        return None
    eth = {}
    if net["mode"] == "dhcp":
        eth["all-en"] = {"match": {"name": "en*"}, "dhcp4": True}
        eth["all-eth"] = {"match": {"name": "eth*"}, "dhcp4": True}
    else:
        iface = net["interface"] or "en*"
        e = {"addresses": [net["address"]], "routes": [{"to": "default", "via": net["gateway"]}]}
        if "*" in iface:
            e["match"] = {"name": iface}
        ns = net["nameservers"] or [net["gateway"]]
        e["nameservers"] = {"addresses": ns}
        if net["search"]:
            e["nameservers"]["search"] = net["search"]
        eth[iface if "*" not in iface else "wired"] = e
    return {"network": {"version": 2, "renderer": rend, "ethernets": eth}}


def sub_network(ctx):
    net = ctx.plan["network"]
    rend = renderer(ctx)
    doc = netplan_doc(net, rend)
    if doc is None:
        ctx.info("network.mode none: netplan left as the image ships it")
    else:
        text = yaml.safe_dump(doc, sort_keys=False) if yaml else json.dumps(doc, indent=2)
        ctx.write("/etc/netplan/50-maluos.yaml", "# Written by the MaluOS installer from the install plan.\n" + text, mode=0o600)
    # the installer owns the network configuration; cloud-init must not write a second one
    ctx.write("/etc/cloud/cloud.cfg.d/99-maluos-install.cfg", "# The MaluOS installer wrote the network configuration.\nnetwork: {config: disabled}\n")
    if net["proxy"]:
        p = net["proxy"]
        ctx.write("/etc/apt/apt.conf.d/50maluos-proxy", f'Acquire::http::Proxy "{p}";\nAcquire::https::Proxy "{p}";\n')
        env = ""
        try:
            env = open(ctx.tpath("etc/environment")).read()
        except OSError:
            pass
        env = "".join(l for l in env.splitlines(True) if not re.match(r"^(http|https|no)_proxy=", l, re.I))
        ctx.write("/etc/environment", env.rstrip("\n") + f"\nhttp_proxy={p}\nhttps_proxy={p}\nno_proxy=localhost,127.0.0.1,::1\n")


def sub_identity(ctx):
    idn = ctx.plan["identity"]
    u = idn["user"]
    name = u["name"]
    exists = ctx.texists(f"/home/{name}") and not ctx.dry_run and name in open(ctx.tpath("etc/passwd")).read()
    if not exists:
        ctx.run(["useradd", "-m", "-G", "sudo", "-s", "/bin/bash", "-c", u["fullname"] or name, name], chroot=True)
    pw = u["password"]
    if pw:
        if pw.startswith("plain:"):
            ctx.run(["chpasswd"], chroot=True, input=f"{name}:{pw[6:]}\n", secret=True)
        else:
            ctx.run(["chpasswd", "-e"], chroot=True, input=f"{name}:{pw}\n", secret=True)
    else:
        ctx.run(["passwd", "-d", name], chroot=True, check=False)
        ctx.run(["passwd", "-l", name], chroot=True, check=False)
    if u["ssh_keys"]:
        ctx.write(f"/home/{name}/.ssh/authorized_keys", "\n".join(u["ssh_keys"]) + "\n", mode=0o600)
        ctx.run(["chmod", "700", f"/home/{name}/.ssh"], chroot=True)
        ctx.run(["chown", "-R", f"{name}:{name}", f"/home/{name}/.ssh"], chroot=True)
    if u["password_change_required"]:
        ctx.run(["chage", "-d", "0", name], chroot=True)
    ssh = idn["ssh"]
    ctx.write("/etc/ssh/sshd_config.d/50-maluos.conf",
              f"# Written by the MaluOS installer.\nPasswordAuthentication {'yes' if ssh['password_auth'] else 'no'}\nKbdInteractiveAuthentication {'yes' if ssh['password_auth'] else 'no'}\n")
    if ssh["server"]:
        # the images ship no host keys (cloud-init makes them on a server's first boot; a desktop has cloud-init off)
        ctx.run(["ssh-keygen", "-A"], chroot=True)
        ctx.run(["systemctl", "enable", "ssh.socket"], chroot=True, check=False)
        ctx.run(["systemctl", "unmask", "ssh.service", "ssh.socket"], chroot=True, check=False)
    else:
        ctx.run(["systemctl", "disable", "ssh.socket", "ssh.service"], chroot=True, check=False)


ISO_SOURCES = """# MaluOS packages carried on the install media.
Types: deb
URIs: file:/var/lib/maluos/apt
Suites: resolute
Components: main
Signed-By: /var/lib/maluos/apt/bootstrap/maluos-archive-keyring.gpg
"""

EXTRA_SOURCES = """
# Ubuntu packages the medium carries for components the image lacks (the apple-t2 toolchain and headers).
Types: deb
URIs: file:/var/lib/maluos/apt/extra
Suites: ./
Trusted: yes
"""


def apt_configure(ctx, target=None, media=None):
    """The on-media repository into the target and maluos-iso.sources beside apt.maluos.com.
    Also used by tests/iso-apt-check.sh (--apt-check), so the test and the installer cannot drift."""
    target = target or ctx.target
    media = media or ctx.media
    src = os.path.join(media, "maluos/apt")
    if not os.path.isdir(src):
        raise RuntimeError(f"no repository at {src}")
    dst = os.path.join(target, "var/lib/maluos/apt")
    ctx.run(["mkdir", "-p", dst])
    ctx.run(["cp", "-rL", "--no-preserve=ownership", src + "/.", dst + "/"])
    path = os.path.join(target, "etc/apt/sources.list.d/maluos-iso.sources")
    text = ISO_SOURCES
    if os.path.isfile(os.path.join(src, "extra/Packages")):   # Ubuntu packages the medium carries for components (iso/extra-pool.sh)
        text += EXTRA_SOURCES
    ctx.write(path, text, in_target=False)


def sub_apt(ctx):
    if ctx.plan["source"]["repository"] == "none":
        ctx.info("source.repository none: no on-media repository copied")
        return
    apt_configure(ctx)


APT_MEDIA_ONLY = ["-o", "Dir::Etc::SourceList=/etc/apt/sources.list.d/maluos-iso.sources", "-o", "Dir::Etc::SourceParts=/nonexistent"]


def sub_components(ctx):
    comps = ctx.plan["components"]
    if not comps["install"] and not comps["remove"]:
        ctx.info("no components beyond the image")
        return
    if ctx.plan["source"]["repository"] == "none":
        raise RuntimeError("components need the on-media repository (source.repository media)")
    ctx.run(["apt-get", "-q"] + APT_MEDIA_ONLY + ["update"], chroot=True, timeout=600)
    if comps["install"]:
        ctx.run(["apt-get", "-q", "-y"] + APT_MEDIA_ONLY + ["install"] + comps["install"], chroot=True, timeout=3600,
                env={"DEBIAN_FRONTEND": "noninteractive"})
    if comps["remove"]:
        ctx.run(["apt-get", "-q", "-y"] + APT_MEDIA_ONLY + ["purge"] + comps["remove"], chroot=True, timeout=1800)
        ctx.run(["apt-get", "-q", "-y"] + APT_MEDIA_ONLY + ["autoremove", "--purge"], chroot=True, timeout=1800)
    ctx.run(["rm", "-rf", ctx.tpath("var/lib/apt/lists")], check=False)


def sub_apple(ctx):
    """The Mac's Wi-Fi and Bluetooth firmware into the target: what the live medium imported, else from the EFI partition."""
    ap = ctx.facts.get("apple") or {}
    if not ap.get("mac"):
        ctx.info("not a Mac; nothing to do")
        return
    if os.path.exists("/usr/bin/maluos-apple-firmware") and os.path.exists("/lib/firmware/brcm/.maluos-apple-firmware"):
        ctx.run(["maluos-apple-firmware", "copy", "--to", ctx.target])
        return
    if os.path.exists(ctx.tpath("usr/bin/maluos-apple-firmware")):
        r = ctx.run(["maluos-apple-firmware", "import", "--auto", "--no-reload"], chroot=True, check=False)
        if ctx.dry_run or os.path.exists(ctx.tpath("lib/firmware/brcm/.maluos-apple-firmware")):
            return
        ctx.warn("no Wi-Fi/Bluetooth firmware found on the Mac's EFI partition: run firmware.sh in macOS and boot the medium again, "
                 "or after the first boot run `sudo get-apple-firmware` (wired network) or `sudo maluos-apple-firmware import --tar FILE`")
        return
    ctx.warn("the target has no maluos-apple-firmware (the apple-t2 component is not installed); the Mac's Wi-Fi needs its firmware by hand")


def sub_firstboot(ctx):
    fb = ctx.plan["firstboot"]
    path = ctx.tpath("etc/maluos/firstboot.yaml")
    doc = {}
    if os.path.exists(path) and yaml:
        try:
            doc = yaml.safe_load(open(path)) or {}
        except Exception:
            doc = {}
    doc.setdefault("tenant", {})["name"] = fb["tenant"]
    doc.setdefault("admin_principal", {})["ref"] = fb["admin"]["principal"]
    for name, spec in (fb["components"] or {}).items():
        doc.setdefault("components", {}).setdefault(name, {}).update(spec if isinstance(spec, dict) else {"enabled": bool(spec)})
    if fb["enroll"]["kind"]:
        e = fb["enroll"]
        doc["enroll"] = {"kind": e["kind"], "url": e["url"], "code": e["code"], "name": e["name"] or ctx.plan["identity"]["hostname"],
                         "owner": ctx.plan["identity"]["user"]["name"]}
    text = (yaml.safe_dump(doc, sort_keys=False) if yaml else json.dumps(doc, indent=2))
    header = ("# MaluOS first-boot provisioning, written by the MaluOS installer from the\n"
              "# install plan. Read once by maluos-firstboot.service. The keys the plan did\n"
              "# not give keep the package's documented defaults.\n")
    ctx.write("/etc/maluos/firstboot.yaml", header + text, mode=0o600 if fb["enroll"]["kind"] else 0o644)
    if fb["cloud_init"]:
        ctx.run(["rm", "-f", ctx.tpath("etc/cloud/cloud-init.disabled")], check=False)
        iid = f"maluos-install-{uuid.uuid4()}"
        ctx.write("/var/lib/cloud/seed/nocloud/meta-data", f"instance-id: {iid}\nlocal-hostname: {ctx.plan['identity']['hostname']}\n")
        ctx.write("/var/lib/cloud/seed/nocloud/user-data", "#cloud-config\n# The MaluOS installer configured this system; cloud-init keeps the NoCloud seed and creates no default user.\nusers: []\npreserve_hostname: true\n")
    else:
        ctx.write("/etc/cloud/cloud-init.disabled", "# The install plan said firstboot.cloud_init: false.\n")


def sub_grub(ctx, layout):
    bl = ctx.plan["bootloader"]
    base = "quiet splash" if variant(ctx) == "desktop" else ""
    default = " ".join(x for x in (base, bl["cmdline"]) if x)
    linux = []
    if layout["luks"]:
        linux.append(f"rd.luks.name={layout['uuids']['luks']}={layout['luks']['name']}")
        linux.append("rd.luks.options=discard")
    if (ctx.facts.get("apple") or {}).get("t2"):
        linux.append(T2_KERNEL_OPTIONS)
    lines = ["# Written by the MaluOS installer from the install plan (bootloader section).",
             f'GRUB_CMDLINE_LINUX_DEFAULT="{default}"',
             f'GRUB_CMDLINE_LINUX="{" ".join(linux)}"',
             f"GRUB_TIMEOUT={bl['timeout']}",
             f"GRUB_TIMEOUT_STYLE={'menu' if bl['timeout'] > 0 else 'hidden'}",
             "GRUB_DISABLE_OS_PROBER=true"]
    if "ttyS" in bl["cmdline"]:
        lines += ['GRUB_TERMINAL="console serial"', 'GRUB_SERIAL_COMMAND="serial --speed=115200"']
    ctx.write("/etc/default/grub.d/50-maluos-install.cfg", "\n".join(lines) + "\n")


def sub_initrd(ctx, layout):
    if not layout["luks"] and not apple_t2(ctx):
        ctx.info("the image's initrd already carries LVM; nothing to rebuild")
        return
    if apple_t2(ctx) and (ctx.dry_run or os.path.exists(ctx.tpath("usr/sbin/dkms"))):
        # every DKMS module for every kernel of the target (a package's postinst builds for the running kernel only)
        kernels = sorted(os.path.basename(os.path.dirname(k)) for k in glob.glob(ctx.tpath("lib/modules/*/build"))) if not ctx.dry_run else ["<kver>"]
        for k in kernels:
            ctx.run(["dkms", "autoinstall", "-k", k], chroot=True, timeout=3600)
        if not ctx.dry_run and not glob.glob(ctx.tpath("lib/modules/*/updates/dkms/apple-bce.ko*")):
            raise RuntimeError("the apple-bce module was not built for the target's kernel (dkms status in the target tells why)")
    ctx.run(["dracut", "--force", "--regenerate-all"], chroot=True, timeout=1800)


def sub_machine_id(ctx):
    ctx.write("/etc/machine-id", "")
    ctx.run(["rm", "-f", ctx.tpath("var/lib/dbus/machine-id")], check=False)


def apply(ctx):
    layout = ctx.state["storage"]
    ctx.mount_chroot()
    try:
        with ctx.substep("swap", "the swap file " + (fmt_size(layout["swap_bytes"]) if layout["swap_bytes"] else "(none)")) as go:
            if go: sub_swap(ctx, layout)
        with ctx.substep("fstab", "fstab by UUID" + (" and crypttab" if layout["luks"] else "")) as go:
            if go: sub_fstab(ctx, layout)
        with ctx.substep("hostname", f"hostname {ctx.plan['identity']['hostname']}") as go:
            if go: sub_hostname(ctx)
        with ctx.substep("locale", f"locale {ctx.plan['locale']['language']}, keyboard {ctx.plan['locale']['keyboard']['layout']}, timezone {ctx.plan['locale']['timezone']}") as go:
            if go: sub_locale(ctx)
        with ctx.substep("network", f"netplan ({ctx.plan['network']['mode']}, renderer {renderer(ctx)})") as go:
            if go: sub_network(ctx)
        with ctx.substep("identity", f"user {ctx.plan['identity']['user']['name']} in sudo; ssh server {'on' if ctx.plan['identity']['ssh']['server'] else 'off'}") as go:
            if go: sub_identity(ctx)
        with ctx.substep("apt", "the on-media repository and maluos-iso.sources") as go:
            if go: sub_apt(ctx)
        comps = ctx.plan["components"]
        with ctx.substep("components", "components: " + (", ".join(comps["install"]) or "none") + (f"; remove {', '.join(comps['remove'])}" if comps["remove"] else "")) as go:
            if go: sub_components(ctx)
        ap = ctx.facts.get("apple") or {}
        with ctx.substep("apple", f"Apple {ap.get('model')}: the Mac's Wi-Fi and Bluetooth firmware" if ap.get("mac") else "not a Mac") as go:
            if go: sub_apple(ctx)
        with ctx.substep("firstboot", f"/etc/maluos/firstboot.yaml (tenant {ctx.plan['firstboot']['tenant']}); cloud-init {'kept' if ctx.plan['firstboot']['cloud_init'] else 'disabled'}") as go:
            if go: sub_firstboot(ctx)
        with ctx.substep("grub", "grub defaults: the cmdline, the timeout, no os-prober") as go:
            if go: sub_grub(ctx, layout)
        with ctx.substep("initrd", "the initrd" + (" rebuilt" + (" for the encrypted root" if layout["luks"] else "") + (" with the T2 bridge driver" if apple_t2(ctx) else "") if (layout["luks"] or apple_t2(ctx)) else "")) as go:
            if go: sub_initrd(ctx, layout)
        with ctx.substep("machine-id", "machine-id cleared") as go:
            if go: sub_machine_id(ctx)
    finally:
        pass   # the chroot stays mounted for the bootloader step; finish releases it
