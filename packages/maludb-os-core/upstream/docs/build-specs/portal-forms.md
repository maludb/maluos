# Build spec: Portal & Forms — "what can a customer see and ask, and what came in through our forms?"

2026-09-20 · Module 11 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/061 (`forms`, `form_fields`, `form_submissions`, `portal_settings`; views `mcp_forms`,
`mcp_form_fields`, `mcp_form_submissions`, `mcp_portal_settings`), `record_shares` (db/030) and
the External flag + additive **db/115**. Manifest "Customer portal & forms": 9 screens and 10
actions, plus the three portal screens and two portal actions listed under Tickets (their PHP
was built with Helpdesk). Tools: `find_forms`, `form_submissions`, `portal_status`.

## Two addresses, two audiences
- **`/forms` is the insiders' module** — forms, their fields, submissions, and (under
  `/settings/portal`) what the portal shows. The Portal application row said `/portal/`; db/115
  points it at `/forms/`, which is where an insider opens it.
- **`/portal` is what an External person sees** (owner's decision 18): its own minimal layout —
  the business name, their name, Log out; no module sidebar, no command bar, no Agent View.
  **An External member who opens a workspace URL is sent to `/portal`** by the `(shell)` layout;
  PHP remains the real gate (`require_insider()`, `require_module()`). An insider who opens
  `/portal` gets a plain note and a link back. A disabled portal (`is_enabled = false`) tells an
  External person so and shows nothing else.

## What the portal shows
Only what is already scoped to an External caller by the views — nothing is widened:
| Area | Setting | Read | State |
| --- | --- | --- | --- |
| Requests | `show_tickets`, `allow_ticket_create` | `mcp_tickets` where the requester is the caller (Helpdesk's endpoints) | ON |
| Invoices | `show_invoices` | `mcp_invoices` — never a draft for an External; their shared company's | ON (list; no PDF, **no online payment: "not available yet"**) |
| Quotes | `show_quotes` | `mcp_quotes` — same rule | ON |
| Projects | `show_projects` | `mcp_projects` — shared company's or a project they are on; the rate is masked by the view | ON (name, status, progress) |
| Documents | `show_documents` | `mcp_documents` — shared one by one (`record_shares` on the document) | ON, downloaded through a portal endpoint that asks the view |
| Appointments | `show_appointments` | `mcp_appointments` is `app_is_insider()` only | **OFF — recorded OPEN**; the setting is stored and the settings screen says it is not available yet |

## Inviting a customer (`portal_access_invite`)
An External invitation for an email and a company: `invitations.is_external_granted = true` and
— db/115 — `invitations.share_organization_id`. When the person registers (password or Google),
`apply_invitation_grants()` makes them External and **shares that one company with them**
(`record_shares`, entity `organization`), which is what the views key off. `sections[]` is
refused if given: the portal's areas are business-wide settings; there is no per-customer
switch in the schema (OPEN). Agent approval: `send`. The mail is the ordinary invitation mail.
`bin/invitation_link.php <invitation-id>` re-issues a link for an operator (the raw token is
never stored) — the smoke uses it, since the mail cannot be read.

## Forms
- A form is `draft` → `published` → `closed` (and back to published). Publishing needs at least
  one field. The slug is the public address: lower-case letters, digits and dashes, unique,
  generated from the name when blank.
- Field kinds are the schema's. **`file` is not offered**: uploads from strangers are not
  accepted on public forms (OPEN). `hidden` carries a fixed value (its placeholder). Options for
  `select` / `multiselect` are one per line.
- `redirect_url` is a relative path starting with one `/` or an `https://` URL — anything else is
  refused (an open redirect is a defect). `notify_members` are insiders.
- `maps_to` says what a field means when a record is made: `contact.full_name`, `contact.email`,
  `contact.phone`, `contact.job_title`, `contact.company` (kept as a note — **a stranger's form
  never creates a company**), `ticket.subject`, `ticket.description`, `deal.title`, `deal.value`,
  `appointment.starts_at`, `notes`.

## The public form (`/f/{slug}`)
A PUBLIC React route in the `(public)` layout (middleware PUBLIC list). The browser never talks
to PHP: the page reads `html/f/view.php`, the server action posts to `html/f/submit.php` with
the anonymous pre-login session's CSRF token, as the login and signing pages do.
- Only a published, unarchived form answers; `requires_login` forms answer only a signed-in
  caller (the portal's support form) and record `submitted_by`.
- **Spam (decision: honeypot + rate limit, no outside service).** A hidden field a person never
  sees: if it is filled the visitor gets the ordinary thank-you and the submission is stored
  with `status = 'spam'` (the schema's way — PF8 asks what was marked spam), creates nothing,
  notifies nobody and is not counted. Rate limit: 5 submissions per form per address per 10
  minutes (`login_attempts`, marker `public-form-<id>`), answered with a plain "try again later".
  At most 40 fields, 5,000 characters per value (10,000 for a textarea), unknown keys ignored,
  values stored as text and shown escaped.
- **What a submission does** (manifest, "Public form endpoint"): `submit_action` runs at once for
  `create_contact`, `create_ticket` and `create_deal` — the contact is matched by email before
  one is made; the ticket has origin `portal` (the closest the check constraint allows to "it
  came in from outside through a form") with the contact as requester; the deal lands in the form's pipeline
  (or the default) at its first stage. `create_appointment` is **not automatic** — a stranger's
  date is a wish, not a booking — it waits as `new` for a person (OPEN). `none` always waits.
  Activity: `form_submission.create` (source `portal`), plus the created record's own event.
- Notifications: an in-app notification to each `notify_members` insider and to the assignee.

## Working submissions
`form_submission_process` (mod:portal or the form's department): make a contact, ticket, deal
or appointment from a waiting submission (`create`), optionally `assign_to`, with a `note`;
`form_submission_mark_spam` (toggle) and `form_submission_reject` (reason). A processed
submission shows the records it made.

## Screens
| Screen | React route | PHP read |
| --- | --- | --- |
| `forms-list` | `/forms?status=&kind=` | `html/forms/index.php` |
| `form-add` / `form-edit` | `/forms/new?kind=&submit_action=`, `/forms/{id}/edit` | `html/forms/form.php` |
| `form-view` | `/forms/{id}` | `html/forms/view.php` — fields, recent submissions, conversion |
| `form-fields` | `/forms/{id}/fields` | `html/forms/fields.php` |
| `form-submissions` | `/forms/submissions?form=&status=&period=` | `html/forms/submissions/index.php` |
| `form-submission-view` | `/forms/submissions/{id}` | `html/forms/submissions/view.php` |
| `public-form` | `/f/{slug}` | `html/f/view.php` |
| `portal-settings` | `/settings/portal` | `html/settings/portal/index.php` |
| `portal-home` | `/portal` | `html/portal/index.php` |
| `portal-request-add` / `-view` | `/portal/requests/new`, `/portal/requests/{id}` | Helpdesk's `html/portal/requests/*` |
