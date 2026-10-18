# Build spec: Content & social — "what are we saying, where, and is it working?"

2026-09-19 · Module 7 of the stubbed modules (`docs/build-specs/stub-modules-decisions.md`).
Schema: db/040 (`channels`, `campaigns`, `content_items`, `content_variants`,
`content_variant_media`, `content_metrics`; views `mcp_channels`, `mcp_campaigns`,
`mcp_content_items`, `mcp_content_variants`, `mcp_content_metrics`) + additive **db/111**.
Manifest "Content & social": 11 screens, 20 actions. Tools: `content_calendar`,
`content_pipeline`, `content_performance`, `channel_health`, `find_content`,
`unapproved_publishing`.

## What is real and what is not (owner's default, decisions file)
**Nothing here posts to an outside network.** No connector exists, so `content_publish` always
answers "not connected yet" (or, for a hand-published channel, "post it yourself, then record
the link"). Planning, writing a variant per channel, review and approval, scheduling (a plan —
a slot on the calendar, not a timer that posts), **marking published with the link**, and
entering metrics by hand are real. `channel_save` takes no credentials and the channel screens
show none; every channel is `not_connected`, and a channel may be set to `connector` mode only
as a statement of intent.

## db/111 (additive)
`mcp_content_variant_media` — the media on a variant: rows of `content_variant_media` joined to
`mcp_content_variants` AND `mcp_documents`, so a caller sees an attachment only if they can see
both the content item and the document. Security barrier; grants to `app_rw`, `app_records_ro`.

## The walk
An **item** is the idea; a **variant** is its words for one channel (one per channel).
`idea` → `draft` (a variant has words) → `in_review` (`content_submit_for_review`; the reviewer
is notified, kind `content_review`) → `approved` | back to `draft` with a note
(`content_request_changes`; the note is kept in the activity trail and shown on the item from
there) → `scheduled` (a variant has a slot) → `published` (a variant was marked published).
`archived` is a shelf: un-archiving puts the item back where its variants say it is.
- **Scheduling and marking published need an approved item** — every item is reviewed, whoever
  wrote it; that is what makes `unapproved_publishing` answer "none". **Approving** is the named
  reviewer's or an admin's; an author who is not an admin cannot approve their own item.
- **Changing approved words un-approves them**: writing a variant on an approved item returns it
  to `draft`. A scheduled variant must be unscheduled before it is edited; a published variant's
  words are never edited.
- A slot must be in the future; times are the caller's wall time unless they carry an offset.
- `content_delete` (admin) is refused once any variant was published. `campaign_delete` (admin)
  leaves its content, expenses and leads in place (the FKs null the link).
- Metrics are snapshots (`source = 'manual'`), only on a published variant; the latest snapshot
  per variant is "how it did".

## Who may do what
`mcp_content_items` admits an item's author and reviewer, and everyone `app_can_see('content', …)`
admits. Writes need `mod:content` and sight of the item — except approve / request changes,
which are the reviewer's even without the grant. Channels are read with the `content` grant and
changed by an admin. Campaign and content deletes are admin. Agents: scheduling and publishing
pause for a person (`content_variant.schedule`, `content_variant.publish`, seeded db/053) and
deletes pause under `*.delete`.

## Screens
| Screen | React route | PHP read |
| --- | --- | --- |
| `content-list` | `/content?status=&campaign=&author=&failed=&q=&page=` | `html/content/index.php` |
| `content-calendar` | `/content/calendar?view=week|month&date=&channel=` | `…/calendar.php` — scheduled and published variants by day, and the channels with nothing coming |
| `content-add` / `-edit` | `/content/new?title=&campaign=&channels=`, `/content/{id}/edit` | `…/form.php` |
| `content-view` | `/content/{id}` | `…/view.php` — variants with media and latest metrics, the review state, the last change request |
| `campaigns-list`, `campaign-add` / `-edit`, `campaign-view` | `/content/campaigns`, `/content/campaigns/new`, `/content/campaigns/{id}(/edit)` | `html/content/campaigns/{index,form,view}.php` — a campaign's content, results, cost (expenses the caller may see) and attributed leads and deals |
| `content-performance` | `/content/performance?period=&channel=&campaign=&metric=` | `…/performance.php` |
| `channels-settings` | `/settings/channels` | `html/settings/channels/index.php` |

## Actions
As the manifest lists them; handlers in `html/content/`, `html/content/campaigns/`,
`html/settings/channels/`. `campaign_update` is a partial update (registered in
`app/partial_update.php`); `content_update` changes only the fields it is sent. Added to the
manifest: `remove` on `content_attach_media` (the undo the manifest names), `q` on
`content-list`, `metric` on `content-performance`.
