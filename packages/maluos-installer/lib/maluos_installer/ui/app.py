"""The wizard: the frame with the title and the footer, the keys, the overlays, the engine in a thread.

    app = Installer(media, facts, variant, seed=plan_or_None, save_plan=None, no_hardware=False)
    result = app.run()        # ("installed", action) | ("failed", message) | ("saved", path) | ("shell", None) | ("quit", None)
"""
import json, os, threading, time, traceback

import urwid

from .. import plan as planmod, engine, telemetry
from ..steps import finish as finish_step, storage as storage_step
from . import screens as S

PALETTE = [
    ("header", "white,bold", "dark blue"), ("footer", "black", "light gray"), ("title", "bold", ""),
    ("label", "bold", ""), ("dim", "dark gray", ""), ("error", "light red,bold", ""), ("ok", "dark green", ""),
    ("button", "", ""), ("focus", "black", "light gray"), ("bar", "white", "dark blue"), ("bar.done", "white", "dark green"),
]
FOOTER = " Enter: continue   Esc: back   Space: select   Tab/arrows: move   F10: shell "


class Installer:
    def __init__(self, media, facts, variant, seed=None, save_plan=None, no_hardware=False, run_dir=engine.RUN_DIR, target="/target"):
        self.media, self.facts, self.variant = media, facts, variant
        self.save_plan, self.no_hardware, self.run_dir, self.target = save_plan, no_hardware, run_dir, target
        self.plan = self._seed(seed)
        self.index = 0
        self.screen = None
        self.result = ("quit", None)
        self.body = urwid.Filler(urwid.Text(""))
        self.frame = urwid.Frame(self.body, header=urwid.AttrMap(urwid.Text(""), "header"),
                                 footer=urwid.AttrMap(urwid.Text(FOOTER), "footer"))
        self.loop = urwid.MainLoop(self.frame, PALETTE, unhandled_input=self.unhandled, handle_mouse=False)
        self.overlay_on = False
        self.events = []
        self.ctx = None
        self.resume = False

    @staticmethod
    def _seed(seed):
        if not seed:
            return {"version": 1}
        raw = {k: v for k, v in seed.items() if not k.startswith("_")}
        raw["version"] = 1
        return raw

    # --- navigation ---------------------------------------------------------------------------
    def show(self, index):
        self.index = index
        self.screen = S.SCREENS[index](self)
        items = self.screen.build()
        walker = urwid.SimpleFocusListWalker([w if isinstance(w, (urwid.Text, urwid.Divider, urwid.LineBox)) or not getattr(w, "selectable", lambda: False)()
                                              else urwid.AttrMap(w, None, focus_map="focus") for w in items])
        self.listbox = urwid.ListBox(walker)
        # focus the first selectable item
        for i, w in enumerate(walker):
            if w.selectable():
                self.listbox.set_focus(i); break
        self.frame.body = urwid.Padding(self.listbox, left=2, right=2)
        self.frame.header.original_widget.set_text(f" MaluOS installer - {self.screen.name} ({index + 1}/{len(S.SCREENS)}) ")
        self.frame.footer.original_widget.set_text(FOOTER)

    def next(self):
        errs = self.screen.validate()
        if errs:
            self.message("Please check:", errs); return
        if isinstance(self.screen, S.Storage):
            prompt, name = self.screen.confirm_text()
            self.ask(prompt, "", lambda typed: self._confirm_disk(typed, name)); return
        self._advance()

    def _confirm_disk(self, typed, name):
        if typed.strip() != name:
            self.message("Not erased", [f"You typed {typed.strip()!r}; the disk's name is {name!r}. Nothing was changed."]); return
        self._advance()

    def _advance(self):
        try:
            self.screen.apply()
        except Exception as e:
            self.message("That did not work:", [f"{e.__class__.__name__}: {e}"]); return
        if self.index + 1 < len(S.SCREENS):
            self.show(self.index + 1)

    def back(self):
        if self.index > 0:
            try:
                self.screen.apply() if not isinstance(self.screen, (S.Summary, S.Storage, S.Identity)) else None
            except Exception:
                pass
            self.show(self.index - 1)

    def unhandled(self, key):
        if self.overlay_on:
            if key == "esc":
                self.close_overlay()
            return
        if key == "enter":
            if isinstance(self.screen, S.Summary):
                return
            self.next()
        elif key == "esc":
            self.back()
        elif key == "f10":
            self.result = ("shell", None); raise urwid.ExitMainLoop()
        elif key == "tab":
            self._move("down")
        elif key == "shift tab":
            self._move("up")

    def _move(self, direction):
        try:
            self.listbox.keypress(self.loop.screen_size or (80, 24), direction)
        except Exception:
            pass

    # --- overlays -------------------------------------------------------------------------------
    def _overlay(self, widget, width=70, height=None):
        box = urwid.LineBox(widget)
        self.saved_widget = self.loop.widget
        self.loop.widget = urwid.Overlay(box, self.frame, align="center", width=("relative", width), valign="middle",
                                         height=height or "pack")
        self.overlay_on = True

    def close_overlay(self):
        self.loop.widget = self.frame
        self.overlay_on = False

    def message(self, title, lines, on_ok=None):
        ok = urwid.Button("OK", on_press=lambda b: (self.close_overlay(), on_ok() if on_ok else None))
        body = urwid.Pile([urwid.Text(("title", title))] + [urwid.Text(("error", f" - {l}")) for l in lines] +
                          [urwid.Divider(), urwid.AttrMap(ok, None, "focus")])
        self._overlay(body)

    def ask(self, prompt, default, on_answer):
        e = urwid.Edit("> ", default)
        def done(b=None):
            self.close_overlay(); on_answer(e.edit_text)
        ok = urwid.Button("OK", on_press=done)
        cancel = urwid.Button("Cancel", on_press=lambda b: self.close_overlay())
        class EnterEdit(urwid.Edit):
            def keypress(self_, size, key):
                if key == "enter":
                    done(); return None
                return super().keypress(size, key)
        e = EnterEdit("> ", default)
        pile = urwid.Pile([urwid.Text(prompt), urwid.Divider(), e, urwid.Divider(),
                           urwid.Columns([(8, urwid.AttrMap(ok, None, "focus")), (12, urwid.AttrMap(cancel, None, "focus"))], dividechars=2)])
        pile.focus_position = 2
        self._overlay(pile)

    # --- the plan ---------------------------------------------------------------------------------
    def filled_plan(self):
        return planmod.fill_defaults({**self.plan, "version": 1}, self.variant)

    def telemetry_preview(self):
        try:
            filled = self.filled_plan()
            ctx = engine.Context(filled, self.facts, media=self.media, dry_run=True, run_dir=self.run_dir)
            try:
                storage_step.check(ctx)
            except Exception:
                pass
            ctx.state["unattended"] = False
            return telemetry.document(ctx, outcome="ok")
        except Exception as e:
            return {"error": f"the report cannot be built yet: {e}"}

    def ask_save(self):
        default = self.save_plan or os.path.join(self.run_dir, "plan.yaml")
        self.ask("Write the plan (with its secrets) to:", default, self._save_to)

    def _save_to(self, path):
        try:
            self.write_plan(path)
        except Exception as e:
            self.message("Not saved", [f"{e.__class__.__name__}: {e}"]); return
        self.message("Saved", [f"the plan is at {path}"])

    def write_plan(self, path):
        filled = self.filled_plan()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("# Install plan written by the MaluOS installer's screens.\n" + planmod.dump(filled))
        return path

    # --- the install --------------------------------------------------------------------------------
    def start_install(self):
        if self.save_plan:
            try:
                self.write_plan(self.save_plan)
            except Exception as e:
                self.message("Not saved", [str(e)]); return
            self.result = ("saved", self.save_plan); raise urwid.ExitMainLoop()
        try:
            filled = self.filled_plan()
            planmod.resolve_refs(filled, self.media)
        except planmod.PlanError as e:
            self.message("The plan cannot run:", str(e).splitlines()); return
        if not self.no_hardware:
            os.makedirs(self.run_dir, exist_ok=True)
            self.write_plan(os.path.join(self.run_dir, "plan.yaml"))
        self.pipe = self.loop.watch_pipe(self._on_pipe)
        self.ctx = engine.Context(filled, self.facts, media=self.media, target=self.target, dry_run=self.no_hardware,
                                  run_dir=self.run_dir, sink=self._sink)
        self.ctx.state["unattended"] = False
        self.ctx.state["remote"] = bool(os.environ.get("SSH_CONNECTION"))
        self._progress_screen()
        threading.Thread(target=self._engine_thread, daemon=True).start()

    def _sink(self, ev):
        try:
            os.write(self.pipe, (json.dumps(ev) + "\n").encode())
        except OSError:
            pass

    def _engine_thread(self):
        try:
            engine.check(self.ctx)
            action = engine.apply(self.ctx, resume=self.resume)
            self._sink({"state": "done", "ok": True, "action": action, "message": f"maluos-install: finished ({action})"})
        except engine.CheckFailed as e:
            self._sink({"state": "done", "ok": False, "step": "check", "message": "the plan cannot be applied to this machine:\n" + "\n".join(e.errors)})
        except engine.StepFailed as e:
            self._sink({"state": "done", "ok": False, "step": f"{e.step}/{e.sub}" if e.sub else e.step, "message": e.message})
        except Exception as e:
            self.ctx.log_text(traceback.format_exc())
            self._sink({"state": "done", "ok": False, "step": "engine", "message": f"{e.__class__.__name__}: {e}"})

    def _progress_screen(self):
        self.ev_walker = urwid.SimpleFocusListWalker([])
        self.ev_list = urwid.ListBox(self.ev_walker)
        self.bar = urwid.ProgressBar("bar", "bar.done", 0, 100)
        self.status = urwid.Text(("title", "Starting…"))
        pile = urwid.Pile([("pack", self.status), ("pack", self.bar), ("pack", urwid.Divider()), self.ev_list])
        self.frame.body = urwid.Padding(pile, left=2, right=2)
        self.frame.header.original_widget.set_text(" MaluOS installer - Installing ")
        self.frame.footer.original_widget.set_text(" The install is running; this screen shows the engine's events. ")
        self.screen = None
        self._buf = ""

    STEP_BASE = {"storage": 0, "unpack": 10, "configure": 60, "bootloader": 85, "finish": 95}

    def _on_pipe(self, data):
        self._buf += data.decode("utf-8", "replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            self._event(ev)

    def _event(self, ev):
        if ev.get("state") == "done":
            self._done(ev); return
        where = ev.get("step") or ""
        if ev.get("sub"):
            where += "/" + ev["sub"]
        mark = {"start": "..", "ok": "ok", "fail": "FAIL", "progress": f"{int(ev.get('pct') or 0)}%", "info": "  ", "warn": "warn"}.get(ev.get("state"), "")
        attr = "error" if ev.get("state") == "fail" else ("ok" if ev.get("state") == "ok" else None)
        line = f"[{(ev.get('ts') or '')[11:19]}] {mark:4s} {where}: {ev.get('message', '')}"
        self.ev_walker.append(urwid.Text((attr, line)) if attr else urwid.Text(line))
        if len(self.ev_walker) > 300:
            del self.ev_walker[0]
        self.ev_list.set_focus(len(self.ev_walker) - 1)
        step = ev.get("step")
        if step in self.STEP_BASE and ev.get("state") in ("start", "ok", "progress"):
            base = self.STEP_BASE[step]
            span = {"storage": 10, "unpack": 50, "configure": 25, "bootloader": 10, "finish": 5}[step]
            pct = base + (span if ev.get("state") == "ok" and not ev.get("sub") else int(span * (ev.get("pct") or 0) / 100) if ev.get("state") == "progress" else 0)
            self.bar.set_completion(max(self.bar.current, min(pct, 100)))
            self.status.set_text(("title", f"{step}: {ev.get('message', '')}"[:200]))

    def _done(self, ev):
        self.bar.set_completion(100 if ev["ok"] else self.bar.current)
        if ev["ok"]:
            self.result = ("installed", ev["action"])
            self.status.set_text(("ok", "Installation complete."))
            b = urwid.Button(f"Press Enter to {ev['action']}" if ev["action"] in ("reboot", "poweroff") else "Press Enter to finish",
                             on_press=lambda b: self._exit())
            self.frame.footer.original_widget.set_text(" Installed. Enter: continue   F10: shell ")
        else:
            self.result = ("failed", ev.get("message"))
            self.status.set_text(("error", f"Failed at {ev.get('step')}: {str(ev.get('message', '')).splitlines()[0][:160]}"))
            for l in (self.ctx.log_tail(15) if self.ctx else []):
                self.ev_walker.append(urwid.Text(("dim", l[:200])))
            b = urwid.Columns([(26, urwid.Button("Retry (resume the install)", on_press=lambda b: self._retry())),
                               (18, urwid.Button("Open a shell", on_press=lambda b: self._exit("shell")))], dividechars=2)
            self.frame.footer.original_widget.set_text(" The install failed. The log is in /run/maluos-install/install.log. ")
        pile = self.frame.body.original_widget
        pile.contents.insert(2, (urwid.AttrMap(b, None, "focus") if not isinstance(b, urwid.Columns) else b, pile.options("pack")))
        pile.focus_position = 2

    def _retry(self):
        self.resume = True
        self._progress_screen()
        threading.Thread(target=self._engine_thread, daemon=True).start()

    def _exit(self, what=None):
        if what == "shell":
            self.result = ("shell", None)
        raise urwid.ExitMainLoop()

    # --- run ----------------------------------------------------------------------------------------
    def run(self):
        self.show(0)
        try:
            self.loop.run()
        finally:
            try:
                self.loop.screen.stop()
            except Exception:
                pass
        return self.result
