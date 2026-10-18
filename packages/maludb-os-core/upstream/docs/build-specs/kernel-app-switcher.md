# Moving between applications — the Help Desk button and the application switcher (K31, planned 2026-10-09)

**Approved 2026-10-09 (D1–D10 as recommended). BUILT the same day, end to end:** the kernel endpoint (step 1), the plugins at 0.9.0 (maludb-os-integration 82ace59/d517077, htmx-php-builder 20ff100/6a09903), ProcessCore the exemplar (1f82c3d … b2d83b8, 29 checks + a headless-Chromium look at desktop and 375px), the cidery (9344d53), and the eight kit applications GL a040d76, Help Desk 1d17a88, Projects 3725230, HR f0321fa, Consultant Tracking c7643e6, txtSchedules 6324e3e, Spaces 4c6d9c3 (30 checks each against the real kernel) and Knowledge (shell only, 12 fixture checks) — all merged to main, which is the deploy. One refinement from the retrofits: every row of the CURRENT application is marked and not linked, a scoped application's sites too (its own site switcher changes the site). Kernel step 1 BUILT the same day:** `html/api/v1/apps/mine.php`, proven by `bin/test_app_switcher.php` (16 checks: the refusals, the super-admin's rows equal the launcher's, keys and launch paths, a scoped application's `?scope=`, the Help Desk with its icon, nothing logged). One change from the plan below: the kernel answers **`launch_path`** (`/launch/<id>`, `?scope=<id>`) and a best-effort `launcher_url`; the application appends the path to its own `OS_LAUNCHER_URL`, because the launcher's scheme is the installer's choice (`--scheme`), not the kernel's to guess.

**For the owner's checkpoint.** A person who holds several applications moves between them today by going back to
`app.<domain>` and choosing a card. The owner asked for two things in every application's header (`div.header-right`):
a dedicated **Helpdesk** button, since the Help Desk is part of every installation, and beside it a **dropdown of every
application the person can open**. The change belongs to both plugins — `maludb-os-htmx-php-guidelines` (the shell
markup) and `maludb-os-integration` (how an application learns what the person holds) — and needs one small thing from
the kernel.

## What exists (the research)

- **The hand-off is the only way into an application** (`docs/build-specs/kernel-sign-on.md`): `app.<domain>/launch/<id>`
  (`web/app/launch/[id]/route.ts` → `html/launch.php`) mints the 60-second token and signed claims for the signed-in
  person and sends the browser to the application's `sso_path`. `?scope=<id>` opens a scoped application at one site or
  department; with one scope held it is chosen for them; a card an external cannot open is refused with "Application not
  found." So **a link from one application to another is a link to the launcher's `/launch/<id>`**, never to the sibling's
  own address — the sibling's guard would only bounce an unsigned visitor back to the launcher.
- **What the launcher shows** comes from one view and one presenter: `mcp_launcher_applications` (db/159; gated by
  `app_can_launch()` and `app_can_use_application()` as the session member) and `present_launcher_application()`
  (`app/features/applications/present.php`): id, name, description, icon (the catalog's feather class), url, sso,
  business_area, capability, status, and for a scoped application `scopes[{id, name, role}]` from
  `mcp_my_application_scopes`. `html/launcher.php` adds `os_url` for a super-admin.
- **The claims an application receives** (`sso_claims()`): the member, departments, capability, role, roles, rights,
  scopes, the chosen scope. Nothing about the person's OTHER applications.
- **How an application already talks to the kernel:** `kernel_call()` / `directory_read()` in `app/os.php` with
  `OS_APPLICATION_TOKEN` against `OS_INTERNAL_URL` (`http://127.0.0.1:8080`); the kernel's `directory_authenticate()`
  checks the token and `application_acting_member()` (`X-Acting-Member`) makes the database context THAT person's, so a
  query against `mcp_launcher_applications` under it answers exactly what the launcher would show them. Every
  application knows the current person's kernel member id (`users.os_member_id` in the adopted ones, `members.id` in the
  kit ones).
- **The headers today:** ProcessCore and the cidery carry the dark-mode toggle and the avatar menu; the eight kit
  applications (GL, Help Desk, Projects, HR, Consultant Tracking, txtSchedules, Spaces, Knowledge) also carry a bell and
  an ad-hoc "All applications" grid icon (`header-launcher-link`, `launcher_url()`) that goes back to the launcher. The
  plugin's skeleton (`layout-skeleton.html`) and shell example carry the theme's search, full-screen, dark-mode, bell and
  avatar items. No shared partial exists for the header's right side.
- **The Help Desk** is catalog key `helpdesk`, installed by default (K10/K21), on this install application 57 with icon
  `feather-life-buoy`.

## The design

**One kernel endpoint, one application helper, one shared partial.**

1. **Kernel — `GET /api/v1/apps/mine.php`** (internal port; bearer = the application token; `X-Acting-Member` = the
   person). Authenticates like the directory API, becomes the acting member, and answers the launcher's own rows:
   ```json
   { "schema": "os.my-applications/1", "launcher_url": "https://app.subello.com/", "os_url": null,
     "applications": [ { "id": 57, "key": "helpdesk", "name": "Help Desk", "icon": "feather-life-buoy",
                         "business_area": "Operations", "capability": "write", "sso": true, "status": "active",
                         "launch": "https://app.subello.com/launch/57",
                         "scopes": [ { "id": 3, "name": "Downtown", "role": "Manager", "launch": "https://app.subello.com/launch/56?scope=3" } ] } ] }
   ```
   `applications` is `find_launchable_applications()` + `present_launcher_application()` — the same code as
   `html/launcher.php`, so the switcher and the launcher can never disagree — plus `key` (the `app_key`) and the ready
   `launch` addresses; `os_url` only for a super-admin. A person with no live grant on the CALLING application is refused
   (403) by `application_acting_member()` as today; an agent is refused (it reaches applications through MCP). Nothing is
   logged (a read). No migration. Spec: this file; proof `bin/test_app_switcher.php` (token, acting member, the rows equal
   the launcher's for that person, a scoped application's entries, a non-holder's 403, an agent's 403).
2. **Application — `os_my_applications(): array`** in `app/os.php` (kit: `app/os_directory.php`): calls the endpoint for
   the signed-in person, **caches the answer in the session for five minutes** (`$_SESSION['os_apps']` with a timestamp),
   refreshes it at `/sso` (a fresh hand-off is the moment a grant most likely changed), and on a failed call keeps the
   last answer or returns an empty list. Standalone (`OS_ENABLED` empty) it returns nothing and the partial renders
   nothing. No new table.
3. **Application — `app/views/shared/app-switcher.php`**, rendered by the layout inside `header-right` before the
   dark-mode toggle (ids fixed: `header-helpdesk-btn`, `header-apps-toggle`, `header-apps-menu`, `header-apps-item-{id}`
   / `-{id}-{scope}`, `header-apps-launcher`, `header-apps-os`):
   - **The Helpdesk button** — `a.nxl-head-link` with `feather-life-buoy` and the word "Helpdesk" (icon only below `sm`),
     linking to the Help Desk's `launch` address; shown when the list holds the key `helpdesk`; **not shown inside the
     Help Desk itself**; hidden when the person does not hold it (a missing grant is the super-admin's to give, not a
     dead button).
   - **The applications dropdown** — the theme's `div.dropdown.nxl-h-item` with `feather-grid`, a
     `dropdown-menu-end nxl-h-dropdown`: a header "Your applications", one `dropdown-item` per application (icon,
     name; a scoped application one item per scope "txtSchedules · Downtown"), **the current application marked
     (`active`, not a link)**, then a divider and "All applications" (the launcher) and, for a super-admin, "Operating
     system". Every link is a full navigation (no `hx-*`) because it leaves the application. Sorted as the launcher sorts
     (business area, then name). One application and nothing else held → the dropdown still shows (it carries the
     launcher link) but the Helpdesk button alone may be all a person needs.
   - Replaces the kit applications' ad-hoc `header-launcher-link`.
4. **The plugins carry it:**
   - `maludb-os-integration` 0.9.0: `sign-on-and-directory.md` gains §8 "Moving between applications" (the endpoint, the
     cache, the rule that a cross-application link is a launch), `php-sign-on-kit.md` gains §8 (the helper and the partial,
     verbatim), `mcp-and-api.md` lists the endpoint beside the directory's, `os-adopt/adapter.md` §3b (adopted
     applications add the partial to their own layout), the checklist a line, `testing-without-a-kernel.md`'s fake kernel
     answers `/api/v1/apps/mine.php` so an application can prove its header without the kernel.
   - `maludb-os-htmx-php-guidelines` 0.9.0: the skeleton and `examples/index.html` carry the two items in `header-right`
     (marked "OS applications only; the partial comes from the integration plugin"), `components.md` a "Header: the
     application switcher" section, `os-application`'s phase table a Shell row, `new-app` Phase 2 ships the partial.

## Decisions (each with a recommendation)

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | Where the list comes from | (a) a kernel endpoint the application calls as the person, cached per session; (b) the hand-off claims carry `applications[]`; (c) the change feed | **(a)**. Fresh within minutes, the claims stay small, and one presenter serves the launcher and the switcher. (b) is stale for the whole session and grows a URL; (c) is per-application by design. |
| D2 | How a link crosses | (a) always through the launcher's `/launch/<id>` (`?scope=` for a scoped application); (b) the sibling's own URL | **(a)**. The hand-off is what signs the person in; (b) only adds a bounce. |
| D3 | The Helpdesk button when the person does not hold the Help Desk, or is in it | (a) hidden in both cases; (b) shown disabled; (c) shown as a request-help link to the launcher | **(a)**. A dead button asks a question nobody there can answer; inside the Help Desk the dropdown marks it current. |
| D4 | What the dropdown lists | (a) every application the person can open, one row per scope for a scoped one, the current one marked, the launcher and (super-admin) the OS at the foot; (b) only the others | **(a)**. Seeing the current one marked is how a person knows where they are. |
| D5 | Grouping | (a) flat, in the launcher's order; (b) grouped by business area | **(a)** for v1 — a dozen rows at most; the area shows as muted text beside the name. |
| D6 | Cache | (a) five minutes in the session, refreshed at `/sso`; (b) every page; (c) once per session | **(a)**. A revoked grant is already closed by the sibling's own guard; the menu only needs to be close. |
| D7 | The kit applications' existing "All applications" icon | (a) replaced by the switcher (its foot keeps the link); (b) kept beside it | **(a)**. Two ways to the launcher in one header is one too many. |
| D8 | The kernel's own React face (`os.` and `app.`) | (a) unchanged; (b) the same switcher there | **(a)**. The launcher IS the switcher there; super-admins reach the OS from the dropdown's foot. |
| D9 | Mobile | (a) icon-only Helpdesk button, the dropdown full width below `sm` like the theme's other menus; (b) move both into the avatar menu on phones | **(a)**. One tap to help, on a phone most of all. |
| D10 | Who builds the retrofit | (a) the planning model, all ten applications in one pass (three files each: the helper, the partial, two lines in the layout) with a short proof each; (b) workers | **(a)**. It is mechanical and small; the picker's worker round showed the per-application set-up costs more than the change. |

## Build order

1. **Kernel K31**: `html/api/v1/apps/mine.php`, `bin/test_app_switcher.php`, this spec marked built, CLAUDE.md's services line.
2. **Integration plugin 0.9.0** with the helper and the partial as code to copy, the fake kernel answering the endpoint.
3. **htmx-php-builder 0.9.0**: skeleton, example shell, components, os-application, new-app.
4. **ProcessCore** as the exemplar (adopted shape: `app/os.php`), proven under `php -S` with the plugin's fake kernel and
   by hand against the live kernel from the owner's session; then **the cidery** (adopted) and **the eight kit
   applications** (`app/os_directory.php`): each gets the helper, the partial, the layout lines, the ad-hoc launcher
   icon removed, a proof of the header (standalone renders nothing; under the fake kernel the Helpdesk button and the
   rows appear, the current application is marked, a scoped application shows its scopes). Merge = deploy, as with the
   picker; nothing pushed.
5. **The owner's:** nothing to install — no migration, no service, no vhost change (`/api/v1/apps/mine.php` is on the
   internal port behind the existing allow-list rules for `/api/v1/apps/`).
