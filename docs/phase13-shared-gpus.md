# Phase 13, shared GPUs: brainstorm (2026-10-25)

A brainstorming note, decided with the owner the same day, from the ask of 2026-10-25: register a GPU
(a DGX Spark, an RTX box) that sits on a networked MaluOS device so that
anyone on the same network can run inference on it through an API with a
queue, managed as the Sovereign LLM Manager manages a fleet; and give the
system manager tabs for GPUs, the MaluOS network and the queue. Nothing
here is built or decided; the recommendations are marked.

## What already exists, and where it overlaps

Three designs in the estate describe "a queue in front of a machine that
runs models". They were written for different machines and overlap.

| Design | Where | State | Machine it assumes |
|---|---|---|---|
| maluos-gateway (Phase 6) | packages/maluos-gateway, docs/phase6-*.md | built, shipped since 26.04.20261019 | a MaluOS host with Ollama; vault principals, classes, affinity, expected wait, PostgreSQL ledger, a TCP listener on 11435 (off by default, loopback) |
| maluos-local-llm-server | github.com/maludb/maluos-local-llm-server, docs/server-design.md | approved 2026-10-17; scheduler, store, keys and a fake backend exist, no HTTP faces yet | a non-MaluOS machine (the Mac Mini M4): SQLite, inference keys, lanes local/cloud, sync and async, OpenAI and Anthropic faces, the node API `/node/v1` on 11435 |
| Sovereign LLM Manager | github.com/maludb/maludb-os-sovereign-llm-manager | Phase 0 (schema, agents, skills); no feature PHP | a Business OS application that pulls every node's `/node/v1` and never serves an inference |
| Phase 13 slice 3, shared inference | docs/phase13-estate.md | planned, nothing specified | a node's gateway as a backend for other nodes, registered through the kernel's directory |

The overlap is real: the gateway and the node service both own a queue,
a scheduler, keys or tokens, a run history and a model catalogue, and
both chose port 11435. The manager was designed against the node
service's API only, so today a MaluOS GPU server cannot be managed by it.

**Recommendation 1: one node API, two implementations.** Lift §6 of the
server design out as *the MaluOS inference node API, surface 1*
(docs/inference-node-api.md) and have both the gateway and the node
service implement it. The gateway is the implementation on MaluOS
(already vault-bound and ledgered in PostgreSQL); the node service is
the implementation on everything else (macOS, DGX OS, a bare Linux box).
The manager then manages both with one worker. The gateway gains what the
node service has and it lacks: the Anthropic face, async jobs with a job
id, `since_seq` on runs and models, SSE events, and inference keys for
callers who are not Linux users of the host (the gateway's bearer tokens
already are these, issued per principal; they need names, limits and
`cloud_allowed` as the key record of the server design §2 has). The node
service is not rewritten; it stays the lightweight sibling.

**A fact that decides the DGX case (confirmed by the owner 2026-10-25).**
The DGX Spark is arm64 (Grace Blackwell, DGX OS). MaluOS has no arm64
build (roadmap E6, an idea), so a DGX Spark joins the network as a
non-MaluOS node running the node service, not as a MaluOS device. **If
MaluOS on the GPU machine is a requirement, the purchase is an RTX card
in an x86 box**, and that box needs the NVIDIA driver, which no seed
carries today: a `nvidia` component in the components catalogue (Phase 7,
docs/components.md) is part of this work.

## Registering a GPU to the network

"Register" has two layers, and both are wanted.

1. **Pairing by hand, no coordinator.** A GPU host exposes its gateway on
   the LAN and issues a token; a desk adds it as a backend by URL and
   token. This is the manager's D12 ("register by URL + the node key
   pasted once") and it works on a home or lab network with no kernel.
   ```
   # on the GPU host
   sudo maluctl gateway expose --bind 0.0.0.0        # tcp.enabled, keys required, refuses to start without one
   sudo maluctl gateway key issue --name ed-desk --class interactive --cloud-allowed=false
   # on a desk
   sudo maluctl gateway backend add gpu-1 https://gpu-1.lan:11435 --key …
   ```
   After that nothing changes for callers on the desk: every call still
   goes through the desk's own gateway socket, which now has a second
   backend and routes to it by policy, class and expected wait. The
   remote node is one more backend kind (`remote`) beside `ollama-local`
   and the cloud providers; the ledger on both ends carries the same
   request id, which is already slice 3's test.
2. **The directory, through the estate.** A node's heartbeat (slice 1's
   report) carries `gpus` and `inference` facts; the kernel's node
   directory lists what each node serves; a desk's `me` and heartbeat
   answers carry `endpoints.inference`, and its gateway adds those
   backends itself, with the node token as the credential and the
   delegation envelope of slice 2 as the authorisation. Pairing by hand
   remains for nodes outside the estate (the Mac, the DGX).

The facts to carry, in the join request and every heartbeat:

```json
"gpus": [{"vendor": "nvidia", "model": "RTX 5090", "vram_mb": 32768, "driver": "580.65",
          "compute": "12.0", "busy_pct": 37, "vram_used_mb": 21000, "temp_c": 61}],
"inference": {"api": "node/v1", "url": "https://gpu-1.lan:11435", "models": ["qwen3:32b", "fast", "strong"],
              "lanes": {"local": {"capacity": 1, "running": 1, "queued": 3, "expected_wait_ms": 42000},
                        "cloud": {"capacity": null, "running": 0, "queued": 0}},
              "shared": true, "contribution": "always"}
```

`shared` is the owner's opt-in (decision 8 of the phase plan: an idle
machine is not a free one). `contribution` follows the machine's chassis
(the owner's rule, 2026-10-25): a **server** shares always and needs no
opt-in; a **dedicated desktop** (an RTX workstation) is opt-in and, once
opted in, shares always; a **laptop** is opt-in and shares only while
idle (no session input for the idle threshold, on mains power), stopping
when its owner returns. The chassis comes from `hostnamectl chassis`
(DMI), overridable in gateway.yaml. The
scheduler on the calling side picks by: policy (may this principal's
data leave the host; `cloud_allowed` stays separate from `remote_allowed`,
a LAN node is not the cloud), the model requested, expected wait, and the
caller's class and max wait, exactly as it picks between local and cloud
today.

**Reading the GPU on MaluOS.** NVIDIA through NVML (`nvidia-smi
--query-gpu=…,--format=csv,noheader` is enough for a first version; the
`pynvml` module when the driver component ships it), AMD and Intel through
`/sys/class/drm/card*/device` (`gpu_busy_percent`, `mem_info_vram_used`),
a Mac or DGX through the node service's `/status` machine block. One
reader, `maluctl gpu status --json` in maluos-tools, used by the session's
host state, the estate report and the GPUs page. A host with no GPU
answers an empty list and the gateway marks itself cloud-only, which the
Phase 6 degradation rules already handle.

**Not "object storage".** The owner's ask said object storage; the
owner has larger plans there and asked that this round stay on the GPU
alone. The registry here is the kernel's node directory; nothing about
storage is designed in this note.

**Authorisation stays the estate's rule.** Connectivity is not permission
(decision 2): a request to a remote node carries the originating
principal, the delegated authority, the data class and an expiry, and the
receiving gateway checks it against its own policy and vault before
queueing. The remote node's ledger names the originating principal and
the sending node, so `maluctl gateway usage` on the GPU host can say who
used it.

## Where the tabs go

"System Manager" in the dock is GNOME's gnome-system-monitor
(seeds/desktop.seed, maluos-meta Depends), unmodified: Processes,
Resources and File Systems are its own, written in C++ against GTK 4,
with no plugin interface. Adding GPUs, MaluOS Network and Queue to it
means forking a GNOME application and rebasing it at every GNOME release,
for three pages whose data is estate-wide while its own three are
host-only. Three placements were weighed.

| Placement | For | Against |
|---|---|---|
| Fork gnome-system-monitor, add three tabs | one window, as asked | a C++ fork to carry across GNOME releases; its pages are local, ours are the estate's; we would own a processes view we did not want |
| Pages in the Desk window (com.maluos.Desk: Agents, Models, Vault, Alerts; Estate planned in slice 1) | already ours, already on the D-Bus state, already gated by role for the Estate page | the Desk is every person's window on *their* agents and vault; operator views would crowd it and most desks have no right to them |
| A MaluOS System Manager window of our own (`com.maluos.SystemManager`), built from the Desk's code | the audience is the system manager (slice 1 decision 6 already gates the Estate page by that role); the dock entry appears only when the role does; the Desk stays personal | a second window to maintain (small: the same state, pages and widgets as the Desk) |

**Decided by the owner 2026-10-25: the fork.** MaluOS carries its own
gnome-system-monitor (49.1 on 26.04) with the three tabs added, as it
carries its other patched sources under vendor/ (apple-t2, maludb). To
keep the patch small and rebaseable, the tabs hold no logic: each is a
GTK 4 widget in the fork's C++ that renders JSON it reads over D-Bus
from the session's state (the same state the Desk window reads) and
calls `maluctl` for actions; every number is computed in Python outside
the fork, so a GNOME rebase touches layout only. The source package is
`maluos-system-monitor` (binary name kept so the seed and the dock entry
need no change, with Conflicts/Replaces on Ubuntu's), the tabs behind a
build option so the patch can be offered upstream later. The Desk's
Models page keeps the *person's* view of the queue ("why is my call
waiting"); the forked monitor has the *operator's* view, and the three
tabs are hidden unless the host has a gateway or the office grants the
system-manager role.

- **GPUs**: this host's GPUs live (utilisation, VRAM, temperature, loaded
  models, the lane gauges), the sharing switch and the contribution rule
  for its chassis, and below it every GPU of the estate with its node and
  health. Local reads need no office; the estate part appears when
  `endpoints.estate` does.
- **MaluOS Network**: the Estate page of slice 1 under the owner's name
  for it: nodes, kinds, health, agents, alerts, what each serves;
  operator actions when slice 2 lands. One page, not two; the roadmap row
  D1 is renamed, not duplicated.
- **Queue**: this host's gateway queue (every principal, every class,
  with cancel and re-prioritise, which `maluctl gateway` lacks today and
  the node API has) and, when the directory exists, the estate's queues
  from the kernel's `nodes_status` snapshot. Deep history, usage by
  period, keys and policies stay in the Sovereign LLM Manager; the page
  links there ("Open in Sovereign LLM Manager") instead of repeating it.

The split with the Sovereign LLM Manager is the same as the Desk's split
with the kernel: the Business OS application is the every-browser,
agent-equipped manager with history; the desktop window is the live view
at the system manager's desk and reads what the kernel already serves.

## Slices, in an order that gives a product at each step

| # | Slice | Needs | Gives | Effort |
|---|---|---|---|---|
| G1 | GPU facts: `maluctl gpu status`, the `nvidia` component, `gpus` in the session's host state and in the slice 1 report; the fork of gnome-system-monitor with the GPUs tab (local half) | nothing | a MaluOS box with an RTX card shows its GPU in System Manager; the gateway reports it | M for the facts, M for the first fork |
| G2 | The node API on the gateway: `/node/v1` status, health, queue (with cancel, priority, pause), runs with `since_seq`, models, keys; async jobs; the Anthropic face; `maluctl gateway expose` and `key issue`; the `remote` backend kind and `backend add` on a desk | G1 for the facts, else nothing | pairing by hand: any MaluOS desk uses any MaluOS GPU host on the LAN; the Sovereign LLM Manager can register a MaluOS node | L |
| G3 | The node service's faces (the server design §10) so the Mac and the DGX Spark speak the same API | nothing (separate repository) | the non-MaluOS nodes join the same fleet | L, the owner's other repository |
| G4 | Phase 13 slice 3 proper: `inference` facts in the heartbeat, `endpoints.inference` to desks, backends from the directory, the envelope on remote requests, admission control estate-wide, desk contribution opt-in | D1, D2 | the directory replaces pairing by hand inside the estate; **built 2026-10-29, boot-tested 2026-10-30** as docs/phase13-slice3-inference.md (its Status section): the idle rule measured by the session service, placement under the `scheduler` entitlement | L |
| G5 | The MaluOS Network and Queue tabs in the fork: the local queue with cancel and priority (G2), the Estate page's data (D1), the estate's queue snapshot and operator actions (D2) | G2 for the local half; D1, D2 for the estate half | the three tabs as asked | M |

**Editions (the owner, 2026-10-25): Community first.** G1, G2, G3 and
G5's local half are Community: a GPU box shared on the LAN by pairing,
visible and operable in System Manager. G4, the directory with
estate-wide admission, is the paid `scheduler` of Phase 9 in a later
release; this settles roadmap decision F5 for inference. G1 and G2 need
no kernel change; they are the natural next things to build in this
repository once the Phase 11 switch is done.

## Decisions

Answered by the owner 2026-10-25 unless marked open.

1. **One node API: decided, option A.** The MaluOS gateway implements
   the management API the local LLM server was designed with (`/node/v1`:
   status, queue, runs, models, keys) and gains the Anthropic face, async
   jobs and named keys; the node service stays the implementation for
   non-MaluOS machines (the Mac, the DGX Spark). Two codebases, one API,
   one manager; a MaluOS box's runs stay in the vault-scoped ledger with
   real principals. The API is lifted out of the server design's §6 into
   docs/inference-node-api.md as surface 1 before G2 starts.
2. **The window: the fork** of gnome-system-monitor, with the tabs kept
   logic-free so the patch rebases.
3. **Editions: Community first**, the paid `scheduler` in a future
   release.
4. **Object storage: skipped** for this round; GPUs only.
5. **Contribution: servers always; dedicated desktops opt-in; laptops
   opt-in and only while idle.**

## Status

**G1 built 2026-10-25** (packages, unit tests and the local self-test pass
on the dev host; both profiles' images rebuilt and their UEFI boot tests
passed the same day, after a fix to the fork's self-test, 49.1+maluos.2,
whose deadline fired while the first paint held the main loop under TCG):

- maluos-firstboot 0.1.10: `/usr/lib/maluos/maluos_gpu.py` (NVIDIA through
  nvidia-smi with a retry for an older binary without `compute_cap`; AMD and
  Intel through /sys/class/drm with amdgpu's busy, VRAM, temperature and
  power; virtual display adapters skipped; the chassis from `hostnamectl
  chassis`, else systemd-detect-virt, else the DMI enclosure type; the
  sharing rule by chassis; the switch's resolution in `share_state`) and
  `maluctl gpu status [--json]`.
- maluos-gateway 0.3.5: gateway.yaml `share:` (enabled, contribution),
  `maluctl gateway share [status|on|off] [--when always|idle]` (root for
  the switch; the status for anyone), `share` in `/v1/maluos/status`. The
  sharing itself, the node API and `expose` are G2.
- maluos-session 0.7.1: `host.gpus`, `host.chassis`,
  `host.contribution_rule` and `gateway.share` in the session state.
- maluos-system-monitor 49.1+maluos.1: GNOME System Monitor 49.1 with the
  GPUs tab (packages/maluos-system-monitor, README.maluos.md lists the
  patch surface: two new source files, the page in interface.ui, one icon,
  marked hunks in interface.cpp, application.*, argv.*, meson and
  POTFILES). The tab polls the session service every 2 s while current,
  renders this computer's GPUs (model, driver, VRAM used of total,
  temperature, power, compute capability, a load bar), the sharing switch
  with the chassis rule, the contribution, the models loaded and the queue
  from the gateway, and the office row; it appears only when the session
  service answers, so on a plain GNOME desktop the application is upstream's.
  `--show-gpus-tab`, `--maluos-self-test`, Alt+4. Replaces Ubuntu's
  gnome-system-monitor in seeds/desktop.seed.
- The `nvidia` component (seeds/nvidia.seed, docs/components.md): the
  signed modules for the generic kernel, driver 595 with 580 as the
  alternative, nvidia-smi, nvtop; off the medium.
- Tests: tests/gpu-test.py (the reader's pure parts, the plugin, the share
  resolution), tests/system-monitor-local-test.sh (the self-test under Xvfb
  against tests/lib/fake_session.py: two GPUs, no GPU, no session), both in
  CI; tests/qcow2-boot-test.sh reads the GPU facts on both profiles and
  runs the fork's self-test on the desktop's live session.
- Not in G1: the MaluOS Network and Queue tabs (G5), any sharing (G2), the
  estate report's `gpus` (with D1, which is not built), translations of the
  tab's strings, the laptop idle detection (G4 decides what "idle" means:
  no session input for a threshold, on mains power).

**G2 built 2026-10-25** (docs/inference-node-api.md is surface 1; the
gateway's local test covers every route; both profiles' images were rebuilt
and their UEFI boot tests passed on 2026-10-26, checking keys, the node API
and `expose`; the first pass failed only on three timing waits in older
sections of the test, which now poll, and the Agents app's self-test
deadline, now 240 s in maluos-agents 0.2.1):

- maluos-gateway 0.4.0: the node API `/node/v1` (status with the machine,
  the GPUs and the lanes; health; the queue with cancel, priority and
  pause/resume per lane; runs from the ledger with `since_seq`; models with
  a catalogue sequence; keys), opened by a node key or an operator on the
  socket (root, or one of the estate's operators: the human accounts the
  provisioning state lists, since gateway 0.4.2). Keys are principals: `key:<name>`, a principal policy (class,
  cloud, remote, tiers) and a token of kind `inference` or `node`, minted by
  `maluctl gateway key issue` or `POST /node/v1/keys`, shown once. Async
  jobs on every face (`X-Node-Mode: async` or the body object `node`,
  202 with a job id, `/v1/jobs`). The Anthropic Messages face
  (`/v1/messages`, the event stream, tools, errors in Anthropic's shape).
  The node headers on every answer. The `remote` backend kind (a paired
  MaluOS host, its pairing key in the vault as `system/remote-<name>` for
  the gateway's own principal `user:maluos-gateway`, `remote_allowed` in
  the policy, the sensitivity gate, no forwarding chains, both ledgers
  joined by the call ids). `maluctl gateway backend add NAME URL --key`,
  `expose|unexpose` (the TCP listener applied live on reload, refused
  without a key), `node status|queue|runs|models|cancel|priority|pause|
  resume`, `jobs`. The sharing switch is enforced on the serving side: with
  share off an inference key's call over the network is refused
  `not_shared`.
- Not in G2: the node events stream, `/usage`, `/settings`, a job's event
  replay, webhooks, idempotency keys, `max_wait` turning sync into async
  (all listed as later in the API document); the laptop idle detection
  (G4); the estate's directory replacing pairing by hand (G4); the node
  service's side of the same API (G3, the other repository).

**G5, the local half, built 2026-10-26** (the fork's local test and the
gateway's local test pass on the dev host; both profiles' images were
rebuilt with gateway 0.4.2 and their UEFI boot tests passed on
2026-10-27, the three tabs on the live desktop session included):

- maluos-system-monitor 49.1+maluos.3: the **MaluOS Network** tab (This
  Node: name and id, the listener, sharing, the manager's last call, the
  lanes, the keys issued; Paired Nodes: the gateway's remote backends with
  their health and models; Estate: the office, with the directory's nodes
  to follow in D1) and the **Queue** tab (Lanes: every backend with its
  running and queued counts, the oldest wait, the resident model, the
  per-class waits, Pause/Resume; Queue: every queued or running call of
  every principal with its principal, key, face, mode and kind, its wait
  or run time, the class as a drop-down that moves a queued call, Cancel;
  "Open in Sovereign LLM Manager" when the desk is enrolled). Alt+5 and
  Alt+6, `--show-network-tab`, `--show-queue-tab`. One session client
  (maluos-session.cpp) now serves the three tabs: GetState every 2 s while
  a tab that draws the state is current, NodeQueue every 2 s while the
  Queue tab is; the GPUs tab was rewritten on it. The actions run `maluctl
  gateway node pause|resume|cancel|priority` as the user and show the
  outcome as a toast; a user who is not an operator of the gateway sees
  the GPUs tab as before and a note on the other two.
- maluos-session 0.8.0: `node` in the state (/node/v1/status and
  /node/v1/keys as the session user, when an operator: this node, the
  lanes, the paired nodes, the keys), `NodeQueue()` live over the bus.
- maluos-gateway 0.4.1: GET /node/v1/queue answers the lanes too.
- Tests: tests/system-monitor-local-test.sh (the self-test now prints the
  three tabs' summaries; a node with a paired host and three jobs, an
  empty queue on a VM, a user who is not an operator, no session);
  tests/gateway-local-test.sh (the lanes in the queue answer); the image
  boot test reads the node in the session state, NodeQueue over the bus,
  pause and resume through maluctl as the tab does, and the three
  summaries of the self-test on the live desktop session.
- The first image chain (2026-10-26) failed the five G5 checks on the
  desktop: the gateway counted only uid 0 on its socket as an operator, so
  the session service, which reads the node API as the login user, got
  403 and the tabs said "not an operator". maluos-gateway 0.4.2 counts the
  estate's operators too (the provisioning state's list, the accounts
  firstboot makes database superusers), re-read on reload; the local test
  covers the switch.
- Not in G5's local half: the estate half of both tabs (the Estate page's
  data, D1; the estate's queue snapshot and operator actions, D2), the
  `move` route, translations of the tabs' strings, a pairing dialog (the
  pairing stays `maluctl gateway backend add`).

**G5b, the estate half, planned 2026-11-03** (roadmap row G5b; scheduled
after the three-machine proof, D7, since every dependency is built: D1
filled the Network tab's Estate group on 2026-10-27, D2 built the
operator actions on 2026-10-28, D3 the estate's inference contract on
2026-10-30):

- The Estate group's node actions. A node row gets a menu with the five
  actions of slice 2 (restart, start or stop an agent, apply updates,
  reboot) that runs `maluctl office estate action NODE ACTION [AGENT]` as
  the user, the way the Queue tab's actions run `maluctl gateway node …`;
  the outcome arrives with a later heartbeat, so the tab shows "sent" at
  once and the result as a toast when the office reports it. The node
  decides what it allows (`actions.allow` in estate.yaml); a refused
  action is shown as refused, not retried. The menu appears only for an
  operator of the office.
- The estate's inference backends in the Network tab. The Estate group
  gains the contract's view of every backend in the estate (node, models,
  queue depth, expected wait, ceiling, shares-while-idle), from
  `GET /api/v1/estate/inference` as `maluctl office estate inference`
  prints it; the Paired Nodes group keeps the directory's rungs as this
  gateway sees them (slice 3), so the two agree or show why they do not.
- An Estate section in the Queue tab. Below the local lanes and calls: one
  row per node with its lanes, running and queued counts and
  `expected_wait_s`, from the kernel's queue snapshot (each node's queue
  rides the heartbeat every 60 s). With the `scheduler` entitlement the
  section is live and names the placement rules in force; without it the
  section shows the last snapshot with its age. The rules themselves are
  edited on the Estate page ("Open in Sovereign LLM Manager"), not here.
- The session service carries both: `office.estate.inference` and
  `office.estate.queue` in the state, read as the session user and
  refreshed with the other office data, so the fork stays logic-free
  (README.maluos.md's rule) and a GNOME rebase touches layout only.
- Tests: tests/lib/fake_session.py `--estate` gains the inference
  backends and the queue snapshot; the self-test summary names them
  ("Estate: N nodes, B backends, Q queued"); tests/system-monitor-local-test.sh
  runs an action against the fake service and checks the "sent" state;
  the image boot test runs the action against the mock office (its
  `POST /api/v1/estate/nodes/ID/actions`, the route slice 2's step 6
  already exercises, so the result is `ok` for restart_agent and
  `not_allowed` for reboot) and reads the two sections on the live desktop.
- Not in G5b: the `move` route, a pairing dialog (the pairing stays
  `maluctl gateway backend add` and the directory), translations of the
  tabs' strings, editing the scheduler's rules (the Estate page's).

**G5b built 2026-11-03** (the fork's local test passes on the dev host, eight
checks; the desktop image chain with its UEFI boot test launched 14:55 UTC,
`build/logs/chain-g5b.log`):

- maluos-session 0.13.0: `office.estate.inference` in the state, the
  office's inference contract as this desk reads it (`maluctl office
  inference --all --json`: every backend of the estate for a system
  manager's desk, with its queue snapshot and expected waits from its
  last heartbeat, `allowed` for this desk, the `editions`); one answer
  serves the Network tab's Estate group and the Queue tab's Estate
  section, so the planned `office.estate.queue` is not a second key. Read
  with each heartbeat and, while a window reads the state (GetState within
  the last 30 s), every 30 s (`MALUOS_SESSION_ESTATE_WATCH`); a failed
  read keeps the last answer marked `stale`. VERSION in the service had
  stayed at 0.11.0 through 0.12.0; it now matches the package.
- maluos-system-monitor 49.1+maluos.6: the Network tab's Estate group gets
  a menu per server row for a system manager (`office.endpoints.actions`
  in the state): restart, start or stop an agent (a dialog asks the
  agent's name, prefilled from the directory), apply updates, reboot (a
  destructive confirmation); the action runs `maluctl office estate
  action NODE ACTION [AGENT] --wait 60` as the user, a toast says "sent"
  at once and the node's answer (completed, or refused with its reason)
  comes as a second toast and to the inbox. A desk's row has no menu (its
  owner runs their own machine). The group also lists the estate's
  shared GPUs: one line for the estate (shared GPUs, how many this desk
  may use, queued and running, the scheduler entitlement or each
  gateway's own ranking) and one row per backend (address, models, queue
  snapshot, waits per class, ceiling and class, priority, shares-while,
  not for this desk). The Queue tab's Estate group: one row per node that
  shares a GPU with its running and queued counts, waits and models; the
  description says live placement with the scheduler, or the last
  snapshot and its age without. The self-test line gains `Estate: N
  nodes, Q queued, R running[, scheduler]` (`no office`, `not published`);
  `MALUOS_SELF_TEST_ACTION=NODE:ACTION[:AGENT]` runs one action through
  the tab's path and prints `self-test action: …` before the summary,
  which waits for it.
- Tests: tests/lib/fake_session.py `--estate` carries the inference answer
  and the actions endpoint, `--estate-no-actions` a desk whose owner is
  not a system manager; tests/system-monitor-local-test.sh runs the action
  case against a fake `maluctl` on PATH and checks the argv the tab
  composed; the image boot test reads `office.estate.inference` after a
  heartbeat and runs `restart_agent helper` on test-node from the tab's
  path against the mock office, checking the unit restarted.
- Not built: the planned "sent" state on the row itself (the toast says
  it), the scheduler's rules by name (the kernel publishes none yet).
- The first image chain (2026-11-03 14:46, desktop UEFI): the three G5b
  checks on the live session passed in substance (`office.estate.inference`
  with server:57's queue snapshot; the self-test summary with
  `inference 1 backend (0 queued), actions` and `Estate: 1 nodes`), and
  the action ran the whole way, tab to office to node, which refused it
  `no_agent`: the test had removed the helper agent before that point,
  so the check now targets the idle `desk` agent. The slice 3 regex for
  the Network tab also needed the inserted inference part. Later checks
  of that run timed out under load (gnome-shell spinning at 140 %, the
  known frozen-shell case, with every `maluctl office` child of the
  session past its 60 s limit between 17:15 and 17:24): the session's
  inference read, which ran inline in the office loop and every 30 s
  while a window read the state, had added to the heartbeat cycle. It
  now runs in its own thread (`estate_loop`), after each successful
  heartbeat and every 60 s while watched, so the heartbeat path costs
  what it did before.
- **The second chain (2026-11-03 17:33, desktop UEFI, build/logs/chain-g5b.run2.log)
  passed 447 checks with one FAIL**, the slice 3 idle-mark race the test
  itself describes (three tries to land a call in the session's poll gap
  after the idle file is removed; the estate rung had also taken over two
  minutes to return beforehand): not G5b's, and green in the first run.
  The three G5b checks passed: `office.estate.inference` with server:57's
  queue snapshot and waits; the self-test summary `estate 2 nodes (…),
  inference 1 backend (0 queued), actions, 2 estate backends; … Estate: 1
  nodes, 0 queued, 0 running`; and `restart_agent desk on test-node`
  driven through the tab's path, completed through the mock office with
  the unit restarted on the node. The office loop's timeouts of the first
  run did not recur. G5b is boot-tested.

**G1 and G2 on real hardware, 2026-11-04** (the first day on the GPU dev
host, docs/dev-host-handoff.md §4 option 2: the host is itself a MaluOS
26.04 server install, release 26.04.20261102, with a GeForce RTX 3060
12 GB on nvidia-driver-580 via DKMS; the local development tree served on
127.0.0.1:8081 became an apt source with the dev key, maluos-desk 0.9.0
installed from it, the other packages already at the tree's versions):

- G1: `maluctl gpu status --json` (firstboot 0.1.13, the reader byte-identical
  to the tree's) on the card: vendor nvidia, model NVIDIA GeForce RTX 3060,
  uuid, pci 01:00.0, driver 580.178.04, vram 12288 MB, compute 8.6,
  temperature, power with its limit, `nvidia_smi: true`; chassis `desktop`
  from hostnamectl on bare metal, contribution rule `opt-in`; the gateway's
  `share status` agreed: off by the chassis rule until the owner opted in.
  With qwen3:8b resident the reader showed 5487 MB used, 53 °C and 159 W
  mid-generation, 45 °C and 41 W idle afterwards: every field is live.
- G2: `maluctl gateway ollama install` (the pinned v0.40.6 tarball,
  checksummed) and Ollama found the card (`inference compute … library=CUDA
  compute=8.6`, 11.6 GiB usable); `ollama pull qwen3:8b` and `llama3.2:3b`
  through the gateway; `share on`, `key issue --kind inference` and
  `--kind node`, `expose` (0.0.0.0:11435, keys required: 401 without one,
  `forbidden` for the node API with an inference key, the status with a
  node key). Real completions: a cold call loaded the model and answered,
  warm calls ran at roughly 55 tokens/s (835 output tokens in 15.3 s,
  qwen3's thinking tokens included); the OpenAI face over the listener with
  the inference key answered 200 with the node headers (route
  ollama-local/qwen3:8b direct, job id, lane, served model, queue wait 0).
  Four concurrent interactive calls on the capacity-1 lane: `maluctl
  gateway queue` showed one running and three queued with their waits;
  they completed in 20, 27, 36 and 43 s. The ledger carries every call
  (`usage --since 10m --by model`); `/node/v1/queue` shows the lane with
  `resident: qwen3:8b` and the per-class expected waits.
- Not done on real hardware yet: `backend add URL --key` from another desk
  and the queue positions a desk sees (the desktop image enrolled against
  the mock office with this host as the estate backend, G5b's path, or
  D7's `desk` machine); the GPUs tab's rendering of a real card (this host
  has no desktop session; the fork is not installed here).
- Two findings from the move itself, neither on the GPU: on an installed
  node the estate report's fixed unit list counts the socket-activated
  maluos-vault.service as down while it is idle (and maluos-estate.service
  before enrolment), so tests/desk-local-test.sh fails two checks here and
  a real office would grade such a node critical; and the desktop boot
  test's idle-rule checks assume the session is past the ten-minute idle
  threshold when they run, which held under TCG and not under KVM (three
  FAILs at ~2 min after login; the mark came up at 600 s and the later
  checks passed).
