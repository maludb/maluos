<?php
declare(strict_types=1);

/**
 * Agent profile photos: the first files this platform stores (db/090).
 *
 * The shape db/035 wrote down for documents, applied here: the bytes live on disk under the
 * tenant's storage root, OUTSIDE the document root, and the database holds the metadata. They
 * are reachable only through `/agents/photo.php`, which applies the same visibility rule as the
 * agent record itself — an uploaded file is never a URL Apache serves on its own.
 *
 * Nothing the client says about the file is believed. The media type comes from reading the
 * image's own bytes, the stored name is the sha256 of those bytes, and the extension is derived
 * from the detected type — so an upload named `avatar.php` is either a real image stored as
 * `<sha>.jpg`, or it is refused.
 */

const AGENT_PHOTO_MAX_BYTES = 2 * 1024 * 1024;           // 2 MB — an avatar, not a photo library
const AGENT_PHOTO_TYPES = [
    IMAGETYPE_JPEG => ['image/jpeg', 'jpg'],
    IMAGETYPE_PNG  => ['image/png',  'png'],
    IMAGETYPE_GIF  => ['image/gif',  'gif'],
    IMAGETYPE_WEBP => ['image/webp', 'webp'],
];

/** Where uploaded files live. Configurable, because a tenant may put storage on its own volume. */
function storage_root(): string
{
    $root = (string) env('STORAGE_ROOT', '');
    return rtrim($root !== '' ? $root : APP_ROOT . '/storage', '/');
}

/**
 * Validate the uploaded photo without touching the database — called before the agent is
 * written, so a bad file never leaves a half-made agent behind.
 *
 * @return array{0: ?array{tmp: string, mime: string, ext: string, size: int, sha256: string}, 1: string[]}
 */
function agent_photo_from_request(string $field = 'profile_photo'): array
{
    $file = $_FILES[$field] ?? null;
    if (!is_array($file) || ($file['error'] ?? UPLOAD_ERR_NO_FILE) === UPLOAD_ERR_NO_FILE) {
        return [null, []];                                        // nothing uploaded is not an error
    }

    $error = (int) $file['error'];
    if ($error !== UPLOAD_ERR_OK) {
        return [null, [match ($error) {
            UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE => 'That picture is too large — 2 MB is the limit.',
            UPLOAD_ERR_PARTIAL => 'The picture only uploaded partially — try again.',
            UPLOAD_ERR_NO_TMP_DIR, UPLOAD_ERR_CANT_WRITE => 'The picture could not be saved on the server.',
            default => 'That picture could not be uploaded.',
        }]];
    }

    $tmp = (string) $file['tmp_name'];
    if (!is_uploaded_file($tmp)) {
        return [null, ['That picture could not be uploaded.']];
    }
    $size = (int) ($file['size'] ?? 0);
    if ($size <= 0) {
        return [null, ['That picture is empty.']];
    }
    if ($size > AGENT_PHOTO_MAX_BYTES) {
        return [null, ['That picture is too large — 2 MB is the limit.']];
    }

    // The file's own bytes decide what it is. $_FILES['type'] is whatever the browser claimed.
    $info = @getimagesize($tmp);
    $type = is_array($info) ? (int) ($info[2] ?? 0) : 0;
    if (!isset(AGENT_PHOTO_TYPES[$type])) {
        return [null, ['A profile picture must be a JPEG, PNG, GIF or WebP image.']];
    }
    [$mime, $ext] = AGENT_PHOTO_TYPES[$type];

    $sha = hash_file('sha256', $tmp);
    if ($sha === false) {
        return [null, ['That picture could not be read.']];
    }

    return [['tmp' => $tmp, 'mime' => $mime, 'ext' => $ext, 'size' => $size, 'sha256' => $sha], []];
}

/**
 * Move the validated upload into storage and record it, replacing whatever was there. The old
 * file is deleted only after the new row is written: a photo the database still points at must
 * never be missing from disk, while an orphaned file is merely waste.
 *
 * @throws RuntimeException if the file cannot be stored (the row is left as it was).
 */
function store_agent_photo(PDO $pdo, int $memberId, array $photo): void
{
    $old = agent_photo_record($pdo, $memberId);

    $relative = 'agent-photos/' . $memberId . '/' . $photo['sha256'] . '.' . $photo['ext'];
    $absolute = storage_root() . '/' . $relative;
    $dir = dirname($absolute);
    if (!is_dir($dir) && !@mkdir($dir, 0o750, true) && !is_dir($dir)) {
        throw new RuntimeException('The picture could not be stored — the storage folder is not writable.');
    }
    if (!@move_uploaded_file($photo['tmp'], $absolute)) {
        throw new RuntimeException('The picture could not be stored — the storage folder is not writable.');
    }
    @chmod($absolute, 0o640);

    $st = $pdo->prepare('UPDATE agent_profiles
                            SET profile_photo_path = :path, profile_photo_mime = :mime,
                                profile_photo_size_bytes = :size, profile_photo_sha256 = :sha,
                                profile_photo_updated_at = now(), updated_at = now()
                          WHERE member_id = :id');
    $st->execute([
        'path' => $relative, 'mime' => $photo['mime'], 'size' => $photo['size'],
        'sha' => $photo['sha256'], 'id' => $memberId,
    ]);

    if ($old !== null && $old['profile_photo_path'] !== $relative) {
        @unlink(storage_root() . '/' . $old['profile_photo_path']);
    }
}

/** Remove the photo: the row first, then the bytes. */
function clear_agent_photo(PDO $pdo, int $memberId): void
{
    $old = agent_photo_record($pdo, $memberId);
    if ($old === null) {
        return;
    }
    $st = $pdo->prepare('UPDATE agent_profiles
                            SET profile_photo_path = NULL, profile_photo_mime = NULL,
                                profile_photo_size_bytes = NULL, profile_photo_sha256 = NULL,
                                profile_photo_updated_at = NULL, updated_at = now()
                          WHERE member_id = :id');
    $st->execute(['id' => $memberId]);
    @unlink(storage_root() . '/' . $old['profile_photo_path']);
}

/**
 * The stored file's facts, for serving or replacing it. Reads the base table for the path —
 * which `mcp_agents` deliberately does not expose, a server path being no business of a client —
 * but joins the view so the caller only ever learns about an agent they may see.
 */
function agent_photo_record(PDO $pdo, int $memberId): ?array
{
    $st = $pdo->prepare('SELECT ap.profile_photo_path, ap.profile_photo_mime,
                                ap.profile_photo_size_bytes, ap.profile_photo_sha256
                           FROM agent_profiles ap
                           JOIN mcp_agents a ON a.agent_member_id = ap.member_id
                          WHERE ap.member_id = :id AND ap.profile_photo_path IS NOT NULL');
    $st->execute(['id' => $memberId]);
    $row = $st->fetch();
    return $row === false ? null : $row;
}
