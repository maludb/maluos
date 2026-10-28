<?php
declare(strict_types=1);

/** Member detail (screen `member-view`). Gate: admin; a dept-admin only for people they administer. */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/team/queries.php';

require_business_admin();

$pdo = db();
$id = request_integer('id');
if ($id === null) {
    http_response_code(404);
    exit('Member not found.');
}

$member = find_team_member($pdo, $id);
if ($member === null) {
    http_response_code(404);
    exit('Member not found.');
}

log_screen_view($pdo, 'member-view');
if (wants_json()) {
    require_once dirname(__DIR__, 2) . '/app/features/team/present.php';
    respond_screen([
        'member' => present_team_member($member, current_member()['timezone'] ?? 'UTC'),
        'departments' => array_map('present_member_department', member_departments($pdo, $id)),
        'modules' => present_module_access(grantable_modules(), member_module_grants($pdo, $id)),
        // Every application and scope a grant reaches them through (db/141) — gated as mcp_application_access is.
        'applications' => (static function () use ($pdo, $id): array {
            $st = $pdo->prepare(<<<'SQL'
                SELECT ac.application_id, ac.application_name, ac.scope_name, ac.role_name, ac.capability,
                       ac.department_id AS route_department_id, ac.resident_location_id AS route_location_id,
                       ac.scope_location_id, ac.scope_department_id,
                       CASE WHEN ac.member_id IS NOT NULL THEN 'Direct'
                            WHEN ac.department_id IS NOT NULL THEN ac.department_name
                            ELSE 'Everyone at ' || ac.resident_location_name END AS route
                  FROM mcp_application_access ac
                 WHERE ac.member_id = :m
                    OR ac.department_id IN (SELECT department_id FROM mcp_department_members WHERE member_id = :m AND left_at IS NULL)
                    OR ac.resident_location_id IN (SELECT location_id FROM mcp_location_residents WHERE member_id = :m)
                 ORDER BY ac.application_name, ac.scope_name
                 LIMIT 200
            SQL);
            $st->execute(['m' => $id]);
            return array_map(static fn (array $r): array => [
                'id' => (int) $r['application_id'], 'name' => (string) $r['application_name'],
                'scope' => $r['scope_name'] !== null ? (string) $r['scope_name'] : null,
                'role' => $r['role_name'] !== null ? (string) $r['role_name'] : null,
                'capability' => (string) $r['capability'], 'route' => (string) $r['route'],
                // Click-around step 3 (db/151): the route's department or location and the scope's target, as links.
                'route_department_id' => $r['route_department_id'] !== null ? (int) $r['route_department_id'] : null,
                'route_location_id' => $r['route_location_id'] !== null ? (int) $r['route_location_id'] : null,
                'scope_location_id' => $r['scope_location_id'] !== null ? (int) $r['scope_location_id'] : null,
                'scope_department_id' => $r['scope_department_id'] !== null ? (int) $r['scope_department_id'] : null,
            ], $st->fetchAll());
        })(),
        // db/142: where app.<domain>/ takes them; set by them or by whoever administers them.
        'default_application' => ($member['member_kind'] ?? 'human') === 'human' ? (static function () use ($pdo, $id): array {
            require_once dirname(__DIR__, 2) . '/app/features/applications/queries.php';
            return present_member_default_application($pdo, find_member_by_id($pdo, $id) ?? ['id' => $id]);
        })() : null,
        'can' => ['admin' => can_admin_member($pdo, $id),
                  // Maintaining a person (2026-09-26): their details by an admin, suspension by the super-admin.
                  'update' => ($member['member_kind'] ?? '') === 'human' && can_admin_member($pdo, $id),
                  'suspend' => ($member['member_kind'] ?? '') === 'human' && is_super_admin() && ($member['status'] ?? '') === 'active'
                      && $id !== (int) current_member_id(),
                  'reinstate' => ($member['member_kind'] ?? '') === 'human' && is_super_admin() && ($member['status'] ?? '') === 'suspended',
                  'set_default_application' => ($member['member_kind'] ?? 'human') === 'human'
                      && ((int) current_member_id() === $id || can_admin_member($pdo, $id))],
    ]);
}
$pageHtml = view('team/view.php', [
    'member' => $member,
    'departments' => member_departments($pdo, $id),
    'grants' => member_module_grants($pdo, $id),
    'modules' => grantable_modules(),
    'canAdmin' => can_admin_member($pdo, $id),
    'viewerTz' => current_member()['timezone'] ?? 'UTC',
]);
render_screen($member['display_name'] . ' · Team · ' . business_name($pdo), $pageHtml,
    ['activeNav' => 'nav-agents', 'screen' => 'member-view', 'entity' => 'member', 'recordId' => (string) $id]);
