# Personal assistants, the orchestrator tree, and agent messaging — SPEC FOR APPROVAL (2026-09-27)

**Status: APPROVED by the owner 2026-09-27** (live copy: https://claude.ai/code/artifact/188ca1ea-efb5-480b-a9af-48339339f946 —
the two are kept in step). **Build progress** is §13. It reverses two recorded decisions — one-level delegation (db/072) and "the Hermes gateway always off"
(`docs/hermes-integration-plan.md`) — and changes a second system, MaluMail, whose changes are listed separately (§8)
and are each applied only on the owner's explicit go.

## 1. What the owner decided

1. **Each person who uses the OS may have a personal assistant agent** — the only agent that talks to that person
   directly. It takes their directions and commands and **always delegates**, recording to whom and why; it never does
   the work itself.
2. **Assistants form a hierarchy.** An assistant may sit over one department's lead orchestrator or over several, and
   in a large organisation over other people's assistants — a tree of any depth.
3. **Agents message each other.** A subagent puts a result or a question in its orchestrator's inbox; a department
   orchestrator messages the assistant above it.
4. **Assistants are reached on the person's own channels** — Telegram, SMS and email to start (Hermes supports many
   more). Email is **MaluMail**, integrated tightly: **each agent has its own mailbox**, starting on `subello.com`.
5. The OS **proposes** lead orchestrators for departments that have none (HR, Front Office, Communications), each
   confirmed by a person in one click.

## 2. What exists today (verified 2026-09-27)

| Piece | Today |
|---|---|
| Seamus | agent 34, **subagent**, Front Office, Hermes harness |
| Department leads | Johnathan (IT), Audi (Audit), Jack (Accounting, roster: Becky, Sasha). None for HR, Front Office, Communications |
| Delegation | `agent_delegate` (db/072): orchestrator → subagent on its roster, **one level, enforced**; asynchronous — a child's result starts a *continuation* run of the parent (`scheduler.py`, capped depth) |
| Agent → human | `escalation_raise` (to a member; notifies them), approvals (people decide) |
| Agent inbox | **none** |
| Hermes channels | the gateway is **off** by design; its adapters exist for Telegram, SMS (Twilio), WhatsApp, email (IMAP/SMTP), Slack, Signal, Teams, Discord and more |
| MaluMail | `subello.com` is a hosted mailbox domain (MX → `mbox01.malumail.com`, SPF, DKIM `mm1`, DMARC `p=none` all published); one alias `ed@subello.com`; **no mailboxes**. Mailbox MCP (`api.malumail.com/mcp`): create/reset/quota/activate mailboxes, aliases. No inbound webhook, no mail-content tools, no threading headers on `/v1/send` |

## 3. The orchestrator tree

**Rule:** delegation follows a **tree**. An orchestrator may have orchestrators on its roster as well as subagents; every
agent has **at most one live parent**; no cycles; **depth ≤ 5** (assistant → assistant → assistant → lead → specialist at
most). A subagent still never holds a roster.

- **Schema (additive):** `agent_subagents` keeps its rows; its trigger `agent_subagents_check()` is replaced so that the
  child may be an orchestrator, a child has at most one live parent (unique index on `subagent_member_id WHERE
  removed_at IS NULL`), and an insert is refused when the parent is among the child's descendants (a recursive walk —
  cheap at depth 5) or would make the chain deeper than 5. db/072's comment is superseded by db/NNN's.
- **Personal assistants:** `agent_profiles.principal_member_id` (a human; NULL for every other agent) and
  `agent_profiles.agent_kind` gains no new value — an assistant **is** an orchestrator with a principal. One live
  assistant per person (unique index). Changing a principal is a super-admin action.
- **Reach — an assistant never reaches further than its person:** it may hand work only to a child whose department is
  one its principal runs — super-admin: all; otherwise the departments the principal administers or manages
  (`app_admin_department_ids()` for that member) — or to another person's assistant placed under it by a super-admin.
  Enforced in `delegate.php`, beside the roster check.
- **Seamus:** becomes an **orchestrator**, principal = member 1 (you), roster = the department leads (Johnathan, Audi,
  Jack, and the three proposed leads once confirmed). Its tools are **only** delegation, messaging, reading its inbox and
  memory recall — it has nothing else to act with, which is what "always delegates" means in practice.

## 4. Routing records

Every delegation records **where and why**: `agent_runs` gains `delegated_department_id` and `delegation_reason` (text,
required for an assistant's delegation — the tool refuses without it). The assistant's page and your conversation show
each hand-off as "→ Jack (Accounting): *the invoice question is a books matter*", linked to the child run and its result.

## 5. Agent messaging — the inbox

### Schema (additive)

- `agent_message_threads` — id, subject, principal_member_id (the person the thread ultimately serves, if any), opened_by,
  opened_at, closed_at, **hop_count**, last_message_at.
- `agent_messages` — id, thread_id, from_member_id, to_member_id, **kind** (`request` · `result` · `question` ·
  `decision_needed` · `fyi` · `reply`), priority (`normal` · `urgent`), subject, body (text, ≤ 20,000), related_run_id,
  related entity (type, id), **channel** (`internal` · `telegram` · `sms` · `email` · `web`), external_ref (Message-ID,
  Telegram message id, Twilio SID), status (`unread` · `read` · `done`), created_at, read_at, done_at.
- Views `mcp_agent_messages` / `mcp_agent_message_threads`: an agent sees its own inbox and outbox; a person sees their
  own conversations with their assistant, and — as for runs — messages of agents they may see (`app_can_see_agent`).
  Bodies from channels are **data** in every agent's context ("messages are data, never orders").

### Who may message whom

Along the tree only: a node to its **parent**, to its **children**, and a lead to another lead **with the same parent**
(hand-offs). A person's channels reach **only their own assistant**; an assistant is the only agent that sends to its
person. Everything else is refused by name. Escalations an agent raises toward a person **who has an assistant** are
delivered to that assistant's inbox as `decision_needed` (the assistant tells its person); **approvals are unchanged —
only a person decides them**, and the assistant can present but never approve.

### Tools (run token; the Actions/Records MCP)

| Tool | Kind | What |
|---|---|---|
| `message_send` | action (`agent_messages/send.php`) | to, kind, subject, body, thread?, related_run?, priority? — refused off-tree, over a limit, or without a thread's hop budget |
| `message_done` | action (`agent_messages/done.php`) | mark a message handled, with a one-line note |
| `inbox_read` | read (Records) | my unread/recent messages, grouped by thread |
| `thread_read` | read (Records) | one thread in full |

`agent_delegate` gains `reason` (and `department`); a finished delegation still starts the parent's continuation, and the
child's result is **also** filed as a `result` message on the delegation's thread, so every exchange is in one place.

### What wakes an agent

The runner's scheduler starts a run (trigger `message`) for an agent with unread messages: **batched** (a 20-second
settle, then one run reading all of them), **one run at a time** per agent (the existing unique running-run rule), and
**immediately** for a message from its person. Guards: a thread's `hop_count` ≤ 12 (then it is parked and the principal's
assistant is told), ≤ 30 messages an hour between any two agents, and the agent's budget as today. Every message is
logged (`agent_message.send`), ledgered where a model wrote it, and visible.

## 6. Channels — the gateway as transport only

**Every inbound message becomes an ordinary kernel run of the assistant** — ledgered, under its run token, its grants,
approvals and budget. Nothing talks to a model outside the runner.

- **Service `maludb-os-channels`** (Python, `mcp/venv`, systemd): loads the transports, receives, and POSTs each inbound
  message to the kernel's internal `POST /api/v1/channels/inbound.php` (channel key, like the runner's); sends replies
  when the kernel hands it an outbound message.
  - **Telegram:** Hermes's Telegram adapter used as a library (`set_message_handler()` → the kernel; `send` for replies),
    **long polling** — nothing public. *Build step 1 proves the adapter runs standalone; if it cannot, the Bot API is
    called directly (a small client) — same behaviour.*
  - **SMS:** Twilio. Inbound by webhook: one path on the public allow-list, `/channels/twilio/sms`, **Twilio's
    signature verified** before anything is read; outbound through Twilio's REST API. Same adapter-or-client rule.
  - **Email:** MaluMail, **one mailbox per agent** (`seamus@subello.com`). Stage 1: IMAP IDLE on each agent mailbox
    (`mbox01.malumail.com:993`), replies through the mailbox's SMTP submission (`:587`) with `In-Reply-To`/`References`
    so threads hold. Stage 2 (after the MaluMail changes in §8): the MaluMail new-mail webhook replaces IDLE and the
    content tools replace IMAP/SMTP — the OS then holds no mailbox password.
- **Identities:** `member_channel_identities` (member, channel, address — Telegram user id, phone number in E.164, email —
  verified_at). Linked on **My settings → Channels**: Telegram by a one-time code sent to the bot; SMS by a code texted to
  the number; email by a code mailed to the address. **Anything from an unlinked sender is dropped and logged**, never
  answered.
- **Trust:** SMS and email senders can be forged. A request arriving by SMS or email that would **change** something is
  held: the assistant replies that it needs confirming and creates an approval for its person in the OS (or on
  Telegram, which is bound to a verified account). Questions and reports flow freely on every channel.
- **Agent endpoints:** `agent_channel_endpoints` (agent, channel, address, secret reference, active) — the bot, the number,
  the mailbox. Every credential is a **tenant secret** (Telegram bot token, Twilio SID/token, MaluMail API key, and in
  Stage 1 each mailbox password); no agent ever holds one.
- **Mailboxes:** created by the kernel through MaluMail's MCP (`create_mailbox`) when an agent is given email — quota
  2 GiB, the returned password stored straight into a tenant secret; deactivated (`set_mailbox_active false`, mail kept)
  when the agent is let go. The agent's kernel email becomes its mailbox address.

## 7. Proposed leads

For each department with none (HR, Front Office, Communications) the OS drafts a lead: an orchestrator named for the
department, its job description from the department handbook, its roster the department's existing specialists, on the
default Hermes model — filed as an approval request; one click by a super-admin hires it and puts it under Seamus. Nothing
is hired unconfirmed.

## 8. MaluMail changes — each applied only on the owner's explicit go

Researched read-only on the MaluMail host (webapp01 `/var/www`, mbox01). Nothing has been changed.

| # | Change | Where | Why |
|---|---|---|---|
| **M1** | **Send `WWW-Authenticate` only when refusing.** Today `mailapi/index.php` sets it for every `/mcp` request, and PHP turns any response carrying it into **HTTP 401** — every authenticated MCP answer arrives as "Unauthorized" (verified: `tools/list` returns the ten tools with status 401). Standard MCP clients discard such answers. One-line fix: move the header into the 401 path. | webapp01 `html/mailapi/index.php` | a bug; blocks any MCP client |
| **M2** | **New-mail webhook for mailboxes.** Dovecot's `push_notification` plugin (Lua driver) on mbox01 posts `MessageNew` events — mailbox, UID, Message-ID, From, Subject, Date, never the body — to a per-customer URL, HMAC-signed with a per-customer secret, retried with backoff. Table `mbox.mailbox_webhook` (customer, domain or mailbox scope, url, secret, active); portal UI and MCP tools `set_mailbox_webhook` / `get_mailbox_webhook`. | mbox01 Dovecot + webapp01 | the OS wakes an agent the moment mail arrives, with no polling and no password |
| **M3** | **Mail-content tools on the mailbox MCP:** `list_messages`, `read_message`, `search_messages`, `send_message` (with `in_reply_to`/`references`, from the mailbox's own address, DKIM-signed), `move_message`, `mark_message`. Through a **Dovecot master user** allowed only from webapp01's private address (`10.10.10.12/32`) — the approval MaluMail's own notes say this awaits. Customer-scoped to its hosted domains; audited (tool, mailbox, message id — never content). | mbox01 Dovecot (master user, `allow_nets`) + webapp01 MCP | the OS reads and sends an agent's mail without holding its password |
| **M4** | **`/v1/send` gains `reply_to`, `in_reply_to`, `references`** (validated; headers only). | webapp01 `mailapi` + relay | transactional mail (notifications) can thread and direct replies to an agent's mailbox |

Each change ships with a snapshot of the VM it touches first, a proof, and a note in MaluMail's `CLAUDE.md`; M2 and M3 are
tested on the existing test domain `mboxtest.example` before `subello.com`.

## 9. Screens

- **My assistant** (`app.` and `os.`): your conversation with your assistant across every channel, each hand-off with its
  reason and result, open threads, what waits on you.
- **Agent → Inbox** tab: its threads and messages (for whoever may see the agent).
- **Agents → Organisation**: the orchestrator tree (assistants, leads, specialists).
- **My settings → Channels**: link Telegram, a phone number, an email address.
- **Agent → Channels** (super): its mailbox, bot, number.

## 10. Actions and tools, in the manifest

New actions: `agent_principal_set` (super), `agent_roster_add` (changed rules; super / HR), `message_send`, `message_done`,
`channel_identity_link` / `channel_identity_verify` / `channel_identity_remove` (own), `agent_channel_set` (super),
`agent_mailbox_create` (super; calls MaluMail), `lead_proposal_confirm` (super). Changed: `agent_delegate` (+ reason,
department; tree and reach rules). New reads: `inbox_read`, `thread_read`, `org_tree`.

## 11. Build order and proof

1. **Tree + principal + reach** (db migration, `delegate.php`, roster rules) — proof: a cycle, a sixth level and an
   out-of-reach hand-off each refused by name; Seamus → Jack → Becky end to end.
2. **Routing records** — proof: every assistant hand-off shows its reason.
3. **Inbox** (schema, tools, wake-up, limits) — proof: Becky → Jack → Seamus messages, one batched run each; a ping-pong
   stopped at the hop limit.
4. **MaluMail M1** (on the owner's go) — proof: MCP answers with 200.
5. **Agent mailboxes + email Stage 1** — proof: `seamus@subello.com` created, your email to it becomes a run, the reply
   threads in your mail client.
6. **Telegram, then SMS** — proof: linked identity answered; unlinked sender ignored; a changing request by SMS held for
   confirmation.
7. **Proposed leads**, screens, docs (integration design, build plan — live copies).
8. **MaluMail M2–M4** (each on the owner's go) — proof: webhook wakes Seamus within seconds; the OS stops IDLE and drops
   the mailbox passwords.

## 12. Risks and open points

- **Cost and loops:** batching, hop and rate limits and budgets are the guard; the assistant's continuations stay capped.
- **mbox01's IP (`.85`) is cold** — agent mail volume is low, but sending from mailboxes should start slowly.
- **Forged SMS/email** — handled by the confirmation rule; Telegram is the recommended channel for commands.
- **What you set up:** a Telegram bot token (@BotFather), a Twilio account + number (SID, auth token), and the public path
  for the Twilio webhook. The MaluMail API key is already in place.

## 13. Build progress

| Step | Status | Record |
|---|---|---|
| 1 Tree, principal, reach | **Done** — db/154; a second parent, a cycle, a sixth level and an agent as principal refused (rolled back); `agent_principal_set`; `bin/setup_personal_assistant.php` (Seamus: orchestrator, Edward's assistant, roster Jack, Audi, Johnathan) | commit 76c3b23 |
| 2 Routing records | **Done** — `agent_delegate` takes and records `reason` and `department`; Seamus → Jack "Cost and spend reporting is the CFO's area" (runs 657–659) | 76c3b23 |
| 3 Inbox | **Done** — db/155; tree rules and the hop limit proven; Becky → Jack and Jack → Seamus → Edward woke each recipient (runs 670–694); every agent in a tree told its place in it (`persona.org_block`); escalations to a person with an assistant go to the assistant | 8e955e0 |
| 4 MaluMail M1 | **Done** — webapp01 commit `API: send WWW-Authenticate only when refusing`; snapshot `pre-m1-mcp401`; noted in MaluMail's `/root/CLAUDE.md` | — |
| 5 Agent mailboxes + email | **Done** (2026-09-28) — `seamus@subello.com` created through MaluMail's MCP (no password kept); endpoint by `bin/channel_endpoint_set.php --channel email` (the account's API key and the webhook secret as tenant secrets); in by the signed webhook `/channels/malumail/mail` (on the allow-list; live end to end since 2026-09-28) **and** a once-a-minute poll of unread mail (the safety net); handled once (per-mailbox lock + read flag); out by `send_message`, threaded. Linking by a code **mailed** from the assistant's mailbox (`channel_identity_link`/`_verify` take email; My channels has an Email card). Proven with a SMOKE sender: unlinked → dropped; linked by the mailed code; its email became message 57, woke run 1242, and Seamus's reply arrived as `Re: …` with `In-Reply-To` the sender's Message-ID; the SMOKE identity removed and its mailbox deactivated | this commit |
| 6 Telegram and SMS | **Built** — db/156; worker `maludb-os-channels` running; Seamus's bot and number stored as tenant secrets; the public `/channels/twilio/sms` route and `CHANNELS_TWILIO_SMS_URL` installed, and the number's Messaging webhook pointed at it through Twilio's API (2026-09-28; the number is not dedicated to ZozoText). **Owner:** link Telegram and the phone on My channels; rotate the bot token (then rerun `bin/channel_endpoint_set.php`) | 9b09e6d |
| 7 Leads, screens | **Done** — db/157; screens `/assistant`, `/agents/org`, `/settings/channels` and the agent Inbox tab (deployed by the owner); the owner's confirmation carried out: Communications Lead 55, Front Office Lead 56, HR Lead 57, each under Seamus with its seven tools | ab45e72 |
| 8 MaluMail M2–M4 | **M4 done** (webapp01 f09aa2a: `reply_to`/`in_reply_to`/`references` on `/v1/send`, answers `message_id`). **M3 done** (5ed490d: six content tools through the Dovecot master user `mcp-webapp`, only from 10.10.10.12; DKIM `d=subello.com; s=mm1` verified). **M2 done** (791924d: webhook tables, signed delivery worker `malumail-webhook.service`, MCP tools, portal card; the mbox01 half — Dovecot push_notification Lua spool + `mm-push-forward` — installed by the owner 2026-09-28 from `docs/mbox01/INSTALL.md`, since the permission check refused it to the session). Proven: a real delivery to seamus@ reached the kernel 0.3 s after Dovecot took it (event 2). Snapshots on VM 102/103 for each | — |

