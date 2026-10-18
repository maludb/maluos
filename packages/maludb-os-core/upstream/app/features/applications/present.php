<?php
declare(strict_types=1);

/**
 * Applications registry presenters. Whitelists, mirrored by web/lib/schemas/applications.ts
 * (docs/react-migration-plan.md, "Presenters, never raw rows"). An endpoint carries only
 * `has_credential` — no screen, view, tool or log row here ever carries a credential's value,
 * and neither does any payload.
 */

function application_category_label(?string $category): string
{
    return ucwords(str_replace('_', ' ', (string) $category));
}

/** Health as the badge shows it: a status and the words under it (health-badge.php). */
function present_application_health(array $a): array
{
    $status = (string) ($a['health_status'] ?? 'unknown');
    $checkedAt = $a['last_health_check_at'] ?? null;
    $detail = $checkedAt === null ? 'never checked'
        : ($status === 'unknown' ? 'not checkable from the platform (checked ' . $checkedAt . ')' : 'checked ' . $checkedAt);
    return ['status' => $status, 'detail' => $detail];
}

/** One row of the registry list (find_applications()). $gaps only when the Gaps filter asked. */
function present_application_row(array $a, array $gaps = []): array
{
    // The cost link went with Expenses in the kernel cut (2026-09-22); the card keeps the key, empty.
    $cost = null;
    return [
        'id' => (int) $a['application_id'],
        'name' => (string) $a['name'],
        'is_builtin' => !empty($a['is_builtin']),
        'gaps' => array_values($gaps),
        'category_display' => application_category_label($a['category'] ?? null),
        'owner_department_name' => $a['owner_department_name'] ?? null,
        'location_name' => $a['location_name'] ?? null,
        'criticality' => (string) ($a['criticality'] ?? 'normal'),
        'status' => (string) ($a['status'] ?? 'active'),
        'health' => present_application_health($a),
        'endpoint_count' => (int) ($a['endpoint_count'] ?? 0),
        'has_agent_mcp' => !empty($a['has_agent_mcp']),
        'monthly_cost_display' => $cost,
    ];
}

/** The unheaded menu group holds what people open every day; here it needs a name. */
function business_area_label(?string $name): string
{
    return ($name ?? '') === '' ? 'Everyday' : (string) $name;
}

/**
 * A registered application as a card (find_application_inventory()). `state` is what the page
 * highlights: active (running), off (a built-in whose module is disabled), planned, retired.
 */
function present_application_card(array $a, array $gaps = []): array
{
    $status = (string) ($a['status'] ?? 'active');
    $state = match (true) {
        $status === 'retired' => 'retired',
        $status === 'planned' => 'planned',
        empty($a['module_enabled']) => 'off',
        default => 'active',
    };
    return [
        'key' => 'app-' . (int) $a['application_id'],
        'id' => (int) $a['application_id'],
        'catalog_key' => $a['catalog_key'] ?? null,
        'name' => (string) $a['name'],
        'description' => $a['description'] ?? null,
        'icon' => (string) ($a['catalog_icon'] ?? 'feather-grid'),
        'vendor' => $a['vendor'] ?? null,
        'is_builtin' => !empty($a['is_builtin']),
        'state' => $state,
        'status' => $status,
        'health' => present_application_health($a),
        'owner_department_name' => $a['owner_department_name'] ?? null,
        'expert_name' => $a['sme_agent_name'] ?? null,
        // Click-around step 2: the ids beside the names, so the card links them.
        'owner_department_id' => isset($a['owner_department_id']) ? (int) $a['owner_department_id'] : null,
        'expert_member_id' => isset($a['sme_agent_member_id']) ? (int) $a['sme_agent_member_id'] : null,
        'skill_count' => (int) ($a['skill_count'] ?? 0),
        'endpoint_count' => (int) ($a['endpoint_count'] ?? 0),
        'has_agent_mcp' => !empty($a['has_agent_mcp']),
        'gaps' => array_values($gaps),
    ];
}

/** A catalog entry nothing registered carries (find_available_catalog_entries()). */
function present_catalog_card(array $c): array
{
    return [
        'key' => 'catalog-' . $c['catalog_key'],
        'open_url' => null,
        'id' => null,
        'catalog_key' => (string) $c['catalog_key'],
        'name' => (string) $c['name'],
        'description' => (string) $c['description'],
        'icon' => (string) $c['icon'],
        'vendor' => $c['vendor'] ?? null,
        'is_builtin' => $c['kind'] === 'builtin',
        'kind' => (string) $c['kind'],
        'state' => 'available',
        'status' => null,
        'health' => null,
        'owner_department_name' => null,
        'expert_name' => null,
        'skill_count' => 0,
        'endpoint_count' => 0,
        'has_agent_mcp' => false,
        'gaps' => [],
    ];
}

/**
 * The inventory: what runs first, as one list by name ('running'), each card naming its business area;
 * then everything else grouped by business area in menu order ('areas'), within an area by state
 * (turned off, planned, available, retired) and then by name. An area with nothing left is left out.
 * $q, when given, keeps only cards whose name, description, vendor, catalog key or area contains it.
 *
 * @param array $areas     find_business_areas()
 * @param array $cards     presented cards, each with its business_area_id beside it: [areaId|null, card]
 */
function present_application_inventory(array $areas, array $cards, string $q = ''): array
{
    $rank = ['active' => 0, 'off' => 1, 'planned' => 2, 'available' => 3, 'retired' => 4];
    $byName = static fn (array $x, array $y): int => strcasecmp($x['name'], $y['name']);
    $areas[] = ['business_area_id' => null, 'name' => 'Other'];
    $areaName = [];
    foreach ($areas as $area) {
        $areaName[$area['business_area_id'] ?? 0] = business_area_label($area['name']);
    }
    $needle = mb_strtolower(trim($q));
    $running = [];
    $rest = [];
    foreach ($cards as [$areaId, $card]) {
        $card['business_area'] = $areaName[$areaId ?? 0] ?? 'Other';
        if ($needle !== '') {
            $hay = mb_strtolower(implode(' ', [$card['name'], $card['description'] ?? '', $card['vendor'] ?? '',
                                                $card['catalog_key'] ?? '', $card['business_area']]));
            if (!str_contains($hay, $needle)) {
                continue;
            }
        }
        if ($card['state'] === 'active') {
            $running[] = $card;
        } else {
            $rest[] = [$areaId, $card];
        }
    }
    usort($running, $byName);
    $out = [];
    foreach ($areas as $area) {
        $mine = array_map(static fn (array $c): array => $c[1],
            array_values(array_filter($rest, static fn (array $c): bool => $c[0] === $area['business_area_id'])));
        if ($mine === []) {
            continue;
        }
        usort($mine, static fn (array $x, array $y): int => ($rank[$x['state']] <=> $rank[$y['state']]) ?: $byName($x, $y));
        $out[] = [
            'id' => $area['business_area_id'] === null ? null : (int) $area['business_area_id'],
            'name' => business_area_label($area['name']),
            'applications' => $mine,
        ];
    }
    return ['running' => $running, 'areas' => $out];
}

/** One skill that belongs to an application (find_application_skills()). */
function present_application_skill(array $s): array
{
    return [
        'id' => (int) $s['skill_assignment_id'],
        'skill_name' => (string) $s['skill_name'],
        'kind' => (string) ($s['kind'] ?? 'skill'),
        'pinned_bundle_hash' => $s['pinned_bundle_hash'] ?? null,
        'note' => $s['note'] ?? null,
        'created_at' => isset($s['created_at']) ? (string) $s['created_at'] : null,
    ];
}

/** An application, for its page and its form (find_application()). */
function present_application(array $a): array
{
    $int = static fn (string $k): ?int => isset($a[$k]) && $a[$k] !== '' ? (int) $a[$k] : null;
    $str = static fn (string $k): ?string => isset($a[$k]) && $a[$k] !== '' ? (string) $a[$k] : null;
    return [
        'id' => $int('application_id'),
        'name' => (string) ($a['name'] ?? ''),
        'app_key' => $str('app_key'),
        'category' => $str('category'),
        'category_display' => application_category_label($a['category'] ?? null),
        'description' => $str('description'),
        'vendor' => $str('vendor'),
        'is_self_hosted' => !empty($a['is_self_hosted']),
        'is_builtin' => !empty($a['is_builtin']),
        'location_id' => $int('location_id'),
        'location_name' => $str('location_name'),
        'siting' => $str('siting'),
        'owner_department_id' => $int('owner_department_id'),
        'owner_department_name' => $str('owner_department_name'),
        'owner_member_id' => $int('owner_member_id'),
        'owner_name' => $str('owner_name'),
        'url' => $str('url'),
        'sso_path' => $str('sso_path'),
        'sso_logout_path' => $str('sso_logout_path'),
        'directory_writes' => !empty($a['directory_writes']),
        'scope_kind' => (string) ($a['scope_kind'] ?? 'none'),
        'scope_count' => (int) ($a['scope_count'] ?? 0),
        'version' => $str('version'),
        'criticality' => (string) ($a['criticality'] ?? 'normal'),
        'status' => (string) ($a['status'] ?? 'active'),
        'health' => present_application_health($a),
        'notes' => $str('notes'),
        'catalog_key' => $str('catalog_key'),
        'business_area_id' => $int('business_area_id'),
        'business_area_name' => isset($a['business_area_id']) ? business_area_label($a['business_area_name'] ?? '') : null,
        'expert_member_id' => $int('sme_agent_member_id'),
        'expert_name' => $str('sme_agent_name'),
    ];
}

/** One endpoint (find_application_endpoints() / find_application_endpoint()). Never a credential. */
function present_application_endpoint(array $e): array
{
    $str = static fn (string $k): ?string => isset($e[$k]) && $e[$k] !== '' ? (string) $e[$k] : null;
    return [
        'id' => isset($e['application_endpoint_id']) ? (int) $e['application_endpoint_id'] : null,
        'name' => (string) ($e['name'] ?? ''),
        'kind' => $str('kind'),
        'url' => $str('url'),
        'auth_kind' => (string) ($e['auth_kind'] ?? 'none'),
        'has_credential' => !empty($e['has_credential']),
        'agent_reachable' => !empty($e['agent_reachable']),
        'mcp_surface_version' => $str('mcp_surface_version'),
        'notes' => $str('notes'),
    ];
}

/** One access grant (find_application_access()). The view already scopes which grants a member sees. */
function present_application_access(array $a, int $viewerId): array
{
    $kind = ($a['member_id'] ?? null) !== null ? 'member'
        : (($a['department_id'] ?? null) !== null ? 'department' : 'residents');
    return [
        'id' => (int) $a['application_access_id'],
        'grantee_kind' => $kind,
        'grantee_name' => match ($kind) {
            'member' => (string) ($a['member_name'] ?? ('member #' . $a['member_id'])),
            'department' => (string) ($a['department_name'] ?? ('department #' . $a['department_id'])),
            default => 'Everyone at ' . (string) ($a['resident_location_name'] ?? ('location #' . $a['resident_location_id'])),
        },
        'capability' => (string) $a['capability'],
        'scope_id' => isset($a['scope_id']) ? (int) $a['scope_id'] : null,
        'scope_name' => ($a['scope_name'] ?? '') !== '' ? (string) $a['scope_name'] : null,
        // Click-around step 3 (db/151): the scope's own target, so the tab links the site or the department.
        'scope_location_id' => isset($a['scope_location_id']) ? (int) $a['scope_location_id'] : null,
        'scope_department_id' => isset($a['scope_department_id']) ? (int) $a['scope_department_id'] : null,
        'role_key' => ($a['role_key'] ?? '') !== '' ? (string) $a['role_key'] : null,
        'role_name' => ($a['role_name'] ?? '') !== '' ? (string) $a['role_name'] : null,
        // Click-around step 2: who the grant is to (id + kind), and who gave it — by name, not by the raw
        // member id it used to print (find_application_access() joins members for granted_by_name).
        'member_id' => isset($a['member_id']) ? (int) $a['member_id'] : null,
        'member_kind' => ($a['member_kind'] ?? '') !== '' ? (string) $a['member_kind'] : null,
        'department_id' => isset($a['department_id']) ? (int) $a['department_id'] : null,
        'resident_location_id' => isset($a['resident_location_id']) ? (int) $a['resident_location_id'] : null,
        'granted_by_member_id' => isset($a['granted_by']) ? (int) $a['granted_by'] : null,
        'granted_by_display' => (int) ($a['granted_by'] ?? 0) === $viewerId ? 'You'
            : (($a['granted_by_name'] ?? '') !== '' ? (string) $a['granted_by_name'] : (isset($a['granted_by']) ? 'member #' . (int) $a['granted_by'] : '—')),
        'granted_at' => isset($a['granted_at']) ? (string) $a['granted_at'] : null,
        'expires_at' => isset($a['expires_at']) ? (string) $a['expires_at'] : null,
        // db/145: every role the grant gives (application_grant_roles(), joined by the caller).
        'roles' => array_map(static fn (array $r): array => ['key' => (string) $r['role_key'], 'name' => (string) $r['role_name'],
            'withdrawn' => !empty($r['withdrawn'])], $a['roles'] ?? []),
    ];
}

/** One of an application's own roles (mcp_application_roles, db/141). */
function present_application_role(array $r): array
{
    return [
        'key' => (string) $r['role_key'],
        'name' => (string) $r['name'],
        'capability' => (string) $r['capability'],
        'is_admin' => !empty($r['is_admin']),
        'live_grant_count' => (int) ($r['live_grant_count'] ?? 0),
        // db/145: what the application says the role is for and lets its holder do.
        'description' => ($r['description'] ?? '') !== '' ? (string) $r['description'] : null,
        'rights' => array_values(array_map(static fn ($x): array => ['key' => (string) ($x['key'] ?? ''), 'description' => (string) ($x['description'] ?? '')],
            is_string($r['rights'] ?? null) ? (json_decode($r['rights'], true) ?: []) : ($r['rights'] ?? []))),
        'withdrawn' => ($r['withdrawn_at'] ?? null) !== null,
    ];
}

/** One site or department a scoped application serves (mcp_application_scopes, db/141). */
function present_application_scope(array $s): array
{
    return [
        'id' => (int) $s['scope_id'],
        'kind' => ($s['location_id'] ?? null) !== null ? 'location' : 'department',
        'location_id' => isset($s['location_id']) ? (int) $s['location_id'] : null,
        'department_id' => isset($s['department_id']) ? (int) $s['department_id'] : null,
        'name' => (string) $s['scope_name'],
        'address' => ($s['address'] ?? '') !== '' ? (string) $s['address'] : null,
        'timezone' => ($s['timezone'] ?? '') !== '' ? (string) $s['timezone'] : null,
        'live_grant_count' => (int) ($s['live_grant_count'] ?? 0),
        'added_at' => isset($s['added_at']) ? (string) $s['added_at'] : null,
    ];
}

/** One launcher card (html/launcher.php) — mirrored by web/lib/schemas/launcher.ts. Never a credential, never an endpoint. */
function present_launcher_application(array $a, array $scopes = []): array
{
    $url = trim((string) ($a['url'] ?? ''));
    return [
        'id' => (int) $a['application_id'],
        'name' => (string) $a['name'],
        'description' => ($a['description'] ?? '') !== '' ? (string) $a['description'] : null,
        'icon' => ($a['icon'] ?? '') !== '' ? (string) $a['icon'] : 'feather-grid',
        'url' => $url !== '' && preg_match('#^https?://#i', $url) ? $url : null,
        'sso' => ($a['sso_path'] ?? '') !== '' && $url !== '',
        'business_area' => ($a['business_area_name'] ?? '') !== '' ? business_area_label((string) $a['business_area_name']) : null,
        'capability' => ($a['capability'] ?? '') !== '' ? (string) $a['capability'] : null,
        'status' => (string) ($a['status'] ?? 'active'),
        // A scoped application (db/141): one link per site or department the person holds.
        'scopes' => array_map(static fn (array $s): array => [
            'id' => (int) $s['scope_id'], 'name' => (string) $s['scope_name'],
            'role' => ($s['role_name'] ?? '') !== '' ? (string) $s['role_name'] : null,
        ], $scopes),
    ];
}

/** The application's kernel token as the Overview shows it (A4): minted when, used when — never the value. */
function present_application_token(?array $t): ?array
{
    return $t === null ? null : ['minted_at' => json_ts($t['created_at'] ?? null), 'last_used_at' => json_ts($t['last_used_at'] ?? null)];
}
