"""The telemetry report: one JSON document, version 1, shown before it goes, sent only when the plan says so.

Never in it: hostname, user names, IP or MAC addresses, serial numbers, disk
models beyond the bus, the enrolment address or code, the plan's text.
"""
import json, time, urllib.request, uuid

from . import VERSION


def release():
    rel, variant = "", ""
    try:
        for line in open("/etc/maluos-release"):
            if line.startswith("MALUOS_VERSION="):
                rel = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return rel or "unknown"


def _redact_tail(lines):
    out = []
    for l in lines:
        if any(k in l for k in ("chpasswd", "luksFormat", "cryptsetup open", "passphrase", "$6$", "code:")):
            out.append("<redacted line>")
        else:
            out.append(l[:300])
    return out


def document(ctx, outcome="ok", failure=None):
    """The report from the plan, the facts and the journal. Pure apart from the clock."""
    plan, facts = ctx.plan, ctx.facts
    layout = ctx.state.get("storage") or {}
    st = plan["storage"]
    disk_gb = (layout.get("disk_bytes") or 0) >> 30
    root_gb = (layout.get("root_bytes") or 0) >> 30
    swap_gb = round((layout.get("swap_bytes") or 0) / (1 << 30), 1)
    comps = sorted(set([plan["source"]["image"]] + list(plan["components"]["install"])))
    doc = {
        "v": 1,
        "install_id": ctx.state.setdefault("install_id", str(uuid.uuid4())),
        "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "outcome": outcome,
        "release": release(),
        "variant": (ctx.state.get("image") or {}).get("variant") or ("desktop" if "desktop" in plan["source"]["image"] else "server"),
        "installer": f"maluos-installer {VERSION}",
        "duration_s": int(time.time() - ctx.started),
        "unattended": bool(ctx.state.get("unattended", True)),
        "remote": bool(ctx.state.get("remote", False)),
        "components": comps,
        "layout": {"kind": st["layout"], "filesystem": st["filesystem"], "encrypt": bool(st["encrypt"]), "target": st.get("target", "disk"),
                   "disk_gb": disk_gb, "root_gb": root_gb, "swap_gb": swap_gb},
        "hardware": {
            "cpu": (facts.get("cpu") or {}).get("model") or "unknown",
            "cores": (facts.get("cpu") or {}).get("cores") or 0,
            "memory_mb": facts.get("memory_mb") or 0,
            "disks": [{"bus": d["bus"], "gb": d["size"] >> 30} for d in facts.get("disks") or [] if not d.get("medium")],
            "gpu": facts.get("gpu") or "none",
            "model": (facts.get("apple") or {}).get("model") or "",   # the Mac's model, else empty (the Apple T2 round)
            "firmware": facts.get("firmware") or "unknown",
            "secure_boot": facts.get("secure_boot") == "on",
            "virtual": facts.get("virtual") or "none",
        },
        "locale": {"language": plan["locale"]["language"].split(".")[0], "keyboard": plan["locale"]["keyboard"]["layout"],
                   "timezone": plan["locale"]["timezone"]},
        "failure": None,
    }
    if failure:
        doc["failure"] = {"step": failure.get("step"), "sub": failure.get("sub"), "error": (failure.get("error") or "")[:500],
                          "log_tail": _redact_tail(ctx.log_tail(40))}
    return doc


def send(ctx, doc, timeout=5):
    """POST once, five seconds, no retry. Returns (ok, note)."""
    url = ctx.plan["telemetry"]["url"]
    body = json.dumps(doc).encode()
    if ctx.dry_run:
        return True, f"would POST {len(body)} bytes to {url}"
    try:
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": doc["installer"]})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status in (200, 204), f"sent ({r.status})"
    except Exception as e:
        return False, f"not sent: {e.__class__.__name__}: {e}"
