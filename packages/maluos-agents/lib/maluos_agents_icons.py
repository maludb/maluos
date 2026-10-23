"""maluos_agents_icons: the agent icons (Phase 12 slice 8).

One source, three places. From the session's state (the local agents the
person owns or may use, and the office's agents on an enrolled desk) this
writes one launcher per agent in ~/.local/share/applications
(maluos-agent-<id>.desktop, Exec=maluos-agents --agent <id>), lists them
in the "Agents" app folder of the GNOME grid
(org.gnome.desktop.app-folders, folder maluos-agents) and copies them into
~/Desktop/Agents. An agent that goes away takes its icon with it. Run by
`maluos-agents --sync`, which the session service calls when the list
changes.

Agent ids: `local:NAME` for an agent on this desk, `office:ID` for one of
the office's.
"""
import json, os, re, subprocess, sys

PREFIX = "maluos-agent-"
FOLDER = "maluos-agents"
SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def data_home():
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def launcher_dir():
    return os.path.join(data_home(), "applications")


def desktop_dir():
    try:
        d = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        d = ""
    return d or os.path.join(os.path.expanduser("~"), "Desktop")


def agent_entries(state):
    """[(id, name, comment, icon)] for every agent the icons should show, from the session's state."""
    out = []
    for a in state.get("agents") or []:
        if not a.get("name"):
            continue
        st = a.get("active") or "inactive"
        comment = f"Agent on this desk ({st})" + (f" · {a['exec']}" if a.get("exec") else "")
        out.append((f"local:{a['name']}", a.get("display") or a["name"], comment, "maluos-logo"))
    o = state.get("office") or {}
    for a in (o.get("agents") or []):
        if a.get("id") is None:
            continue
        out.append((f"office:{a['id']}", a.get("name") or str(a["id"]), f"Agent at {o.get('office', {}).get('name') or o.get('url') or 'the office'}: {a.get('description') or ''}".rstrip(": "),
                    a.get("icon") or "maluos-logo"))
    return out


def file_id(agent_id):
    return SAFE.sub("_", agent_id.replace(":", "-"))


def launcher_text(agent_id, name, comment, icon):
    return ("[Desktop Entry]\nType=Application\n" f"Name={name}\n" f"Comment={comment.replace(chr(10), ' ')}\n"
            f"Exec=maluos-agents --agent {agent_id}\n" f"Icon={icon}\nTerminal=false\nCategories=System;Utility;\n"
            f"X-MaluOS-Agent={agent_id}\nStartupNotify=true\n")


def _write(path, text):
    cur = None
    try:
        cur = open(path).read()
    except OSError:
        pass
    if cur == text:
        return False
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.chmod(tmp, 0o755); os.replace(tmp, path)
    return True


def set_app_folder(file_ids):
    """The 'Agents' folder in the GNOME grid, holding exactly these launchers (removed when there are none)."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except Exception:
        return False
    src = Gio.SettingsSchemaSource.get_default()
    if not src or not src.lookup("org.gnome.desktop.app-folders", True):
        return False
    folders = Gio.Settings.new("org.gnome.desktop.app-folders")
    children = list(folders.get_strv("folder-children"))
    if file_ids:
        f = Gio.Settings.new_with_path("org.gnome.desktop.app-folders.folder", f"/org/gnome/desktop/app-folders/folders/{FOLDER}/")
        f.set_string("name", "Agents"); f.set_boolean("translate", False)
        f.set_strv("apps", [f"{PREFIX}{i}.desktop" for i in file_ids])
        if FOLDER not in children:
            folders.set_strv("folder-children", children + [FOLDER])
    elif FOLDER in children:
        folders.set_strv("folder-children", [c for c in children if c != FOLDER])
        f = Gio.Settings.new_with_path("org.gnome.desktop.app-folders.folder", f"/org/gnome/desktop/app-folders/folders/{FOLDER}/")
        f.set_strv("apps", [])
    Gio.Settings.sync()
    return True


def sync(state):
    """Write the launchers, the app folder and the Desktop folder for this state; returns a summary dict."""
    entries = agent_entries(state)
    ldir, ddir = launcher_dir(), os.path.join(desktop_dir(), "Agents")
    os.makedirs(ldir, exist_ok=True)
    wanted, changed = {}, 0
    for agent_id, name, comment, icon in entries:
        fid = file_id(agent_id)
        wanted[fid] = launcher_text(agent_id, name, comment, icon)
    for d in (ldir, ddir):
        if d == ddir and not wanted and not os.path.isdir(ddir):
            continue
        if d == ddir:
            os.makedirs(ddir, exist_ok=True)
        for fid, text in wanted.items():
            changed += _write(os.path.join(d, f"{PREFIX}{fid}.desktop"), text)
        for f in os.listdir(d):
            if f.startswith(PREFIX) and f.endswith(".desktop") and f[len(PREFIX):-8] not in wanted:
                os.remove(os.path.join(d, f)); changed += 1
    if not wanted and os.path.isdir(ddir) and not os.listdir(ddir):
        os.rmdir(ddir)
    folder = set_app_folder(list(wanted))
    if changed:
        try:
            subprocess.run(["update-desktop-database", ldir], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    return {"agents": len(wanted), "changed": changed, "launchers": [f"{PREFIX}{i}.desktop" for i in wanted], "folder": folder, "desktop_dir": ddir if wanted else None}
