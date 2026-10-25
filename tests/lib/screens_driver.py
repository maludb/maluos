#!/usr/bin/python3
"""An expect-style driver for the MaluOS installer's screens (Phase 11 slice 3).

It reads a terminal stream (a pty, or QEMU's serial socket), strips the escape sequences, waits
for each screen's title and sends the keys that answer it. `drive()` reproduces the medium's
unattended plan: login maluos, the test key, lvm, ext4, telemetry off. Used by
tests/install-screens-test.py (a pty on the build host) and tests/live-install-test.sh --screens
(the QEMU serial console, through the autologin shell).

  screens_driver.py --serial SOCKET --log FILE --disk vda --key FILE [--password maluos] [--sudo] [--no-change] [--telemetry] [--echo]
"""
import os, re, select, socket, sys, time

ESC = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[()][0-9A-Za-z]|\x1b[=>78DEHM]|\x1b\][^\x07]*(\x07|\x1b\\)|\x1b[#%][0-9A-Za-z]|\x1b")
ENTER, ESC_KEY, DOWN, UP, TAB, SPACE = b"\r", b"\x1b", b"\x1b[B", b"\x1b[A", b"\t", b" "


class Terminal:
    def __init__(self, read_fd, write_fn, log=None, echo=False):
        self.fd, self.write_fn, self.log, self.echo = read_fd, write_fn, log, echo
        self.text = ""

    def _pump(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return False
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            return False
        if not data:
            raise EOFError("the terminal closed")
        if self.log:
            self.log.write(data); self.log.flush()
        clean = ESC.sub(b"", data).replace(b"\r", b"")
        self.text += clean.decode("utf-8", "replace")
        if len(self.text) > 200000:
            self.text = self.text[-100000:]
        return True

    def expect(self, pattern, timeout=120):
        """Wait until the regex matches the stripped text; consume up to the match."""
        rx = re.compile(pattern)
        deadline = time.time() + timeout
        while True:
            m = rx.search(self.text)
            if m:
                self.text = self.text[m.end():]
                if self.echo:
                    print(f"   driver: saw {pattern!r}", flush=True)
                return m
            if time.time() > deadline:
                raise TimeoutError(f"waited {timeout}s for {pattern!r}; last text: {self.text[-400:]!r}")
            self._pump(min(1.0, max(0.05, deadline - time.time())))

    def send(self, data, pause=0.05):
        if isinstance(data, str):
            data = data.encode()
        for i in range(0, len(data), 32):
            self.write_fn(data[i:i + 32])
            time.sleep(pause)

    def type(self, text):
        self.send(text, pause=0.02)

    def settle(self, seconds=0.4):
        end = time.time() + seconds
        while time.time() < end:
            self._pump(0.1)


def drive(term, disk, key, login="maluos", password="maluos", fullname="MaluOS Test", telemetry=False,
          password_auth=True, change_required=True, sudo=False, screen_timeout=300):
    """Answer the nine screens so the plan equals the medium's unattended plan (plus the key and the disk).
    With sudo=True the driver first starts the installer from a shell prompt on the terminal."""
    if sudo:
        term.send(ENTER); term.settle(1.0)
        term.expect(r"\$ ", timeout=screen_timeout)
        term.send("sudo maluos-install\r")
    term.expect(r"Welcome \(1/9\)", timeout=screen_timeout); term.settle(); term.send(ENTER)
    term.expect(r"Keyboard \(2/9\)", timeout=60); term.settle(); term.send(ENTER)
    term.expect(r"Network \(3/9\)", timeout=60); term.settle(); term.send(ENTER)
    term.expect(r"Storage \(4/9\)", timeout=60); term.settle(); term.send(ENTER)
    term.expect(r"Type the disk's name", timeout=60); term.settle(); term.type(disk); term.send(ENTER)
    term.expect(r"Identity \(5/9\)", timeout=60); term.settle()
    term.send(DOWN); term.type(fullname)          # hostname keeps its default; then "Your name"
    term.send(DOWN); term.type(login)
    term.send(DOWN); term.type(password)
    term.send(DOWN); term.type(password)
    term.send(DOWN); term.type(key)               # the SSH keys box (multi-line)
    term.send(DOWN)                               # out of the keys box: "Run the SSH server" (kept)
    term.send(DOWN)
    if password_auth:
        term.send(SPACE)                          # "Allow SSH logins with a password"
    term.send(DOWN)
    if change_required:
        term.send(SPACE)                          # "The password must be changed at the first login"
    term.settle(); term.send(ENTER)
    term.expect(r"Components \(6/9\)", timeout=60); term.settle(); term.send(ENTER)
    term.expect(r"First boot \(7/9\)", timeout=60); term.settle(); term.send(ENTER)
    term.expect(r"Help improve MaluOS \(8/9\)", timeout=60); term.settle()
    if not telemetry:
        term.send(DOWN); term.send(SPACE)
    term.send(ENTER)
    term.expect(r"Summary \(9/9\)", timeout=60); term.settle(1.0); term.send(ENTER)   # Install (or Save and finish)


def main(argv):
    opts = {"--serial": None, "--log": None, "--disk": "vda", "--key": None, "--password": "maluos", "--login": "maluos"}
    flags = set()
    it = iter(argv)
    for a in it:
        if a in opts:
            opts[a] = next(it)
        elif a in ("--sudo", "--telemetry", "--echo", "--no-change"):
            flags.add(a)
        else:
            sys.exit(__doc__)
    if not opts["--serial"] or not opts["--key"]:
        sys.exit(__doc__)
    key = open(opts["--key"]).read().strip()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    for _ in range(120):
        try:
            s.connect(opts["--serial"]); break
        except OSError:
            time.sleep(1)
    else:
        sys.exit(f"no serial socket at {opts['--serial']}")
    log = open(opts["--log"], "ab", buffering=0) if opts["--log"] else None
    term = Terminal(s.fileno(), s.sendall, log=log, echo="--echo" in flags)
    try:
        drive(term, opts["--disk"], key, login=opts["--login"], password=opts["--password"], telemetry="--telemetry" in flags,
              change_required="--no-change" not in flags, sudo="--sudo" in flags, screen_timeout=900)
        print("driver: the screens are answered; the install is running", flush=True)
        term.expect(r"Installation complete", timeout=5400); term.settle(1.0); term.send(ENTER)
        term.expect(r"maluos-install: finished \((reboot|poweroff|none|shell)\)", timeout=120)
        print("driver: maluos-install: finished", flush=True)
    except (TimeoutError, EOFError) as e:
        print(f"driver: FAILED: {e}", flush=True)
        return 1
    finally:
        # keep logging until the VM goes away so the serial log is complete
        try:
            while True:
                if not term._pump(5.0):
                    break
        except (EOFError, OSError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
