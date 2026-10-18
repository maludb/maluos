# The fourteen stubbed modules — the owner's decisions and the rules of the unattended build

2026-09-19 · **Read this before building any of them.** The owner asked for every stubbed module
to be built in an unattended session and answered the open questions up front, twenty of them,
in five rounds. This file is those answers, the defaults taken where the documents already
leaned one way, what a read-only inventory found, and how the run behaves. It does not replace
the approved M1 documents — the schema (`db/`), `docs/business-os-action-manifest.md` and
`docs/business-os-mcp-tool-surface.md` stay the authority, and a module's build spec may add to
them but never contradict them.

The modules: AI Ops (`/ai/prompt-log`), Approvals, Content, Documents, Portal & Forms (`/forms`),
Inbox, Inventory, My Work, People, Reports, Calendar (`/schedule`), Signatures, Helpdesk
(`/tickets`), Time. Each is a `render_module_stub()` page today.

## What the inventory found (2026-09-19)

- **M1 did most of the deciding.** Every table for all fourteen is live, with `mcp_*` read views;
  every screen and action is in the manifest; every read tool is designed. None of the endpoints
  exist; of the tools only `approval_queue`, `agent_runs`, `ledger_calls`, `prompt_for_request`.
- Approvals is half built: `html/approvals/{approve,reject,cancel}.php`, the replay in
  `app/features/approvals/`, a JSON queue read — no React screens, no policy actions.
- My Work has its data already: `home_work()` in `app/features/home/queries.php`.
- All 23 application rows and all 14 nav keys exist. Two URL mismatches to settle in their
  slices: the Calendar row says `/calendar/`, nav and manifest say `/schedule/`; the Portal row
  says `/portal/`, nav says `/forms/`.
- **Shared gaps every module leans on:**
  1. `tenant_secrets` has no writer. The design is decided (AES-256-GCM, `SECRETS_KEY` in
     `config/.env`); the key is absent. Needed by Inbox, Signatures providers, channels, People.
  2. The manifest marks agent approval (`send` / `money`) on `mail_message.send`,
     `signature_request.send/remind`, `purchase_order.send`, `report_schedule.save`,
     `pay_run.approve/pay`, `compensation_change.create`, `stock_movement.write_off`,
     `ai_usage_posting.*` — the live `approval_policies` cover none of them. Without a seed,
     agents will not pause.
  3. No `mcp_*` view for the lookup tables `sla_policies`, `ticket_categories`,
     `availability_blocks`, `content_variant_media`, `mail_thread_reads`; "every list/detail
     screen reads an mcp_* view" (db/063), so their settings screens need views.
  4. No PDF renderer, no RRULE library, no chart library, no `pdftotext`. PHP accepts 2 MB
     uploads, the web app 5 MB.
  5. MaluMail cannot send cc, attachments, Reply-To, custom headers, and cannot receive.
  6. The posting run knows invoices, payments, credit notes and expenses only.
  7. Public no-login pages (`/f/<slug>`, `/sign/<token>`, `/portal`) are React routes that must be
     added to `web/middleware.ts`'s PUBLIC list; a webhook or feed an outside system calls must
     be added to the Apache allow-list (`docs/deploy/apache-react-cutover.conf`).
- Out of scope by decision, unchanged: statutory payroll; warehouse management and manufacturing
  (bins, lots, serials, BOMs); FX conversion. The desk companion is phase 6.

## The owner's answers

### How the run behaves
| # | Question | Answer |
| --- | --- | --- |
| 1 | Migrations | **Yes, additive only**, from `db/105`: views, seed rows, new columns with defaults, new tables. Nothing dropped or rewritten. Each one is named in its done-note. |
| 2 | Installs and configuration | **Yes, all of it**: npm / composer / apt packages as needed, each named in the done-note; a generated `SECRETS_KEY` added to `config/.env` — **the file must stay `640 maludb:www-data`; never `sed -i` it; back it up to `~/env-backups/` first.** |
| 3 | The spec gate | **Write each spec, then build it**: `docs/build-specs/<module>.md` from the M1 documents plus this file, committed, then built to. The owner reviews specs and code together afterwards. |
| 4 | Ambiguity | **Take the conservative default, record it, continue** — the option that writes least, exposes least and is easiest to change; recorded as an OPEN decision in the plan with what was chosen and why. **Irreversible or outward-facing things — real mail to real people, deleting data — always stop instead.** |
| 20 | Order and stopping | **Dependency order, one commit per module, run to the end.** A module that cannot be finished is left at its last passing commit with its gaps listed, and the run moves on. |

### Shared
| # | Question | Answer |
| --- | --- | --- |
| 5 | PDF | **Headless Chromium through the Playwright already installed** — a small render service turns an HTML page into a PDF, so a PDF looks like its screen. |
| 16 | Ledger posting | **All three now**: stock and purchase orders, pay runs, AI usage — the posting run's existing pattern (a rule per source, idempotent, period-aware, skipped items reported with reasons). Payroll's rule is seeded; stock and AI usage get rules by an additive seed. |

### Per module
| # | Module | Question | Answer |
| --- | --- | --- | --- |
| 6 | Inbox | Mail in | **IMAP polling** by a Python timer (like the activity ingest), credentials in the secrets store. No real mailbox is connected, so it is built and unit-checked, not proven end to end. |
| 7 | Inbox | Mail out | **MaluMail, within its limits** — no cc, no attachments, no threading headers; replies leave from the platform's sending address. The compose screen must not offer what cannot be sent, and the spec records `mail_send`'s `cc` / `attachments` parameters as not supported yet. |
| 8 | Helpdesk | SLA business hours | **A business-hours setting**: an additive table, open/close per weekday in the business timezone, seeded Mon–Fri 09:00–17:00, editable under Settings → Business. SLA clocks pause outside it. No holidays yet. |
| 9 | Time | Rate when the project has none | **A business default rate** (additive column in business settings). Project rate → business default → if blank, billable with **no amount**, flagged "no rate" on the unbilled screen — never invoiced at zero by accident. |
| 10 | Documents | Uploads | **25 MB; office files and images**: PDF, Word / Excel / PowerPoint, OpenDocument, text / markdown / CSV, PNG / JPEG / GIF / WebP. Type decided from the bytes, never the name; stored outside the web root; served only through a permission-checked endpoint; executables, scripts and archives refused. Text extracted from text, PDF and Word for search. Raise PHP's and the web app's limits to match. |
| 11 | Calendar | Recurrence | **Full RRULE with exceptions** (a recurrence library): weekdays, "second Tuesday", end date or count, "this occurrence only" edits and cancellations; the iCal feed emits the rule. |
| 12 | People | Leave | **Granted upfront each year** (1 January, or pro-rated from the start date); approved leave draws it down; a yearly job grants the new year; carry-over is a manual HR adjustment. |
| 13 | Inventory | Costing | **Weighted average cost.** |
| 14 | Inventory | Stock out | **When the invoice is sent**; a void or a credit note puts it back; drafts and quotes reserve nothing. |
| 15 | Inventory | Products on invoices | **A product picker beside the catalogue** on the invoice / quote line editor, recording `product_id`; the catalogue stays for services. This edits two built, tested forms and their save handlers — carefully, and re-verified (`mcp/smoke/1-crm-sales.json` must still pass). |
| 17 | Signatures | How a signer signs | **Typed name + consent tick + an optional drawn signature**, behind a private link; who / when / IP / document hash / each step in an event trail; the executed copy is a PDF of the document with a signature block and an audit page. |
| 18 | Portal | What an external person sees | **A separate, minimal layout under `/portal`** — only what was shared with them; no module sidebar, no command bar, no Agent View; an external user who tries a workspace URL is sent back to the portal. |
| 19 | AI Ops | Scope | **Prompt log, run view, spend, the AI-usage posting and the read tools — plus eval set / case / schedule authoring screens that say plainly "no runner yet"** when asked to run. The eval runner itself waits for the agent runtime. |

### Defaults taken because the documents already lean that way (the owner was told; none objected)
- Content: `content_publish` on a connector channel answers "not connected yet"; planning and
  manual publish with link capture are real (build plan, phase 3 / 4).
- Reports: a report **is a tool call, not SQL** — PHP calls the records MCP server with a
  short-lived token for the member. Scheduled delivery emails a **link** (no attachments exist).
- Calendar: the existing iCal feed (`html/feed/calendar.php`) is re-pointed at appointments.
- Documents: `desk_import_*` waits for phase 6 (nothing feeds it).
- Helpdesk: an agent's ticket reply needs approval by default (manifest, open point 1).
- Portal: online payment stays hidden until a Stripe slice exists.
- Forms: spam protection is a honeypot plus rate limiting — no outside service.
- Time: the week starts Monday.

## Build order
0. **Groundwork** — secrets writer + `SECRETS_KEY`; approval-policy seeds; lookup `mcp_*` views;
   the PDF render service; upload limits.
1. Approvals · 2. Time · 3. Documents · 4. Calendar · 5. Helpdesk (with the portal's request
   screens) · 6. Inbox · 7. Content · 8. Inventory · 9. People · 10. Signatures · 11. Portal &
   Forms · 12. AI Ops · 13. Reports · 14. My Work.

## What "done" means for each module
1. `docs/build-specs/<module>.md` written and committed first.
2. PHP: reads with one JSON branch fed by whitelist presenters in
   `app/features/<f>/present.php`; every state-changing handler has `require_post()` +
   `verify_csrf()` + authorization + `check_approval()` where the manifest names a category +
   `log_activity()` with the manifest's event name, reports through `emit_action_status()`, and —
   having no template — answers its refusals with `respond_invalid()`. Exemplar:
   `html/team/invitations/`.
3. Web: a zod schema per feature, pages through `renderScreen()`, forms through `useRecordForm`
   / `ActionForm`, Bootstrap nxl look, no modals, works at 375 px, every element id kept to the
   id scheme, `data-screen` / `data-entity` / `data-record-id` stamped.
4. Agents: `php bin/build_action_registry.php` makes the module's actions real tools; its read
   tools are added in `mcp/business_<module>.py` **under the names the tool surface gives them**.
5. Proof: `web/scripts/deploy.sh`; `web/scripts/verify.sh <member> <every route>` all `ok` at
   1280 and 375, as the owner (1), a dept-admin (5) and an ordinary user (6) where the gate
   differs; a click-level `--probe` for any menu, tab or toggle; a write smoke through the
   agents' door (`mcp/smoke/<n>-<module>.json`, records named `SMOKE <run>`, mail only to
   `example.invalid`), including the refusals.
6. A done-note in `docs/react-migration-plan.md` ("State"), naming every migration, every
   install and every OPEN decision taken; then one commit on main, explicit `git add` paths,
   never pushed.
