# maluos-system-monitor: GNOME System Monitor with the MaluOS tabs

Upstream: gnome-system-monitor 49.1 (https://download.gnome.org/sources/gnome-system-monitor/49/),
packaging from Ubuntu 26.04's 49.1-2 (debian/copyright, debian/rules, the manual page), both
unmodified except where this file says. Decided 2026-10-25 (docs/phase13-shared-gpus.md,
"Where the tabs go"): the tabs are logic-free so the patch stays small, every number is computed
in Python outside this tree (maluos_gpu.py, the gateway, the session service) and a GNOME
rebase touches layout only.

## The patch surface (everything MaluOS added or changed)

G1 added the GPUs tab (49.1+maluos.1), G5 the MaluOS Network and Queue tabs and the shared session client (49.1+maluos.3); Phase 13 slice 1 filled the Network tab's Estate group from office.estate (49.1+maluos.4).

| File | Change |
|---|---|
| `src/maluos-session.cpp`, `src/maluos-session.h` | new: the one session client of the process (GsmMaluosSession), which talks to `com.maluos.Session`: GetState every 2 s while a tab that draws the state is current, NodeQueue every 2 s while the Queue tab is; each answer is a signal the tabs draw from; `available` (the service answered once: the tabs are shown) and `stale` (a later call failed: a banner); the JSON helpers; `gsm_maluos_run` for the tabs' maluctl actions; `--maluos-self-test` |
| `src/maluos-gpus.cpp`, `src/maluos-gpus.h` | new: the GPUs view (GsmMaluosGpusView): this computer's GPUs, the sharing switch (`pkexec maluctl gateway share on|off`), the loaded models and the queue, and the office |
| `src/maluos-network.cpp`, `src/maluos-network.h` | new: the MaluOS Network view (GsmMaluosNetworkView): this node as the node API reports it (name, id, the listener, sharing, the manager, the lanes, the keys issued), the nodes paired by hand, the office; from the state's `node` section (maluos-desktop-session 0.8.0) |
| `src/maluos-queue.cpp`, `src/maluos-queue.h` | new: the Queue view (GsmMaluosQueueView): every lane with Pause/Resume, every queued or running call with Cancel and its class as a drop-down, from NodeQueue; the actions run `maluctl gateway node pause|resume|cancel|priority`; "Open in Sovereign LLM Manager" opens the office |
| `data/interface.ui` | the `gpus`, `network` and `queue` AdwViewStackPages after File Systems, hidden until the session answers |
| `data/icons/public/hicolor/symbolic/apps/maluos-gpus-symbolic.svg`, `src/gsm.gresource.xml.in` | the GPUs tab icon (the other two use Adwaita's network-workgroup and view-list-ordered) |
| `src/interface.cpp` | `g_type_ensure` for the three views before the builder, the views fetched from the builder, the pages' `visible` bound to the session client's `available`, freeze/thaw of each view in `update_page_activities` |
| `src/org.gnome.gnome-system-monitor.gschema.xml.in` | `gpus`, `network`, `queue` added to the `current-tab` choices |
| `src/application.h`, `src/application.cpp` | the three view members, `--show-gpus-tab` / `--show-network-tab` / `--show-queue-tab` / `--maluos-self-test` in `on_command_line`, Alt+4, Alt+5, Alt+6 |
| `src/argv.h`, `src/argv.cpp` | the four options |
| `meson.build`, `src/meson.build` | json-glib-1.0 and the four sources |
| `po/POTFILES.in` | the new sources (their strings are untranslated for now) |
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
session state and the queue once (GetState, NodeQueue) and prints one line from the three tabs'
summaries: `self-test ok: GPUs: session reachable, N gpus, chassis X, rule R, share on|off, gateway
ok|absent; Network: node NAME, L lanes, P paired, K keys, exposed|socket only; Queue: N jobs (R running,
Q queued) in L lanes`, exit 0 (the Network and Queue parts say `not an operator` / `forbidden (not an
operator)` for a user who is not an operator of the gateway, `no gateway` without one, and name a
session service too old for NodeQueue). When a call is refused (no service: ServiceUnknown) or
nothing has answered within 60 s it prints `self-test FAIL: the MaluOS session service did not answer:
<error>` and exits 1. A call still in flight is always waited for (its own 30 s D-Bus timeout ends
it), because on a slow machine the window's first paint can hold the main loop past any deadline.
tests/system-monitor-local-test.sh runs it under Xvfb against a fake session service (two GPUs with a
node and a queue; no GPU; not an operator; no session); the image boot test runs it on the real session.
