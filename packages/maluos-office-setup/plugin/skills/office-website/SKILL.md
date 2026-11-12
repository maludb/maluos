---
name: office-website
description: Turn the starter landing page of a MaluOS office into the business's own website - the public page served at the bare domain and www. Built on Bootstrap 5.3 and htmx as static files. Works on a copy in the operator's home directory, shows what changed, and publishes only on the operator's word. Use when the user asks to "customise the landing page", "build our website", "replace the starter page", "change the home page", "update the website", or invokes /office-website.
---

# Office website: the page at the bare name

Every office answers at its bare domain and `www.` with static files from `/var/www/landing`. First boot
puts a **starter** there: a page that says it is a starter, carries placeholder sections, and tells the
visitor how to replace it. This skill replaces it with the business's own page, and maintains that page
afterwards.

What the site is, and is not:

- Static files only: HTML, CSS, JavaScript, images, fonts. Apache serves them; there is **no PHP** and
  nothing to post a form to on this name.
- **Bootstrap 5.3** (`static/bootstrap.min.css`, `static/bootstrap.bundle.min.js`) and **htmx 2**
  (`static/htmx.min.js`) are in the directory. Nothing is loaded from another site, and nothing should
  be: an office may have no internet, and a visitor's browser should not be sent elsewhere.
- htmx here loads **fragments** from `partials/` into the page (`hx-get="partials/x.html"`). It cannot
  save anything.
- The office's updates never overwrite the directory once it has been changed.

Read `references/bootstrap-htmx.md` before writing any markup. It is the house style for this site.

## The one privileged script

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/landing-site.sh status
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/landing-site.sh checkout ~/website
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/landing-site.sh publish ~/website
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/landing-site.sh restore
```

Never edit `/var/www/landing` in place and never use `sudo` for anything else in this skill. Work in the
copy; the script checks it, backs the live page up and replaces it.

## Phase 1: where things stand

Run `status`. Say in one sentence whether the live page is the starter or already customised, and the
names it is served under.

If `~/website` exists and is not empty, ask whether to continue with it or start again from the live
page (then the operator moves or removes the old copy; do not delete it yourself). Otherwise run
`checkout ~/website`.

## Phase 2: the interview

Ask only what the page needs, a few questions at a time, and accept "skip" for any of them:

1. The business's name as it should appear, and one sentence on what it does and for whom.
2. Which sections it wants. Offer: About, Services or Products (how many, and a line for each), Opening
   hours, Contact (email, telephone, address), a second page (menu, prices, team). The starter has
   About, Services and Contact.
3. Colours and logo. A brand colour as a name or a hex value; a logo or photographs as files the
   operator puts on the office (ask for the path; copy them into `~/website/static/img/`).
4. Whether the public should find it yet. Until they say yes, keep `<meta name="robots"
   content="noindex">`.

Do not invent facts about the business: an address, a telephone number, opening hours, prices, claims
about quality or awards. What the operator has not given stays a visibly marked placeholder
(`class="placeholder-tag"`) or the section is left out.

## Phase 3: write it

Edit the copy in `~/website`:

- `index.html`: replace every block marked `STARTER` with the business's content. Keep the **Sign in**
  link to `https://app.<domain>/` (or `http://` when the office is served over http): it is how the
  business's people reach the office.
- `partials/`: one fragment per piece of content worth its own file.
- `static/site.css`: the brand colour and any styles. Never edit `bootstrap.min.css`.
- More pages are more files beside `index.html` (`menu.html`), each with the same head, navigation and
  footer.

When the content is real, and only then, remove the three starter marks together:

1. the banner block (`<div class="starter-banner" …>`) and the `#customise` instructions section;
2. `<meta name="maluos-landing" content="starter">`;
3. the `STARTER` rules at the end of `static/site.css` and any `placeholder-tag` left in the markup.

Remove `<meta name="robots" content="noindex">` only when the operator has said the public may find
the page.

## Phase 4: show, then publish

Before publishing, show the operator what will go live: the sections in order with their headings and
first lines, the colours, the files added, and anything still a placeholder. A diff against the live
page helps (`diff -ru /var/www/landing ~/website`, the live files are world-readable).

Publish only when they say so:

```bash
sudo ${CLAUDE_PLUGIN_ROOT}/scripts/landing-site.sh publish ~/website
```

Report its PASS and FAIL lines as they are. If it refuses the copy (a symlink, a dot file, a `.php`
file, a missing `index.html`), fix the copy and run it again; do not work around the check.

Then tell the operator where to look: `https://<domain>/` through their proxy, or `http://<domain>/`
on the LAN. If they do not like it, `restore` puts the previous page back.

## Later changes

The same loop: `checkout` into an empty directory (or continue in `~/website` if it is the copy that
was published), edit, show, `publish`. Ten backups are kept.

## What this skill does not do

- A form that sends or stores anything. The site has no server-side code. Offer a `mailto:` link, or
  an application of the office that takes the enquiry.
- DNS, the proxy, certificates: `/office-setup` and the handbook's 30-reverse-proxy.md.
- Anything under `app.` or `os.`: those are the office's own screens.
