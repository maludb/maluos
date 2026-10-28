# Kernel — application roles and rights (db/145, 2026-09-27)

**The owner's decision (2026-09-27):** the OS assigns rights **inside** an application; the application
exposes the roles available within it through its own MCP server; the super-admin granting a person
access sets their application roles. Choices made with the owner: a person may hold **several** roles in
one application (the rights add up); **only the super-admin** grants, changes and revokes application
access; for HR, manager rights come from **both** the Manager role and the employment record.

The contract for applications: `maludb-os-integration` 0.4.0, `skills/os-integration/references/roles-and-rights.md`.
The first application: HR, `/srv/apps/hr/docs/build-specs/roles-and-rights.md` (HR db/012).

## 1. What the application publishes

The tool **`app_roles`** on its records MCP server, with no arguments, answers `os.app-roles/1`:
`rights[{key, description}]`, `roles[{key, name, description, capability, is_admin, rights[key]}]`.
`validate_application_roles()` rejects the whole document on:
- a wrong schema, a malformed key, or a duplicate role;
- a right that is not listed in `rights`;
- a missing name, or a capability that is not read, write or admin;
- anything other than exactly one admin role, or an admin role that does not amount to `admin`;
- an empty list of roles.

## 2. How the kernel reads it

- **Token.** `mint_kernel_token($appKey)` (`app/auth.php`):
  `kernel.{exp}.{app_key}.{nonce}.{hmac over "kernel:exp.app_key.nonce"}`, 60 s, signed with
  `ACTION_TOKEN_KEY`. The application admits it to `app_roles` and nothing else.
- **Client.** `mcp_call_tool_as_kernel()` (`app/features/applications/roles.php`) is a small
  streamable-HTTP MCP client: `initialize`, `notifications/initialized`, `tools/call`. It reads a JSON
  or an event-stream answer, keeps the session id, and puts every failure in words a super-admin can
  act on.
- **Where it looks.** `fetch_application_roles()` tries each **active `mcp` endpoint** of the
  application in order until one answers.
- **Action.** `application_roles_refresh` (`html/applications/roles-refresh.php`, super, log
  `application.roles_refresh` with before, after and the added, changed, withdrawn and restored
  keys). `apply_application_roles()` makes `application_roles` match:
  - new roles are added;
  - changed ones are updated;
  - a role no longer published gets `withdrawn_at` and is never deleted;
  - a withdrawn role that returns is restored;
  - `applications.roles_synced_at` is set.
- **Hand-set roles.** `application_roles_set` stays only for an application that cannot publish. The
  Roles panel offers it only while `roles_synced_at` is null.

## 3. Grants give sets of roles

- **Schema (db/145, additive).**
  - `application_roles` gains `description`, `rights` (jsonb `[{key, description}]`), `withdrawn_at`
    and `updated_at`.
  - New table `application_access_roles (application_access_id, application_id, role_key)`. Its
    trigger refuses a role that is not the application's, or is withdrawn.
  - Every existing role-bearing grant was copied into it.
- **The grant's own row.** `application_access.role_key` stays the **highest** of the grant's roles
  (capability, then the application's order), so its capability is the grant's and every one-role
  reader keeps working. `app_grant_settle()` recomputes it when a role's capability changes.
- **`grant_application_access()`** takes `roles` (or the old single `role_key`).
- **`change_application_access()`** revokes the old grant and makes a new one with the new set, in
  one transaction, so the history stays dated.
- **The actions.** `application_access_grant` and `application_access_change` take `roles[]` (a
  repeated field: a comma list from the agents' door). `application_access_grant`,
  `application_access_change` and `application_access_revoke` are **super-admin only**
  (`require_super_admin()`; `can_manage_access()` agrees).
- **Who holds what.** `app_member_role_keys(app, member)` gives every role reaching a member, per
  scope, through any route, with withdrawn roles left out. A super-admin holds the admin role (on
  an unscoped application, and in every live scope).

## 4. What the application receives

`sso_member_holding()` is still the one holding. It gains `roles` (every key held) and `rights` (the union of
those roles' published rights), and each scope entry gains its own.

| Where | New fields |
|---|---|
| Hand-off claims | `roles`, `rights`, and `scopes[].roles`, `scopes[].rights` |
| Change feed `access[]` | `roles`, `rights`, and the same per scope |
| Run facts | `roles`, `rights` |

After a refresh the feed sends every holder again (`roles_synced_at > since`), because what a role gives may
have changed. All of this is additive: `role` and `capability` keep their meaning.

## 5. Screens

- **Application → Access tab.**
  - Grant with tick boxes, one per offered role, with its description and rights underneath.
  - Each grant's roles shown as badges, "amounts to" its capability.
  - *Change roles* on each grant.
  - A warning listing grants that still hold a withdrawn role.
- **Roles panel.** Each role as a card with its rights, its admin and "no longer offered" badges and
  its live grant count. *Read roles from the application* shows when the roles were last read.
- **Member page (`/team/<id>/edit` → Application access).**
  - Roles as tick boxes when granting.
  - *Change* per grant, and Revoke.
  - Inherited grants named, with a link to where they are changed.
  - Only a super-admin sees the controls.

## Built and proven (2026-09-27)

- Smoke **29** (10/10). One grant holds two roles (Staff + Manager, whose highest gives `write`), and
  the holding lists both. An unknown role is refused. Changing the grant to Admin gives `admin`, and
  revoking it removes access.
- Smoke **28** (10/10, now with `roles`). The member page's grant, change and revoke, and a revoke
  aimed at another application is refused.
- The kernel read HR's four roles and seven rights through HR's records MCP with its token. A token
  for another application key was refused, and the kernel token could not call any other tool.
- Smoke **30** (16/16), across the kernel and HR:
  - the refresh read 4 roles;
  - Payroll granted: the claims carry `payroll` and `pay.write`, and after HR's directory sync its
    mirror holds `{payroll}`, may run pay and see pay, and is not HR staff;
  - changed to Employee: both are off;
  - revoked: HR holds nothing for the person.
- A real hand-off wrote `{hr_admin}` into HR's mirror for member 1.
- HR's grants 19, 20 and 47 (admin, with no role) were changed to HR Admin, which gives the same
  rights under a name. The agent grant 21 (write, with no role) is unchanged.

**Owed / open.**
- The owner's web deploy, for the screens.
- The installer script (C4) should call `application_roles_refresh` after the endpoints.
- ZozoCal (C3) publishes its roles the 0.4.0 way.
- An agent's grant on an application that has roles still carries no role. The kernel accepts old
  grants as they are, but a new grant needs a role. Whether agents get a role of their own is for the
  owner to decide.
