<?php
declare(strict_types=1);

/**
 * Business OS authorization, settings and approval helpers.
 *
 * Three roles and only three (CLAUDE.md): super_admin, dept_admin, user. "External" is a flag
 * on a user, not a role. Every rule below delegates to the SQL helpers installed by
 * db/030_business_foundation.sql, so the app, the MCP read servers and the agents all decide
 * visibility with the same function in the same place.
 *
 * Endpoints use the manifest's vocabulary directly:
 *   mod:x  -> require_module('x')          admin -> require_business_admin()
 *   super  -> require_super_admin()        all   -> require_login()
 */

// --------------------------------------------------------------------------
// Business settings (one row)
// --------------------------------------------------------------------------
function business_settings(PDO $pdo): array
{
    static $settings = null;
    if ($settings === null) {
        $row = $pdo->query('SELECT * FROM business_settings LIMIT 1')->fetch();
        $settings = $row === false ? [] : $row;
    }
    return $settings;
}

function business_name(PDO $pdo): string
{
    return (string) (business_settings($pdo)['business_name'] ?? 'Business OS');
}

function base_currency(PDO $pdo): string
{
    return (string) (business_settings($pdo)['base_currency'] ?? 'USD');
}

// --------------------------------------------------------------------------
// Role accessors (read the signed-in member; never trust request input)
// --------------------------------------------------------------------------
function business_role(): string
{
    $m = current_member();
    return (string) ($m['business_role'] ?? 'user');
}

function member_kind(): string
{
    $m = current_member();
    return (string) ($m['member_kind'] ?? 'human');
}

function is_super_admin(): bool
{
    return is_logged_in() && business_role() === 'super_admin';
}

function is_dept_admin(): bool
{
    return is_logged_in() && business_role() === 'dept_admin';
}

/** Super-admin, or a dept-admin (scoped to their departments — check the row too). */
function is_business_admin(): bool
{
    return is_super_admin() || is_dept_admin();
}

function is_external_member(): bool
{
    $m = current_member();
    return (bool) ($m['is_external'] ?? false);
}

function is_agent_member(): bool
{
    return member_kind() === 'agent';
}

// --------------------------------------------------------------------------
// Department and module reach (delegated to SQL)
// --------------------------------------------------------------------------
/** @return int[] departments the member belongs to */
function my_department_ids(PDO $pdo): array
{
    static $ids = null;
    if ($ids === null) {
        $ids = pg_int_array($pdo->query('SELECT app_my_department_ids()')->fetchColumn());
    }
    return $ids;
}

/** @return int[] departments the member administers (admin flag or named manager) */
function admin_department_ids(PDO $pdo): array
{
    static $ids = null;
    if ($ids === null) {
        $ids = pg_int_array($pdo->query('SELECT app_admin_department_ids()')->fetchColumn());
    }
    return $ids;
}

function is_admin_of_department(PDO $pdo, ?int $departmentId): bool
{
    if ($departmentId === null) {
        return is_super_admin();
    }
    $st = $pdo->prepare('SELECT app_is_admin_of(:d)');
    $st->execute(['d' => $departmentId]);
    return (bool) $st->fetchColumn();
}

/** The people rule: grants, tokens, contact details, time, leave. */
function can_admin_member(PDO $pdo, int $memberId): bool
{
    $st = $pdo->prepare('SELECT app_can_admin_member(:m)');
    $st->execute(['m' => $memberId]);
    return (bool) $st->fetchColumn();
}

/**
 * False when a super-admin has DISABLED the application (nav_items.status, db/127–129): it is
 * closed to everyone, the super-admin included, until it is switched back on. A hidden
 * application is enabled — it merely has no sidebar entry.
 */
function module_enabled(PDO $pdo, string $module): bool
{
    static $cache = [];
    if (!array_key_exists($module, $cache)) {
        $st = $pdo->prepare('SELECT app_module_enabled(:m)');
        $st->execute(['m' => $module]);
        $cache[$module] = (bool) $st->fetchColumn();
    }
    return $cache[$module];
}

/**
 * The front door (called once, by app/bootstrap.php). Handlers gate in many ways, so a DISABLED
 * application is closed by address before any of them — for a person and for the actions MCP
 * server alike. app_path_closed() (db/129) names the disabled entry that owns the path.
 */
function refuse_disabled_application(): void
{
    $path = (string) parse_url((string) ($_SERVER['REQUEST_URI'] ?? ''), PHP_URL_PATH);
    if ($path === '' || $path === '/' || str_starts_with($path, '/api/')) {
        return;
    }
    $st = db()->prepare('SELECT app_path_closed(:p)');
    $st->execute(['p' => $path]);
    $label = $st->fetchColumn();
    if (is_string($label) && $label !== '') {
        deny($label . ' is switched off for this business. A super-admin can switch it back on '
            . 'under Settings → Navigation.');
    }
}

function has_module(PDO $pdo, string $module): bool
{
    if (!module_enabled($pdo, $module)) {
        return false;
    }
    static $cache = [];
    if (!array_key_exists($module, $cache)) {
        $st = $pdo->prepare('SELECT app_has_module(:m)');
        $st->execute(['m' => $module]);
        $cache[$module] = (bool) $st->fetchColumn();
    }
    // A dept-admin reaches their own departments' records without a module grant; the row-level
    // rule (app_can_see) decides that. For screen entry, a dept-admin is admitted to the module.
    return $cache[$module] || is_business_admin();
}

/** The row rule — same function the mcp_* views use. */
function can_see_record(
    PDO $pdo,
    string $module,
    ?int $ownerMemberId,
    ?int $departmentId,
    string $entityType,
    int $entityId,
    ?int $organizationId = null
): bool {
    $st = $pdo->prepare('SELECT app_can_see(:mod, :owner, :dept, :etype, :eid, :org)');
    $st->execute([
        'mod' => $module, 'owner' => $ownerMemberId, 'dept' => $departmentId,
        'etype' => $entityType, 'eid' => $entityId, 'org' => $organizationId,
    ]);
    return (bool) $st->fetchColumn();
}

// --------------------------------------------------------------------------
// Gates (call one at the top of every endpoint, GET and POST)
// --------------------------------------------------------------------------
function deny(string $message = 'You do not have access to this.'): never
{
    emit_action_status(false, ['error' => $message]);
    if (wants_json()) {
        json_error('forbidden', $message, 403);
    }
    http_response_code(403);
    if (is_htmx_request()) {
        echo '<div class="alert alert-danger m-4" role="alert">' . e($message) . '</div>';
    } else {
        echo e($message);
    }
    exit;
}

function require_module(string $module): void
{
    require_login();
    if (!module_enabled(db(), $module)) {
        deny('This application is switched off for the business. A super-admin can switch it '
            . 'back on under Settings → Navigation.');
    }
    if (!has_module(db(), $module)) {
        deny('You do not have access to this module.');
    }
}

/**
 * Admission to the DATA, not merely to the screen — stricter than require_module().
 *
 * has_module() admits any business admin to a module's screens (see its own note), which is
 * right for a module whose rows carry a department: there `app_can_see(module, owner, dept, …)`
 * honours a dept-admin inside the departments they administer, and the row rule does the real
 * work. It is wrong for a module whose read views are gated on the bare grant because its rows
 * are business-wide and have no department to scope by — `app_can_see_books()` is literally
 * `app_has_module('books')`, and `mcp_accountant_exports` is gated the same way. A dept-admin
 * admitted there gets empty screens and 404s on rows that plainly exist, which reads as a
 * broken app rather than a permission.
 *
 * Found twice in review (Expenses 2026-09-18, then the ledger): admission to the screen is not
 * admission to the data. Refuse at the door, naming the grant, so the answer is actionable.
 *
 * Note for the doc vocabulary: `mod:x` in the action manifest means "super-admin, or a
 * dept-admin within their departments, or a grant holder". For a business-wide module there is
 * no "within their departments", so `mod:x` collapses to "super-admin or grant holder" — which
 * is exactly what this function enforces.
 */
function require_module_grant(string $module): void
{
    if (!has_module_grant($module)) {
        deny('This needs the ' . $module . ' module grant, which is business-wide data rather '
            . 'than your department\'s. An admin can grant it under HR → People & access.');
    }
}

/**
 * The same rule as require_module_grant(), asked rather than enforced: a screen uses it to
 * decide whether to offer the buttons the endpoint would accept. Deliberately NOT has_module(),
 * which admits a dept-admin to a module for the sake of their own departments' records — a
 * business-wide module has no such records, so offering a dept-admin an Edit button here would
 * only walk them into a refusal.
 */
function has_module_grant(string $module): bool
{
    require_login();
    if (!module_enabled(db(), $module)) {
        return false;                               // disabled: closed to the super-admin too
    }
    if (is_super_admin()) {
        return true;
    }
    static $cache = [];
    if (!array_key_exists($module, $cache)) {
        $st = db()->prepare('SELECT app_has_module(:m)');
        $st->execute(['m' => $module]);
        $cache[$module] = (bool) $st->fetchColumn();
    }
    return $cache[$module];
}

function require_business_admin(): void
{
    require_login();
    if (!is_business_admin()) {
        deny('This needs an administrator.');
    }
}

/**
 * Anyone who works here — the PHP mirror of SQL's `app_is_insider()`
 * (`app_business_role() <> 'anon' AND NOT app_is_external()`).
 *
 * Some modules are readable by every member of the business and changeable only by a grant
 * holder. The estate is the first: `mcp_locations` is gated on `app_is_insider()`, and the
 * action manifest gives its read tools the `insider` gate while every estate *action* is
 * `mod:locations`. Reading it with `require_module_grant()` would refuse at the screen someone
 * the MCP surface answers happily — the same screen-versus-data mismatch as before, pointing
 * the other way.
 */
function require_insider(): void
{
    require_login();
    if (is_external_member()) {
        deny('This is internal to the business.');
    }
}

function require_super_admin(): void
{
    require_login();
    if (!is_super_admin()) {
        deny('This needs the super-admin.');
    }
}

/** Admin gate for one record: a dept-admin only inside the departments they administer. */
function require_admin_for_department(PDO $pdo, ?int $departmentId): void
{
    require_login();
    if (is_super_admin()) {
        return;
    }
    if (!is_dept_admin() || !is_admin_of_department($pdo, $departmentId)) {
        deny('This needs an administrator of that department.');
    }
}

// --------------------------------------------------------------------------
// Approval awareness (manifest decision 5)
// --------------------------------------------------------------------------
/**
 * Does an active policy pause this action for the acting member? Returns the matching policy
 * row, or null when the action may execute now. $logEvent is the manifest log event
 * ('organization.delete'); $amount/$currency are required for money thresholds.
 */
function approval_required(PDO $pdo, string $logEvent, ?string $amount = null, ?string $currency = null): ?array
{
    $memberId = current_member_id();
    if ($memberId === null) {
        return null;
    }
    $st = $pdo->prepare(<<<'SQL'
        SELECT p.*
          FROM approval_policies p
         WHERE p.active
           AND (
                :event = p.action_pattern
             OR (p.action_pattern LIKE '%.*' AND :event LIKE replace(p.action_pattern, '.*', '.') || '%')
             OR (p.action_pattern LIKE '*.%' AND :event LIKE '%.' || replace(p.action_pattern, '*.', ''))
           )
           AND (
                (p.applies_to = 'agents'     AND (SELECT member_kind FROM members WHERE id = :me) = 'agent')
             OR (p.applies_to = 'agent'      AND p.agent_member_id = :me)
             OR (p.applies_to = 'department' AND p.department_id = ANY (app_my_department_ids()))
             OR  p.applies_to = 'everyone'
           )
           AND (
                p.amount_threshold IS NULL
             OR (:amount::numeric IS NOT NULL AND :currency::text IS NOT NULL
                 AND p.currency = :currency::bpchar AND :amount::numeric >= p.amount_threshold)
           )
         ORDER BY p.amount_threshold NULLS FIRST, p.id
         LIMIT 1
    SQL);
    $st->execute(['event' => $logEvent, 'me' => $memberId, 'amount' => $amount, 'currency' => $currency]);
    $row = $st->fetch();
    return $row === false ? null : $row;
}

/**
 * Write the paused request and return its id. Approver: the policy's approver, else the
 * requester's manager (agents always have one), else their department's manager, else the
 * lowest-id active super-admin.
 */
function create_approval_request(
    PDO $pdo,
    array $policy,
    string $actionKey,
    string $summary,
    array $parameters,
    ?string $entityType = null,
    ?int $entityId = null,
    ?string $amount = null,
    ?string $currency = null,
    ?string $handlerPath = null,
    ?array $requestBody = null
): int {
    $me = (int) current_member_id();
    $approver = $policy['approver_member_id'] !== null ? (int) $policy['approver_member_id'] : null;

    if ($approver === null) {
        $st = $pdo->prepare(<<<'SQL'
            SELECT COALESCE(
                -- The nearest HUMAN up the management chain. An agent's manager is often another
                -- agent (an orchestrator), and an agent may never decide an approval — routing the
                -- request to one would leave it waiting on someone forbidden to answer. Whether an
                -- orchestrator may answer approvals is an open question in the requirements; until
                -- the owner opens it, a person decides. Delegation is one level deep, but the walk is
                -- bounded anyway.
                (WITH RECURSIVE chain AS (
                     SELECT ap.manager_member_id AS id, 1 AS depth FROM agent_profiles ap WHERE ap.member_id = :me
                     UNION ALL
                     SELECT ap.manager_member_id, c.depth + 1
                       FROM chain c JOIN agent_profiles ap ON ap.member_id = c.id
                      WHERE c.depth < 8)
                 SELECT c.id FROM chain c JOIN members m ON m.id = c.id
                  WHERE m.member_kind = 'human' AND m.status = 'active'
                  ORDER BY c.depth LIMIT 1),
                (SELECT d.manager_member_id FROM departments d
                   JOIN department_members dm ON dm.department_id = d.id
                  WHERE dm.member_id = :me AND dm.left_at IS NULL AND d.manager_member_id IS NOT NULL
                  ORDER BY dm.is_primary DESC, d.id LIMIT 1),
                (SELECT m.id FROM members m
                  WHERE m.business_role = 'super_admin' AND m.status = 'active' ORDER BY m.id LIMIT 1))
        SQL);
        $st->execute(['me' => $me]);
        $approver = (int) $st->fetchColumn();
    }

    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO approval_requests
            (policy_id, requested_by_member_id, action_key, parameters, summary, amount, currency,
             entity_type, entity_id, approver_member_id, expires_at,
             agent_run_id, handler_path, request_body)
        VALUES
            (:policy, :me, :action, :params, :summary, :amount, :currency,
             :etype, :eid, :approver, now() + make_interval(hours => :hours),
             :run, :handler, :body)
        RETURNING id
    SQL);
    $st->execute([
        'policy'   => $policy['id'],
        'me'       => $me,
        'action'   => $actionKey,
        'params'   => json_encode($parameters, JSON_THROW_ON_ERROR),
        'summary'  => $summary,
        'amount'   => $amount,
        'currency' => $currency,
        'etype'    => $entityType,
        'eid'      => $entityId,
        'approver' => $approver,
        // What an approval replays (db/097). `parameters` is the summary the caller chose and
        // cannot re-run the action; this is the request itself, minus the one-use CSRF token.
        // An uploaded file is not in $_POST and so is not replayable — such an action must say so.
        'run'      => function_exists('current_agent_run_id') ? current_agent_run_id() : null,
        // The approval hook (A7) names an application's handler by absolute URL and hands the body.
        'handler'  => $handlerPath ?? (parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH) ?: null),
        'body'     => json_encode($requestBody ?? array_diff_key($_POST, ['csrf_token' => true]), JSON_THROW_ON_ERROR),
        'hours'    => (int) $policy['expires_after_hours'],
    ]);
    $requestId = (int) $st->fetchColumn();

    // Announce it. Every module's pause comes through here, so no slice can add an approval and
    // forget to tell the person who has to decide it (build plan, phase 5 step 5).
    require_once __DIR__ . '/features/approvals/notify.php';
    notify_approval_raised($pdo, $requestId, $approver, $summary, $amount, $currency,
        current_member()['display_name'] ?? 'Someone');
    return $requestId;
}

/**
 * The one call an endpoint makes: if a policy matches, record the request, answer the caller
 * and stop. Returns normally when the action may proceed.
 */
function check_approval(
    PDO $pdo,
    string $actionKey,
    string $logEvent,
    string $summary,
    array $parameters,
    ?string $entityType = null,
    ?int $entityId = null,
    ?string $amount = null,
    ?string $currency = null
): void {
    // The approved replay of this very request passes — once (features/approvals/replay.php).
    // The action then runs as its requester; for an agent that means the run it belonged to, so
    // the handler's own log line carries source='agent', the run's request_id and agent_run_id.
    if (($_SERVER['HTTP_X_APPROVAL_REPLAY'] ?? '') !== '') {
        require_once __DIR__ . '/features/approvals/queries.php';
        require_once __DIR__ . '/features/approvals/replay.php';
        $approved = approval_replay_verify($pdo, $actionKey);
        if ($approved !== null) {
            $GLOBALS['__approval_replay_id'] = (int) $approved['id'];
            if ($approved['agent_run_id'] !== null) {
                $GLOBALS['__agent_run_id'] = (int) $approved['agent_run_id'];
            }
            return;
        }
    }
    $policy = approval_required($pdo, $logEvent, $amount, $currency);
    if ($policy === null) {
        return;
    }
    $requestId = create_approval_request($pdo, $policy, $actionKey, $summary, $parameters,
        $entityType, $entityId, $amount, $currency);
    log_activity($pdo, 'approval_request.create', 'approval_request', $requestId, [
        'after' => ['action_key' => $actionKey, 'summary' => $summary, 'policy' => $policy['name']],
    ]);
    emit_action_status(false, [
        'status' => 'pending_approval',
        'did' => $summary . ' waits for approval',
        'approval_request_id' => $requestId,
    ]);
    http_response_code(202);
    echo '<div class="alert alert-warning m-4" role="alert">'
        . e($summary) . ' needs approval first (policy: ' . e((string) $policy['name']) . '). '
        . 'It has been sent to the approver and nothing was changed.</div>';
    exit;
}

// --------------------------------------------------------------------------
// The menu — data since db/127 (nav_groups, nav_items, app_nav()); docs/build-specs/data-driven-nav.md.
// Nothing about which applications exist, or how they are grouped, lives in code.
// --------------------------------------------------------------------------
/**
 * The signed-in member's sidebar, grouped. The menu is data (db/127): app_nav() is the one
 * gatherer — who sees what is decided there, not here.
 */
function nav_modules(PDO $pdo): array
{
    $groups = [];
    $sql = 'SELECT group_name, item_key, label, url, icon, phase, opens,
                   array_to_json(active_patterns) AS active_patterns
              FROM app_nav()';
    foreach ($pdo->query($sql) as $row) {
        $groups[$row['group_name']][] = [
            'key' => $row['item_key'], 'label' => $row['label'], 'url' => $row['url'],
            'icon' => $row['icon'], 'phase' => (int) $row['phase'], 'opens' => $row['opens'],
            'active_patterns' => json_decode((string) $row['active_patterns'], true) ?: [],
        ];
    }
    return $groups;
}

function module_by_key(string $key): ?array
{
    $st = db()->prepare(<<<'SQL'
        SELECT g.name AS "group", i.item_key AS key, i.label, i.url, i.icon, i.module, i.phase
          FROM nav_items i JOIN nav_groups g ON g.id = i.group_id
         WHERE i.item_key = :k
    SQL);
    $st->execute(['k' => $key]);
    return $st->fetch() ?: null;
}

// --------------------------------------------------------------------------
// Small helpers
// --------------------------------------------------------------------------
/** Parse a PostgreSQL int array literal ('{1,2}') into an int[]. */
function pg_int_array(?string $literal): array
{
    $literal = trim((string) $literal, '{}');
    if ($literal === '') {
        return [];
    }
    return array_map('intval', explode(',', $literal));
}

/** Render a PHP int[] as a PostgreSQL array literal. */
function pg_array_literal(array $values): string
{
    return '{' . implode(',', array_map(static fn ($v) => (string) $v, $values)) . '}';
}

/** Format money for display: "1,234.50 USD" — never summed across currencies. */
function money(?string $amount, ?string $currency): string
{
    if ($amount === null || $amount === '') {
        return '—';
    }
    return number_format((float) $amount, 2) . ' ' . strtoupper((string) $currency);
}
