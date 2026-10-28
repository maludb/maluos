# React slice template — how a module moves from HTMX to the Next.js app

2026-09-19 · written from the Contacts/CRM exemplar (`web/app/(app)/(shell)/contacts/`,
`web/components/contacts/`, `app/features/contacts/present.php`). Read
`docs/react-migration-plan.md` first. **Copy the exemplar; never improvise. An ambiguity stops
the slice and is recorded as an open question.**

## What a conversion touches — and what it must not

| Touch | Never touch |
| --- | --- |
| `html/<module>/*.php` **GET** controllers: add one `wants_json()` branch | Any write handler (they answer JSON already — `json_mode_finish()`), any gate, `verify_csrf()`, `log_activity()`, any file path |
| `app/features/<f>/present.php`: new whitelist functions | `queries.php`, `app/views/**` (frozen; deleted at cut-over), `db/**`, the `mcp_*` views |
| `web/lib/schemas/<f>.ts`, `web/app/(app)/(shell)/<module>/**`, `web/components/<f>/**` | `web/lib/api.ts`, `web/lib/actions.ts`, `web/lib/screen.tsx`, the kit — extend the kit only when a second screen needs the same thing |

## PHP: one branch per read

Place it **after** the gate, the 404 check and `log_screen_view()`, **before** `view()`:

```php
log_screen_view($pdo, 'organization-view');
if (wants_json()) {
    require_once dirname(__DIR__, 3) . '/app/features/contacts/present.php';
    respond_screen([
        'organization' => present_organization($organization),
        'people' => array_map('present_organization_person', find_people_for_organization($pdo, $id)),
        'can' => ['edit' => true, 'admin' => is_business_admin()],
    ]);
}
```

Presenter rules (the migration's security rule — a payload is reviewed against these):

1. **Whitelist.** Name every key. Never `return $row`, never spread a row, never pass `view()` data.
2. Cast: ids and counts `(int)`, flags `(bool)`, blank strings to `null`, timestamps through
   `json_ts()`, Postgres arrays through `parse_pg_text_array()`, jsonb through `json_decode`.
3. Money: send `value`, `currency` **and** `value_display => money(...)`. PHP stays the one formatter.
4. Anything the template decided with a PHP helper (`is_business_admin()`, "is this mine")
   travels as a boolean under `can` or on the item (`mine`) — the React side never re-derives a
   permission.
5. A form payload is `{ <record>, options: {...} }`; a new record is the same shape with `id: null`
   and the controller's prefills.
6. Option lists are `{id, name}` (plus what the label needs, e.g. `kind` for "(agent)").
7. A column the `mcp_*` view hides stays hidden. The single exception so far is documented at
   `find_organization_tax_id()`; a new one needs the owner's decision.
8. **A tabbed page reads only the shown tab's sections** (2026-09-28). Every tab's key travels
   in the one payload — the shape is one contract — but the handler fills the shown tab's and sends
   the others empty, so a click costs one tab's reads (the agent page: 45 statements → 13).
   Exemplar: `agent_view_data()` and `html/agents/view.php`. And a check that depends only on the
   caller belongs in a scalar subquery of the view, run once per statement (db/160), never per row.

Writes: nothing to do, **provided the handler reports** `emit_action_status(true|false, …)`. If a
handler you need does not (see the ~56 listed in the plan), stop and record it.

## Web: the files of a slice

```
web/lib/schemas/<f>.ts                          zod mirror of present.php — change both together
web/app/(app)/(shell)/<module>/page.tsx          list        → renderScreen(path, schema, render)
web/app/(app)/(shell)/<module>/[id]/page.tsx     detail
web/app/(app)/(shell)/<module>/[id]/edit/page.tsx  ┐ both render the same client
web/app/(app)/(shell)/<module>/new/page.tsx        ┘ <XForm data={…}/> from web/components/<f>/
```

URLs are the PHP canonical URLs without the trailing slash. Pages are server components; a page
is `return renderScreen(phpPath, schema, (data) => <…/>)` and nothing else handles 401/403/404/501.
Validate route params (`/^\d+$/` → `notFound()`) and pass through only the query parameters the
PHP controller reads.

| HTMX | React |
| --- | --- |
| `hx-get` + `hx-push-url` on a link | `<Link href>` from `components/kit/Link` (prefetch is off — keep it off) |
| search box / filter select / pagination | `SearchInput`, `FilterSelect`, `Pagination` — state is the URL |
| full-page form posting to `save.php` | client `XForm` using `useRecordForm("/…/save.php")`; Save/Cancel in `PageHeader`; `<ActionOutcome>` above the row |
| small in-place `hx-post` form | `<ActionForm path="/…/x.php">` + `<SubmitButton>`; `follow` when PHP navigates away (delete, merge); `confirm="…"` where there was `hx-confirm`; `resetOnSuccess` for add-boxes |
| `hx-trigger="xChanged from:body"` region refresh | nothing — `ActionForm` re-reads the page after a success |
| a select that posts on change (`hx-trigger="change"`) | `<AutoSubmitSelect>` inside an `<ActionForm>` |
| a checkbox filter | `<FilterCheckbox>` |
| dependent selects fed by Pattern A fragments (`*-fragment.php`) | the form payload carries **every** option (already visibility-filtered and capped by its query) and the client form filters; give the dependent `<select>` a `key` of the parent's value so its choice starts over, as the fragment swap did. The fragment endpoints are not converted — they die with the HTMX UI |
| `nl2br(e($x))` | `<Nl2br text={x} />` |
| `format_ts($x, $tz, 'M j, Y g:i A')` | `formatTs(x, timeZone)`; without the year: `formatTs(x, timeZone, false)` |
| `view('shared/tags.php' …)`, interactions, comments | `<Tags>`, `<Conversations>`, `<Notes>` from `components/records/` |
| owner / department pickers | `OwnerSelect`, `DepartmentSelect`; address block `AddressFields` |

## Markup rules (design system, unchanged)

- **Copy the PHP template's markup and every `id`.** Ids are the change-request vocabulary.
- No modals. Create/edit are full pages. Save/Cancel live in the page header.
- **`stretch stretch-full` only on a column's ONLY card; stacked cards are plain `.card`.** (A
  column of `stretch-full` cards cannot scroll to its own bottom — found 2026-09-19.)
- Inline `style` only where the PHP template had it. No new CSS outside `app-overrides.css`.
- Inter-element whitespace that mattered in PHP (badges on separate lines) is a `{" "}` in React.

- **A list of things a person recognises by name is cards, not a table** (the owner's preference,
  2026-09-21: Applications first, then People, Agent Workforce, Departments, Work Locations).
  `web/components/kit/RecordCard.tsx` is the kit: `CardFilters` (the title and filters in a card
  of their own), `CardSection` (a named group with its count), `RecordCard` (icon or avatar, title
  link, badges, description, label/value facts, footer actions, "Open"), `CardsEmpty`, `groupBy`.
  What is live is a solid card with the brand edge; what is not (retired, ended, suspended,
  merely available) is dashed and muted (`muted`). Group by what people think in — business
  area, department, kind of location. A card keeps the id the table row had (`agent-row-{id}`),
  paging stays under the cards, and the payload does not change: this is presentation only.
  Ledgers and line items (invoices, journal lines, time entries, stock movements) stay tables.

## Click-around (docs/build-specs/click-around.md, step 0 built 2026-09-27)

- **R1 — a name is a link.** Wherever a screen shows the name of a record that has a page, it is a
  `Link` to that page; a presenter that emits a name emits the id beside it (for a member, the kind
  too — `<Who who={…} here={here} />` picks `/agents/` or `/team/`). Cards, facts, badges, cells,
  sentences: no exceptions.
- **R2 — one route map.** `web/lib/routes.ts` (`recordHref(kind, id)`, `memberHref`) is the only
  place that knows where a kind of record lives. Activity rows, audit subjects, "what it did" rows
  and every other `entity_type #id` go through it.
- **R3 — every crumb links except the last.** "AI Ops" → `/ai`, "HR" → `/agents`, and so on.
- **R4 — a detail page knows where it came from.** A page reads `const here = await herePath()`
  (`web/lib/here.ts`) once and wraps every link that leaves it in `withBack(href, here)`; a detail
  page passes `back={{ href, label }}` (its structural parent) to `PageHeader`, which shows
  "← Back to …" — the carried `back` if the opening link had one, else the parent. Tab links
  re-carry the page's own incoming `back` (`isSafeBack(rawBack)`), not `here`.
- **R5 — forms land on the record.** Save lands on the saved record (with its tab); Cancel on an
  edit goes to the record, on a create to the list.
- **R6 — an aggregate row opens its detail.** A row that sums by something links to the filtered
  list of what it sums, so the target list accepts that filter as a query parameter.

## Done means

1. `php -l` clean; `npx tsc --noEmit` clean; `web/scripts/deploy.sh` builds.
2. `web/scripts/verify.sh <member-id> <every route of the slice>` prints `ok` at 1280 **and** 375
   for each: 200, a title, not refused, not the not-converted card, no horizontal scroll, no inner
   scroll, no `hx-` attributes, no console errors. It sends the quiet cookie — a check is never
   logged as a screen view. Never exercise a successful write in a test: it is a real activity
   row under a real name.
3. The payloads were read once with `curl -H 'Accept: application/json'` and contain nothing the
   PHP template did not show.
4. A done-note in `docs/react-migration-plan.md`, and one commit.
