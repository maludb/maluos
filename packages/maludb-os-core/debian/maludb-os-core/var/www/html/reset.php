<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/app/bootstrap.php';

header('Cache-Control: no-store');
header('X-Frame-Options: DENY');
header('Referrer-Policy: same-origin');

$pdo = db();

/** Resolve a live (unused, unexpired) reset token to its row. */
$findToken = function (string $raw) use ($pdo): ?array {
    if ($raw === '') {
        return null;
    }
    $st = $pdo->prepare(<<<'SQL'
        SELECT * FROM password_reset_tokens
        WHERE token_hash = :h AND used_at IS NULL AND expires_at > now() LIMIT 1
    SQL);
    $st->execute(['h' => hash_token($raw)]);
    return ($r = $st->fetch()) === false ? null : $r;
};

$rawToken = request_string('token');

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'GET') {
    $tok = $findToken($rawToken);
    if (wants_json()) {
        // Whether the link still works, and nothing about whose it is.
        respond_screen(['valid' => $tok !== null,
                        'error' => $tok === null ? 'This reset link is invalid or has expired.' : null]);
    }
    echo view('auth-layout.php', [
        'title'   => 'Reset password',
        'content' => $tok === null
            ? view('auth/reset.php', ['token' => '', 'error' => 'This reset link is invalid or has expired.'])
            : view('auth/reset.php', ['token' => $rawToken]),
    ]);
    exit;
}

require_post();
verify_csrf();

$tok = $findToken($rawToken);
$password = (string) ($_POST['password'] ?? '');
$confirm  = (string) ($_POST['password_confirm'] ?? '');

$render = function (array $extra) use ($rawToken): never {
    echo view('auth-layout.php', [
        'title'   => 'Reset password',
        'content' => view('auth/reset.php', array_merge(['token' => $rawToken], $extra)),
    ]);
    exit;
};

if ($tok === null) {
    if (wants_json()) {
        json_error('invalid_token', 'This reset link is invalid or has expired.', 410);
    }
    $render(['token' => '', 'error' => 'This reset link is invalid or has expired.']);
}
$errors = validate_password($password);
if ($password !== $confirm) {
    $errors[] = 'Passwords do not match.';
}
if ($errors !== []) {
    if (wants_json()) {
        respond_invalid($errors);
    }
    $render(['errors' => $errors]);
}

$pdo->beginTransaction();
try {
    $pdo->prepare('UPDATE members SET password_hash = :h WHERE id = :id')
        ->execute(['h' => hash_password($password), 'id' => (int) $tok['member_id']]);
    $pdo->prepare('UPDATE password_reset_tokens SET used_at = now() WHERE id = :id')
        ->execute(['id' => (int) $tok['id']]);
    log_activity($pdo, 'auth.reset_completed', 'member', (int) $tok['member_id']);
    $pdo->commit();
} catch (Throwable $ex) {
    if ($pdo->inTransaction()) {
        $pdo->rollBack();
    }
    error_log('reset failed: ' . $ex->getMessage());
    if (wants_json()) {
        json_error('reset_failed', 'We could not reset your password. Please request a new link.', 500);
    }
    $render(['error' => 'We could not reset your password. Please request a new link.']);
}

redirect('/login.php');
