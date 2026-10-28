# Kernel hosts — os.<domain>, app.<domain> and the launcher (A2)

2026-09-22 · Business OS build plan, phase 7 Part A, step A2. Design: `docs/business-os-integration.md`,
"Hosts and the network layout" and "Identity and single sign-on". Built the same day.

## What it is

One codebase, two faces, decided by the name the browser used:

| Face | Name | Who | What exists there |
| --- | --- | --- | --- |
| Operating system | `os.<domain>` (`OS_HOST`) | Super-admins, and agents by token | Every kernel screen, as before |
| Person | `app.<domain>` (`APP_HOST`) | Every active human | Sign-in (login, 2FA, register, forgot, reset, Google), the **launcher** at `/launcher`, the person's own settings at `/settings` |
| Landing | `subello.com`, `www.subello.com` | Anyone | A static page under `/var/www/landing` on its own Apache virtual host: the three doors — website, applications, operating system (the owner's request, 2026-09-22). Never reaches PHP or React |
| Neither | any other name still reaching the React app | — | Sent on to `app.<domain>`, path and query intact (308) |

Both names are configuration: `OS_HOST` and `APP_HOST` in `config/.env` (PHP) and in the
`maludb-os-web` systemd drop-in (React). Both empty = one face, the operating system, as before
the split; `localhost` and `127.0.0.1` are always the operating system (health checks, the deploy
script). The DNS records and the proxy entries for the two names are the owner's.

## How it is enforced

- **React middleware** (`web/middleware.ts`, `web/lib/face.ts`): decides the face from
  `X-Forwarded-Host`/`Host`; on the person face any path outside the allow-list redirects to
  `/launcher`; a name that is neither redirects to `app.<domain>`; stamps `x-face` on the request.
- **Shell layout** (`web/app/(app)/(shell)/layout.tsx`): on the person face renders `PersonShell`
  (a top bar: business, name, Settings, Sign out — no kernel navigation); on the operating system a
  non-super-admin is redirected to `https://app.<domain>/launcher`.
- **PHP** (`app/bootstrap.php`, `os_face_gate()`): under the os name a signed-in non-super-admin is
  refused on every read and write — 403 JSON, or a redirect to the launcher for a browser — except
  `/api/v1/session.php` (it only says who you are) and `/logout.php`. A localhost caller with an
  action token has no browser and is not judged. This is the guarantee; the layout is the courtesy.

## The launcher

`html/launcher.php` → screen `launcher` (`/launcher`, manifest "Home"). Cards
(`web/components/kit/RecordCard`) for what `mcp_my_applications` admits the person to — a live
access grant of their own or their department's, or everything for a super-admin — minus the
platform's row and the built-in modules; a super-admin also gets **Operating system** →
`https://os.<domain>`. Presenter `present_launcher_application()`; schema `web/lib/schemas/launcher.ts`.
Until A3 a card opens the application's recorded `url` in a new tab; A3 replaces that with the
hand-off token. Logged as a screen view.

## Proven

- `launcher.php` answers for a super-admin (the operating-system card plus the granted
  applications) and for an ordinary user (their grants only).
- Under `X-Forwarded-Host: os.<domain>` an ordinary user's session gets 403 on `/locations/`, 200
  on `/api/v1/session.php`; under `app.<domain>` the same session reads `/launcher.php`.
- The React middleware: `Host: app.<domain>` + `/dashboard` → `/launcher`; `Host: subello.com` or
  `www.subello.com` → the landing page itself at `/` (`web/public/landing` is a symlink to `/var/www/landing`),
  anything else under those names → 307 to `https://app.subello.com/…`; any other unknown name → 307 to `app.`
  (never 308 — browsers cache a permanent redirect, and the 308 this once sent kept the bare name on `app.` after
  the landing page existed; changed 2026-09-25); `Host: os.<domain>` unchanged; `Host: 127.0.0.1:3000` unchanged.

## Not here

Sign-on into an application (A3), the directory API (A4). The bare name is answered by Apache's
landing vhost before the React app sees it; the two kernel names need DNS and proxy entries.
