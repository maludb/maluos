<?php
declare(strict_types=1);

/**
 * An agent's profile photo (db/090). Not a screen and not an action: it answers with the image
 * bytes, or 404.
 *
 * Gate: insider — the same reach as the agent record itself, applied by reading through
 * `mcp_agents` (agent_photo_record()). The bytes live outside the document root, so this is the
 * only way to them: Apache never serves the storage folder, and a member who may not see the
 * agent may not see its face either.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/agents/render.php';
agents_require_files();

require_insider();

$pdo = db();
$id = request_integer('agent');
$photo = $id === null ? null : agent_photo_record($pdo, $id);
if ($photo === null) {
    http_response_code(404);
    exit('No photo.');
}

$path = storage_root() . '/' . $photo['profile_photo_path'];
if (!is_file($path) || !is_readable($path)) {
    // The row says there is a photo and the disk disagrees: log it, and let the screen fall
    // back to initials rather than showing a broken image.
    error_log('agent photo missing on disk: ' . $path);
    http_response_code(404);
    exit('No photo.');
}

// The sha256 of the bytes is a true ETag: the stored name changes whenever the content does.
$etag = '"' . $photo['profile_photo_sha256'] . '"';
header('Content-Type: ' . $photo['profile_photo_mime']);
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
