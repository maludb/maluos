<?php
declare(strict_types=1);

/**
 * Nodes: a MaluOS server or inference host joined to this estate — the kernel half of Phase 13 slice 1
 * (maluos: docs/phase13-slice1-nodes.md; db/188). The contract is the node's, surface 1, the desk contract's
 * shape (db/187): a one-time code an OPERATOR mints is exchanged at POST /api/v1/estate/join for a NODE TOKEN
 * (mcp_access_tokens, scope 'node', bound to the node's location row, never a person for the MCP servers);
 * the node heartbeats presence and facts every heartbeat_s and the REPORT every report_s; the kernel applies
 * the fixed health rules to the report and keeps the estate's alerts (estate_alerts). GET /api/v1/estate/nodes
 * answers the estate to a node, and to a desk whose owner is an operator (GET /api/v1/desks/estate).
 */
require_once dirname(__DIR__, 2) . '/features/estate/desks.php';

const NODE_HEARTBEAT_S = 60;
const NODE_REPORT_S = 300;
const NODE_KINDS = ['server', 'inference'];
const NODE_REPORT_MAX_BYTES = 32 * 1024;
const NODE_REPORTS_KEPT = 24;
const NODE_CRITICAL_UNITS = ['postgresql@18-main.service', 'maluos-vault.service'];

// --------------------------------------------------------------------------
// Join
// --------------------------------------------------------------------------
/** The facts a node reports: the desk's, plus its components and public key. */
function node_facts(array $body): array
{
    $facts = desk_facts($body);
    if (is_array($body['components'] ?? null)) {
        $facts['components'] = array_values(array_filter(array_map(static fn ($c) => is_string($c) ? mb_substr(trim($c), 0, 60) : '', $body['components']), static fn ($c) => $c !== ''));
    }
    if (is_string($body['public_key'] ?? null) && preg_match('/^ssh-ed25519 [A-Za-z0-9+\/=]+( [^\s]{1,120})?$/', trim($body['public_key']))) {
        $facts['public_key'] = trim($body['public_key']);
    }
    return $facts;
}

/**
 * Make the node for the code and mint its token, in one transaction. The code's kind is the node's unless the body
 * names the other node kind, which is a code minted for another kind (the caller answers 403). A previous active
 * node with the same machine_id is retired first. @return array{node:array,token:string}
 * Throws PDOException 23505 when the name is taken.
 */
function node_join(PDO $pdo, array $code, array $body, ?string $principal): array
{
    $kind = (string) $code['kind'];
    $facts = node_facts($body);
    $name = is_string($body['name'] ?? null) && trim($body['name']) !== '' ? mb_substr(trim($body['name']), 0, 120)
        : ((string) ($code['desk_name'] ?? '') !== '' ? (string) $code['desk_name'] : ($facts['hostname'] ?? "node-" . bin2hex(random_bytes(2))));
    if (isset($facts['machine_id'])) {
        $old = $pdo->prepare("SELECT id FROM locations WHERE kind = ANY(:kinds) AND status = 'active' AND machine_id = :mid");
        $old->execute(['kinds' => '{' . implode(',', NODE_KINDS) . '}', 'mid' => $facts['machine_id']]);
        foreach ($old->fetchAll(PDO::FETCH_COLUMN) as $oldId) {
            node_retire($pdo, (int) $oldId);
            log_activity($pdo, 'node.retire', 'location', (int) $oldId, ['source' => 'node', 'after' => ['reason' => 'the same machine joined again']]);
        }
    }
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO locations
            (name, kind, is_always_on, external_ref, presence, last_seen_at, enrolled_at, enrolled_by_member_id,
             hostname, os_platform, operating_system, app_version, mcp_surface_version, cpu_cores, memory_mb, storage_gb, machine_id,
             public_key, components, platform, siting)
        VALUES
            (:name, :kind, true, :ref, 'online', now(), now(), :by,
             :hostname, :os_platform, :operating_system, :app_version, :mcp_surface_version, :cpu_cores, :memory_mb, :storage_gb, :machine_id,
             :public_key, :components, 'physical_os', 'onsite')
        RETURNING id
    SQL);
    $st->execute([
        'name' => $name, 'kind' => $kind, 'ref' => $principal !== null ? mb_substr($principal, 0, 120) : null, 'by' => (int) $code['member_id'],
        'hostname' => $facts['hostname'] ?? null, 'os_platform' => $facts['os_platform'] ?? null,
        'operating_system' => $facts['operating_system'] ?? null, 'app_version' => $facts['app_version'] ?? null,
        'mcp_surface_version' => $facts['mcp_surface_version'] ?? null, 'cpu_cores' => $facts['cpu_cores'] ?? null,
        'memory_mb' => $facts['memory_mb'] ?? null, 'storage_gb' => $facts['storage_gb'] ?? null, 'machine_id' => $facts['machine_id'] ?? null,
        'public_key' => $facts['public_key'] ?? null,
        'components' => isset($facts['components']) ? '{' . implode(',', array_map(static fn ($c) => '"' . str_replace('"', '', $c) . '"', $facts['components'])) . '}' : null,
    ]);
    $nodeId = (int) $st->fetchColumn();

    $raw = 'node_' . bin2hex(random_bytes(24));
    $st = $pdo->prepare("INSERT INTO mcp_access_tokens (member_id, label, token_hash, scope, location_id) VALUES (:m, :l, :h, 'node', :loc) RETURNING id");
    $st->execute(['m' => (int) $code['member_id'], 'l' => 'Node: ' . $name, 'h' => hash('sha256', $raw), 'loc' => $nodeId]);
    $tokenId = (int) $st->fetchColumn();
    $pdo->prepare('UPDATE locations SET enrollment_token_id = :t WHERE id = :id')->execute(['t' => $tokenId, 'id' => $nodeId]);
    $pdo->prepare('UPDATE desk_enrollment_codes SET used_at = now(), location_id = :loc WHERE id = :id')->execute(['loc' => $nodeId, 'id' => $code['id']]);
    return ['node' => node_row($pdo, $nodeId), 'token' => $raw];
}

/** The node's own row (locations, not the view). */
function node_row(PDO $pdo, int $id): array
{
    $st = $pdo->prepare("SELECT * FROM locations WHERE id = :id AND kind = ANY(:kinds)");
    $st->execute(['id' => $id, 'kinds' => '{' . implode(',', NODE_KINDS) . '}']);
    $row = $st->fetch();
    return $row === false ? [] : $row;
}

function node_revoke_tokens(PDO $pdo, int $id): void
{
    $pdo->prepare("UPDATE mcp_access_tokens SET revoked_at = now() WHERE scope = 'node' AND location_id = :id AND revoked_at IS NULL")
        ->execute(['id' => $id]);
}

/** Retire a node: status retired, offline, the token revoked, every open alert cleared. Work Locations' retire.php calls it too. */
function node_retire(PDO $pdo, int $id): void
{
    $pdo->prepare("UPDATE locations SET status = 'retired', retired_at = COALESCE(retired_at, now()), presence = 'offline', updated_at = now() WHERE id = :id")
        ->execute(['id' => $id]);
    node_revoke_tokens($pdo, $id);
    $pdo->prepare('UPDATE estate_alerts SET cleared_at = now() WHERE location_id = :id AND cleared_at IS NULL')->execute(['id' => $id]);
    overlay_free($pdo, $id);      // db/189: its overlay address into quarantine; a hub leaving unsets the hub
}

// --------------------------------------------------------------------------
// Heartbeat, the report, the health rules, the alerts
// --------------------------------------------------------------------------
function node_heartbeat(PDO $pdo, array $node, string $presence, array $body): void
{
    $id = (int) $node['id'];
    $facts = desk_facts(is_array($body['facts'] ?? null) ? $body['facts'] + $body : $body);
    unset($facts['machine_id']);
    $sets = ['presence = :presence', 'last_seen_at = now()', 'updated_at = now()'];
    $params = ['presence' => $presence, 'id' => $id];
    foreach ($facts as $col => $v) {
        $sets[] = "{$col} = :{$col}";
        $params[$col] = $v;
    }
    $report = is_array($body['report'] ?? null) ? $body['report'] : null;
    if ($report !== null) {
        $json = json_encode($report, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $sets[] = 'report = :report';
        $sets[] = 'last_report_at = now()';
        $params['report'] = $json;
        $pdo->prepare('INSERT INTO estate_node_reports (location_id, report) VALUES (:id, :r)')->execute(['id' => $id, 'r' => $json]);
    }
    $pdo->prepare('UPDATE locations SET ' . implode(', ', $sets) . ' WHERE id = :id')->execute($params);
    if ($report !== null) {
        node_evaluate($pdo, $id, $report);
    }
    node_set_presence($pdo, $id, (string) $node['name'], $presence);
}

/** Presence changes raise and clear node_offline: a clean offline (shutdown, stop) is told like a swept one. */
function node_set_presence(PDO $pdo, int $id, string $name, string $presence): void
{
    if ($presence === 'online') {
        $pdo->prepare("UPDATE estate_alerts SET cleared_at = now() WHERE location_id = :id AND kind = 'node_offline' AND cleared_at IS NULL")->execute(['id' => $id]);
    } else {
        alert_raise($pdo, $id, 'node_offline', 'presence', 'warning', "{$name} is offline", null);
    }
}

/** One open row per (node, kind, key): title and severity follow the latest report; the row's id and raised_at stay. */
function alert_raise(PDO $pdo, int $id, string $kind, string $key, string $severity, string $title, ?string $reportTs): void
{
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO estate_alerts (location_id, kind, key, severity, title, report_ts)
        VALUES (:id, :kind, :key, :sev, :title, :ts)
        ON CONFLICT (location_id, kind, key) WHERE cleared_at IS NULL
        DO UPDATE SET severity = EXCLUDED.severity, title = EXCLUDED.title, report_ts = COALESCE(EXCLUDED.report_ts, estate_alerts.report_ts)
    SQL);
    $st->execute(['id' => $id, 'kind' => $kind, 'key' => mb_substr($key, 0, 200), 'sev' => $severity, 'title' => mb_substr($title, 0, 300), 'ts' => $reportTs]);
}

/**
 * The fixed rules of the contract on a report: a unit of the fixed list down (critical for PostgreSQL and the
 * vault), an agent failed or failing, the vault not answering or its alerts, the gateway not answering, a restart
 * required, a disk over 85 % (critical over 95 %), memory under 5 %. What the report no longer shows is cleared.
 */
function node_evaluate(PDO $pdo, int $id, array $rep): void
{
    $found = [];     // "kind\tkey" => [severity, title]
    foreach (is_array($rep['units'] ?? null) ? $rep['units'] : [] as $u) {
        if (!is_array($u) || ($u['active'] ?? null) === 'active') { continue; }
        $unit = (string) ($u['unit'] ?? '?');
        $found["unit_down\t{$unit}"] = [in_array($unit, NODE_CRITICAL_UNITS, true) ? 'critical' : 'warning', "{$unit} " . (string) ($u['active'] ?? 'down')];
    }
    foreach (is_array($rep['agents'] ?? null) ? $rep['agents'] : [] as $a) {
        if (!is_array($a)) { continue; }
        $active = $a['active'] ?? null;
        $restarts = (int) ($a['restarts'] ?? 0);
        if ($active === 'failed' || ($active === 'activating' && $restarts > 0)) {
            $name = (string) ($a['name'] ?? '?');
            $found["agent_down\t{$name}"] = ['warning', "agent {$name} " . ($active === 'failed' ? 'failed' : 'failing') . " ({$restarts} restarts)"];
        }
    }
    $v = $rep['vault'] ?? null;
    if (is_array($v) && empty($v['ok'])) {
        $found["unit_down\tmaluos-vault"] = ['critical', 'maluos-vault not answering'];
    }
    foreach (is_array($v['alerts'] ?? null) ? $v['alerts'] : [] as $al) {
        if (!is_array($al)) { continue; }
        $key = (string) ($al['id'] ?? $al['title'] ?? '?');
        $found["vault_alert\t{$key}"] = ['warning', str_replace('_', ' ', (string) ($al['kind'] ?? 'alert')) . ': ' . (string) ($al['principal'] ?? '?')];
    }
    $g = $rep['gateway'] ?? null;
    if (is_array($g) && empty($g['ok'])) {
        $found["unit_down\tmaluos-gateway"] = ['warning', 'maluos-gateway not answering'];
    }
    if (!empty($rep['updates']['reboot_required'])) {
        $found["reboot_required\treboot"] = ['warning', 'a restart is required to finish updates'];
    }
    foreach (is_array($rep['disk'] ?? null) ? $rep['disk'] : [] as $d) {
        if (!is_array($d)) { continue; }
        $pct = (int) ($d['used_pct'] ?? 0);
        if ($pct > 85) {
            $mount = (string) ($d['mount'] ?? '?');
            $found["disk_full\t{$mount}"] = [$pct > 95 ? 'critical' : 'warning', "disk {$mount} at {$pct} %"];
        }
    }
    $m = $rep['memory'] ?? null;
    if (is_array($m) && !empty($m['total_mb']) && isset($m['available_mb']) && (float) $m['available_mb'] < 0.05 * (float) $m['total_mb']) {
        $found["memory_low\tmemory"] = ['critical', "memory available {$m['available_mb']} MB of {$m['total_mb']}"];
    }
    $ts = is_string($rep['ts'] ?? null) ? mb_substr($rep['ts'], 0, 40) : null;
    foreach ($found as $kk => [$sev, $title]) {
        [$kind, $key] = explode("\t", $kk, 2);
        alert_raise($pdo, $id, $kind, $key, $sev, $title, $ts);
    }
    // Clear what the report no longer shows: every open alert of a report kind whose (kind, key) was not found.
    $st = $pdo->prepare("SELECT id, kind, key FROM estate_alerts WHERE location_id = :id AND cleared_at IS NULL AND kind NOT IN ('node_offline', 'manual')");
    $st->execute(['id' => $id]);
    $clear = [];
    foreach ($st->fetchAll() as $a) {
        if (!isset($found[$a['kind'] . "\t" . $a['key']])) { $clear[] = (int) $a['id']; }
    }
    if ($clear !== []) {
        $pdo->prepare('UPDATE estate_alerts SET cleared_at = now() WHERE id = ANY(:ids)')->execute(['ids' => '{' . implode(',', $clear) . '}']);
    }
}

/** The presence sweep for nodes: silent for three heartbeats is offline, with node_offline raised; old reports trimmed. */
function node_presence_sweep(PDO $pdo): array
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE locations SET presence = 'offline', updated_at = now()
         WHERE kind = ANY(:kinds) AND status = 'active' AND presence = 'online'
           AND last_seen_at < now() - make_interval(secs => :s)
        RETURNING id, name
    SQL);
    $st->execute(['kinds' => '{' . implode(',', NODE_KINDS) . '}', 's' => 3 * NODE_HEARTBEAT_S]);
    $gone = $st->fetchAll();
    foreach ($gone as $n) {
        alert_raise($pdo, (int) $n['id'], 'node_offline', 'presence', 'warning', "{$n['name']} is offline", null);
    }
    $pdo->prepare(<<<'SQL'
        DELETE FROM estate_node_reports r USING (
            SELECT id FROM (SELECT id, row_number() OVER (PARTITION BY location_id ORDER BY ts DESC) AS n FROM estate_node_reports) x WHERE x.n > :keep
        ) old WHERE r.id = old.id
    SQL)->execute(['keep' => NODE_REPORTS_KEPT]);
    return $gone;
}

// --------------------------------------------------------------------------
// Authentication and answers
// --------------------------------------------------------------------------
/**
 * Resolve the bearer node token: 401 for anything but a live node token, 410 once the node is retired. The request
 * context becomes the operator who enrolled the node (the token's member), for RLS and the activity rows of join
 * and leave; heartbeats are not logged. @return array{token:array,node:array,member:array}
 */
function node_authenticate(): array
{
    $pdo = db();
    $raw = api_bearer_token();
    if ($raw === '') {
        api_error('unauthorized', 'A valid node token is required.', 401);
    }
    $st = $pdo->prepare("SELECT * FROM mcp_access_tokens WHERE token_hash = :h AND scope = 'node' AND (expires_at IS NULL OR expires_at > now())");
    $st->execute(['h' => hash('sha256', $raw)]);
    $token = $st->fetch();
    if ($token === false || $token['location_id'] === null) {
        error_log('node auth: token rejected (missing, wrong scope or expired)');
        api_error('unauthorized', 'A valid node token is required.', 401);
    }
    $node = node_row($pdo, (int) $token['location_id']);
    if ($node !== [] && $node['status'] !== 'active') {
        api_error('retired', 'This node was retired by the office.', 410);
    }
    $member = find_member_by_id($pdo, (int) $token['member_id']);
    if ($token['revoked_at'] !== null || $node === [] || $member === null || $member['status'] !== 'active') {
        error_log('node auth: token revoked, or it maps to no node or an inactive operator');
        api_error('unauthorized', 'A valid node token is required.', 401);
    }
    $pdo->prepare('UPDATE mcp_access_tokens SET last_used_at = now() WHERE id = :id')->execute(['id' => $token['id']]);
    $_SESSION['member_id'] = (int) $member['id'];
    $_SESSION['member_role'] = $member['role'];
    $GLOBALS['__api_token_authed'] = true;
    db_apply_context($pdo);
    return ['token' => $token, 'node' => $node, 'member' => $member];
}

function node_endpoints(bool $overlay = false): array
{
    return ['heartbeat' => app_url('/api/v1/estate/heartbeat'), 'me' => app_url('/api/v1/estate/me'),
            'leave' => app_url('/api/v1/estate/leave'), 'nodes' => app_url('/api/v1/estate/nodes'),
            'overlay' => $overlay ? app_url('/api/v1/estate/overlay') : null];
}

/** The contract's answer for join (with the token and enrolled_by added by the caller), heartbeat and me. */
function node_answer(PDO $pdo, array $node): array
{
    $overlay = overlay_block($pdo, $node);      // db/189
    return [
        'ok' => true, 'surface' => DESK_SURFACE,
        'node' => ['id' => (int) $node['id'], 'kind' => (string) $node['kind'], 'name' => (string) $node['name'], 'status' => (string) $node['status'],
                   'presence' => (string) $node['presence'], 'last_seen_at' => json_ts($node['last_seen_at'] ?? null), 'last_report_at' => json_ts($node['last_report_at'] ?? null)],
        'office' => ['name' => business_name($pdo), 'url' => app_url('/')],
        'endpoints' => node_endpoints($overlay !== null), 'heartbeat_s' => NODE_HEARTBEAT_S, 'report_s' => NODE_REPORT_S, 'overlay' => $overlay,
    ];
}

/** A node's health from its presence and open alerts: offline, critical, warning, ok. */
function node_health(array $node, array $openAlerts): string
{
    if (($node['status'] ?? '') !== 'active') { return 'retired'; }
    if (($node['presence'] ?? '') !== 'online') { return 'offline'; }
    $sev = [];
    foreach ($openAlerts as $a) {
        if ($a['kind'] !== 'node_offline') { $sev[$a['severity']] = true; }
    }
    return isset($sev['critical']) ? 'critical' : ($sev !== [] ? 'warning' : 'ok');
}

function node_summary(array $node, array $rep): string
{
    if (($node['presence'] ?? '') !== 'online') { return 'offline'; }
    $parts = [];
    $down = 0;
    foreach (is_array($rep['units'] ?? null) ? $rep['units'] : [] as $u) { if (is_array($u) && ($u['active'] ?? null) !== 'active') { $down++; } }
    $failed = 0;
    foreach (is_array($rep['agents'] ?? null) ? $rep['agents'] : [] as $a) { if (is_array($a) && ($a['active'] ?? null) === 'failed') { $failed++; } }
    if ($down) { $parts[] = "{$down} unit" . ($down !== 1 ? 's' : '') . ' down'; }
    if ($failed) { $parts[] = "{$failed} agent" . ($failed !== 1 ? 's' : '') . ' failed'; }
    $u = is_array($rep['updates'] ?? null) ? $rep['updates'] : [];
    if (!empty($u['pending_count'])) { $parts[] = "{$u['pending_count']} updates pending" . (!empty($u['security_count']) ? " ({$u['security_count']} security)" : ''); }
    if (!empty($u['reboot_required'])) { $parts[] = 'restart required'; }
    foreach (is_array($rep['disk'] ?? null) ? $rep['disk'] : [] as $d) {
        if (is_array($d) && (int) ($d['used_pct'] ?? 0) > 85) { $parts[] = "disk {$d['mount']} at {$d['used_pct']} %"; }
    }
    return $parts === [] ? 'online' : implode(' · ', $parts);
}

function present_alert(array $a): array
{
    return ['id' => (int) $a['id'], 'ts' => json_ts($a['raised_at'] ?? null), 'node_id' => (int) $a['location_id'], 'node' => (string) ($a['node_name'] ?? ''),
            'kind' => (string) $a['kind'], 'key' => (string) $a['key'], 'severity' => (string) $a['severity'], 'title' => (string) $a['title'],
            'cleared_at' => json_ts($a['cleared_at'] ?? null), 'report_ts' => $a['report_ts'] ?? null];
}

/** The nodes answer's row for a server or inference node; the full report only when $full. */
function present_node_row(array $n, array $openAlerts, bool $full = false): array
{
    $rep = is_string($n['report'] ?? null) ? (json_decode($n['report'], true) ?: []) : (is_array($n['report'] ?? null) ? $n['report'] : []);
    $units = is_array($rep['units'] ?? null) ? array_filter($rep['units'], 'is_array') : [];
    $agents = is_array($rep['agents'] ?? null) ? array_filter($rep['agents'], 'is_array') : [];
    $g = is_array($rep['gateway'] ?? null) ? $rep['gateway'] : null;
    $m = is_array($rep['memory'] ?? null) ? $rep['memory'] : [];
    $disk = is_array($rep['disk'] ?? null) ? array_filter($rep['disk'], 'is_array') : [];
    $row = [
        'id' => (int) $n['id'], 'kind' => (string) $n['kind'], 'name' => (string) $n['name'], 'hostname' => $n['hostname'] ?? null,
        'presence' => (string) $n['presence'], 'last_seen_at' => json_ts($n['last_seen_at'] ?? null), 'last_report_at' => json_ts($n['last_report_at'] ?? null),
        'health' => node_health($n, $openAlerts), 'summary' => node_summary($n, $rep),
        'units' => ['up' => count(array_filter($units, static fn ($u) => ($u['active'] ?? null) === 'active')), 'down' => count(array_filter($units, static fn ($u) => ($u['active'] ?? null) !== 'active'))],
        'agents' => ['count' => count($agents), 'running' => count(array_filter($agents, static fn ($a) => ($a['active'] ?? null) === 'active')), 'failed' => count(array_filter($agents, static fn ($a) => ($a['active'] ?? null) === 'failed'))],
        'gateway' => $g !== null ? ['ok' => !empty($g['ok']), 'backends_healthy' => count(array_filter(is_array($g['backends'] ?? null) ? $g['backends'] : [], static fn ($b) => is_array($b) && !empty($b['healthy']))),
                                   'backends' => count(is_array($g['backends'] ?? null) ? $g['backends'] : []), 'queued' => (int) ($g['queue']['queued'] ?? 0), 'running' => (int) ($g['queue']['running'] ?? 0)] : null,
        'updates' => is_array($rep['updates'] ?? null) ? ['pending_count' => $rep['updates']['pending_count'] ?? null, 'security_count' => $rep['updates']['security_count'] ?? null, 'reboot_required' => $rep['updates']['reboot_required'] ?? null] : null,
        'disk_max_pct' => $disk !== [] ? max(array_map(static fn ($d) => (int) ($d['used_pct'] ?? 0), $disk)) : null,
        'memory_available_pct' => !empty($m['total_mb']) ? (int) round(100 * (float) ($m['available_mb'] ?? 0) / (float) $m['total_mb']) : null,
        'load1' => is_array($rep['load'] ?? null) ? ($rep['load'][0] ?? null) : null,
        'facts' => ['hostname' => $n['hostname'] ?? null, 'os_release' => $n['operating_system'] ?? null, 'cpu_cores' => $n['cpu_cores'] !== null ? (int) $n['cpu_cores'] : null,
                    'memory_mb' => $n['memory_mb'] !== null ? (int) $n['memory_mb'] : null, 'storage_gb' => $n['storage_gb'] !== null ? (int) $n['storage_gb'] : null,
                    'app_version' => $n['app_version'] ?? null, 'components' => $n['components'] !== null ? array_values(array_filter(array_map(static fn ($c) => trim($c, '"'), explode(',', trim((string) $n['components'], '{}'))))) : []],
        'enrolled_at' => json_ts($n['enrolled_at'] ?? null),
        // db/189: the node's place on the overlay, or null
        'overlay' => ($n['overlay_address'] ?? null) !== null && ($n['overlay_address_freed_at'] ?? null) === null ? ['address' => (string) $n['overlay_address']] : null,
    ];
    if ($full) {
        $row['report'] = $rep !== [] ? $rep : null;
    }
    return $row;
}

function present_desk_row(array $d): array
{
    return ['id' => (int) $d['id'], 'kind' => 'desk', 'name' => (string) $d['name'], 'owner' => ['display_name' => (string) ($d['owner_name'] ?? '')],
            'presence' => (string) $d['presence'], 'last_seen_at' => json_ts($d['last_seen_at'] ?? null),
            'health' => $d['status'] !== 'active' ? 'retired' : ($d['presence'] === 'online' ? 'ok' : 'offline'), 'summary' => (string) $d['presence'],
            'facts' => ['hostname' => $d['hostname'] ?? null, 'os_release' => $d['operating_system'] ?? null, 'app_version' => $d['app_version'] ?? null],
            'overlay' => ($d['overlay_address'] ?? null) !== null && ($d['overlay_address_freed_at'] ?? null) === null ? ['address' => (string) $d['overlay_address']] : null];
}

/** Open alerts, and those cleared in the last hour, newest first; by node when $nodeId. @return array<int,array> */
function estate_alert_rows(PDO $pdo, ?int $nodeId = null, bool $openOnly = false): array
{
    $sql = "SELECT a.*, l.name AS node_name FROM estate_alerts a JOIN locations l ON l.id = a.location_id WHERE "
         . ($openOnly ? 'a.cleared_at IS NULL' : "(a.cleared_at IS NULL OR a.cleared_at >= now() - interval '1 hour')")
         . ($nodeId !== null ? ' AND a.location_id = :id' : '') . ' ORDER BY a.cleared_at NULLS FIRST, a.raised_at DESC, a.id DESC';
    $st = $pdo->prepare($sql);
    $st->execute($nodeId !== null ? ['id' => $nodeId] : []);
    return $st->fetchAll();
}

/** The nodes answer: the whole estate (nodes with health, desks, the alerts), or one node with its full report. */
function estate_nodes_answer(PDO $pdo, ?int $nodeId = null): ?array
{
    $base = ['ok' => true, 'surface' => DESK_SURFACE, 'office' => ['name' => business_name($pdo), 'url' => app_url('/')], 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z')];
    if ($nodeId !== null) {
        $n = node_row($pdo, $nodeId);
        if ($n === []) { return null; }
        $open = estate_alert_rows($pdo, $nodeId, true);
        return $base + ['node' => present_node_row($n, $open, true), 'alerts' => array_map('present_alert', $open)];
    }
    $alerts = estate_alert_rows($pdo);
    $openByNode = [];
    foreach ($alerts as $a) { if ($a['cleared_at'] === null) { $openByNode[(int) $a['location_id']][] = $a; } }
    $st = $pdo->prepare("SELECT * FROM locations WHERE kind = ANY(:kinds) AND status = 'active' ORDER BY name");
    $st->execute(['kinds' => '{' . implode(',', NODE_KINDS) . '}']);
    $nodes = array_map(static fn (array $n) => present_node_row($n, $openByNode[(int) $n['id']] ?? []), $st->fetchAll());
    $st = $pdo->query("SELECT l.*, m.display_name AS owner_name FROM locations l LEFT JOIN members m ON m.id = l.owner_member_id WHERE l.kind = 'desk' AND l.status = 'active' ORDER BY l.name");
    $desks = array_map('present_desk_row', $st->fetchAll());
    return $base + ['nodes' => array_merge($nodes, $desks), 'alerts' => array_map('present_alert', $alerts)];
}

// --------------------------------------------------------------------------
// Settings → Desks, for an operator: the estate's nodes and alerts
// --------------------------------------------------------------------------
function present_estate_for_settings(PDO $pdo): array
{
    $ans = estate_nodes_answer($pdo);
    return ['nodes' => array_values(array_filter($ans['nodes'], static fn ($n) => $n['kind'] !== 'desk')),
            'alerts' => array_values(array_filter($ans['alerts'], static fn ($a) => $a['cleared_at'] === null)),
            'overlay' => present_overlay_for_settings($pdo)];
}
