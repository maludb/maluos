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
| G4 | Phase 13 slice 3 proper: `inference` facts in the heartbeat, `endpoints.inference` to desks, backends from the directory, the envelope on remote requests, admission control estate-wide, desk contribution opt-in | D1, D2 | the directory replaces pairing by hand inside the estate | L |
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
