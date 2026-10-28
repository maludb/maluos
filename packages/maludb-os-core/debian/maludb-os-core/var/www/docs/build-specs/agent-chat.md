# Agent Chat — talk to one agent from its page

Status: **APPROVED by the owner 2026-09-29 (all five §10 recommendations accepted) — building.**
Read with: `kernel-chat-endpoint.md` (A6, the application-side chat this reuses), `assistants-and-messaging.md`
(agent-to-agent messages and personal assistants), `agent-runtime-*.md`, `react-slice-template.md`, `click-around.md`.

## 1. What and why

On an agent's page (`/agents/{id}`, the OS face) add a **Chat** tab, the **leftmost** tab, before **Job**.
It is a conversation between the signed-in OS user and **that one agent**: the person asks questions and gives tasks in plain
words; the agent answers, works with its own tools, and says what it did, what it could not do and what is waiting for approval.

Today the only ways to make an agent do something are a one-shot "run now" instruction (`html/agents/run.php`, no thread, no
reply on the page) and an application's command bar (A6, application face only). Chat gives super-admins a direct, persistent,
auditable line to each agent.

### Non-goals (v1)

- Group chats, or one message to several agents (delegation and agent messaging already exist).
- File or image attachments, voice, and typing-by-token streaming (v2; see §9).
- Chat for people on the `app.` face, or changes to A6's application endpoint (its behavior is unchanged).
- A second chat runtime. Chat turns are ordinary **agent runs** with trigger `chat`.

## 2. Users and access

| Who | May |
|---|---|
| Super-admin (the OS face is theirs alone) | Chat with any agent they can see. |
| Dept-admin / manager on a single-face install | Chat with agents they manage — the same gate as `agent_run_start` (`agent_require_hr_or_manager`). |
| An agent | Never (delegation is its own action; `agent_refuse_agent_caller()`). |

A conversation belongs to the person who started it and is listed only to them. The runs behind it remain visible wherever runs are
visible today (AI Ops → Runs, the agent's Performance and Trail tabs) — chat is not a way around the audit trail, and the tab says so.

**Who can be chatted with.** The tab is shown for every agent but the composer is enabled only when the agent is active, has an active
configuration version, and its harness supports `chat` (the runner's `TRIGGERS` includes it; the `system_one` playbook harness and
`voice` agents do **not** take conversational turns — their tab shows a one-line reason and points to Duties/Job). A suspended,
offboarded or not-yet-activated agent shows the reason instead of a box.

## 3. The screen

Tab order: **Chat · Job · Tools · Skills · Duties · Roster/Orchestrators · Inbox · Performance · Trail** (Inbox is only for the agents
that already have it). URL: `/agents/{id}?tab=chat&c={conversation}`; `withBack()` and the crumbs work as on every other tab.
Which tab opens by default is an owner decision (§10, Q1).

```
┌ Chat ─ Job ─ Tools ─ Skills ─ Duties ─ … ───────────────────────────┐
│ Conversations  [+ New]      │  Sasha · Sonnet 5 · active            │
│  • Q3 spend review   2m     │ ─────────────────────────────────────│
│  • Hire plan         Tue    │            You  10:02                 │
│  (archived ▸)               │   How much did we spend in September? │
│                             │  Sasha  10:03   ran 2 tools · $0.02 ▸ │
│                             │   September spend is $41.20 …         │
│                             │  ⏸ Waiting for approval → Approval 31 │
│                             │ ─────────────────────────────────────│
│                             │ [ Message Sasha…            ] [Send]  │
│                             │ Enter sends · Shift+Enter new line    │
└─────────────────────────────┴───────────────────────────────────────┘
```

- **Two panes on desktop, stacked at 375px** (thread on top, conversation list behind a "Conversations" toggle). Bootstrap 5.3 nxl look;
  **no modals**. Lists of named things follow the card rule; a thread is a thread, not a table.
- **A turn** shows the person's words, then the agent's reply. Under the reply a collapsed **"Work done"** line: tools used
  (name, status, duration; a written record links to it by the click-around rules), model, cost with currency, duration, and a link to
  the **run** (`/ai/runs/{id}?back=…`). Failures show the runner's own words.
- **In flight:** a "working…" bubble with the live tool events as they arrive, a **Stop** button (existing run-cancel), and the composer
  disabled for that agent until the run ends.
- **Waiting for approval:** an inline card naming the request and linking to it. The paused run stays where it is: the existing approval
  flow may start a *follow-up run* when the approver asks for one, and that run is a run of the agent, **not a turn of this thread** (it
  shows in Performance and AI Ops). The agent is not busy while paused, so the person can keep talking to it; the next prompt's history
  says the earlier turn paused. Chat adds no approval logic.
- **Busy agent:** the runner allows one run per agent. If the agent is on a duty or a delegated task, the composer is disabled and says
  what it is doing and links to that run; nothing is queued in v1 (§10, Q3).
- **Rendering:** replies are rendered as Markdown-lite (paragraphs, lists, code, links) through a sanitizer — never raw HTML.
- A new conversation is created by the first message; the title is the first ~60 characters, renameable. **Archive** hides a
  conversation; nothing is deleted (its runs are audit records).

## 4. Behavior of a turn

1. **Send** (server action → `POST /agents/chat-send.php`): validate gate, length (≤ 6,000 chars), agent
   able to chat; create the conversation if none; build the prompt (§5); `start_agent_run($agent, $prompt, 'chat', null, $me)`;
   stamp the run with `conversation_id` and `chat_utterance`; answer **at once** with `{run_id, conversation_id, status:'running'}`.
   The request never waits for the model (unlike A6's held request).
2. **Poll** (a Next route handler proxying `GET /agents/chat-turn.php?run=`, browser → Next only): every ~1.5 s returns
   `{status, reply, error, events[], approval_request_id, cost, currency, finished}`; events come from `agent_run_events`
   (db/122) after a cursor. Stops on a terminal status. Reload-safe: opening the tab re-reads the thread and resumes polling any
   running turn.
3. **Finish:** the reply is `agent_runs.result`; the turn's ledger rows are the run's own (every model call is already in the
   prompt ledger). Nothing extra is written for accounting.
4. **Cancel:** the Stop button calls the existing cancel path; the turn shows "stopped by <person>".

Task versus question needs no separate mode: the prompt tells the agent it may act with its tools and must say plainly what it did.
Anything that writes goes through the agent's own grants and the approval hook exactly as it does for a duty.

## 5. The prompt

Refactor the scaffold in `html/api/v1/agents/chat.php` into `app/features/agents/chat.php::build_chat_prompt(array $ctx): string`, used by
both callers so they cannot drift. A6's output for its callers stays byte-for-byte the same (regression check in §8).
For OS chat the context is:

- Who is speaking (name, member id, "a super-admin of this business") and where ("the agent's Chat tab in the Business OS").
- The instruction: answer directly; do the work with your tools when the message asks for action; say what could not be done or paused.
- **History:** the last *N* succeeded turns of this conversation, oldest first, each truncated (defaults N = 10, person 1,200 chars,
  agent 2,000; total budget ~12,000 chars, dropping the oldest first). A stopped or failed turn is included as such so the agent
  is not misled. Longer memory is the agent's own (MaluDB memory MCP) — chat does not summarise in v1.
- The person's message, last.

The whole prompt is capped at `AGENT_CHAT_PROMPT_MAX` (20,000 characters — the runner enforces no cap, only the PHP handlers do; the 8,000 of a duty's instructions would not hold the history window). The person's verbatim text is kept in `chat_utterance`; the assembled
prompt in `instructions`, as A6 does.

## 6. Data (db/163, additive)

```sql
CREATE TABLE agent_conversations (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agent_member_id  bigint NOT NULL REFERENCES members(id),
  member_id        bigint NOT NULL REFERENCES members(id),   -- the person
  title            text   NOT NULL DEFAULT '',
  created_at       timestamptz NOT NULL DEFAULT now(),
  archived_at      timestamptz
);
CREATE INDEX ON agent_conversations (member_id, agent_member_id, id DESC);

ALTER TABLE agent_runs ADD COLUMN conversation_id bigint REFERENCES agent_conversations(id);
CREATE INDEX agent_runs_chat_idx ON agent_runs (conversation_id, id) WHERE conversation_id IS NOT NULL;
```

- **A turn is a run.** No message table: the person's words are `agent_runs.chat_utterance`, the agent's are `result`, the state is
  `status`, cost and tools come from the ledger and `agent_run_events`. This reuses A6's two columns (db/138) and keeps one truth.
- View `mcp_agent_conversations` (security barrier; the caller-only test in a scalar subquery, per db/160) for the MCP tool, and
  the existing `mcp_agent_runs` view gets `conversation_id` appended **last**. Grants checked afterwards.
- RLS: a conversation row is readable by its `member_id` only; super-admin sees none of others' by default in the screen
  (transparency is through the runs).
- The A6 `conversation_key` (text, per application) is untouched; the two never mix (`conversation_id` set ⇒ OS chat).

## 7. Surfaces (the slice ships whole)

| Piece | Where |
|---|---|
| Migration | `db/163_agent_chat.sql` |
| Prompt builder + helpers | `app/features/agents/chat.php`; A6 refactored onto it |
| Handlers (POST: `require_post`, `verify_csrf`, gate, `log_activity`, `emit_action_status`) | `html/agents/chat-send.php`, `chat-rename.php`, `chat-archive.php` |
| Poll (GET JSON, presenter only) | `html/agents/chat-turn.php` |
| Presenter for the tab | `app/features/agents/present.php` — `chat` block on `GET /agents/{id}?tab=chat` (conversation list, selected thread, `can.chat` + reason, running turn) |
| React | `web/app/(app)/(shell)/agents/[id]/page.tsx` — add `["chat","Chat"]` first in `tabs` and `"chat"` in `TAB_KEYS`; `web/components/agents/ChatTab.tsx` (server-rendered thread) + `ChatComposer.tsx` (client: send, poll, stop, textarea) ; route helper in `web/lib/routes.ts` |
| Next route handler for polling | `web/app/api/agent-chat/route.ts` → `web/lib/api.ts` (the browser never talks to PHP) |
| Action manifest | `agent_chat_send`, `agent_chat_archive` (gate `admin`/manager, like `agent_run_start`) → `mcp/action_registry.json` via `bin/build_action_registry.php` |
| MCP tools | records MCP: `agent_conversations` (mine), `agent_conversation_read` (turns of one); no write tool — an agent must not chat as a person |
| Activity | `agent_chat.send` (ids only — agent, conversation, run — as A6 logs; text stays in `chat_utterance`), `agent_chat.archive` |
| Docs | this file; `docs/build-specs/README.md` index; CLAUDE.md line; build-plan note (sync rule applies only if requirements text changes) |

Apache: nothing new on the public allow-list (Next route handler + internal PHP).

## 8. Tests and proof

- **PHP:** `bin/test_agent_chat.php` — gate (manager, super-admin, other member 403/404, agent caller refused), empty and over-long message,
  inactive/busy agent (409 with the reason), prompt builder (history order, truncation, budget), A6 prompt unchanged (golden string).
- **Smoke:** `mcp/smoke/NN-agent-chat.json` writes one real conversation as member 1, named `SMOKE <run>`, against a cheap test agent.
- **Real turn** on a live agent, two turns in one conversation: the second sees the first; cost and ledger rows checked; a turn that
  triggers an approval pauses and resumes; Stop cancels; reload mid-turn resumes polling.
- **UI at 375 px** and desktop; keyboard send; Markdown sanitizing test (script tags, `javascript:` links).
- **Regression:** A6 endpoint (`html/api/v1/agents/chat.php`) still answers the proven cases from `kernel-chat-endpoint.md`.

## 9. Later (not in v1)

Token streaming (SSE through the ledger proxy), a per-agent queue instead of "busy", rolling summaries for long threads, attachments,
inline approve/deny in the thread, unifying with the personal-assistant Telegram/SMS/email threads so one assistant conversation spans
channels, and starting a conversation from an escalation or a run.

## 10. Decisions (owner, 2026-09-29 — every recommendation accepted)

1. **Default tab.** Recommend **Chat opens first** for chat-capable agents (leftmost = default) and Job for the rest. Alternative: keep Job
   as the default and add Chat only to the left.
2. **Privacy.** Recommend conversations **private to their person**, runs visible as today. Alternative: visible to all super-admins.
3. **Busy agent.** Recommend **refuse with the reason** in v1; queueing is v2.
4. **Which agents.** Recommend all conversational agents, including personal assistants (a person may chat with their own assistant
   here as well as by Telegram/SMS); `system_one` and voice excluded.
5. **History window.** Recommend 10 turns / ~12,000 characters as above; raise later if agents lose the thread.

## 11. Build plan

Each step is committed on its own, with the checkpoint gate honored: **no PHP until the owner approves this spec (schema + tool
surface + manifest entries together).**

| Step | Work | Done when |
|---|---|---|
| 0 | Owner answers §10; approves the schema, MCP tools and manifest entries above. | approval recorded here |
| 1 | `db/163`; `build_chat_prompt()`; refactor A6 onto it; `bin/test_agent_chat.php` prompt and gate tests. | tests pass; A6 regression clean |
| 2 | `chat-send.php`, `chat-turn.php`, rename/archive handlers; activity logging; presenter block. | curl-level proof of a two-turn conversation on a test agent |
| 3 | React: tab order, `ChatTab`, `ChatComposer`, polling route handler, states (idle, working, waiting for approval, busy, unavailable, error), 375 px. | click-through on desktop and phone width |
| 4 | Manifest entries + registry build; MCP `agent_conversations` / `agent_conversation_read`; smoke file; click-around rules R1–R6 check. | registry count matches; smoke passes |
| 5 | Real-agent proof (two turns, an approval, Stop, reload), docs/index/CLAUDE.md, commit. Deploy is the owner's (`web/scripts/deploy.sh`). | proof written under "Proven" here |

Estimate: steps 1–2 are PHP/SQL worker-size; step 3 is the one that needs care (client polling in a server-component app —
`web/components/kit/AutoRefresh.tsx` is the nearest precedent). Steps 1 and 2 can be built before 3; nothing ships to users until 5.

## Open risks

- **One run per agent** makes chat and duties compete; a chatty person can block an agent's scheduled duty for the length of a turn.
  Mitigated in v1 by refusing chat while a duty runs and vice versa being refused by the runner; worth watching.
- **Long tasks** exceed a chat's patience: the run timeout is the agent's own limit; the thread must survive reload and long waits.
- **Cost:** history is resent every turn; the window caps it, and each turn shows its cost.
- **Transcripts are data:** `chat_utterance` and `result` may hold sensitive text; they inherit `agent_runs` retention and visibility
  and are never copied into logs or the activity trail.

## Status (2026-09-29)

**Built and committed:** steps 1–4 (db/163 applied; `app/features/agents/chat.php`; `chat-send/turn/rename/archive.php`; the `chat` block of
`GET /agents/{id}`; manifest rows `agent_chat_send|rename|archive`; records MCP `agent_conversations`, `agent_conversation_read`; React `ChatTab`,
`ChatPane`, the poll route `web/app/api/agent-chat/route.ts`, the server actions in `web/lib/agent-chat-actions.ts`; the Chat tab leftmost and the default
for chat-capable agents). Also fixed: `html/agents/run-cancel.php` read `$agent['member_id']` (the view has `agent_member_id`), so Stop would have answered 404.

**Proven:** `bin/test_agent_chat.php` (23 checks, rolled back); smoke `mcp/smoke/33-agent-chat.json` through the actions MCP, 17/17 — two real turns with
Comms (agent 47; the second carried the first from history; about 0.011 USD a turn), a playbook agent refused, an empty message refused, rename, archive,
an archived conversation refused; the rendered JSON of the tab (default tab per agent kind, `?c=new`, the archived list); the poll answers only the
person's own turns (404 otherwise); `tsc` clean and a full `next build` in a scratch copy.

**Not yet proven — needs a browser session that is the owner's, after the web deploy:** the client behavior (send, live polling and the tool trail, Stop, reload
mid-turn, the phone layout, the paused-for-approval card), and a Stop against a real running turn (to prove the run-cancel fix).
