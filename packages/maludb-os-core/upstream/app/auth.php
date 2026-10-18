<?php
declare(strict_types=1);

/**
 * Authentication & authorization helpers (php-session-auth non-negotiables).
 * The auth+profile entity is `members` (plays the php-session-auth `users` role).
 */

// We pin bcrypt cost 12 for every real hash so timing is stable regardless of what
// PASSWORD_DEFAULT resolves to. The dummy hash below is a genuine cost-12 hash, verified
// on unknown accounts so a missing account is indistinguishable by timing.
const PASSWORD_COST = 12;
const AUTH_DUMMY_HASH = '$2y$12$SlodTZj2trkRXcbPOY5ZdONsrMFMsd1.YPckse8c0iTn52olJH/7q';

const PASSWORD_MIN = 12;
const PASSWORD_MAX_BYTES = 72;   // bcrypt truncates past 72 bytes

/** Hash a password at the pinned cost. */
function hash_password(string $pw): string
{
    return password_hash($pw, PASSWORD_BCRYPT, ['cost' => PASSWORD_COST]);
}

// ---- request-context accessors -------------------------------------------
function is_logged_in(): bool
{
    return !empty($_SESSION['member_id']);
}

function current_member(): ?array
{
    static $member = null;
    if (!is_logged_in()) {
        return null;
    }
    if ($member === null) {
        $member = find_member_by_id(db(), (int) $_SESSION['member_id']);
    }
    return $member ?: null;
}

function current_member_id(): ?int
{
    return is_logged_in() ? (int) $_SESSION['member_id'] : null;
}

function is_organizer(): bool
{
    return ($_SESSION['member_role'] ?? '') === 'organizer';
}

function require_login(): void
{
    if (!is_logged_in()) {
        if (wants_json()) {
            json_error('unauthorized', 'Sign in required.', 401);
        }
        redirect('/login.php?next=' . rawurlencode($_SERVER['REQUEST_URI'] ?? '/'));
    }
}

function require_organizer(): void
{
    require_login();
    if (!is_organizer()) {
        http_response_code(403);
        exit('Forbidden — organizers only.');
    }
}

// ---- misc helpers ---------------------------------------------------------
/** Constrain a post-login redirect to a local path (prevents open redirects). */
function safe_next(string $next): string
{
    if ($next === '' || $next[0] !== '/' || str_starts_with($next, '//')) {
        return '/';
    }
    return $next;
}

/** Whether Sign in with Google is configured for this environment. */
function google_enabled(): bool
{
    return (string) env('GOOGLE_CLIENT_ID', '') !== '' && (string) env('GOOGLE_CLIENT_SECRET', '') !== '';
}

// ---- normalization & policy ----------------------------------------------
function normalize_email(string $email): string
{
    return strtolower(trim($email));
}

/** @return string[] error messages (empty = valid) */
function validate_password(string $pw): array
{
    $errors = [];
    if (strlen($pw) < PASSWORD_MIN) {
        $errors[] = 'Password must be at least ' . PASSWORD_MIN . ' characters.';
    }
    if (strlen($pw) > PASSWORD_MAX_BYTES) {
        $errors[] = 'Password must be at most ' . PASSWORD_MAX_BYTES . ' bytes.';
    }
    return $errors;
}

// ---- member lookups -------------------------------------------------------
function find_member_by_id(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM members WHERE id = :id');
    $st->execute(['id' => $id]);
    return ($m = $st->fetch()) === false ? null : $m;
}

function find_member_by_email(PDO $pdo, string $email): ?array
{
    $st = $pdo->prepare('SELECT * FROM members WHERE email = :e');
    $st->execute(['e' => normalize_email($email)]);
    return ($m = $st->fetch()) === false ? null : $m;
}

// ---- brute-force throttle (per account AND per IP) ------------------------
function too_many_attempts(PDO $pdo, string $email, string $ip): bool
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT
          count(*) FILTER (WHERE email = :e AND NOT successful) AS acct_fails,
          count(*) FILTER (WHERE ip_address = :ip AND NOT successful) AS ip_fails
        FROM login_attempts
        WHERE attempted_at > now() - interval '15 minutes'
    SQL);
    $st->execute(['e' => normalize_email($email), 'ip' => $ip]);
    $row = $st->fetch();
    return ((int) $row['acct_fails'] >= 5) || ((int) $row['ip_fails'] >= 20);
}

function record_attempt(PDO $pdo, string $email, string $ip, bool $ok): void
{
    $st = $pdo->prepare(
        'INSERT INTO login_attempts (email, ip_address, successful) VALUES (:e, :ip, :ok)'
    );
    $st->execute(['e' => normalize_email($email), 'ip' => $ip, 'ok' => $ok ? 1 : 0]);
}

// ---- session establishment ------------------------------------------------
/**
 * Promote to a fully signed-in session. Used by password login, Google callback, and
 * the 2FA challenge — no path skips it. Regenerates the id, mints a fresh CSRF token,
 * refreshes the DB RLS context, records last_login, and logs the event.
 */
function establish_session(PDO $pdo, array $member, string $method): void
{
    session_regenerate_id(true);
    $_SESSION['member_id']    = (int) $member['id'];
    $_SESSION['member_role']  = $member['role'];
    $_SESSION['member_email'] = $member['email'];
    $_SESSION['member_name']  = $member['display_name'];
    unset($_SESSION['pending_2fa_member_id'], $_SESSION['pending_2fa_at']);
    $_SESSION['csrf_token'] = bin2hex(random_bytes(32));   // rotate on privilege change

    $pdo->prepare('UPDATE members SET last_login_at = now() WHERE id = :id')
        ->execute(['id' => (int) $member['id']]);

    db_apply_context($pdo);
    log_activity($pdo, 'auth.login', 'member', (int) $member['id'], ['after' => ['method' => $method]]);
}

function logout(PDO $pdo): void
{
    $id = current_member_id();
    if ($id !== null) {
        log_activity($pdo, 'auth.logout', 'member', $id);
    }
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $p = session_get_cookie_params();
        setcookie(session_name(), '', time() - 42000, $p['path'], $p['domain'], $p['secure'], $p['httponly']);
    }
    session_destroy();
}

// ---- pending-2FA state ----------------------------------------------------
function begin_2fa_challenge(int $memberId): void
{
    session_regenerate_id(true);
    $_SESSION['pending_2fa_member_id'] = $memberId;
    $_SESSION['pending_2fa_at'] = time();
}

function pending_2fa_member_id(): ?int
{
    $id = $_SESSION['pending_2fa_member_id'] ?? null;
    $at = $_SESSION['pending_2fa_at'] ?? 0;
    if ($id === null || (time() - (int) $at) > 600) {   // 10-minute expiry
        unset($_SESSION['pending_2fa_member_id'], $_SESSION['pending_2fa_at']);
        return null;
    }
    return (int) $id;
}

// ---- invitations (invite-only registration) ------------------------------
function find_valid_invitation(PDO $pdo, string $email): ?array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT * FROM invitations
        WHERE email = :e AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()
        ORDER BY created_at DESC LIMIT 1
    SQL);
    $st->execute(['e' => normalize_email($email)]);
    return ($i = $st->fetch()) === false ? null : $i;
}

function find_invitation_by_token(PDO $pdo, string $rawToken): ?array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT * FROM invitations
        WHERE token_hash = :h AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()
        LIMIT 1
    SQL);
    $st->execute(['h' => hash('sha256', $rawToken)]);
    return ($i = $st->fetch()) === false ? null : $i;
}

function mark_invitation_accepted(PDO $pdo, int $invitationId, int $memberId): void
{
    $st = $pdo->prepare(
        'UPDATE invitations SET accepted_at = now(), accepted_member_id = :m WHERE id = :id'
    );
    $st->execute(['m' => $memberId, 'id' => $invitationId]);
}

// ---- token hashing for reset / verification -------------------------------
function random_token(): string
{
    return bin2hex(random_bytes(32));
}

function hash_token(string $raw): string
{
    return hash('sha256', $raw);
}

// ---- action tokens (assistant → app endpoints, no browser session) --------
// Short-lived HMAC token minted by /assistant/message.php (which holds the session) and
// relayed by the actions MCP server. An endpoint that receives a valid X-Action-Token
// acts as that member with the same authorization, and the token stands in for CSRF.
function action_token_key(): string
{
    $k = (string) env('ACTION_TOKEN_KEY', '');
    if (strlen($k) < 32) {
        throw new RuntimeException('ACTION_TOKEN_KEY is not configured.');
    }
    return $k;
}

function mint_action_token(int $memberId, int $ttlSeconds = 600): string
{
    $payload = $memberId . '.' . (time() + $ttlSeconds);
    return $payload . '.' . hash_hmac('sha256', $payload, action_token_key());
}

// ---- sign-on hand-off (A3, 2026-09-22) ----------------------------------------------------
// The launcher carries a person into an application from us with a token on the action token's
// pattern, signed with the same tenant key the application already holds to verify run tokens.
//   {member_id}.{expires}.{app_key}.{nonce}.{hmac}   over "sso:member.exp.app.nonce"
// 60 seconds, single use (the application records the nonce), bound to one application. Beside
// it travel the signed claims the application refreshes its directory mirror from:
//   base64url(json).{hmac}                            over the base64url text
// The sign-out notice: {member_id}.{issued}.{app_key}.{hmac} over "sso-logout:member.issued.app".

function base64url_encode(string $bytes): string
{
    return rtrim(strtr(base64_encode($bytes), '+/', '-_'), '=');
}

function base64url_decode(string $text): string|false
{
    return base64_decode(strtr($text, '-_', '+/') . str_repeat('=', (4 - strlen($text) % 4) % 4), true);
}

function mint_sso_token(int $memberId, string $appKey, int $ttlSeconds = 60): string
{
    $payload = $memberId . '.' . (time() + $ttlSeconds) . '.' . $appKey . '.' . bin2hex(random_bytes(16));
    return $payload . '.' . hash_hmac('sha256', 'sso:' . $payload, action_token_key());
}

/**
 * Verify a hand-off token for ONE application. Returns [member_id, nonce] or null. The caller
 * (an application from us) also refuses a nonce it has seen — this function cannot know that.
 */
function verify_sso_token(string $token, string $expectedAppKey): ?array
{
    $parts = explode('.', $token);
    if (count($parts) !== 5) {
        return null;
    }
    [$mid, $exp, $app, $nonce, $mac] = $parts;
    if (!ctype_digit($mid) || !ctype_digit($exp) || (int) $exp < time() || $app !== $expectedAppKey
        || !preg_match('/^[a-f0-9]{32}$/', $nonce)) {
        return null;
    }
    $expected = hash_hmac('sha256', 'sso:' . $mid . '.' . $exp . '.' . $app . '.' . $nonce, action_token_key());
    return hash_equals($expected, $mac) ? [(int) $mid, $nonce] : null;
}

function sign_sso_claims(array $claims): string
{
    $text = base64url_encode(json_encode($claims, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
    return $text . '.' . hash_hmac('sha256', $text, action_token_key());
}

/** The claims beside a hand-off token, or null when the signature does not hold. */
function verify_sso_claims(string $signed): ?array
{
    $dot = strrpos($signed, '.');
    if ($dot === false) {
        return null;
    }
    $text = substr($signed, 0, $dot);
    $mac = substr($signed, $dot + 1);
    if (!hash_equals(hash_hmac('sha256', $text, action_token_key()), $mac)) {
        return null;
    }
    $json = base64url_decode($text);
    $claims = $json === false ? null : json_decode($json, true);
    return is_array($claims) ? $claims : null;
}

// ---- the kernel's own call into an application (db/145, 2026-09-27) ----------------------------
// When the kernel itself — not a person, not an agent — reads an application's MCP server (today only
// the `app_roles` tool, to learn the application's roles), it presents a token on the hand-off's pattern:
//   kernel.{expires}.{app_key}.{nonce}.{hmac}   over "kernel:expires.app.nonce"
// 60 seconds, bound to one application. The application admits it to `app_roles` and nothing else.
function mint_kernel_token(string $appKey, int $ttlSeconds = 60): string
{
    $payload = (time() + $ttlSeconds) . '.' . $appKey . '.' . bin2hex(random_bytes(16));
    return 'kernel.' . $payload . '.' . hash_hmac('sha256', 'kernel:' . $payload, action_token_key());
}

function mint_sso_logout_notice(int $memberId, string $appKey, int $ttlSeconds = 120): string
{
    $payload = $memberId . '.' . time() . '.' . $appKey;
    return $payload . '.' . hash_hmac('sha256', 'sso-logout:' . $payload, action_token_key());
}

function verify_sso_logout_notice(string $notice, string $expectedAppKey, int $ttlSeconds = 120): ?int
{
    $parts = explode('.', $notice);
    if (count($parts) !== 4) {
        return null;
    }
    [$mid, $issued, $app, $mac] = $parts;
    if (!ctype_digit($mid) || !ctype_digit($issued) || $app !== $expectedAppKey || abs(time() - (int) $issued) > $ttlSeconds) {
        return null;
    }
    $expected = hash_hmac('sha256', 'sso-logout:' . $mid . '.' . $issued . '.' . $app, action_token_key());
    return hash_equals($expected, $mac) ? (int) $mid : null;
}

/**
 * Verify a signed token; returns the member id or null. Two shapes share ACTION_TOKEN_KEY:
 *
 *   {mid}.{exp}.{hmac}        the assistant's action token (mint_action_token), over "mid.exp";
 *   {mid}.{exp}.{run}.{hmac}  an agent RUN token, minted only by the agent runner, over
 *                             "run:mid.exp.run". It is honoured only with a valid $relay —
 *                             hmac(ACTIONS_RELAY_KEY, token), which the actions MCP server adds.
 *                             The agent holds its token but never the relay key, so it cannot POST
 *                             to a handler itself and step around its tool grants.
 */
/**
 * A run token's signature alone, without the relay (A7 (b)): what the run-facts call checks for an
 * application's read server, which holds the tenant key but never the relay key. Returns
 * [member_id, run_id] or null. A three-part (person) token answers [member_id, null].
 */
function verify_token_signature(string $token): ?array
{
    $parts = explode('.', $token);
    if (count($parts) === 4) {
        [$mid, $exp, $run, $sig] = $parts;
        if (!ctype_digit($mid) || !ctype_digit($exp) || !ctype_digit($run) || time() > (int) $exp) {
            return null;
        }
        $expected = hash_hmac('sha256', 'run:' . $mid . '.' . $exp . '.' . $run, action_token_key());
        return hash_equals($expected, (string) $sig) ? [(int) $mid, (int) $run] : null;
    }
    if (count($parts) !== 3) {
        return null;
    }
    [$mid, $exp, $sig] = $parts;
    if (!ctype_digit($mid) || !ctype_digit($exp) || time() > (int) $exp) {
        return null;
    }
    return hash_equals(hash_hmac('sha256', $mid . '.' . $exp, action_token_key()), (string) $sig) ? [(int) $mid, null] : null;
}

function verify_action_token(string $token, string $relay = ''): ?int
{
    $parts = explode('.', $token);
    if (count($parts) === 4) {
        [$mid, $exp, $run, $sig] = $parts;
        if (!ctype_digit($mid) || !ctype_digit($exp) || !ctype_digit($run)) {
            return null;
        }
        $expected = hash_hmac('sha256', 'run:' . $mid . '.' . $exp . '.' . $run, action_token_key());
        if (!hash_equals($expected, (string) $sig) || time() > (int) $exp) {
            return null;
        }
        $relayKey = (string) env('ACTIONS_RELAY_KEY', '');
        if (strlen($relayKey) < 32 || $relay === ''
            || !hash_equals(hash_hmac('sha256', $token, $relayKey), $relay)) {
            return null;
        }
        return (int) $mid;
    }
    if (count($parts) !== 3) {
        return null;
    }
    [$mid, $exp, $sig] = $parts;
    if (!ctype_digit($mid) || !ctype_digit($exp)) {
        return null;
    }
    $expected = hash_hmac('sha256', $mid . '.' . $exp, action_token_key());
    if (!hash_equals($expected, (string) $sig) || time() > (int) $exp) {
        return null;
    }
    return (int) $mid;
}

/** The agent_runs id inside a run token, or null for the assistant's token. Call after verifying. */
function action_token_run_id(string $token): ?int
{
    $parts = explode('.', $token);
    return count($parts) === 4 && ctype_digit($parts[2]) ? (int) $parts[2] : null;
}

/** The agent run this request belongs to, or null. */
function current_agent_run_id(): ?int
{
    return $GLOBALS['__agent_run_id'] ?? null;
}

/** True when the current request authenticated via an action token (not a browser session). */
function is_action_authed(): bool
{
    return !empty($GLOBALS['__action_authed']);
}

// ---- TOTP secret encryption at rest (libsodium secretbox) -----------------
function totp_key(): string
{
    $hex = (string) env('APP_TOTP_KEY', '');
    if (strlen($hex) !== 64 || !ctype_xdigit($hex)) {
        throw new RuntimeException('APP_TOTP_KEY must be 64 hex chars (32 bytes).');
    }
    return sodium_hex2bin($hex);
}

function encrypt_secret(string $plain): string
{
    $nonce = random_bytes(SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
    return base64_encode($nonce . sodium_crypto_secretbox($plain, $nonce, totp_key()));
}

function decrypt_secret(string $stored): string
{
    $raw = base64_decode($stored, true);
    if ($raw === false || strlen($raw) < SODIUM_CRYPTO_SECRETBOX_NONCEBYTES) {
        throw new RuntimeException('Corrupt TOTP secret.');
    }
    $nonce = substr($raw, 0, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
    $cipher = substr($raw, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
    $plain = sodium_crypto_secretbox_open($cipher, $nonce, totp_key());
    if ($plain === false) {
        throw new RuntimeException('Failed to decrypt TOTP secret.');
    }
    return $plain;
}
