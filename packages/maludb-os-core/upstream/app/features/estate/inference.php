<?php
declare(strict_types=1);

/**
 * Shared inference across the estate, the kernel half of Phase 13 slice 3 (maluos: docs/phase13-slice3-inference.md;
 * db/191). A member's heartbeat carries its gateway's INFERENCE FACTS; the kernel keeps them and publishes, per
 * member, the BACKENDS it may use (endpoints.inference: name, overlay address, port, models, expected wait, the
 * ceilings the policy gives it) and, per serving host, the PEERS allowed to call it (each with the SHA-256 of its
 * inference key and its ceilings). The kernel never routes a call: the member's own gateway makes a rung per backend.
 * The INFERENCE KEY is a bearer secret minted at join or enrol (shown once, only its hash kept); a serving host checks
 * a presented key against the peers answer, so no key crosses the estate by hand. The POLICY (estate_inference_policy)
 * says who may use what; the most specific subject wins (node > dept > kind > org), a backend-specific rule beats a
 * general one at the same depth, a deny beats an allow; a desk's contribution is never used by other desks (decision 4).
 * Two versions tell members what changed: `version` (the backends) and `peers_version` (the peers), answered as
 * inference_changed / peers_changed on heartbeats. With the `scheduler` entitlement the kernel answers PLACEMENT.
 */
require_once dirname(__DIR__, 2) . '/features/estate/overlay.php';

const INFERENCE_REFRESH_S = 3600;
const INFERENCE_FACTS_MAX_BYTES = 8 * 1024;
const INFERENCE_CLASSES = ['interactive' => 0, 'agent' => 1, 'batch' => 2];        // the gateway's seeded classes, by priority
const INFERENCE_SENSITIVITY = ['public' => 0, 'internal' => 1, 'restricted' => 2, 'prohibited' => 3];
const INFERENCE_DEFAULT_CLASSIFICATION = 'internal';

// --------------------------------------------------------------------------
// Settings, versions, the entitlement
// --------------------------------------------------------------------------
function inference_settings(PDO $pdo): array
{
    $row = $pdo->query('SELECT * FROM estate_inference_settings WHERE id = 1')->fetch();
    return $row === false ? ['version' => 0, 'peers_version' => 0, 'scheduler' => false, 'lease_s' => 30] : $row;
}

/** Bump the backends' version, the peers' version, or both ('backends' | 'peers' | 'both'). */
function inference_bump(PDO $pdo, string $which = 'both'): void
{
    $sets = [];
    if ($which === 'backends' || $which === 'both') { $sets[] = 'version = version + 1'; }
    if ($which === 'peers' || $which === 'both') { $sets[] = 'peers_version = peers_version + 1'; }
    $pdo->exec('UPDATE estate_inference_settings SET ' . implode(', ', $sets) . ', updated_at = now() WHERE id = 1');
}

function inference_editions(PDO $pdo): array
{
    return !empty(inference_settings($pdo)['scheduler']) ? ['scheduler'] : [];
}

/** A super-admin flips the entitlement until Phase 9's contracts service sets it. */
function inference_set_scheduler(PDO $pdo, bool $on): void
{
    $pdo->prepare('UPDATE estate_inference_settings SET scheduler = :s, updated_at = now() WHERE id = 1')->execute(['s' => $on ? 't' : 'f']);
    inference_bump($pdo, 'backends');
}

/** Whether the backends changed since this member last heard (a heartbeat answer's inference_changed); marks it heard. */
function inference_changed(PDO $pdo, array $loc): bool
{
    $v = (int) inference_settings($pdo)['version'];
    if ((int) ($loc['inference_seen_version'] ?? 0) === $v) { return false; }
    $pdo->prepare('UPDATE locations SET inference_seen_version = :v WHERE id = :id')->execute(['v' => $v, 'id' => $loc['id']]);
    return true;
}

/** Whether the peers changed since this member last heard (peers_changed); marks it heard. */
function peers_changed(PDO $pdo, array $loc): bool
{
    $v = (int) inference_settings($pdo)['peers_version'];
    if ((int) ($loc['peers_seen_version'] ?? 0) === $v) { return false; }
    $pdo->prepare('UPDATE locations SET peers_seen_version = :v WHERE id = :id')->execute(['v' => $v, 'id' => $loc['id']]);
    return true;
}

/** The join and enrol answers carry the backends and the editions, so the member has heard the version they were made at. */
function inference_mark_seen(PDO $pdo, int $locationId): void
{
    $pdo->prepare('UPDATE locations SET inference_seen_version = (SELECT version FROM estate_inference_settings WHERE id = 1),
                                        peers_seen_version = (SELECT peers_version FROM estate_inference_settings WHERE id = 1) WHERE id = :id')->execute(['id' => $locationId]);
}

// --------------------------------------------------------------------------
// The inference key: minted at join or enrol (and on request), its hash on the location row
// --------------------------------------------------------------------------
function inference_key_mint(PDO $pdo, int $locationId): string
{
    $raw = 'inf_' . bin2hex(random_bytes(24));
    $pdo->prepare('UPDATE locations SET inference_key_hash = :h, updated_at = now() WHERE id = :id')->execute(['h' => hash('sha256', $raw), 'id' => $locationId]);
    inference_bump($pdo, 'peers');
    return $raw;
}

function inference_key_forget(PDO $pdo, int $locationId): void
{
    $st = $pdo->prepare('UPDATE locations SET inference_key_hash = NULL WHERE id = :id AND inference_key_hash IS NOT NULL');
    $st->execute(['id' => $locationId]);
    if ($st->rowCount() > 0) { inference_bump($pdo, 'peers'); }
}

/** The member a presented inference key belongs to (the `place` endpoint's authentication), or 401. */
function inference_key_authenticate(PDO $pdo): array
{
    $raw = api_bearer_token();
    if ($raw === '' || !str_starts_with($raw, 'inf_')) {
        api_error('unauthorized', 'A valid inference key is required.', 401);
    }
    $st = $pdo->prepare("SELECT * FROM locations WHERE inference_key_hash = :h AND status = 'active'");
    $st->execute(['h' => hash('sha256', $raw)]);
    $loc = $st->fetch();
    if ($loc === false) {
        error_log('inference auth: key rejected (unknown, or its member retired)');
        api_error('unauthorized', 'A valid inference key is required.', 401);
    }
    return $loc;
}

// --------------------------------------------------------------------------
// The facts a member reports with its heartbeat
// --------------------------------------------------------------------------
/** Validate and store a member's inference facts. @return ?string an error message for 400, null when stored */
function inference_facts_store(PDO $pdo, array $loc, mixed $facts): ?string
{
    if (!is_array($facts)) { return 'inference is an object.'; }
    if (strlen(json_encode($facts, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) ?: '') > INFERENCE_FACTS_MAX_BYTES) { return 'inference is over 8 KB.'; }
    $models = [];
    foreach (is_array($facts['models'] ?? null) ? $facts['models'] : [] as $m) {
        if (!is_array($m) || !is_string($m['name'] ?? null) || $m['name'] === '') { continue; }
        $models[] = ['name' => mb_substr($m['name'], 0, 120), 'family' => is_string($m['family'] ?? null) ? mb_substr($m['family'], 0, 60) : null,
                     'size' => is_numeric($m['size'] ?? null) ? (int) $m['size'] : null, 'loaded' => !empty($m['loaded']),
                     'backend' => is_string($m['backend'] ?? null) ? mb_substr($m['backend'], 0, 60) : null];
        if (count($models) >= 200) { break; }
    }
    $contribution = in_array($facts['contribution'] ?? null, ['always', 'idle'], true) ? $facts['contribution'] : 'always';
    $port = is_numeric($facts['port'] ?? null) && (int) $facts['port'] >= 1 && (int) $facts['port'] <= 65535 ? (int) $facts['port'] : 11435;
    $share = !empty($facts['share']);
    $api = is_numeric($facts['api_version'] ?? null) ? (int) $facts['api_version'] : 1;
    $waits = [];
    foreach (is_array($facts['expected_wait_s'] ?? null) ? $facts['expected_wait_s'] : [] as $cls => $s) {
        if (is_string($cls) && is_numeric($s)) { $waits[$cls] = round((float) $s, 1); }
    }
    $queue = is_array($facts['queue'] ?? null) ? ['queued' => (int) ($facts['queue']['queued'] ?? 0), 'running' => (int) ($facts['queue']['running'] ?? 0)] : [];
    $lanes = is_array($facts['lanes'] ?? null) ? $facts['lanes'] : [];
    $names = array_column($models, 'name');
    sort($names);
    $sig = hash('sha256', json_encode([$names, $share, $contribution, $port, $api]) ?: '');
    $cur = $pdo->prepare('SELECT signature FROM estate_inference WHERE location_id = :id');
    $cur->execute(['id' => $loc['id']]);
    $old = $cur->fetchColumn();
    $pdo->prepare(<<<'SQL'
        INSERT INTO estate_inference (location_id, models, lanes, queue, expected_wait_s, share, contribution, port, api_version, signature, updated_at)
        VALUES (:id, :models, :lanes, :queue, :waits, :share, :contribution, :port, :api, :sig, now())
        ON CONFLICT (location_id) DO UPDATE SET models = EXCLUDED.models, lanes = EXCLUDED.lanes, queue = EXCLUDED.queue, expected_wait_s = EXCLUDED.expected_wait_s,
            share = EXCLUDED.share, contribution = EXCLUDED.contribution, port = EXCLUDED.port, api_version = EXCLUDED.api_version, signature = EXCLUDED.signature, updated_at = now()
    SQL)->execute(['id' => $loc['id'], 'models' => json_encode($models), 'lanes' => json_encode($lanes), 'queue' => json_encode($queue ?: new stdClass()),
                   'waits' => json_encode($waits ?: new stdClass()), 'share' => $share ? 't' : 'f', 'contribution' => $contribution, 'port' => $port, 'api' => $api, 'sig' => $sig]);
    if ($old !== $sig) {
        inference_bump($pdo, 'backends');      // what callers see changed (a new model, the switch); the queue alone never bumps
    }
    return null;
}

/** A member's facts leave with it (retirement, leave). */
function inference_facts_forget(PDO $pdo, int $locationId): void
{
    $st = $pdo->prepare('DELETE FROM estate_inference WHERE location_id = :id');
    $st->execute(['id' => $locationId]);
    if ($st->rowCount() > 0) { inference_bump($pdo, 'backends'); }
}

/** A member leaves the estate: its facts, its key, and the peers everyone else sees. */
function inference_member_retire(PDO $pdo, int $locationId): void
{
    inference_facts_forget($pdo, $locationId);
    inference_key_forget($pdo, $locationId);
    inference_bump($pdo, 'both');
}

// --------------------------------------------------------------------------
// The policy
// --------------------------------------------------------------------------
/** The subjects a member matches, most specific first: node:ID, dept:N (a desk's owner's departments), kind:K, org. */
function inference_subjects(PDO $pdo, array $loc): array
{
    $subjects = ['node:' . (int) $loc['id'] => 3];
    if (($loc['kind'] ?? '') === 'desk' && ($loc['owner_member_id'] ?? null) !== null) {
        $st = $pdo->prepare('SELECT department_id FROM department_members WHERE member_id = :m AND left_at IS NULL');
        $st->execute(['m' => (int) $loc['owner_member_id']]);
        foreach ($st->fetchAll(PDO::FETCH_COLUMN) as $d) { $subjects['dept:' . (int) $d] = 2; }
    }
    $subjects['kind:' . (string) $loc['kind']] = 1;
    $subjects['org'] = 0;
    return $subjects;
}

/**
 * What the policy says about $caller using $backend (both location rows): allow, max_class, max_classification,
 * priority, and which rule decided (null = the default).
 */
function inference_rule(PDO $pdo, array $caller, array $backend): array
{
    $out = ['allow' => true, 'max_class' => null, 'max_classification' => INFERENCE_DEFAULT_CLASSIFICATION, 'priority' => 0, 'rule' => null];
    if (($backend['kind'] ?? '') === 'desk' && ($caller['kind'] ?? '') === 'desk') {
        return ['allow' => false, 'max_class' => null, 'max_classification' => null, 'priority' => 0, 'rule' => 'desk_to_desk'];
    }
    $subjects = inference_subjects($pdo, $caller);
    $best = null;
    $bestKey = null;
    foreach ($pdo->query('SELECT * FROM estate_inference_policy ORDER BY id')->fetchAll() as $r) {
        if (!isset($subjects[$r['subject']])) { continue; }
        if ($r['backend_location_id'] !== null && (int) $r['backend_location_id'] !== (int) $backend['id']) { continue; }
        $key = [$subjects[$r['subject']], $r['backend_location_id'] !== null ? 1 : 0, !empty($r['allow']) ? 0 : 1];
        if ($best === null || $key > $bestKey) { $best = $r; $bestKey = $key; }
    }
    if ($best === null) { return $out; }
    return ['allow' => !empty($best['allow']), 'max_class' => $best['max_class'], 'max_classification' => $best['max_classification'] ?? INFERENCE_DEFAULT_CLASSIFICATION,
            'priority' => (int) $best['priority'], 'rule' => (int) $best['id']];
}

function inference_rule_add(PDO $pdo, array $f, int $memberId): array
{
    $subject = trim((string) ($f['subject'] ?? 'org'));
    if (!($subject === 'org' || preg_match('/^(dept:[0-9]+|kind:(desk|server|inference)|node:[0-9]+)$/', $subject))) {
        throw new InvalidArgumentException('subject is org, dept:N, kind:desk|server|inference or node:ID');
    }
    $backend = isset($f['backend_location_id']) && $f['backend_location_id'] !== '' && $f['backend_location_id'] !== null ? (int) $f['backend_location_id'] : null;
    $maxClass = isset($f['max_class']) && $f['max_class'] !== '' ? (string) $f['max_class'] : null;
    if ($maxClass !== null && !isset(INFERENCE_CLASSES[$maxClass])) { throw new InvalidArgumentException('max_class is interactive, agent or batch'); }
    $maxCls = isset($f['max_classification']) && $f['max_classification'] !== '' ? (string) $f['max_classification'] : null;
    if ($maxCls !== null && !isset(INFERENCE_SENSITIVITY[$maxCls])) { throw new InvalidArgumentException('max_classification is public, internal, restricted or prohibited'); }
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO estate_inference_policy (subject, backend_location_id, allow, max_class, max_classification, priority, note, created_by_member_id)
        VALUES (:subject, :backend, :allow, :max_class, :max_cls, :priority, :note, :by) RETURNING *
    SQL);
    $st->execute(['subject' => $subject, 'backend' => $backend, 'allow' => !isset($f['allow']) || filter_var($f['allow'], FILTER_VALIDATE_BOOL) ? 't' : 'f',
                  'max_class' => $maxClass, 'max_cls' => $maxCls, 'priority' => (int) ($f['priority'] ?? 0),
                  'note' => isset($f['note']) && trim((string) $f['note']) !== '' ? mb_substr(trim((string) $f['note']), 0, 300) : null, 'by' => $memberId]);
    $row = $st->fetch();
    inference_bump($pdo, 'both');
    return $row;
}

function inference_rule_delete(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare('DELETE FROM estate_inference_policy WHERE id = :id');
    $st->execute(['id' => $id]);
    if ($st->rowCount() > 0) { inference_bump($pdo, 'both'); return true; }
    return false;
}

// --------------------------------------------------------------------------
// The backends: what the estate publishes to a member
// --------------------------------------------------------------------------
/** Every member with facts, joined to its row; `published` says whether callers can see it (shared, with an overlay address). */
function inference_backend_rows(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT l.id, l.kind, l.name, l.owner_member_id, l.presence, host(l.overlay_address) AS address, l.overlay_address_freed_at,
               i.models, i.lanes, i.queue, i.expected_wait_s, i.share, i.contribution, i.port, i.api_version, i.updated_at
          FROM estate_inference i JOIN locations l ON l.id = i.location_id
         WHERE l.status = 'active'
         ORDER BY l.name
    SQL)->fetchAll();
}

function inference_backend_published(array $b): bool
{
    return !empty($b['share']) && ($b['address'] ?? null) !== null && ($b['overlay_address_freed_at'] ?? null) === null && ($b['presence'] ?? '') === 'online';
}

function inference_json(mixed $v, mixed $default): mixed
{
    if (is_string($v)) { $d = json_decode($v, true); return $d ?? $default; }
    return $v ?? $default;
}

function present_inference_backend(PDO $pdo, array $b, array $rule): array
{
    return ['node' => $b['kind'] . ':' . (int) $b['id'], 'id' => (int) $b['id'], 'kind' => (string) $b['kind'],
            'name' => overlay_member_name($pdo, (int) $b['id']) ?? overlay_label((string) $b['name']), 'display_name' => (string) $b['name'],
            'address' => $b['address'], 'port' => (int) $b['port'], 'api_version' => (int) $b['api_version'],
            'models' => inference_json($b['models'], []), 'expected_wait_s' => inference_json($b['expected_wait_s'], new stdClass()),
            'queue' => inference_json($b['queue'], new stdClass()), 'share' => !empty($b['share']), 'contribution' => (string) $b['contribution'],
            'class_max' => $rule['max_class'], 'classification_max' => $rule['max_classification'] ?? INFERENCE_DEFAULT_CLASSIFICATION, 'priority' => $rule['priority'],
            'updated_at' => json_ts($b['updated_at'] ?? null)];
}

/** GET endpoints.inference for a member: the backends it may use, never itself. With $everything (an operator's desk, ?all=1):
 *  every published backend, each with `allowed` for this member. */
function inference_backends_answer(PDO $pdo, array $loc, bool $everything = false): array
{
    $s = inference_settings($pdo);
    $out = [];
    foreach (inference_backend_rows($pdo) as $b) {
        if ((int) $b['id'] === (int) $loc['id'] || !inference_backend_published($b)) { continue; }
        $rule = inference_rule($pdo, $loc, $b);
        if (!$rule['allow'] && !$everything) { continue; }
        $row = present_inference_backend($pdo, $b, $rule);
        if ($everything) { $row['allowed'] = $rule['allow']; }
        $out[] = $row;
    }
    $editions = inference_editions($pdo);
    $pdo->prepare('UPDATE locations SET inference_seen_version = :v WHERE id = :id')->execute(['v' => (int) $s['version'], 'id' => $loc['id']]);
    return ['ok' => true, 'surface' => DESK_SURFACE, 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z'), 'self' => $loc['kind'] . ':' . (int) $loc['id'],
            'backends' => $out, 'editions' => $editions, 'place' => in_array('scheduler', $editions, true) ? app_url('/api/v1/estate/inference/place') : null,
            'lease_s' => (int) $s['lease_s'], 'refresh_s' => INFERENCE_REFRESH_S, 'version' => (int) $s['version']];
}

// --------------------------------------------------------------------------
// The peers: who may call a serving host
// --------------------------------------------------------------------------
function inference_peers_answer(PDO $pdo, array $host): array
{
    $s = inference_settings($pdo);
    $st = $pdo->query("SELECT * FROM locations WHERE status = 'active' AND kind IN ('desk', 'server', 'inference') AND inference_key_hash IS NOT NULL ORDER BY name");
    $peers = [];
    foreach ($st->fetchAll() as $m) {
        if ((int) $m['id'] === (int) $host['id']) { continue; }
        $rule = inference_rule($pdo, $m, $host);
        if (!$rule['allow']) { continue; }
        $peers[] = ['node' => $m['kind'] . ':' . (int) $m['id'], 'id' => (int) $m['id'], 'kind' => (string) $m['kind'],
                    'name' => overlay_member_name($pdo, (int) $m['id']) ?? overlay_label((string) $m['name']), 'display_name' => (string) $m['name'],
                    'address' => ($m['overlay_address'] ?? null) !== null && ($m['overlay_address_freed_at'] ?? null) === null ? (string) $m['overlay_address'] : null,
                    'key_hash' => (string) $m['inference_key_hash'], 'class_max' => $rule['max_class'],
                    'classification_max' => $rule['max_classification'] ?? INFERENCE_DEFAULT_CLASSIFICATION, 'priority' => $rule['priority']];
    }
    $pdo->prepare('UPDATE locations SET peers_seen_version = :v WHERE id = :id')->execute(['v' => (int) $s['peers_version'], 'id' => $host['id']]);
    return ['ok' => true, 'surface' => DESK_SURFACE, 'fetched_at' => gmdate('Y-m-d\TH:i:s\Z'), 'self' => $host['kind'] . ':' . (int) $host['id'],
            'peers' => $peers, 'refresh_s' => 300, 'version' => (int) $s['peers_version']];
}

// --------------------------------------------------------------------------
// Placement (the `scheduler` entitlement)
// --------------------------------------------------------------------------
function inference_model_served(array $models, ?string $model): bool
{
    if ($model === null || $model === '') { return true; }
    foreach ($models as $m) {
        $n = (string) ($m['name'] ?? '');
        if ($n === $model || $n === $model . ':latest' || $model === $n . ':latest') { return true; }
    }
    return false;
}

/** {class, model, sensitivity, deadline_s, origin} → {backend, lease_s, reason}. */
function inference_place(PDO $pdo, array $caller, array $body): array
{
    $s = inference_settings($pdo);
    if (empty($s['scheduler'])) {
        return ['ok' => true, 'surface' => DESK_SURFACE, 'backend' => null, 'reason' => 'not_entitled', 'lease_s' => 0];
    }
    $class = is_string($body['class'] ?? null) && isset(INFERENCE_CLASSES[$body['class']]) ? $body['class'] : 'interactive';
    $model = is_string($body['model'] ?? null) ? $body['model'] : null;
    $sens = is_string($body['sensitivity'] ?? null) && isset(INFERENCE_SENSITIVITY[$body['sensitivity']]) ? $body['sensitivity'] : 'internal';
    $deadline = is_numeric($body['deadline_s'] ?? null) ? (float) $body['deadline_s'] : null;
    $cands = [];
    $considered = 0;
    $skipped = ['classification' => 0, 'no_capacity' => 0, 'no_model' => 0];
    foreach (inference_backend_rows($pdo) as $b) {
        if ((int) $b['id'] === (int) $caller['id'] || !inference_backend_published($b)) { continue; }
        $rule = inference_rule($pdo, $caller, $b);
        if (!$rule['allow']) { continue; }
        $considered++;
        $models = inference_json($b['models'], []);
        if (!inference_model_served(is_array($models) ? $models : [], $model)) { $skipped['no_model']++; continue; }
        if (INFERENCE_SENSITIVITY[$sens] > INFERENCE_SENSITIVITY[$rule['max_classification'] ?? INFERENCE_DEFAULT_CLASSIFICATION]) { $skipped['classification']++; continue; }
        $cls = $class;
        if ($rule['max_class'] !== null && INFERENCE_CLASSES[$cls] < INFERENCE_CLASSES[$rule['max_class']]) {
            $cls = $rule['max_class'];      // the ceiling: a higher class is served as the ceiling's, not refused
        }
        $waits = inference_json($b['expected_wait_s'], []);
        $wait = is_array($waits) && isset($waits[$cls]) && is_numeric($waits[$cls]) ? (float) $waits[$cls] : 0.0;
        $queue = inference_json($b['queue'], []);
        if (is_array($queue) && (int) ($queue['queued'] ?? 0) >= 100) { $skipped['no_capacity']++; continue; }
        if ($deadline !== null && $wait > $deadline) { $skipped['no_capacity']++; continue; }
        $cands[] = ['row' => present_inference_backend($pdo, $b, $rule), 'wait' => $wait, 'priority' => $rule['priority'], 'class' => $cls];
    }
    if ($cands === []) {
        // the reason that matters most: a host that serves the model but refuses the classification, then one with no room, then no host with the model
        $reason = $considered === 0 ? 'no_backend' : ($skipped['classification'] > 0 ? 'classification' : ($skipped['no_capacity'] > 0 ? 'no_capacity' : 'no_model'));
        return ['ok' => true, 'surface' => DESK_SURFACE, 'backend' => null, 'reason' => $reason, 'lease_s' => 0, 'considered' => $considered];
    }
    usort($cands, static fn ($a, $b) => [$b['priority'], $a['wait'], $a['row']['name']] <=> [$a['priority'], $b['wait'], $b['row']['name']]);
    $best = $cands[0];
    return ['ok' => true, 'surface' => DESK_SURFACE, 'backend' => $best['row'], 'class' => $best['class'], 'expected_wait_s' => $best['wait'],
            'lease_s' => (int) $s['lease_s'], 'reason' => 'placed', 'considered' => $considered];
}

// --------------------------------------------------------------------------
// Settings → Desks, for an operator
// --------------------------------------------------------------------------
function present_inference_rule(array $r): array
{
    return ['id' => (int) $r['id'], 'subject' => (string) $r['subject'], 'backend_location_id' => $r['backend_location_id'] !== null ? (int) $r['backend_location_id'] : null,
            'backend_name' => $r['backend_name'] ?? null, 'allow' => !empty($r['allow']), 'max_class' => $r['max_class'], 'max_classification' => $r['max_classification'],
            'priority' => (int) $r['priority'], 'note' => $r['note'], 'created_at' => json_ts($r['created_at'] ?? null)];
}

function present_inference_for_settings(PDO $pdo): array
{
    $s = inference_settings($pdo);
    $backends = [];
    foreach (inference_backend_rows($pdo) as $b) {
        $row = present_inference_backend($pdo, $b, ['max_class' => null, 'max_classification' => INFERENCE_DEFAULT_CLASSIFICATION, 'priority' => 0]);
        unset($row['class_max'], $row['classification_max'], $row['priority']);
        $row['presence'] = (string) $b['presence'];
        $row['published'] = inference_backend_published($b);
        $row['why'] = $row['published'] ? null : (empty($b['share']) ? 'not shared' : ($b['address'] === null || $b['overlay_address_freed_at'] !== null ? 'no overlay address' : 'offline'));
        $row['models'] = array_map(static fn ($m) => ['name' => $m['name'] ?? '', 'loaded' => !empty($m['loaded'])], is_array($row['models']) ? $row['models'] : []);
        $backends[] = $row;
    }
    $rules = array_map('present_inference_rule', $pdo->query('SELECT p.*, l.name AS backend_name FROM estate_inference_policy p LEFT JOIN locations l ON l.id = p.backend_location_id ORDER BY p.id')->fetchAll());
    $keyed = (int) $pdo->query("SELECT count(*) FROM locations WHERE status = 'active' AND inference_key_hash IS NOT NULL")->fetchColumn();
    $queued = 0; $running = 0;
    foreach ($backends as $b) { $q = is_array($b['queue']) ? $b['queue'] : (array) $b['queue']; $queued += (int) ($q['queued'] ?? 0); $running += (int) ($q['running'] ?? 0); }
    return ['backends' => $backends, 'rules' => $rules, 'scheduler' => !empty($s['scheduler']), 'lease_s' => (int) $s['lease_s'],
            'version' => (int) $s['version'], 'peers_version' => (int) $s['peers_version'], 'members_with_keys' => $keyed,
            'queue' => ['queued' => $queued, 'running' => $running, 'backends' => count(array_filter($backends, static fn ($b) => $b['published']))]];
}
