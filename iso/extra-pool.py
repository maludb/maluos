#!/usr/bin/python3
"""The Ubuntu packages a component needs that the target image lacks, downloaded into a flat
repository on the medium (/maluos/apt/extra), so the installer can add the component offline.
Built for the apple-t2 component (the Apple T2 round): DKMS and its toolchain, the kernel headers
of the image's kernel, Vulkan, the audio DSP's plugins. The MaluOS and vendored packages are in the
on-media repository already; this resolves only what is Ubuntu's.

  iso/extra-pool.py --manifest IMAGE.manifest --index PACKAGES --out DIR --seed seeds/apple-t2.seed [--seed ...] [--squashfs IMAGE.squashfs]

The host's apt (its lists and sources) does the resolving against the image's own dpkg status (read
out of the squashfs with --squashfs; else one made from the manifest), so only what the image lacks
is fetched, without the recommends of Ubuntu's packages (the chroot's apt skips what the medium
lacks). The image's kernel headers are requested by the manifest's kernel version and must still be
downloadable: when the archive has moved on, the images are rebuilt first.
"""
import os, re, shutil, subprocess, sys, tempfile


def read_seed(path):
    out = []
    for line in open(path):
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.lstrip("?"))
    return out


def read_index(path):
    pkgs, para = {}, {}
    for line in list(open(path)) + ["\n"]:
        if not line.strip():
            if para.get("Package"):
                pkgs[para["Package"]] = para
            para = {}
        elif ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1); para[k.strip()] = v.strip()
    return pkgs


def dep_names(field):
    names = []
    for alt in (field or "").split(","):
        first = alt.split("|")[0].strip()
        name = re.sub(r"\s*\(.*\)|\s*\[.*\]|\s*<.*>|:any$", "", first).strip()
        if name:
            names.append(name)
    return names


def main(argv):
    opts = {"--manifest": None, "--index": None, "--out": None, "--squashfs": None}
    seeds = []
    it = iter(argv)
    for a in it:
        if a in opts:
            opts[a] = next(it)
        elif a == "--seed":
            seeds.append(next(it))
        else:
            sys.exit(__doc__)
    if not all(v for k, v in opts.items() if k != "--squashfs") or not seeds:
        sys.exit(__doc__)
    manifest = {}
    for line in open(opts["--manifest"]):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 2:
            manifest[f[0].split(":")[0]] = f[1]
    index = read_index(opts["--index"])
    # the Ubuntu names: the seeds' entries not on the medium, plus the Depends and Recommends of the medium's packages the seeds name
    want = set()
    for seed in seeds:
        for name in read_seed(seed):
            if name in index:
                for field in ("Depends", "Recommends"):
                    want.update(dep_names(index[name].get(field)))
            else:
                want.add(name)
    want = {n for n in want if n not in index and n not in manifest}
    kernels = sorted(v[len("linux-image-"):] for v in manifest if re.match(r"^linux-image-\d.*-generic$", v))
    for k in kernels:
        want.add(f"linux-headers-{k}")
    if not want:
        print("extra-pool: nothing to fetch"); return 0
    out = os.path.abspath(opts["--out"])
    tmp = tempfile.mkdtemp(prefix="maluos-extra-pool-")
    try:
        status = os.path.join(tmp, "status")
        text = ""
        if opts["--squashfs"]:   # the image's own records (Architecture, Multi-Arch, Provides): apt then re-fetches nothing it has
            text = subprocess.run(["unsquashfs", "-cat", opts["--squashfs"], "var/lib/dpkg/status"], capture_output=True, text=True).stdout
        if not text.strip():
            text = "".join(f"Package: {name}\nStatus: install ok installed\nVersion: {ver}\nArchitecture: amd64\n\n" for name, ver in manifest.items())
        open(status, "w").write(text)
        os.makedirs(os.path.join(tmp, "cache/archives/partial"), exist_ok=True)
        os.makedirs(os.path.join(out, "partial"), exist_ok=True)
        cmd = ["apt-get", "-q", "-y", "-o", f"Dir::State::status={status}", "-o", f"Dir::Cache={tmp}/cache",
               "-o", f"Dir::Cache::archives={out}", "-o", "Debug::NoLocking=1", "-o", "APT::Get::Download-Only=1",
               "-o", "APT::Install-Recommends=0", "-o", "APT::Get::AllowUnauthenticated=0", "install"] + sorted(want)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stdout[-2000:] + r.stderr[-2000:])
            sys.exit(f"extra-pool: apt-get could not resolve or fetch {' '.join(sorted(want))} (the image's kernel {', '.join(kernels)}: "
                     "rebuild the images if the archive has moved on)")
        shutil.rmtree(os.path.join(out, "partial"), ignore_errors=True)
        for f in ("lock",):
            try:
                os.remove(os.path.join(out, f))
            except OSError:
                pass
        debs = sorted(f for f in os.listdir(out) if f.endswith(".deb"))
        if not debs:
            sys.exit("extra-pool: apt-get fetched nothing")
        idx = subprocess.run(["dpkg-scanpackages", "--multiversion", "."], cwd=out, capture_output=True, text=True, check=True).stdout
        open(os.path.join(out, "Packages"), "w").write(idx)
        subprocess.run(["gzip", "-kf", "Packages"], cwd=out, check=True)
        size = sum(os.path.getsize(os.path.join(out, d)) for d in debs)
        print(f"extra-pool: {len(debs)} Ubuntu packages, {size >> 20} MB, for {', '.join(sorted(want))}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
