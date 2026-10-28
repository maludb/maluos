<?php
declare(strict_types=1);

/**
 * GET /api/v1/session — what the Next.js server needs before it can render or post anything
 * (docs/react-migration-plan.md, "The PHP side"): whether the visitor is signed in, the
 * session's CSRF token, and the shell payload (member, role flags, business, navigation).
 *
 * Session-only, by design. No bearer path and no CORS headers: this hands out a CSRF token,
 * so it must never be readable cross-origin, and a token caller has no session to protect.
 * An anonymous caller gets a pre-login session (the Set-Cookie on this response) and its
 * token — that is how the login form's POST passes verify_csrf().
 *
 * Not logged to activity_log: the shell calls this on every render. It is neither a screen
 * view nor a state change, and activity memory cannot be un-polluted.
 */
require_once dirname(__DIR__, 3) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/logo.php';

api_require_get();

$pdo = db();
$member = is_logged_in() ? current_member() : null;
if ($member !== null && ($member['status'] ?? '') !== 'active') {
    $member = null;
}

$payload = [
    'authenticated' => $member !== null,
    'csrf_token' => csrf_token(),
    'two_factor_pending' => $member === null && pending_2fa_member_id() !== null,
    'google_enabled' => google_enabled(),
    'business' => ['name' => business_name($pdo)],
    'member' => null,
    'nav' => [],
];

if ($member !== null) {
    $payload['business']['currency'] = base_currency($pdo);
    // The company's own logo, if one was uploaded (db/134); null = the shipped logo-full.png.
    $payload['business']['logo_url'] = business_logo_url($pdo);
    // Whitelist — never the members row (password_hash, totp_secret live there).
    $payload['member'] = [
        'id' => (int) $member['id'],
        'display_name' => $member['display_name'],
        'email' => $member['email'],
        'job_title' => $member['job_title'],
        'timezone' => $member['timezone'],
        'kind' => member_kind(),
        'business_role' => business_role(),
        'is_external' => is_external_member(),
        'is_super_admin' => is_super_admin(),
        'is_dept_admin' => is_dept_admin(),
        'is_admin' => is_business_admin(),
        'admin_department_ids' => admin_department_ids($pdo),
    ];
    foreach (nav_modules($pdo) as $group => $items) {
        $payload['nav'][] = ['group' => $group, 'items' => $items];
    }
}

api_json($payload);
