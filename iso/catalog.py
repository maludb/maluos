#!/usr/bin/python3
"""Build /maluos/catalog.yaml for the installer medium: the components (the seeds' metapackages)
with their description, whether the target image already carries them, and the installed size of
their MaluOS packages in the on-media repository (approximate: the seed's own packages, not the
whole dependency closure; Ubuntu packages are not on the medium).

  iso/catalog.py SEEDS_DIR DESCRIPTIONS PACKAGES_INDEX TARGET_MANIFEST [OFFLINE_LIST] > catalog.yaml

OFFLINE_LIST (iso/extra-pool.py's offline.txt) names the components whose Ubuntu dependencies the
medium carries; a component not in the image and not in the list gets `offline: false`, and the
installer refuses it until the network path exists. Without the list every component is offline.
"""
import os, sys


def read_seed(path):
    pkgs = []
    for line in open(path):
        line = line.split("#", 1)[0].strip()
        if line:
            pkgs.append(line.lstrip("?"))
    return pkgs


def read_descriptions(path):
    out = {}
    for line in open(path):
        if "|" in line and not line.startswith("#"):
            name, title, desc = (line.rstrip("\n").split("|", 2) + ["", ""])[:3]
            out[name.strip()] = (title.strip(), desc.strip())
    return out


def read_packages(path):
    sizes, para = {}, {}
    for line in list(open(path)) + ["\n"]:
        if line.strip() == "":
            if para.get("Package"):
                sizes[para["Package"]] = int(para.get("Installed-Size", "0") or 0)
            para = {}
        elif ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1); para[k.strip()] = v.strip()
    return sizes


def read_manifest(path):
    return {l.split("\t")[0].strip() for l in open(path) if l.strip()}


def main(seeds_dir, descriptions, packages, manifest, offline_list=None):
    desc = read_descriptions(descriptions)
    sizes = read_packages(packages)
    inimg = read_manifest(manifest)
    offline = {l.strip() for l in open(offline_list) if l.strip()} if offline_list and os.path.exists(offline_list) else None
    print("# The components this medium can install (iso/catalog.py): name, description, whether the target")
    print("# image already carries it, and the installed size of its MaluOS packages on the medium (approximate).")
    print("components:")
    for f in sorted(os.listdir(seeds_dir)):
        if not f.endswith(".seed"):
            continue
        short = f[:-5]
        if short in ("base", "live"):
            continue
        name = f"maluos-{short}"
        pkgs = read_seed(os.path.join(seeds_dir, f))
        kib = sum(sizes.get(p, 0) for p in [name] + pkgs)
        title, text = desc.get(short, (name, ""))
        print(f"  - name: {name}")
        print(f"    title: {title!r}" if "'" in title else f"    title: \"{title}\"")
        print(f"    description: \"{text.replace(chr(34), chr(39))}\"")
        print(f"    in_image: {'true' if name in inimg else 'false'}")
        print(f"    offline: {'true' if (name in inimg or offline is None or name in offline) else 'false'}")
        print(f"    size_mb: {(kib + 1023) // 1024}")
        print(f"    packages: [{', '.join(pkgs)}]")


if __name__ == "__main__":
    if len(sys.argv) not in (5, 6):
        print(__doc__); sys.exit(2)
    main(*sys.argv[1:])
