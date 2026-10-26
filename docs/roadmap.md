# MaluOS roadmap: the next steps

A working plan of what comes next, in the order it is scheduled today.
Each row is one task; move rows between sections to re-prioritise. The
authoritative phase table is docs/PLAN.md; the detail of a slice lives in
its phase document. Dates are UTC. Written 2026-10-23 12:00 UTC.

Status words: `done`, `running` (a build or test is in flight), `ready`
(coded, waiting on a build or a test), `planned` (written up, not
started), `idea` (not written up), `blocked` (needs a decision or a
thing outside this repo). Effort is a rough size for one person with the
tooling as it is: S under half a day, M a day, L several days.

## Where we are

| | |
|---|---|
| Latest release | 26.04.20261024, shipped 2026-10-24 00:37 UTC with Phase 12 slices 7 and 8; 26.04.20261025 (slice 9) built and boot-tested 2026-10-24, release after 00:00 UTC |
| Phase 12 (desktop) | slices 1 to 8 released (26.04.20261024); slice 9 built and boot-tested 2026-10-24 (desktop UEFI 252 ok, server UEFI 140 ok), on the share for the 26.04.20261025 release |
| Phase 13 (estate) | planned 2026-10-23, nothing built; the Agents app's task interface (slice 8) is its first protocol |
| Phase 11 (installer) | proposed only |
| Phases 7 and 9 | partly done; the rest waits (components catalogue, editions) |
| Dev host | Proxmox VM 4050, 16 GB cap with an 8 GB balloon floor since 2026-10-23; the host OOM-killed it five times before that |

## A. Today and tomorrow: the 26.04.20261024 release

Freeze at 22:00 UTC; release after 00:00 UTC. Everything below A6 is
optional filler for the remaining hours and goes in only if the step
before it is green by about 20:00 UTC.

| # | Task | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| A1 | Slice 8 desktop chain: publish, rootfs, qcow2, UEFI boot test | done 12:29, 230 ok / 0 FAIL | 1.5 h wall | packages built 11:35 | log build/logs/chain-slice8.log; the WebKit window built and reported ready on the first run |
| A2 | Fix what A1 finds; rebuild only what the fix touches | done, nothing to fix | S | A1 | |
| A3 | Commit and push slice 8 | ready | S | A2 | CI then boot-tests the server image with maluos-agent 0.3.0 |
| A4 | Server set: rootfs, qcow2, ISO, iso-check, UEFI boot test, share (BIOS is CI's) | done 13:30, 138 ok / 0 FAIL, share updated | 2 h wall | A3 | the server images on the share are still the slice 6 set; maluos-firstboot 0.1.8 and maluos-agent 0.3.0 apply to servers |
| A5 | Desktop ISO rebuilt with slice 8 and A7, iso-check, share | done 14:35 (sha 1a215c…) | S | A2 | |
| A6 | Release prep: docs/release.md row drafted, download page text ready, docs/PLAN.md and phase12 status rows final | done 14:40 (the commit id goes in at the tag) | S | A4, A5 | docs/install-plan.md written for Phase 11 slice 2 meanwhile |
| A7 | Filler: the session refreshes the MaluApps catalogue on each heartbeat (slice 7 leftover) | done: maluos-desktop-session 0.6.1, desktop UEFI 231 ok / 0 FAIL 14:31 | S | A3 | |
| A8 | Filler: remove packages/maluos-meta/debian/docs/claude-log/ from the repo | done 2ba9fc7 (and `**/claude-log/` ignored) | S | nothing | |
| A9 | Filler: anything the owner wants changed in the Agents app after seeing it | idea | S to M | A1 | |
| A10 | Freeze 22:00 UTC: fixes only | | | A4, A5 | |
| A11 | Release 26.04.20261024: scripts/release.sh in tmux (the owner types the passphrase), then verify GitHub, R2, apt.maluos.com, publish the download page, start the CI run | done 2026-10-24 00:37 UTC (tag at 27eb819; apt republished 00:45; download page 00:49; release CI run 40045853008) | 1 h wall | A10, 00:00 UTC | the release holds slices 7 and 8; release.sh needs `source ~/.config/maluos/publish.env` first, else the R2 upload is skipped (it was, and was run by hand) |

## B. Slice 9 (Phase 12), planned 2026-10-23

Cut as recommended: the session leftovers and the slice 7 and 8
leftovers, all in this repository (docs/phase12-desktop.md "Slice 9").

| # | Task | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| B1 | Grant requests decided with level, expiry and budget; "Choose…" opens the Credential Manager | built 2026-10-24 | S | nothing | session, Desk, Credential Manager: Decide… (level, expiry, budget), Choose… on the notification |
| B2 | A grant request carries the model call that caused it | built 2026-10-24 | M | nothing | vault request rows carry `cause`, the gateway passes the call, the session and the windows show it |
| B3 | Agents' budget alerts reach their owners | built 2026-10-24 | S | nothing | the alert names the agent and carries its owner; the owner is notified by name |
| B4 | Re-authentication (polkit auth_self) before a reveal, a rotation and a backup | built 2026-10-24 | M | nothing | the check lives in the vault (pkcheck on the caller, polkit action com.maluos.vault.reveal, auth_self); ledger detail reauth |
| B5 | Agents app: streaming answers, the office page with the desk's identity, timers | built 2026-10-24 | M | nothing | task progress + Client.stream, Talk draws the answer as it grows, the office page with the desk token, timers |
| B6 | The public MaluApps catalogue signed and verified | built 2026-10-24 | S | F2 taken by default (release key) | catalog.json.asc by the release key, verified with the archive keyring; scripts/publish-catalog.sh |
| B7 | Not in slice 9: desktop-background icons (F1), DEP-11 and the upgrade path, branding on hardware | deferred | | | their own slices later |

## C. Kernel-side work (maludb-os-core repository)

Specified in docs/desk-enrolment.md, built in the kernel repository, no
change needed on the desk when they land.

| # | Task | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| C1 | `desks/apps`: the applications table decides what an office's desks see | specified | M | nothing | the mock office serves four apps |
| C2 | `desks/agents` with per-agent `tasks`, `activity`, `page` | specified | M | Agent HR | the mock office serves two agents |
| C3 | The model endpoint for desks (`surface = desk` on the prompt ledger); memory and actions MCP servers published to desks | planned (phase12 "After that" 1) | L | nothing | turns endpoints.models, memory, actions from null into real ones |

## D. Phase 13, the estate (docs/phase13-estate.md)

Six slices as planned; the order of 3 and 4 is an open question for the
owner. Each slice ends with its test on the three-machine proof.

| # | Slice | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| D1 | 1 Nodes and the operator's view: node identity, enrolment of servers, the Estate page on the Desk | specified (docs/phase13-slice1-nodes.md) | L | nothing | new package maluos-estate; the kernel half (db/188, the estate endpoints) needs the owner's approval first |
| D2 | 2 The agent directory and delegation: Agent HR registration, the A2A task endpoint on every node with the authorisation envelope, the desk's personal agent, operator actions on remote nodes | specified (docs/phase13-slice2-delegation.md) | L | D1, C2 | nodes pull their tasks from the coordinator; the envelope is verified on the agent's host; the kernel half (db/189) needs the owner's approval first |
| D3 | 3 Shared inference: the gateway as a backend for other nodes, admission control, desk contribution opt-in | planned; specified as G1-G5 below | L | D1 | |
| D4 | 4 Federated memory: personal, departmental and enterprise memory over the existing scopes; the memory endpoint real | planned | L | D1 | the Agents app's Memory page waits for this |
| D5 | 5 Events and durable work | planned | L | D2 | |
| D6 | 6 Skills, resilience, federation between estates | planned | L | D2 to D5 | |
| D7 | The three-machine proof | planned | M | each slice | |

Shared GPUs (docs/phase13-shared-gpus.md, decided with the owner
2026-10-25): a GPU on a networked MaluOS device served to the LAN through
the gateway, managed by the Sovereign LLM Manager through one node API,
shown in a forked System Manager. Community first; G4 is the paid
`scheduler` later. A DGX Spark is arm64 and joins as a non-MaluOS node;
an RTX x86 box is the MaluOS case.

| # | Slice | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| G1 | GPU facts: the `nvidia` component, `maluctl gpu status --json` (NVML, amdgpu/i915 sysfs), `gpus` in the session's host state and the D1 report; the fork of gnome-system-monitor 49.1 as maluos-system-monitor with the GPUs tab (local half: live GPUs, the sharing switch, the contribution rule by chassis) | built 2026-10-25 (docs/phase13-shared-gpus.md, Status) | M + M | nothing | tabs logic-free: JSON over D-Bus from the session, `maluctl` for actions |
| G2 | The node API on the gateway (`/node/v1` status, health, queue with cancel/priority/pause, runs with `since_seq`, models, keys), async jobs, the Anthropic face; `maluctl gateway expose` and `key issue`; the `remote` backend kind and `backend add URL --key` on a desk | built 2026-10-25, images boot-tested 2026-10-26 (maluos-gateway 0.4.0; docs/phase13-shared-gpus.md, Status) | L | G1 for the facts | docs/inference-node-api.md is surface 1 (written first); pairing by hand, no coordinator |
| G3 | The node service's faces in maluos-local-llm-server so the Mac and the DGX Spark speak the same API | planned | L | G2's API document | the owner's other repository |
| G4 | Phase 13 slice 3 proper: `inference` facts in the heartbeat, `endpoints.inference` to desks, backends from the directory, the envelope on remote requests, admission estate-wide; servers share always, dedicated desktops opt-in, laptops opt-in and idle only | planned, paid `scheduler` in a later release | L | D1, D2, G2 | = D3; settles F5 for inference and F6 |
| G5 | The MaluOS Network and Queue tabs in the fork: the local queue with cancel and priority, the Estate page's data, the estate's queue snapshot and operator actions | local half built 2026-10-26 (maluos-system-monitor 49.1+maluos.3, maluos-session 0.8.0; docs/phase13-shared-gpus.md, Status); the estate half waits for D1 and D2 | M | G2 (local half); D1, D2 (estate half) | "Open in Sovereign LLM Manager" for history, usage, keys, policies |

## E. Phase 11, the installer, and the rest

| # | Task | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| E1 | Phase 11: a MaluOS installer replacing subiquity, five slices (docs/phase11-installer.md): the live environment and our own ISO assembly; the engine and the unattended plan; the urwid screens; parity and the switch; the graphical live installer | slice 1 built 2026-10-24 (the live medium boots on BIOS and UEFI; docs/phase11-slice1-live.md status); slice 2 built 2026-10-24 (the engine installs unattended from the medium's plan; every round passed: server BIOS and UEFI, desktop, encrypted, over SSH; docs/phase11-slice2-engine.md status); slice 3 built 2026-10-24 (the screens; the pty test and the serial-console round pass; docs/phase11-slice3-screens.md); next: slice 4, the switch, after the owner's real-machine round | L per slice | nothing (slice 5 after Phase 12) | the last Ubuntu-branded surface; telemetry endpoint needed beside the download site (slice 2) |
| E2 | Phase 11, the Apple T2 round: Intel Macs with the T2 chip (2018 on) for the installer and the installed system (docs/phase11-apple-t2.md): the apple-t2 component (apple-bce and the two patched drivers by DKMS, the Touch Bar and fan daemons, the audio profiles, Vulkan for the Radeon), the installer's Mac facts, the kernel options, the firmware import from macOS, storage.target free beside macOS, the extra Ubuntu pool on the medium | built 2026-10-24 (unit tests, the pty screens test; the QEMU rounds --alongside and --apple in the status); the real MacBookPro15,1 round is the owner's | L | E1 slices 1-3 | the first real T2 Mac decides suspend, audio and the Touch Bar; the firmware comes from the owner's macOS |
| E2 | A graphical live session on the ISO | folded into Phase 11 slice 5 | L | E1 | |
| E3 | Phase 7 rest: ISO catalogue layers and the maluctl component selector | in progress | M | nothing | docs/components.md |
| E4 | Phase 9 rest: editions and entitlements (Professional, Enterprise) | requirements drafted | L | a pricing decision | Phase 13 absorbs fleet and scheduler |
| E5 | Phase 14+: journal to memory, quality judge | idea | L | D4 | |
| E6 | arm64 builds | idea | M | nothing | PLAN.md framing decision |

## F. Decisions waiting on the owner

| # | Decision | Where it is written | Blocks |
|---|---|---|---|
| F1 | Agent icons on the desktop background: live with the grid folder, or ship our own shell extension | docs/phase12-desktop.md, slice 8 status | B7 |
| F2 | Which key signs the public apps catalogue: the release key, taken by default in slice 9 (a separate key would need maluos-keyring to ship it) | docs/phase12-desktop.md, slice 9 status | nothing now |
| F3 | Lid switch behaviour with the new power defaults | docs/phase12-desktop.md, slice 7 | nothing yet |
| F4 | Office catalogue location in the kernel (which table decides what desks see) | docs/desk-enrolment.md | C1 |
| F5 | Edition boundary for estate features | docs/phase13-estate.md, open questions; for inference decided 2026-10-25 (Community G1-G3, G5; paid `scheduler` G4), docs/phase13-shared-gpus.md | E4 |
| F6 | Desk inference contribution rules | decided 2026-10-25: servers always, dedicated desktops opt-in, laptops opt-in and idle only (docs/phase13-shared-gpus.md) | nothing |
| F7 | Phase 13 slice 3 before 4, or 4 before 3 | docs/phase13-estate.md, open questions | D3, D4 |
| F8 | Pricing and editions | docs/phase9-editions.md | E4 |

## H. Housekeeping

| # | Task | Status | Notes |
|---|---|---|---|
| H1 | Proxmox host memory: balloon floors on the other VMs, KSM check | with the owner | commands given 2026-10-23; the dev VM has its cap and floor |
| H2 | Cloudflare transform rule for download.maluos.com | with the owner | from the Phase 10 release work |
| H3 | packages/maluos-meta/debian/docs/claude-log/ out of the repo | done | A8 |
| H4 | Lintian back on in the local package build (SKIP_LINTIAN=1 since slice 7 because of maludb-os-core's node_modules) | idea | exclude that package from lintian instead |
| H5 | Memory notes and docs kept current after each release | ongoing | |
