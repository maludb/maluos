<?php
declare(strict_types=1);

/**
 * The company's logo (db/134). Not a screen and not an action: it answers with the image
 * bytes, or 404 when the business still shows the shipped one.
 *
 * Gate: signed in — the logo heads every signed-in screen, and nobody else sees the shell. The
 * bytes live outside the document root, so this is the only way to them; the browser reaches
 * it through the web app's picture relay (web/app/api/avatar), never directly.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/logo.php';

require_login();

$logo = business_logo_record(db());
if ($logo === null) {
    http_response_code(404);
    exit('No logo.');
}

$path = storage_root() . '/' . $logo['logo_path'];
if (!is_file($path) || !is_readable($path)) {
    // The row says there is a logo and the disk disagrees: log it, and let the shell fall
    // back to the shipped logo rather than show a broken image.
    error_log('business logo missing on disk: ' . $path);
    http_response_code(404);
    exit('No logo.');
}

// The sha256 of the bytes is a true ETag: the stored name changes whenever the content does.
$etag = '"' . $logo['logo_sha256'] . '"';
header('Content-Type: ' . $logo['logo_mime']);
header('Cache-Control: private, max-age=300');
header('ETag: ' . $etag);
header('X-Content-Type-Options: nosniff');
header('Content-Disposition: inline');

if (trim((string) ($_SERVER['HTTP_IF_NONE_MATCH'] ?? '')) === $etag) {
    http_response_code(304);
    exit;
}

header('Content-Length: ' . (string) filesize($path));
readfile($path);
