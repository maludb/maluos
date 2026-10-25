# maluos-system-monitor: GNOME System Monitor with the MaluOS tabs

Upstream: gnome-system-monitor 49.1 (https://download.gnome.org/sources/gnome-system-monitor/49/),
packaging from Ubuntu 26.04's 49.1-2 (debian/copyright, debian/rules, the manual page), both
unmodified except where this file says. Decided 2026-10-25 (docs/phase13-shared-gpus.md,
"Where the tabs go"): the tabs are logic-free so the patch stays small, every number is computed
in Python outside this tree (maluos_gpu.py, the gateway, the session service) and a GNOME
rebase touches layout only.

## The patch surface (everything MaluOS added or changed)

| File | Change |
|---|---|
| `src/maluos-gpus.cpp`, `src/maluos-gpus.h` | new: the GPUs view (GsmMaluosGpusView), a GtkWidget that polls `com.maluos.Session` GetState every 2 s while its tab is current, renders this computer's GPUs, the sharing switch, the loaded models and the queue, and the office; the switch runs `pkexec maluctl gateway share on|off`; `--maluos-self-test` |
| `data/interface.ui` | the `gpus` AdwViewStackPage after File Systems, hidden until the session answers |
| `data/icons/public/hicolor/symbolic/apps/maluos-gpus-symbolic.svg`, `src/gsm.gresource.xml.in` | the tab icon |
| `src/interface.cpp` | `g_type_ensure` before the builder, the view fetched from the builder, the page's `visible` bound to the view's `available`, freeze/thaw in `update_page_activities` |
| `src/org.gnome.gnome-system-monitor.gschema.xml.in` | `gpus` added to the `current-tab` choices |
| `src/application.h`, `src/application.cpp` | the `maluos_gpus` member, `--show-gpus-tab` / `--maluos-self-test` in `on_command_line`, Alt+4 |
| `src/argv.h`, `src/argv.cpp` | the two options |
| `meson.build`, `src/meson.build` | json-glib-1.0 and the two sources |
| `po/POTFILES.in` | the new source (its strings are untranslated for now) |
| `debian/` | source and binary renamed to maluos-system-monitor (Provides/Conflicts/Replaces gnome-system-monitor), `3.0 (native)`, libjson-glib-dev, this changelog |

Every hunk in an upstream file is marked `MaluOS` in a comment.

## Rebasing on a new upstream

1. Unpack the new tarball over this directory (`tar --strip-components=1`), then `git diff` shows
   upstream's changes; ours are the rows above.
2. Re-apply the hunks in the table if the unpack overwrote them (interface.ui, interface.cpp,
   application.*, argv.*, meson, POTFILES, the gresource list); the new files survive.
3. Take Ubuntu's new debian/copyright, rules and manual page; keep our control, changelog, format.
4. Build (`dpkg-buildpackage -us -uc -b`), run tests/system-monitor-local-test.sh, bump the
   changelog to `<upstream>+maluos.1`.

## The self-test

`gnome-system-monitor --maluos-self-test` builds the window, selects the GPUs tab, reads the
session state once and prints `self-test ok: GPUs: session reachable, N gpus, chassis X, rule R,
share on|off, gateway ok|absent`, exit 0; when a call is refused (no service: ServiceUnknown) or
nothing has answered within 60 s it prints `self-test FAIL: ... did not answer: <error>` and exits 1.
A call still in flight is always waited for (its own 30 s D-Bus timeout ends it), because on a slow
machine the window's first paint can hold the main loop past any deadline. tests/system-monitor-local-test.sh runs it under Xvfb against
a fake session service; the image boot test runs it on the real session.
