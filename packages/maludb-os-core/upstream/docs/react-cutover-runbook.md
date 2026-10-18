# React cut-over runbook (migration step R6)

2026-09-19 · **RUN on 2026-09-19 on the owner's go ("Fix and cut over").** What was actually done is
under "As run" at the end; the sections above it are the plan as it stood.
Read `docs/react-migration-plan.md` first. This is the order, the checks and the way back for
the one step of the migration that a redeploy does not undo.

## Where things stand

- Every business screen that exists in PHP exists in React (R2–R5 done; the owner approved the
  Contacts/CRM exemplar on 2026-09-19). The only PHP screens without a JSON branch are the
  cert-study legacy ones the owner decided not to port (`attempts`, `events`, `issues`,
  `members`, `organizer`, `plans`, `resources`, `study`, `study-log`, `calendar/index.php`);
  `applications/access.php` is covered by the React application page.
- Today: Apache serves PHP **publicly** on :80 (one vhost, `000-default.conf`); Next.js listens
  on :3000 behind the outside proxy (`agentview.subello.com`). The web app reaches PHP at
  `API_BASE_URL=http://localhost`; the actions MCP posts to `http://127.0.0.1`.
- Done ahead of time (additive, harmless before the flip): `/reset.php`, `/register.php`,
  `/forgot.php` and `/login.php` redirect to the React pages with their query string
  (`web/next.config.mjs`, 307 until cut-over, 308 after).

## What must stay reachable from outside — "PHP internal-only" is not a blanket flip

These are called by things that are not this app's browser pages. The flip must allow-list
them, or cut-over silently breaks integrations:

| Path | Who calls it |
| --- | --- |
| `/api/v1/health`, `/me`, `/members`, `/org-graph` | bearer-token API clients (a public, CORS-enabled API by the owner's decision). `/session` and `/graph` are session-only and need no outside access |
| `/mcp/records`, `/mcp/activity` | external MCP clients, through Apache's reverse proxy |
| `/feed/calendar.php?…` | calendar applications subscribed to a member's feed URL |
| `/voice/retell-inbound.php` | the voice provider's webhook |

Everything else under `html/` is reached only by the Next.js server and the actions MCP, both
on localhost.

## Before the flip (no go needed — safe)

1. Owner's browser click-through of each module's writes (in progress; findings so far: the
   cached agent photo and the logo, both fixed).
2. ~~`APP_URL` was `http://localhost`~~ **Done 2026-09-19:** `https://subello.com` is the outside
   proxy in front of this server's Apache/PHP (proved by a request appearing in the local access
   log), so `APP_URL=https://subello.com`. Every absolute link PHP hands out carried the old
   value: reset and invitation mail, the MCP URLs shown in Settings, new calendar-feed URLs.
   **Mail sent before this carries `http://localhost/…` links nobody outside this machine can
   open — those people need a fresh reset or a re-sent invitation.** Google sign-in is
   unaffected (not configured here, and its redirect URI is set explicitly).
3. ~~`LOGIN_URL`~~ **Done 2026-09-19:** `web/.env.local` sent a signed-out Agent View visitor to
   `https://subello.com/login` — the legacy PHP sign-in, on another host. Removed; the app falls
   back to its own `/login`. `web/.env.example` now says to leave it unset.
4. At the flip, `APP_URL` moves to the React host name, and the mail templates to the React
   paths (step 6) — until then the PHP pages at `subello.com` are what the links open, and the
   redirects above cover the day they stop being PHP.

Backups of both env files as they were: `~/env-backups/` (outside the repo, mode 600).

## The flip (needs the owner's go) — in this order

1. **Tag** `pre-cutover` on main; `pg_dump maludb_os` to a dated file; copy
   `/etc/apache2/sites-enabled/000-default.conf` aside. *(Way back for everything below.)*
2. **Manifest smoke through the assistant** — every action in the manifest still succeeds
   through the actions MCP. This writes real rows, so it runs against records the owner names
   (or a scratch tenant), never silently.
3. **Apache**: bind the PHP vhost to `127.0.0.1:80` and add a public vhost that serves only the
   allow-list above and proxies everything else to `127.0.0.1:3000`. `apachectl configtest`,
   reload, then check: a React page, a write, `/api/v1/health` with a token, an MCP initialize,
   a calendar feed URL. **Reversible**: restore the saved conf and reload.
4. Redirects to 308; the staging host renamed (owner's decision 2 of 2026-09-18).
5. ~~Soak~~ — dropped by the owner's decision 2.
5a. **`mcp/actions_server.py` asks for JSON.** Its `app_post()` sends `HX-Request: true` and
   reads `X-Action-Status` headers — the HTML mode the deletion removes. Switch it to
   `Accept: application/json` (every handler already answers through `json_mode_finish()`),
   re-run `mcp/smoke/*.json`, and only then delete. Found by the 2026-09-19 action smoke.
6. **The deletion (not reversible by redeploy; reversible only from the tag):** `app/views/`
   (263 templates, 19.4k lines), the HTML branch of ~230 controllers (`render_screen()` /
   `view()` calls — JSON mode becomes the only mode), `htmx.min.js` and the jQuery vendor bundle
   the React shell never loads, the legacy cert-study screens and their nav entries (tables
   stay). Mail templates point at the React paths. Action registry regenerated.
7. Tenant provisioning script gains Node + the `maludb-os-web` unit; `CLAUDE.md` loses the
   HTMX rules and the `new-screen` skill reference; requirements (3 copies) and build plan
   (2 copies) synced; tag `react-cutover`.
8. R7: build-plan phases 3–6 resume on the React slice template.

## The owner's decisions (2026-09-19) — none left open

1. **Google sign-in: ported to the React login.** `/auth/google/start` and
   `/auth/google/callback` in the web app relay PHP's two handlers server-side (state in the
   pre-login session, cookie relayed, PHP owns every rule and every activity row); PHP's
   callback answers its one failure sentence as JSON. **When Google is configured,
   `GOOGLE_REDIRECT_URI` and the URI registered at Google must be
   `https://<react host>/auth/google/callback`.** Not configured on this server, so only the
   unconfigured path could be exercised. The PHP pair therefore leaves the public allow-list.
2. **No soak.** The PHP UI "was never completed or tested properly, so it can be deleted as soon
   as the React is ready" — step 5 is dropped; the deletion follows the flip once the owner's
   click-through is done. Ready is the owner's word, not an inference.
3. **The manifest smoke may write to anything.**

## As run (2026-09-19)

1. **Safety net**: tag `pre-cutover`; `pg_dump -Fc maludb_os` (172 tables, verified readable),
   the Apache vhost and `ports.conf` copied to `~/cutover-backups/`.
2. **The agents' door fixed first** (`docs/action-smoke-2026-09-19.md`), and the actions server
   moved to JSON mode — smoke-tested before anything was deleted.
3. **The flip, in two stages so nothing was ever down**: (a) `Listen 127.0.0.1:8080` and the
   internal PHP vhost added beside the old public one; the web app (`API_BASE_URL` via a systemd
   drop-in — `web/.env.local` was not touched) and the actions server (`APP_BASE`) moved to it and
   verified; (b) the public vhost replaced: everything → the React app on :3000, except the
   allow-list. Checked through the real names: `https://subello.com/login` is the React login,
   `/dashboard` and `/reset.php?token=` redirect relatively, `/api/v1/health` answers,
   `/api/v1/session` is no longer public, `/login.php` and `/contacts/index.php` are not PHP.
   The Google pair is not on the allow-list (ported to React).
4. **The deletion**: 249 screen templates (`app/views/` keeps only `emails/`, which `app/mail.php`
   renders); the unported cert-study screens (`attempts`, `events`, `issues`, `members`, `plans`,
   `resources`, `study`, `study-log`, `calendar`, `organizer/exams`, `organizer/health`,
   `dashboard/complete-item.php`); `htmx.min.js`, DataTables, select2 and `assets/js`; the four
   cert-study tools and the legacy screens in the actions server (169 → 165 tools). Legacy-link
   redirects are now permanent (308).
   **What made it safe:** write handlers still render their old HTML after saving (JSON mode
   discards it), so deleting templates naively would have crashed every write after its commit.
   `view()` now renders a missing SCREEN template as nothing, and still throws for a missing
   mail template. Proved by re-running the write smokes with the templates gone.
5. **Regression**: 72 routes across every module `ok` at 1280 and 375; write smokes
   (`mcp/smoke/2`, `4`, `5`) pass apart from correct refusals.

**Not done, deliberately or for want of room — see the plan's last note:** the dead HTML tails
inside ~230 controllers are still there (unreachable, harmless, tidy-up); the tenant
provisioning script does not yet install Node and the web unit; the requirements (3 copies) and
the build plan (2 copies) have not been synced to say the cut-over happened;
`agentview.subello.com` has not been renamed; invitations have no UI.

**Way back:** `sudo cp ~/cutover-backups/000-default.conf.pre-cutover
/etc/apache2/sites-enabled/000-default.conf`, same for `ports.conf`, remove
`/etc/systemd/system/maludb-os-web.service.d/cutover.conf`, `git checkout pre-cutover`, reload
Apache, restart `maludb-os-web` and `maludb-os-actions-mcp`. The database needs no restore for
that — db/103 is compatible with the old code.
