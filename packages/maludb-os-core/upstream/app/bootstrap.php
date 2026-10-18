<?php
declare(strict_types=1);

/**
 * Application bootstrap. Every web endpoint requires this first.
 *   - loads environment config
 *   - wires error handling
 *   - loads infrastructure helpers (db, http, auth, activity, mail)
 *   - starts a hardened session
 *   - resolves the signed-in member so db() can set the RLS request context
 *
 * Endpoints under /var/www/html reach this via:
 *   require_once dirname(__DIR__, N) . '/app/bootstrap.php';   // N = depth below html/
 */

define('APP_ROOT', dirname(__DIR__));                 // /var/www
define('APP_START', microtime(true));

// --------------------------------------------------------------------------
// Environment: load config/.env into the process env for non-prod.
// In prod, real environment variables (systemd/Apache SetEnv) take precedence.
// --------------------------------------------------------------------------
(function (): void {
    $envFile = APP_ROOT . '/config/.env';
    if (!is_readable($envFile)) {
        return;
    }
    foreach (file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#' || !str_contains($line, '=')) {
            continue;
        }
        [$key, $value] = explode('=', $line, 2);
        $key = trim($key);
        $value = trim($value);
        // Strip surrounding quotes.
        if (strlen($value) >= 2 && ($value[0] === '"' || $value[0] === "'") && $value[-1] === $value[0]) {
            $value = substr($value, 1, -1);
        }
        if (getenv($key) === false) {        // real env wins
            putenv("{$key}={$value}");
            $_ENV[$key] = $value;
        }
    }
})();

/** Read an environment value with a default. */
function env(string $key, ?string $default = null): ?string
{
    $value = getenv($key);
    return $value === false ? $default : $value;
}

function app_is_prod(): bool
{
    return env('APP_ENV', 'dev') === 'prod';
}

function app_url(string $path = ''): string
{
    return rtrim((string) env('APP_URL', ''), '/') . '/' . ltrim($path, '/');
}

// --------------------------------------------------------------------------
// The kernel's two faces (A2, 2026-09-22 — docs/business-os-integration.md, "Hosts"): OS_HOST is
// where super-admins run the operating system, APP_HOST where everyone signs in and launches
// applications. Both empty = one face, as before.
// --------------------------------------------------------------------------
function os_host(): string
{
    return strtolower(trim((string) env('OS_HOST', '')));
}

function app_host(): string
{
    return strtolower(trim((string) env('APP_HOST', '')));
}

/** The name the browser used — forwarded by the React server, first entry only, no port. */
function request_host(): string
{
    $forwarded = (string) ($_SERVER['HTTP_X_FORWARDED_HOST'] ?? '');
    $host = $forwarded !== '' ? trim(explode(',', $forwarded)[0]) : (string) ($_SERVER['HTTP_HOST'] ?? '');
    return strtolower(explode(':', $host, 2)[0]);
}

/**
 * The operating system admits super-admins only (the owner's decision, 2026-09-22). Judged on the
 * name the browser used: a localhost caller with an action token has no browser and is not judged;
 * /api/v1/session only says who you are (the React layout reads it to send a non-admin to the
 * launcher) and /logout.php lets them leave. Everything else under the os name answers 403 — or,
 * to a browser, a redirect to the launcher on the person face.
 */
function os_face_gate(): void
{
    $os = os_host();
    if ($os === '' || request_host() !== $os || !is_logged_in() || !empty($GLOBALS['__action_authed']) || is_super_admin()) {
        return;
    }
    $path = (string) parse_url((string) ($_SERVER['REQUEST_URI'] ?? ''), PHP_URL_PATH);
    if (in_array($path, ['/api/v1/session.php', '/logout.php'], true)) {
        return;
    }
    $to = 'https://' . (app_host() !== '' ? app_host() : $os) . '/launcher';
    if (wants_json()) {
        json_error('forbidden', 'The operating system is for administrators. Open ' . $to . '.', 403);
    }
    header('Location: ' . $to, true, 302);
    exit;
}

// --------------------------------------------------------------------------
// Error handling: verbose in dev, generic in prod. Never leak to the browser
// in prod; always to the error log.
// --------------------------------------------------------------------------
// Never display errors to the browser unless APP_DEBUG=1 is explicitly set (they leak
// stack traces on public sites). Errors always go to the log.
error_reporting(E_ALL);
ini_set('display_errors', env('APP_DEBUG') === '1' ? '1' : '0');
ini_set('log_errors', '1');

// --------------------------------------------------------------------------
// Composer autoloader (otphp, endroid/qr-code, league/oauth2-google)
// --------------------------------------------------------------------------
if (is_file(APP_ROOT . '/vendor/autoload.php')) {
    require_once APP_ROOT . '/vendor/autoload.php';
}

// --------------------------------------------------------------------------
// Infrastructure helpers
// --------------------------------------------------------------------------
require_once __DIR__ . '/db.php';
require_once __DIR__ . '/http.php';
require_once __DIR__ . '/activity.php';
require_once __DIR__ . '/mail.php';
require_once __DIR__ . '/auth.php';
require_once __DIR__ . '/business.php';
require_once __DIR__ . '/totp.php';

// A JSON caller never receives PHP's own error output — same rule as /api/v1 (no exception
// text, no SQL, no stack), and a 500 it can parse instead of an HTML fragment.
if (PHP_SAPI !== 'cli' && wants_json()) {
    json_mode_begin();                  // buffer the handler; answer from what it reported
    set_exception_handler(static function (Throwable $e): void {
        error_log('json error: ' . $e->getMessage() . ' @ ' . $e->getFile() . ':' . $e->getLine());
        if (!headers_sent()) {
            json_error('server_error', 'Something went wrong.', 500);
        }
        exit;
    });
}

// --------------------------------------------------------------------------
// Session (hardened — see php-session-auth). Skip for CLI (seed scripts).
// --------------------------------------------------------------------------
if (PHP_SAPI !== 'cli') {
    $isHttps = (($_SERVER['HTTPS'] ?? '') !== '' && $_SERVER['HTTPS'] !== 'off')
        || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');

    $cookieParams = [
        'lifetime' => 0,
        'path'     => '/',
        'secure'   => $isHttps || app_is_prod(),
        'httponly' => true,
        'samesite' => 'Lax',
    ];
    // SESSION_COOKIE_DOMAIN (config/.env, empty by default) widens the cookie to cover
    // every host under it (e.g. ".subello.com" for agentview + this app). Applied only when
    // the CURRENT request's host actually ends with that domain, so a value set for
    // production cannot silently break a localhost session — see public-api-org-graph.md.
    $cookieDomain = trim((string) env('SESSION_COOKIE_DOMAIN', ''));
    if ($cookieDomain !== '') {
        // Behind a reverse proxy the browser's hostname may arrive as X-Forwarded-Host rather
        // than Host, and if we only read Host we quietly issue a HOST-ONLY cookie — which looks
        // to the user like "no cookies at all" on the other subdomain. Prefer the forwarded
        // name when present, and take only its first entry: it is a comma-separated list when
        // more than one proxy is in the path.
        $forwarded = (string) ($_SERVER['HTTP_X_FORWARDED_HOST'] ?? '');
        $requestHost = $forwarded !== ''
            ? trim(explode(',', $forwarded)[0])
            : (string) ($_SERVER['HTTP_HOST'] ?? '');
        $requestHost = strtolower(explode(':', $requestHost, 2)[0]);
        $needle = strtolower(ltrim($cookieDomain, '.'));
        if ($requestHost === $needle || str_ends_with($requestHost, '.' . $needle)) {
            $cookieParams['domain'] = $cookieDomain;
        }
    }

    session_set_cookie_params($cookieParams);
    ini_set('session.use_strict_mode', '1');
    ini_set('session.use_only_cookies', '1');
    session_name('CSTSID');
    session_start();

    // Per-session CSRF token.
    if (empty($_SESSION['csrf_token'])) {
        $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
    }

    // Action-token auth (assistant/actions server): if the caller presents a valid
    // X-Action-Token and there is no browser session, act as that member for this request.
    // The token replaces both the session and CSRF (see verify_csrf()).
    if (!is_logged_in()) {
        $actionToken = $_SERVER['HTTP_X_ACTION_TOKEN'] ?? '';
        if ($actionToken !== '') {
            $mid = verify_action_token($actionToken, $_SERVER['HTTP_X_ACTION_RELAY'] ?? '');
            if ($mid !== null) {
                $m = find_member_by_id(db(), $mid);
                if ($m !== null && $m['status'] === 'active') {
                    $_SESSION['member_id'] = (int) $m['id'];
                    $_SESSION['member_role'] = $m['role'];
                    $GLOBALS['__action_authed'] = true;
                    $GLOBALS['__agent_run_id'] = action_token_run_id($actionToken);
                    // A token speaks for ONE request. Without this the response carried a fresh
                    // CSTSID and the session behind it stayed logged in as the member after the
                    // token expired — anyone holding that cookie needed no token at all.
                    header_remove('Set-Cookie');
                    register_shutdown_function(static function (): void {
                        if (session_status() === PHP_SESSION_ACTIVE) {
                            $_SESSION = [];
                            session_destroy();
                        }
                    });
                    db_apply_context(db());   // re-scope the connection to this member
                    // An *_update action tool sends only what changes (app/partial_update.php).
                    require_once __DIR__ . '/partial_update.php';
                    partial_update_prefill(db());
                }
            }
        }
    }
}

// A disabled application is closed at the door, whatever gate its handlers use (db/129).
if (isset($_SERVER['REQUEST_URI'])) {
    os_face_gate();
    refuse_disabled_application();
}
