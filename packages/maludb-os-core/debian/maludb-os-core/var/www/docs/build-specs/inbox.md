# Build spec: Shared inbox — "what has come in, who is answering it, and how fast?"

2026-09-19 · Module 6 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/057 (`mailboxes`, `mail_threads`, `mail_messages`, `mail_attachments`, `mail_rules`,
`mail_thread_reads`; views `mcp_mailboxes`, `mcp_mail_threads`, `mcp_mail_messages`,
`mcp_mail_attachments`, `mcp_mail_rules`). **No migration is needed.** Manifest "Shared inbox":
9 screens, 15 actions. Tools: `find_mail_threads`, `mail_thread`, `search_mail`,
`mailbox_stats`, `mailbox_rules`.

## Mail in (owner's decision 6: IMAP polling)
- `mcp/inbox_poll.py`, run by the systemd timer `maludb-os-inbox-poll.timer` every 2 minutes as
  `www-data` (units in `docs/deploy/`), single-flight under an advisory lock. For each active
  mailbox with `inbound_kind = 'imap'`, a host and a credential, it opens IMAP over TLS (993),
  reads the messages of the last 3 days in `INBOX` **without marking them read** (`BODY.PEEK[]`),
  and hands each one it has not seen to the ingest. It never deletes or moves mail.
- The credential is a tenant secret (`app/secrets.php` / `mcp/secrets_store.py`, AES-256-GCM)
  holding JSON `{"username": …, "password": …, "port"?: 993, "folder"?: "INBOX"}`. The mailbox
  form takes username and password; nothing ever shows them again.
- **Python parses, PHP files.** The poller turns MIME into a plain JSON message (headers, the
  text body — an HTML-only mail is reduced to text — and attachments written under
  `storage/mail/<mailbox>/`), then runs `php bin/inbox_ingest.php <json>`, which owns every
  database rule so there is one copy of each: de-duplication on `(mailbox, Message-ID)`,
  threading, contact matching, routing rules, tickets (through Helpdesk's `insert_ticket()`, so
  SLA times are right), counters. `inbox_poll.py --eml <file> --mailbox <id>` ingests one saved
  message with no IMAP at all — the seam the smoke uses, since **no real mailbox is connected
  here: the IMAP leg is built and unit-checked, not proven end to end.**
- **Threading:** `In-Reply-To` / `References` against known Message-IDs in the mailbox; else a
  ticket number in the subject (`[T-00042]`) joins that ticket's thread; else an open thread in
  the mailbox with the same normalised subject and the same correspondent in the last 30 days;
  else a new thread. A message on a closed thread reopens it.
- **Matching:** the sender's address against `contacts.email` links the thread's contact and
  company (first message only, never overwritten).
- **Rules** run on the FIRST inbound message of a new thread, in `sort_order`: `assign`
  (`member_id`), `create_ticket` (`category_id?`, `priority?`), `link_organization`
  (`organization_id`), `close`, `mark_spam`, `tag` (`tag` — a tagging with entity type
  `mail_thread`); `stop_after` stops the walk. A bad regex never matches. Then, if no rule made
  one and the mailbox has `auto_create_tickets`, a ticket is opened in the mailbox's default
  category. A ticket made from mail has `origin = 'email'`, the matched contact as requester.
- Attachments: stored by sha256 outside the web root, up to 25 MB each, any type (they are
  somebody else's files, kept as received) — but served only through
  `html/inbox/attachment.php` with `Content-Disposition: attachment` and the view's permission,
  and **filed into Documents only if the Documents module would accept the type**.

## Mail out (owner's decision 7: MaluMail, within its limits)
MaluMail sends one message to a list of recipients from the platform's sending address. It
cannot carry cc, attachments, Reply-To or threading headers. Therefore:
- `mail_send` / `mail_reply` **refuse** `cc` and `attachments` with "not supported yet" rather
  than dropping them silently; the compose screen offers neither. `reply_all` puts the other
  original recipients in `to`.
- A sent message leaves as *"<mailbox from-name>" <MAIL_FROM>*, the mailbox's signature
  appended, and **a reply to it goes to the platform's address, not to the mailbox** — the
  compose and reply forms say so. Recorded OPEN: per-mailbox sending addresses need MaluMail
  sender verification and a Reply-To.
- Outbound rows are `mail_messages` with `direction = 'outbound'`, `sent_by_member_id`, a
  generated Message-ID (so an answer that quotes it threads), and the thread's counters moved.
- **An agent's send pauses for approval** (`mail_message.send`, category `external_send`, seeded
  in db/105). Sending asks a person to confirm.
- Drafts: `mail_draft_save` keeps an `is_draft` row (a new conversation's draft creates its
  thread, which stays out of the inbox until something is sent); `mail_send` / `mail_reply` take
  an optional `draft` (added to the manifest) and remove it on send.

## Who may do what
`app_can_see_mailbox()` (db/057): a super-admin, the admin of the mailbox's department, a
personal mailbox's owner, or an `inbox` grant holder in the mailbox's department (or any, for a
mailbox with no department). A thread's assignee always reads it — that is how an agent handles
one. Writes need `mod:inbox` **and** sight of the thread; the assignee may reply, set status and
mark read. Mailboxes and rules: admin (rules also `mod:inbox`).

## Screens
| Screen | React route | PHP read |
| --- | --- | --- |
| `inbox` | `/inbox?mailbox=&status=&assignee=&unread=&starred=&page=` | `html/inbox/index.php` |
| `mail-thread-view` | `/inbox/threads/{id}` | `html/inbox/threads/view.php` (opening it marks it read) |
| `mail-compose` | `/inbox/compose?mailbox=&to=&organization=&thread=&draft=` | `html/inbox/compose.php` |
| `mail-search` | `/inbox/search?q=&mailbox=&period=` | `html/inbox/search.php` |
| `mailboxes-settings` | `/settings/mailboxes` | `html/settings/mailboxes/index.php` |
| `mailbox-add` / `mailbox-edit` | `/settings/mailboxes/new`, `/settings/mailboxes/{id}/edit` | `…/form.php` |
| `mailbox-rules`, `mail-rule-add` | `/settings/mailboxes/{id}/rules`, `…/rules/new` | `…/rules.php` (the add form is on the same read) |

## Actions
As the manifest lists them; handlers in `html/inbox/` and `html/settings/mailboxes/`.
`mailbox_sync_now` runs the poller for that one mailbox and reports what it said.
`mail_thread_to_ticket` opens a ticket from the thread (requester = its contact, description =
the first message) and links it. `mail_attachment_file` creates a Document from the stored
bytes, optionally in a folder and linked to the thread's company or ticket.
