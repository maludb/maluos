#!/usr/bin/python3
"""The installer's screens driven in a pty (Phase 11 slice 3), no root, no VM: the wizard runs with
--no-hardware and a staged medium, the driver answers the nine screens as tests/lib/screens_driver.py
does on the serial console, and the saved plan is compared with the medium's unattended plan.

  python3 tests/install-screens-test.py [--keep]
"""
import fcntl, os, pty, struct, subprocess, sys, tempfile, termios, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests/lib"))
sys.path.insert(0, os.path.join(ROOT, "packages/maluos-installer/lib"))
import screens_driver as D                      # noqa: E402
from maluos_installer import plan as P          # noqa: E402

try:
    import yaml
except ImportError:
    sys.exit("python3-yaml is needed")

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAtestkeytestkeytestkeytestkeytestkeytestkey maluos-screens-test"


def main(argv):
    keep = "--keep" in argv
    work = tempfile.mkdtemp(prefix="maluos-screens-")
    media = os.path.join(work, "media")
    os.makedirs(os.path.join(media, ".disk")); os.makedirs(os.path.join(media, "maluos/plan"))
    open(os.path.join(media, ".disk/info"), "w").write("MaluOS 26.04 Server amd64 (test)\n")
    # the catalogue as the ISO build makes it, from the repository's seeds (no package index: sizes 0)
    cat = subprocess.run([sys.executable, os.path.join(ROOT, "iso/catalog.py"), os.path.join(ROOT, "seeds"),
                          os.path.join(ROOT, "packages/maluos-meta/debian/descriptions"), "/dev/null", "/dev/null"],
                         capture_output=True, text=True)
    open(os.path.join(media, "maluos/catalog.yaml"), "w").write(cat.stdout)
    out = os.path.join(work, "plan.yaml")
    log = open(os.path.join(work, "terminal.log"), "wb")
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(TERM="vt220", LANG="C.UTF-8", LC_ALL="C.UTF-8", MALUOS_INSTALL_MEDIA=media, TMPDIR=work)
        os.execv(sys.executable, [sys.executable, os.path.join(ROOT, "packages/maluos-installer/bin/maluos-install"),
                                  "--screens", "--no-hardware", "--media", media, "--save-plan", out])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    term = D.Terminal(fd, lambda b: os.write(fd, b), log=log, echo=True)
    rc = 0
    try:
        D.drive(term, "sda", KEY, screen_timeout=60)
        term.expect(r"maluos-install: the plan is saved at", timeout=60)
    except (TimeoutError, EOFError) as e:
        print(f"FAIL: {e}"); rc = 1
    try:
        _, status = os.waitpid(pid, 0)
    except ChildProcessError:
        status = 0
    log.close()
    if rc == 0 and not os.path.exists(out):
        print("FAIL: no plan was saved"); rc = 1
    if rc == 0:
        saved = yaml.safe_load(open(out))["maluos-install"]
        expected = yaml.safe_load(open(os.path.join(ROOT, "iso/plans/server-unattended.yaml")))["maluos-install"]
        expected["storage"]["disk"] = "/dev/sda"
        expected["identity"]["user"]["ssh_keys"] = [KEY]
        expected["identity"]["user"]["fullname"] = "MaluOS Test"
        expected["bootloader"] = {}                      # no bootloader screen: the defaults
        exp = P.fill_defaults(expected, "server"); exp.pop("_variant", None)
        got_hash = saved["identity"]["user"]["password"]
        if not got_hash.startswith("$6$"):
            print(f"FAIL: the password is not a SHA-512 crypt hash: {got_hash[:10]}"); rc = 1
        else:
            salt = got_hash.split("$")[2]
            check = subprocess.run(["openssl", "passwd", "-6", "-salt", salt, "maluos"], capture_output=True, text=True).stdout.strip()
            if check != got_hash:
                print("FAIL: the hash does not verify against the typed password"); rc = 1
            else:
                print("  ok   the password is a SHA-512 crypt hash of what was typed")
        saved["identity"]["user"]["password"] = exp["identity"]["user"]["password"]
        for section in exp:
            if saved.get(section) != exp[section]:
                print(f"FAIL: section {section} differs:\n   screens:    {saved.get(section)}\n   unattended: {exp[section]}"); rc = 1
            else:
                print(f"  ok   {section} matches the unattended plan")
    if rc == 0:
        print("PASS: the screens build the medium's unattended plan")
    else:
        print(f"the terminal log is {work}/terminal.log")
    if not keep and rc == 0:
        subprocess.run(["rm", "-rf", work])
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
