<?php
declare(strict_types=1);

/**
 * Team & Access presenters. Whitelists, mirrored by web/lib/schemas/team.ts
 * (docs/react-migration-plan.md, "Presenters, never raw rows"). Everything here reads from
 * mcp_team_directory / mcp_departments / mcp_department_members / mcp_module_grants rows —
 * never from `members`, which carries password_hash and totp_secret.
 */

/** "{HR,"Front Office"}" → ["HR", "Front Office"] — the directory's department names. */
function present_pg_names(mixed $literal): array
{
    if (!is_string($literal) || $literal === '' || $literal === '{}') {
        return [];
    }
    return array_values(array_filter(array_map(
        static fn (string $s): string => trim($s, '"'),
        str_getcsv(trim($literal, '{}'), ',', '"', '\\')
    ), static fn (string $s): bool => $s !== ''));
}

/** One row of the people list (team_members()). */
/** The `department_ids` beside `departments` (db/151), zipped with the names: [{id, name}] in the view's order. */
function present_department_links(array $m): array
{
    $names = present_pg_names($m['departments'] ?? null);
    $ids = array_values(array_filter(array_map('intval', present_pg_names($m['department_ids'] ?? null)), static fn (int $i): bool => $i > 0));
    if (count($ids) !== count($names)) {
        return [];
    }
    return array_map(static fn (int $id, string $name): array => ['id' => $id, 'name' => $name], $ids, $names);
}

function present_team_member_row(array $m): array
{
    return [
        'id' => (int) $m['member_id'],
        'display_name' => (string) $m['display_name'],
        'kind' => (string) $m['member_kind'],
        'business_role' => (string) $m['business_role'],
        'departments' => present_pg_names($m['departments'] ?? null),
        'department_links' => present_department_links($m),
        'email' => ($m['email'] ?? '') !== '' ? $m['email'] : null,
    ];
}

/** A member's identity card (find_team_member()). last_login is formatted in the viewer's zone. */
function present_team_member(array $m, string $viewerTz): array
{
    $lastLogin = format_ts($m['last_login_at'] ?? null, $viewerTz);
    return present_team_member_row($m) + [
        'job_title' => ($m['job_title'] ?? '') !== '' ? $m['job_title'] : null,
        'status' => $m['status'] ?? null,
        'timezone' => $m['timezone'] ?? null,
        'phone' => ($m['phone'] ?? '') !== '' ? (string) $m['phone'] : null,
        'has_2fa' => isset($m['has_2fa']) ? (bool) $m['has_2fa'] : null,
        'last_login_display' => $lastLogin !== '' ? $lastLogin : null,
    ];
}

/** A department a member belongs to (member_departments()). */
function present_member_department(array $d): array
{
    return [
        'id' => (int) $d['department_id'],
        'name' => (string) $d['department_name'],
        'is_admin' => (bool) $d['is_admin'],
        'is_primary' => (bool) $d['is_primary'],
    ];
}

/**
 * Every grantable module with this member's access to it ('' = none), in catalog order —
 * grantable_modules() joined to member_module_grants(), as both team templates did inline.
 */
function present_module_access(array $modules, array $grants): array
{
    $out = [];
    foreach ($modules as $key => $label) {
        $out[] = ['key' => (string) $key, 'label' => (string) $label, 'access' => (string) ($grants[$key]['access'] ?? '')];
    }
    return $out;
}

/** A department, for the list, its page and its form (find_departments() / find_department()). */
function present_department(array $d): array
{
    $int = static fn (string $k): ?int => isset($d[$k]) && $d[$k] !== '' ? (int) $d[$k] : null;
    return [
        'id' => $int('department_id'),
        'name' => (string) ($d['name'] ?? ''),
        'description' => ($d['description'] ?? '') !== '' ? $d['description'] : null,
        'handbook_markdown' => ($d['handbook_markdown'] ?? '') !== '' ? (string) $d['handbook_markdown'] : null,
        'parent_id' => $int('parent_id'),
        'parent_name' => $d['parent_name'] ?? null,
        'manager_member_id' => $int('manager_member_id'),
        'manager_name' => $d['manager_name'] ?? null,
        'home_location_id' => $int('home_location_id'),
        'home_location_name' => $d['home_location_name'] ?? null,
        'member_count' => (int) ($d['member_count'] ?? 0),
        'monthly_budget_amount' => isset($d['monthly_budget_amount']) ? (string) $d['monthly_budget_amount'] : null,
        'budget_currency' => $d['budget_currency'] ?? null,
        'budget_display' => isset($d['monthly_budget_amount'])
            ? money($d['monthly_budget_amount'], $d['budget_currency'] ?? null) : null,
        'is_system' => (bool) ($d['is_system'] ?? false),
        'system_key' => $d['system_key'] ?? null,
    ];
}

/** A member of one department (department_members()). */
function present_department_member(array $m): array
{
    return [
        'id' => (int) $m['member_id'],
        'name' => (string) $m['member_name'],
        'kind' => (string) $m['member_kind'],
        'is_admin' => (bool) $m['is_admin'],
        'is_primary' => (bool) $m['is_primary'],
    ];
}

/** One tie between a department and an application (department_applications()). */
function present_department_application(array $a): array
{
    return [
        'id' => (int) $a['application_id'],
        'name' => (string) $a['name'],
        'status' => (string) $a['status'],
        'tie' => (string) $a['tie'],
        'role' => $a['role_key'] !== null ? (string) $a['role_key'] : null,
        'capability' => $a['capability'] !== null ? (string) $a['capability'] : null,
        'scope_name' => $a['scope_name'] !== null ? (string) $a['scope_name'] : null,
    ];
}

/**
 * One kind of thing that names a department (department_ties()). A ledger line's amount is the
 * super-admin's to read, so anyone else sees that the line exists and not what it says.
 */
function present_department_tie(array $t, bool $superAdmin): array
{
    return [
        'key' => (string) $t['key'],
        'label' => (string) $t['label'],
        'blocks' => (bool) $t['blocks'],
        'items' => array_map(static fn (array $i): array => [
            'id' => (int) $i['id'],
            'name' => (string) $i['name'],
            'detail' => $t['key'] === 'ledger_lines' && !$superAdmin ? null
                : ($i['detail'] !== null ? (string) $i['detail'] : null),
        ], $t['items']),
    ];
}

/** One live application grant reaching a member (member_application_grants()); `route` = how. */
function present_member_application_grant(array $g): array
{
    return [
        'id' => (int) $g['application_access_id'],
        'application_id' => (int) $g['application_id'],
        'application_name' => (string) $g['application_name'],
        'route' => (string) $g['route'],
        'through_id' => $g['through_id'] !== null ? (int) $g['through_id'] : null,
        'through_name' => $g['through_name'] !== null ? (string) $g['through_name'] : null,
        'scope_name' => $g['scope_name'] !== null ? (string) $g['scope_name'] : null,
        'role_key' => $g['role_key'] !== null ? (string) $g['role_key'] : null,
        'role_name' => $g['role_name'] !== null ? (string) $g['role_name'] : null,
        'capability' => (string) $g['capability'],
        'expires_at' => json_ts($g['expires_at'] ?? null),
        'roles' => array_map(static fn (array $r): array => ['key' => (string) $r['key'], 'name' => (string) $r['name'],
            'withdrawn' => !empty($r['withdrawn'])], json_decode((string) ($g['roles'] ?? '[]'), true) ?: []),
    ];
}

/** An application offered for a grant, with its roles and scopes (grantable_applications()). */
function present_grantable_application(array $a): array
{
    return [
        'id' => (int) $a['id'],
        'name' => (string) $a['name'],
        'scope_kind' => (string) $a['scope_kind'],
        'roles' => array_map(static fn (array $r): array => [
            'key' => (string) $r['role_key'], 'name' => (string) $r['name'], 'capability' => (string) $r['capability'],
            'description' => ($r['description'] ?? '') !== '' ? (string) $r['description'] : null,
            'rights' => array_values(array_map(static fn ($x): array => ['key' => (string) ($x['key'] ?? ''), 'description' => (string) ($x['description'] ?? '')],
                json_decode((string) ($r['rights'] ?? '[]'), true) ?: [])),
        ], $a['roles']),
        'scopes' => array_map(static fn (array $s): array => ['id' => (int) $s['id'], 'name' => (string) $s['name']], $a['scopes']),
    ];
}

/** An application one department member can use (department_member_applications()). */
function present_member_application(array $a): array
{
    return ['id' => (int) $a['application_id'], 'name' => (string) $a['name'], 'capability' => (string) $a['capability']];
}

/** A location offered in a picker (business_locations()). */
function present_location_option(array $l): array
{
    return ['id' => (int) $l['location_id'], 'name' => (string) $l['name'],
            'kind' => (string) $l['kind'], 'siting' => $l['siting'] ?? null];
}
