"""finish: the evidence into the target, the telemetry report when asked, the mounts released, then the plan's action.

/var/log/maluos-install/ in the target gets install.log, plan.yaml (secrets
redacted) and journal.json. The medium is ejected by casper at reboot (the
`noeject` boot option keeps it); `finish.eject: false` adds nothing on top.
"""
import os, shutil, subprocess

from .. import plan as planmod
from .. import telemetry
from . import storage


def check(ctx):
    return []


def summary(ctx):
    f = ctx.plan["finish"]
    return f"finish: the log, the redacted plan and the journal into {f['log']}; telemetry {'sent' if ctx.plan['telemetry']['send'] else 'not sent'}; then {f['action']}"


def copy_evidence(ctx):
    d = ctx.tpath(ctx.plan["finish"]["log"])
    if ctx.dry_run:
        ctx.info(f"would copy install.log, plan.yaml (redacted) and journal.json into {d}")
        return
    os.makedirs(d, mode=0o750, exist_ok=True)
    with open(os.path.join(d, "plan.yaml"), "w") as f:
        f.write(planmod.dump(planmod.redact(ctx.plan)))
    ctx.save_journal()
    for name in ("journal.json", "install.log"):
        src = os.path.join(ctx.run_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(d, name))
    os.chmod(d, 0o750)
    for name in os.listdir(d):
        os.chmod(os.path.join(d, name), 0o640)


def apply(ctx):
    action = ctx.plan["finish"]["action"]
    with ctx.substep("evidence", f"the log, the plan and the journal into {ctx.plan['finish']['log']}") as go:
        if go:
            copy_evidence(ctx)
    if ctx.plan["telemetry"]["send"]:
        with ctx.substep("telemetry", f"one report to {ctx.plan['telemetry']['url']}") as go:
            if go:
                doc = telemetry.document(ctx, outcome="ok")
                ok, note = telemetry.send(ctx, doc)
                ctx.info(f"telemetry: {note}")
    else:
        ctx.info("telemetry: not sent (telemetry.send is false)")
    if action == "shell":
        ctx.info(f"finish.action shell: the target stays mounted at {ctx.target}")
    else:
        with ctx.substep("release", "unmounting the target, closing LUKS, deactivating the VG") as go:
            if go:
                ctx.run(["sync"], check=False)
                storage.release(ctx)
    ctx.emit("ok", f"maluos-install: finished ({action})", sub="done")
    return action


def do_action(ctx, action):
    """What the plan says, after the engine has returned (so the console unit can print the marker)."""
    if ctx.dry_run:
        ctx.info(f"would now {action}")
        return
    if action == "reboot":
        subprocess.run(["systemctl", "reboot"])
    elif action == "poweroff":
        subprocess.run(["systemctl", "poweroff"])
