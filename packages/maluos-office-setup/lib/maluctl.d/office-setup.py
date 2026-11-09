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


def ensure_claude():
    if os.geteuid() == 0:
        sys.exit("maluctl office-setup: run this as the operator account (maluos), not as root; the plugin's scripts elevate themselves")
    c = claude_path()
    if c:
        return c
    print(f"Claude Code is not installed for {pwd.getpwuid(os.getuid()).pw_name}; installing with Anthropic's native installer ({INSTALLER}) ...", flush=True)
    r = subprocess.run(["bash", "-c", f"curl -fsSL {INSTALLER} | bash"], env=dict(os.environ, HOME=home()))
    if r.returncode != 0:
        sys.exit("the Claude Code installer failed; see its output above (network access to claude.ai is needed)")
    c = claude_path()
    if not c:
        sys.exit("claude is not on PATH after the install; add ~/.local/bin to PATH and run again")
    print(f"Claude Code: {subprocess.run([c, '--version'], capture_output=True, text=True).stdout.strip() or c}")
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
    if verb == "check":
        return as_root([os.path.join(scripts, "preflight.py"), "--report"])
    if verb == "status":
        return as_root([os.path.join(scripts, "preflight.py"), "--human"])
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
