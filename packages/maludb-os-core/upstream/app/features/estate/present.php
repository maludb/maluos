<?php
declare(strict_types=1);

/**
 * Estate (Work Locations) presenters. Whitelists, mirrored by web/lib/schemas/estate.ts
 * (docs/react-migration-plan.md, "Presenters, never raw rows"). Rows come from mcp_locations,
 * mcp_location_residents, mcp_departments and mcp_applications.
 */

/** "8 cores · 16,384 MB · 200 GB" — the compact specs summary of specs.php, or null when none. */
function location_specs_summary(array $l): ?string
{
    $parts = [];
    if (!empty($l['cpu_cores'])) {
        $parts[] = (int) $l['cpu_cores'] . ' cores';
    }
    if (!empty($l['memory_mb'])) {
        $parts[] = number_format((int) $l['memory_mb']) . ' MB';
    }
    if (!empty($l['storage_gb'])) {
        $parts[] = (int) $l['storage_gb'] . ' GB';
    }
    return $parts === [] ? null : implode(' · ', $parts);
}

/**
 * The full specs panel as [label, value] rows, in the order and with the words specs.php uses.
 * NULL is a real state for ssh/root access ("Not recorded") and must not read as "No". A desk
 * shows its companion's facts only once enrolled — enrollment is phase 6, displayed, never written.
 */
function location_spec_rows(array $l): array
{
    $tri = static fn ($v): string => yes_no_unrecorded($v === null ? null : (bool) $v);
    if (($l['kind'] ?? '') === 'site') {
        return [['label' => 'Address', 'value' => (string) ($l['address'] ?? '') ?: '—'],
                ['label' => 'Time zone', 'value' => (string) ($l['timezone'] ?? '') ?: '—']];
    }
    $rows = [];
    if (($l['kind'] ?? '') !== 'building') {
        $rows[] = ['Siting', ($l['siting'] ?? null) !== null ? ucfirst((string) $l['siting']) : '—'];
    }
    $rows[] = ['Platform', location_platform_label($l['platform'] ?? null)];
    $rows[] = ['Operating system', trim((string) ($l['operating_system'] ?? '') . ' ' . (string) ($l['os_version'] ?? '')) ?: '—'];
    $rows[] = ['SSH access', $tri($l['ssh_access'] ?? null)];
    $rows[] = ['Root access', $tri($l['root_access'] ?? null)];
    $rows[] = ['Host reference', (string) ($l['external_ref'] ?? '—')];
    $rows[] = ['Hostname', (string) ($l['hostname'] ?? '—')];
    $rows[] = ['IP address', (string) ($l['ip_address'] ?? '—')];
    $rows[] = ['CPU cores', isset($l['cpu_cores']) ? (string) $l['cpu_cores'] : '—'];
    $rows[] = ['Memory', isset($l['memory_mb']) ? number_format((int) $l['memory_mb']) . ' MB' : '—'];
    $rows[] = ['Storage', isset($l['storage_gb']) ? $l['storage_gb'] . ' GB' : '—'];
    $rows[] = ['Always on', !empty($l['is_always_on']) ? 'Yes' : 'No'];
    if (($l['kind'] ?? '') === 'desk') {
        if (($l['enrolled_at'] ?? null) === null) {
            $rows[] = ['Desk companion', 'Not enrolled yet.'];
        } else {
            $rows[] = ['App version', (string) ($l['app_version'] ?? '—')];
            $rows[] = ['OS', (string) ($l['os_platform'] ?? '—')];
            $rows[] = ['MCP surface', (string) ($l['mcp_surface_version'] ?? '—')];
            $rows[] = ['Enrolled', (string) $l['enrolled_at']];
        }
    }
    return array_map(static fn (array $r): array => ['label' => $r[0], 'value' => $r[1]], $rows);
}

/** One row of the locations list (find_locations()). */
function present_location_row(array $l): array
{
    return [
        'id' => (int) $l['location_id'],
        'name' => (string) $l['name'],
        'kind' => (string) $l['kind'],
        'parent_name' => $l['parent_location_name'] ?? null,
        'parent_location_id' => ($l['parent_location_id'] ?? null) !== null ? (int) $l['parent_location_id'] : null,
        'presence' => (string) ($l['presence'] ?? 'unknown'),
        'last_seen_at' => $l['last_seen_at'] ?? null,
        'siting' => $l['siting'] ?? null,
        'owner_name' => $l['owner_name'] ?? null,
        'owner_member_id' => ($l['owner_member_id'] ?? null) !== null ? (int) $l['owner_member_id'] : null,
        'specs_summary' => location_specs_summary($l),
        'resident_count' => (int) ($l['resident_count'] ?? 0),
        'status' => (string) $l['status'],
        'address' => ($l['address'] ?? '') !== '' ? (string) $l['address'] : null,
        'timezone' => ($l['timezone'] ?? '') !== '' ? (string) $l['timezone'] : null,
        'serving_application_count' => (int) ($l['serving_application_count'] ?? 0),
    ];
}

/** A location's own page (find_location()). */
function present_location(array $l): array
{
    $int = static fn (string $k): ?int => isset($l[$k]) && $l[$k] !== '' ? (int) $l[$k] : null;
    return present_location_row($l) + [
        'parent_id' => $int('parent_location_id'),
        'description' => ($l['description'] ?? '') !== '' ? $l['description'] : null,
        'owner_member_id' => $int('owner_member_id'),
        'office_manager_member_id' => $int('office_manager_member_id'),
        'office_manager_name' => $l['office_manager_name'] ?? null,
        'allows_agents' => !empty($l['allows_agents']),
        'allows_humans' => !empty($l['allows_humans']),
        'spec_rows' => location_spec_rows($l),
    ];
}

/** A location as its form edits it. */
function present_location_form(array $l): array
{
    $int = static fn (string $k): ?int => isset($l[$k]) && $l[$k] !== '' ? (int) $l[$k] : null;
    $str = static fn (string $k): ?string => isset($l[$k]) && $l[$k] !== '' ? (string) $l[$k] : null;
    $tri = static fn (string $k): ?bool => isset($l[$k]) ? (bool) $l[$k] : null;
    return [
        'id' => $int('location_id'),
        'name' => (string) ($l['name'] ?? ''),
        'kind' => (string) ($l['kind'] ?? 'office'),
        'siting' => $str('siting'),
        'parent_location_id' => $int('parent_location_id'),
        'owner_member_id' => $int('owner_member_id'),
        'description' => $str('description'),
        'platform' => $str('platform'),
        'operating_system' => $str('operating_system'),
        'os_version' => $str('os_version'),
        'ssh_access' => $tri('ssh_access'),
        'root_access' => $tri('root_access'),
        'external_ref' => $str('external_ref'),
        'hostname' => $str('hostname'),
        'ip_address' => $str('ip_address'),
        'cpu_cores' => $int('cpu_cores'),
        'memory_mb' => $int('memory_mb'),
        'storage_gb' => $int('storage_gb'),
        'is_always_on' => !empty($l['is_always_on']),
        'address' => $str('address'),
        'timezone' => $str('timezone'),
    ];
}

/** Someone who works at a location (find_location_residents()). */
function present_location_resident(array $r): array
{
    return [
        'id' => (int) $r['member_id'],
        'name' => (string) $r['member_name'],
        'kind' => (string) $r['member_kind'],
        'is_primary' => (bool) $r['is_primary'],
        'is_office_manager' => !empty($r['is_office_manager']),
    ];
}

/** An application that runs at a location (find_location_applications()). */
function present_location_application(array $a): array
{
    return [
        'id' => (int) $a['application_id'],
        'name' => (string) $a['name'],
        'category_display' => ucwords(str_replace('_', ' ', (string) $a['category'])),
        'status' => (string) $a['status'],
    ];
}

/** {id, name} from a row keyed location_id / member_id / department_id. */
function present_named(array $row, string $idKey, string $nameKey): array
{
    return ['id' => (int) $row[$idKey], 'name' => (string) $row[$nameKey]];
}
