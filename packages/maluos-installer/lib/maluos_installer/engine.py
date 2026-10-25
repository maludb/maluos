"""The engine: runs the steps in order, keeps the journal, emits events, resumes.

Every action is an event {ts, step, sub, state: start|ok|fail|progress|info, pct, message}
written to the log and, with json=True, to stdout as one line each; without
json the console gets one readable line per event. Nothing here knows about a
screen: the screens of slice 3 consume the stream.

The journal (/run/maluos-install/journal.json) records each step and sub-step
with its state, start, end and error. `storage` and `unpack` are all-or-nothing:
a resume with either not completed is a fresh start. `configure` and
`bootloader` are sub-stepped and idempotent: a resume skips the sub-steps that
completed.
"""
import contextlib, hashlib, json, os, shlex, subprocess, sys, time, traceback

from . import plan as planmod

RUN_DIR = "/run/maluos-install"
STEP_ORDER = ("storage", "unpack", "configure", "bootloader", "finish")
ALL_OR_NOTHING = ("storage", "unpack")


class StepFailed(Exception):
    def __init__(self, step, sub, message):
        super().__init__(message)
        self.step, self.sub, self.message = step, sub, message


class CheckFailed(Exception):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


class Context:
    def __init__(self, plan, facts, media="/cdrom", target="/target", dry_run=False, json_out=False,
                 run_dir=RUN_DIR, console=None, sink=None):
        self.plan, self.facts = plan, facts
        self.media, self.target = media, target
        self.dry_run, self.json_out = dry_run, json_out
        self.run_dir = run_dir
        self.console = console            # an extra stream for the readable lines (the test's serial console)
        self.sink = sink                  # a callable taking each event instead of the console (the screens)
        self.state = {}                   # shared between steps: the layout, the devices, the UUIDs
        self.warnings = []
        self.started = time.time()
        self.step = self.sub = None
        self.chroot_mounted = []
        if not dry_run:
            os.makedirs(run_dir, exist_ok=True)
        self.log_path = os.path.join(run_dir, "install.log")
        self.journal_path = os.path.join(run_dir, "journal.json")
        self._log = None
        if not dry_run:
            self._log = open(self.log_path, "a")
        self.journal = self._load_journal()

    # --- events ----------------------------------------------------------------
    def emit(self, state, message, step=None, sub=None, pct=None):
        ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "step": step or self.step, "sub": sub or self.sub,
              "state": state, "pct": pct, "message": message}
        line = json.dumps(ev)
        if self._log:
            self._log.write(line + "\n"); self._log.flush()
        if self.sink:
            self.sink(ev)
            return
        if self.json_out:
            print(line, flush=True)
        else:
            where = ev["step"] or "-"
            if ev["sub"]:
                where += "/" + ev["sub"]
            mark = {"start": "..", "ok": "ok", "fail": "FAIL", "progress": f"{int(pct or 0):3d}%", "info": "  ", "warn": "warn"}.get(state, state)
            text = f"[{ev['ts'][11:19]}] {mark:4s} {where}: {message}"
            print(text, flush=True)
            if self.console:
                try:
                    self.console.write(text + "\n"); self.console.flush()
                except OSError:
                    pass

    def info(self, message, **k):
        self.emit("info", message, **k)

    def warn(self, message, **k):
        self.warnings.append(message)
        self.emit("warn", message, **k)

    def log_text(self, text):
        """Raw command output into the log only."""
        if self._log and text:
            self._log.write(text if text.endswith("\n") else text + "\n"); self._log.flush()

    def log_tail(self, n=40):
        try:
            lines = open(self.log_path).read().splitlines()
        except OSError:
            return []
        return lines[-n:]

    # --- the journal -------------------------------------------------------------
    def _load_journal(self):
        try:
            return json.load(open(self.journal_path))
        except (OSError, ValueError):
            return {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "plan_sha": self.plan_sha(), "steps": {}}

    def plan_sha(self):
        return hashlib.sha256(planmod.dump(planmod.redact(self.plan)).encode()).hexdigest()[:16]

    def save_journal(self):
        if self.dry_run:
            return
        tmp = self.journal_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.journal, f, indent=1)
        os.replace(tmp, self.journal_path)

    def reset_journal(self):
        self.journal = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "plan_sha": self.plan_sha(), "steps": {}}
        self.save_journal()

    def step_state(self, step):
        return self.journal["steps"].get(step, {}).get("state")

    def sub_state(self, step, sub):
        return self.journal["steps"].get(step, {}).get("subs", {}).get(sub, {}).get("state")

    def _mark(self, step, sub, state, error=None):
        s = self.journal["steps"].setdefault(step, {"state": None, "subs": {}})
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if sub:
            rec = s["subs"].setdefault(sub, {})
        else:
            rec = s
        rec["state"] = state
        if state == "start":
            rec["start"] = now; rec.pop("error", None)
        else:
            rec["end"] = now
        if error:
            rec["error"] = error
        self.save_journal()

    @contextlib.contextmanager
    def substep(self, name, message=None):
        """A journaled, resumable sub-step of the current step. Skipped when already ok."""
        if self.sub_state(self.step, name) == "ok":
            self.emit("info", f"{message or name}: done earlier, skipped", sub=name)
            yield False
            return
        self.sub = name
        self._mark(self.step, name, "start")
        self.emit("start", message or name)
        try:
            yield True
        except StepFailed:
            raise
        except Exception as e:
            self._mark(self.step, name, "fail", f"{e.__class__.__name__}: {e}")
            raise StepFailed(self.step, name, f"{e.__class__.__name__}: {e}")
        self._mark(self.step, name, "ok")
        self.emit("ok", message or name)
        self.sub = None

    # --- commands and files ---------------------------------------------------------
    def run(self, argv, input=None, check=True, chroot=False, secret=False, env=None, timeout=None, quiet=False):
        """Run a command (in the target's chroot with chroot=True). Returns stdout. Dry run: prints it."""
        shown = " ".join(shlex.quote(a) for a in argv)
        if chroot:
            shown = f"chroot {self.target} {shown}"
            argv = ["chroot", self.target] + list(argv)
        if self.dry_run:
            self.emit("info", f"would run: {shown}" + ("  (with input on stdin)" if input is not None else ""))
            return ""
        if not quiet:
            self.log_text(f"$ {shown}")
        e = dict(os.environ); e.update(DEBIAN_FRONTEND="noninteractive", LC_ALL="C.UTF-8"); e.update(env or {})
        try:
            r = subprocess.run(argv, input=input, capture_output=True, text=True, env=e, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{shown}: timed out after {timeout}s")
        except OSError as ex:
            raise RuntimeError(f"{shown}: {ex}")
        out = (r.stdout or "") + (r.stderr or "")
        if not secret:
            self.log_text(out)
        if check and r.returncode != 0:
            tail = "\n".join(out.strip().splitlines()[-6:])
            raise RuntimeError(f"{shown} failed (rc={r.returncode}):\n{tail}")
        return r.stdout or ""

    def write(self, path, content, mode=0o644, in_target=True):
        """Write a file (under the target by default). Dry run: describes it."""
        full = os.path.join(self.target, path.lstrip("/")) if in_target else path
        if self.dry_run:
            n = len(content.splitlines())
            self.emit("info", f"would write {full} ({n} line{'s' if n != 1 else ''}, mode {mode:o})")
            return
        os.makedirs(os.path.dirname(full), exist_ok=True)
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(full, mode)
        self.log_text(f"wrote {full}")

    def tpath(self, path):
        return os.path.join(self.target, path.lstrip("/"))

    def texists(self, path):
        return os.path.exists(self.tpath(path))

    # --- the chroot ------------------------------------------------------------------
    def mount_chroot(self):
        """Bind /dev, /dev/pts, /proc, /sys, /run and the medium into the target (and efivarfs on UEFI)."""
        if self.dry_run:
            self.emit("info", f"would bind /dev /dev/pts /proc /sys /run {self.media} into {self.target}")
            return
        binds = [("/dev", "dev"), ("/dev/pts", "dev/pts"), ("/proc", "proc"), ("/sys", "sys"), ("/run", "run")]
        if os.path.isdir(self.media):
            binds.append((self.media, "cdrom"))
        for src, rel in binds:
            dst = self.tpath(rel)
            os.makedirs(dst, exist_ok=True)
            if not os.path.ismount(dst):
                self.run(["mount", "--bind", src, dst], quiet=True)
                self.chroot_mounted.append(dst)
        if os.path.isdir("/sys/firmware/efi/efivars"):
            dst = self.tpath("sys/firmware/efi/efivars")
            if not os.path.ismount(dst):
                self.run(["mount", "-t", "efivarfs", "efivarfs", dst], check=False, quiet=True)
                self.chroot_mounted.append(dst)

    def umount_chroot(self):
        if self.dry_run:
            return
        for dst in reversed(self.chroot_mounted):
            subprocess.run(["umount", "-l", dst], capture_output=True)
        self.chroot_mounted = []


def load_steps():
    from .steps import storage, unpack, configure, bootloader, finish
    return {"storage": storage, "unpack": unpack, "configure": configure, "bootloader": bootloader, "finish": finish}


def check(ctx):
    """Every step's check, all of them, before anything is applied. Raises CheckFailed."""
    steps = load_steps()
    errors = []
    for name in STEP_ORDER:
        ctx.step, ctx.sub = name, "check"
        try:
            errs = steps[name].check(ctx) or []
        except Exception as e:
            errs = [f"{name}: check crashed: {e.__class__.__name__}: {e}"]
            ctx.log_text(traceback.format_exc())
        for e in errs:
            ctx.emit("fail", e)
        errors.extend(f"{name}: {e}" for e in errs)
    ctx.step = ctx.sub = None
    if errors:
        raise CheckFailed(errors)
    return [steps[n].summary(ctx) for n in STEP_ORDER]


def apply(ctx, resume=False):
    """Run the steps. Returns the finish step's action. Raises StepFailed."""
    steps = load_steps()
    if resume:
        bad = [s for s in ALL_OR_NOTHING if ctx.step_state(s) != "ok"]
        if bad:
            ctx.emit("info", f"resume: {', '.join(bad)} did not complete; starting again from the beginning", step="resume")
            ctx.reset_journal()
            resume = False
        else:
            ctx.emit("info", "resume: storage and unpack are done; continuing with the sub-steps left", step="resume")
            steps["storage"].ensure_mounted(ctx)
    for name in STEP_ORDER:
        ctx.step, ctx.sub = name, None
        if resume and ctx.step_state(name) == "ok" and name != "finish":
            ctx.emit("info", "done earlier, skipped")
            continue
        ctx._mark(name, None, "start")
        ctx.emit("start", steps[name].summary(ctx))
        t0 = time.time()
        try:
            steps[name].apply(ctx)
        except StepFailed as e:
            ctx._mark(name, None, "fail", e.message)
            ctx.emit("fail", e.message, sub=e.sub)
            raise
        except Exception as e:
            msg = f"{e.__class__.__name__}: {e}"
            ctx.log_text(traceback.format_exc())
            ctx._mark(name, ctx.sub, "fail", msg)
            if ctx.sub:
                ctx._mark(name, None, "fail", msg)
            ctx.emit("fail", msg)
            raise StepFailed(name, ctx.sub, msg)
        ctx._mark(name, None, "ok")
        ctx.emit("ok", f"{name} done in {int(time.time() - t0)}s")
    ctx.step = ctx.sub = None
    return ctx.plan["finish"]["action"]
