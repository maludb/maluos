#!/usr/bin/python3
"""The Ubuntu packages the medium's components need that the target image lacks, downloaded into a
flat repository on the medium (/maluos/apt/extra), so the installer can add a component offline.
Every component of the catalogue is resolved (the API server's Python stack, the Apple T2 toolchain
and Vulkan, ...); one that cannot be resolved from the archive is reported as not installable
offline and the catalogue says so (iso/catalog.py --offline), unless it is --require'd, which
fails the build.

  iso/extra-pool.py --manifest IMAGE.manifest --squashfs IMAGE.squashfs --repo MEDIA/maluos/apt --out DIR
                    [--require maluos-apple-t2] maluos-api maluos-apple-t2 ...

apt does the resolving: the host's Ubuntu sources plus the on-media MaluOS repository as a file:
source, against the image's own dpkg status (read out of the squashfs), download-only, without
Ubuntu's recommends (the chroot's apt skips what the medium lacks); the MaluOS packages apt fetches
are dropped again (the on-media repository has them). Writes DIR/Packages(.gz) and DIR/offline.txt,
the components that resolved. The image's kernel headers are requested by the manifest's kernel
version and must still be downloadable: when the archive has moved on, the images are rebuilt first.
"""
import glob, os, re, shutil, subprocess, sys, tempfile


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
    opts = {"--manifest": None, "--squashfs": None, "--repo": None, "--out": None}
    require, comps = set(), []
    it = iter(argv)
    for a in it:
        if a in opts:
            opts[a] = next(it)
        elif a == "--require":
            n = next(it); require.add(n); comps.append(n)
        elif a.startswith("-"):
            sys.exit(__doc__)
        else:
            comps.append(a)
    if not all(opts.values()) or not comps:
        sys.exit(__doc__)
    comps = list(dict.fromkeys(comps))
    manifest = {}
    for line in open(opts["--manifest"]):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 2:
            manifest[f[0].split(":")[0]] = f[1]
    kernels = sorted(v[len("linux-image-"):] for v in manifest if re.match(r"^linux-image-\d.*-generic$", v))
    idx_paths = glob.glob(os.path.join(opts["--repo"], "dists/*/*/binary-amd64/Packages"))
    index = read_index(idx_paths[0]) if idx_paths else {}
    suite = idx_paths[0].split("/dists/")[1].split("/")[0] if idx_paths else "resolute"
    out = os.path.abspath(opts["--out"])
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="maluos-extra-pool-")
    try:
        status = os.path.join(tmp, "status")
        text = subprocess.run(["unsquashfs", "-cat", opts["--squashfs"], "var/lib/dpkg/status"], capture_output=True, text=True).stdout
        if not text.strip():
            text = "".join(f"Package: {n}\nStatus: install ok installed\nVersion: {v}\nArchitecture: amd64\n\n" for n, v in manifest.items())
        open(status, "w").write(text)
        # the sources: the host's Ubuntu ones and the on-media MaluOS repository
        parts = os.path.join(tmp, "sources.list.d"); os.makedirs(parts)
        for f in glob.glob("/etc/apt/sources.list.d/*.sources") + glob.glob("/etc/apt/sources.list.d/*.list"):
            if "maluos" not in os.path.basename(f) and "mozilla" not in os.path.basename(f):
                shutil.copy(f, parts)
        open(os.path.join(parts, "maluos-media.list"), "w").write(f"deb [trusted=yes] file:{os.path.abspath(opts['--repo'])} {suite} main\n")
        for d in ("lists/partial", "cache/archives/partial"):
            os.makedirs(os.path.join(tmp, d))
        os.makedirs(os.path.join(out, "partial"), exist_ok=True)
        base = ["apt-get", "-q", "-y", "-o", f"Dir::State::status={status}", "-o", f"Dir::State::lists={tmp}/lists", "-o", f"Dir::Cache={tmp}/cache",
                "-o", f"Dir::Etc::SourceList={tmp}/sources.list", "-o", f"Dir::Etc::SourceParts={parts}", "-o", "Dir::Etc::Preferences=/dev/null",
                "-o", "Dir::Etc::PreferencesParts=/dev/null", "-o", "Debug::NoLocking=1", "-o", "APT::Install-Recommends=0"]
        open(os.path.join(tmp, "sources.list"), "w").close()
        r = subprocess.run(base + ["update"], capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr[-1500:]); sys.exit("extra-pool: apt-get update failed")
        resolved, failed = [], {}
        for comp in comps:
            want = [comp] + [n for n in dep_names(index.get(comp, {}).get("Recommends")) if n in index]
            want += [f"linux-headers-{k}" for k in kernels]
            r = subprocess.run(base + ["-o", f"Dir::Cache::archives={out}", "-o", "APT::Get::Download-Only=1", "install"] + want, capture_output=True, text=True)
            if r.returncode:
                reason = next((l for l in (r.stderr + r.stdout).splitlines() if l.startswith("E:")), "unresolvable")
                failed[comp] = reason
            else:
                resolved.append(comp)
        shutil.rmtree(os.path.join(out, "partial"), ignore_errors=True)
        for f in ("lock",):
            try:
                os.remove(os.path.join(out, f))
            except OSError:
                pass
        dropped = 0
        for deb in glob.glob(os.path.join(out, "*.deb")):
            name = subprocess.run(["dpkg-deb", "-f", deb, "Package"], capture_output=True, text=True).stdout.strip()
            if name in index:
                os.remove(deb); dropped += 1
        debs = sorted(f for f in os.listdir(out) if f.endswith(".deb"))
        if debs:
            idx = subprocess.run(["dpkg-scanpackages", "--multiversion", "."], cwd=out, capture_output=True, text=True, check=True).stdout
            open(os.path.join(out, "Packages"), "w").write(idx)
            subprocess.run(["gzip", "-kf", "Packages"], cwd=out, check=True)
        open(os.path.join(out, "offline.txt"), "w").write("".join(c + "\n" for c in resolved))
        size = sum(os.path.getsize(os.path.join(out, d)) for d in debs)
        print(f"extra-pool: {len(debs)} Ubuntu packages, {size >> 20} MB, for {', '.join(resolved) or 'nothing'}")
        for comp, reason in failed.items():
            print(f"extra-pool: {comp} is not installable offline from this medium: {reason}")
        missing = [c for c in comps if c in failed and c in require]
        if missing:
            sys.exit(f"extra-pool: required component(s) {', '.join(missing)} could not be resolved (the image's kernel {', '.join(kernels)}: rebuild the images if the archive has moved on)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
