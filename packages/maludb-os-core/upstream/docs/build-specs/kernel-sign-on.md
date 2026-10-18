# Kernel sign-on — the hand-off token (A3)

2026-09-22 · Business OS build plan, phase 7 Part A, step A3. Design: `docs/business-os-integration.md`,
"Identity and single sign-on"; the application's side: the `maludb-os-integration` plugin,
`references/sign-on-and-directory.md`. Built the same day.

## What it is

The kernel is the one identity. An application from us keeps no password and no login form: the
launcher carries a person in with a signed, short-lived, single-use token, and beside it the signed
claims the application refreshes its directory mirror from. Sign-out on the kernel tells every
application the person entered this session.

| Piece | Where |
| --- | --- |
| `sso_path`, `sso_logout_path` on the application | db/135 (columns, appended last on `mcp_applications` and `mcp_my_applications`); the application form and `application_save` |
| Minting and verifying | `app/auth.php`: `mint_sso_token`, `verify_sso_token`, `sign_sso_claims`, `verify_sso_claims`, `mint_sso_logout_notice`, `verify_sso_logout_notice` (the verifiers are what an application in PHP copies) |
| The claims and the launch address | `app/features/applications/sso.php`: `sso_claims()`, `sso_launch_url()`, `sso_logout_notices()` |
| Screen `launch` | `html/launch.php` (GET, `?application=`): the gate, the mint, `application.sign_on` logged, the application remembered in the session; JSON answers `{location}`, a browser is redirected |
| The route | `web/app/launch/[id]/route.ts`: asks PHP, sends the browser on; a refusal returns to `/launcher?refused=…` in PHP's words |
| The launcher | a card with a sign-on path opens through `/launch/<id>`; one without opens its address as it is |
| Sign-out | `html/logout.php` posts the notice to each application in `$_SESSION['sso_apps']` before the session dies; `application.sign_off` logged with what answered |

## The token

`{member_id}.{expires}.{app_key}.{nonce}.{hmac}` — HMAC-SHA256 with the tenant's `ACTION_TOKEN_KEY`
over `sso:member.exp.app.nonce`; 60 seconds; the nonce is 16 random bytes, and the application
refuses one it has seen; the audience is the application's `app_key`. Claims:
`base64url(json).{hmac}` over the base64url text — `member_id`, `display_name`, `email`,
`business_role`, `is_external`, `status`, `departments[{id,name,is_admin}]`, `capability`. The
sign-out notice: `{member_id}.{issued}.{app_key}.{hmac}` over `sso-logout:member.issued.app`, 120 s.

## Who may launch

A signed-in **human** (an agent's credential is its run token, on MCP) with a live access grant on
the application — what `mcp_my_applications` shows them, so an External member sees nothing here
until a grant reaches them through that view — for an **active** application with an **address**
and a **sign-on path**. Every other case is refused in the handler's own words; "not found" for an
application the person may not see, on purpose.

## Proven

- Registering an application with the two paths; a path not starting with `/` refused (422).
- `launch.php` as the super-admin: the location is the application's address + sso path with
  `token` and `claims`; the token verifies for its app key and not for another; the claims verify
  and carry the member, role, departments and capability; a tampered claim is refused; the
  sign-out notice verifies.
- Refusals: no address (422), unknown or ungranted application (404).
- An ordinary insider with a read grant: the launcher lists the application with `sso`, the launch
  mints for them with `capability: read`, an ungranted application is 404, and sign-out logs
  `application.sign_off` with the notice's outcome (the test application's name does not resolve,
  so the outcome is 0 — the notice is best effort by design).

## Open

- **External members and the launcher** — *decided and built 2026-09-28 (db/159, for the Projects
  application, build plan A9 K2; the owner: "yes, open it up")*: `app_can_launch()` admits an insider, or an
  External who holds at least one live grant on an application that is not retired; `mcp_my_applications`
  is gated on it in place of `app_is_insider()`, and the launcher reads `mcp_launcher_applications` (its
  own view, gated the same way) instead of joining the insider-gated registry views. An External still
  sees nothing of the registry, the catalog or the OS face; `/launch/<id>` mints for them exactly as for an
  insider, since it reads `mcp_my_applications`.
- The receivers on the application side are the plugin's to build; nothing here can be exercised
  end to end until the first application from us exists (A8).
