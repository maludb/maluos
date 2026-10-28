# Build spec: the Memory screens (plan stage H7, memory part)

> Plan: `docs/hermes-integration-plan.md` (H7). Spec of the thing shown: `docs/build-specs/agent-memory.md`.
> **Nothing new is decided here** — no schema, no tool, no manifest action. The two write actions
> (`memory_remember`, `core_memory_set`) and their handlers exist since H4; the rules for who reads
> what are the Memory MCP server's, restated in PHP. This is two reads and two screens.

## Why PHP reads and not the MCP server

The browser never talks to PHP, and the web app never talks to anything but PHP. So the screens get
their data from two GET controllers, which resolve scope **from the signed-in member** exactly as
`mcp/memory_server.py` does and hold the MaluDB token as `remember.php` already does. No person
ever holds a MaluDB token; a namespace is never taken from the request.

## Reads (`html/memory/`, JSON only)

| Path | Params | Answers |
|---|---|---|
| `index.php` | `q?`, `subject?`, `scope?` (`self`/`department`/`org`) | the caller's scope set by name; when `q` is 2+ characters, MaluDB `POST /v1/memory/recall` over that set (narrowed, never widened); the agents whose core memory the caller may open; `can.remember_org`; the caller's departments for the write form |
| `core.php` | `member` (default: caller) | that member's core memory — MaluDB `GET /v1/principals/{ref}/profile` — and `can.set`. **Read rule** (the MCP tool's): oneself; holders of `mod:hr`; an agent one may see in full (`app_can_see_agent`). Anyone else: 403. **`can.set`** is `memory_can_set_core()` — the write handler's own rule, so the form is shown exactly when the handler would accept. |

Both: `require_insider()`, `log_screen_view()`, whitelist presenters in
`app/features/memory/present.php`. A result shows `text`, `about` (subject), `from` (`you` / a
department's name / `the organisation`) — **not the similarity**: with no embedding model
configured it is arbitrary, and a number on screen would claim otherwise. MaluDB down answers the
screen with `memory_available: false` and its sentence, not an error page: the write form and the
links still work.

An agent cannot reach these (a run token is honoured only when relayed by the actions server, which
relays POSTs to manifest handlers). Agents read memory through the Memory MCP server.

## Screens (React, nxl look, no modals, 375px)

| Route | Shows |
|---|---|
| `/memory` | **What we know** — a search (words, subject, where) whose state is the URL, and the results. **Remember something** — `ActionForm` → `/memory/remember.php` (text, subject, where, department when it is a department's and the person has several). **Core memory** — links: one's own, and each agent one may open. A short card saying what the three scopes are and that an agent's shared write waits for a person. |
| `/memory/core/[member]` | the entries (key, value, note, when), and — when `can.set` — **Set an entry** → `/memory/core-set.php`. Says that setting a key supersedes, never erases. |

Reached from: a **Memory** button beside **Skills** on `/agents`, and a **Core memory** link on an
agent's page for those who may open it (the link is always shown to those who see the agent page in
full; the read decides).

## Files (exactly these)

```
html/memory/index.php  html/memory/core.php
app/features/memory/present.php  app/features/memory/reads.php
web/lib/schemas/memory.ts
web/app/(app)/(shell)/memory/page.tsx  web/app/(app)/(shell)/memory/core/[member]/page.tsx
web/components/memory/RememberForm.tsx  web/components/memory/CoreSetForm.tsx
web/app/(app)/(shell)/agents/page.tsx  web/app/(app)/(shell)/agents/[id]/page.tsx   (one link each)
```

## Acceptance

1. The owner searches a phrase from Sasha's private note: not found (it is `agent:44`'s). Searches a
   department fact: found, labelled with the department's name.
2. `/memory/core/44` as the owner shows `vendor_naming` and the set form; as a plain user in another
   department: 403.
3. A namespace or principal in the query string changes nothing (there is no such parameter).
4. `verify.sh` passes both routes at 1280 and 375; the payloads hold nothing the screens do not show.

## Built *(2026-09-19)* — acceptance as run on this server

| # | Result |
|---|---|
| 1 | Sam (a plain user in Accounting) searching *vendor bills* finds the department fact, labelled **Accounting**; the owner (Front Office) searching the same words finds nothing — it is not his department's. Narrowed to *only mine*, Sam finds nothing. |
| 2 | `/memory/core/44` shows `vendor_naming` and the set form to the owner and to Dana (dept-admin of Accounting); Sam gets 403 *"You may read your own core memory, or that of an agent you manage."* and sees his own, empty, with the form. An unknown member is 404. |
| 3 | `?namespace=dept:3&namespaces[]=dept:3&scope=dept:3` as the owner: the scope set stays *you · Front Office · the organisation*, no result. Results whose namespace was not asked for are dropped by the controller even if MaluDB returned them. |
| 4 | `verify.sh` passes `/memory`, `/memory?q=…`, `/memory/core/6`, `/memory/core/44`, `/agents`, `/agents/44` at 1280 and 375. The core entries began as a table and became a list: at 375 a three-column table broke the value one word per line. |

No successful write was exercised from the screens (a write is a real memory under a real name); both
forms post to handlers proven in H4, with the field names read from those handlers.

## Open Questions

*(none)*
