# Build spec: members directory + profiles slice (Phase 3, slice 8)

Exemplar: **exam-catalog** for list structure. **Read-only** slice (no member editing here — self-profile edits live in Settings, Phase 4). Composes data from earlier slices under each member's visibility rules.

Schema tables (read): `members`, plus visible slices of `exam_attempts`, `study_plans`, `study_issues`, `replies`, `community_events`, `resource_endorsements`. No new tables.

## Screens
| Screen id | Served URL | Purpose |
|---|---|---|
| `members-list` | `/members/` | Directory of active members |
| `member-view`  | `/members/view.php?id={id}` | Public profile |

## List (`members-list`)
- Columns: Name (row link to view; avatar) · Organization · Certified in (exam codes where passed+shared+unexpired) · Taking (exam codes with a visible upcoming attempt) · Joined (`joined_at` medium)
- Filters: `exam` (taking this exam — join visible attempts), `certified_in` (exam), free-text `q` over display_name (trigram/ILIKE). Sort: `name` (default), `joined`. Page size 25. Active members only.

## Detail (`member-view`)
- Header: name, organization, bio, joined, certified badges (from shared+unexpired passes).
- Panels (each shows only what the viewer may see under §3.2):
  - **Visible exams**: attempts where `calendar_visible OR result_shared` (dates; results only if shared).
  - **Community plans**: their `visibility='community'` plans (link to plan-view).
  - **Issues & accepted answers**: issues authored (not hidden) + replies of theirs that were accepted (a "helper" signal, O6).
  - **Hosted events**: upcoming events they host.
- No email, no private data. This screen must not expose anything the directory viewer couldn't already see elsewhere.

## Files
- `/var/www/html/members/index.php` · `view.php`
- `/var/www/app/features/members/queries.php`
- `/var/www/app/views/members/page.php` · `partials/table.php` · `row.php` · `view.php`

## Query functions (all respect viewer visibility; pass `$viewerId`,`$isOrganizer`)
- `find_members(PDO, string $q='', ?int $takingExamId=null, ?int $certifiedExamId=null, string $sort='name', int $page=1): array`
- `find_member_profile(PDO, int $id): ?array` (base profile; active only)
- `member_certifications(PDO, int $id): array` (shared+unexpired passes)
- `member_visible_attempts(PDO, int $id, int $viewerId): array`
- `member_community_plans(PDO, int $id): array`
- `member_issues(PDO, int $id): array`, `member_accepted_answers(PDO, int $id): array`
- `member_hosted_events(PDO, int $id): array`

## Action manifest entries
Screens `members-list`, `member-view`. No write actions (read-only slice). `find_members`/`member_profile` correspond to the MCP read tools already designed.

## Activity events
`screen.view` (members-list, member-view). No mutations.

## Status / vocabulary
Certified badge → success. "Taking" tag → info. No editable status.

## Out of scope
- Editing your own profile (Settings, Phase 4). Following/messaging members. "Who viewed my profile" (deliberately not built for members; §2).

## Open Questions
- (none)
