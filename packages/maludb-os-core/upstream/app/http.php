<?php
declare(strict_types=1);

/** True when the request came from HTMX. */
function is_htmx_request(): bool
{
    return ($_SERVER['HTTP_HX_REQUEST'] ?? '') === 'true';
}

/** True when HTMX is doing a full-page boost/history restore (treat like a normal nav). */
function is_htmx_boosted(): bool
{
    return ($_SERVER['HTTP_HX_BOOSTED'] ?? '') === 'true';
}

// --------------------------------------------------------------------------
// JSON mode (React migration, docs/react-migration-plan.md). Until cut-over every endpoint
// answers both ways: HTML for the HTMX UI, JSON for the Next.js server. The gate, CSRF and
// log_activity() lines of a handler are the same in both modes — only the response differs.
// --------------------------------------------------------------------------
/** True when the caller asked for JSON (the Next.js server always does; a browser never does). */
function wants_json(): bool
{
    static $wants = null;
    if ($wants === null) {
        $accept = strtolower((string) ($_SERVER['HTTP_ACCEPT'] ?? ''));
        $wants = !is_htmx_request() && str_starts_with(ltrim($accept), 'application/json');
    }
    return $wants;
}

function json_response(array $payload, int $status = 200): never
{
    $GLOBALS['__json_sent'] = true;
    while (ob_get_level() > 0) {
        ob_end_clean();                 // drop anything buffered by json_mode_begin()
    }
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    // The request id every activity row of this request carries — an application copies it into
    // its own log so the two trails join (sign-on-and-directory.md §4; HR was the first to need it).
    if (function_exists('request_id')) {
        header('X-Request-Id: ' . request_id());
    }
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

/** The one error shape, shared with /api/v1 — never exception text, SQL or a stack. */
function json_error(string $code, string $message, int $status, array $extra = []): never
{
    json_response(['error' => ['code' => $code, 'message' => $message] + $extra], $status);
}

/**
 * A screen's data, JSON mode only. $payload comes from the feature's present.php whitelist
 * functions — NEVER the array handed to view(): templates chose what to show, and a raw row
 * carries what they hid (password hashes, masked project names).
 */
function respond_screen(array $payload): never
{
    json_response(['data' => $payload]);
}

/** A state change succeeded. `location` is where the HTMX flow would have navigated. */
function respond_saved(array $data = []): never
{
    json_response(['ok' => true] + $data);
}

/**
 * Validation refused the input: 422, never a 200 (a 200-with-a-form is read as success by
 * every non-browser caller). $errors is the handler's message list; $fields optionally keys
 * messages by input name so a form can place them.
 */
function respond_invalid(array $errors, array $fields = []): never
{
    json_error('invalid', (string) ($errors[0] ?? 'That could not be saved.'), 422,
        ['errors' => array_values($errors), 'fields' => (object) $fields]);
}

/**
 * A timestamptz for JSON: ISO 8601 in UTC ("2026-09-18T21:04:00Z"), which every client parses
 * the same way. Postgres hands PHP "2026-09-18 21:04:00.123+00" under SET TIME ZONE 'UTC'.
 */
function json_ts(?string $utc): ?string
{
    if ($utc === null || $utc === '') {
        return null;
    }
    try {
        return (new DateTimeImmutable($utc, new DateTimeZone('UTC')))
            ->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\TH:i:s\Z');
    } catch (Exception) {
        return null;
    }
}

function respond_not_found(string $message = 'Not found.'): never
{
    json_error('not_found', $message, 404);
}

// --------------------------------------------------------------------------
// The JSON-mode adapter: a JSON caller NEVER receives HTML, whatever the handler does.
//
// Write handlers were built for HTMX: on success they call emit_action_status(true, …) and
// echo a re-rendered partial; on a validation failure emit_action_status(false, …) and echo
// the form; on a refusal they set a 4xx and exit('plain words'). Rather than edit two hundred
// handlers, JSON mode buffers their output and, at shutdown, answers from what they REPORTED:
//
//   json_response() already sent        → nothing to do (explicit branches win)
//   status ≥ 500                        → server_error, generic words (never the body)
//   status 4xx                          → that status, the handler's own words as the message
//   202 + pending_approval reported     → 202 {ok:false, status:'pending_approval', …}
//   success reported                    → 200 {ok:true, did, location?}   (location = where
//                                          HTMX was told to go: HX-Push-Url / HX-Location)
//   failure reported                    → 422 invalid, with the handler's error list
//   none of the above (an HTML screen)  → 501 not_converted
//
// So every handler that reports its outcome — which the actions MCP server already required
// of every business write — answers JSON with no edit at all. Only reads need a branch
// (respond_screen), because only reads have data to whitelist.
// --------------------------------------------------------------------------
function json_mode_begin(): void
{
    ob_start();
    register_shutdown_function('json_mode_finish');
}

function json_mode_finish(): void
{
    if (!empty($GLOBALS['__json_sent'])) {
        return;
    }
    $body = '';
    while (ob_get_level() > 0) {
        $body = (string) ob_get_clean() . $body;
    }
    $status = (int) http_response_code();
    $reported = $GLOBALS['__action_status'] ?? null;

    // Where the HTMX flow was sent — the record just created, the list after a delete.
    $location = null;
    foreach (headers_list() as $line) {
        [$name, $value] = array_map('trim', explode(':', $line, 2) + [1 => '']);
        $name = strtolower($name);
        if ($name === 'hx-push-url' || $name === 'hx-redirect' || $name === 'location') {
            $location = $value;
        } elseif ($name === 'hx-location') {
            $location = json_decode($value, true)['path'] ?? $location;
        }
        if (str_starts_with($name, 'hx-') || $name === 'location') {
            header_remove($name);
        }
    }

    $send = static function (array $payload, int $code): void {
        http_response_code($code);
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
        echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    };
    $error = static fn (string $code, string $message, array $extra = []): array
        => ['error' => ['code' => $code, 'message' => $message] + $extra];

    if ($status >= 500) {
        // A handler that REPORTED its failure (an approval carried out and refused by the application, 502) keeps its
        // words; an unreported 5xx — a fatal, a blank — is the generic sentence, since the page may hold a stack trace.
        $reported5 = $reported !== null && !$reported['ok'] ? ($reported['data']['errors'] ?? null) : null;
        $words5 = is_array($reported5) && trim((string) ($reported5[0] ?? '')) !== '' ? (string) $reported5[0] : null;
        $send($words5 !== null
            ? $error('failed', $words5, ['errors' => array_values($reported5), 'fields' => (object) []])
            : $error('server_error', 'Something went wrong.'), $status);
        return;
    }
    if ($status >= 400) {
        $codes = [400 => 'bad_request', 401 => 'unauthorized', 403 => 'forbidden', 404 => 'not_found',
                  405 => 'method_not_allowed', 409 => 'conflict', 422 => 'invalid', 429 => 'rate_limited'];
        $words = trim(preg_replace('/\s+/', ' ', html_entity_decode(strip_tags($body), ENT_QUOTES, 'UTF-8')) ?? '');
        if ($words === '' || mb_strlen($words) > 400) {
            $words = (string) ($reported['data']['error'] ?? 'That could not be done.');
        }
        $send($error($codes[$status] ?? 'refused', $words), $status);
        return;
    }
    if ($reported !== null && ($reported['data']['status'] ?? '') === 'pending_approval') {
        $send(['ok' => false, 'status' => 'pending_approval',
               'message' => (string) ($reported['data']['did'] ?? 'This waits for approval.'),
               'approval_request_id' => $reported['data']['approval_request_id'] ?? null], 202);
        return;
    }
    if ($reported !== null && $reported['ok']) {
        $send(['ok' => true] + $reported['data'] + ($location !== null ? ['location' => $location] : []), 200);
        return;
    }
    if ($reported !== null) {
        $errors = $reported['data']['errors'] ?? [(string) ($reported['data']['error'] ?? 'That could not be saved.')];
        $send($error('invalid', (string) ($errors[0] ?? 'That could not be saved.'),
            ['errors' => array_values((array) $errors), 'fields' => (object) []]), 422);
        return;
    }
    if ($location !== null && $body === '') {
        $send(['ok' => true, 'location' => $location], 200);
        return;
    }
    $send($error('not_converted', 'This screen does not answer JSON yet.'), 501);
}

// --------------------------------------------------------------------------
// The Next.js server calls PHP from localhost, so REMOTE_ADDR is 127.0.0.1 for every visitor —
// which would pool everyone into one per-IP login lockout and blank the activity log's ip.
// The forwarded address is believed only from loopback AND only with the shared key
// (WEB_INTERNAL_KEY, config/.env); anyone else's X-Forwarded-For is ignored.
// --------------------------------------------------------------------------
function is_internal_web_request(): bool
{
    static $internal = null;
    if ($internal === null) {
        $key = (string) env('WEB_INTERNAL_KEY', '');
        $internal = $key !== ''
            && in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1'], true)
            && hash_equals($key, (string) ($_SERVER['HTTP_X_WEB_KEY'] ?? ''));
    }
    return $internal;
}

function client_ip(): string
{
    $remote = (string) ($_SERVER['REMOTE_ADDR'] ?? '0.0.0.0');
    if (is_internal_web_request()) {
        $first = trim(explode(',', (string) ($_SERVER['HTTP_X_FORWARDED_FOR'] ?? ''))[0]);
        if (filter_var($first, FILTER_VALIDATE_IP) !== false) {
            return $first;
        }
    }
    return $remote;
}

/** Escape a value for safe HTML output. Use on EVERY dynamic value. */
function e(mixed $value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

/**
 * Render a view under app/views. Template names come from application code, never
 * from request input (path-confined to app/views).
 */
function view(string $template, array $data = []): string
{
    $viewsRoot = realpath(__DIR__ . '/views');
    if ($viewsRoot === false) {
        throw new RuntimeException('View directory does not exist.');
    }
    $path = realpath($viewsRoot . '/' . ltrim($template, '/'));
    // Since the React cut-over (2026-09-19) the only templates left are the mail bodies under
    // emails/. The screens' templates are gone, but handlers still call view() for the HTML they
    // used to answer with — JSON mode discards that output, so a screen template that no longer
    // exists renders as nothing. A missing MAIL template is still an error: that one is a bug.
    if ($path === false && !str_starts_with(ltrim($template, '/'), 'emails/')) {
        return '';
    }
    if ($path === false || !str_starts_with($path, $viewsRoot . DIRECTORY_SEPARATOR)) {
        throw new RuntimeException("Invalid view: {$template}");
    }
    extract($data, EXTR_SKIP);
    ob_start();
    try {
        require $path;
        return (string) ob_get_clean();
    } catch (Throwable $exception) {
        ob_end_clean();
        throw $exception;
    }
}

/** Render a full page (partial when the request is HTMX and not boosted). */
function render_screen(string $title, string $pageHtml, array $layout = []): void
{
    // A JSON caller reaching here means this endpoint has no respond_screen() branch yet.
    // Say so — HTML with a 200 would be read as success (migration step R4 tracks these).
    if (wants_json()) {
        json_error('not_converted', 'This screen does not answer JSON yet.', 501);
    }
    if (is_htmx_request() && !is_htmx_boosted()) {
        header('Vary: HX-Request');
        echo $pageHtml;
        return;
    }
    echo view('layout.php', array_merge(['title' => $title, 'content' => $pageHtml], $layout));
}

function require_post(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
        header('Allow: POST');
        if (wants_json()) {
            json_error('method_not_allowed', 'Only POST is supported.', 405);
        }
        http_response_code(405);
        exit('Method Not Allowed');
    }
}

function request_integer(string $name): ?int
{
    $value = $_POST[$name] ?? $_GET[$name] ?? null;
    if ($value === null || $value === '') {
        return null;
    }
    $filtered = filter_var($value, FILTER_VALIDATE_INT);
    return $filtered === false ? null : $filtered;
}

function request_string(string $name, string $default = ''): string
{
    return trim((string) ($_POST[$name] ?? $_GET[$name] ?? $default));
}

function request_bool(string $name): bool
{
    $v = $_POST[$name] ?? $_GET[$name] ?? null;
    return in_array((string) $v, ['1', 'true', 'on', 'yes'], true);
}

/**
 * Format a UTC timestamp (as PG returns it under SET TIME ZONE 'UTC') in a viewer's
 * timezone. Returns '' for null/empty. Used for timestamptz columns (events, activity).
 */
function format_ts(?string $utc, string $tz, string $fmt = 'M j, Y g:i A'): string
{
    if ($utc === null || $utc === '') {
        return '';
    }
    try {
        $dt = new DateTime($utc, new DateTimeZone('UTC'));
        $dt->setTimezone(new DateTimeZone($tz !== '' ? $tz : 'UTC'));
        return $dt->format($fmt);
    } catch (Exception) {
        return $utc;
    }
}

/**
 * Convert a datetime-local input entered in the member's tz to a UTC string PG accepts
 * for a timestamptz column. Returns null for empty input.
 */
function local_to_utc(?string $localInput, string $tz): ?string
{
    $localInput = trim((string) $localInput);
    if ($localInput === '') {
        return null;
    }
    try {
        $dt = new DateTime($localInput, new DateTimeZone($tz !== '' ? $tz : 'UTC'));
        return $dt->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d H:i:sP');
    } catch (Exception) {
        return null;
    }
}

// --------------------------------------------------------------------------
// CSRF (guards every unsafe verb; accepts the hidden field OR the X-CSRF-Token
// header stamped by the shell's htmx:configRequest listener).
// --------------------------------------------------------------------------
function csrf_token(): string
{
    return (string) ($_SESSION['csrf_token'] ?? '');
}

function csrf_field(): string
{
    return '<input type="hidden" name="csrf_token" value="' . e(csrf_token()) . '">';
}

function verify_csrf(): void
{
    $unsafe = ['POST', 'PUT', 'PATCH', 'DELETE'];
    if (!in_array($_SERVER['REQUEST_METHOD'] ?? 'GET', $unsafe, true)) {
        return;
    }
    // An action-token-authenticated request (assistant) carries no CSRF token; the signed
    // action token is itself the CSRF protection.
    if (function_exists('is_action_authed') && is_action_authed()) {
        return;
    }
    $sent = $_POST['csrf_token'] ?? ($_SERVER['HTTP_X_CSRF_TOKEN'] ?? '');
    if (!hash_equals(csrf_token(), (string) $sent)) {
        if (wants_json()) {
            json_error('csrf_failed', 'CSRF validation failed.', 403);
        }
        http_response_code(403);
        exit('CSRF validation failed.');
    }
}

/**
 * Emit a machine-readable result header for action-token callers (the actions MCP server),
 * so it can tell success from a validation re-render without parsing HTML. No-op for
 * browser requests. Call at a controller's success and validation-error points.
 */
function emit_action_status(bool $ok, array $data = []): void
{
    // Recorded for every caller: JSON mode answers from it at shutdown (json_mode_finish()).
    // The first failure stands — a later "ok" cannot paper over a refusal.
    if (!isset($GLOBALS['__action_status']) || $GLOBALS['__action_status']['ok']) {
        $GLOBALS['__action_status'] = ['ok' => $ok, 'data' => $data];
    }
    if (function_exists('is_action_authed') && is_action_authed() && !headers_sent()) {
        header('X-Action-Status: ' . ($ok ? 'ok' : 'error'));
        if ($data !== []) {
            header('X-Action-Data: ' . json_encode($data, JSON_UNESCAPED_SLASHES));
        }
    }
}

// --------------------------------------------------------------------------
// Redirect helpers (HTMX-aware)
// --------------------------------------------------------------------------
/** Full navigation redirect (used for login/logout/2FA — never a swap). */
function redirect(string $path): never
{
    // A JSON caller cannot follow a navigation; it is told where the browser would have gone.
    if (wants_json()) {
        respond_saved(['location' => $path]);
    }
    // For an HTMX request that must become a real navigation, HX-Redirect does it.
    if (is_htmx_request()) {
        header('HX-Redirect: ' . $path);
    } else {
        header('Location: ' . $path);
    }
    http_response_code(is_htmx_request() ? 200 : 302);
    exit;
}

/** Tell HTMX to swap a canonical URL into #page-content and push it to history. */
function hx_location(string $path, string $target = '#page-content'): void
{
    header('HX-Location: ' . json_encode(['path' => $path, 'target' => $target], JSON_THROW_ON_ERROR));
}

/** Fire a client-side event so listening regions refresh (Pattern D). */
function hx_trigger(string $event): void
{
    header('HX-Trigger: ' . $event);
}
