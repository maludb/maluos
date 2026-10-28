# Kernel services for applications — SMS (K6) and application reads (K7)

*2026-09-28, the owner: "Add the necessary functionality" — what txtSchedules' decisions owe the kernel
(`docs/build-specs/txtschedules-requirements.md` §9): **D6** SMS through the kernel, no application holding a Twilio
key; **D5/D9** one application reading another's data (HR told what time off was taken; txtSchedules reading
Reservations' covers). Both on the internal port, both with the application's token — the pattern of the directory
API (A4) and the chat endpoint (A6). Additive: db/161.*

## K6 — SMS for applications

An application asks; the kernel decides, sends from the business's number, and records it.

```
POST {OS_INTERNAL_URL}/api/v1/notify/sms.php      Bearer <application token>
     {"member_id": 26, "text": "Your Fri 5–11pm shift at Airport was approved.", "reference": "exchange:412"}
→ 202 {"notification": {"id": 91, "status": "queued"}}
→ 422 {"error": {"code": "no_verified_phone" | "not_held" | "opted_out" | "rate_limited" | "invalid", "message": …}}
→ 503 {"error": {"code": "no_sender", …}}                 the business has no notification number yet
GET  {OS_INTERNAL_URL}/api/v1/notify/sms.php?id=91 → {"notification": {"id", "status": queued|sent|failed, "sent_at", "error"}}
```

- **Who can be texted:** a member who (1) holds the application — any live grant, or a super-admin; (2) has a
  **verified** SMS identity in the kernel (`member_channel_identities`, the one-time-code link already on
  `/settings/channels`) — the kernel never learns a number from an application; (3) has not opted out of
  application texts. An application never sees the number.
- **The sender:** the business's **notification number** — an `sms` row of the new `notification_endpoints` (address,
  Twilio account SID in `config`, the auth token a tenant secret by reference), set by a super-admin with
  `bin/notify_endpoint_set.php`. Separate from an assistant's number, so a reply to a shift text never reaches an
  assistant. None set → 503 `no_sender`, and the application falls back to email.
- **The message:** at most 480 characters of the application's text, prefixed with the application's name
  (`txtSchedules: …`); longer → 422 `invalid`. No other person's details belong in it (the application's rule, NF-3).
- **Limits:** 30 texts a member a day per application, 2,000 a day per application → 422 `rate_limited`.
- **Opting out:** a member turns application texts off on `/settings/channels` (per application); Twilio's answer
  21610 (the carrier's STOP) marks the identity opted out too.
- **Delivery:** queued in `application_notifications`, sent by the channels worker that already delivers the
  assistants' messages (`maludb-os-channels`, `channel_deliver_pending()`), five attempts; `sent_at` / `error` kept.
- **Records:** `application.notify` in the activity log (the application, the member, the reference, never the text);
  a super-admin sees the queue on the application's page later (UI owed; MCP tool `application_notifications`).

## K7 — application reads (one application asks another, through the kernel)

A **provider** application shares named read tools; a **consumer** asks the kernel to call one; the kernel calls it
only over a **connection** a super-admin approved, and passes nothing but the arguments and the site.

```
POST {OS_INTERNAL_URL}/api/v1/apps/read.php       Bearer <consumer's application token>
     {"provider": "reservations", "tool": "covers_by_service",
      "arguments": {"from": "2026-10-05", "to": "2026-10-11"}, "location_id": 21}
→ 200 {"result": {…the provider's answer…}, "provider": "reservations", "tool": "covers_by_service"}
→ 403 {"error": {"code": "no_connection" | "not_shared" | "not_at_location", …}}
→ 502 {"error": {"code": "provider_failed", "message": …}}
```

- **Sharing is the provider's to declare** — `maludb-os.json` → `"shares": [{"tool": "covers_by_service",
  "description": "Booked covers per day and service", "scoped": true}]`, recorded by the installer in
  `application_shares`. Its MCP server admits the kernel's own token to **`app_roles` and its shared tools only** (the
  C5 kernel-token rule, widened by the provider's own list).
- **Wanting is the consumer's to declare** — `maludb-os.json` → `"reads": [{"app": "reservations", "tool":
  "covers_by_service", "why": "Expected covers for the staffing forecast"}]`; the installer **proposes** a connection.
- **A connection is a super-admin's decision** — `application_connections(consumer, provider, tool, approved_by,
  approved_at, revoked_at)`; proposed rows wait; `application_connection_approve` / `_revoke` (super), logged.
- **Sites:** for a `scoped` share the consumer names a kernel `location_id`; the kernel checks that **both**
  applications serve that location (a live scope of each) and passes the provider **its own** `scope_id` for it as
  the argument `scope_id`. An unscoped share takes no location.
- **The call:** the kernel's `mcp_call_tool_as_kernel()` (C5) against the provider's MCP endpoints in order; the share's
  own timeout (K26, below; 8 s unless declared); the answer passed back unchanged, capped at 256 kB.
- **Records:** `application.read` in the activity log (consumer, provider, tool, location, outcome, milliseconds —
  never the answer); the call counts toward nothing else.
- **A tool about people (db/162, owner 2026-09-28):** a share flagged `"people": true` answers about members, keyed by the
  kernel's member id — the first is txtSchedules' `time_off_taken` for HR (per-person time off, for pay and records). Only
  a consumer registered for **directory writes** (HR, the one application that changes the directory) may read it: the
  kernel refuses the connection's approval for any other consumer, and refuses the call (403 `people_restricted`) even if a
  connection was approved before the tool was marked. Otherwise the same gates: an approved connection, the site both
  serve. The provider answers only about people at the named site.
- **What it is not:** no writes between applications (a consumer that must change another application asks a person);
  no member identity crosses (a provider's shared tool answers about the site, not about who asked) — the one identity
  that does cross is the consuming application's own (K26).

### K26 — the provider is told who is asking, and a share may ask for a longer call (owner approved 2026-10-06; db/173)

Three applications needed it: Knowledge gates a share by the bases shared *with that application*; Spaces answers a share as the
consumer's expert agent and had to take the agent's id from the consumer's own word; Inventory found the same gap. Until K26 the
kernel passed a provider nothing but the arguments and the site.

- **Who is asking travels in two HTTP headers on every message of the kernel's MCP call**, set by `application_read()` from the
  consumer's own row — never from what the consumer sent: `X-OS-Consumer: <the consumer's app key>` and, when the consumer has an
  expert, `X-OS-Consumer-Agent: <applications.sme_agent_member_id>`. Headers, not arguments, because six of the seven providers
  validate a share's arguments strictly (`extra = forbid`) and an identity in the arguments would have broken their shares; a
  provider's kernel-token gate reads the headers in the same place it reads `Authorization` and trusts them for the same reason:
  only the kernel can mint the token the request carries.
- **Reserved arguments are stripped** before the call: `scope_id` (already), `consumer`, `consumer_agent_id`, `as_agent`. A consumer
  cannot name itself or an agent.
- **A share's timeout is its own:** `shares[].timeout_seconds` (1–60, default 8; clamped) recorded by the installer in
  `application_shares.timeout_seconds` (db/173); the kernel waits that long for the tool's answer (the handshake keeps 8 s). Knowledge's
  `ask` and `search` run the engine and declare 60.
- **Recorded:** `application.read` gains `consumer_agent_id` and `timeout_seconds`.
- **Providers:** Spaces reads `X-OS-Consumer-Agent` into its share door (its `as_agent` argument is gone); Knowledge's three shares
  gate on `X-OS-Consumer` (Phase 4); Reservations, txtSchedules, GL and Consultant Tracking ignore the headers and are unchanged.
  Plugin 0.8.0 `sms-and-reads.md` says how a provider reads them.

## The first uses
| Consumer | Provider | Tool | For |
|---|---|---|---|
| txtSchedules | Reservations | `covers_by_service` (from, to, scope_id) → covers per date and service | the forecast (FR-F2) |
| HR | txtSchedules | `time_off_taken` (from, to, scope_id) → approved time off per member id (a **people** share) | HR's records and pay (D5) — when both are built |

Reservations' `covers_by_service` is added to its admin MCP with the kernel-token rule (ZozoCal repo).

## Plugin
`maludb-os-integration` 0.5.0: `sms-and-reads.md` (both services, the manifest keys `shares` and `reads`, the widened
kernel-token rule); `registration.md` gains `shares`, `reads`. 0.8.0 (K26, 2026-10-06): the two headers a provider may read,
`shares[].timeout_seconds`, the reserved arguments.

## Proof
K6: a member with a verified phone and a grant → queued, then sent (or failed with Twilio's words) by the worker; no
grant → `not_held`; no verified phone → `no_verified_phone`; opted out → `opted_out`; the 31st of the day →
`rate_limited`; no sender → 503; a revoked token → 401. K7: no connection → `no_connection`; a proposed one →
`no_connection`; approved → the provider's answer; a location one side does not serve → `not_at_location`; a tool
not shared → `not_shared`; revoked → `no_connection` again; the provider refusing a kernel token for any other tool.
K26 (`bin/test_app_services.php`, the echo provider `bin/test_app_services_echo.php` on :8097): `timeout_seconds` recorded and clamped;
the provider sees `X-OS-Consumer` and `X-OS-Consumer-Agent`; the consumer's own `consumer`, `consumer_agent_id`, `as_agent` and `scope_id`
stripped; a consumer with no expert sends no agent header; a 2-second share that takes 4 s → 502 `provider_failed` inside 4 s; a 60-second
share that takes 3 s answered; the log row carries the timeout and the agent.
