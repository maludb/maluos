# Phase 11 slice 3: the screens

Specified and built 2026-10-24 from docs/phase11-installer.md (decisions
2, 3 and 8; the owner's answers 1, 3 and 4), docs/install-plan.md (the
plan the screens build) and slice 2 (docs/phase11-slice2-engine.md, the
engine that runs it). The status at the end says what the build settled.

## What the slice delivers

A medium booted without a plan now shows the MaluOS installer's screens
instead of a shell: language and time zone; keyboard; network; storage
with the guided layouts, LUKS and a typed confirmation; identity with the
password's strength and SSH keys by paste or GitHub login; components
from the medium's catalogue; first boot with the tenant, the administrator
and an enrolment; "Help improve MaluOS" with the report shown; the summary
with "Save the plan"; progress with the engine's events; done. Every
screen writes to one plan, the plan of docs/install-plan.md; the summary
screen runs the same engine the unattended path runs. The screens work on
the console, on a serial line and over SSH, and a keystroke driver on the
serial console tests them.

```
sudo maluos-install                       the screens (what the console unit runs without maluos.plan=)
sudo maluos-install --screens --plan P    the screens prefilled from a plan (an unattended plan reviewed before it runs)
maluos-install --screens --no-hardware --media DIR --save-plan OUT    the screens without a machine: the pty test
```

## Decisions

1. **urwid, one wizard, one plan.** `maluos_installer/ui/` holds
   `app.py` (the frame, the title, the footer with the keys, Back and
   Continue, the overlays) and `screens.py` (one class per screen with
   `build()`, `validate()` returning the errors to show, and `apply()`
   writing its section of the plan). The plan is a plain mapping of the
   contract's keys; `plan.fill_defaults()` and `plan.semantic_errors()`
   validate it on every Continue, so the screens cannot build a plan the
   engine refuses. The variant's defaults (the server's SSH on, the
   desktop's cloud-init off) come from the medium as in slice 2.
2. **The keys are the same on every screen.** Enter continues (on a
   button it presses the button; in a multi-line field it inserts a
   line), Esc goes back, Space selects, Tab and the arrows move, F10
   quits to a shell. The footer says so. Every screen's title line is
   `MaluOS installer - NAME (n/9)` (ASCII, so a serial console without UTF-8 shows it), which the keystroke driver waits for.
3. **Storage asks twice.** The disks are listed with path, size, model
   and bus (the medium left out); the layout, the filesystem, the root
   size, the swap and the LUKS switch with its passphrase typed twice
   follow the plan's keys. Continue shows what will be erased and asks
   for the disk's short name typed in full (`vda`, `nvme0n1`) before the
   plan gets `erase: true`.
4. **The screens hash.** The password goes into the plan as a SHA-512
   crypt hash made with `openssl passwd -6`; the strength shown is a
   small heuristic (length and character classes), not a rule. `github:
   NAME` in the SSH keys becomes `url:https://github.com/NAME.keys`,
   which the engine resolves once the network is up.
5. **Telemetry is shown before it is chosen.** The "Help improve MaluOS"
   screen builds the document of slice 2 from the plan so far and the
   machine's facts and shows it in a scrolling box above Send (the
   default, the owner's answer 4) and Don't send.
6. **Summary, then the engine in a thread.** The summary shows the plan
   as the engine understands it (secrets redacted) with Install, Save the
   plan and Back. Save writes the plan, unredacted, to a path the person
   types (a mounted USB stick's path, or `/run/maluos-install/plan.yaml`
   by default) for the next machine. Install runs `engine.check` and
   `engine.apply` in a thread; the events reach the progress screen
   through a pipe the main loop watches, so the UI never knows about a
   step. On success the done screen offers Reboot; on failure it shows
   the step, the message and the log's tail with Retry (a resume) and
   Shell.
7. **The console unit runs the screens.** Without `maluos.plan=` and
   without `/maluos/plan/default.yaml`, `maluos-install` on tty1 shows
   the screens; a serial console or an SSH session runs `sudo
   maluos-install` for the same screens. `maluos.test=1` without a plan
   keeps slice 1's medium check, so tests/live-iso-boot-test.sh is
   unchanged. Quit to a shell leaves a root shell on the console as
   slice 1 did.
8. **The test drives keystrokes, twice.** `tests/lib/screens_driver.py`
   is an expect-style driver: it strips the terminal's escape sequences
   from what it reads, waits for a screen's title, sends the keys for
   that screen, and knows the answers that reproduce the medium's
   unattended plan (login maluos, the test key, lvm, ext4). It runs in
   two places: `tests/install-screens-test.py` drives the screens in a
   pty on the build host with `--no-hardware` and a staged medium and
   compares the saved plan with the unattended plan (the packages
   workflow); `tests/live-install-test.sh --screens` drives them on the
   QEMU serial console through the autologin shell and then boots and
   verifies the disk as slice 2's rounds do, reading the redacted plan
   the engine left in /var/log/maluos-install/.

## Status (2026-10-24)

Built the same day as slice 2, in one round. What the build settled against
the decisions above:

| Item | Where | Notes |
|---|---|---|
| The wizard | packages/maluos-installer/lib/maluos_installer/ui/{app,screens}.py, maluos-installer 0.2.0 | As decisions 1 and 2. urwid 3.0.4: radio buttons keep their value as an attribute (the library passes `user_data` to signal handlers and does not store it); radio buttons and check boxes let Enter through so it means Continue on them; the ListBox of each screen gets the focus on its first selectable item; Tab and Shift+Tab move like the arrows. The titles are ASCII (`MaluOS installer - Storage (4/9)`) so a serial console without UTF-8 shows them; the footer fits 80 columns. |
| Storage | screens.py Storage | Decision 3: the layout computed with the engine's own `compute_layout` is shown in the confirmation overlay with what will be erased; the overlay's Edit takes Enter as OK, and a wrong name changes nothing. |
| Identity | screens.py Identity | Decision 4: `openssl passwd -6` (openssl is in the live image); `github:NAME`; the strength shown as the password is typed (a `change` signal). A plan given with `--plan` keeps its hash when nothing is typed. |
| Telemetry, summary, install | screens.py Telemetry and Summary, app.py | Decisions 5 and 6: the document from `telemetry.document` on a dry-run context with the storage check run for the layout; the summary shows the redacted plan under Install, Save the plan… and Back; the engine runs in a thread and reports through `MainLoop.watch_pipe`; the progress bar maps the five steps to 10/50/25/10/5 percent. |
| The console unit | bin/maluos-install | Decision 7: no plan means the screens, after a three-second pause for the network; `maluos.test=1` without a plan keeps the medium check (slice 1's test is unchanged); the shell on Quit or on a failure keeps the unit alive. |
| The driver and the tests | tests/lib/screens_driver.py, tests/install-screens-test.py, tests/live-install-test.sh --screens | Decision 8. The pty test (in the packages workflow, with python3-urwid and openssl in the container) answers the nine screens in about four seconds and the saved plan equals the medium's unattended plan section by section, the password verified against its salt; the only field the screens do not ask is `bootloader.cmdline`, so the comparison takes the defaults there. The serial round uses the `--test-ssh` medium (the serial entry default, the autologin shell) and `--no-change` for the forced password change, which sshd would refuse a non-interactive verification over. |

| Round (2026-10-24, TCG on the dev VM) | Result |
|---|---|
| the pty test | PASS: the nine screens driven, the plan equal to the unattended plan, the hash verified |
| server BIOS, the screens on the serial console | PASS, 45 ok / 0 FAIL on the re-verification: the driver started `sudo maluos-install` from the autologin shell, answered the nine screens with the typed disk confirmation, pressed Install; the install finished in about ten minutes under the progress screen and Enter on the done screen rebooted; the disk booted, first boot provisioned, and the plan the engine left in /var/log/maluos-install/ has the answers typed. The one check that failed looked for the unattended plan's serial console on the kernel command line, which the screens do not ask for (no bootloader screen); the check now expects the defaults in the screens round. |

The screens ask nothing about the bootloader, so an install from the screens
gets grub's defaults (no serial console, timeout 3 on the server); the
unattended plan adds `console=ttyS0` for headless servers. A bootloader
question, or an "advanced" page, is a later item if asked for.

