# Kernel directory API — application tokens, reads, the change feed, HR's writes (A4)

2026-09-22 · Business OS build plan, phase 7 Part A, step A4. Design: `docs/business-os-integration.md`,
"The directory API"; the application's side: the `maludb-os-integration` plugin,
`references/sign-on-and-directory.md` §4. Built the same day.

## What it is

The kernel owns the directory — who exists, their role and status, their departments. An
application from us mirrors it with the kernel's ids and, when it is HR, changes it here and
nowhere else. Served on the internal PHP port only (`127.0.0.1:8080`), never on a public name.

| Piece | Where |
| --- | --- |
| The application token | db/136: `mcp_access_tokens.scope = 'application'` + `application_id`, one live token per application; `member_id` is the super-admin who minted it. `html/applications/token-mint.php` / `token-revoke.php` (actions `application_token_mint` / `_revoke`, super-admin); the Overview's Application token card shows the value once; retiring the application revokes it |
| `directory_writes` on the application | db/136; the form's Directory checkbox; `application_save` |
| The helpers | `app/api/directory.php`: `directory_authenticate()`, `directory_acting_member()`, `directory_require()`, `directory_log()`, the row whitelists, the three list readers |
| The endpoints | `html/api/v1/directory/members.php`, `memberships.php`, `departments.php`, `changes.php` |
| Activity | source `application` (db/136 widened the CHECK); every write logs the acting member as actor and `via_application` in `after` |

## Calls

All carry `Authorization: Bearer <OS_APPLICATION_TOKEN>`. A write also carries
`X-Acting-Member: <member id>`; bodies are JSON (`Content-Type: application/json`) or a form.

| Call | Does | Rule |
| --- | --- | --- |
| `GET members.php` | Every member, every kind and status, with live departments | Any active application with a token |
| `GET departments.php` | Every department (archived dated) and every live membership | Same |
| `GET memberships.php` | Every live membership | Same |
| `GET changes.php?since=<next>` | Rows changed since the cursor (current state, not events), plus `deleted_departments` — id, name and when, from the activity log, the one change with no row to carry (2026-09-23); no `since` = the whole directory and every deletion ever; `next` is taken 10 s back so a late commit is delivered again | Same |
| `POST members.php` | Invite a human (`email`, `business_role` user/dept_admin, `department_id`, `message`); 202, the member exists once they register | `directory_writes`; super-admin, or admin of that department |
| `PATCH members.php?id=` | `display_name`, `job_title`, `phone`, `timezone`, `is_external`, `status` active/suspended, `business_role` user/dept_admin | `directory_writes`; `app_can_admin_member`; never a super-admin, never an agent |
| `POST memberships.php` | Add or update: `member_id`, `department_id`, `is_admin`, `is_primary` | `directory_writes`; `app_is_admin_of(department)` |
| `DELETE memberships.php` | Remove (`left_at` dated) | Same |
| `POST departments.php` | Create: `name`, `description`, `parent_id`, `manager_member_id` | `directory_writes`; super-admin, or admin of the parent |
| `PATCH departments.php?id=` | Rename, re-parent (cycle refused), manager, description | `directory_writes`; `app_is_admin_of(id)` |

Reads run as the token's minter, so the directory is handed over as the kernel sees it; a write
switches the database context to the acting person before any rule is asked. One 401 sentence
covers every token failure. What no application can do here: grants, tokens, agents, super-admins.

## Proven (test application, then retired)

Mint answers the value once; reads answer 200 with a token, 401 without or with a wrong one, and
never reach PHP on the public port; the full feed and a `since` feed carrying exactly the rows
changed (a member, a department, a membership that left); no acting member 400; an ordinary user
acting on a super-admin 403 and on someone they do not administer 403; the super-admin acting:
member fields 200, membership add and remove 200, department create 201 and rename 200, invitation
202 with the mail sent; every write in the log with source `application`; `directory_writes` off
turns writes into 403 while reads still answer; retiring the application revokes the token (401).

## Open

- The mirror's timer and receivers are the application's (plugin §4).
- An External member with a grant still sees an empty launcher (from A3); the directory rows do
  carry `is_external`, so an application can decide for itself.
