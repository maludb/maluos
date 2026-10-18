# Build spec: E-signature — "what is out for signature, and who are we waiting on?"

2026-09-19 · Module 10 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/060 (`signature_providers`, `signature_requests`, `signature_signers`,
`signature_events`; views `mcp_signature_*`) + additive **db/114**. Manifest "E-signature":
5 screens (one public), 8 actions. Tools: `find_signature_requests`, `signature_audit`.

## db/114 (additive)
- `signature_requests`: `document_version_id`, `document_sha256` (what is being signed, fixed
  at send), `executed_render_error` (the last failure to make the executed copy),
  `render_token_hash` + `render_token_expires_at` (the one-time page the PDF service prints).
- `signature_signers`: `signed_name`, `consent_at`, `signature_image_path`, `user_agent`; an
  index on `access_token_hash`.
- Views, columns appended last, security barrier and grants kept: `mcp_signature_requests`
  (+ `document_version_id`, `document_sha256`, `executed_render_error`),
  `mcp_signature_signers` (+ `signed_name`, `ip_address`, `has_drawn_signature`),
  `mcp_signature_events` (+ `ip_address`). Never a token, a hash of one, or an image path.

## Built-in signing only (owner's decision 17)
No outside provider is built: `provider_id` stays NULL, `/settings/signatures` says that
documents are signed on the platform's own page, and `signature_provider_save` answers "no
outside provider is built yet" (it stores nothing — in particular no credential).

**How a signer signs:** a private link `/sign/<token>` → the document (a written page is shown;
a file is offered as a download) → their **typed name**, a **consent tick**, and an **optional
drawn signature** → Sign, or Decline with a reason.
- **Token:** 32 random bytes (64 hex), only its sha256 is stored (`access_token_hash`), looked
  up by hash and re-checked with `hash_equals`; one signer per token; it expires with the
  request (default 30 days when no `expires_at` is given); it works until that signer signs or
  declines. Because only the hash is kept, **a reminder re-issues the link and the earlier one
  stops working** (the mail says so); `php bin/signature_link.php <signer-id>` does the same
  for an operator. Wrong, expired, voided, used or not-yet-your-turn: one plain sentence,
  nothing about the document. Wrong tokens are counted per address in `login_attempts`
  (marker `signing-link`): 20 in 15 minutes and the page stops answering that address.
- **No session, same CSRF:** `/sign/…` is on the web app's PUBLIC list; its server component and
  server action reach PHP on localhost through `web/lib/api.ts` exactly as the login form does —
  `apiPost()` opens PHP's anonymous pre-login session, takes its CSRF token and posts with it, so
  `verify_csrf()` is unchanged. The token is the authority; the session only carries CSRF. The
  PHP endpoints (`html/sign/{view,submit,document,executed}.php`) are NOT on Apache's public
  allow-list — the browser never talks to PHP.
- **What is signed:** at send, the document's current version is fixed on the request with its
  sha256 (the stored file's bytes — `document_versions.sha256`, re-verified against the disk —
  or, for a written page, the sha256 of its Markdown body). If the document's current version
  is no longer that version, **signing is refused** until the request is voided and re-sent.
- **Order:** `sequential` — a signer's link is issued only when everyone before them
  (`sign_order`) has signed; `parallel` — everyone at once. `cc` is recorded and never signs.
  Anyone declining ends the request as `declined`. Void is a member's action with a reason.
- **Trail:** every step is a `signature_events` row — created, sent (per signer), viewed,
  signed, declined, reminded, voided, expired, completed, error — with the IP (the web server's
  forwarded address, believed only from our own server: `client_ip()`), the user agent and the
  document hash in `detail`. Member actions also `log_activity()` under the manifest's names;
  the signer's own steps log `signature_signer.view / sign / decline` with no actor.
- **Drawn signature:** a PNG data URL from a canvas; PHP checks the bytes are a PNG, ≤ 200 KB,
  stores it under `storage/signatures/<request>/` and serves it only inside the executed page
  and to members who can see the request.

## The executed copy
When the last signer signs the request is `completed` **first**; then PHP mints a one-time
render token and asks `maludb-os-pdf` to print `/sign/executed/<render-token>` — a public,
minimal React page fed by `html/sign/executed.php`: a written page in full, then a signature
block per signer (typed name, drawn signature, when, from where), then the audit trail and the
document hash. The PDF becomes a NEW Document (`origin = generated`, the request's department,
linked to the same record) and `signed_document_id`. **A failure never loses a signature:** it
is recorded (`executed_render_error`, an `error` event) and `signature_document_file` — which
also files the copy into a folder — makes it again. OPEN: for a FILE original (a PDF, a Word
file) the executed copy is a certificate that names the file and carries its hash; the original
pages are not re-stamped.

## Mail
`signature-request` / `signature-reminder` templates through MaluMail; the link is
`APP_URL/sign/<token>`. An agent's send or reminder waits for a person (`signature_request.send`
/ `.remind`, seeded db/105). Smoke signers are fresh `example.invalid` addresses per run.

## Who
`mcp_signature_*` decide sight (`app_can_see('signatures', owner, department, …)`). Creating
needs `mod:signatures`, a document the caller can see, and — when linked — a record they can
see. Send and void: `mod:signatures` (the manifest's "admin" is already inside that gate).
Providers: super.

## Screens
`/signatures` (status, entity_type, expiring), `/signatures/new?document=&entity_type=&entity=`,
`/signatures/{id}` (signers, trail, executed copy, send / remind / void / file),
`/settings/signatures`, and the public `/sign/{token}` (+ `/sign/executed/{token}` for the
printer). Public pages use their own minimal layout: no sidebar, no command bar, no Agent View.
