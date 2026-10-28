# Company Profile — who the business is, what it sells, and a feed a website can be built from

Spec written 2026-09-20; **approved by the owner the same day and built** — see "Built" below. Post-cut-over slice: React screens, template-less PHP handlers
(exemplar `html/team/invitations/`), reads through whitelist presenters.

## What exists today (checked, not assumed)

- **No company profile.** Nothing in the requirements, the build plan or the code describes the
  business to the outside world.
- **Settings → Business** (`/settings/business`, table `business_settings`, super only) holds the
  operating settings: business name, legal name, currency, timezone, fiscal year, payment terms.
  The table also has `address`, `email`, `phone`, `website` and `tax_id` — **but no screen edits
  them and no presenter sends them** (`app/features/settings/present.php` says so). Today only
  `business_name` = "MaluDb OS" is filled.
- **What it sells** lives in two places: `catalog_items` (5 rows — the sellable lines quotes and
  invoices use: name, description, unit, price) and `products` (16 rows — inventory: SKU, cost,
  stock). Neither has public copy, an image, or a notion of "show this to the world".
- Building blocks already there: multipart uploads through `web/lib/api.ts`, the closed download
  relay (`web/app/api/download/route.ts`), the bearer-token API (`html/api/v1/`, `app/api/bootstrap.php`)
  and its Apache allow-list, and the records MCP server.

## The owner's four decisions (2026-09-20)

| # | Decision |
|---|---|
| 1 | **Products: both** — curated catalog items and inventory products, *plus* free-form showcase entries for things that are not sellable records |
| 2 | **Website feed: token API + MCP tool** — `GET /api/v1/company-profile` behind a bearer token, and a read tool `company_profile`. Nothing is public without a token |
| 3 | **Placement: a new `/company` page** in the main navigation — everyone inside reads it, super-admins edit; identity fields stay in `business_settings` (one source of truth) |
| 4 | **Images: uploads** — logo, hero image, one image per product |

## Schema — one additive migration (`db/NNN_company_profile.sql`, next free number at build time)

**`company_profile`** — singleton (`id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1)`), seeded empty.
`tagline` (≤160), `about` (text), `mission` (text), `founded_year` (1800–this year), `industry`,
`headquarters` (free text: "Chicago, IL"), `team_size` (free text: "11–50"),
`social_links jsonb` (array of `{label, url}`, ≤12, https only), `logo_media_id`, `hero_media_id`,
`is_published boolean DEFAULT false`, `published_at`, `published_by`, `updated_by`, timestamps.

Identity is **not copied**: name, legal name, address, email, phone and website are read from
`business_settings`. The profile form edits `address`, `email`, `phone`, `website` there — the
first screen that can. `tax_id` stays off the profile and out of the feed.

**`company_profile_items`** — the "products" list. `id`, `kind` (`catalog_item` | `product` |
`custom`), `catalog_item_id` / `product_id` (FK, `ON DELETE CASCADE`; exactly the one the kind
names, none for `custom` — CHECK), `title` (required for `custom`; an optional override
otherwise), `blurb` (≤200, the card line), `description` (text), `image_media_id`,
`show_price boolean DEFAULT false`, `price_text` (`custom` only: "From $49 / month"),
`link_url` (https), `display_order integer`, `is_visible boolean DEFAULT true`, `created_by`,
timestamps. One row per catalog item and per product (partial unique indexes).

**`company_profile_media`** — `id`, `slot` (`logo` | `hero` | `item`), `storage_path` (under the
documents store root, own subdirectory `company/`), `original_name`, `mime`
(`image/png` | `image/jpeg` | `image/webp` | `image/svg+xml` for the logo only), `bytes`
(≤ 5 MB), `sha256`, `width`, `height`, `uploaded_by`, `created_at`. Bytes are checked
(`getimagesize`; SVG: no script, no external reference) — a renamed file is refused.

**Views** (`WITH (security_barrier = true)`, granted to `app_records_ro`):
`mcp_company_profile` (the singleton joined to the business identity, no `tax_id`) and
`mcp_company_profile_items` (each item with its source's name, unit, price and currency resolved;
an archived source hides the item). Insiders only — an External (portal customer) reads neither.

Archiving a catalog item or product hides it from the profile; deleting one removes its row
(`CASCADE`). Nothing here changes `catalog_items`, `products` or `business_settings` columns.

## Screens (React, Bootstrap nxl, no modals, 375px)

| Route | Screen id | Gate | What |
|---|---|---|---|
| `/company` | `company-profile` | all insiders | The profile as a visitor would meet it: logo, name, tagline, hero, about, mission, facts (founded, industry, headquarters, team size), contact, social links, product cards in display order. For a super-admin: **Edit**, **Add a product**, per-card edit / up / down / hide, and a **Website feed** card — publish state, the endpoint, download JSON / Markdown |
| `/company/edit` | `company-profile-edit` | super | Full-page form: contact (address, email, phone, website → `business_settings`), story, facts, social links (repeatable rows), logo and hero upload / remove. Business and legal name are shown read-only with a link to Settings → Business |
| `/company/items/new`, `/company/items/{id}/edit` | `company-profile-item-form` | super | Kind first; `catalog_item` / `product` then offers the sources not yet on the profile (name · price), and shows what the record already says so the blurb does not have to repeat it; `custom` asks for a title. Image upload, show price, link, visible |

Navigation: one entry, **Company**, in the main menu (id `nav-company`), visible to every insider.
No new module: the profile belongs to the platform application that owns business settings, so it
needs no module grant — reading is every insider's, editing is `super` (as business settings are).

## Actions (manifest rows; every handler: `require_post()` + `verify_csrf()` + gate + `log_activity()`, template-less → `emit_action_status()` + `respond_invalid()`)

| Action | Handler | Fields | Undo | Approval | Log | Gate |
|---|---|---|---|---|---|---|
| `company_profile_update` | `/company/save.php` | tagline, about, mission, founded_year, industry, headquarters, team_size, social_links, address, email, phone, website | restore prior | ✔ | `company_profile.update` | super |
| `company_profile_media_set` | `/company/media-set.php` | **slot** (logo/hero), **file** | restore prior | | `company_profile.media_set` | super |
| `company_profile_media_remove` | `/company/media-remove.php` | **slot** | set again | | `company_profile.media_remove` | super |
| `company_profile_item_save` | `/company/items/save.php` | item, **kind**, catalog_item / product, title, blurb, description, show_price, price_text, link_url, is_visible, file | restore prior / delete new | | `company_profile_item.save` | super |
| `company_profile_item_move` | `/company/items/move.php` | **item**, **direction** (up/down) | move back | | `company_profile_item.move` | super |
| `company_profile_item_delete` | `/company/items/delete.php` | **item** | add again | | `company_profile_item.delete` | super |
| `company_profile_publish` | `/company/publish.php` | **published** (true/false) | toggle back | ✔ **send** | `company_profile.publish` | super |

`company_profile_item_save` is registered in `app/partial_update.php` (an agent's update sends the
item and what changes). Agents are always `user`, so none of these is theirs unless a person
grants it; **publishing is outward-facing and always pauses for a person when an agent asks**
(approval policy `company_profile.publish`, seeded like `ticket.reply`).

## The website feed

**`GET /api/v1/company-profile`** — bearer token (`api_authenticate()`), any insider's token,
logged as `api.company_profile.read`. `404 not_published` until the profile is published, so a
half-written profile never reaches a website. One document:

```json
{
  "schema": "business-os.company-profile/1",
  "generated_at": "2026-09-20T14:03:11Z",
  "published_at": "2026-09-20T13:58:40Z",
  "company": {
    "name": "…", "legal_name": "…", "tagline": "…", "about": "…", "mission": "…",
    "founded_year": 2019, "industry": "…", "headquarters": "…", "team_size": "…",
    "contact": { "email": "…", "phone": "…", "website": "…",
                 "address": { "line1": "…", "line2": null, "city": "…", "region": "…", "postal_code": "…", "country": "…" } },
    "social": [ { "label": "LinkedIn", "url": "https://…" } ],
    "logo": { "url": "/api/v1/company-profile-media?id=3", "mime": "image/png", "width": 512, "height": 512, "sha256": "…" },
    "hero": null
  },
  "products": [
    { "id": 7, "kind": "catalog_item", "name": "…", "blurb": "…", "description": "…", "unit": "hour",
      "price": { "value": "150.00", "currency": "USD", "display": "$150.00" },
      "link_url": null, "image": { "url": "…", "mime": "image/jpeg", "width": 1200, "height": 800, "sha256": "…" } }
  ]
}
```

`price` is `null` unless the item says *show price*; hidden items and items whose source is
archived are left out; `about`, `mission` and `description` are plain text with line breaks (a
website renders paragraphs — no HTML is stored or sent). **`GET /api/v1/company-profile-media?id=`**
streams one image under the same token, only media the published profile references. A static
site fetches both at build time; `sha256` tells it when an image changed.

Both paths join the Apache allow-list (`docs/deploy/apache-react-cutover.conf` and the live vhost)
— **the one step that needs root**, handed to the owner as a two-line change.

**MCP read tool `company_profile`** (records server, insider): *"Call it when asked what the
company does, what it sells, how to reach it, or to build or update its website."* Returns the
same document from `mcp_company_profile` + `mcp_company_profile_items`, published or not, with
`is_published` stated. Params: `include_hidden?` (super only).

**Exports from the screen**: `/company/export.php?format=json|md` through the closed download
relay — the same document, and a Markdown rendering a person can paste into a site generator.
Logged `company_profile.export`.

## Done means

`php -l`, `npx tsc --noEmit`, `web/scripts/deploy.sh`; `verify.sh` as members 1 (super), 5 and 6 on
`/company` (and as 1 on the edit and item forms) at 1280 and 375; the write path smoked through the
agents' door with an action token (`mcp/smoke/`), including a refused upload (a text file named
`.png`) and an agent's publish pausing for approval; the feed read with a minted token before and
after publishing (404, then the document), media fetched, an unknown media id 404; the MCP tool
answered; payloads read once for anything the screen does not show (`tax_id` must be nowhere);
action registry rebuilt; manifest, tool surface, schema doc and questions doc updated; **the
requirements (three copies) and build plan (two copies) synced** with a short "Company Profile"
entry; done-note in `docs/react-migration-plan.md`; one commit, explicit paths.

## Built *(2026-09-20)* — as run on this server

| Check | Result |
|---|---|
| Schema | `db/120_company_profile.sql` applied: three tables, two insider-only views, the `company_profile.publish` approval policy. Additive; nothing existing changed |
| Write path through the agents' door | `mcp/smoke/21-company-profile.json` — **39/39**. A tool that sends one field leaves the rest as they were (singleton and cards both); `founded_year=1492`, `javascript:` as a website, a bad email, an `http://` link, a showcase card with no title, a catalog item already on the profile and an unknown product are each refused in words; destructive actions ask for confirmation; the run leaves no card, no tagline, unpublished |
| Pictures | A text file named `fake.png` sent as `image/png` → *"A picture must be a PNG, JPEG or WebP image."* (the bytes decide). Real uploads stored as `storage/company/<sha256>.<ext>`, mode 640, outside the web root; replacing the logo drops the old row **and** its file; an unknown id and a bad slot are refused |
| Screens | `verify.sh` ok at 1280 and 375 for `/company`, `/company/edit`, `/company/items/new`, `/company/items/{id}/edit` as member 1; `/company` as Dana (dept-admin) and Sam (user); Sam is **refused** `/company/edit`. `tsc` clean |
| The browser's own path | `web/scripts/probe-company.mjs`: impostor refused inside the form, logo replaced, a social-link row added and the profile saved (lands on `/company?saved=1`), a card moved down and back — no page errors. So `social_url[]` and files survive the server action |
| Website feed | No token → 401. Unpublished → `404 not_published` (media too). Published → the document (`business-os.company-profile/1`): company, contact with `postal_code`, social links, logo with width/height/sha256, the two visible cards — the catalog item with `{"value":"180.00","currency":"USD"}`, the showcase card with its own price words. **No `tax_id`, no storage path, no hidden card.** Media: logo and card image 200 `image/png`; unknown id and `id=abc` → 404. Unpublished again → 404; revoked token → 401 |
| MCP tool | `company_profile` as member 1 with `include_hidden` returns the hidden card; as Sam the same call does not; an External (member 46) gets *"internal to the business"* |

**Changed from the spec.** (1) **No SVG**, even for the logo: an SVG is a document that can carry script, `getimagesize()` cannot read one, and sanitising it is a project of its own — PNG, JPEG and WebP only. (2) The manifest has `company_profile_item_create` **and** `company_profile_item_update` on the one handler, because the registry builder understands exactly *"any field of <create action>"* and nothing looser — my first wording gave the update tool no fields, and the smoke run caught it. (3) The singleton has no record id for `app/partial_update.php` to key on, so `save.php` itself treats an action-token request's unsent fields as unchanged. (4) The feed document also says `is_published`. (5) Exports are open to every insider (they can read all of it on the page); the buttons sit on the super-admin's feed card.

**Worth knowing.** Agents are always `user`, and every action here is `super` — so today no agent can reach them at all, and the publish approval policy is a second lock behind the gate, not the first. The profile currently holds **sample words I wrote to show the page** (tagline, about, mission, facts, Chicago, `subello.com`, a GitHub link), two sample cards and three solid-colour test pictures; it is **unpublished**. Replace them with the real ones.

**Apache allow-list — done 2026-09-20.** The owner added `company-profile|company-profile-media` to the two `/api/v1/` rules in the live vhost; Apache was reloaded afterwards (the edit alone changed nothing — until the reload the public port still sent the path to the React app's login redirect). Checked on the public port: no token → 401 JSON; a token with the profile unpublished → `404 not_published`. The repo copy differs from the live file only by its one comment line.

## Not in this slice

- **The website itself.** This slice produces the source; building or hosting a site from it is a
  separate piece of work (an agent with the `company_profile` tool is the obvious builder).
- An unauthenticated public URL (decision 2), multiple profiles / brands, translations,
  rich-text or HTML content, image resizing or cropping, testimonials / team pages.

## Open Questions

| # | Question | Default taken |
|---|---|---|
| 1 | Which token may read the feed? | Any insider's API token (the profile is what every insider can already see); Externals never |
| 2 | Should editing the profile be delegable below super-admin (a marketing dept-admin)? | No — super only, as business settings are; widen later with a grant if wanted |
| 3 | Does unpublishing need approval too? | No — pulling the feed back is always allowed at once |
