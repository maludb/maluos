# Build spec: exam-catalog slice (EXEMPLAR)

This is the first Phase 3 slice, built by the planning-class model. It becomes the canonical reference every other slice replicates. Organizer-only throughout (authorization checked in every endpoint; non-organizers get 403 and never see the nav item).

Schema tables (never modify them): `exams`, `exam_domains`, `community_settings`. Defined in `db/002_exams.sql`, seeded in `db/020_seed_exams.sql`.

## Screens

| Screen id | Canonical URL | Purpose |
|---|---|---|
| `org-exams`  | `/organizer/exams`            | List of exams (the canonical table pattern) + a retake-policy panel |
| `exam-add`   | `/organizer/exams/new`        | Full-container exam form (empty) |
| `exam-edit`  | `/organizer/exams/{id}/edit`  | Same exam form pre-filled + inline domains editor for that exam |

No separate detail view — editing is the detail (organizer tool). Domains are managed inline on `exam-edit` (a domain has no page of its own).

## List screen (`org-exams`)
- Columns, in order: Code (`exams.code`) · Name (`exams.name`) · Audience (`exams.audience`) · Questions (`exams.question_count`) · Domains (count from `exam_domains`) · Status (active → dot+badge: `active`=success, inactive=`secondary`) · Actions (Edit)
- Search matches: `code`, `name`. Sort allowlist: `code`, `name`, `sort_order` (default `sort_order`). Page size: 25 (the catalog is tiny; pagination is for pattern conformance).
- Row link target: `exam-edit`.
- Below the table: **Retake policy panel** editing `community_settings` (wait days per fail as a comma list, max attempts / 12 mo, study-buddy window days, at-risk no-study days). Saves via `retake_policy_update`.

## Form (exam)
- Fields, in order:
  | Field | Input | Required | Validation | id |
  |---|---|---|---|---|
  | code | text | ✔ | 2–20 chars, unique (catch 23505 → field error) | `exam-form-field-code` |
  | name | text | ✔ | 1–200 chars | `exam-form-field-name` |
  | audience | text | — | ≤ 60 | `exam-form-field-audience` |
  | guide_version | text | — | ≤ 40 | `exam-form-field-guide-version` |
  | official_guide_url | url | — | valid URL or empty | `exam-form-field-guide-url` |
  | duration_minutes | number | ✔ | 1–600, default 120 | `exam-form-field-duration` |
  | question_count | number | — | 1–500 | `exam-form-field-questions` |
  | passing_score | number | ✔ | 0–1000, default 720 | `exam-form-field-passing` |
  | validity_months | number | ✔ | 1–120, default 12 | `exam-form-field-validity` |
  | sort_order | number | — | integer, default 0 | `exam-form-field-sort` |
  | active | checkbox | — | bool, default true | `exam-form-field-active` |
- Inline domains editor (only on `exam-edit`, where the exam id exists): a table of `exam_domains` rows (name, weight %, sort_order) with add/edit/delete-per-row via Pattern C (`hx-target="closest tr"`), and a live sum-of-weights hint (warn, don't block, if ≠ 100 — the guides don't always sum exactly). Delete a domain → `hx-confirm`.
- No tabs (the exemplar form is single-column).

## Files (exactly these — no additions) — AS BUILT
- `/var/www/html/organizer/exams/index.php` · `form.php` · `save.php` · `delete.php`
- `/var/www/html/organizer/exams/domain-save.php` · `domain-delete.php` · `domain-reorder.php` · `policy.php`
- `/var/www/app/features/exams/queries.php`
- `/var/www/app/views/exams/page.php` · `partials/table.php` · `row.php` · `form.php` · `domains.php` · `domain-row.php` · `policy.php`

**Deviation from template:** no `saved.php`. Full-page forms don't show a "saved" confirmation
card; on success the write controller returns the **refreshed list** and retargets the whole
content area (see Canonical patterns below). Slices whose create/edit is a full page follow this;
slices with only inline edits may still use a `saved.php` confirmation.

## Canonical patterns established by this exemplar (replicate these)
1. **Dual list endpoint distinguishes swap targets by the `HX-Target` header.** `index.php`
   returns the *table fragment* only when `HTTP_HX_TARGET === '{entity}-list-results'` (search /
   pagination / `{entity}Changed` refresh); otherwise `render_screen()` returns the full page
   (whole shell on a hard load, `#page-content` fragment on an HTMX nav).
2. **Write success → refreshed list into `#page-content`.** `save.php` / `delete.php` on success
   emit `HX-Retarget: #page-content`, `HX-Reswap: innerHTML`, `HX-Push-Url: /{entities}/`, and echo
   the list `page.php`. Validation errors emit `HX-Retarget: #page-content` and re-echo the full
   `form.php` with an `$errors` block (fields repopulated from POST).
3. **Clean URLs need mod_rewrite (currently OFF, `AllowOverride None`).** Until it's enabled, forms
   are served at their real endpoints and `hx-push-url` uses them verbatim: **`/organizer/exams/form.php`**
   (add) and **`/organizer/exams/form.php?id={id}`** (edit) — explicit URLs, reload-safe, never
   `hx-push-url="true"`. When mod_rewrite is enabled, map `/organizer/exams/new` and
   `/organizer/exams/{id}/edit` to these and switch the push URLs to the pretty forms.
4. **Inline editable child rows use `hx-include="closest tr"` (never a `<form>` inside `<tr>`).**
   CSRF rides the `X-CSRF-Token` header the shell installs; child-row ops (`domain-save/-delete/-reorder`)
   re-render the whole child region (`#exam-domains-region`) so derived state (weight sum, order) updates.

## Query functions (signatures fixed; PDO first, no request/response awareness)
- `find_exams(PDO, string $search='', string $sort='sort_order', int $page=1): array`
- `find_exam(PDO, int $id): ?array`
- `insert_exam(PDO, string $code, string $name, ?string $audience, ?string $guideVersion, ?string $guideUrl, int $duration, ?int $questions, int $passing, int $validity, int $sort, bool $active): array`
- `update_exam(PDO, int $id, …same fields): array`
- `delete_exam(PDO, int $id): bool`  *(only when no attempts/plans reference it; ON DELETE RESTRICT will raise — surface a friendly "in use" message, never the PG error)*
- `find_domains_for_exam(PDO, int $examId): array`
- `upsert_domain(PDO, int $examId, ?int $id, string $name, float $weight, int $sort): array`
- `delete_domain(PDO, int $id): bool`
- `reorder_domains(PDO, int $examId, array $orderedIds): void`
- `get_community_settings(PDO): array`
- `update_retake_policy(PDO, array $waitDays, int $maxPer12mo, int $buddyWindow, int $atRiskDays): array`

## Action manifest entries
- Screens: `org-exams`, `exam-add`, `exam-edit` (see `docs/action-manifest.md`).
- Actions: `exam_create`, `exam_update`, `domain_save`, `domain_reorder`, `retake_policy_update` — plus a destructive `exam_delete` (confirm) not exposed to voice by default. All organizer-only.

## Activity log events (in each controller, after success, per php-patterns)
- `exam.create`, `exam.update` (before/after JSON) · `domain.create`, `domain.update`, `domain.reorder` · `settings.update` (retake policy) · `screen.view` on each GET.

## Status vocabulary mapping
- exam `active` → success · inactive → secondary. (Locked colors, per design-system.)

## Out of scope for this slice
- Exam attempts, plans, calendar — later slices. Do NOT add a "members taking this exam" panel here.
- No public (member-facing) exam pages; members see exams only as filter options in later slices.
- No CSV import/export of the catalog.

## Open Questions (must be EMPTY before a worker starts)
- (none — exemplar built by planning-class model)
