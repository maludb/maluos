<?php
declare(strict_types=1);

require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/invitations/queries.php';   // apply_invitation_grants()

header('Cache-Control: no-store');

$pdo = db();
$ip = client_ip();

$fail = function (string $logReason) use ($pdo): never {
    log_activity($pdo, 'auth.login_failed', null, null, ['after' => ['method' => 'google', 'reason' => $logReason]]);
    // The React login relays this callback server-side (web/app/auth/google/callback) and asks
    // for JSON: the same one sentence, whatever the reason. Owner's decision, 2026-09-19.
    if (wants_json()) {
        json_error('google_failed', 'We could not sign you in with Google.',
            $logReason === 'rate_limited' ? 429 : 401);
    }
    // Same generic error as a bad password (no enumeration).
    echo view('auth-layout.php', ['title' => 'Login',
        'content' => view('auth/login.php', [
            'error' => 'We could not sign you in with Google.',
            'googleEnabled' => google_enabled(),
        ])]);
    exit;
};

if (!google_enabled()) {
    redirect('/login.php');
}

// Rate-limit the callback like the login handler.
if (too_many_attempts($pdo, 'google-callback', $ip)) {
    http_response_code(429);
    $fail('rate_limited');
}

$state = request_string('state');
$sessionState = $_SESSION['oauth2state'] ?? '';
$next = safe_next($_SESSION['oauth2next'] ?? '/');
// Consume state on first use so a replayed callback fails.
unset($_SESSION['oauth2state'], $_SESSION['oauth2next']);

if ($state === '' || !hash_equals((string) $sessionState, $state)) {
    record_attempt($pdo, 'google-callback', $ip, false);
    $fail('bad_state');
}

$provider = new League\OAuth2\Client\Provider\Google([
    'clientId'     => (string) env('GOOGLE_CLIENT_ID'),
    'clientSecret' => (string) env('GOOGLE_CLIENT_SECRET'),
    'redirectUri'  => (string) env('GOOGLE_REDIRECT_URI', app_url('/auth/google/callback')),
]);

try {
    $token = $provider->getAccessToken('authorization_code', ['code' => request_string('code')]);
    $data  = $provider->getResourceOwner($token)->toArray();
} catch (Throwable $ex) {
    error_log('google callback error: ' . $ex->getMessage());
    record_attempt($pdo, 'google-callback', $ip, false);
    $fail('token_exchange');
}

$sub   = (string) ($data['sub'] ?? '');
$email = normalize_email((string) ($data['email'] ?? ''));
$verified = (bool) ($data['email_verified'] ?? false);
$name  = (string) ($data['name'] ?? ($email !== '' ? explode('@', $email)[0] : 'Member'));

// An unverified Google email is treated as no email.
if ($sub === '' || $email === '' || !$verified) {
    record_attempt($pdo, 'google-callback', $ip, false);
    $fail('unverified_email');
}

// Linking rules (php-session-auth google-signin.md).
$member = null;

// 1) Existing identity → that member.
$st = $pdo->prepare('SELECT m.* FROM auth_identities i JOIN members m ON m.id = i.member_id WHERE i.provider = :p AND i.provider_user_id = :sub');
$st->execute(['p' => 'google', 'sub' => $sub]);
$member = $st->fetch() ?: null;

if ($member === null) {
    $existing = find_member_by_email($pdo, $email);
    if ($existing !== null) {
        // 2) Same verified email, no different Google identity yet → auto-link.
        $hasOther = $pdo->prepare('SELECT 1 FROM auth_identities WHERE member_id = :m AND provider = :p AND provider_user_id <> :sub');
        $hasOther->execute(['m' => (int) $existing['id'], 'p' => 'google', 'sub' => $sub]);
        if ($hasOther->fetchColumn()) {
            $fail('email_has_other_identity');   // 4) never auto-merge
        }
        $pdo->prepare('INSERT INTO auth_identities (member_id, provider, provider_user_id, email_at_provider) VALUES (:m, :p, :sub, :e)')
            ->execute(['m' => (int) $existing['id'], 'p' => 'google', 'sub' => $sub, 'e' => $email]);
        log_activity($pdo, 'auth.identity_linked', 'member', (int) $existing['id'], ['after' => ['provider' => 'google']]);
        $member = $existing;
    } else {
        // 3) No account at all → invite-only: require a valid invitation for this email.
        $invite = find_valid_invitation($pdo, $email);
        if ($invite === null) {
            $fail('no_invitation');
        }
        $pdo->beginTransaction();
        try {
            $ins = $pdo->prepare('INSERT INTO members (email, password_hash, display_name, role, email_verified_at) VALUES (:e, NULL, :n, :r, now()) RETURNING *');
            $ins->execute(['e' => $email, 'n' => $name, 'r' => $invite['role_granted']]);
            $member = $ins->fetch();
            $pdo->prepare('INSERT INTO auth_identities (member_id, provider, provider_user_id, email_at_provider) VALUES (:m, :p, :sub, :e)')
                ->execute(['m' => (int) $member['id'], 'p' => 'google', 'sub' => $sub, 'e' => $email]);
            apply_invitation_grants($pdo, $invite, (int) $member['id']);   // as register.php does
            mark_invitation_accepted($pdo, (int) $invite['id'], (int) $member['id']);
            log_activity($pdo, 'invite.accept', 'member', (int) $member['id'], ['after' => ['method' => 'google']]);
            $pdo->commit();
        } catch (Throwable $ex) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            error_log('google signup failed: ' . $ex->getMessage());
            $fail('signup_failed');
        }
    }
}

record_attempt($pdo, 'google-callback', $ip, true);

// 2FA applies to Google sign-ins too.
if ($member['totp_enabled_at'] !== null) {
    begin_2fa_challenge((int) $member['id']);
    redirect('/login/2fa.php?next=' . rawurlencode($next));
}

establish_session($pdo, $member, 'google');
redirect($next);
