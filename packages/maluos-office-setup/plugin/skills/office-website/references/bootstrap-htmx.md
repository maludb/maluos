# Bootstrap 5.3 and htmx on the office's landing page

The rules for markup on this site. They keep the page consistent, readable on a phone, and free of
anything the server cannot do.

## The page skeleton

Every page has the same head and the same three scripts, with relative paths:

```html
<!doctype html>
<html lang="en" data-bs-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page title | Business name</title>
<meta name="description" content="One sentence.">
<link href="static/bootstrap.min.css" rel="stylesheet">
<link href="static/site.css" rel="stylesheet">
</head>
<body>
  <nav class="navbar navbar-expand-md border-bottom bg-body">…</nav>
  <main>…</main>
  <footer class="border-top py-4">…</footer>
  <script src="static/bootstrap.bundle.min.js"></script>
  <script src="static/htmx.min.js"></script>
</body>
</html>
```

- Never a CDN, a web font service, an analytics script or an embed that loads from another site
  without the operator asking for that service by name.
- One `<h1>` per page. Sections are `<section id="…" class="py-5">` with a `.container` inside.

## Layout

- The grid: `.container` > `.row.g-3` (or `g-4`) > `.col-md-6`, `.col-md-4`, `.col-lg-8`. Design for
  375 px first: a column class without a breakpoint only when it must hold on a phone.
- Spacing with utilities (`py-5`, `mb-3`, `gap-2`), not with new CSS.
- Alternate section backgrounds with `bg-body` and `bg-body-tertiary`. These follow light and dark.
- Cards for lists of like things: `.card.h-100 > .card-body > .card-title + .card-text`.
- Buttons: one `.btn-primary` per view for the main action; others `.btn-outline-secondary`.
- Tables (opening hours, prices): `.table` inside `.table-responsive`.
- Images: `class="img-fluid rounded"`, always `alt`, `width` and `height`, `loading="lazy"` below the
  first screen. Put files in `static/img/`. Keep a photograph under 300 kB.

## Colour and type

- Use Bootstrap's colour roles (`text-body-secondary`, `bg-primary-subtle`, `border`), never a fixed
  hex in the markup, so dark mode keeps working.
- The brand colour is set once in `static/site.css`:

```css
:root { --bs-primary: #1f6f4a; --bs-primary-rgb: 31, 111, 74; --bs-link-color-rgb: 31, 111, 74; --bs-link-hover-color-rgb: 24, 90, 60; }
.btn-primary { --bs-btn-bg: #1f6f4a; --bs-btn-border-color: #1f6f4a; --bs-btn-hover-bg: #185a3c; --bs-btn-hover-border-color: #185a3c; --bs-btn-active-bg: #154d34; }
[data-bs-theme="dark"] { --bs-primary-bg-subtle: #10281d; }
```

- Check the brand colour against white text for the button (contrast 4.5:1 or better); darken it if
  not.
- System fonts (Bootstrap's default stack). A custom font only as files in `static/fonts/` with
  `@font-face` in `site.css`.

## Components that need JavaScript

`bootstrap.bundle.min.js` is loaded, so the navbar toggler, collapse, accordion, carousel, dropdown,
tabs and offcanvas work from data attributes alone (`data-bs-toggle="collapse"
data-bs-target="#nav"`). Write no JavaScript for them. Avoid modals for content; a section or a page
reads better and works without script.

## htmx on a files-only site

htmx can fetch a file and put it in the page. That is all it can do here: there is no server code.

```html
<div id="hours">
  <button class="btn btn-outline-primary" hx-get="partials/hours.html" hx-target="#hours" hx-swap="innerHTML">Opening hours</button>
</div>
```

- A fragment in `partials/` has no `<html>`, `<head>` or `<body>`: only the markup that goes into the
  target.
- Load on arrival with `hx-trigger="load"`, when scrolled to with `hx-trigger="revealed"`.
- Tabs or a menu by section: several links with `hx-get` to different fragments and one `hx-target`.
  Add `hx-push-url="false"`; the fragments are not pages.
- Only `hx-get`. Never `hx-post`, `hx-put` or `hx-delete`: Apache answers 405 or serves the file, and
  nothing is saved.
- Content that matters to a search engine or must be readable without JavaScript belongs in the page
  itself, not in a fragment.

## Forms

There is nowhere on this name to send a form. Use:

- `<a class="btn btn-primary" href="mailto:hello@example.com?subject=Enquiry">Email us</a>`
- a link to an application of the office that takes the request, when one is installed;
- a service the operator names, with its own form address, stated to them as loading from elsewhere.

Never write a form whose `action` points at this site.

## Before publishing

- Every `STARTER` mark dealt with: replaced, or deliberately kept and said so.
- No `__DOMAIN__` left, no `Your Company`, no `placeholder-tag` unless the operator knows.
- Links to `app.<domain>` use the office's scheme.
- Every page opens at 375 px without sideways scrolling; the navbar collapses and opens.
- Every image has `alt`; every link has words, not "click here".
- Only files a static site serves: no dot files, no symlinks, no `.php`.
