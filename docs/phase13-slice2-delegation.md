# Phase 13 slice 2: the agent directory and delegation

Specified 2026-10-23 from docs/phase13-estate.md (decisions 1, 2, 5, 7,
9) on top of slice 1 (docs/phase13-slice1-nodes.md) and the task
interface of Phase 12 slice 8 (maluos_agent_tasks). Nothing here is
built. It is sequenced after slice 1 in docs/roadmap.md (D2); the
kernel half needs the owner's approval first.

## What the slice delivers

Every agent on every node is listed in the estate's directory by what it
can do. A person, or an agent acting for one, sends a task to an agent
anywhere in the estate; the request carries a signed **envelope** that
says who originated it, what authority they delegate and what the data
may touch; the node that hosts the agent decides on its own whether to
accept it; the answer comes back with its provenance. The desk's
personal agent is the person's representative in that traffic, and
questions or approvals from office agents reach the person's Desk. A
system manager restarts an agent or applies updates on a remote node
from the Estate page, through the same envelope.

```
sudo maluctl agent create helpdesk --exec … --capability helpdesk --capability tickets --accept-from org
maluctl agent policy helpdesk [set --accept-from dept:3,user:ed --max-classification internal --approve restricted]
maluctl agent send helpdesk "…"                       # local, as today
maluctl office agents [--capability helpdesk]          # the directory, from the office
maluctl office agent send helpdesk "…"                 # remote, with the envelope, as today's command
maluctl office inbox [--json] | reply ID "…" | decide ID approve|deny
maluctl office estate action NODE restart_agent helpdesk
maluos-agents                                          # the Agents app: the directory, provenance, the Policy page, "Make my personal agent"
```

## What exists to build on

| Piece | Reused as |
|---|---|
| maluos_agent_tasks (JSON-RPC over the agent's socket and over the office's HTTPS; `agent/card`, `tasks/send`, `tasks/get`, `tasks/list`) | the protocol; `tasks/send` gains an `envelope` param and the server verifies it |
| the agent's card (`capabilities` list) and `maluctl agent create` | the manifest the directory registers; `--capability` and `--accept-from` flags |
| slice 1: node tokens, node keys, `maluos-estated`, the heartbeat | the node registers its agents and pulls its inbox; the key signs envelopes |
| the vault's delegation model (use-only, budget, expiry) and the grant-request path on the Desk | the shape of delegated authority; the decision notifications |
| the gateway's sensitivity gate (`X-MaluOS-Sensitivity`: public, internal, restricted, prohibited) and ledger | the envelope's classification is applied to the agent's model calls; ledger rows carry the envelope id |
| the kernel's Agent HR (`agent_profiles`, config versions), `agent_messages` (kinds request, result, question, decision_needed, fyi, reply) | the directory's kernel side and the person's inbox |
| `GET /api/v1/desks/agents`, the Agents app's list and icons (Phase 12 slice 8) | fed by the directory |
| the mock office and the boot test | the mock estate's directory, inbox and keys; the slice's test |

## Decisions

1. **Traffic goes through the coordinator; nodes pull.** In this slice
   no node accepts an inbound connection. A task for an agent on node N
   is posted to the kernel, which stores it durably (decision 7 of the
   phase: a task table in PostgreSQL, idempotent on the envelope id) and
   hands it to N's `maluos-estated` when it long-polls its inbox. The
   result goes back the same way. Latency is a long-poll's, under a
   second when idle; no firewall rule, no overlay, no certificate on
   any node. Direct node-to-node calls come with slice 3 or the overlay,
   when a measured need appears, and change the transport, not the
   envelope.
2. **The envelope is signed by the sending node's key and verified by
   the receiving agent, not by the coordinator alone.** The kernel
   checks it too (and refuses what it can see is wrong), but the agent's
   host verifies the signature chain against the public keys it fetches
   from the coordinator's directory, checks expiry and replay, and
   applies its own accept policy. A compromised or mistaken coordinator
   can route a task; it cannot make a node accept an envelope its
   originator did not sign.
3. **Desks get a key in this slice.** Slice 1 gave servers a node key
   and desks none. A desk's envelopes need one: `office-desk-key`
   (ed25519, kind key) is made at `maluctl office enroll` and, for a
   desk enrolled before this slice, by the session on its first
   heartbeat after the upgrade, registered with
   `POST /api/v1/desks/key`. It lives in the owner's compartment beside
   the desk token, with the same grants: the personal agent signs with
   it only under the owner's delegation.
4. **Authority is a ceiling, never a credential.** The envelope carries
   what the originator *asks* the agent to work within: memory scopes, a
   classification ceiling, a budget. No secret crosses nodes; the
   specialist acts with its own vault, its own policy and its own
   budget, and the envelope can only narrow them. In this slice the
   classification is enforced (the agent's model calls during the task
   carry the envelope's sensitivity, so the gateway's egress gate holds
   the originator's ceiling), the budget is recorded and reported in the
   result's usage and enforced per task with the work queue of slice 5,
   and the scopes are recorded for slice 4's memory queries.
5. **Who may task an agent is the agent's owner's policy, on the agent's
   host.** `/etc/maluos/agents/NAME.policy.yaml`: `accept_from` (a list
   of `org`, `dept:N`, `user:LOGIN`, `agent:NAME`, `node:KIND` entries;
   the default for an agent made with `--owner` is its owner only, so
   nothing changes for today's agents), `max_classification`, and
   `approve` (classifications or originators whose tasks wait for the
   owner's approval on their Desk before they run). `maluctl agent
   policy` edits it; the Agents app's Policy page (a slice 8 placeholder)
   shows and edits it. The kernel's directory shows an agent's
   `accept_from` so a sender learns before asking.
6. **The directory is a table of its own, with a link to Agent HR.**
   `estate_agents` (node, name, principal, display name, description,
   capabilities, owner, status, accept_from, card, last_seen_at) is
   written by the node's registration; a row may be linked to an
   `agent_profiles` member when the office hires the agent into its
   organisation (the kernel's own flow, unchanged), which is what gives
   it a manager, a budget and a place in Agent HR. Capability names are
   free-form lowercase tags with a short recommended list (`chat`,
   `research`, `helpdesk`, `tickets`, `diagnosis`, `code`, `summarise`,
   `schedule`, `approve`); the query is by tag, not by host. The kernel's
   own agents (Agent HR) appear in the same answers with
   `node: coordinator`.
7. **The person's inbox is `agent_messages`.** A question, a decision
   request or a result from any agent to a person is a row of the
   kernel's existing table with the desk's owner as `to_member_id`. The
   session long-polls `GET /api/v1/desks/inbox` while online and turns
   `question` and `decision_needed` into notifications with actions, the
   grant-request path generalised (`TaskDecide(id, decision, note)` on
   the bus); `result` and `fyi` are notifications without actions.
   Replies and decisions are `POST …/inbox/ID/reply` and `…/decide`,
   signed with the desk key so the agent that asked gets an envelope
   back and the decision is attributable.
8. **The personal agent is opt-in and ordinary.** "Make my personal
   agent" in the Agents app runs `maluctl agent create me --personal`
   (polkit, as the Tools Installer): an agent owned by the person,
   capability `personal`, `accept_from` its owner only, the desk token
   and the desk key delegated to it use-only with a one-week expiry
   that the Agents app renews, a policy of `--egress internal` and a
   small budget, and the demo agent's chat loop as its first body. It
   sends tasks to office agents as the person (originator the person,
   sender the agent, both in the envelope's chain) and answers the
   person's own questions through the gateway. Nothing about it is
   special in the vault, the gateway or the directory; it is the
   phase's "representative" built from the parts that exist.
9. **Remote actions are inbox items with a node-side allow list.** A
   system manager's action from the Estate page (`restart_agent`,
   `start_agent`, `stop_agent`, `apply_updates`, `reboot`) is an
   envelope-signed request the kernel checks against the manager's role
   and queues to the node; `maluos-estated` runs it only if
   `/etc/maluos/estate.yaml` allows that action (`actions.allow`,
   default the four agent and update actions, `reboot` off), and reports
   the outcome. The node's owner decides what the estate may do to it.
10. **Provenance is in every result.** A task result carries the chain
    it travelled (each hop's principal, node, task id, timestamp), the
    node and agent that produced it, the model calls it made (the
    gateway ledger ids on that node, with model and cost), the memory
    scopes it read (slice 4 fills them) and the envelope id, so that a
    person on a desk can see where an answer came from and an auditor
    can follow it across nodes by one id.

## The envelope

Sent as the `envelope` param of `tasks/send` (and of a node action);
JSON, canonicalised for signing as sorted keys and no whitespace,
without the `sig` member.

```json
{"v": 1, "id": "env_7c1b…", "issued_at": "2026-11-12T10:02:11Z", "expires_at": "2026-11-12T10:12:11Z", "nonce": "…",
 "originator": {"principal": "user:ed", "kind": "human", "node": "desk:42", "member_id": 1},
 "sender": {"principal": "agent:me", "node": "desk:42"},
 "chain": [{"principal": "user:ed", "node": "desk:42", "ts": "…", "task_id": null},
           {"principal": "agent:me", "node": "desk:42", "ts": "…", "task_id": "t_18a2"}],
 "target": {"agent": "helpdesk", "node": "server:57"},
 "purpose": "investigate the recurring login failures reported by Acme",
 "authority": {"scopes": ["dept:3:read"], "classification": "internal", "budget": {"usd": 0.50, "calls": 20}},
 "sig": {"alg": "ed25519", "key": "desk:42", "value": "base64…"}}
```

- `originator` is the person or agent the work is for; `sender` the
  party sending this hop; `chain` every hop so far, appended by each
  sender. A hop that forwards (the Help Desk agent asking a technical
  agent) signs a new envelope with the same `id`, `originator` and
  `authority` (or a narrower one), its own `sender`, the chain extended,
  and attaches the received envelope as `parent` so the receiver can
  verify the chain end to end.
- `target` is an agent on a node, or `{"capability": "diagnosis"}` for
  the kernel to resolve against the directory (first match by
  availability and the originator's `accept_from` fit, recorded in the
  task).
- `authority.classification` is one of the gateway's sensitivities;
  `prohibited` means "local models only". `scopes` are memory scopes
  with a level; `budget` is in USD and calls.
- `expires_at` is at most one hour after `issued_at`; `nonce` is unique
  per key and remembered by each receiver for the envelope's lifetime.
- `sig.key` names the signing node (`desk:ID`, `server:ID`, or
  `coordinator`); the public keys come from `GET /api/v1/estate/keys`,
  cached by `maluos-estated` in `/run/maluos/estate/keys.json` and by
  the session for the desk.

**Verification on the receiving host**, in `maluos_agent_tasks`, before
the task is queued: the signature of this envelope and of each `parent`
against the directory's keys; `expires_at` not passed; the nonce unseen;
`sender.node` is the signing key's node; the agent's policy accepts the
originator (`accept_from`), the classification is at or below
`max_classification`, and `approve` does not apply (else the task is
parked `pending_approval` and the owner's Desk is asked through the
inbox). Refusals are JSON-RPC errors with codes `bad_signature`,
`expired`, `replay`, `not_accepted`, `classification`, `approval_needed`
in `error.data.reason`, and a ledger row on the node either way.

**During the task**: `maluos_agent_tasks` sets the envelope as the
current task context; the gateway client in the agent's process adds
`X-MaluOS-Sensitivity` from the classification and `X-MaluOS-Envelope`
with the id to every call, and the gateway writes the id on the ledger
row (`envelope_id`, a new column) so `maluctl gateway usage --envelope
ID` lists what a task cost on this node.

**The result** (the task record of slice 8, extended):

```json
{"id": "t_9f03", "state": "completed", "input": {…}, "output": {"text": "…", "artifacts": []},
 "provenance": {"envelope": "env_7c1b…", "node": "server:57", "agent": "agent:helpdesk",
                "chain": [… the envelope's chain plus this hop …],
                "models": [{"ledger_id": 88123, "model": "qwen3:8b", "backend": "local", "usd": 0.0}],
                "scopes_read": [], "started_at": "…", "done_ts": "…"},
 "usage": {"usd": 0.0, "calls": 2, "budget": {"usd": 0.50, "calls": 20}}}
```

## The directory and the inbox (contract, surface 1)

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/estate/agents` | node token | register or update this node's agents (the manifest list; the node sends the full list after each `agent create|remove` and with each report) |
| `GET /api/v1/estate/agents[?capability=X&node=N]` | node or desk token | the directory as the caller may see it |
| `GET /api/v1/estate/keys` | node or desk token | the public keys of every active node and the coordinator, with `since` for the cache |
| `POST /api/v1/estate/agents/ID/tasks` | node or desk token | JSON-RPC as slice 8; `tasks/send` needs `envelope`; the kernel stores the task and queues it to the agent's node |
| `GET /api/v1/estate/tasks/ID` | the originator's or sender's token | the task record, with provenance when done |
| `GET /api/v1/estate/inbox?wait=25` | node token | long-poll: items for this node (`task`, `action`), leased 120 s |
| `POST /api/v1/estate/inbox/ID/result` | node token | the result or refusal of an item |
| `POST /api/v1/estate/nodes/ID/actions` | desk token, role checked | a remote action with its envelope |
| `GET /api/v1/desks/agents` | desk token | as slice 8, now the directory's view for this desk |
| `GET /api/v1/desks/inbox?wait=25` | desk token | the owner's `agent_messages` (unread), long-poll |
| `POST /api/v1/desks/inbox/ID/reply`, `…/decide` | desk token | the reply or decision, with the desk's envelope |
| `POST /api/v1/desks/key` | desk token | register the desk's public key (decision 3) |

`maluctl office agent send` (slice 8) keeps its name and gains the
envelope (signed with the desk key as the owner, originator the owner);
`maluctl agent send` on the same host stays envelope-free over the
socket (peer credentials are the identity there, as today), and a local
send to an agent whose policy names `accept_from` still passes for the
owner and root.

The node registers its agents from `/etc/maluos/agents/*.manifest.yaml`
(written by `create`: name, display, description, capabilities, owner,
accept_from, tasks yes/no) and refreshes the card from the socket when
the agent is running.

## The kernel half (maludb-os-core), for approval

- db/189: `estate_agents` (decision 6); `estate_tasks` (id = envelope
  id + hop, node, agent, originator, envelope jsonb, state
  `queued|leased|running|completed|failed|refused`, lease_until,
  result jsonb, created_at, done_at; the idempotency key is the envelope
  id and hop); `estate_actions` (the same shape for node actions);
  `locations.public_key` gains desks; a kernel key pair for the
  coordinator's own envelopes.
- The endpoints above; the long-poll on a `LISTEN/NOTIFY` channel per
  node so a queued task wakes the waiting poll at once; the lease sweep
  (an item not acked in 120 s goes back to `queued`; after three leases,
  `failed: node_unresponsive`).
- The kernel's own agents answer the same `tasks/send` (the office's
  agents of slice 8 become directory entries with `node: coordinator`).
- `agent_messages` rows for a person's desk inbox and their replies;
  the role check for node actions.
- Settings → Estate: the agents tab (the directory), the tasks tab (the
  last tasks across the estate with their provenance), the actions log.
- proof `bin/test_estate_delegation.php`.

## The host half

**maluos-agent** (0.4.0): the envelope (canonicalisation, signing,
verification, nonce memory) in `maluos_agent_tasks`; the policy file
and `maluctl agent policy`; `--capability`, `--accept-from`,
`--personal` on `create`; the manifest; the task context and the two
gateway headers in `maluos_gateway_client` (the shared client the demo
agent and maluctl use); `pending_approval` tasks and their release.

**maluos-estate** (0.2.0): the inbox long-poll loop in
`maluos-estated` (one thread; items run through the local socket as
root, which the socket already allows; results posted back; the lease
acked on receipt); the keys cache; agent registration after each report
and on `agent create|remove` (a hook the agent package calls); the
`actions.allow` policy and the five actions; `maluctl estate agents`,
`tasks`, `keys`.

**maluos-desk** (0.5.0): the desk key at enrol and `office key`
registration; the envelope on `office agent send`; `office inbox`,
`reply`, `decide`; `office estate action`; the Estate page's actions
(a node row's menu: restart an agent, apply updates, with the outcome
shown when the action's result arrives); the mock office's directory,
keys, inbox, tasks and actions, with `/mock/inbox` to inject a
`decision_needed` and `/mock/task` to inject a task from a named
originator with a chosen signature (valid, tampered, expired, replayed).

**maluos-desktop-session** (0.8.0): the desk inbox long-poll thread
while online; the four notification kinds; `TaskDecide` and
`TaskReply`; `office.inbox` in the state (unread count, the last ten);
the desk key made on first heartbeat for desks enrolled before.

**maluos-agents** (0.2.0): the list from the directory with the
capability tags and the accept policy; a task's provenance behind the
answer ("from helpdesk on db-1 · 2 model calls · $0.00"); the Policy
page real (accept_from, max classification, approve); "Make my personal
agent" and its renewal; the Inbox page (the person's questions and
decisions, the same actions as the notifications).

**maluos-gateway** (0.4.0): `envelope_id` on ledger rows from the
header; `maluctl gateway usage --envelope ID`.

**maluos-meta** (0.2.8): the version bumps.

## Test (tests/qcow2-boot-test.sh, office section, after slice 1's steps)

1. `sudo maluctl agent create helper --exec … --capability chat
   --accept-from org` → the manifest exists; within a report the mock's
   directory lists `helper` on `test-node` with `capabilities: [chat]`,
   `accept_from: [org]`; `maluctl office agents --capability chat` lists
   it and `demo` does not appear (its policy is owner-only).
2. `maluctl office agent send helper "ping"` as the desk owner → the
   result's `provenance.node == "server:57"`, `provenance.agent ==
   "agent:helper"`, `provenance.models` has one ledger id, and `maluctl
   gateway usage --envelope ENV` on the node lists that row with the
   sensitivity `internal`.
3. `/mock/task` with a tampered signature → the node refuses
   `bad_signature`; expired → `expired`; the same nonce twice →
   `replay`; from originator `user:stranger` to `demo` → `not_accepted`;
   with classification `restricted` to `helper` (max `internal`) →
   `classification`. Each refusal is a ledger row on the node.
4. `maluctl agent policy helper set --approve restricted`; a
   `restricted` task from the owner parks as `pending_approval`; the
   session notifies "helper asks to run a restricted task"; `maluctl
   office inbox decide ID approve` releases it; the result arrives.
5. `/mock/inbox` injects a `decision_needed` → the session's state has
   `office.inbox.unread == 1`, the log has the notification, `maluctl
   office inbox decide ID deny --note "not now"` → the mock shows the
   decision with the desk's signature verified.
6. `maluctl office estate action test-node restart_agent helper` →
   the unit's `ActiveEnterTimestamp` changes, the action's result is
   `ok`; `… reboot` → refused `not_allowed` by the node.
7. The Agents app: `maluos-agents --self-test` reports the directory
   count and the personal agent absent; `sudo maluctl agent create me
   --personal --owner user:maluos` then `maluos-agents --agent local:me
   --self-test` reports it with the two delegations; `maluctl agent send
   me "ask helper to ping"` → `me` sends an envelope to `helper` with
   the chain `[user:maluos, agent:me]` and returns the answer with
   provenance.
8. Leave: `office leave` removes the desk key with the token; `estate
   leave` deregisters the node's agents (the directory no longer lists
   `helper`).

The three-machine proof's steps 1 to 3 (docs/phase13-estate.md) run
after this slice on real machines, without the inference server's part.

## Deferred

- Direct node-to-node calls and streaming of remote tasks: with slice 3
  (shared inference) or the overlay; the kernel's long-poll is the path
  until then.
- Per-task budget enforcement, checkpoints and retries: slice 5.
- Scopes in the envelope acted on by memory: slice 4.
- Delegating a vault secret across nodes: never, by decision 4; an agent
  that needs a credential on another node asks that node's agent.
- Capability negotiation beyond tags (schemas, examples): later, if the
  directory's tags prove too coarse.

## Effort

| Part | Size | Notes |
|---|---|---|
| the envelope, verification and task context in maluos-agent | M | the security core; written first, with unit tests of its own (`tests/envelope-test.py`) |
| the inbox loop, keys and registration in maluos-estate | M | |
| maluos-desk: desk key, send, inbox, actions, the mock estate | M | the mock is half the test |
| the session's inbox and notifications; the Agents app's four changes | M | |
| the gateway's envelope id | S | |
| the kernel half | L | separate repository, owner's approval first |

Larger than slice 1; three build-and-test rounds on the desktop image.

## Status

**Both halves built 2026-10-28**, the day the overlay (slice 1b) was
boot-tested; the kernel half awaits the owner's approval of db/190 before
it is pushed, the host half is built against the mock and the local kernel:

- The kernel half (maludb-os-core fa6e588, vendored as maludb-os-core
  2026.10.28maluos2; `docs/build-specs/estate-delegation.md` there): db/190
  (`estate_agents`, `estate_tasks` leased to a node's long-polled inbox,
  `estate_actions`, `estate_inbox`, the coordinator's ed25519 key,
  `estate_nonces`); the envelope verified in PHP (libsodium) against
  `locations.public_key` with the signer bound to the caller's token;
  the endpoints of the contract table; desks register a key at enrol or
  with `POST /api/v1/desks/key`; Settings → Desks shows the directory, the
  last tasks and the actions; proof `bin/test_estate_delegation.php` (86
  checks; it also proves the PHP and Python canonical forms agree byte
  for byte).
- The host half: maluos-estate 0.3.0 (`maluos_estate.envelope`; the daemon
  registers the manifests, caches the keys in
  `/run/maluos/estate/keys.json`, long-polls the inbox and runs tasks
  through the agent's socket, runs the allowed actions under a polkit
  rule; `maluctl estate agents|tasks|keys|inbox|actions`; the mock office
  serves the whole contract and verifies envelopes), maluos-agent 0.5.0
  (the task server verifies the envelope and applies the policy, parks for
  approval, carries provenance and usage; `create --capability
  --accept-from --max-classification --approve --personal`; `maluctl agent
  policy`; the personal agent's body), maluos-desk 0.6.0 (the desk key,
  `office agent send` with the envelope, `office inbox`, `office estate
  action`), maluos-session 0.10.0 (the inbox thread and its notifications,
  `TaskDecide`/`TaskReply`), maluos-agents 0.3.0 (the directory, the
  provenance line, the Policy page, "Make my personal agent", the Inbox
  page), maluos-gateway 0.5.2 (the envelope on the ledger row, `usage
  --envelope`).
- Tests: tests/envelope-test.py (the module alone), tests/desk-local-test.sh
  (a real end-to-end run against the mock: the daemon's inbox loop, a fake
  agent on a socket, every refusal, the approval through the inbox, an
  action; 117 checks in all), tests/qcow2-boot-test.sh (both profiles: the
  eight steps of the test plan above, the real demo agent answering
  through the gateway, the ledger row with the envelope).

Where the build departs from the text above, and why:

1. **The migration is db/190** — db/189 became the overlay.
2. **The person's inbox is a table of its own (`estate_inbox`), not
   `agent_messages`**: db/155's tree rule lets only a person's own assistant
   write to them, and an agent on a node is not a member until Agent HR
   hires it (`estate_agents.agent_member_id` links the two then).
3. **The coordinator's own agents are listed with `tasks: false`**;
   running a kernel agent's turn from an estate task is the chat endpoint's
   and waits for slice 5's work queue.
4. **An approval goes to the task's originator** when their desk sent it,
   else to the node's operator: a node agent's owner is a Linux login the
   kernel cannot map until the agent is hired. One waiting state
   (`pending_approval`) serves approvals and questions; `ask.kind` says
   which.
5. **The approve list admits what the ceiling alone would refuse**: a task
   above `max_classification` whose classification (or originator) is in
   `approve` parks for the owner instead of being refused, so an owner can
   let a restricted task through by hand.
6. **No ledger row on the node for a refusal**: the vault's ledger has no
   write door for an agent; refusals are in the agent's journal and the
   office records them on the task. The model calls of an accepted task are
   ledgered with the envelope id.
7. **Node-side `dept:N` rules** match only when the originator carries
   `departments`; the kernel applies them at capability resolution, the
   node cannot look up a membership.
8. **`actions.allow`** defaults to the four agent and update actions;
   `reboot` is off until `maluctl estate actions allow …` (or `join
   --allow-actions`) names it. `apply_updates` starts
   `maluos-estate-updates.service` (a oneshot running `maluctl update
   apply`).
