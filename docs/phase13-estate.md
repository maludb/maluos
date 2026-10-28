# Phase 13: the estate (servers, desks and agents as one network)

Planned 2026-10-23, from the owner's vision and a brainstorming note on
"MaluOS Fabric". Nothing here is built; the sections say what exists to
build on, what is decided, and the slices in the order that gives a
working product at each step.

## The vision

A company runs one or more MaluOS servers in its data centre: the
databases, the shared memory, the application servers (the Business OS
kernel and its applications). Its system managers run MaluOS Desktop:
their desks see the servers' operations and run agents locally. The
servers and desks form one trusted network in which agents, knowledge,
model inference and work itself are shared, with ownership, policy and
audit kept where they are today.

Three things make that different from computers that share files and
databases:

- **Shared intelligence.** Knowledge is found and used across machines
  without unrestricted data sharing: an agent gets the fact it is
  entitled to, with its source, confidence, time and scope, not the
  record it came from.
- **Shared capability.** Agents find and delegate work to specialists
  anywhere in the estate, each specialist acting with its own authority
  inside its own system; the coordinator needs no credentials to those
  systems.
- **Shared computation.** Inference and long background work are placed
  on authorised hardware that has capacity: a GPU server, an idle desk
  that opted in, an approved cloud model as the fallback.

The product line, once it holds: *an operating system where people,
agents, knowledge and computing resources work together across a whole
network.*

## What exists to build on

The estate is a networking layer over what Phases 4 to 12 already made,
not a second agent framework. Each row is a piece the slices below
extend rather than replace.

| Piece | Where | What it already does |
|---|---|---|
| The office and the desk | docs/desk-enrolment.md, maluos-desk, maludb-os-core (the desk is a location kind in the kernel's estate, with an owner, a token, presence) | a desk joins an office with a one-time code, holds its desk token in the vault, heartbeats, and receives the office's endpoints (`records`, `activity`, `memory`, `actions`, `models`); the kernel has Settings → Desks and the presence sweep |
| Agents as system entities | docs/agents.md, maluos-agent | an agent is a Linux user, a principal, a compartment, a policy and a unit; scopes (`agent:NAME`, `dept:N`, `org`) are already the three memory classes below |
| The gateway | docs/phase6-*.md, maluos-gateway | ladders, backends, tiers, budgets, the ledger, a TCP listener with bearer tokens; the office's model endpoint is already a backend on an enrolled desk; multi-host scheduling was deferred as "later" in the Phase 6 plan |
| The vault | maluos-vault | peer-credential identity, grants, delegation with budget and expiry, the use-only level agents get for keys |
| Memory | maludb-core, the MC2DB listener | principals, scopes, claims with confidence, graph relations, event history; the `memory` endpoint in the enrolment contract is the hook for remote queries (null today) |
| The kernel | maludb-os-core (vendored), docs/components.md | the organisation, Agent HR, agent messaging, applications with `maludb-os.json` manifests and MCP endpoints |
| The Desk | maluos-desktop-session | the agent-aware session: indicator, notifications, ownership, grant requests, the Desk window and its pages |
| Editions | docs/phase9-editions.md | `fleet`, `scheduler` and `sso` are named Enterprise services; the estate is where they land |

## Decisions

1. **One coordinator, many autonomous nodes.** The Business OS kernel on
   one server is the estate's control plane: identity, the agent
   directory, policy, scheduling, audit. Desks and servers work on their
   own when it is unreachable (as a desk does today) and reconcile when it
   is back. Several coordinators and regional federation come later, if
   ever; a fully decentralised control plane is not attempted.
2. **Connectivity is not permission.** Every cross-node request carries
   who originated it (person or agent), what is asked, what authority was
   delegated, the data classification and an expiry; the receiving node
   authorises it against its own vault, policy and scopes, independently
   of the sender's claims. Nothing in the estate bypasses what the vault
   and gateway enforce on one host.
3. **Servers enrol like desks.** `maluctl office enroll` becomes
   `maluctl estate join` for any MaluOS host; a node's identity is a
   machine key in its vault, the token is per node, and the contract of
   slice 6 (code, heartbeat, me, leave, endpoints) is the base for all
   node kinds. The name "estate" is the kernel's own term; "Fabric" was
   the brainstorming note's working name for the same thing.
4. **Transport: HTTPS to the coordinator; the estate's own network for
   nodes.** Desks and servers talk to the office over HTTPS and keep
   doing so. Node-to-node traffic (remote inference, memory queries,
   direct task calls) goes over a WireGuard overlay that every node gets
   when it joins, hub and spoke through the coordinator's host, because
   the people on MaluOS Desktop have no static addresses and must never
   be asked to set up a VPN (the owner, 2026-10-28; slice 1b,
   docs/phase13-slice1b-overlay.md). The overlay is reachability only:
   every service keeps its own tokens, keys and envelopes (decision 2).
   Until 2026-10-28 this read "overlay later, if needed"; the kernel's
   long-poll path of slice 2 stays as the office transport either way.
5. **A2A for agent tasks, MCP for tools.** Agents delegate work to each
   other over an A2A-compatible task interface with MaluOS's
   authorisation envelope as an extension; applications keep exposing
   tools over MCP. The two are complementary and both already have a
   place (MCP in the kernel's applications and the office endpoints).
6. **Memory: ownership and scoped queries, no multi-master.** Each fact
   has one authoritative node. Remote reads are permission-checked
   queries that return claims with provenance; selected records and
   knowledge summaries are replicated under a policy; PostgreSQL
   multi-master replication is not used.
7. **Durable work in PostgreSQL.** Events and tasks live in transactional
   outbox and task tables in the kernel's database with idempotency keys;
   a message broker (NATS JetStream is the candidate) only when a measured
   need appears.
8. **An idle machine is not a free one.** A desk contributes inference or
   work only when its owner opted in; contribution stops when interactive
   use resumes, and the owner can reserve the machine at any time.
9. **Humans approve what matters.** Approvals, budgets and high-impact
   recommendations reach the responsible person's Desk, as grant requests
   do today; independent review agents can challenge a result before it
   is presented.
10. **Edition boundary, to decide.** Phase 9 names `fleet`, `scheduler`
    and `sso` as Enterprise services. Which estate features are
    Community (a desk and a server joining, the operator's view, agent
    discovery) and which are paid (estate-wide scheduling, SSO, many
    coordinators) is the owner's call before slice 3 ships.

## Slices

Each slice is a product on its own; each later one reuses the earlier.

### Slice 1: nodes and the operator's view

Specified in docs/phase13-slice1-nodes.md (2026-10-23): the estate
endpoints, the report, the health rules, the kernel half, the packages
and the test.
**The host half built 2026-10-27** against the mock estate (maluos-estate
0.1.0 and the packages around it; docs/phase13-slice1-nodes.md, Status);
the kernel half waits for the owner's approval.

- `maluctl estate join URL --code CODE` on servers and desks (the desk
  path keeps its `office` alias); node kinds `desk`, `server`,
  `inference`; a machine key per node in the vault; presence and facts by
  heartbeat; `maluctl estate status|nodes|leave`. The kernel's estate
  gains the node kinds, node tokens and a node directory.
- Servers report what an operator needs: units up or down, agents and
  their state, gateway backends and queue depth, vault alerts, pending
  updates and restart needs, disk and memory, the last heartbeat. The
  reporting is the host's own `maluctl` status calls, sent with the
  heartbeat, so nothing new is computed.
- **The Estate page on the Desk**, for people whose kernel role allows
  it (system managers): every node, its health, its agents, the alerts
  across the estate, read-only, with notifications for a node going
  offline or an alert being raised. Actions on remote nodes (restart an
  agent, apply updates) come in slice 2 with the delegation envelope.
- Test: the mock office grows node kinds; the boot test enrols a server
  and a desk, the desk's Estate page lists both, a stopped agent on the
  server shows on the desk within a heartbeat.

### Slice 1b: the overlay

Specified in docs/phase13-slice1b-overlay.md (2026-10-28): WireGuard,
hub and spoke through the coordinator's host, the tunnel made by `join`
and `enroll` with the key in the vault, an address and a name
(`NAME.internal`) per node from the kernel, `maluctl gateway expose
--bind overlay`, the kernel half beside db/188. A desk at home reaches
the office's GPU server by name; nothing is asked of the person.

### Slice 2: the agent directory and delegation

Specified in docs/phase13-slice2-delegation.md (2026-10-23): the
envelope, the directory, the inbox, the personal agent, remote
actions, the kernel half and the test.

- Every agent made with `maluctl agent create` registers in the kernel's
  Agent HR with its capabilities (declared in the agent's manifest),
  location, owner, scopes, models it may use, availability and resource
  needs; the directory is queried by capability, not by host.
- An A2A-compatible task endpoint on every node (`maluos-agent` serves
  it for its agents; the kernel routes by directory), with the
  authorisation envelope of decision 2; the receiving node checks the
  originator's authority in its own vault and policy. Results carry
  their provenance and the ledger rows they caused.
- The desk's personal agent as the person's representative: it sends
  work to office agents and receives requests for assistance or approval,
  which appear on the Desk (the grant-request path, generalised to tasks).
- The Agents app (Phase 12 slice 8) is the person's window on all of
  this: the same task interface for a local agent over the socket and a
  remote one through the office; the directory feeds its list and the
  agent icons.
- Operator actions on remote nodes from the Estate page, through the
  same envelope.
- Test: a desk agent finds a Help Desk agent by capability on the office
  server, delegates a task, the answer comes back with its provenance;
  a task from a principal without the authority is refused by the server,
  not by the desk.

### Slice 3: shared inference

- The gateway's deferred multi-host scheduling: a node's gateway is a
  backend for other nodes, registered through the directory with its
  models, capacity and policy; the office model endpoint of slice 6 is
  the first instance of this. Requests carry quality, privacy class,
  deadline and budget; the scheduler picks an authorised backend with
  capacity: the desk itself, an office GPU server, a remote inference
  node, an approved cloud model as escalation or fallback.
- Admission control estate-wide, backpressure per host, priorities;
  desk contribution opt-in with the interactive-use rule of decision 8.
- Test: three machines (below); a desk request served by the inference
  node's model, shown in both ledgers with the same request id; the desk
  stops accepting remote work when its owner is active.

### Slice 4: federated memory

- Three memory classes on the existing scopes: personal (the home scope),
  departmental (`dept:N`), enterprise (`org`). The `memory` endpoint of
  the enrolment contract becomes real: permission-checked remote queries
  to the authoritative node through the MC2DB listener, answered as
  claims with source, confidence, timestamp and scope, never as records.
- Selective replication: knowledge summaries and chosen records copied
  to nodes under a policy with provenance kept; conflict is impossible
  because ownership is single.
- Test: an HR fact on server A (an employee's training) answers a
  scheduling agent's qualification query on server B as one claim, and
  the agent cannot read the rest of the record.

### Slice 5: events and durable work

- The kernel's applications publish events to an outbox table; an event
  router (in the kernel) decides which agents respond; every consumer is
  idempotent on the event id.
- A distributed work queue for long tasks: assignment to a suitable node,
  checkpoints for portable tasks so another worker can resume, retention
  of node-bound tasks until the node returns. Queued work migrates;
  running agents do not.
- Test: the recurring-customer-issue scenario below runs end to end on
  the three machines with one node taken offline mid-task.

### Slice 6: skills, resilience, federation between estates

- Versioned skills published to the estate after review and tests, with
  rollback; no agent changes a peer's instructions on its own.
- Many coordinators, a second hub for the overlay of slice 1b.
- Narrow, contractual interactions between two estates (a purchasing
  agent and a supplier's inventory agent) with their own identity,
  authorisation, residency and liability questions; not before the
  single-estate network is secure and boring.

## The proof: three machines

One office server (the kernel, the applications, memory), one desk, one
inference server with a GPU. Success is one scenario:

1. A person on the desk describes a recurring customer problem to their
   personal agent, which assembles the permitted context.
2. The agent finds the Help Desk agent on the office server by
   capability and delegates the investigation.
3. The Help Desk agent searches prior tickets and memory, asks a
   technical agent on the server for a diagnosis, and that agent's code
   analysis is served by the inference server's model.
4. A remediation task is created in Projects and linked to the case; the
   proposed change reaches the responsible person's Desk for approval.
5. The approved outcome reaches each authorised system; the whole
   interaction is in the audit trail with provenance, ledger rows on
   every node, and the diagnostic knowledge kept in memory.

That exercises node identity, discovery, delegation, shared inference,
scoped memory, approval and audit on three machines, which validates the
architecture without a cluster.

## Open questions for the owner

- The edition boundary (decision 10).
- Whether desks ever contribute inference by default (off, per
  decision 8) or only on servers.
- The coordinator's availability: one kernel today; what the estate does
  during a kernel upgrade (nodes keep working; the directory is stale).
- The order of slices 3 and 4: the brainstorming note would start with
  discovery, delegation and memory and extend the gateway in parallel;
  this plan puts inference before memory because the office model
  endpoint already exists and the gateway's deferred work is well
  specified. Either order works.
