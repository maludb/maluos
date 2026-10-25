"""unpack: the target image verified against /maluos/SHA256SUMS, then unsquashed onto the mounted target.

No overlay, no rsync: the image is the installed system, as Phase 3 built it.
A hash mismatch fails before any write.
"""
import hashlib, os


def image_path(ctx):
    return os.path.join(ctx.media, "maluos/images", ctx.plan["source"]["image"] + ".squashfs")


def listed_sum(ctx):
    name = "images/" + ctx.plan["source"]["image"] + ".squashfs"
    try:
        for line in open(os.path.join(ctx.media, "maluos/SHA256SUMS")):
            f = line.split()
            if len(f) == 2 and f[1].lstrip("*") == name:
                return f[0]
    except OSError:
        return None
    return None


def image_size(ctx):
    """The uncompressed size the ISO build recorded beside the image, or 0."""
    try:
        return int(open(os.path.join(ctx.media, "maluos/images", ctx.plan["source"]["image"] + ".size")).read().strip())
    except (OSError, ValueError):
        return 0


def variant(ctx):
    return "desktop" if "desktop" in ctx.plan["source"]["image"] else "server"


def check(ctx):
    errs = []
    img = image_path(ctx)
    if not os.path.exists(img):
        d = os.path.join(ctx.media, "maluos/images")
        have = sorted(f[:-9] for f in (os.listdir(d) if os.path.isdir(d) else []) if f.endswith(".squashfs"))
        return [f"no image {ctx.plan['source']['image']} on the medium (there: {', '.join(have) or 'none'})"]
    if ctx.plan["source"]["verify"] and not listed_sum(ctx):
        errs.append(f"{os.path.basename(img)} is not listed in /maluos/SHA256SUMS (set source.verify false to install anyway)")
    size = image_size(ctx)
    layout = ctx.state.get("storage")
    if size and layout and layout["root_bytes"] < size * 1.15 + layout["swap_bytes"] + (1 << 30):
        from ..plan import fmt_size
        errs.append(f"the root ({fmt_size(layout['root_bytes'])}) is too small for the image ({fmt_size(size)} unpacked) plus swap and room to work")
    ctx.state["image"] = {"path": img, "size": size, "variant": variant(ctx)}
    return errs


def summary(ctx):
    i = ctx.state.get("image") or {}
    return f"unpack: {os.path.basename(i.get('path') or image_path(ctx))} verified and unsquashed onto {ctx.target}"


def sha256_progress(ctx, path):
    h = hashlib.sha256()
    total = os.path.getsize(path) or 1
    done, last = 0, -1
    with open(path, "rb") as f:
        while True:
            b = f.read(8 << 20)
            if not b:
                break
            h.update(b); done += len(b)
            pct = done * 100 // total
            if pct // 10 != last // 10:
                last = pct
                ctx.emit("progress", f"verifying {os.path.basename(path)}", pct=pct)
    return h.hexdigest()


def apply(ctx):
    img = image_path(ctx)
    with ctx.substep("verify", "sha256 of the image against /maluos/SHA256SUMS"):
        if ctx.plan["source"]["verify"]:
            want = listed_sum(ctx)
            if ctx.dry_run:
                ctx.info(f"would hash {img} and compare with {want}")
            else:
                got = sha256_progress(ctx, img)
                if got != want:
                    raise RuntimeError(f"checksum mismatch: the medium's {os.path.basename(img)} is damaged ({got[:12]}… ≠ {want[:12]}…)")
                ctx.info(f"sha256 ok ({got[:16]}…)")
        else:
            ctx.info("source.verify is false: the image is not checked")
    with ctx.substep("unsquashfs", f"unpacking {os.path.basename(img)} onto {ctx.target}"):
        ctx.run(["unsquashfs", "-f", "-xattrs", "-no-progress", "-quiet", "-d", ctx.target, img], timeout=3600)
        ctx.run(["sync"], check=False)
    ctx.state["image"] = {"path": img, "size": image_size(ctx), "variant": variant(ctx)}
    ctx.journal.setdefault("state", {})["image"] = ctx.state["image"]
    ctx.save_journal()
