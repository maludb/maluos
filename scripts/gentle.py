#!/usr/bin/env python3
"""Copy or checksum large files without filling the page cache.

  scripts/gentle.py cp  SRC... DEST_DIR  [--rate MB/s]   copy, print "sha256  size  dest" per file
  scripts/gentle.py cp  SRC DEST_FILE    [--rate MB/s]   copy under a new name
  scripts/gentle.py sum FILE...          [--rate MB/s]   print sha256sum-format lines

Every chunk read or written is released from the page cache (fdatasync +
posix_fadvise DONTNEED) and the stream is capped at --rate (default 100
MB/s). Reason: the dev VM is killed by its hypervisor when the guest's page
cache grows to its full RAM, which plain cp and sha256sum over the 13 GB of
images on the share did twice on 2026-10-22 (20:30 and 21:07) with nothing
in the guest's journal. Copies go to DEST.part and are renamed when complete.
"""
import argparse, hashlib, os, sys, time

CHUNK = 8 << 20
SYNC_EVERY = 8  # chunks between fdatasync + release on the destination


def read_chunks(path, rate):
    fd = os.open(path, os.O_RDONLY)
    try:
        off, t0 = 0, time.monotonic()
        while True:
            b = os.read(fd, CHUNK)
            if not b:
                break
            off += len(b)
            yield b
            os.posix_fadvise(fd, 0, off, os.POSIX_FADV_DONTNEED)
            if rate:
                due = t0 + off / (rate * 1048576)
                now = time.monotonic()
                if due > now:
                    time.sleep(due - now)
    finally:
        os.close(fd)


def checksum(path, rate):
    h = hashlib.sha256()
    n = 0
    for b in read_chunks(path, rate):
        h.update(b); n += len(b)
    return h.hexdigest(), n


def copy(src, dest_dir, rate):
    dest = os.path.join(dest_dir, os.path.basename(src)) if os.path.isdir(dest_dir) else dest_dir
    dest_dir = os.path.dirname(dest) or "."
    part = dest + ".part"
    h = hashlib.sha256()
    n = 0
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        i = 0
        for b in read_chunks(src, rate):
            os.write(fd, b); h.update(b); n += len(b); i += 1
            if i % SYNC_EVERY == 0:
                os.fdatasync(fd)
                os.posix_fadvise(fd, 0, n, os.POSIX_FADV_DONTNEED)
        os.fsync(fd)
        os.posix_fadvise(fd, 0, n, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)
    os.rename(part, dest)
    dfd = os.open(dest_dir, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return h.hexdigest(), n, dest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["cp", "sum"])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--rate", type=float, default=100, help="MB/s cap, 0 for none")
    a = ap.parse_args()
    if a.mode == "sum":
        for p in a.paths:
            digest, n = checksum(p, a.rate)
            print(f"{digest}  {p}", flush=True)
    else:
        if len(a.paths) < 2 or (len(a.paths) > 2 and not os.path.isdir(a.paths[-1])):
            sys.exit("cp needs SRC... DEST_DIR, or SRC DEST_FILE")
        for src in a.paths[:-1]:
            digest, n, dest = copy(src, a.paths[-1], a.rate)
            print(f"{digest}  {n}  {dest}", flush=True)


if __name__ == "__main__":
    main()
