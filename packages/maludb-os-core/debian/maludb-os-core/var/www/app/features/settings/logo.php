<?php
declare(strict_types=1);

/**
 * The company's logo (db/134): one file, uploaded by a super-admin on Business settings and
 * shown in the sidebar header of every signed-in screen in place of the shipped
 * /assets/images/logo-full.png.
 *
 * The shape of the agent photos (app/features/agents/photos.php, db/090): the bytes live under
 * the storage root, outside the document root; the row holds the facts; the media type comes
 * from the file's own bytes, the stored name is the sha256 of those bytes, and the extension is
 * derived from the detected type. The file is reachable only through
 * /settings/business/logo.php, behind the session.
 */

require_once dirname(__DIR__) . '/agents/photos.php';   // storage_root(), the accepted image types

const BUSINESS_LOGO_MAX_BYTES = 2 * 1024 * 1024;         // 2 MB — a mark, not a poster
const BUSINESS_LOGO_TYPES = AGENT_PHOTO_TYPES;           // JPEG, PNG, GIF, WebP (no SVG: it can carry script)

/**
 * Validate the uploaded logo without touching the database.
 *
 * @return array{0: ?array{tmp: string, mime: string, ext: string, size: int, sha256: string}, 1: string[]}
 */
function business_logo_from_request(string $field = 'logo'): array
{
    $file = $_FILES[$field] ?? null;
    if (!is_array($file) || ($file['error'] ?? UPLOAD_ERR_NO_FILE) === UPLOAD_ERR_NO_FILE) {
        return [null, []];                                        // nothing uploaded is not an error
    }

    $error = (int) $file['error'];
    if ($error !== UPLOAD_ERR_OK) {
        return [null, [match ($error) {
            UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE => 'That logo is too large — 2 MB is the limit.',
            UPLOAD_ERR_PARTIAL => 'The logo only uploaded partially — try again.',
            UPLOAD_ERR_NO_TMP_DIR, UPLOAD_ERR_CANT_WRITE => 'The logo could not be saved on the server.',
            default => 'That logo could not be uploaded.',
        }]];
    }

    $tmp = (string) $file['tmp_name'];
    if (!is_uploaded_file($tmp)) {
        return [null, ['That logo could not be uploaded.']];
    }
    $size = (int) ($file['size'] ?? 0);
    if ($size <= 0) {
        return [null, ['That logo is empty.']];
    }
    if ($size > BUSINESS_LOGO_MAX_BYTES) {
        return [null, ['That logo is too large — 2 MB is the limit.']];
    }

    // The file's own bytes decide what it is. $_FILES['type'] is whatever the browser claimed.
    $info = @getimagesize($tmp);
    $type = is_array($info) ? (int) ($info[2] ?? 0) : 0;
    if (!isset(BUSINESS_LOGO_TYPES[$type])) {
        return [null, ['A logo must be a JPEG, PNG, GIF or WebP image.']];
    }
    [$mime, $ext] = BUSINESS_LOGO_TYPES[$type];

    $sha = hash_file('sha256', $tmp);
    if ($sha === false) {
        return [null, ['That logo could not be read.']];
    }

    return [['tmp' => $tmp, 'mime' => $mime, 'ext' => $ext, 'size' => $size, 'sha256' => $sha], []];
}

/**
 * The stored logo's facts, or null when the business still shows the shipped one.
 *
 * @return ?array{logo_path: string, logo_mime: string, logo_size_bytes: int, logo_sha256: string, logo_updated_at: string}
 */
function business_logo_record(PDO $pdo): ?array
{
    $row = $pdo->query('SELECT logo_path, logo_mime, logo_size_bytes, logo_sha256, logo_updated_at
                          FROM business_settings
                         WHERE id = 1 AND logo_path IS NOT NULL')->fetch();
    return $row === false ? null : $row;
}

/**
 * The logo's address for a screen, versioned by the time of the upload so a new picture is a
 * new address (present_agent_avatar() does the same). logo.php ignores the parameter. Null when
 * the shipped logo is in use.
 */
function business_logo_url(PDO $pdo): ?string
{
    $logo = business_logo_record($pdo);
    if ($logo === null) {
        return null;
    }
    $updated = strtotime((string) $logo['logo_updated_at']);
    return '/settings/business/logo.php' . ($updated !== false ? '?v=' . $updated : '');
}

/**
 * Move the validated upload into storage and record it, replacing whatever was there. The old
 * file is deleted only after the new row is written: a logo the database still points at must
 * never be missing from disk, while an orphaned file is merely waste.
 *
 * @throws RuntimeException if the file cannot be stored (the row is left as it was).
 */
function store_business_logo(PDO $pdo, array $logo): void
{
    $old = business_logo_record($pdo);

    $relative = 'business/logo/' . $logo['sha256'] . '.' . $logo['ext'];
    $absolute = storage_root() . '/' . $relative;
    $dir = dirname($absolute);
    if (!is_dir($dir) && !@mkdir($dir, 0o750, true) && !is_dir($dir)) {
        throw new RuntimeException('The logo could not be stored — the storage folder is not writable.');
    }
    if (!@move_uploaded_file($logo['tmp'], $absolute)) {
        throw new RuntimeException('The logo could not be stored — the storage folder is not writable.');
    }
    @chmod($absolute, 0o640);

    $st = $pdo->prepare('UPDATE business_settings
                            SET logo_path = :path, logo_mime = :mime, logo_size_bytes = :size,
                                logo_sha256 = :sha, logo_updated_at = now(), updated_at = now()
                          WHERE id = 1');
    $st->execute(['path' => $relative, 'mime' => $logo['mime'], 'size' => $logo['size'], 'sha' => $logo['sha256']]);

    if ($old !== null && $old['logo_path'] !== $relative) {
        @unlink(storage_root() . '/' . $old['logo_path']);
    }
}

/** Back to the shipped logo: the row first, then the bytes. */
function clear_business_logo(PDO $pdo): void
{
    $old = business_logo_record($pdo);
    if ($old === null) {
        return;
    }
    $pdo->exec('UPDATE business_settings
                   SET logo_path = NULL, logo_mime = NULL, logo_size_bytes = NULL,
                       logo_sha256 = NULL, logo_updated_at = NULL, updated_at = now()
                 WHERE id = 1');
    @unlink(storage_root() . '/' . $old['logo_path']);
}
