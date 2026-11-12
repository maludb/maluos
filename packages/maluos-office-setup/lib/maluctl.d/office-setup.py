"""maluctl office-setup: configure this office's Business OS with the maluos-office-setup plugin.

  maluctl office-setup [run]            install Claude Code for you if missing (Anthropic's native installer,
                                        ~/.local/bin/claude), then start it with the plugin loaded and /office-setup
                                        running. As the operator, not as root; in tmux (provisioning takes minutes).
  maluctl office-setup shell            Claude Code with the plugin loaded, no skill started
  maluctl office-setup check            the completion report, without Claude (scripts/preflight.py --report)
  maluctl office-setup status           the state, readable, without Claude (scripts/preflight.py --human)
  maluctl office-setup providers PROVIDER [--from-file F] [--mail-from ADDR]
                                        a provider key through the protected prompt (scripts/set-provider-key.sh);
                                        anthropic, openrouter, openai, deepseek, moonshot, fireworks, malumail
  maluctl office-setup providers --status
  maluctl office-setup admin [check]    does the first sign-in work, and if not, why (scripts/admin-login.py --check):
                                        the administrator's member, the stored password against it, the sign-in
                                        throttle, the session cookie, a real sign-in on the office. No password shown.
  maluctl office-setup admin reset      a new generated password for the administrator, stored root-only
                                        (/var/lib/maluos/secrets/business-os/admin-password); then the same checks
  maluctl office-setup database [--show | --check … | --apply …]
                                        where this server keeps its data, and a MaluOS database server tested and set
                                        (scripts/database-server.py; --help there for the arguments)
  maluctl office-setup website          the office's public page (the bare name): Claude Code with /office-website,
                                        which turns the starter page into the business's own on a working copy
  maluctl office-setup website status | checkout DIR | publish DIR | restore [BACKUP]
                                        the same steps without Claude (scripts/landing-site.sh)

The plugin is /usr/share/maluos/claude-plugins/maluos-office-setup (the package maluos-office-setup); its
sudoers rule lets members of sudo run its scripts as root without a password, which check, status and
providers use through sudo -n when you are not root. The handbook: 10-office-configuration.md.
"""
import os, pwd, shutil, subprocess, sys

ROOT = os.environ.get("MALUOS_OFFICE_SETUP_ROOT", "/usr/share/maluos/claude-plugins/maluos-office-setup")
INSTALLER = "https://claude.ai/install.sh"


def home():
    return os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir


def claude_path():
    env_path = os.environ.get("PATH", "") + ":" + os.path.join(home(), ".local", "bin")
    return shutil.which("claude", path=env_path)


PATH_MARK = "# added by maluctl office-setup: Claude Code lives in ~/.local/bin"


def ensure_on_path():
    """Anthropic's installer puts claude in ~/.local/bin, which a shell opened before the install does not
    search (the login profile adds the directory only when it exists at login). Without this, `claude` typed
    after the setup answers "command not found". Add it to ~/.bashrc once, and say what to do in this shell."""
    local = os.path.join(home(), ".local", "bin")
    if local in os.environ.get("PATH", "").split(":"):
        return
    rc = os.path.join(home(), ".bashrc")
    try:
        text = open(rc).read() if os.path.exists(rc) else ""
        if PATH_MARK not in text:
            with open(rc, "a") as f:
                f.write(f'\n{PATH_MARK}\ncase ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac\n')
    except OSError as e:
        print(f"(could not add ~/.local/bin to {rc}: {e})", file=sys.stderr)
    print("Note: `claude` is installed in ~/.local/bin, which this shell does not search yet. A new terminal finds it;\n"
          "      in this one run:  export PATH=\"$HOME/.local/bin:$PATH\"\n"
          "      `maluctl office-setup` and `maluctl office-setup shell` always find it.", flush=True)


def ensure_claude():
    if os.geteuid() == 0:
        sys.exit("maluctl office-setup: run this as the operator account (maluos), not as root; the plugin's scripts elevate themselves")
    c = claude_path()
    if c:
        ensure_on_path()
        return c
    print(f"Claude Code is not installed for {pwd.getpwuid(os.getuid()).pw_name}; installing with Anthropic's native installer ({INSTALLER}) ...", flush=True)
    r = subprocess.run(["bash", "-c", f"curl -fsSL {INSTALLER} | bash"], env=dict(os.environ, HOME=home()))
    if r.returncode != 0:
        sys.exit("the Claude Code installer failed; see its output above (network access to claude.ai is needed)")
    c = claude_path()
    if not c:
        sys.exit("claude is not on PATH after the install; add ~/.local/bin to PATH and run again")
    print(f"Claude Code: {subprocess.run([c, '--version'], capture_output=True, text=True).stdout.strip() or c}")
    ensure_on_path()
    return c


def as_root(cmd):
    """Run a plugin script as root: directly when root, through sudo -n otherwise; fall back to unprivileged."""
    if os.geteuid() == 0:
        return subprocess.call(cmd)
    if subprocess.call(["sudo", "-n", "true"], stderr=subprocess.DEVNULL) == 0:
        return subprocess.call(["sudo", "-n", *cmd])
    print("(no passwordless sudo for the plugin's scripts: running without root; root-only files read as unknown)", file=sys.stderr)
    return subprocess.call(cmd)


def main(args):
    if not os.path.isdir(ROOT):
        print(f"the plugin is not installed at {ROOT} (apt install maluos-office-setup)", file=sys.stderr); return 1
    if args and args[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    verb = args[0] if args else "run"
    rest = args[1:]
    scripts = os.path.join(ROOT, "scripts")
    if verb in ("run", "shell"):
        c = ensure_claude()
        os.environ["PATH"] = os.environ.get("PATH", "") + ":" + os.path.join(home(), ".local", "bin")
        if not os.path.exists("/etc/maluos/firstboot.yaml"):
            print("warning: /etc/maluos/firstboot.yaml is missing; this does not look like a MaluOS office", file=sys.stderr)
        cmd = [c, "--plugin-dir", ROOT] + ([] if verb == "shell" else [rest[0] if rest else "/office-setup"])
        os.execv(c, cmd)
    if verb == "database":
        return as_root([os.path.join(scripts, "database-server.py"), *(rest or ["--show"])])
    if verb == "website":
        if not rest:
            c = ensure_claude()
            os.environ["PATH"] = os.environ.get("PATH", "") + ":" + os.path.join(home(), ".local", "bin")
            os.execv(c, [c, "--plugin-dir", ROOT, "/office-website"])
        if rest[0] not in ("status", "checkout", "publish", "restore"):
            print(__doc__); return 2
        return as_root([os.path.join(scripts, "landing-site.sh"), *rest])
    if verb == "check":
        return as_root([os.path.join(scripts, "preflight.py"), "--report"])
    if verb == "status":
        return as_root([os.path.join(scripts, "preflight.py"), "--human"])
    if verb == "admin":
        sub = rest[0] if rest else "check"
        if sub not in ("check", "reset"):
            print(__doc__); return 2
        return as_root([os.path.join(scripts, "admin-login.py"), "--" + sub, *rest[1:]])
    if verb == "providers":
        if not rest:
            print(__doc__); return 2
        if rest[0] == "--status":
            return as_root([os.path.join(scripts, "set-provider-key.sh"), "--status"])
        if os.geteuid() != 0 and subprocess.call(["sudo", "-n", "true"], stderr=subprocess.DEVNULL) != 0:
            # the prompt needs a terminal and root: plain sudo asks for the operator's password here, which is fine in their terminal
            return subprocess.call(["sudo", os.path.join(scripts, "set-provider-key.sh"), *rest])
        return as_root([os.path.join(scripts, "set-provider-key.sh"), *rest])
    print(__doc__); return 2
