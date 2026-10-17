#!/usr/bin/python3
"""Drive subiquity's text UI over a QEMU serial socket, rendering it with pyte.

usage: tui-driver.py <socket> <outdir>
Steps: Serial screen -> "Continue in rich mode"; then wait for the language
screen or the "Sorry ..." dialog; dump each screen as text to <outdir>.
On the error dialog, press F1 to show the Help menu and dump it.
"""
import re, socket, sys, time
sys.path.append('/usr/lib/python3/dist-packages')
import pyte

sock, outdir = sys.argv[1], sys.argv[2]
s = None
for _ in range(120):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(sock); break
    except OSError:
        time.sleep(1)
s.settimeout(1)
scr = pyte.Screen(80, 24); st = pyte.ByteStream(scr)
raw = open(f"{outdir}/tui-raw.log", "ab")

def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        try:
            d = s.recv(65536)
            if d:
                st.feed(d); raw.write(d); raw.flush()
        except socket.timeout:
            pass

def screen():
    return "\n".join(l.rstrip() for l in scr.display)

def dump(name):
    txt = screen()
    open(f"{outdir}/screen-{name}.txt", "w").write(txt)
    print(f"--- screen {name} ---\n{txt}\n", flush=True)

def wait_for(pattern, limit, step=5):
    end = time.time() + limit
    while time.time() < end:
        pump(step)
        if re.search(pattern, screen(), re.S | re.I):
            return True
    return False

print("waiting for the Serial screen", flush=True)
if not wait_for(r"basic mode", 2400):
    dump("timeout-serial"); sys.exit(2)
dump("serial"); pump(2)
s.sendall(b"\r")                      # "Continue in rich mode" is focused
print("sent Enter for rich mode", flush=True)
ok = wait_for(r"select your language|Your name|Enter the username|Sorry,|restarted|internal error", 1500)
dump("after-serial")
if re.search(r"Sorry,|restarted|internal error", screen(), re.I):
    print("ERROR DIALOG REPRODUCED", flush=True)
    s.sendall(b"\x1bOP")              # F1 -> Help menu
    wait_for(r"shell|SSH", 60); dump("help-menu")
elif ok and re.search(r"Your name", screen()):
    print("IDENTITY SCREEN OK; filling the form", flush=True)
    def keys(b, settle=8):
        s.sendall(b); pump(settle)
    keys(b"Edward Honour")            # Your name (focused)
    dump("typed-name")
    keys(b"\x1b[B"); keys(b"\x1b[B")  # down to server name, then username (prefilled)
    keys(b"\x1b[B"); keys(b"Maluos-Test1")      # password
    keys(b"\x1b[B"); keys(b"Maluos-Test1")      # confirm
    dump("filled")
    keys(b"\x1b[B", 4); keys(b"\r", 30)        # Done
    wait_for(r"SSH|Sorry,|restarted|internal error", 600)
    dump("after-done")
    if re.search(r"Sorry,|restarted|internal error", screen(), re.I):
        print("ERROR DIALOG REPRODUCED AFTER FORM", flush=True)
        s.sendall(b"\x1bOP"); wait_for(r"shell|SSH", 60); dump("help-menu")
    else:
        print("FORM SUBMITTED OK", flush=True)
elif ok:
    print("SCREEN OK (no dialog)", flush=True)
    pump(180); dump("after-3min")
    if re.search(r"Sorry,|restarted|internal error", screen(), re.I):
        print("ERROR DIALOG APPEARED LATER", flush=True)
        s.sendall(b"\x1bOP"); wait_for(r"shell|SSH", 60); dump("help-menu")
else:
    print("NEITHER (timeout)", flush=True)
