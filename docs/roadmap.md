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
| Latest release | 26.04.20261024 is tomorrow's; 26.04.20261023 shipped with Phase 12 slice 6 (one release per UTC day) |
| Phase 12 (desktop) | slices 1 to 6 released; slice 7 built, boot-tested, committed c9ccdbf, desktop ISO rebuilt; slice 8 coded, packaged, image chain running |
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
| A4 | Server set: rootfs, qcow2, ISO, iso-check, UEFI boot test, share (BIOS is CI's) | running since 12:32 | 2 h wall | A3 | the server images on the share are still the slice 6 set; maluos-firstboot 0.1.8 and maluos-agent 0.3.0 apply to servers |
| A5 | Desktop ISO rebuilt with slice 8 and A7, iso-check, share | queued behind A4 and the A7 desktop chain | S | A2 | five minutes with the chain script |
| A6 | Release prep: docs/release.md row drafted, download page text ready, docs/PLAN.md and phase12 status rows final | planned | S | A4, A5 | |
| A7 | Filler: the session refreshes the MaluApps catalogue on each heartbeat (slice 7 leftover) | coded (maluos-desktop-session 0.6.1), desktop chain queued | S | A3 | boot test check added; commit after the test |
| A8 | Filler: remove packages/maluos-meta/debian/docs/claude-log/ from the repo | done 2ba9fc7 (and `**/claude-log/` ignored) | S | nothing | |
| A9 | Filler: anything the owner wants changed in the Agents app after seeing it | idea | S to M | A1 | |
| A10 | Freeze 22:00 UTC: fixes only | | | A4, A5 | |
| A11 | Release 26.04.20261024: scripts/release.sh in tmux (the owner types the passphrase), then verify GitHub, R2, apt.maluos.com, publish the download page, start the CI run | planned | 1 h wall | A10, 00:00 UTC | the release holds slices 7 and 8 |

## B. Slice 9 candidates (Phase 12)

Not yet cut. The owner picks; the recommendation is B1 plus B2 as one
slice, since every item is in this repo and visible on the desk.

| # | Task | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| B1 | The session, further: grant budget and level choice in the notification; credential requests surfaced with the model call that caused them; agents' budget alerts attributed to their owners | planned (phase12 "After that" 5) | M | nothing | |
| B2 | Slice 7 and 8 leftovers: re-authentication before the Credential Manager reveals a secret; streaming answers in the Agents app; the office agent page loaded with the desk's identity; activity re-read on a timer | planned | M | nothing | re-authentication needs a polkit or PAM path, the one design question |
| B3 | A desktop-icons shell extension of our own, so agent icons appear on the desktop background | idea | M to L | owner's decision | gnome-shell-extension-desktop-icons-ng is not in the 26.04 archive; the grid's Agents folder and ~/Desktop/Agents stand in |
| B4 | Signing the public apps catalogue (download.maluos.com/apps/catalog.json) | planned | S to M | a key decision | which key, where verification happens (maluctl office apps) |
| B5 | Updates, further: DEP-11 metadata for apt.maluos.com so GNOME Software lists MaluOS packages; a release upgrade path to the next LTS | planned (phase12 "After that" 2) | M (DEP-11), L (upgrade path) | nothing | |
| B6 | Branding the rest: firmware logo path on hardware, GNOME help, the ISO's own boot splash | planned (phase12 "After that" 3) | M | hardware to test on | |

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
| D1 | 1 Nodes and the operator's view: node identity, enrolment of servers, the Estate page on the Desk | planned | L | nothing | |
| D2 | 2 The agent directory and delegation: Agent HR registration, the A2A task endpoint on every node with the authorisation envelope, the desk's personal agent, operator actions on remote nodes | planned | L | D1, C2 | slice 8's maluos_agent_tasks is the protocol; this adds the envelope and the directory |
| D3 | 3 Shared inference: the gateway as a backend for other nodes, admission control, desk contribution opt-in | planned | L | D1 | |
| D4 | 4 Federated memory: personal, departmental and enterprise memory over the existing scopes; the memory endpoint real | planned | L | D1 | the Agents app's Memory page waits for this |
| D5 | 5 Events and durable work | planned | L | D2 | |
| D6 | 6 Skills, resilience, federation between estates | planned | L | D2 to D5 | |
| D7 | The three-machine proof | planned | M | each slice | |

## E. Phase 11, the installer, and the rest

| # | Task | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| E1 | Phase 11: a MaluOS installer replacing subiquity, five slices (docs/phase11-installer.md): the live environment and our own ISO assembly; the engine and the unattended plan; the urwid screens; parity and the switch; the graphical live installer | planned 2026-10-23, the owner's five answers in | L per slice | nothing (slice 5 after Phase 12) | the last Ubuntu-branded surface; telemetry endpoint needed beside the download site (slice 2) |
| E2 | A graphical live session on the ISO | folded into Phase 11 slice 5 | L | E1 | |
| E3 | Phase 7 rest: ISO catalogue layers and the maluctl component selector | in progress | M | nothing | docs/components.md |
| E4 | Phase 9 rest: editions and entitlements (Professional, Enterprise) | requirements drafted | L | a pricing decision | Phase 13 absorbs fleet and scheduler |
| E5 | Phase 14+: journal to memory, quality judge | idea | L | D4 | |
| E6 | arm64 builds | idea | M | nothing | PLAN.md framing decision |

## F. Decisions waiting on the owner

| # | Decision | Where it is written | Blocks |
|---|---|---|---|
| F1 | Agent icons on the desktop background: live with the grid folder, or ship our own shell extension | docs/phase12-desktop.md, slice 8 status | B3 |
| F2 | Which key signs the public apps catalogue | docs/phase12-desktop.md, slice 7 status | B4 |
| F3 | Lid switch behaviour with the new power defaults | docs/phase12-desktop.md, slice 7 | nothing yet |
| F4 | Office catalogue location in the kernel (which table decides what desks see) | docs/desk-enrolment.md | C1 |
| F5 | Edition boundary for estate features | docs/phase13-estate.md, open questions | E4 |
| F6 | Desk inference contribution rules | docs/phase13-estate.md, open questions | D3 |
| F7 | Phase 13 slice 3 before 4, or 4 before 3 | docs/phase13-estate.md, open questions | D3, D4 |
| F8 | Pricing and editions | docs/phase9-editions.md | E4 |

## G. Housekeeping

| # | Task | Status | Notes |
|---|---|---|---|
| G1 | Proxmox host memory: balloon floors on the other VMs, KSM check | with the owner | commands given 2026-10-23; the dev VM has its cap and floor |
| G2 | Cloudflare transform rule for download.maluos.com | with the owner | from the Phase 10 release work |
| G3 | packages/maluos-meta/debian/docs/claude-log/ out of the repo | done | A8 |
| G4 | Lintian back on in the local package build (SKIP_LINTIAN=1 since slice 7 because of maludb-os-core's node_modules) | idea | exclude that package from lintian instead |
| G5 | Memory notes and docs kept current after each release | ongoing | |
