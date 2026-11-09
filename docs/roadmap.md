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
| Latest release | 26.04.20261108, cut 2026-11-08 14:14 UTC (Phase 13 D1c, the estate behind a proxy: the fresh set from b9e3e68, both images boot-tested on UEFI, guard-clean; apt.maluos.com carries estate 0.7.0 / kernel 2026.11.06maluos1 / installer 0.3.6 / firstboot 0.1.16 since 11-06 22:17). 26.04.20261106 (11-06 22:07) was a mixed set cut mid-chain: the D1c server image, the G5b desktop image, the 11-02 ISOs (docs/release.md) |
| Phase 12 (desktop) | slices 1 to 8 released (26.04.20261024); slice 9 built and boot-tested 2026-10-24 (desktop UEFI 252 ok, server UEFI 140 ok), on the share for the 26.04.20261025 release |
| Phase 13 (estate) | slices 1, 1b, 2, 3, 4 and 4b (D1 to D4) built, boot-tested and released by 2026-11-02 (kernel db/188 to db/193); shared GPUs G1, G2 and G5's local half built by 2026-10-27, G4 with slice 3, G1/G2 on real hardware 2026-11-04; G5b built and boot-tested 2026-11-03; D7 started on the owner's machines 2026-11-05 and stopped at the office behind its proxy, answered by D1c (the hub as a setting, `proxy_address`) the same day and released as 26.04.20261108; next: D7 again with D1c (step 0a of the runbook), B8, E4 slice 1, G3; D5, D6 planned |
| Phase 11 (installer) | proposed only |
| Phases 7 and 9 | partly done; the rest waits (components catalogue, editions) |
| Dev host | Back on the Proxmox VM 4050 from 2026-11-05 (no KVM: packages ~10 min, a server chain ~1 h, the desktop chain longer; the drop-caches loop and gentle.py apply); the bare-metal RTX 3060 host (docs/dev-host-handoff.md) served 2026-11-04 and 2026-11-05 for the real-hardware rounds and stays the place for G1/G2/G4 on hardware and the fast boot tests |

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
| B7 | Not in slice 9: DEP-11 and the upgrade path, branding on hardware (desktop-background icons dropped by F1, 2026-11-03) | deferred | | | their own slices later |
| B8 | The lid switch on a desk: `HandleLidSwitchExternalPower=ignore` in maluos-desktop-branding's logind drop-in (battery unchanged), the boot test reads `loginctl show-session`/the drop-in | planned 2026-11-03 (F3) | S | nothing | rides the next desktop package bump |

## C. Kernel-side work (maludb-os-core repository)

Specified in docs/desk-enrolment.md, built in the kernel repository, no
change needed on the desk when they land.

| # | Task | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| C1 | `desks/apps`: the applications table decides what an office's desks see | specified; the rule settled by F4 on 2026-11-03 (active apps with a url the desk owner's member or department has an `application_access` grant on, plus the built-ins) | M | nothing | the mock office serves four apps |
| C2 | `desks/agents` with per-agent `tasks`, `activity`, `page` | specified | M | Agent HR | the mock office serves two agents |
| C3 | The model endpoint for desks (`surface = desk` on the prompt ledger); memory and actions MCP servers published to desks | planned (phase12 "After that" 1) | L | nothing | turns endpoints.models, memory, actions from null into real ones |

## D. Phase 13, the estate (docs/phase13-estate.md)

Six slices as planned; the order of 3 and 4 is an open question for the
owner. Each slice ends with its test on the three-machine proof.

| # | Slice | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| D1 | 1 Nodes and the operator's view: node identity, enrolment of servers, the estate on the System Monitor's MaluOS Network tab | host half built and boot-tested 2026-10-27 against the mock estate; the kernel half (db/188) built 2026-10-28 at maludb-os-core 84af4f0, vendored as 2026.10.28maluos1 (maluos-estate 0.1.1, vault 0.4.1, gateway 0.4.3, firstboot 0.1.11, desk 0.5.0, session 0.9.0, the fork 49.1+maluos.4; docs/phase13-slice1-nodes.md, Status); the kernel half approved and built 2026-10-28 (bin/test_estate_nodes.php, 54 checks) | L | nothing | new package maluos-estate |
| D1b | 1b The overlay: WireGuard hub and spoke through the coordinator's host, the tunnel made by join and enroll, the key in the vault, an address and a name per node from the kernel, `gateway expose --bind overlay` | both halves built 2026-10-28 (kernel db/189 at maludb-os-core 6c94d29; maluos-estate 0.2.1, desk 0.5.1, gateway 0.5.1, vault 0.4.2; docs/phase13-slice1b-overlay.md, Status); images boot-tested 2026-10-28 | M | D1 | Community; a mesh and a second hub later |
| D1c | The estate behind a proxy (docs/phase13-estate-behind-a-proxy.md): the hub is whichever member the others reach on one UDP port, the role a setting of the running estate (`maluctl estate overlay hub HOST:PORT \| off`, `POST /api/v1/estate/overlay/hub`), the reconciler following a moved hub, a reachability verdict from the handshakes in `overlay status` and the report, the office-through-a-forward case documented (router or nginx `stream`); part 2: `components.maludb-os-core.proxy_address` so the office's names under https go to the proxy, never loopback, in the component, the kernel's installer (`--proxy-address`), the First boot screen and the plan | built 2026-11-05 (maluos-estate 0.7.0, maludb-os-core 2026.11.06maluos1 with the kernel at main 9e931ca vendored (the branch estate/hub-and-proxy-address, proved 62 ok and merged as PR #6 on 2026-11-06), installer 0.3.6, firstboot 0.1.16; apps-test 20, install-plan-test 40, screens pty PASS, desk-local-test 156, the server UEFI boot test 215 ok with the https seed and the hub round trip; released 26.04.20261108, apt.maluos.com republished 11-06); the relay through the kernel and the mesh stay deferred with their shape fixed | S + M + M | D1b | the owner's questions in the note: which member is the hub in the test estate; `proxy_address` in the handbook's plan |
| D2 | 2 The agent directory and delegation: the directory, the A2A task endpoint on every node with the authorisation envelope, the desk's personal agent, operator actions on remote nodes | both halves built 2026-10-28, images boot-tested 2026-10-29 (desktop UEFI 357 ok, server UEFI 181 ok; kernel db/190 at maludb-os-core fa6e588, approved and pushed; maluos-estate 0.3.1, agent 0.5.2, desk 0.6.0, session 0.10.0, agents 0.3.1, gateway 0.5.2; docs/phase13-slice2-delegation.md, Status) | L | D1, D1b | nodes pull their tasks from the coordinator; the envelope is verified on the agent's host; Agent HR hiring of a node's agent later |
| D3 | 3 Shared inference: the gateway as a backend for other nodes through the directory, the idle rule, the envelope on remote calls; estate-wide placement and admission as the paid `scheduler` | both halves BUILT and BOOT-TESTED 2026-10-30 on the spec's recommendations (kernel db/191 at maludb-os-core d7ebcfa, 58 checks; gateway 0.6.0, estate 0.4.0, desk 0.7.0, session 0.11.0, firstboot 0.1.12, system-monitor +maluos.5; desk-local-test 133, gateway-local-test 188; UEFI boot tests desktop 389 / server 191 after four chain runs: docs/phase13-slice3-inference.md, Status, "What the image chain found") | L | D1, D1b, D2, G2 | node-to-node traffic over the overlay |
| D4 | 4 Federated memory: personal, departmental and enterprise memory over the existing scopes; the memory endpoint real | both halves BUILT and BOOT-TESTED 2026-11-01 (docs/phase13-slice4-memory.md, Status: kernel db/192 at maludb-os-core 0c89fc6 with a 68-check proof; the new package maluos-memory 0.1.3, estate 0.5.0, desk 0.8.0, agent 0.6.1, agents 0.4.0, session 0.12.0; local tests 57 + 149 + 22 checks; the image chain's fifth run passed: desktop 437, server 200; seven findings in the Status); PUSHED 2026-11-01 (8920827); slice 4b (docs/phase13-slice4b-memory.md: semantic recall through the gateway, the Memory MCP for desks under the policy, a dual host published once) built 2026-11-01, kernel db/193 ab00263, the chain to run; the maludb-core follow-ups on two branches of maludb-core-26 (0.107.0 scope on claims and statements; the listener's principal binding), the owner's to merge | L | D1, D2 (the envelope, the keys), D3 (the facts/view/peers pattern) | the Agents app's Memory page waits for this; maludb-core 0.106.0 enforces scope on memories, episodes and documents but not on claims or statements, and the MC2DB listener binds no principal: both filed as follow-ups for the owner's other repository Slice 4b (memory quality: semantic recall through the gateway, the Memory MCP to desks under the policy, a dual host published once; docs/phase13-slice4b-memory.md) BUILT and BOOT-TESTED 2026-11-02 (desktop 445, server 200; memory 0.2.1, desk 0.9.0, agents 0.5.0, estate 0.6.0, gateway 0.6.1, kernel db/193 vendored 2026.11.01maluos1). |
| D5 | 5 Events and durable work | planned | L | D2 | |
| D6 | 6 Skills, resilience, federation between estates | planned; federation is an Enterprise entitlement (F5, 2026-11-03), skills and resilience Community | L | D2 to D5; E4 slice 1 for the entitlement check | |
| D7 | The three-machine proof | the runbook written 2026-10-29 (docs/phase13-three-machine-proof.md: office, gpu, desk; slices 1, 1b, 2, 3 on real hosts); the owner's first run 2026-11-05 passed stages 1 to 3 and stopped at stage 4 on the office behind its proxy (handbook 22-estate-behind-a-proxy.md); the runbook's step 0a now asks where the hub is; runs again with D1c's packages | M | each slice, D1c | the GPU host needs no static address as a spoke; as the hub it needs one UDP port |

Shared GPUs (docs/phase13-shared-gpus.md, decided with the owner
2026-10-25): a GPU on a networked MaluOS device served to the LAN through
the gateway, managed by the Sovereign LLM Manager through one node API,
shown in a forked System Manager. Community first; G4 is the paid
`scheduler` later. A DGX Spark is arm64 and joins as a non-MaluOS node;
an RTX x86 box is the MaluOS case.

| # | Slice | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| G1 | GPU facts: the `nvidia` component, `maluctl gpu status --json` (NVML, amdgpu/i915 sysfs), `gpus` in the session's host state and the D1 report; the fork of gnome-system-monitor 49.1 as maluos-system-monitor with the GPUs tab (local half: live GPUs, the sharing switch, the contribution rule by chassis) | built 2026-10-25; on real hardware 2026-11-04 (RTX 3060 on the GPU dev host: every field live, chassis desktop → opt-in; docs/phase13-shared-gpus.md, Status); the installer adds the `nvidia` component on a box with an NVIDIA card, from the medium or the network (installer 0.3.4, 2026-11-04) | M + M | nothing | tabs logic-free: JSON over D-Bus from the session, `maluctl` for actions |
| G2 | The node API on the gateway (`/node/v1` status, health, queue with cancel/priority/pause, runs with `since_seq`, models, keys), async jobs, the Anthropic face; `maluctl gateway expose` and `key issue`; the `remote` backend kind and `backend add URL --key` on a desk | built 2026-10-25, images boot-tested 2026-10-26 (maluos-gateway 0.4.0); on real hardware 2026-11-04 (Ollama 0.40.6 on the RTX 3060, qwen3:8b through the gateway, share/keys/expose, the queue under load; `backend add` from a second desk still to do; docs/phase13-shared-gpus.md, Status) | L | G1 for the facts | docs/inference-node-api.md is surface 1 (written first); pairing by hand, no coordinator |
| G3 | The node service's faces in maluos-local-llm-server so the Mac and the DGX Spark speak the same API | planned | L | G2's API document | the owner's other repository |
| G4 | Phase 13 slice 3 proper: `inference` facts in the heartbeat, `endpoints.inference` to desks, backends from the directory, the envelope on remote requests, admission estate-wide; servers share always, dedicated desktops opt-in, laptops opt-in and idle only | built and boot-tested 2026-10-30 with D3; the `scheduler` entitlement is a flag on the kernel's settings row until Phase 9's contracts service exists | L | D1, D2, G2 | = D3; settles F5 for inference and F6 |
| G5 | The MaluOS Network and Queue tabs in the fork: the local queue with cancel and priority, the Estate page's data, the estate's queue snapshot and operator actions | local half built 2026-10-26, images boot-tested 2026-10-27 (maluos-system-monitor 49.1+maluos.3, maluos-session 0.8.0, maluos-gateway 0.4.2; docs/phase13-shared-gpus.md, Status); the Estate group of the Network tab filled by D1 (49.1+maluos.4: the office's nodes, presence, health, alerts; read-only) and D3 (49.1+maluos.5: the directory's backends in Paired Nodes); the rest of the estate half is G5b | M | G2 (local half); D1, D3 (the Estate group) | "Open in Sovereign LLM Manager" for history, usage, keys, policies |
| G5b | G5's estate half: the Estate group's node actions (a node row's menu: restart, start or stop an agent, apply updates, reboot where the node allows it, through `maluctl office estate action`, the outcome as a toast when the result arrives); the estate's inference backends with their queue and expected wait in the Network tab (`GET /api/v1/estate/inference`, as `maluctl office estate inference` shows them); an Estate section in the Queue tab from the kernel's queue snapshot per node (the heartbeat's lanes, queue and `expected_wait_s`, every 60 s), shown live when the office has `scheduler` and as the last snapshot otherwise; the session state carries both so the tabs stay logic-free; the local test's fixture and the self-test summary grow the two, the boot test checks them on the mock estate | built and boot-tested 2026-11-03 (maluos-session 0.13.0, maluos-system-monitor 49.1+maluos.6; the fork's local test 8 checks; desktop UEFI boot test 447 ok, 1 FAIL in slice 3's idle-mark race, not G5b's; docs/phase13-shared-gpus.md, "G5b built"); on the next release's images | M | D1, D2 (the actions), D3 (the inference contract); the fork at 49.1+maluos.5 | the `scheduler` rules stay on the Estate page ("Open in Sovereign LLM Manager"); not in it: the `move` route, a pairing dialog, translations |

## E. Phase 11, the installer, and the rest

| # | Task | Status | Effort | Depends on | Notes |
|---|---|---|---|---|---|
| E1 | Phase 11: a MaluOS installer replacing subiquity, five slices (docs/phase11-installer.md): the live environment and our own ISO assembly; the engine and the unattended plan; the urwid screens; parity and the switch; the graphical live installer | slice 1 built 2026-10-24 (the live medium boots on BIOS and UEFI; docs/phase11-slice1-live.md status); slice 2 built 2026-10-24 (the engine installs unattended from the medium's plan; every round passed: server BIOS and UEFI, desktop, encrypted, over SSH; docs/phase11-slice2-engine.md status); slice 3 built 2026-10-24 (the screens; the pty test and the serial-console round pass; docs/phase11-slice3-screens.md); next: slice 4, the switch, after the owner's real-machine round | L per slice | nothing (slice 5 after Phase 12) | the last Ubuntu-branded surface; telemetry endpoint needed beside the download site (slice 2) |
| E2 | Phase 11, the Apple T2 round: Intel Macs with the T2 chip (2018 on) for the installer and the installed system (docs/phase11-apple-t2.md): the apple-t2 component (apple-bce and the two patched drivers by DKMS, the Touch Bar and fan daemons, the audio profiles, Vulkan for the Radeon), the installer's Mac facts, the kernel options, the firmware import from macOS, storage.target free beside macOS, the extra Ubuntu pool on the medium | built 2026-10-24 (unit tests, the pty screens test; the QEMU rounds --alongside and --apple in the status); the real MacBookPro15,1 round is the owner's | L | E1 slices 1-3 | the first real T2 Mac decides suspend, audio and the Touch Bar; the firmware comes from the owner's macOS |
| E2 | A graphical live session on the ISO | folded into Phase 11 slice 5 | L | E1 | |
| E3 | Phase 7 rest: ISO catalogue layers and the maluctl component selector | in progress | M | nothing | docs/components.md |
| E4 | Phase 9 rest: editions and entitlements (Professional, Enterprise) | terms confirmed 2026-11-03 (F5, F8); slice 1 (entitlements: maluos-pro, the contracts stub owning the `scheduler` flag, the esm suite) scheduled after D7 and G5b; price points needed before slice 5 (commerce) | L | D7, G5b; price points for slice 5 | Phase 13 absorbs fleet and scheduler; federation (D6) is Enterprise |
| E5 | Phase 14+: journal to memory, quality judge | idea | L | D4 | |
| E6 | arm64 builds | idea | M | nothing | PLAN.md framing decision |
| E7 | The applications as components (the maluos-apps proposal, maluos-docs 21-maluos-apps.md; reconciliation R6): phase 1 the maluos-apps metapackage, the kernel component's applications step (components.maludb-os-core.apps: install, ref, propose_agents; a marker per application; a failure does not block the next), `maluctl app names`; phase 2 `maluctl app add|update|status|list|remove` and the installer's First boot screen; phase 3 `maludb-os-<key>` packages for the four defaults and DocCloud so an offline ISO installs an office with its applications; phase 4 `remove --purge`, the kernel's retire path, the names in the estate's node report | phase 1 merged 2026-11-05 (maluos#4: maludb-os-core 2026.11.01maluos2, maluos-firstboot 0.1.15, maluos-meta 0.2.17; tests/apps-test.py 13 checks; the boot test's checks behind BOOT_TEST_APPS=1); the dev-host boot test is the owner's: an office with hr, projects, helpdesk and spaces active after first boot, `maluctl app names` listing eight names | S + M + L + M | the kernel's installer (bin/app_install.php); R5 (the component on from the screen or the plan) | until phase 3 an office needs the network at first boot (the clones come from github.com/maludb) |

## F. Decisions waiting on the owner

| # | Decision | Where it is written | Blocks |
|---|---|---|---|
| F1 | Agent icons on the desktop background: live with the grid folder, or ship our own shell extension | decided 2026-11-03: live with the grid folder and ~/Desktop/Agents; no extension of our own; reopen only if users ask (docs/phase12-desktop.md, slice 8 status) | nothing (B7 loses the item) |
| F2 | Which key signs the public apps catalogue: the release key, taken by default in slice 9 (a separate key would need maluos-keyring to ship it) | decided 2026-11-03: the release key, as slice 9 built it (docs/phase12-desktop.md, slice 9 status) | nothing |
| F3 | Lid switch behaviour with the new power defaults | decided 2026-11-03: ignore the lid on external power only (`HandleLidSwitchExternalPower=ignore`; on battery the lid still suspends), so a plugged-in laptop keeps its agents and its shared GPU with the lid shut (docs/phase12-desktop.md, slice 7) | B8 |
| F4 | Office catalogue location in the kernel (which table decides what desks see) | decided 2026-11-03: `applications` with status active and a url, filtered by `application_access` for the desk owner's member row or department, plus every built-in of `application_catalog`; the grants are the publishing decision, no new table (docs/desk-enrolment.md) | C1 |
| F5 | Edition boundary for estate features | decided 2026-11-03: the estate is free, management is paid. Community: join, the operator's view, delegation, memory, sharing and the node API, one coordinator, any number of nodes. Paid: `scheduler` (decided 2026-10-25), `fleet`, `sso`, federation between estates (D6) (docs/phase13-estate.md, decision 10) | E4, D6 |
| F6 | Desk inference contribution rules | decided 2026-10-25: servers always, dedicated desktops opt-in, laptops opt-in and idle only (docs/phase13-shared-gpus.md) | nothing |
| F7 | Phase 13 slice 3 before 4, or 4 before 3 | settled 2026-10-29: 3 first (the owner started slice 3 on the spec's recommendations) | D4 |
| F8 | Pricing and editions | decided 2026-11-03: the terms of docs/phase9-editions.md §10 stand (Professional per machine per year, Enterprise per fleet per year, free personal use on 3 machines, commercial code in separate repositories); price points are set before E4's commerce slice; E4 starts after Phase 13's D7 and G5b | E4 |

## H. Housekeeping

| # | Task | Status | Notes |
|---|---|---|---|
| H1 | Proxmox host memory: balloon floors on the other VMs, KSM check | with the owner | commands given 2026-10-23; the dev VM has its cap and floor |
| H2 | Cloudflare transform rule for download.maluos.com | with the owner | from the Phase 10 release work |
| H3 | packages/maluos-meta/debian/docs/claude-log/ out of the repo | done | A8 |
| H4 | Lintian back on in the local package build (SKIP_LINTIAN=1 since slice 7 because of maludb-os-core's node_modules) | done 2026-11-01: lintian runs on the current version of every package but maludb-os-core (34 s, 150 MB); the installer's two intentional errors overridden (0.3.3), the agent changelog fixed; the warnings (no-manual-page, maintainer-script-calls-systemctl) stay | |
| H5 | Memory notes and docs kept current after each release | ongoing | |
