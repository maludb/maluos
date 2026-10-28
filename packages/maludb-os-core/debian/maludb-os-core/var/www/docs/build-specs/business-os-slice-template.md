# Business OS slice build spec — template

2026-09-17 · written at M1 (build plan 1.7)

Every Business OS slice gets one spec under `docs/build-specs/`, written by the planning-class
model and approved before the slice starts. The spec's job: a worker building the slice makes
**substitutions, never decisions**.

**Standing instruction handed to every worker:**

> Build this slice exactly like the **Contacts/CRM exemplar** (`docs/build-specs/contacts-crm.md`,
> code under `html/contacts/`, `app/features/contacts/`, `app/views/contacts/`), applying this
> spec. Read `php-patterns` before any PHP and `design-system` before any markup. If anything in
> this spec is ambiguous, conflicting or missing — a field with no source, a screen with no
> action, an action with no gate — **STOP**, record the exact question under Open Questions,
> and escalate. Do not improvise. An invented decision is a defect even when the code works.

This template extends the plugin's `new-app/references/slice-build-spec.md` with the five things
that are specific to the Business OS: **the gate**, **visibility**, **the manifest**, **the tool
surface**, and **approval awareness**.

---

## Sources a spec may never contradict

| Source | What it fixes |
| --- | --- |
| `db/0NN_*.sql` (installed) | Tables, columns, constraints, the `mcp_*` read views. A slice **never** changes schema; a needed change stops the slice and escalates. |
| `docs/business-os-action-manifest.md` | The slice's screen ids, canonical URLs, action names, endpoint files, params, undo, confirm, approval category, log event, and **Who** (the gate). |
| `docs/business-os-mcp-tool-surface.md` | The tools that must answer this module's questions, and the views they read. |
| `docs/business-os-questions.md` | The questions the slice is accountable for. |
| `CLAUDE.md` (roles section) | `super_admin` / `dept_admin` / `user`, external as a flag, the helper names. |

---

## Spec skeleton (copy this)

```markdown
# Build spec: {slice} slice

Exemplar to replicate: Contacts/CRM
Module grant: `{module}`  ·  Manifest section: `{heading in docs/business-os-action-manifest.md}`
Schema tables (never modify): `{tables}` — defined in `db/{NNN}_{name}.sql`
Read views (all list/detail reads go through these): `mcp_{...}`
Questions this slice must answer: {ids from docs/business-os-questions.md}

## Gate and visibility
- Module gate: `mod:{module}` — `require_module('{module}')` in every GET and POST endpoint.
- Admin-only actions: {list} — `require_business_admin()` / `require_can_admin_member()`.
- Reads: `mcp_{entity}` only. Never SELECT the base table for a list or detail screen: the view
  is what makes a screen show a person exactly what an agent would show them.
- Writes: base tables, after `require_module()` **and** a `can_see_record()` re-check of the
  target row (RLS is permissive for `app_rw`; the app is the gate).
- Department stamping: {which column carries department_id and where it comes from}.

## Screens
| Screen id | Canonical URL | Purpose (the manifest's "when the user wants…" line) | Params |

## List screen
- Columns in order: {column → view field, format}
- Search matches: {fields} · sort allowlist: {fields} (default {x}) · page size: {n}
- Filters: {param → view field} · Row link target: {screen id}
- Empty state: {text}

## Detail screen (if any)
- Header facts, then panels in order: {panel → source view, limit}
- `data-screen` / `data-entity` / `data-record-id` values

## Form
| Field | Input | Required | Validation | id |
- Select option sources: {select → query function}
- Tabs: {only if the entity's form is tabbed}

## Files (exactly these — no additions)
- `html/{module}/…` · `app/features/{module}/queries.php` · `app/views/{module}/…`

## Query functions (signatures fixed; PDO first, no request/response awareness)
- {list}

## Action-manifest entries (copied from the manifest — do not invent)
| Action | File | Params | Undo | Confirm | Agent approval | Log event | Who |

## Activity log events
- One `log_activity()` per successful state change with the manifest's log event, plus
  `log_screen_view()` on every GET screen. Money actions put `amount` + `currency` in `after`.

## MCP tools this slice must leave working
- {tool → questions → views it reads}. The views already exist; the slice proves them with data.

## Status vocabulary mapping
- {state → locked colour: success/warning/danger/info/secondary/dark}

## Out of scope for this slice
- {things a helpful model would be tempted to add}

## Open Questions (must be EMPTY before a worker starts; workers append when escalating)
- (none)
```

---

## The five Business OS rules a spec must make explicit

1. **The gate is in the endpoint, in the manifest's words.** `mod:x` → `require_module('x')`.
   `admin` → `require_business_admin()` (super-admin, or dept-admin inside a department they
   administer). `super` → `require_super_admin()`. `own` → owner/assignee/requester check.
   `all` → `require_login()`. The gate is checked in **every** endpoint, GET and POST; a screen
   hidden from the navigation is not a gate.
2. **Reads go through `mcp_*` views; writes go to base tables.** One visibility rule for humans
   and agents, written once in SQL. A slice that hand-rolls a visibility `WHERE` clause is wrong
   even when the rows come out right.
3. **Every state-changing endpoint is `require_post()` → `verify_csrf()` → gate →
   `check_approval()` → write → `log_activity()`**, and returns `HX-Trigger: {entity}Changed`.
   **It answers the action channel on both paths:** `emit_action_status(true, [...])` on success
   and `emit_action_status(false, ['errors' => $errors])` on a validation failure. A validation
   error that re-renders the form with HTTP 200 reads as *success* to the assistant and to every
   agent — the screen looks right and the caller is lied to.
4. **Approval awareness is not optional.** Before writing, an endpoint whose action has an
   approval category asks `approval_required($pdo, $action, $amount, $currency)`. A match writes
   an `approval_requests` row, emits `pending_approval` through `emit_action_status()`, and
   **executes nothing**. Humans are not paused by the default policies; agents are.
5. **The slice ships whole.** Screens (no modals, 375px clean) + handlers + activity logging +
   the manifest entries + the MCP tools for its questions. A slice missing any one of these is
   not done, and "later" is not a plan.

## Conformance checklist (run before calling a slice done)

- [ ] Every endpoint: gate checked; every POST: `require_post()` + `verify_csrf()`.
- [ ] Every state change: `log_activity()` with the manifest's exact event name.
- [ ] Every screen id and action in `docs/business-os-action-manifest.md`, unchanged.
- [ ] Every list/detail read comes from an `mcp_*` view.
- [ ] Every dynamic value escaped with `e()`; every SQL identifier from an allowlist.
- [ ] No `.modal` for data; no `hx-push-url="true"`; ids per the naming scheme.
- [ ] 375px: no horizontal scroll, tables in `.table-responsive`, header actions collapse.
- [ ] The module's MCP tools answer their questions against the data the slice creates.
- [ ] The slice's manifest rows name the endpoint in full and use the endpoint's own field
      names, then `php bin/build_action_registry.php` regenerates the registry and the slice's
      actions appear as tools — every action reachable by one spoken sentence.
- [ ] A validation failure and a refusal both come back as `status: error` through the action
      channel, not as a 200 with a form in it.
- [ ] Open Questions section is empty (or the slice is stopped and escalated).
