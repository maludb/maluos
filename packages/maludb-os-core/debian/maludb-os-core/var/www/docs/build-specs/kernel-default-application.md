# Kernel default application — where app.<domain> takes a person (2026-09-26)

The owner's direction, 2026-09-26: every person who is not an OS user has a **default application**
they go to after signing in; someone with access to several applications chooses on the launcher;
someone with none sees "You do not have access to any applications, please contact support." Decisions:
the default is set by the person (in `/settings`) **and** by whoever administers them (their member page);
a person with no default and exactly one application goes straight into it. Approved and built the same day.

## The rule (`app_home_destination()`, `app/features/applications/queries.php`)

Arriving at `app.<domain>/` — and so after every sign-in, whose default `next` is `/` — the middleware sends
the browser to `/home` (`web/app/home/route.ts`), which asks `GET /home.php` and redirects:

1. A super-admin (or an agent): the launcher — it carries the operating system.
2. The person's default application, while it is on their launcher and openable (active, with an address):
   `/launch/<id>`, with `?scope=` when their default scope is still one they hold; an application without
   the platform's sign-on opens at its address.
3. No usable default, and exactly one application on their launcher (openable): that one.
4. Otherwise the launcher — with "Your default application could not be opened — choose one below." when a
   default was set but is no longer theirs or openable; with the empty message when they hold nothing.

The decision reads the launcher's own list (`find_launchable_applications()`), so the two never disagree. The
launcher never redirects, so its links and an application's "switch application" cannot loop. The default is
advice to the landing page, never a grant: revoke the grant and the default simply stops applying.

## Schema — db/142 (additive)

`members.default_application_id` (FK, `ON DELETE SET NULL`), `members.default_scope_id` (FK to
`application_scopes`, only with an application; a trigger refuses a scope of another application);
`app_my_default_application_id()` for the read servers.

## Action — `member_default_application_set` (`html/settings/default-application.php`)

Params: `member` (omit for yourself), `application` (omit to clear), `scope`. Gate: own, or
`app_can_admin_member()`. Refused: an application the member does not hold, a scope they do not hold there,
an agent. Log `member.default_application_set` with before and after.

## Screens and tools

`/settings` (Profile) and the member page (`/team/<id>`) carry "Open on sign-in" (`DefaultApplicationForm`);
the launcher marks the default card and says "You do not have access to any applications, please contact
support." when there is nothing; MCP `my_applications` answers `is_default`.

## Proven

`mcp/smoke/26-default-application.json` (an administrator sets Priya's default; an application she does not
hold, an agent, and a scope she does not hold are refused; the log row). `/home.php` over HTTP with action
tokens: Priya with her default → `/launch/48`; with none and two applications → the launcher; with a default
she no longer holds → the launcher with the notice; Dana, one application → straight into it; a person with
none → the launcher, no cards; the super-admin → the launcher. The React build is typechecked; deploying it is
the owner's (`web/scripts/deploy.sh`).
