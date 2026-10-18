<?php
declare(strict_types=1);

require_once dirname(__DIR__, 2) . '/app/bootstrap.php';

header('Cache-Control: no-store');
header('X-Frame-Options: DENY');
header('Referrer-Policy: same-origin');

// Guarded by the pending-2FA state, NOT a full session. Expires after 10 minutes.
$pendingId = pending_2fa_member_id();
if ($pendingId === null) {
    if (wants_json()) {
        json_error('two_factor_expired', 'That sign-in expired. Please start again.', 401);
    }
    redirect('/login.php');
}

$pdo = db();
$next = safe_next(request_string('next', '/'));

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'GET') {
    echo view('auth-layout.php', ['title' => 'Two-factor', 'content' => view('auth/twofa.php', ['next' => $next])]);
    exit;
}

require_post();
verify_csrf();

$ip = client_ip();
$member = find_member_by_id($pdo, $pendingId);
if ($member === null || $member['totp_enabled_at'] === null) {
    redirect('/login.php');
}

// Rate-limit exactly like password attempts (six digits brute-force fast otherwise).
$identifier = '2fa:' . $member['email'];
if (too_many_attempts($pdo, $identifier, $ip)) {
    if (wants_json()) {
        json_error('rate_limited', 'Too many attempts. Wait a few minutes.', 429);
    }
    http_response_code(429);
    echo view('auth-layout.php', ['title' => 'Two-factor',
        'content' => view('auth/twofa.php', ['next' => $next, 'error' => 'Too many attempts. Wait a few minutes.'])]);
    exit;
}

$code = (string) ($_POST['code'] ?? '');
$ok = verify_totp_code($pdo, $member, $code) || verify_recovery_code($pdo, (int) $member['id'], $code);
record_attempt($pdo, $identifier, $ip, $ok);

if (!$ok) {
    log_activity($pdo, 'auth.login_failed', 'member', (int) $member['id'], ['after' => ['reason' => '2fa']]);
    if (wants_json()) {
        json_error('invalid_code', 'Invalid code. Try again.', 401);
    }
    echo view('auth-layout.php', ['title' => 'Two-factor',
        'content' => view('auth/twofa.php', ['next' => $next, 'error' => 'Invalid code. Try again.'])]);
    exit;
}

establish_session($pdo, $member, 'password+2fa');
log_activity($pdo, 'auth.login_2fa', 'member', (int) $member['id']);
redirect($next);   // JSON mode: {ok, location} — see redirect()
