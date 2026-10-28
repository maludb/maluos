# Build spec: Agent HR slice (and the model registry)

2026-09-18 · **pulled forward** from phase 5 at the owner's request · planning-class spec
Second half of "setup first", after the Estate slice.

Exemplar to replicate: **Contacts/CRM** (`docs/build-specs/contacts-crm.md`). **Read the "Review
findings" sections of `docs/build-specs/expenses.md`, `bookkeeping-ledger.md` and `estate.md`
before starting** — between them they record ten defects found in review, and this slice can
repeat most of them.

Module grant: `hr` · Manifest sections: **Agents (HR)**, plus the model-registry rows of
**AI: prompt log, models & evals**
Schema tables (never modify): `model_registry`, `agent_profiles`, `agent_config_versions`,
`agent_tool_grants`, `agent_duties`, `hr_events`, `performance_reviews`, `agent_escalations`
(`db/042_agent_hr.sql`).
Read views: `mcp_agents`, `mcp_agent_config_versions`, `mcp_agent_tool_grants`,
`mcp_agent_duties`, `mcp_hr_events`, `mcp_performance_reviews`, `mcp_agent_escalations`,
`mcp_model_registry` — **check each exists before building; if one is missing, stop and
escalate rather than reading a base table.**
Questions this slice must answer: **H1–H3, H5, H7, H8, H10–H15** (H4, H6 and H9 need the
prompt ledger and agent runs — see Out of scope).

## Why the model registry is in this slice

`agent_profiles.model_id` is `NOT NULL REFERENCES model_registry(id)`, and **`model_registry`
has zero rows**. Without it you cannot hire anybody, so the registry's three screens
(`models-settings`, `model-add`, `model-edit`) and two actions (`model_save`,
`model_set_status`) come along, even though the manifest files them under AI. They are gated
`super` there and stay `super` here.

**No API keys in this slice.** `model_registry.api_secret_id` points at `tenant_secrets`, which
has no writer yet — the Stripe slice builds that (decided 2026-09-18, AES-256-GCM with
`SECRETS_KEY`). Register the model; leave `api_secret_id` NULL; the form says a key is attached
once the secret store exists. A model without a key can be hired against and cannot be *run*,
which is exactly the state this slice leaves the world in.

## What this slice does NOT do — and why it still makes sense

**Nothing here runs an agent.** The agent runner, harness registry, prompt ledger and agent runs
are phase 5. This slice is the **employee records**: who we employ, what their job says, which
tools they hold, what they are scheduled to do, who manages them, and the trail of all of it.
That is worth having on its own — it is what the Estate's office-manager picker, the approval
policies and the department model already expect to exist.

Carved out, each answering rather than pretending:

- **`agent_run_duty_now`** — build the endpoint; it answers "running a duty needs the agent
  runtime, which arrives with AI ops" through `emit_action_status(false, …)` and writes nothing.
  Duties are still authored, scheduled and displayed; `last_run_at` / `next_run_at` are
  displayed, never written here.
- **Eval authoring, running and grading** — the whole of `db/046`. See the activation gate below.
- **H4, H6, H9** (performance metrics, what an agent did last week, remaining budget) need
  `prompt_ledger` and `agent_runs`. The agent-view's Performance tab says so instead of showing
  zeros that read as facts — the lesson from the ledger slice's "posted through" line.
- **`escalation_raise` is built and usable today**, because an agent with a minted action token
  can already call the actions server (proven with the expenses slice). It is the one part of
  the agent's own surface that works before the runtime exists.

## The activation gate, without evals

> **Superseded 2026-09-20:** evals are run on demand and advise; activation is never refused for the
> lack of a passing run. It records the passing run when one exists for the version, and otherwise says the
> version went live unevaluated (`activate_config_version()`).

`agent_activate_version` is specified "refused without a passing gating eval run", and
`agent_config_versions.gating_eval_run_id` is its FK. Evals do not exist yet.

**Do not fake a pass, and do not silently drop the gate.** The rule is:

- If a **gating eval set exists for this agent**, activation requires a passing run — refuse
  otherwise, naming the eval set.
- If **no eval set exists**, activation proceeds, `gating_eval_run_id` stays NULL, and both the
  screen and the activity log say **"activated without an eval gate — no eval set exists for
  this agent yet."**

The moment the evals slice lands the gate tightens by itself, with nothing in this slice to
change. Until then the record is honest about which versions went live ungated, which is
precisely what an auditor will ask.

## Gate and visibility

- **Checked 2026-09-18, so you do not have to guess: `mcp_agents` is gated on
  `app_is_insider()`**, exactly like `mcp_locations`. So this module takes the same shape as the
  Estate slice: **reads are insider-open, writes need the grant.**
  - GET `agents-list`, `agent-view`, `agent-versions`, `escalations` → **`require_insider()`**.
    Who works here and what their job is, is not a secret from the people they work with (H1's
    audience is literally `all`).
  - Every write, the hire and edit forms, and the model registry → **`require_module_grant('hr')`**,
    and the model registry additionally `require_super_admin()` because the manifest says `super`.
  - All eight `mcp_*` views this slice needs exist; none is missing.
- **A comma in the Who column means OR.** `agent_update_config` is "mod:hr, agent's manager" =
  a grant holder **or** that agent's manager. `agent_offboard` is `super` alone.
- `app_can_admin_member()` is the people rule (CLAUDE.md): use it for anything touching a
  member's own record, and pair it with the manager check.
- **Agents must not reach this module's authoring.** An agent caller may read its own profile
  (H3, H10) and raise escalations; it may not hire, configure, grant tools or review. Refuse
  agent callers explicitly on those endpoints — `is_agent_member()` exists.
- Reads through `mcp_*` views; writes to base tables after the gate.

## Two rules the schema states that the app must respect

1. **An agent's manager is a person or an orchestrator agent** *(2026-09-18; the spec said
   "a human", and the owner corrected it — an orchestrator already holds a roster and delegates
   to it, so managing what it delegates to is the same job stated twice)*.
   `agent_profiles.manager_member_id` is a plain FK with `CHECK (manager_member_id <> member_id)`
   and a comment saying "human (app-enforced)" — the schema has never enforced the kind, so the
   *app* is the whole of the enforcement. That is one function, `agent_manager_error()`, asked by
   the hire form, the manager picker and both endpoints behind them. It refuses a subagent and a
   voice agent by name, an offboarded agent, an agent managing itself, and a loop — an
   orchestrator made to report to the very agent that reports to it would leave a management
   chain with nobody at the top, which is how an approval queue becomes unanswerable.
2. **An agent lives wherever it is put.** Hiring sets `home_location_id` **and** writes the
   `location_residents` row, so the hire ties this model to the estate one. It used to be
   refused when the office was "unmanaged" (`db/067`); **that rule is gone** — db/094 stopped
   the refusal and db/095 removed the concept, after it failed every hire in a tenant whose
   locations were all unmanaged by default. The only residency rule left is structural: nobody
   lives in a building, and no picker offers one. Offer every active office and desk, and never
   pre-filter the list into silence — an empty picker with no explanation is how the estate
   model becomes a mystery.

## Screens

| Screen id | Canonical URL | Purpose | Params |
| --- | --- | --- | --- |
| `agents-list` | `/agents/` | the agents we employ | `department`, `status` |
| `agent-hire` | `/agents/new` | hire an agent | `department`, `job_title` |
| `agent-view` | `/agents/{id}` | one agent: job, tools, duties, performance, spend | `tab` |
| `agent-edit` | `/agents/{id}/edit` | change the job, model, tools, duties or budget | — |
| `agent-versions` | `/agents/{id}/versions` | configuration history and eval gates | — |
| `escalations` | `/agents/escalations` | escalations raised by agents | `agent`, `open` |
| `review-add` | `/team/{id}/reviews/new` | write a performance review | — |
| `models-settings` | `/settings/models` | the model registry and harnesses | — |
| `model-add` | `/settings/models/new` | register a model | — |
| `model-edit` | `/settings/models/{id}/edit` | edit prices or status | — |

`/agents/{id}/versions` is a three-segment path with the id in the middle, **which no installed
rewrite rule serves** — the ledger slice learned this the hard way. Serve it as
`/agents/versions?agent={id}`, and change the manifest row to match, exactly as
`bank-import` was corrected. Same for `review-add`: `/team/reviews/new?member={id}`.

## Hiring — the screen this slice exists for

`agent-hire` is one form that creates **four things in one transaction**: the `members` row
(`member_kind = 'agent'`, `business_role = 'user'` — the schema's `members_agent_is_user_check`
requires it), the `agent_profiles` row, **version 1** in `agent_config_versions`, and the
`location_residents` row at the home location.

| Field | Input | Required | Notes |
| --- | --- | --- | --- |
| `name` | text | ✔ | becomes `members.display_name` |
| `email` | text | ✔ | agents need an identity for tokens; unique, validated |
| `job_title` | text | ✔ | `members.job_title` |
| `department_id` | select | ✔ | writes a `department_members` row |
| `manager_member_id` | select | ✔ | a person **or an active orchestrator agent** — `agent_manager_error()` is the whole rule (2026-09-18) |
| `model_id` | select | ✔ | from `mcp_model_registry` where status = active; if none, the form says "register a model first" and links to `/settings/models/new` |
| `job_description` | textarea | ✔ | the system prompt; version 1's `job_description` |
| `monthly_budget_amount` + `budget_currency` | number + select | | |
| `home_location_id` | select | | every active office and desk; optional, and changeable later |
| `tools[]` | multi | | `server` + `tool_name` rows in `agent_tool_grants`, snapshotted into version 1's `tool_grants` |
| `duties[]` | repeating rows | | name, instructions, cron, timezone → `agent_duties`, snapshotted into `schedule` |

**Hiring activates** *(2026-09-18, owner; the spec said status starts `candidate`)*. A hire
writes version 1, stamps it activated, points the profile at it and lands on `active`, in one
transaction, with two `hr_events` rows: `hire` and an `onboard` recording that version 1 went
live ungated. `agent_hire` is **confirm ✔** in the manifest and logs `agent.hire`.

Why the gate does not belong at hire: a version created seconds ago cannot have a passing eval
run against it, so the gate could only ever refuse every hire or be waived for every hire. It
keeps its real job on **version 2 and after**, where there is a previous version to regress
against — that is still `agent_activate_version`, and still where the gate bites.

`candidate` stays in the vocabulary: it is the honest word for an agent whose activation was
refused or undone, and for the history of the ones that had it. What must not come back is a
hire that lands there and waits for somebody to find a button.

## Config versions are immutable

`agent_update_config` never edits a version; it **creates the next one** (`version_no + 1`,
`UNIQUE (agent_member_id, version_no)`), copying forward what was not changed and snapshotting
`tool_grants` and `schedule` as jsonb. `agent_profiles.current_config_version_id` only moves on
activation. This is the same shape as the ledger's posted entries: history is written, never
rewritten, and H7 ("what changed, when, and who changed it") is answered from it.

`agent-versions` lists every version with its change note, who created it, whether and when it
was activated, by whom, and its eval gate (or "no gate — none existed").

## `agent-view` tabs

`job` (default) · `tools` · `duties` · `performance` · `trail`.

- **Job** — current version's description, model (with harness and prices), budget, manager,
  department, home location with its control/siting badges from the Estate slice.
- **Tools** — live `agent_tool_grants` grouped by server, with constraints rendered
  (`max_amount: 500`), plus grant and revoke.
- **Duties** — the schedule, each with its cron in words ("weekdays at 07:00 UTC"), `next_run_at`
  displayed if set, and a **Run now** button that answers the carve-out message.
- **Performance** — everything about the agent's work on its own page (owner, 2026-09-27 —
  nobody should have to bounce between screens for it): its model calls summed for this month,
  last month and all time, its last ten runs and ten calls, its eval sets with each one's latest
  run, the eval runs and open alerts — all read from the AI Ops views (`mcp_prompt_ledger`,
  `mcp_agent_runs`, `mcp_eval_*`), so `app_can_see_run()` and `app_can_see_evals()` decide what a
  reader sees here exactly as they do in AI Ops, and an agent caller gets no evals (people's
  work); each section links to the AI Ops screen that goes deeper. Then what activity memory
  knows: escalations raised, approval requests, and actions taken from `activity_log`. (Until
  2026-09-27 this tab carried the H4/H6/H9 carve-out message pointing at AI Ops instead.)
- **Trail** — `hr_events` and `/activity?entity_type=member&entity_id={id}` (H12, H13).
- **Paused for an approval** (2026-09-27, above the tabs, only while a run waits): each paused run
  with its pending requests and the approver's decision right there — approve (then let the agent
  carry on, a follow-up run), reject with a reason, or withdraw as the nearest human manager.
  Opening the page first sweeps overdue requests (`docs/build-specs/approvals-execution.md`).

## Files (exactly these — no additions)

```
html/agents/index.php · form.php · view.php · versions.php · hire.php · config-save.php
           · config-activate.php · manager.php · run-duty.php · suspend.php · reinstate.php
           · offboard.php · tool-grant.php · tool-revoke.php
           · escalations.php · escalation-save.php · escalation-resolve.php
html/team/reviews/form.php · save.php
html/settings/models/index.php · form.php · save.php · status.php

app/features/agents/queries.php   (profiles, versions, grants, duties, escalations)
app/features/agents/hiring.php    (the hire transaction and config-version creation)
app/features/agents/render.php    (the shared re-renders)
app/features/agents/models.php    (the model registry)

app/views/agents/agents.php · agent.php · agent-form.php · versions.php · escalations.php
app/views/agents/partials/agent-table.php · job.php · tools.php · duties.php
                 · performance.php · trail.php · version-row.php · escalation-table.php
app/views/team/review-form.php
app/views/settings/models.php · model-form.php

mcp/business_agents.py
```

## Query functions (signatures fixed)

```php
// app/features/agents/queries.php
const AGENT_PAGE_SIZE = 25;
const AGENT_STATUSES = ['candidate', 'active', 'suspended', 'offboarded'];
const TOOL_SERVERS = ['records', 'activity', 'actions', 'desk'];

find_agents(PDO, array $filters, int $page): array
find_agent(PDO, int $memberId): ?array
find_agent_versions(PDO, int $memberId): array
find_agent_version(PDO, int $versionId): ?array
find_agent_tool_grants(PDO, int $memberId): array
grant_agent_tool(PDO, int $memberId, string $server, string $tool, array $constraints, int $by): array
revoke_agent_tool(PDO, int $grantId): bool
find_agent_duties(PDO, int $memberId): array
upsert_agent_duty(PDO, int $memberId, ?int $dutyId, array $f): array
remove_agent_duty(PDO, int $dutyId): bool
set_agent_manager(PDO, int $memberId, int $managerId): array   // agent_manager_error() decides
suspend_agent(PDO, int $memberId, ?string $reason, int $by): array
reinstate_agent(PDO, int $memberId, int $by): array
offboard_agent(PDO, int $memberId, string $reason, int $by): array  // revokes tokens + grants, keeps the trail
find_hr_events(PDO, int $memberId): array
find_escalations(PDO, array $filters, int $page): array
raise_escalation(PDO, int $agentMemberId, array $f): array
resolve_escalation(PDO, int $id, ?string $note, int $by): array
find_performance_reviews(PDO, int $memberId): array
create_performance_review(PDO, int $memberId, array $f, int $by): array

// app/features/agents/hiring.php
hire_agent(PDO, array $f, int $by): array          // one transaction: member + profile + v1 + resident
create_config_version(PDO, int $memberId, array $f, int $by): array   // never edits; always the next
activate_config_version(PDO, int $versionId, int $by): array
    // gate: a gating eval set for this agent requires a passing run; none exists -> allowed,
    // gating_eval_run_id stays NULL, and the caller is told it went live ungated
gating_eval_set_for(PDO, int $memberId): ?array    // returns null until the evals slice exists

// app/features/agents/models.php
find_models(PDO, bool $includeDisabled): array
find_model(PDO, int $id): ?array
upsert_model(PDO, ?int $id, array $f): array
set_model_status(PDO, int $id, string $status): array
```

## Action-manifest entries

The manifest's eleven Agents (HR) rows and the two model rows, unchanged in substance, with two
**URL corrections** this slice makes (and must apply to the manifest in the same commit):
`agent-versions` → `/agents/versions?agent={id}`, `review-add` →
`/team/reviews/new?member={id}`. Spell every endpoint in full with its real field names, then
`php bin/build_action_registry.php`.

`agent_run_duty_now` keeps its row and its endpoint, answering the carve-out message —
a designed action that says why it cannot act yet is reachable by voice and honest; a missing
one is invisible.

## Activity log events

One `log_activity()` per state change with the manifest's exact event name, plus
`log_screen_view()` on every GET. `agent.hire`, `agent.suspend`, `agent.reinstate`,
`agent.offboard`, `agent.set_manager`, `agent_config_version.create`,
`agent_config_version.activate` (carrying whether it was gated), `agent_escalation.create`,
`agent_escalation.resolve`, `performance_review.create`, `model.save`, `model.set_status`.
Every one also writes the matching `hr_events` row where the schema has an event type for it —
`activity_log` is the audit trail, `hr_events` is the employment record, and H12/H13 read the
latter.

## MCP tools this slice must leave working

`mcp/business_agents.py`, registered from `records_server.py` as the other modules are. **Take
the tool names, parameters and gates from `docs/business-os-mcp-tool-surface.md`, not from this
spec** — the Estate slice's spec invented three tool names and the worker was right to build to
that document instead. Its "Departments & agent HR" rows are authoritative; build the ones whose
views exist, and leave anything needing `prompt_ledger`, `agent_runs` or eval tables unbuilt
rather than stubbed.

## Out of scope for this slice

- **Running anything**: the agent runner, harness registry, prompt ledger, agent runs, AI spend.
- **Evals** in their entirety; the activation gate degrades honestly as described above.
- **API keys / `tenant_secrets`** — the Stripe slice builds the secret store.
- **People & payroll** (`db/058`) — the human employment side is its own module; this slice
  writes `hr_events` and `performance_reviews` for humans too, because both tables are
  member-keyed, but adds no employment or pay screens.
- Desk-resident agents and the task queue (phase 6).

## Acceptance (the demo this slice owes)

1. Register a model (`claude-opus-5`, provider anthropic, harness claude_agent_sdk, prices) —
   the registry starts empty, so this is step one and the hire form says so until it is done.
2. Hire an agent into **Accounting**, managed by Dana, home = Main Office. It succeeds, and the
   `location_residents` row appears at Main Office — proving the Estate model and this one are
   the same model. *(This step used to be a refusal, until db/094 and db/095 removed the
   managed/unmanaged rule that produced it.)*
3. The agent appears in `agents-list` as **`active`** with version 1 already activated, resident
   at Main Office, and the office-manager picker is no longer empty. *(Steps 3 and 4 used to be
   "appears as candidate" then "activate version 1"; db/096 made the hire do both.)*
4. Edit it — a new version 2 is written, unactivated, and the agent page offers **Activate
   version 2** in its header. Activating says in the screen and the log whether an eval gate
   applied, naming the reason when it did not.
5. Grant it two tools (`records:find_expenses`, `actions:expense_create` with
   `{"max_amount": 250}`); revoke one; both show in the trail.
6. Add a duty ("weekday close check", cron `0 7 * * 1-5`); **Run now** answers the carve-out.
7. Edit the job description → version 2 exists, version 1 is untouched, `agent-versions` shows
   both and who did what (H7).
8. Set an agent as the manager → refused, naming the rule.
9. As that agent (minted action token, as the expenses slice proved), raise an escalation; it
   appears on `/agents/escalations` and resolves.
10. Write a performance review for the agent and for a human.
11. Suspend, reinstate, then offboard: tokens and grants revoked, trail kept, `hr_events`
    complete (H12, H13).
12. 375px: the tabbed agent view, the duties editor and the tools list all work; no horizontal
    scroll.

## Revision — agent identity, the prompt library and its parameters (`db/070`, `db/071`)

**Applied 2026-09-18, after the slice landed.** `db/071` followed the same day: **model
parameters are managed on the prompt version**, not per agent.

A prompt version is the whole instruction unit — *this wording, at these settings*. Changing
temperature is a new version exactly as changing a sentence is, because both change what an
eval is measuring. `system_prompt_versions.parameters` (jsonb, object-checked) holds them, with
generated `temperature` and `max_tokens` columns beside it so comparing versions is a query;
the immutability trigger guards parameters as well as body; and
`agent_config_versions.harness_config` is written by trigger from the cited version, so a
configuration can never claim settings its prompt version did not have. Verified: a config
citing v2 while sending `{"temperature":1.9}` stored the version's `0.2`.

**The consequence, stated rather than discovered later:** two agents needing different
temperatures need two prompt versions (or two prompts). That is deliberate. The mirror trigger
is the single place to relax it if per-agent tuning is ever wanted.



Asked for 2026-09-18 while this slice was being built; held until it landed, then applied —
exactly as control and siting were added to Estate after it shipped.

Of the eight fields asked for, **four already existed** and are deliberately not duplicated:
`name` is `members.display_name`, `available_tools` is `agent_tool_grants`, `available_modules`
is `module_grants` (member-keyed, so it already works for agents), and `role` has precedent in
`eval_sets.role_key`. Adding columns for tools or modules would give an agent two different
answers to "what am I allowed to do", one of which the MCP servers ignore.

What `db/070` adds:

- **A prompt library** — `system_prompts` + `system_prompt_versions`, so one prompt serves many
  agents and improving a shared instruction is one edit rather than fifty. A version's text is
  immutable (trigger), because a configuration cites it.
- **`agent_config_versions.system_prompt_id` + `system_prompt_version`**, with
  `job_description` kept as the **resolved copy** of what that configuration actually used.
  Editing the library later must never change the record of what a past configuration said —
  the config history is what the eval gate and the audit trail rest on. Same principle as a
  posted journal entry or an issued invoice number.
- **`agent_profiles.description`, `role_key`, the profile photo.** The photo started as a URL
  (db/070) because this server had no file storage. **Superseded 2026-09-18 by db/090**: the
  photo is uploaded and held — `profile_photo_path` (relative to the tenant storage root,
  default `<app>/storage`), `mime`, `size_bytes`, `sha256`, `updated_at`; the bytes live outside
  the document root and only `/agents/photo.php` serves them, under the same visibility rule as
  the agent record. `mcp_agents.profile_pic_url` survives as a derived column — the address that
  serves the photo, or NULL — so every reader that already asked for a URL still gets one. This
  is the first use of the storage root db/035 describes, so the Documents slice inherits its
  shape rather than inventing one.

The follow-up pass then carries them through the hire and edit forms, the agent view, the MCP
tools, and adds prompt-library screens with their own manifest rows.

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)

- (none)


## Voice agents and the inbound call *(added 2026-09-18)*

`agent_kind = 'voice'` (db/091) is an agent that answers the phone. It stands outside
delegation at both ends, so db/072's one-level rule — and the cycle-freedom resting on it —
is untouched, and the roster tab does not apply to it.

**How a call finds its agent.** `agent_profiles.phone_number` (db/093) is one E.164 number per
voice agent, unique, refused on any other kind. RetellAI's inbound-call webhook sends the
number that was dialled, and that is the whole routing decision.

**The webhook** is `html/voice/retell-inbound.php`. It is neither a screen nor a manifest
action: no member is present, so it carries no session, no CSRF token and no module gate.

- **Authentication** is Retell's signature: header `X-Retell-Signature: v={timestamp_ms},d={hex}`,
  where the digest is `HMAC-SHA256(rawBody . timestamp)` keyed with `RETELL_API_KEY` from
  `config/.env`. The timestamp must be within five minutes, or a captured request could be
  replayed. A refusal answers `401` and says nothing about why; the reason goes to the error log,
  because "timestamp too old" versus "digest wrong" is a hint an attacker can use.
- **Reads go to the base tables**, deliberately: with no member session `app_is_insider()` is
  false and every `mcp_*` view would answer empty. The request is authenticated by signature
  instead, and the query is one agent by one number.
- **The answer** is `{"call_inbound": {...}}`. Retell has no field for a raw system prompt, so
  the prompt travels as a dynamic variable (`system_prompt`, alongside `agent_name`,
  `agent_job_title`, `business_name`) that the Retell agent's template references; `metadata`
  carries our `agent_member_id` and `config_version_id` so a call in Retell's console can be
  found in our trail. The prompt is the resolved copy on the agent's **active configuration
  version** — editing a library prompt later never changes what a past call ran on.
- **`{"call_inbound": {}}` is the honest "no override"**, used for an unknown number, an agent
  that is not active, and an agent with no configuration version. It leaves Retell's own
  configuration in charge. The call is never rejected from here: declining to override is ours
  to decide, hanging up on a customer is not.
- **Every call is logged**: `voice_call.inbound` against the agent (source `webhook`, the agent
  as actor, carrying call_id, both numbers, the agent's status and whether a prompt was
  supplied), or `voice_call.unrouted` when no agent answers that number.

Retell waits ten seconds and retries twice, so every path answers at once and nothing slow sits
in the request.

**Not built here:** call records, transcripts, cost through the prompt ledger, outbound calls,
or any Retell configuration beyond the key. Those belong to the call-integration slice.
