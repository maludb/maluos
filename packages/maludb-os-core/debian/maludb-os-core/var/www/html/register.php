<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/invitations/queries.php';   // apply_invitation_grants()

header('Cache-Control: no-store');
header('X-Frame-Options: DENY');
header('Referrer-Policy: same-origin');

if (is_logged_in()) {
    redirect('/');
}

$pdo = db();
$googleEnabled = google_enabled();

// A registration link carries the invite token (?token=...). We prefill the invited email.
$rawToken = request_string('token');
$invite = $rawToken !== '' ? find_invitation_by_token($pdo, $rawToken) : null;

$renderForm = function (array $extra = []) use ($rawToken, $invite, $googleEnabled): never {
    echo view('auth-layout.php', [
        'title'   => 'Create account',
        'content' => view('auth/register.php', array_merge([
            'token'         => $rawToken,
            'email'         => $invite['email'] ?? '',
            'googleEnabled' => $googleEnabled,
        ], $extra)),
    ]);
    exit;
};

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'GET') {
    if (wants_json()) {
        // What the PHP form was prefilled with, and no more: the invited address is shown only
        // to the holder of a live invitation token, exactly as the template did.
        $badToken = $rawToken !== '' && $invite === null;
        respond_screen([
            'token' => $badToken ? '' : $rawToken,
            'email' => (string) ($invite['email'] ?? ''),
            'error' => $badToken
                ? 'This invitation link is invalid or has expired. Ask an organizer to resend it.' : null,
        ]);
    }
    if ($rawToken !== '' && $invite === null) {
        $renderForm(['error' => 'This invitation link is invalid or has expired. Ask an organizer to resend it.']);
    }
    $renderForm();
}

require_post();
verify_csrf();

$displayName = request_string('display_name');
$email       = normalize_email(request_string('email'));
$password    = (string) ($_POST['password'] ?? '');
$confirm     = (string) ($_POST['password_confirm'] ?? '');

// The invitation is the authority: registration only succeeds against a valid, unexpired,
// unrevoked invitation for THIS email. Resolve by token when present, else by email.
$invite = $rawToken !== '' ? find_invitation_by_token($pdo, $rawToken) : find_valid_invitation($pdo, $email);

$errors = [];
if ($displayName === '') {
    $errors[] = 'Display name is required.';
}
if ($invite === null || normalize_email($invite['email']) !== $email) {
    $errors[] = 'No valid invitation was found for that email address.';
}
if ($password !== $confirm) {
    $errors[] = 'Passwords do not match.';
}
$errors = array_merge($errors, validate_password($password));

if ($errors !== []) {
    if (wants_json()) {
        respond_invalid($errors);
    }
    $renderForm(['errors' => $errors, 'displayName' => $displayName, 'email' => $invite['email'] ?? $email]);
}

try {
    $pdo->beginTransaction();
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO members (email, password_hash, display_name, role, email_verified_at)
        VALUES (:email, :hash, :name, :role, now())
        RETURNING *
    SQL);
    $st->execute([
        'email' => $email,
        'hash'  => hash_password($password),
        'name'  => $displayName,
        'role'  => $invite['role_granted'],
    ]);
    $member = $st->fetch();
    // The business role, the external flag and the department the invitation carries
    // (app/features/invitations/queries.php) — inside this transaction, so a member is never
    // left half-granted.
    apply_invitation_grants($pdo, $invite, (int) $member['id']);
    mark_invitation_accepted($pdo, (int) $invite['id'], (int) $member['id']);
    log_activity($pdo, 'invite.accept', 'member', (int) $member['id'], ['after' => ['email' => $email]]);
    $pdo->commit();
} catch (PDOException $ex) {
    if ($pdo->inTransaction()) {
        $pdo->rollBack();
    }
    // 23505 = unique violation → the email is already registered.
    $msg = ($ex->getCode() === '23505')
        ? 'An account already exists for that email. Try logging in.'
        : 'We could not create your account. Please try again.';
    error_log('register failed: ' . $ex->getMessage());
    if (wants_json()) {
        json_error($ex->getCode() === '23505' ? 'conflict' : 'register_failed', $msg,
            $ex->getCode() === '23505' ? 409 : 500);
    }
    $renderForm(['error' => $msg, 'displayName' => $displayName]);
}

establish_session($pdo, $member, 'password');
redirect('/');
