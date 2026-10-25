#!/usr/bin/python3
"""Drive a QEMU serial console on a unix socket: log everything to a file and answer the LUKS
passphrase prompt (tests/live-install-test.sh --encrypt).

  serial-answer.py SOCKET LOGFILE PASSPHRASE
"""
import socket, sys, time

sock_path, log_path, passphrase = sys.argv[1:4]
PROMPTS = (b"Please enter passphrase", b"passphrase for disk", b"Enter passphrase")
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
for _ in range(60):
    try:
        s.connect(sock_path); break
    except OSError:
        time.sleep(1)
else:
    sys.exit(f"no serial socket at {sock_path}")
s.settimeout(1.0)
buf = b""; answered = 0
with open(log_path, "ab", buffering=0) as log:
    while True:
        try:
            data = s.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            break
        if not data:
            break
        log.write(data)
        buf = (buf + data)[-4096:]
        if any(p in buf for p in PROMPTS):
            time.sleep(0.5)
            s.sendall(passphrase.encode() + b"\n")
            answered += 1
            log.write(f"\n[serial-answer: passphrase sent ({answered})]\n".encode())
            buf = b""
