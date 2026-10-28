<?php
declare(strict_types=1);

/**
 * Bootstrap for the public JSON API (`/api/v1/…`), the platform's first browser-facing
 * surface (build spec: docs/build-specs/public-api-org-graph.md). Every endpoint under
 * html/api/v1/ requires this after app/bootstrap.php.
 *
 * Auth (spec "Auth", revised 2026-09-18): a PHP session first (agentview's server calls
 * this on localhost, forwarding the caller's cookie — no CORS, no token in JS), then a
 * bearer token against mcp_access_tokens (scope='api', db/078). A missing, malformed,
 * expired, revoked or wrong-scope token all answer identically — never distinguish, it is
 * an enumeration oracle.
 *
 * This is not a second visibility model: api_authenticate() only resolves *who* is calling
 * and sets app.member_id (db_apply_context), exactly as the session/action-token paths in
 * app/bootstrap.php already do. Every read after that goes through the same mcp_* views
 * the screens and agents read — see app/features/orgchart/queries.php.
 */
require_once dirname(__DIR__) . '/bootstrap.php';

// Uncaught exceptions never reach the browser as PHP output (stack traces, SQL, file
// paths) — the screens already route those to error_log(); the API must too (spec
// "Errors": "No exception text, no SQL, no stack").
set_exception_handler(static function (Throwable $e): void {
    error_log('api error: ' . $e->getMessage());
    if (!headers_sent()) {
        api_error('server_error', 'Something went wrong.', 500);
    }
    exit;
});

// --------------------------------------------------------------------------
// JSON envelope
// --------------------------------------------------------------------------
function api_json(array $payload, int $status = 200): never
{
    json_response($payload, $status);   // app/http.php — one envelope for /api/v1 and JSON mode
}

/** One error shape everywhere (spec "Errors") — never exception text, SQL or a stack. */
function api_error(string $code, string $message, int $status): never
{
    json_error($code, $message, $status);
}

// --------------------------------------------------------------------------
// CORS (spec "CORS"). agentview never needs this — its server does the fetching. This is
// for any other browser client, and stays off unless API_CORS_ORIGINS lists the origin.
// --------------------------------------------------------------------------
function api_cors(): void
{
    header('Vary: Origin');
    $configured = array_filter(array_map('trim', explode(',', (string) env('API_CORS_ORIGINS', ''))));
    $origin = (string) ($_SERVER['HTTP_ORIGIN'] ?? '');

    if ($origin !== '' && in_array($origin, $configured, true)) {
        header('Access-Control-Allow-Origin: ' . $origin);
        header('Access-Control-Allow-Methods: GET, OPTIONS');
        header('Access-Control-Allow-Headers: Authorization, Content-Type');
        // No Access-Control-Allow-Credentials, deliberately: this API is token-authenticated
        // and must never be reachable by a browser's ambient session cookie (that would make
        // it CSRF-able).
    }
    // An origin not on the list gets no CORS headers at all (the browser then refuses it),
    // but the request is still answered normally for non-browser callers.

    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'OPTIONS') {
        http_response_code(204);
        exit;
    }
}

/** v1 is read-only (spec "Decisions taken before this spec"): GET and OPTIONS only. */
function api_require_get(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
        api_error('method_not_allowed', 'Only GET is supported.', 405);
    }
}

// --------------------------------------------------------------------------
// Auth
// --------------------------------------------------------------------------
/** Read the bearer token from the Authorization header, tolerant of how PHP/Apache expose it. */
function api_bearer_token(): string
{
    $header = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
    if ($header === '' && isset($_SERVER['REDIRECT_HTTP_AUTHORIZATION'])) {
        $header = (string) $_SERVER['REDIRECT_HTTP_AUTHORIZATION'];
    }
    if ($header === '' && function_exists('getallheaders')) {
        foreach (getallheaders() as $name => $value) {
            if (strcasecmp($name, 'Authorization') === 0) {
                $header = (string) $value;
                break;
            }
        }
    }
    if (!preg_match('/^Bearer\s+(\S+)$/i', trim($header), $m)) {
        return '';
    }
    return $m[1];
}

/**
 * Resolve the caller to a member row, or 401. Order (spec "Auth"): a PHP session first,
 * then Authorization: Bearer. On the token path this also stamps last_used_at and sets the
 * RLS request context (app.member_id), exactly like the action-token path in
 * app/bootstrap.php, so every subsequent query is scoped to this member automatically.
 */
function api_authenticate(): array
{
    $pdo = db();

    if (is_logged_in()) {
        $member = current_member();
        if ($member !== null && ($member['status'] ?? '') === 'active') {
            return $member;
        }
    }

    $token = api_bearer_token();
    if ($token === '') {
        error_log('api auth: no session and no bearer token presented');
        api_error('unauthorized', 'A valid API token is required.', 401);
    }

    // Every failure reason (no such token, wrong scope, expired, revoked) collapses into
    // "no row" here on purpose — the client never learns which, so the endpoint cannot be
    // used to enumerate tokens.
    $st = $pdo->prepare(<<<'SQL'
        SELECT * FROM mcp_access_tokens
         WHERE token_hash = :h
           AND scope = 'api'
           AND revoked_at IS NULL
           AND (expires_at IS NULL OR expires_at > now())
    SQL);
    $st->execute(['h' => hash('sha256', $token)]);
    $tokenRow = $st->fetch();
    if ($tokenRow === false) {
        error_log('api auth: token rejected (missing, wrong scope, expired or revoked)');
        api_error('unauthorized', 'A valid API token is required.', 401);
    }

    $member = find_member_by_id($pdo, (int) $tokenRow['member_id']);
    if ($member === null || $member['status'] !== 'active') {
        error_log('api auth: token maps to a member who is not active');
        api_error('unauthorized', 'A valid API token is required.', 401);
    }

    $pdo->prepare('UPDATE mcp_access_tokens SET last_used_at = now() WHERE id = :id')
        ->execute(['id' => $tokenRow['id']]);

    $_SESSION['member_id'] = (int) $member['id'];
    $_SESSION['member_role'] = $member['role'];
    $GLOBALS['__api_token_authed'] = true;
    db_apply_context($pdo);   // re-scope the connection's app.member_id to this member

    return $member;
}

// --------------------------------------------------------------------------
// members/{id} — the installed rewrite rules serve /api/v1/members/{id} as members.php
// with the id reaching PHP either as PATH_INFO or as the request URI's trailing segment
// (spec: "no Apache change is needed"); ?id= is accepted too for a direct query-string call.
// --------------------------------------------------------------------------
function api_path_id(): ?int
{
    $fromQuery = request_integer('id');
    if ($fromQuery !== null) {
        return $fromQuery;
    }

    $pathInfo = trim((string) ($_SERVER['PATH_INFO'] ?? ''), '/');
    if ($pathInfo !== '' && ctype_digit($pathInfo)) {
        return (int) $pathInfo;
    }

    $path = (string) (parse_url((string) ($_SERVER['REQUEST_URI'] ?? ''), PHP_URL_PATH) ?? '');
    $segments = array_values(array_filter(explode('/', $path), static fn ($s) => $s !== ''));
    $last = end($segments);
    if ($last !== false && ctype_digit($last)) {
        return (int) $last;
    }

    return null;
}
