<?php
declare(strict_types=1);

/**
 * Screen `invitations` — /team/invitations (action manifest, "Team & access"): invite people and
 * manage the invitations that are still pending. Gate: admin. Reads go through
 * mcp_business_invitations, so a dept-admin sees only invitations into departments they
 * administer. JSON only — this screen was born after the React cut-over and has no template.
 */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/invitations/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/invitations/present.php';
require_once dirname(__DIR__, 3) . '/app/features/team/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/records/present.php';   // present_department_option()

require_business_admin();

$pdo = db();
log_screen_view($pdo, 'invitations');

// A dept-admin invites into the departments they administer; a super-admin into any, or none.
$mine = admin_department_ids($pdo);
$departments = array_values(array_filter(find_departments($pdo),
    static fn (array $d): bool => is_super_admin() || in_array((int) $d['department_id'], $mine, true)));
$roles = is_super_admin() ? INVITABLE_BUSINESS_ROLES : ['user', 'dept_admin'];

respond_screen([
    'invitations' => array_map('present_pending_invitation', find_pending_business_invitations($pdo)),
    'options' => [
        'departments' => array_map('present_department_option', $departments),
        'business_roles' => array_map(
            static fn (string $r): array => ['id' => $r, 'name' => BUSINESS_ROLE_LABELS[$r]], $roles),
    ],
    'can' => ['invite_without_department' => is_super_admin()],
    'ttl_days' => INVITE_TTL_DAYS,
]);
