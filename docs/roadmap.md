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
| Latest release | 26.04.20261024, shipped 2026-10-24 00:37 UTC with Phase 12 slices 7 and 8 (one release per UTC day) |
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
| B1 | Grant requests decided with level, expiry and budget; "Choose…" opens the Credential Manager | planned | S | nothing | session, Desk, Credential Manager |
| B2 | A grant request carries the model call that caused it | planned | M | nothing | vault request rows, gateway, session |
| B3 | Agents' budget alerts reach their owners | planned | S | nothing | gateway alerts, session |
| B4 | Re-authentication (polkit auth_self) before a reveal, a rotation and a backup | planned | M | nothing | the one design in the slice; ledger detail reauth |
| B5 | Agents app: streaming answers, the office page with the desk's identity, timers | planned | M | nothing | maluos-agent task progress, maluos-agents, mock office |
| B6 | The public MaluApps catalogue signed and verified | planned | S | a key decision (F2) | release key by default |
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
| D3 | 3 Shared inference: the gateway as a backend for other nodes, admission control, desk contribution opt-in | planned | L | D1 | |
| D4 | 4 Federated memory: personal, departmental and enterprise memory over the existing scopes; the memory endpoint real | planned | L | D1 | the Agents app's Memory page waits for this |
| D5 | 5 Events and durable work | planned | L | D2 | |
| D6 | 6 Skills, resilience, federation between estates | planned | L | D2 to D5 | |
| D7 | The three-machine proof | planned | M | each slice | |

## E. Phase 11, the installer, and the rest

| # | Task | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| E1 | Phase 11: a MaluOS installer replacing subiquity, five slices (docs/phase11-installer.md): the live environment and our own ISO assembly; the engine and the unattended plan; the urwid screens; parity and the switch; the graphical live installer | planned 2026-10-23, the owner's five answers in; slices 1 and 2 specified (docs/phase11-slice1-live.md, docs/phase11-slice2-engine.md) | L per slice | nothing (slice 5 after Phase 12) | the last Ubuntu-branded surface; telemetry endpoint needed beside the download site (slice 2) |
| E2 | A graphical live session on the ISO | folded into Phase 11 slice 5 | L | E1 | |
| E3 | Phase 7 rest: ISO catalogue layers and the maluctl component selector | in progress | M | nothing | docs/components.md |
| E4 | Phase 9 rest: editions and entitlements (Professional, Enterprise) | requirements drafted | L | a pricing decision | Phase 13 absorbs fleet and scheduler |
| E5 | Phase 14+: journal to memory, quality judge | idea | L | D4 | |
| E6 | arm64 builds | idea | M | nothing | PLAN.md framing decision |

## F. Decisions waiting on the owner

| # | Decision | Where it is written | Blocks |
|---|---|---|---|
| F1 | Agent icons on the desktop background: live with the grid folder, or ship our own shell extension | docs/phase12-desktop.md, slice 8 status | B7 |
| F2 | Which key signs the public apps catalogue (the release key is proposed) | docs/phase12-desktop.md, slice 9 | B6 |
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
