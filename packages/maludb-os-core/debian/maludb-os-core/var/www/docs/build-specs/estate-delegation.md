# The agent directory and delegation (db/190) — the kernel half of Phase 13 slice 2

Built 2026-10-28 from the MaluOS specification `docs/phase13-slice2-delegation.md` (maluos repository), on top of
the nodes (db/188, `estate-nodes.md`) and the overlay (db/189, `estate-overlay.md`). Proof:
`BOS_INTERNAL_URL=http://127.0.0.1:8089 php bin/test_estate_delegation.php` (86 checks, re-runnable).

## What it does

Every agent on every node is listed in the estate's **directory** by what it can do. A person on a desk, or an
agent acting for one, sends a task to an agent anywhere in the estate; the request carries a signed **envelope**
that says who originated it, who sends this hop, what authority they delegate and what the data may touch. The
kernel verifies what it can see, stores the task durably, hands it to the agent's node when that node long-polls
its **inbox**, and keeps the result with its **provenance**. The node that hosts the agent verifies the envelope
again with the directory's keys and applies the agent's own accept policy; a compromised coordinator can route a
task but cannot make a node accept an envelope its originator did not sign. A task that waits for a person (an
approval, a question) parks and the person's **estate inbox** carries the question to their desk; their signed
answer re-queues it. A system manager's **action** on a remote node (restart an agent, apply updates) travels the
same way, and the node runs only what its own `actions.allow` permits.

## Schema (db/190, additive)

| Table | Holds |
|---|---|
| `estate_agents` | the directory: node (`location_id`, null = the coordinator's own), name, principal, display, description, `capabilities text[]`, owner, `accept_from text[]` (empty = its owner only), `max_classification`, `approve text[]`, `tasks`, `unit_state` (from the report), `card`, `agent_member_id` (Agent HR, once hired), status active/removed |
| `estate_coordinator` | one row: the coordinator's ed25519 key (public `ssh-ed25519 …`, secret base64), made on first use |
| `estate_tasks` | `id t_…`, `(envelope_id, hop)` unique, agent, node, originator principal + member, sender principal + node, `envelope`, `message`, state `queued|leased|running|pending_approval|completed|failed|refused`, `lease_until`, `leases`, `result` (output, provenance, usage, ask, answer), reason |
| `estate_actions` | `id a_…`, node, action, agent, envelope, requester, state, lease, result |
| `estate_inbox` | a person's items: kind `question|decision_needed|result|fyi`, subject, body, from principal + node, task, options, status `unread|read|done`, decision, note, reply, the desk's `answer_envelope` |
| `estate_nonces` | (key, nonce) remembered for the envelope's life |

`locations.public_key` (db/188) now carries a desk's key too.

## The envelope

```json
{"v": 1, "id": "env_…", "issued_at": "…Z", "expires_at": "…Z", "nonce": "…",
 "originator": {"principal": "user:ed", "kind": "human", "node": "desk:42"},
 "sender": {"principal": "agent:me", "node": "desk:42"},
 "chain": [{"principal": "user:ed", "node": "desk:42", "ts": "…", "task_id": null}, …],
 "target": {"agent": "helpdesk", "node": "server:57"}  |  {"capability": "diagnosis"},
 "purpose": "…", "authority": {"scopes": [], "classification": "internal", "budget": {"usd": 0.5, "calls": 20}},
 "parent": {… the received envelope when forwarding …},
 "sig": {"alg": "ed25519", "key": "desk:42", "value": "base64"}}
```

**Canonical form for signing** (`envelope_canonical()`): the object without `sig`, every member whose value is
null, `[]` or `{}` omitted, keys sorted at every level, no whitespace, slashes, unicode and line terminators
unescaped. The hosts' Python (`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` after the
same pruning) produces the same bytes; the proof runs both and compares.

**Verification** (`envelope_verify()`): v, id (`env_` + hex), times (a life of at most an hour, 60 s skew),
`sig.alg` ed25519, `sig.key` a node reference, `sender.node` = `sig.key`, the signing key bound to the caller's
token (a desk token signs as its desk, a node token as its node), the signature against `locations.public_key` or
the coordinator's, the chain's last hop = the sender, a known classification, every `parent` verified (same id;
nonces not consumed for parents), the nonce unseen (recorded in `estate_nonces`). Reasons: `bad_envelope`,
`bad_signature`, `expired`, `replay`.

**Keys**: `ssh-ed25519 AAAA…` lines (what `ssh-keygen -t ed25519` prints and the node key of db/188 already is);
`ssh_ed25519_raw()` takes the 32 bytes out, `ssh_ed25519_line()` puts them back.

## Contract (surface 1)

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/estate/agents` | node | register this node's agents (the manifest list; agents not listed are removed) |
| `POST /api/v1/estate/heartbeat` with `agents: [...]` | node | the same, with each report; the report's `agents[].active` sets `unit_state` |
| `GET /api/v1/estate/agents[?capability=X&node=N&all=1]`, `GET …/agents/ID` | node or desk | the directory |
| `GET /api/v1/estate/keys` | node or desk | every active member's key and the coordinator's |
| `POST /api/v1/estate/agents/ID/tasks` | node or desk | JSON-RPC: `agent/card`, `tasks/send` (needs `envelope`; `wait` true polls up to 60 s), `tasks/get`, `tasks/list` |
| `POST /api/v1/estate/tasks` | node or desk | `tasks/send` by the envelope's target: `{agent, node}` or `{capability}` (resolved: online first, `accept_from` applied) |
| `GET /api/v1/estate/tasks/ID[?wait=N]` | originator, sender, the agent's node, an operator | the record with provenance |
| `GET /api/v1/estate/inbox?wait=25` | node | queued tasks and actions, leased 120 s (LISTEN/NOTIFY wakes the poll) |
| `POST /api/v1/estate/inbox/ID/result` | node | `{"result": task record}` (state completed/failed/refused/pending_approval with output, provenance, usage, ask) or `{"refused": reason}`; for an action `{"result": {"ok", "output", "error"}}` |
| `POST /api/v1/estate/nodes/ID/actions` | desk, operator | `{action, agent, envelope, wait}` → queued; `GET /api/v1/estate/actions[/ID]` |
| `GET /api/v1/desks/agents`, `…/agents/ID/activity`, `POST …/agents/ID/tasks` | desk | the directory in slice 8's shape; the same task interface |
| `GET /api/v1/desks/inbox?wait=25[&all=1&since=ID]` | desk | the person's items; `POST …/inbox/ID/reply`, `…/decide`, `…/read` (reply and decide carry the desk's envelope) |
| `POST /api/v1/desks/key` | desk | register the desk's key; `enroll` takes `public_key` too |

A desk's `heartbeat` answer carries `inbox_unread`; a node's carries `agents_registered`. `endpoints` of both
name the new paths (`agents`, `inbox`, `keys`, `key`, `tasks`, `actions` for an operator).

## Flow

1. A node registers its agents (the daemon, after `agent create|remove` and with each report).
2. The desk builds an envelope, signs it with the desk key and posts `tasks/send` → the kernel verifies, stores
   `estate_tasks` (`queued`), NOTIFYs `estate_node_<id>` and (with `wait`) polls the row.
3. The node's `GET inbox` leases the item (120 s; three leases unanswered = `failed: node_unresponsive`, the sweep
   in `bin/cron/desk_presence.php` requeues expired leases every minute) and runs it through the agent's socket
   with the envelope; the agent verifies and applies its policy.
4. `POST inbox/ID/result` records the outcome. `pending_approval` + `ask` posts a `decision_needed` (or
   `question`) to the originator's inbox (a task without a member originator asks the node's operator); the desk's
   `decide`/`reply` with its envelope sets `result.answer` and re-queues the task, so the node's next poll hands it
   again with `answer` (its daemon calls the agent's `tasks/resume`).
5. A refused or failed task posts an `fyi` to the originator; an action's outcome posts a `result` to its requester.

The originator member of a task is the desk's owner when a desk sent it (the token binds them, never the envelope's
claim); when a node sent a forwarded envelope it is the owner of the desk that signed the root parent.

## Where it departs from the MaluOS specification

1. **The inbox is `estate_inbox`, not `agent_messages`** — db/155's tree rule lets only a person's own assistant
   write to them, and an agent on a node is not a member until Agent HR hires it (`estate_agents.agent_member_id`
   links the two then; a later slice can mirror items into `agent_messages` for hired agents).
2. **The coordinator's own agents are listed with `tasks: false`** (`node: coordinator`); `tasks/send` to them
   answers `not_supported` — running a kernel agent's turn from an estate task is the chat endpoint's and waits
   for the work queue of slice 5.
3. **An approval goes to the task's originator** when they are a member (their desk sent it), else to the node's
   operator (`enrolled_by_member_id`): a node agent's owner is a Linux login the kernel cannot map until the agent
   is hired.
4. **One waiting state** (`pending_approval`) serves both an approval and a question; the `ask.kind` says which.
5. **The migration is db/190** (db/189 became the overlay).

## Settings

Settings → Desks, for an operator (`present_estate_for_settings()['delegation']`): the directory (agent, node,
capabilities, accept policy, ceiling, presence, owner), the last thirty tasks with their state, originator, model
count and envelope id, the actions log, the coordinator's key.
