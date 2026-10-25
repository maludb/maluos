"""The screens, one class each. A screen gets the app (the plan being built, the facts, the medium),
builds its widgets into a ListBox, validates on Continue and writes its section of the plan.

The keys are the same everywhere (app.py): Enter continues, Esc goes back, Space selects, Tab and
the arrows move, F10 quits to a shell. Radio buttons and check boxes here let Enter through so it
means Continue on them too.
"""
import json, os, re, subprocess

import urwid

from .. import plan as planmod, disks as disksmod, telemetry

try:
    import yaml
except ImportError:
    yaml = None

LANGUAGES = [
    ("en_US.UTF-8", "English (United States)"), ("en_GB.UTF-8", "English (United Kingdom)"),
    ("de_DE.UTF-8", "Deutsch"), ("es_ES.UTF-8", "Español"), ("fr_FR.UTF-8", "Français"),
    ("it_IT.UTF-8", "Italiano"), ("pt_BR.UTF-8", "Português (Brasil)"), ("pt_PT.UTF-8", "Português"),
    ("nl_NL.UTF-8", "Nederlands"), ("pl_PL.UTF-8", "Polski"), ("sv_SE.UTF-8", "Svenska"),
    ("ja_JP.UTF-8", "日本語"), ("zh_CN.UTF-8", "中文 (简体)"),
]
COMMON_LAYOUTS = ["us", "gb", "de", "fr", "es", "it", "pt", "br", "nl", "pl", "se", "ch", "jp", "latam"]


class Radio(urwid.RadioButton):
    def keypress(self, size, key):
        return key if key == "enter" else super().keypress(size, key)


class Check(urwid.CheckBox):
    def keypress(self, size, key):
        return key if key == "enter" else super().keypress(size, key)


def text(s, attr=None):
    return urwid.Text((attr, s)) if attr else urwid.Text(s)


def edit(caption, value="", mask=None, multiline=False):
    e = urwid.Edit(("label", caption), value, mask=mask, multiline=multiline)
    return e


def radios(options, selected):
    """[(value, label)] -> (group, [Radio]) with `selected` on."""
    group, items = [], []
    for value, label in options:
        r = Radio(group, label, state=(value == selected))
        r.value = value
        items.append(r)
    return group, items


def chosen(group):
    for r in group:
        if r.state:
            return r.value
    return None


def password_strength(pw):
    if not pw:
        return ""
    classes = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    score = classes + (len(pw) >= 8) + (len(pw) >= 12) + (len(pw) >= 16)
    return ["very weak", "very weak", "weak", "weak", "fair", "good", "strong", "strong"][min(score, 7)]


def hash_password(pw):
    r = subprocess.run(["openssl", "passwd", "-6", "-stdin"], input=pw + "\n", capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.startswith("$6$"):
        raise RuntimeError("openssl passwd failed: " + r.stderr.strip())
    return r.stdout.strip()


def keyboard_layouts():
    out = []
    try:
        section = False
        for line in open("/usr/share/X11/xkb/rules/evdev.lst"):
            if line.startswith("! layout"):
                section = True; continue
            if section and line.startswith("!"):
                break
            if section and line.strip():
                code, _, name = line.strip().partition(" ")
                out.append((code, name.strip()))
    except OSError:
        pass
    if not out:
        out = [(c, c) for c in COMMON_LAYOUTS]
    names = dict(out)
    first = [(c, names.get(c, c)) for c in COMMON_LAYOUTS if c in names]
    rest = sorted((c, n) for c, n in out if c not in COMMON_LAYOUTS)
    return first + rest


def read_catalog(media):
    p = os.path.join(media, "maluos/catalog.yaml")
    if not os.path.exists(p) or not yaml:
        return []
    try:
        return (yaml.safe_load(open(p)) or {}).get("components") or []
    except Exception:
        return []


class Screen:
    name = "Screen"
    section = None       # the plan key(s) this screen owns, for error filtering

    def __init__(self, app):
        self.app = app
        self.plan = app.plan            # the raw mapping being built
        self.items = []

    def build(self):
        """Return the list of widgets (a ListBox is made of them)."""
        raise NotImplementedError

    def validate(self):
        """Return a list of error strings; empty means Continue."""
        return []

    def apply(self):
        """Write this screen's answers into the plan."""

    def errors_for(self, raw):
        """Validate the whole raw plan and keep the errors about this screen's sections."""
        try:
            filled = planmod.fill_defaults(raw, self.app.variant)
        except planmod.PlanError as e:
            return [str(e)]
        errs = planmod.semantic_errors(filled)
        mine = [e for e in errs if any(e.startswith(s) for s in (self.section or ()))]
        return mine


# --- 1 welcome -------------------------------------------------------------------------------
class Welcome(Screen):
    name = "Welcome"
    section = ("locale",)

    def build(self):
        loc = self.plan.setdefault("locale", {})
        self.group, items = radios(LANGUAGES, loc.get("language", "en_US.UTF-8"))
        self.tz = edit("Time zone: ", loc.get("timezone", "UTC"))
        rel = ""
        try:
            rel = open("/etc/maluos-release").readline().strip()
        except OSError:
            pass
        ap = self.app.facts.get("apple") or {}
        mac = []
        if ap.get("mac"):
            mac = [urwid.Divider(), text(f"This is an Apple {ap.get('model') or 'Mac'}" + (
                " with the T2 chip. The apple-t2 component (the internal keyboard, trackpad, Touch Bar, camera and "
                "audio drivers, the Wi-Fi firmware import, Vulkan for the Radeon) is selected on the Components screen; "
                "the Storage screen can keep macOS and install into the free space." if ap.get("t2") else "."), "dim")]
        return [text(f"Welcome to the MaluOS installer{(' (' + rel + ')') if rel else ''}.", "title"), urwid.Divider(),
                text("This installer puts MaluOS on a disk of this machine from the medium it booted from. "
                     "Every answer goes into one install plan, shown before anything is written; the summary "
                     "screen can save that plan for the next machine.")] + mac + [urwid.Divider(),
                text("Language of the installed system:")] + items + [
                urwid.Divider(), self.tz, text("  (a name like Europe/London, UTC, or auto)", "dim")]

    def validate(self):
        tz = self.tz.edit_text.strip()
        if tz != "auto" and not os.path.exists(f"/usr/share/zoneinfo/{tz}"):
            return [f"{tz!r} is not a time zone name (try Europe/London or UTC)"]
        return []

    def apply(self):
        self.plan.setdefault("locale", {})["language"] = chosen(self.group)
        self.plan["locale"]["timezone"] = self.tz.edit_text.strip() or "UTC"


# --- 2 keyboard ------------------------------------------------------------------------------
class Keyboard(Screen):
    name = "Keyboard"
    section = ("locale",)

    def build(self):
        kb = self.plan.setdefault("locale", {}).setdefault("keyboard", {})
        self.group, items = radios(keyboard_layouts(), kb.get("layout", "us"))
        self.variant = edit("Variant (optional): ", kb.get("variant", ""))
        self.try_it = edit("Try your keyboard here: ", "")
        return [text("Keyboard layout of the installed system (and of this installer's console).", "title"),
                urwid.Divider(), self.try_it, self.variant, urwid.Divider()] + items

    def apply(self):
        kb = self.plan["locale"].setdefault("keyboard", {})
        kb["layout"] = chosen(self.group) or "us"
        kb["variant"] = self.variant.edit_text.strip()
        try:
            subprocess.run(["loadkeys", kb["layout"]], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


# --- 3 network -------------------------------------------------------------------------------
class Network(Screen):
    name = "Network"
    section = ("network",)

    def build(self):
        net = self.plan.setdefault("network", {})
        ifaces = disksmod.wired_interfaces() if not self.app.no_hardware else [("eth0", True, ["10.0.0.5"])]
        lines = [text("Network of the installed system. The medium carries the MaluOS repository, so an install "
                      "needs no network; the network is for the first boot and for keys fetched from a URL.", "title"),
                 urwid.Divider(), text("Wired interfaces now:")]
        for name, up, addrs in ifaces or []:
            lines.append(text(f"  {name}  {'link' if up else 'no link'}  {' '.join(addrs) if addrs else '(no address)'}"))
        if not ifaces:
            lines.append(text("  none found"))
        self.group, modes = radios([("dhcp", "DHCP on every wired interface (default)"), ("static", "A static address"),
                                    ("none", "No network configuration (netplan stays as the image ships it)")], net.get("mode", "dhcp"))
        self.iface = edit("Interface: ", net.get("interface") or (ifaces[0][0] if ifaces else ""))
        self.addr = edit("Address (CIDR, e.g. 10.0.0.5/24): ", net.get("address", ""))
        self.gw = edit("Gateway: ", net.get("gateway", ""))
        self.ns = edit("Name servers (space separated): ", " ".join(net.get("nameservers") or []))
        self.proxy = edit("HTTP proxy (optional, http://host:port): ", net.get("proxy", ""))
        return lines + [urwid.Divider()] + modes + [urwid.Divider(), text("For a static address:"),
                                                     self.iface, self.addr, self.gw, self.ns, urwid.Divider(), self.proxy]

    def validate(self):
        raw = self._raw()
        return self.errors_for({**self.plan, "network": raw, "version": 1})

    def _raw(self):
        mode = chosen(self.group) or "dhcp"
        raw = {"mode": mode, "proxy": self.proxy.edit_text.strip()}
        if mode == "static":
            raw.update(interface=self.iface.edit_text.strip(), address=self.addr.edit_text.strip(),
                       gateway=self.gw.edit_text.strip(), nameservers=self.ns.edit_text.split())
        return raw

    def apply(self):
        self.plan["network"] = self._raw()


# --- 4 storage -------------------------------------------------------------------------------
class Storage(Screen):
    name = "Storage"
    section = ("storage",)

    def build(self):
        st = self.plan.setdefault("storage", {})
        self.disks = [d for d in self.app.facts["disks"] if not d["medium"]]
        opts = [(d["path"], f"{d['path']}  {planmod.fmt_size(d['size'])}  {d['model'] or '-'}  ({d['bus']}{', removable' if d['removable'] else ''})") for d in self.disks]
        current = st.get("disk") if st.get("disk", "").startswith("/dev/") else (self.disks[0]["path"] if self.disks else "")
        self.dgroup, ditems = radios(opts, current)
        # the free space on the disks that have some beside an EFI partition (a Mac with macOS shrunk): the target choice
        self.free_on = {d["path"]: max((f["size"] for f in (d.get("table") or {}).get("free") or []), default=0)
                        for d in self.disks if (d.get("table") or {}).get("esp") and (d.get("table") or {}).get("label") == "gpt"}
        self.free_on = {k: v for k, v in self.free_on.items() if v >= 16 << 30}
        topts = [("disk", "Erase the whole disk")]
        if self.free_on:
            topts.append(("free", "Keep the existing partitions (macOS, its EFI partition) and install into the free space: " +
                          ", ".join(f"{os.path.basename(k)} {planmod.fmt_size(v)} free" for k, v in self.free_on.items())))
        self.tgroup, titems = radios(topts, st.get("target", "disk") if self.free_on else "disk")
        self.lgroup, litems = radios([("lvm", "LVM: a volume group maluos with the root as a logical volume and the rest free (recommended)"),
                                      ("direct", "Direct: one root partition taking the disk")], st.get("layout", "lvm"))
        self.fgroup, fitems = radios([("ext4", "ext4 (default)"), ("xfs", "xfs (large database servers)")], st.get("filesystem", "ext4"))
        self.root_size = edit("Root size (LVM; a size like 50G, or all): ", st.get("root_size", "50G"))
        self.swap = edit("Swap file (auto, none, or a size): ", st.get("swap", "auto"))
        self.encrypt = Check("Encrypt the root with LUKS2 (a passphrase is asked at every boot)", state=bool(st.get("encrypt")))
        self.pass1 = edit("Passphrase: ", st.get("passphrase", ""), mask="*")
        self.pass2 = edit("Passphrase again: ", st.get("passphrase", ""), mask="*")
        lines = [text("Where MaluOS goes. The chosen disk is erased entirely unless the free space is chosen; the next step asks you to confirm by typing its name.", "title"),
                 urwid.Divider(), text("Disk:")] + (ditems or [text("  no disk found besides the medium", "error")])
        lines += [urwid.Divider(), text("Target:")] + titems
        lines += [urwid.Divider(), text("Layout:")] + litems + [urwid.Divider(), text("Root filesystem:")] + fitems
        lines += [urwid.Divider(), self.root_size, self.swap, urwid.Divider(), self.encrypt, self.pass1, self.pass2]
        return lines

    def _raw(self):
        target = chosen(self.tgroup) or "disk"
        raw = {"disk": chosen(self.dgroup) or "", "target": target, "erase": target == "disk", "layout": chosen(self.lgroup) or "lvm",
               "filesystem": chosen(self.fgroup) or "ext4", "swap": self.swap.edit_text.strip() or "auto",
               "encrypt": bool(self.encrypt.state)}
        rs = self.root_size.edit_text.strip()
        if raw["layout"] == "lvm" and rs:
            raw["root_size"] = rs
        if raw["encrypt"]:
            raw["passphrase"] = self.pass1.edit_text
        return raw

    def validate(self):
        if not self.disks:
            return ["no disk to install on"]
        raw = self._raw()
        if raw["encrypt"] and self.pass1.edit_text != self.pass2.edit_text:
            return ["the two passphrases differ"]
        if raw["encrypt"] and len(self.pass1.edit_text) < 8:
            return ["a passphrase of at least 8 characters, please"]
        errs = self.errors_for({**self.plan, "storage": raw, "version": 1})
        if errs:
            return errs
        from ..steps import storage as stor
        disk = next(d for d in self.disks if d["path"] == raw["disk"])
        filled = planmod.fill_defaults({**self.plan, "storage": raw, "version": 1}, self.app.variant)
        if raw["target"] == "free" and disk["path"] not in self.free_on:
            return [f"{disk['path']} has no free space beside an EFI partition to install into; erase it, or shrink a partition first"]
        layout = stor.compute_layout(filled["storage"], disk["path"], disk["size"], self.app.facts["memory_mb"] << 20,
                                     table=disk.get("table"), sector=disk.get("sector", 512))
        self.layout_text = stor.describe(layout)
        return layout["errors"]

    def confirm_text(self):
        d = next(d for d in self.disks if d["path"] == chosen(self.dgroup))
        if (chosen(self.tgroup) or "disk") == "free":
            return (f"The partitions of {d['path']} ({planmod.fmt_size(d['size'])}, {d['model'] or d['bus']}) are kept; MaluOS goes into "
                    f"the free space and shares the EFI partition.\n\n{self.layout_text}\n\nType the disk's name ({os.path.basename(d['path'])}) to continue:"), os.path.basename(d["path"])
        return (f"Everything on {d['path']} ({planmod.fmt_size(d['size'])}, {d['model'] or d['bus']}) will be erased.\n\n"
                f"{self.layout_text}\n\nType the disk's name ({os.path.basename(d['path'])}) to continue:"), os.path.basename(d["path"])

    def apply(self):
        self.plan["storage"] = self._raw()


# --- 5 identity ------------------------------------------------------------------------------
class Identity(Screen):
    name = "Identity"
    section = ("identity",)

    def build(self):
        idn = self.plan.setdefault("identity", {})
        user = idn.setdefault("user", {})
        ssh = idn.setdefault("ssh", {})
        self.hostname = edit("This machine's name: ", idn.get("hostname", "maluos"))
        self.fullname = edit("Your name: ", user.get("fullname", ""))
        self.login = edit("Login: ", user.get("name", ""))
        self.pw1 = edit("Password: ", "", mask="*")
        self.pw2 = edit("Password again: ", "", mask="*")
        self.strength = text("")
        urwid.connect_signal(self.pw1, "change", lambda w, t: self.strength.set_text(f"  strength: {password_strength(t)}" if t else ""))
        keys = user.get("ssh_keys") or []
        self.keys = edit("SSH keys (one per line; github:NAME fetches a GitHub user's keys):\n",
                         "\n".join(k.replace("url:https://github.com/", "github:").replace(".keys", "") if k.startswith("url:https://github.com/") else k for k in keys), multiline=True)
        self.server = Check("Run the SSH server on the installed system", state=ssh.get("server", self.app.variant == "server"))
        self.pwauth = Check("Allow SSH logins with a password (else keys only)", state=bool(ssh.get("password_auth", False)))
        self.change = Check("The password must be changed at the first login", state=bool(user.get("password_change_required", False)))
        self.has_hash = user.get("password", "").startswith("$")
        return [text("Who uses this machine. The first user is an administrator (sudo).", "title"), urwid.Divider(),
                self.hostname, urwid.Divider(), self.fullname, self.login, self.pw1, self.strength, self.pw2,
                text("  (leave the password empty to log in with SSH keys only)" + ("; a hash from the plan is kept if you type nothing" if self.has_hash else ""), "dim"),
                urwid.Divider(), self.keys, urwid.Divider(), self.server, self.pwauth, self.change]

    def _raw(self, hashed=None):
        keys = []
        for line in self.keys.edit_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("github:"):
                line = f"url:https://github.com/{line[7:].strip()}.keys"
            keys.append(line)
        user = {"name": self.login.edit_text.strip(), "fullname": self.fullname.edit_text.strip(), "ssh_keys": keys,
                "password_change_required": bool(self.change.state)}
        if hashed:
            user["password"] = hashed
        elif self.pw1.edit_text:
            user["password"] = "plain:" + self.pw1.edit_text      # validated as plain; hashed in apply()
        elif self.has_hash:
            user["password"] = self.plan["identity"]["user"]["password"]
        return {"hostname": self.hostname.edit_text.strip(), "user": user,
                "ssh": {"server": bool(self.server.state), "password_auth": bool(self.pwauth.state)}}

    def validate(self):
        if self.pw1.edit_text != self.pw2.edit_text:
            return ["the two passwords differ"]
        return self.errors_for({**self.plan, "identity": self._raw(), "version": 1})

    def apply(self):
        hashed = hash_password(self.pw1.edit_text) if self.pw1.edit_text else None
        self.plan["identity"] = self._raw(hashed)


# --- 6 components ----------------------------------------------------------------------------
class Components(Screen):
    name = "Components"
    section = ("components",)

    def build(self):
        self.catalog = read_catalog(self.app.media)
        comps = self.plan.setdefault("components", {})
        wanted = set(comps.get("install") or [])
        removed = set(comps.get("remove") or [])
        self.boxes = []
        lines = [text("What the installed system carries. The components in the image are already there; "
                      "the others are installed from the medium's repository before the first boot.", "title"), urwid.Divider()]
        if not self.catalog:
            lines.append(text("  the medium carries no catalogue; the image installs as it is"))
        t2 = bool((self.app.facts.get("apple") or {}).get("t2"))
        for c in self.catalog:
            state = (c["name"] in wanted) or (c.get("in_image") and c["name"] not in removed) \
                or (t2 and c["name"] == "maluos-apple-t2" and c["name"] not in removed)
            box = Check(f"{c['name']}  ({'in the image' if c.get('in_image') else str(c.get('size_mb', 0)) + ' MB from the medium'})", state=bool(state))
            box.component = c
            self.boxes.append(box)
            lines.append(box)
            lines.append(text(f"      {c.get('title', '')}: {c.get('description', '')}"[:400], "dim"))
        return lines

    def apply(self):
        install, remove = [], []
        for b in self.boxes:
            c = b.component
            if b.state and not c.get("in_image"):
                install.append(c["name"])
            if not b.state and c.get("in_image"):
                remove.append(c["name"])
        self.plan["components"] = {"install": install, "remove": remove}


# --- 7 first boot ----------------------------------------------------------------------------
class FirstBoot(Screen):
    name = "First boot"
    section = ("firstboot",)

    def build(self):
        fb = self.plan.setdefault("firstboot", {})
        en = fb.get("enroll") or {}
        self.tenant = edit("Tenant (the memory database's schema): ", fb.get("tenant", "maluos"))
        self.principal = edit("Administrator principal: ", (fb.get("admin") or {}).get("principal", "human:admin"))
        self.egroup, eitems = radios([("", "No enrolment"), ("office", "Join a Business OS office as a desk (maluctl office enroll)"),
                                      ("estate", "Join an estate as a node (Phase 13; not available on this release)")], en.get("kind", ""))
        self.url = edit("Address (https://…): ", en.get("url", ""))
        self.code = edit("One-time code: ", en.get("code", ""))
        self.ename = edit("Name at the office (default: the hostname): ", en.get("name", ""))
        self.cloud = Check("Keep cloud-init enabled (NoCloud and cloud data sources)", state=fb.get("cloud_init", self.app.variant == "server"))
        return [text("The first boot provisions the memory database, the tenant, the administrator and the components "
                     "(maluos-firstboot). An enrolment joins an office or an estate at that moment.", "title"), urwid.Divider(),
                self.tenant, self.principal, urwid.Divider(), text("Enrolment:")] + eitems + [self.url, self.code, self.ename, urwid.Divider(), self.cloud]

    def _raw(self):
        raw = {"tenant": self.tenant.edit_text.strip() or "maluos", "admin": {"principal": self.principal.edit_text.strip() or "human:admin"},
               "cloud_init": bool(self.cloud.state)}
        kind = chosen(self.egroup) or ""
        if kind:
            raw["enroll"] = {"kind": kind, "url": self.url.edit_text.strip(), "code": self.code.edit_text.strip(), "name": self.ename.edit_text.strip()}
        return raw

    def validate(self):
        return self.errors_for({**self.plan, "firstboot": self._raw(), "version": 1})

    def apply(self):
        self.plan["firstboot"] = self._raw()


# --- 8 telemetry -----------------------------------------------------------------------------
class Telemetry(Screen):
    name = "Help improve MaluOS"
    section = ("telemetry",)

    def build(self):
        tel = self.plan.setdefault("telemetry", {})
        doc = self.app.telemetry_preview()
        self.group, items = radios([("yes", "Send this report (one document, at the end of the install)"),
                                    ("no", "Don't send")], "no" if tel.get("send") is False else "yes")
        body = json.dumps(doc, indent=1)
        return [text("One report helps MaluOS know what it is installed on: the release, the layout, the hardware "
                     "class, the locale and how long it took. No name, address or serial is in it. This is the "
                     "document, exactly as it would go to telemetry.maluos.com:", "title"), urwid.Divider(),
                urwid.LineBox(text(body)), urwid.Divider()] + items

    def apply(self):
        self.plan["telemetry"] = {"send": chosen(self.group) == "yes"}


# --- 9 summary -------------------------------------------------------------------------------
class Summary(Screen):
    name = "Summary"

    def build(self):
        filled = planmod.fill_defaults({**self.plan, "version": 1}, self.app.variant)
        shown = planmod.dump(planmod.redact(filled))
        self.install = urwid.Button("Install" if not self.app.save_plan else "Save the plan and finish", on_press=lambda b: self.app.start_install())
        self.save = urwid.Button("Save the plan…", on_press=lambda b: self.app.ask_save())
        self.back = urwid.Button("Back", on_press=lambda b: self.app.back())
        return [text("The plan as the installer understands it. Install erases the disk and runs it; Save the plan "
                     "writes it (with the secrets) for another machine.", "title"), urwid.Divider(),
                urwid.Columns([("pack", self.install), ("pack", self.save), ("pack", self.back)], dividechars=2), urwid.Divider(),
                urwid.LineBox(text(shown))]

    def apply(self):
        pass


SCREENS = [Welcome, Keyboard, Network, Storage, Identity, Components, FirstBoot, Telemetry, Summary]
