<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/app/bootstrap.php';

// Auth pages get no-store + anti-clickjacking headers.
header('Cache-Control: no-store');
header('X-Frame-Options: DENY');
header('Referrer-Policy: same-origin');

if (is_logged_in()) {
    redirect('/');
}

$next = safe_next(request_string('next', '/'));
$googleEnabled = google_enabled();

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'GET') {
    echo view('auth-layout.php', [
        'title'   => 'Login',
        'content' => view('auth/login.php', [
            'next' => $next, 'googleEnabled' => $googleEnabled,
            'notice' => $_GET['registered'] ?? '' ? 'Account created — please log in.' : '',
        ]),
    ]);
    exit;
}

require_post();
verify_csrf();

$pdo = db();
$email = request_string('email');
$password = (string) ($_POST['password'] ?? '');
$ip = client_ip();

$renderError = function (string $msg, int $code = 200) use ($email, $next, $googleEnabled): never {
    if (wants_json()) {
        json_error($code === 429 ? 'rate_limited' : 'invalid_credentials', $msg, $code === 429 ? 429 : 401);
    }
    http_response_code($code);
    echo view('auth-layout.php', [
        'title'   => 'Login',
        'content' => view('auth/login.php', compact('email', 'next', 'googleEnabled') + ['error' => $msg]),
    ]);
    exit;
};

if (too_many_attempts($pdo, $email, $ip)) {
    log_activity($pdo, 'auth.login_failed', null, null, ['after' => ['reason' => 'rate_limited', 'email' => $email]]);
    $renderError('Too many attempts. Please wait a few minutes and try again.', 429);
}

$member = find_member_by_email($pdo, $email);
// Verify even when missing (dummy hash) to equalize timing; a null password_hash
// (Google-only account) also falls through to the dummy so timing stays constant.
$hash = $member['password_hash'] ?? null;
$ok = password_verify($password, $hash ?? AUTH_DUMMY_HASH) && $member !== null && $hash !== null;

record_attempt($pdo, $email, $ip, $ok);

if (!$ok || ($member['status'] ?? '') === 'suspended') {
    log_activity($pdo, 'auth.login_failed', null, null, ['after' => ['email' => $email]]);
    $renderError('Invalid email or password.');
}

// Re-hash if the stored cost drifted from our pinned cost.
if (password_needs_rehash($hash, PASSWORD_BCRYPT, ['cost' => PASSWORD_COST])) {
    $pdo->prepare('UPDATE members SET password_hash = :h WHERE id = :id')
        ->execute(['h' => hash_password($password), 'id' => (int) $member['id']]);
}

// 2FA gate — do not establish the session yet if 2FA is enabled.
if ($member['totp_enabled_at'] !== null) {
    begin_2fa_challenge((int) $member['id']);
    if (wants_json()) {
        respond_saved(['two_factor_required' => true, 'next' => $next]);
    }
    redirect('/login/2fa.php?next=' . rawurlencode($next));
}

establish_session($pdo, $member, 'password');
redirect($next);   // JSON mode: {ok, location} — see redirect()
