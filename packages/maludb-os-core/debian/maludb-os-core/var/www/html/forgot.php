<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/app/bootstrap.php';

header('Cache-Control: no-store');
header('X-Frame-Options: DENY');
header('Referrer-Policy: same-origin');

$pdo = db();
// Generic message either way — never reveals whether an account exists (enumeration defense).
$notice = 'If an account exists for that email, a reset link is on its way.';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'GET') {
    if (wants_json()) {
        respond_screen(['ready' => true]);          // the form needs nothing from the server
    }
    echo view('auth-layout.php', ['title' => 'Reset password', 'content' => view('auth/forgot.php')]);
    exit;
}

require_post();
verify_csrf();

$email = normalize_email(request_string('email'));
$member = $email !== '' ? find_member_by_email($pdo, $email) : null;

if ($member !== null && $member['password_hash'] !== null) {
    $raw = random_token();
    $pdo->prepare(<<<'SQL'
        INSERT INTO password_reset_tokens (member_id, token_hash, expires_at)
        VALUES (:m, :h, now() + interval '1 hour')
    SQL)->execute(['m' => (int) $member['id'], 'h' => hash_token($raw)]);

    send_email($member['email'], 'Reset your password', 'reset', [
        'name' => $member['display_name'],
        'url'  => app_url('/reset.php?token=' . $raw),
    ]);
    log_activity($pdo, 'auth.reset_requested', 'member', (int) $member['id']);
}

// JSON callers get the SAME single sentence whether or not the account exists — this is the
// one answer this endpoint has, in either mode (enumeration defence; owner's decision 1).
if (wants_json()) {
    respond_saved(['notice' => $notice]);
}
echo view('auth-layout.php', ['title' => 'Reset password', 'content' => view('auth/forgot.php', ['notice' => $notice])]);
