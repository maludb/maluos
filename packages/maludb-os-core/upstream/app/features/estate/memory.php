<?php
declare(strict_types=1);

/**
 * Federated memory, the kernel half of Phase 13 slice 4 (maluos: docs/phase13-slice4-memory.md; db/192). A member's
 * heartbeat carries its memory face's MEMORY FACTS (the departmental and enterprise scopes it holds, how much, how fresh,
 * which of them it shares, its ceiling, its port); the kernel keeps them and publishes, per member, the HOLDERS it may
 * ask for each scope (endpoints.memory) and, per holder, the PEERS allowed to ask it. The kernel never relays a query:
 * the member's own face asks the holders over the overlay with the slice 2 envelope as the credential. The office's own
 * memory (the agent-memory stage H4, app/features/memory/*) is one holder more: POST .../memory/query answers claims
 * (text, scope, sensitivity, confidence, time, source, holder), never records. The POLICY (estate_memory_policy) says who
 * may read which scope from which holder; the most specific subject wins (node > dept > kind > org), a rule naming one
 * holder beats one for any, a rule naming one scope beats one for any, a deny beats an allow; the defaults: every active
 * member reads `org`, a desk the `dept:N` scopes of its owner's departments, a server or inference node every department;
 * a desk holder never serves another desk (decision 5). Two versions tell members what changed: `version` (the holders)
 * and `peers_version` (the peers), answered as memory_changed / memory_peers_changed on heartbeats.
 */
require_once __DIR__ . '/inference.php';                                  // inference_subjects(), the sensitivity ranks
require_once dirname(__DIR__, 2) . '/features/memory/scope.php';          // memory_principal_ref()
require_once dirname(__DIR__, 2) . '/features/memory/maludb.php';         // maludb_request()
require_once dirname(__DIR__, 2) . '/features/memory/reads.php';          // memory_recall()

const MEMORY_REFRESH_S = 3600;
const MEMORY_PEERS_REFRESH_S = 300;
const MEMORY_FACTS_MAX_BYTES = 8 * 1024;
const MEMORY_DEFAULT_PORT = 11437;
const MEMORY_DEFAULT_CLASSIFICATION = 'internal';
const MEMORY_QUERY_MAX_CHARS = 1000;
const MEMORY_LIMIT_MAX = 50;
const MEMORY_LIMIT_DEFAULT = 12;
const MEMORY_SCOPES_MAX = 200;

// --------------------------------------------------------------------------
// Settings and versions
// --------------------------------------------------------------------------
function memory_settings(PDO $pdo): array
{
    $row = $pdo->query('SELECT * FROM estate_memory_settings WHERE id = 1')->fetch();
    return $row === false ? ['version' => 0, 'peers_version' => 0, 'fanout_max' => 8, 'rate_per_min' => 30] : $row;
}

/** Bump the holders' version, the peers' version, or both ('holders' | 'peers' | 'both'). */
function memory_bump(PDO $pdo, string $which = 'both'): void
{
    $sets = [];
    if ($which === 'holders' || $which === 'both') { $sets[] = 'version = version + 1'; }
    if ($which === 'peers' || $which === 'both') { $sets[] = 'peers_version = peers_version + 1'; }
    $pdo->exec('UPDATE estate_memory_settings SET ' . implode(', ', $sets) . ', updated_at = now() WHERE id = 1');
}

/** Whether the holders changed since this member last heard (a heartbeat answer's memory_changed); marks it heard. */
function memory_changed(PDO $pdo, array $loc): bool
{
    $v = (int) memory_settings($pdo)['version'];
    if ((int) ($loc['memory_seen_version'] ?? 0) === $v) { return false; }
    $pdo->prepare('UPDATE locations SET memory_seen_version = :v WHERE id = :id')->execute(['v' => $v, 'id' => $loc['id']]);
    return true;
}

/** Whether the peers changed since this member last heard (memory_peers_changed); marks it heard. */
function memory_peers_changed(PDO $pdo, array $loc): bool
{
    $v = (int) memory_settings($pdo)['peers_version'];
    if ((int) ($loc['memory_peers_seen_version'] ?? 0) === $v) { return false; }
    $pdo->prepare('UPDATE locations SET memory_peers_seen_version = :v WHERE id = :id')->execute(['v' => $v, 'id' => $loc['id']]);
    return true;
}

/** The join and enrol answers name the memory endpoints, so the member has heard the versions they were made at. */
function memory_mark_seen(PDO $pdo, int $locationId): void
{
    $pdo->prepare('UPDATE locations SET memory_seen_version = (SELECT version FROM estate_memory_settings WHERE id = 1),
                                        memory_peers_seen_version = (SELECT peers_version FROM estate_memory_settings WHERE id = 1) WHERE id = :id')->execute(['id' => $locationId]);
}

// --------------------------------------------------------------------------
// Scopes
// --------------------------------------------------------------------------
/** A shareable scope: org or dept:N. Personal scopes (agent:NAME, user:LOGIN, member:ID) never cross the estate. */
function memory_scope_shareable(mixed $scope): bool
{
    return is_string($scope) && ($scope === 'org' || preg_match('/^dept:[0-9]+$/', $scope) === 1);
}

/** The departments the office holds memory for: [{id, name}]. */
function memory_departments(PDO $pdo): array
{
    return $pdo->query('SELECT id, name FROM departments WHERE archived_at IS NULL ORDER BY id')->fetchAll();
}

// --------------------------------------------------------------------------
// The facts a member reports with its heartbeat
// --------------------------------------------------------------------------
/** Validate and store a member's memory facts. @return ?string an error message for 400, null when stored */
function memory_facts_store(PDO $pdo, array $loc, mixed $facts): ?string
{
    if (!is_array($facts)) { return 'memory is an object.'; }
    if (strlen(json_encode($facts, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) ?: '') > MEMORY_FACTS_MAX_BYTES) { return 'memory is over 8 KB.'; }
    $scopes = [];
    foreach (is_array($facts['scopes'] ?? null) ? $facts['scopes'] : [] as $s) {
        if (!is_array($s) || !memory_scope_shareable($s['scope'] ?? null)) { continue; }      // a personal scope is dropped, never stored
        $kinds = [];
        foreach (is_array($s['kinds'] ?? null) ? $s['kinds'] : [] as $k => $n) {
            if (is_string($k) && preg_match('/^[a-z][a-z0-9_]{0,30}$/', $k) && is_numeric($n)) { $kinds[$k] = max(0, (int) $n); }
        }
        $scopes[$s['scope']] = ['scope' => $s['scope'], 'count' => is_numeric($s['count'] ?? null) ? max(0, (int) $s['count']) : 0,
                                'updated_at' => is_string($s['updated_at'] ?? null) && strtotime($s['updated_at']) !== false ? gmdate('Y-m-d\TH:i:s\Z', strtotime($s['updated_at'])) : null,
                                'kinds' => $kinds ?: new stdClass()];
        if (count($scopes) >= MEMORY_SCOPES_MAX) { break; }
    }
    $shared = [];
    foreach (is_array($facts['shared'] ?? null) ? $facts['shared'] : [] as $s) {
        if (memory_scope_shareable($s)) { $shared[$s] = true; }
    }
    $shared = array_keys($shared);
    sort($shared);
    $maxc = is_string($facts['max_classification'] ?? null) && isset(INFERENCE_SENSITIVITY[$facts['max_classification']]) ? $facts['max_classification'] : MEMORY_DEFAULT_CLASSIFICATION;
    $port = is_numeric($facts['port'] ?? null) && (int) $facts['port'] >= 1 && (int) $facts['port'] <= 65535 ? (int) $facts['port'] : MEMORY_DEFAULT_PORT;
    $api = is_numeric($facts['api_version'] ?? null) ? (int) $facts['api_version'] : 1;
    $held = array_keys($scopes);
    sort($held);
    $sig = hash('sha256', json_encode([$held, $shared, $maxc, $port, $api]) ?: '');
    $cur = $pdo->prepare('SELECT signature FROM estate_memory WHERE location_id = :id');
    $cur->execute(['id' => $loc['id']]);
    $old = $cur->fetchColumn();
    $pdo->prepare(<<<'SQL'
        INSERT INTO estate_memory (location_id, scopes, shared, max_classification, port, api_version, signature, updated_at)
        VALUES (:id, :scopes, :shared, :maxc, :port, :api, :sig, now())
        ON CONFLICT (location_id) DO UPDATE SET scopes = EXCLUDED.scopes, shared = EXCLUDED.shared, max_classification = EXCLUDED.max_classification,
            port = EXCLUDED.port, api_version = EXCLUDED.api_version, signature = EXCLUDED.signature, updated_at = now()
    SQL)->execute(['id' => $loc['id'], 'scopes' => json_encode(array_values($scopes)), 'shared' => json_encode($shared), 'maxc' => $maxc, 'port' => $port, 'api' => $api, 'sig' => $sig]);
    if ($old !== $sig) {
        memory_bump($pdo, 'holders');      // a scope appeared or went, the shared list, the ceiling or the port moved; the counts alone never bump
    }
    return null;
}

/** A member's facts leave with it (retirement, leave). */
function memory_facts_forget(PDO $pdo, int $locationId): void
{
    $st = $pdo->prepare('DELETE FROM estate_memory WHERE location_id = :id');
    $st->execute(['id' => $locationId]);
    if ($st->rowCount() > 0) { memory_bump($pdo, 'holders'); }
}

/** A member leaves the estate: its facts, and the holders and peers everyone else sees. */
function memory_member_retire(PDO $pdo, int $locationId): void
{
    memory_facts_forget($pdo, $locationId);
    memory_bump($pdo, 'both');
}

// --------------------------------------------------------------------------
// The policy
// --------------------------------------------------------------------------
/** The rules, read once per request. */
function memory_rules(PDO $pdo, bool $reload = false): array
{
    static $rules = null;
    if ($rules === null || $reload) { $rules = $pdo->query('SELECT * FROM estate_memory_policy ORDER BY id')->fetchAll(); }
    return $rules;
}

/** The default: org for everyone; dept:N for a server or inference node, or for a desk whose owner is in the department. */
function memory_default_allow(array $caller, array $subjects, string $scope): bool
{
    if ($scope === 'org') { return true; }
    if (!memory_scope_shareable($scope)) { return false; }
    if (in_array($caller['kind'] ?? '', ['server', 'inference'], true)) { return true; }
    return isset($subjects[$scope]);      // a desk: inference_subjects() lists its owner's departments as dept:N
}

/**
 * What the policy says about $caller reading $scope from $holder (location rows; the office is ['id' => 0, 'kind' =>
 * 'coordinator']): allow, max_classification, replicate, priority, and which rule decided (null = the default allowed,
 * 'default' = the default refused, 'desk_to_desk', or a rule id).
 */
function memory_rule(PDO $pdo, array $caller, array $holder, string $scope): array
{
    if (($holder['kind'] ?? '') === 'desk' && ($caller['kind'] ?? '') === 'desk') {
        return ['allow' => false, 'max_classification' => null, 'replicate' => false, 'priority' => 0, 'rule' => 'desk_to_desk'];
    }
    $subjects = inference_subjects($pdo, $caller);
    $default = memory_default_allow($caller, $subjects, $scope);
    $out = ['allow' => $default, 'max_classification' => MEMORY_DEFAULT_CLASSIFICATION, 'replicate' => false, 'priority' => 0, 'rule' => $default ? null : 'default'];
    $best = null;
    $bestKey = null;
    foreach (memory_rules($pdo) as $r) {
        if (!isset($subjects[$r['subject']])) { continue; }
        if ($r['holder_location_id'] !== null && (int) $r['holder_location_id'] !== (int) ($holder['id'] ?? 0)) { continue; }
        if ($r['scope'] !== '*' && $r['scope'] !== $scope) { continue; }
        $key = [$subjects[$r['subject']], $r['holder_location_id'] !== null ? 1 : 0, $r['scope'] !== '*' ? 1 : 0, !empty($r['allow']) ? 0 : 1];
        if ($best === null || $key > $bestKey) { $best = $r; $bestKey = $key; }
    }
    if ($best === null) { return $out; }
    return ['allow' => !empty($best['allow']), 'max_classification' => $best['max_classification'] ?? MEMORY_DEFAULT_CLASSIFICATION,
            'replicate' => !empty($best['replicate']), 'priority' => (int) $best['priority'], 'rule' => (int) $best['id']];
}

function memory_rule_add(PDO $pdo, array $f, int $memberId): array
{
    $subject = trim((string) ($f['subject'] ?? 'org'));
    if (!($subject === 'org' || preg_match('/^(dept:[0-9]+|kind:(desk|server|inference)|node:[0-9]+)$/', $subject))) {
        throw new InvalidArgumentException('subject is org, dept:N, kind:desk|server|inference or node:ID');
    }
    $scope = trim((string) ($f['scope'] ?? '*'));
    if ($scope === '') { $scope = '*'; }
    if ($scope !== '*' && !memory_scope_shareable($scope)) { throw new InvalidArgumentException('scope is org, dept:N or * (any)'); }
    $holder = isset($f['holder_location_id']) && $f['holder_location_id'] !== '' && $f['holder_location_id'] !== null ? (int) $f['holder_location_id'] : null;
    $maxCls = isset($f['max_classification']) && $f['max_classification'] !== '' ? (string) $f['max_classification'] : null;
    if ($maxCls !== null && !isset(INFERENCE_SENSITIVITY[$maxCls])) { throw new InvalidArgumentException('max_classification is public, internal, restricted or prohibited'); }
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO estate_memory_policy (subject, scope, holder_location_id, allow, max_classification, replicate, priority, note, created_by_member_id)
        VALUES (:subject, :scope, :holder, :allow, :max_cls, :replicate, :priority, :note, :by) RETURNING *
    SQL);
    $st->execute(['subject' => $subject, 'scope' => $scope, 'holder' => $holder, 'allow' => !isset($f['allow']) || filter_var($f['allow'], FILTER_VALIDATE_BOOL) ? 't' : 'f',
                  'max_cls' => $maxCls, 'replicate' => isset($f['replicate']) && filter_var($f['replicate'], FILTER_VALIDATE_BOOL) ? 't' : 'f', 'priority' => (int) ($f['priority'] ?? 0),
                  'note' => isset($f['note']) && trim((string) $f['note']) !== '' ? mb_substr(trim((string) $f['note']), 0, 300) : null, 'by' => $memberId]);
    $row = $st->fetch();
    memory_rules($pdo, true);
    memory_bump($pdo, 'both');
    return $row;
}

function memory_rule_delete(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare('DELETE FROM estate_memory_policy WHERE id = :id');
    $st->execute(['id' => $id]);
    memory_rules($pdo, true);
    if ($st->rowCount() > 0) { memory_bump($pdo, 'both'); return true; }
    return false;
}

// --------------------------------------------------------------------------
// The holders: what the estate publishes to a member
// --------------------------------------------------------------------------
/** Every member with facts, joined to its row. */
function memory_holder_rows(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT l.id, l.kind, l.name, l.owner_member_id, l.presence, host(l.overlay_address) AS address, l.overlay_address_freed_at, l.machine_id,
               m.scopes, m.shared, m.max_classification, m.port, m.api_version, m.updated_at,
               (SELECT n.name FROM locations n WHERE n.kind <> 'desk' AND n.status = 'active' AND n.machine_id IS NOT NULL
                   AND n.machine_id = l.machine_id AND n.id <> l.id ORDER BY n.id LIMIT 1) AS node_of_host
          FROM estate_memory m JOIN locations l ON l.id = m.location_id
         WHERE l.status = 'active'
         ORDER BY l.name
    SQL)->fetchAll();
}

/** db/193 (slice 4b, decision 9): a desk whose machine id is an active node's is that node's host; its face is one and is
 *  published as the node (the office allocated the desk an overlay address the host never carries: its interface is the node's). */
function memory_holder_is_other_membership(array $h): bool
{
    return ($h['kind'] ?? '') === 'desk' && ($h['node_of_host'] ?? null) !== null;
}

function memory_holder_published(array $h): bool
{
    return ($h['address'] ?? null) !== null && ($h['overlay_address_freed_at'] ?? null) === null && ($h['presence'] ?? '') === 'online' && inference_json($h['shared'], []) !== []
        && !memory_holder_is_other_membership($h);
}

/** The scopes a holder holds, keyed by name. */
function memory_holder_scopes(array $h): array
{
    $out = [];
    foreach (inference_json($h['scopes'], []) as $s) { if (is_array($s) && isset($s['scope'])) { $out[$s['scope']] = $s; } }
    return $out;
}

function present_memory_holder(PDO $pdo, array $h, array $scopes): array
{
    return ['node' => $h['kind'] . ':' . (int) $h['id'], 'id' => (int) $h['id'], 'kind' => (string) $h['kind'],
            'name' => overlay_member_name($pdo, (int) $h['id']) ?? overlay_label((string) $h['name']), 'display_name' => (string) $h['name'],
            'address' => $h['address'], 'port' => (int) $h['port'], 'api_version' => (int) $h['api_version'], 'max_classification' => (string) $h['max_classification'],
            'scopes' => $scopes, 'updated_at' => json_ts($h['updated_at'] ?? null)];
}

/** The scopes the office itself holds that $caller may read: org and the departments, as the policy allows; self for a desk. */
function memory_office_scopes(PDO $pdo, array $caller): array
{
    $office = ['id' => 0, 'kind' => 'coordinator'];
    $out = [];
    if (($caller['kind'] ?? '') === 'desk') { $out[] = ['scope' => 'self', 'classification_max' => 'restricted', 'label' => 'you']; }
    $r = memory_rule($pdo, $caller, $office, 'org');
    if ($r['allow']) { $out[] = ['scope' => 'org', 'classification_max' => $r['max_classification'] ?? MEMORY_DEFAULT_CLASSIFICATION, 'label' => 'the organisation']; }
    foreach (memory_departments($pdo) as $d) {
        $scope = 'dept:' . (int) $d['id'];
        $r = memory_rule($pdo, $caller, $office, $scope);
        if ($r['allow']) { $out[] = ['scope' => $scope, 'classification_max' => $r['max_classification'] ?? MEMORY_DEFAULT_CLASSIFICATION, 'label' => (string) $d['name']]; }
    }
    return $out;
}

/** GET endpoints.memory for a member: the holders it may ask, scope by scope, never itself. With $everything (an operator's desk,
 *  ?all=1): every published holder with every shared scope, each scope with `allowed` for this member. */
function memory_holders_answer(PDO $pdo, array $loc, bool $everything = false): array
{
    $s = memory_settings($pdo);
    $out = [];
    foreach (memory_holder_rows($pdo) as $h) {
        if ((int) $h['id'] === (int) $loc['id'] || !memory_holder_published($h)) { continue; }
        $held = memory_holder_scopes($h);
        $scopes = [];
        foreach (inference_json($h['shared'], []) as $scope) {
            if (!is_string($scope)) { continue; }
            $rule = memory_rule($pdo, $loc, $h, $scope);
            if (!$rule['allow'] && !$everything) { continue; }
            $row = ['scope' => $scope, 'count' => (int) ($held[$scope]['count'] ?? 0), 'updated_at' => $held[$scope]['updated_at'] ?? null,
                    'kinds' => $held[$scope]['kinds'] ?? new stdClass(), 'classification_max' => $rule['max_classification'] ?? MEMORY_DEFAULT_CLASSIFICATION,
                    'replicate' => $rule['replicate'], 'priority' => $rule['priority']];
            if ($everything) { $row['allowed'] = $rule['allow']; }
            $scopes[] = $row;
        }
        if ($scopes === []) { continue; }
        $out[] = present_memory_holder($pdo, $h, $scopes);
    }
    $pdo->prepare('UPDATE locations SET memory_seen_version = :v WHERE id = :id')->execute(['v' => (int) $s['version'], 'id' => $loc['id']]);
    $query = ($loc['kind'] ?? '') === 'desk' ? app_url('/api/v1/desks/memory/query') : app_url('/api/v1/estate/memory/query');
    return ['ok' => true, 'surface' => DESK_SURFACE, 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z'), 'self' => $loc['kind'] . ':' . (int) $loc['id'],
            'holders' => $out, 'office' => ['query' => $query, 'scopes' => memory_office_scopes($pdo, $loc)],
            'fanout_max' => (int) $s['fanout_max'], 'rate_per_min' => (int) $s['rate_per_min'], 'refresh_s' => MEMORY_REFRESH_S, 'version' => (int) $s['version']];
}

// --------------------------------------------------------------------------
// The peers: who may ask a holder
// --------------------------------------------------------------------------
function memory_peers_answer(PDO $pdo, array $host): array
{
    $s = memory_settings($pdo);
    $facts = $pdo->prepare('SELECT shared FROM estate_memory WHERE location_id = :id');
    $facts->execute(['id' => $host['id']]);
    $shared = inference_json($facts->fetchColumn() ?: '[]', []);
    $peers = [];
    if ($shared !== []) {
        $st = $pdo->query("SELECT * FROM locations WHERE status = 'active' AND kind IN ('desk', 'server', 'inference') ORDER BY name");
        foreach ($st->fetchAll() as $m) {
            if ((int) $m['id'] === (int) $host['id']) { continue; }
            $scopes = [];
            foreach ($shared as $scope) {
                if (!is_string($scope)) { continue; }
                $rule = memory_rule($pdo, $m, $host, $scope);
                if (!$rule['allow']) { continue; }
                $scopes[] = ['scope' => $scope, 'classification_max' => $rule['max_classification'] ?? MEMORY_DEFAULT_CLASSIFICATION, 'replicate' => $rule['replicate'], 'priority' => $rule['priority']];
            }
            if ($scopes === []) { continue; }
            $peers[] = ['node' => $m['kind'] . ':' . (int) $m['id'], 'id' => (int) $m['id'], 'kind' => (string) $m['kind'],
                        'name' => overlay_member_name($pdo, (int) $m['id']) ?? overlay_label((string) $m['name']), 'display_name' => (string) $m['name'],
                        'address' => ($m['overlay_address'] ?? null) !== null && ($m['overlay_address_freed_at'] ?? null) === null ? (string) $m['overlay_address'] : null,
                        'public_key' => is_string($m['public_key'] ?? null) && $m['public_key'] !== '' ? $m['public_key'] : null,      // the peer's signing key (db/190), so a holder verifies its envelopes from this answer alone
                        'scopes' => $scopes];
        }
    }
    $pdo->prepare('UPDATE locations SET memory_peers_seen_version = :v WHERE id = :id')->execute(['v' => (int) $s['peers_version'], 'id' => $host['id']]);
    return ['ok' => true, 'surface' => DESK_SURFACE, 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z'), 'self' => $host['kind'] . ':' . (int) $host['id'],
            'shared' => $shared, 'peers' => $peers, 'keys' => app_url('/api/v1/estate/keys'), 'refresh_s' => MEMORY_PEERS_REFRESH_S, 'version' => (int) $s['peers_version']];
}

// --------------------------------------------------------------------------
// The office as a holder: POST .../memory/query
// --------------------------------------------------------------------------
/** The scopes an envelope's authority delegates: scope → level ('dept:3:read' → dept:3 read; 'org' → org read). */
function memory_authority_scopes(array $env): array
{
    $out = [];
    foreach (is_array($env['authority']['scopes'] ?? null) ? $env['authority']['scopes'] : [] as $s) {
        if (!is_string($s)) { continue; }
        if (preg_match('/^(.+):(read|write)$/', $s, $m)) { $out[$m[1]] = $m[2]; } else { $out[$s] = 'read'; }
    }
    return $out;
}

/** Validate a query body. @return array{0: ?array, 1: ?string} [the parsed query, an error message] */
function memory_query_parse(array $body, bool $isDesk): array
{
    $scopes = [];
    foreach (is_array($body['scopes'] ?? null) ? $body['scopes'] : [] as $s) {
        if ($s === 'self' && $isDesk) { $scopes['self'] = true; continue; }
        if (!memory_scope_shareable($s)) { return [null, 'scopes are org, dept:N' . ($isDesk ? ' or self' : '') . '.']; }
        $scopes[$s] = true;
    }
    $scopes = array_keys($scopes);
    if ($scopes === []) { return [null, 'scopes is a non-empty list.']; }
    if (count($scopes) > 32) { return [null, 'at most 32 scopes.']; }
    $query = is_string($body['query'] ?? null) ? trim($body['query']) : '';
    if ($query === '' || mb_strlen($query) > MEMORY_QUERY_MAX_CHARS) { return [null, 'query is 1 to ' . MEMORY_QUERY_MAX_CHARS . ' characters.']; }
    $cls = $body['classification'] ?? MEMORY_DEFAULT_CLASSIFICATION;
    if (!is_string($cls) || !isset(INFERENCE_SENSITIVITY[$cls])) { return [null, 'classification is public, internal, restricted or prohibited.']; }
    $limit = is_numeric($body['limit'] ?? null) ? max(1, min(MEMORY_LIMIT_MAX, (int) $body['limit'])) : MEMORY_LIMIT_DEFAULT;
    return [['scopes' => $scopes, 'query' => $query, 'classification' => $cls, 'limit' => $limit], null];
}

/** How many queries this member had answered in the last minute (the office's rate). */
function memory_rate_count(PDO $pdo, int $locationId): int
{
    $st = $pdo->prepare("SELECT count(*) FROM activity_log WHERE action = 'memory.query' AND entity_type = 'locations' AND entity_id = :id AND created_at > now() - interval '1 minute'");
    $st->execute(['id' => $locationId]);
    return (int) $st->fetchColumn();
}

/** One of MaluDB's recall results as a claim (decision 6): the text and where it came from, never the record. */
function present_memory_claim(array $r, array $namespaceToScope, int $rank): array
{
    $ns = (string) ($r['namespace'] ?? '');
    return ['text' => (string) ($r['source_text'] ?? $r['text'] ?? ''), 'scope' => $namespaceToScope[$ns] ?? $ns, 'kind' => 'memory',
            'sensitivity' => is_string($r['sensitivity'] ?? null) ? $r['sensitivity'] : MEMORY_DEFAULT_CLASSIFICATION,
            'confidence' => is_numeric($r['confidence'] ?? null) ? round((float) $r['confidence'], 3) : null,
            'observed_at' => json_ts($r['occurred_at'] ?? null), 'recorded_at' => json_ts($r['recorded_at'] ?? $r['created_at'] ?? null),
            'source' => ['node' => 'coordinator', 'object' => 'memory', 'id' => $r['document_id'] ?? $r['memory_id'] ?? $r['id'] ?? null,
                         'ref' => ($r['subject_name'] ?? '') !== '' ? (string) $r['subject_name'] : null],
            'writer' => is_string($r['principal_ref'] ?? null) ? $r['principal_ref'] : null, 'holder' => 'coordinator', 'rank' => $rank];
}

/**
 * The office answers a member's query from its own memory. $ctx is the authenticated context (desk or node); for a node
 * the body carries the envelope. $recall overrides MaluDB for the proof: fn(array $namespaces, string $query, int $limit)
 * → [?array answer, ?string error]. @return array{0: int, 1: array} [HTTP status, the body or {error, message}]
 */
function memory_office_query(PDO $pdo, array $ctx, array $body, ?callable $recall = null): array
{
    $loc = $ctx['node'] ?? $ctx['desk'];
    $isDesk = ($loc['kind'] ?? '') === 'desk';
    $fail = static fn (int $status, string $code, string $msg) => [$status, ['error' => $code, 'message' => $msg]];
    [$q, $err] = memory_query_parse($body, $isDesk);
    if ($q === null) { return $fail(400, 'invalid', $err); }
    $envelope = null;
    $authority = null;
    if (!$isDesk) {
        if (!is_array($body['envelope'] ?? null)) { return $fail(401, 'bad_envelope', 'A node\'s query carries an envelope.'); }
        $v = envelope_verify($pdo, $body['envelope'], node_ref($loc));
        if (!$v['ok']) { return $fail($v['reason'] === 'replay' ? 409 : 401, $v['reason'], $v['message']); }
        $envelope = $body['envelope'];
        $authority = memory_authority_scopes($envelope);
        foreach ($q['scopes'] as $scope) {
            if (!isset($authority[$scope])) { return $fail(403, 'forbidden', "The envelope's authority does not cover $scope."); }
        }
        $ecls = (string) ($envelope['authority']['classification'] ?? MEMORY_DEFAULT_CLASSIFICATION);
        if (INFERENCE_SENSITIVITY[$q['classification']] > (INFERENCE_SENSITIVITY[$ecls] ?? 1)) { return $fail(403, 'classification', "The envelope's classification is $ecls."); }
    }
    $s = memory_settings($pdo);
    if (memory_rate_count($pdo, (int) $loc['id']) >= (int) $s['rate_per_min']) { return $fail(429, 'rate', 'At most ' . (int) $s['rate_per_min'] . ' queries a minute.'); }
    $office = ['id' => 0, 'kind' => 'coordinator'];
    $namespaces = [];
    $nsToScope = [];
    foreach ($q['scopes'] as $scope) {
        if ($scope === 'self') {
            $ns = memory_principal_ref((int) $ctx['member']['id'], 'human');
            $namespaces[] = $ns; $nsToScope[$ns] = 'self';
            continue;
        }
        $rule = memory_rule($pdo, $loc, $office, $scope);
        if (!$rule['allow']) { return $fail(403, 'forbidden', "This member may not read $scope at the office."); }
        if (INFERENCE_SENSITIVITY[$q['classification']] > INFERENCE_SENSITIVITY[$rule['max_classification'] ?? MEMORY_DEFAULT_CLASSIFICATION]) {
            return $fail(403, 'classification', "The ceiling on $scope is " . ($rule['max_classification'] ?? MEMORY_DEFAULT_CLASSIFICATION) . '.');
        }
        if ($scope !== 'org' && !in_array((int) substr($scope, 5), array_map(static fn ($d) => (int) $d['id'], memory_departments($pdo)), true)) {
            return $fail(403, 'forbidden', "No such department: $scope.");
        }
        $namespaces[] = $scope; $nsToScope[$scope] = $scope;
    }
    $recall ??= static fn (array $ns, string $query, int $limit) => memory_recall(array_map(static fn ($n) => ['namespace' => $n], $ns), $query, null, $limit);
    [$ans, $err] = $recall($namespaces, $q['query'], $q['limit']);
    $logged = ['scopes' => $q['scopes'], 'classification' => $q['classification'], 'envelope_id' => $envelope['id'] ?? null,
               'task_id' => is_array($envelope['chain'] ?? null) ? (end($envelope['chain'])['task_id'] ?? null) : null, 'originator' => $envelope['originator']['principal'] ?? null];
    if ($ans === null) {
        log_activity($pdo, 'memory.query', 'locations', (int) $loc['id'], ['after' => $logged + ['count' => 0, 'error' => 'memory_unavailable']]);
        return $fail(503, 'memory_unavailable', 'The office\'s memory could not be asked: ' . (string) $err);
    }
    $claims = [];
    $i = 0;
    foreach (is_array($ans['results'] ?? null) ? $ans['results'] : [] as $r) {
        if (!is_array($r)) { continue; }
        $claims[] = present_memory_claim($r, $nsToScope, ++$i);
        if ($i >= $q['limit']) { break; }
    }
    $read = array_values(array_unique(array_map(static fn ($c) => $c['scope'], $claims)));
    log_activity($pdo, 'memory.query', 'locations', (int) $loc['id'], ['after' => $logged + ['count' => count($claims), 'scopes_read' => $read]]);
    return [200, ['ok' => true, 'surface' => DESK_SURFACE, 'self' => $loc['kind'] . ':' . (int) $loc['id'], 'holder' => 'coordinator', 'claims' => $claims,
                  'scopes_read' => $read, 'scopes_asked' => $q['scopes'], 'truncated' => count($claims) >= $q['limit'], 'count' => count($claims)]];
}

// --------------------------------------------------------------------------
// Settings → Desks, for an operator
// --------------------------------------------------------------------------
function present_memory_rule(array $r): array
{
    return ['id' => (int) $r['id'], 'subject' => (string) $r['subject'], 'scope' => (string) $r['scope'],
            'holder_location_id' => $r['holder_location_id'] !== null ? (int) $r['holder_location_id'] : null, 'holder_name' => $r['holder_name'] ?? null,
            'allow' => !empty($r['allow']), 'max_classification' => $r['max_classification'], 'replicate' => !empty($r['replicate']),
            'priority' => (int) $r['priority'], 'note' => $r['note'], 'created_at' => json_ts($r['created_at'] ?? null)];
}

function present_memory_for_settings(PDO $pdo): array
{
    $s = memory_settings($pdo);
    $holders = [];
    $scopeCount = 0;
    foreach (memory_holder_rows($pdo) as $h) {
        $held = memory_holder_scopes($h);
        $shared = inference_json($h['shared'], []);
        $scopes = [];
        foreach ($held as $name => $sc) {
            $scopes[] = ['scope' => (string) $name, 'count' => (int) ($sc['count'] ?? 0), 'updated_at' => $sc['updated_at'] ?? null, 'shared' => in_array($name, $shared, true)];
        }
        $row = present_memory_holder($pdo, $h, $scopes);
        $row['shared'] = array_values(array_filter($shared, 'is_string'));
        $row['presence'] = (string) $h['presence'];
        $row['published'] = memory_holder_published($h);
        $row['why'] = $row['published'] ? null : ($shared === [] ? 'shares nothing' : (memory_holder_is_other_membership($h) ? 'the node ' . $h['node_of_host'] . ' of the same host' : ($h['address'] === null || $h['overlay_address_freed_at'] !== null ? 'no overlay address' : 'offline')));
        if ($row['published']) { $scopeCount += count($row['shared']); }
        $holders[] = $row;
    }
    $rules = array_map('present_memory_rule', $pdo->query('SELECT p.*, l.name AS holder_name FROM estate_memory_policy p LEFT JOIN locations l ON l.id = p.holder_location_id ORDER BY p.id')->fetchAll());
    $office = [['scope' => 'org', 'label' => 'the organisation']];
    foreach (memory_departments($pdo) as $d) { $office[] = ['scope' => 'dept:' . (int) $d['id'], 'label' => (string) $d['name']]; }
    $queries = (int) $pdo->query("SELECT count(*) FROM activity_log WHERE action = 'memory.query' AND created_at > now() - interval '1 day'")->fetchColumn();
    return ['holders' => $holders, 'rules' => $rules, 'office' => $office, 'version' => (int) $s['version'], 'peers_version' => (int) $s['peers_version'],
            'fanout_max' => (int) $s['fanout_max'], 'rate_per_min' => (int) $s['rate_per_min'],
            'counts' => ['holders' => count(array_filter($holders, static fn ($h) => $h['published'])), 'scopes' => $scopeCount, 'queries_24h' => $queries]];
}
