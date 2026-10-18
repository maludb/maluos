<?php
declare(strict_types=1);

/**
 * `/estate/` — kept only so old links and bookmarks land somewhere sane.
 *
 * Work Locations used to be two screens: a tree map here and a table at `/locations/`. The
 * tree was unusable and offered no way to edit anything (owner, 2026-09-18), so the table is
 * now the one Work Locations screen and this URL redirects to it. HTMX navigations need
 * HX-Redirect — a 302 would be followed by the XHR and swapped into the page-content region
 * with no URL change, leaving the address bar on a screen that no longer exists.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';

if (($_SERVER['HTTP_HX_REQUEST'] ?? '') === 'true') {
    header('HX-Redirect: /locations/');
    exit;
}
header('Location: /locations/', true, 302);
