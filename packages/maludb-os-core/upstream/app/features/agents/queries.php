<?php
declare(strict_types=1);

/**
 * Agent HR: employees (human and agent), their config history, tool grants, duties,
 * escalations and performance reviews (build spec: docs/build-specs/agent-hr.md).
 *
 * Reads come from the mcp_* views; writes go to base tables, as every earlier slice
 * established. `mcp_agents` is insider-open (app_is_insider()); the detail views
 * (mcp_agent_config_versions, mcp_agent_tool_grants, mcp_agent_duties, mcp_hr_events,
 * mcp_performance_reviews, mcp_agent_escalations) are gated tighter, on app_can_see_agent()
 * (hr grant holder, the agent's manager, or the agent itself) — that filtering happens in SQL,
 * so a plain insider reading agent-view simply sees less, never an error.
 */

const AGENT_PAGE_SIZE = 25;
const AGENT_STATUSES = ['candidate', 'active', 'suspended', 'offboarded'];
const ESCALATION_REASON_KINDS = ['needs_approval', 'uncertain', 'blocked', 'policy', 'error', 'budget', 'other'];
/**
 * The agent-view tabs, defined once. Both entry points read this: the full-page GET
 * (html/agents/view.php) and the re-render (render_agent_page()). They each kept their own
 * copy until 2026-09-18, which meant adding a tab worked in one and 404'd in the other.
 */
const AGENT_VIEW_TABS = ['chat', 'job', 'tools', 'skills', 'duties', 'roster', 'inbox', 'performance', 'trail'];   // inbox: db/155   // skills: owner, 2026-09-27   // chat: agent-chat.md, 2026-09-29 (leftmost)

const AGENT_KINDS = ['orchestrator', 'subagent', 'voice'];
/** What each kind is called on screen (db/091 added the voice agent). */
const AGENT_KIND_LABELS = [
    'orchestrator' => 'Orchestrator',
    'subagent' => 'Subagent',
    'voice' => 'Voice Agent',
];

/** json_encode([]) yields '[]', not the empty jsonb OBJECT agent_tool_grants.constraints and
 *  agent_config_versions.harness_config expect — force '{}' for an empty array. */
function json_object_encode(array $a): string
{
    return $a === [] ? '{}' : json_encode($a, JSON_THROW_ON_ERROR);
}

// --------------------------------------------------------------------------
// Agents
// --------------------------------------------------------------------------
function find_agents(PDO $pdo, array $filters, int $page = 1): array
{
    $where = [];
    $params = [];
    if (($filters['status'] ?? '') !== '' && in_array($filters['status'], AGENT_STATUSES, true)) {
        $where[] = 'a.status = :status';
        $params['status'] = $filters['status'];
    } else {
        $where[] = "a.status <> 'offboarded'";
    }
    if (($filters['department'] ?? null) !== null) {
        $where[] = 'EXISTS (SELECT 1 FROM mcp_department_members dm
                             WHERE dm.member_id = a.agent_member_id AND dm.department_id = :dept AND dm.left_at IS NULL)';
        $params['dept'] = (int) $filters['department'];
    }
    if (($filters['kind'] ?? '') !== '' && in_array($filters['kind'], AGENT_KINDS, true)) {
        $where[] = 'a.agent_kind = :kind';
        $params['kind'] = $filters['kind'];
    }
    $whereSql = $where === [] ? '' : 'WHERE ' . implode(' AND ', $where);
    $offset = (max(1, $page) - 1) * AGENT_PAGE_SIZE;

    // mcp_agents carries the db/070-072 columns since db/073 (description, role_key,
    // profile_pic_url, agent_kind, subagent_count), so nothing joins back to the base table:
    // reads go through the view, writes go to agent_profiles. The join this replaced worked in
    // PHP and broke the MCP tools outright, because app_records_ro holds no base-table grants.
    // The department an agent works in is a department_members row, not a column on the agent:
    // one lateral, taking the primary membership (the one hiring writes) and falling back to
    // the first by name, so the list can show it without a query per row.
    $st = $pdo->prepare("
        SELECT a.*, d.department_name, d.department_id, count(*) OVER() AS total_count
          FROM mcp_agents a
          LEFT JOIN LATERAL (
              SELECT dm.department_name, dm.department_id
                FROM mcp_department_members dm
               WHERE dm.member_id = a.agent_member_id AND dm.left_at IS NULL
               ORDER BY dm.is_primary DESC, dm.department_name
               LIMIT 1
          ) d ON true
          {$whereSql}
         ORDER BY a.display_name
         LIMIT :lim OFFSET :off
    ");
    foreach ($params as $k => $v) {
        $st->bindValue($k, $v);
    }
    $st->bindValue('lim', AGENT_PAGE_SIZE, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

function find_agent(PDO $pdo, int $memberId): ?array
{
    $st = $pdo->prepare('
        SELECT a.*, td.email, td.departments, td.timezone, td.status AS member_status,
               mm.member_kind AS manager_kind, hl.name AS home_location_name
          FROM mcp_agents a
          LEFT JOIN mcp_team_directory td ON td.member_id = a.agent_member_id
          -- Same-row joins (click-around step 2): the kind of the manager decides which page the
          -- name opens; the name of the home location replaces "View location" on the page.
          LEFT JOIN members mm ON mm.id = a.manager_member_id
          LEFT JOIN mcp_locations hl ON hl.location_id = a.home_location_id
         WHERE a.agent_member_id = :id
    ');
    $st->execute(['id' => $memberId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

// --------------------------------------------------------------------------
// Config versions (immutable — see hiring.php for how a new one is created/activated)
// --------------------------------------------------------------------------
// v.harness_config already carries the resolved model parameters (db/071's mirror trigger),
// via mcp_agent_config_versions — nothing extra to join for those. system_prompt_id/version
// were added to agent_config_versions by db/070 but not to the view, so both are joined back
// here on the row the view already decided this caller may see (never a new row), same as
// find_agent() above; sp.* is likewise a same-row join, not a new visibility decision.
const AGENT_CONFIG_VERSION_PROMPT_JOIN = "
    JOIN agent_config_versions base ON base.id = v.config_version_id
    LEFT JOIN system_prompts sp ON sp.id = base.system_prompt_id
    LEFT JOIN mcp_model_registry mr ON mr.model_id = v.model_id
";
const AGENT_CONFIG_VERSION_PROMPT_COLUMNS = '
    mr.display_name AS model_name, base.system_prompt_id, base.system_prompt_version,
    sp.prompt_key AS system_prompt_key, sp.name AS system_prompt_name,
    base.runtime_config
';

function find_agent_versions(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare('
        SELECT v.*, ' . AGENT_CONFIG_VERSION_PROMPT_COLUMNS . '
          FROM mcp_agent_config_versions v
          ' . AGENT_CONFIG_VERSION_PROMPT_JOIN . '
         WHERE v.agent_member_id = :id
         ORDER BY v.version_no DESC
    ');
    $st->execute(['id' => $memberId]);
    return $st->fetchAll();
}

function find_agent_version(PDO $pdo, int $versionId): ?array
{
    $st = $pdo->prepare('
        SELECT v.*, ' . AGENT_CONFIG_VERSION_PROMPT_COLUMNS . '
          FROM mcp_agent_config_versions v
          ' . AGENT_CONFIG_VERSION_PROMPT_JOIN . '
         WHERE v.config_version_id = :id
    ');
    $st->execute(['id' => $versionId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** The version to show on the Job tab: the active one, else the most recent draft (a
 *  candidate has no current_config_version_id until activation — show its latest anyway). */
function current_or_latest_agent_version(PDO $pdo, array $agent): ?array
{
    if (($agent['current_config_version_id'] ?? null) !== null) {
        return find_agent_version($pdo, (int) $agent['current_config_version_id']);
    }
    $versions = find_agent_versions($pdo, (int) $agent['agent_member_id']);
    return $versions[0] ?? null;
}

// --------------------------------------------------------------------------
// Tool grants
// --------------------------------------------------------------------------
function find_agent_tool_grants(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_agent_tool_grants WHERE agent_member_id = :id ORDER BY endpoint_name, tool_name');
    $st->execute(['id' => $memberId]);
    return $st->fetchAll();
}

/** The MCP endpoints an agent may be granted a tool on, for the Tools-tab and hire-form
 *  pickers: kind='mcp', agent_reachable, and still active. Reads mcp_application_endpoints
 *  (the view) — never the application_endpoints base table (app_records_ro holds no base-table
 *  grants). Whether a chosen endpoint actually qualifies is still enforced by the
 *  agent_tool_grants_endpoint_valid trigger on write — this is the picker's offer, not the
 *  authority. */
function find_grantable_tool_endpoints(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT application_endpoint_id, application_id, application_name,
               name AS endpoint_name, url AS endpoint_url, mcp_surface_version
          FROM mcp_application_endpoints
         WHERE kind = 'mcp' AND agent_reachable = true
         ORDER BY application_name, name
    SQL)->fetchAll();
}

/** One endpoint's application/endpoint name, for building a readable label (approval
 *  descriptions, revoke messages) before or without the tool-grant row itself. Also reads
 *  the view, and is not restricted to mcp/agent_reachable — used for labelling, not for
 *  deciding whether a grant is allowed (the trigger decides that). */
function find_application_endpoint_option(PDO $pdo, int $endpointId): ?array
{
    $st = $pdo->prepare('SELECT application_endpoint_id, application_id, application_name,
                                 name AS endpoint_name, kind, url
                            FROM mcp_application_endpoints WHERE application_endpoint_id = :id');
    $st->execute(['id' => $endpointId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function grant_agent_tool(PDO $pdo, int $memberId, int $endpointId, string $tool, array $constraints, int $by): array
{
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO agent_tool_grants (agent_member_id, application_endpoint_id, tool_name, constraints, granted_by)
        VALUES (:m, :endpoint, :tool, :constraints, :by)
        ON CONFLICT (agent_member_id, application_endpoint_id, tool_name) WHERE revoked_at IS NULL
        DO UPDATE SET constraints = EXCLUDED.constraints, granted_by = EXCLUDED.granted_by, revoked_at = NULL
        RETURNING id
    SQL);
    $st->execute([
        'm' => $memberId, 'endpoint' => $endpointId, 'tool' => $tool,
        'constraints' => json_object_encode($constraints), 'by' => $by,
    ]);
    $row = $st->fetch();
    if ($row === false) {
        return [];
    }
    $st2 = $pdo->prepare('SELECT * FROM mcp_agent_tool_grants
                            WHERE agent_member_id = :m AND application_endpoint_id = :e AND tool_name = :t');
    $st2->execute(['m' => $memberId, 'e' => $endpointId, 't' => $tool]);
    return $st2->fetch() ?: [];
}

function revoke_agent_tool(PDO $pdo, int $grantId): bool
{
    $st = $pdo->prepare('UPDATE agent_tool_grants SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL');
    $st->execute(['id' => $grantId]);
    return $st->rowCount() > 0;
}

function find_agent_tool_grant(PDO $pdo, int $grantId): ?array
{
    $st = $pdo->prepare('SELECT * FROM agent_tool_grants WHERE id = :id');
    $st->execute(['id' => $grantId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

// --------------------------------------------------------------------------
// Duties
// --------------------------------------------------------------------------
function find_agent_duties(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_agent_duties WHERE agent_member_id = :id ORDER BY name');
    $st->execute(['id' => $memberId]);
    return $st->fetchAll();
}

function upsert_agent_duty(PDO $pdo, int $memberId, ?int $dutyId, array $f): array
{
    if ($dutyId === null) {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO agent_duties (agent_member_id, name, instructions, schedule_cron, timezone, active)
            VALUES (:m, :name, :instructions, :cron, :tz, true)
            RETURNING id
        SQL);
        $st->execute([
            'm' => $memberId, 'name' => $f['name'], 'instructions' => $f['instructions'],
            'cron' => $f['schedule_cron'], 'tz' => $f['timezone'] ?: 'UTC',
        ]);
    } else {
        $st = $pdo->prepare(<<<'SQL'
            UPDATE agent_duties
               SET name = :name, instructions = :instructions, schedule_cron = :cron,
                   timezone = :tz, updated_at = now()
             WHERE id = :id AND agent_member_id = :m
            RETURNING id
        SQL);
        $st->execute([
            'id' => $dutyId, 'm' => $memberId, 'name' => $f['name'], 'instructions' => $f['instructions'],
            'cron' => $f['schedule_cron'], 'tz' => $f['timezone'] ?: 'UTC',
        ]);
    }
    $row = $st->fetch();
    if ($row === false) {
        return [];
    }
    $st2 = $pdo->prepare('SELECT * FROM mcp_agent_duties WHERE duty_id = :id');
    $st2->execute(['id' => $row['id']]);
    return $st2->fetch() ?: [];
}

function remove_agent_duty(PDO $pdo, int $dutyId): bool
{
    $st = $pdo->prepare('DELETE FROM agent_duties WHERE id = :id');
    $st->execute(['id' => $dutyId]);
    return $st->rowCount() > 0;
}

function find_agent_duty(PDO $pdo, int $dutyId): ?array
{
    $st = $pdo->prepare('SELECT * FROM agent_duties WHERE id = :id');
    $st->execute(['id' => $dutyId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/**
 * description/role_key (db/070) are plain agent_profiles columns, not versioned like
 * job_description — editable any time, independent of the config-version history. Called from
 * the edit form alongside create_config_version(); hire_agent() sets them at INSERT instead.
 * The photo is not here: it is a file, written by store_agent_photo() (db/090, photos.php).
 */
function update_agent_identity(PDO $pdo, int $memberId, array $f): array
{
    // phone_number is only written when the form offered it (a voice agent); otherwise the
    // stored value stands, so editing a subagent never silently clears a number it never had.
    $sql = 'UPDATE agent_profiles SET description = :desc, role_key = :role, updated_at = now()';
    $params = ['desc' => $f['description'] ?: null, 'role' => $f['role_key'] ?: null, 'id' => $memberId];
    if (array_key_exists('phone_number', $f)) {
        $sql = 'UPDATE agent_profiles SET description = :desc, role_key = :role,
                       phone_number = :phone, updated_at = now()';
        $params['phone'] = $f['phone_number'] ?: null;
    }
    $st = $pdo->prepare($sql . ' WHERE member_id = :id RETURNING member_id');
    $st->execute($params);
    $row = $st->fetch();
    return $row === false ? [] : (find_agent($pdo, $memberId) ?? []);
}

// --------------------------------------------------------------------------
// Manager, lifecycle
// --------------------------------------------------------------------------
/** Refuses a manager that is neither a person nor an orchestrator agent (agent_manager_error). */
function set_agent_manager(PDO $pdo, int $memberId, int $managerId): array
{
    $problem = agent_manager_error($pdo, $managerId, $memberId);
    if ($problem !== null) {
        throw new RuntimeException($problem);
    }
    $st = $pdo->prepare('UPDATE agent_profiles SET manager_member_id = :mgr, updated_at = now()
                          WHERE member_id = :id RETURNING member_id');
    $st->execute(['mgr' => $managerId, 'id' => $memberId]);
    if ($st->fetch() === false) {
        return [];
    }
    $ev = $pdo->prepare(<<<'SQL'
        INSERT INTO hr_events (member_id, event_type, actor_member_id, note)
        VALUES (:m, 'manager_change', :by, NULL)
    SQL);
    $ev->execute(['m' => $memberId, 'by' => $managerId]);
    return find_agent($pdo, $memberId) ?? [];
}

function suspend_agent(PDO $pdo, int $memberId, ?string $reason, int $by): array
{
    $st = $pdo->prepare("UPDATE agent_profiles SET status = 'suspended', suspended_at = now(), updated_at = now()
                          WHERE member_id = :id AND status IN ('active', 'candidate') RETURNING member_id");
    $st->execute(['id' => $memberId]);
    if ($st->fetch() === false) {
        return [];
    }
    $ev = $pdo->prepare("INSERT INTO hr_events (member_id, event_type, actor_member_id, note) VALUES (:m, 'suspend', :by, :note)");
    $ev->execute(['m' => $memberId, 'by' => $by, 'note' => $reason]);
    return find_agent($pdo, $memberId) ?? [];
}

function reinstate_agent(PDO $pdo, int $memberId, int $by): array
{
    $st = $pdo->prepare("UPDATE agent_profiles SET status = 'active', suspended_at = NULL, updated_at = now()
                          WHERE member_id = :id AND status = 'suspended' RETURNING member_id");
    $st->execute(['id' => $memberId]);
    if ($st->fetch() === false) {
        return [];
    }
    $ev = $pdo->prepare("INSERT INTO hr_events (member_id, event_type, actor_member_id, note) VALUES (:m, 'reinstate', :by, NULL)");
    $ev->execute(['m' => $memberId, 'by' => $by]);
    return find_agent($pdo, $memberId) ?? [];
}

/** Revokes tokens and grants; the trail (hr_events, activity_log) is kept forever — an agent
 *  row is never deleted (CLAUDE.md, agent HR: never delete). */
function offboard_agent(PDO $pdo, int $memberId, string $reason, int $by): array
{
    $pdo->beginTransaction();
    try {
        $st = $pdo->prepare("UPDATE agent_profiles SET status = 'offboarded', offboarded_at = now(),
                                     offboarded_by = :by, updated_at = now()
                              WHERE member_id = :id AND status <> 'offboarded' RETURNING member_id");
        $st->execute(['id' => $memberId, 'by' => $by]);
        if ($st->fetch() === false) {
            $pdo->rollBack();
            return [];
        }
        $pdo->prepare('UPDATE agent_tool_grants SET revoked_at = now() WHERE agent_member_id = :id AND revoked_at IS NULL')
            ->execute(['id' => $memberId]);
        $pdo->prepare('UPDATE agent_duties SET active = false, updated_at = now() WHERE agent_member_id = :id AND active')
            ->execute(['id' => $memberId]);
        $pdo->prepare('UPDATE mcp_access_tokens SET revoked_at = now() WHERE member_id = :id AND revoked_at IS NULL')
            ->execute(['id' => $memberId]);
        $pdo->prepare('UPDATE location_residents SET removed_at = now() WHERE member_id = :id AND removed_at IS NULL')
            ->execute(['id' => $memberId]);
        $ev = $pdo->prepare("INSERT INTO hr_events (member_id, event_type, actor_member_id, note) VALUES (:m, 'offboard', :by, :note)");
        $ev->execute(['m' => $memberId, 'by' => $by, 'note' => $reason]);
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
    return find_agent($pdo, $memberId) ?? [];
}

// --------------------------------------------------------------------------
// HR events (trail)
// --------------------------------------------------------------------------
function find_hr_events(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_hr_events WHERE member_id = :id ORDER BY occurred_at DESC');
    $st->execute(['id' => $memberId]);
    return $st->fetchAll();
}

// --------------------------------------------------------------------------
// Escalations
// --------------------------------------------------------------------------
function find_escalations(PDO $pdo, array $filters, int $page = 1): array
{
    $where = ['1 = 1'];
    $params = [];
    if (($filters['agent'] ?? null) !== null) {
        $where[] = 'e.agent_member_id = :agent';
        $params['agent'] = (int) $filters['agent'];
    }
    if (!empty($filters['open'])) {
        $where[] = 'e.resolved_at IS NULL';
    }
    $whereSql = implode(' AND ', $where);
    $offset = (max(1, $page) - 1) * AGENT_PAGE_SIZE;

    $st = $pdo->prepare("
        SELECT e.*, count(*) OVER() AS total_count
          FROM mcp_agent_escalations e
         WHERE {$whereSql}
         ORDER BY e.created_at DESC
         LIMIT :lim OFFSET :off
    ");
    foreach ($params as $k => $v) {
        $st->bindValue($k, $v);
    }
    $st->bindValue('lim', AGENT_PAGE_SIZE, PDO::PARAM_INT);
    $st->bindValue('off', $offset, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

function find_escalation(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_agent_escalations WHERE escalation_id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** Called by an agent caller only (Who: "agents only"). $f: reason_kind, summary, entity_type?,
 *  entity_id?, to_member_id? (default: the agent's own manager), open_ticket (bool, carve-out
 *  below — the tickets module is not built yet, so a ticket is never actually opened). */
function raise_escalation(PDO $pdo, int $agentMemberId, array $f): array
{
    $toMemberId = $f['to_member_id'] ?? null;
    if ($toMemberId === null) {
        $st = $pdo->prepare('SELECT manager_member_id FROM mcp_agents WHERE agent_member_id = :id');
        $st->execute(['id' => $agentMemberId]);
        $toMemberId = $st->fetchColumn() ?: null;
    }
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO agent_escalations
            (agent_member_id, to_member_id, reason_kind, summary, entity_type, entity_id)
        VALUES (:agent, :to, :reason, :summary, :etype, :eid)
        RETURNING id
    SQL);
    $st->execute([
        'agent' => $agentMemberId, 'to' => $toMemberId, 'reason' => $f['reason_kind'],
        'summary' => $f['summary'], 'etype' => $f['entity_type'] ?? null, 'eid' => $f['entity_id'] ?? null,
    ]);
    $id = (int) $st->fetchColumn();
    return find_escalation($pdo, $id) ?? [];
}

function resolve_escalation(PDO $pdo, int $id, ?string $note, int $by): array
{
    $st = $pdo->prepare('UPDATE agent_escalations SET resolved_at = now(), resolved_by = :by
                          WHERE id = :id AND resolved_at IS NULL RETURNING id');
    $st->execute(['id' => $id, 'by' => $by]);
    if ($st->fetch() === false) {
        return [];
    }
    return find_escalation($pdo, $id) ?? [];
}

// --------------------------------------------------------------------------
// Performance reviews (member-keyed — humans and agents both, per the spec)
// --------------------------------------------------------------------------
function find_performance_reviews(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_performance_reviews WHERE member_id = :id ORDER BY period_end DESC');
    $st->execute(['id' => $memberId]);
    return $st->fetchAll();
}

/**
 * "metrics filled from records and activity" (manifest). The prompt ledger and agent runs are
 * out of scope for this slice (they do not exist yet), so the metrics this fills are exactly
 * what IS answerable today: activity_log volume for the period, and, for an agent, escalations
 * raised — the same carve-out the Performance tab states rather than showing zeros that read
 * as facts.
 */
function review_metrics_for(PDO $pdo, array $member, string $periodStart, string $periodEnd): array
{
    $memberId = (int) $member['member_id'];
    $st = $pdo->prepare('SELECT count(*) FROM activity_log
                          WHERE actor_member_id = :id AND occurred_at::date BETWEEN :from AND :to');
    $st->execute(['id' => $memberId, 'from' => $periodStart, 'to' => $periodEnd]);
    $metrics = ['activity_count' => (int) $st->fetchColumn()];
    if (($member['member_kind'] ?? 'human') === 'agent') {
        $st = $pdo->prepare('SELECT count(*) FROM agent_escalations
                              WHERE agent_member_id = :id AND created_at::date BETWEEN :from AND :to');
        $st->execute(['id' => $memberId, 'from' => $periodStart, 'to' => $periodEnd]);
        $metrics['escalations_raised'] = (int) $st->fetchColumn();
    }
    $metrics['note'] = 'Task/ticket/spend/eval metrics arrive with the prompt ledger and agent runs (phase 5).';
    return $metrics;
}

function create_performance_review(PDO $pdo, int $memberId, array $f, int $by): array
{
    $member = find_team_member($pdo, $memberId);
    if ($member === null) {
        throw new RuntimeException('That member does not exist.');
    }
    $metrics = review_metrics_for($pdo, $member, $f['period_start'], $f['period_end']);
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO performance_reviews
            (member_id, reviewer_member_id, period_start, period_end, rating, summary, metrics)
        VALUES (:m, :by, :from, :to, :rating, :summary, :metrics)
        RETURNING id
    SQL);
    $st->execute([
        'm' => $memberId, 'by' => $by, 'from' => $f['period_start'], 'to' => $f['period_end'],
        'rating' => $f['rating'], 'summary' => $f['summary'] ?: null,
        'metrics' => json_encode($metrics, JSON_THROW_ON_ERROR),
    ]);
    $id = (int) $st->fetchColumn();
    $pdo->prepare("INSERT INTO hr_events (member_id, event_type, actor_member_id, note) VALUES (:m, 'review', :by, :note)")
        ->execute(['m' => $memberId, 'by' => $by, 'note' => $f['summary'] ?: null]);
    $st2 = $pdo->prepare('SELECT * FROM mcp_performance_reviews WHERE review_id = :id');
    $st2->execute(['id' => $id]);
    return $st2->fetch() ?: [];
}

// --------------------------------------------------------------------------
// Performance tab — what IS answerable before the prompt ledger and agent runs exist:
// escalations raised, approval requests, and actions taken from activity_log.
// --------------------------------------------------------------------------
function find_agent_approval_requests(PDO $pdo, int $memberId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_approval_requests WHERE requested_by_member_id = :id
                          ORDER BY created_at DESC LIMIT 10');
    $st->execute(['id' => $memberId]);
    return $st->fetchAll();
}

function count_member_activity(PDO $pdo, int $memberId): int
{
    $st = $pdo->prepare('SELECT count(*) FROM activity_log WHERE actor_member_id = :id');
    $st->execute(['id' => $memberId]);
    return (int) $st->fetchColumn();
}

// --------------------------------------------------------------------------
// Pickers
// --------------------------------------------------------------------------
/**
 * Who may manage an agent: any person, or an orchestrator agent (2026-09-18, owner). An
 * orchestrator already holds a roster and delegates to it, so managing what it delegates to is
 * the same job stated twice; a subagent does the work and never re-delegates, and a voice agent
 * answers calls, so neither manages anybody.
 */
function find_manager_options(PDO $pdo): array
{
    return $pdo->query("
        SELECT member_id, display_name, member_kind
          FROM mcp_team_directory
         WHERE member_kind = 'human'
         UNION ALL
        SELECT agent_member_id AS member_id, display_name, 'agent' AS member_kind
          FROM mcp_agents
         WHERE agent_kind = 'orchestrator' AND status <> 'offboarded'
         ORDER BY member_kind, display_name")->fetchAll();
}

/**
 * Why this member cannot manage that agent, or null when it can. One rule, asked by the hire
 * form, the manager picker and the endpoints behind both — the schema has never enforced it
 * ("human (app-enforced)" in db/042), so a single place to ask is the whole of the enforcement.
 */
function agent_manager_error(PDO $pdo, int $managerId, ?int $agentMemberId): ?string
{
    if ($agentMemberId !== null && $managerId === $agentMemberId) {
        return 'An agent cannot manage itself.';
    }
    $st = $pdo->prepare('SELECT m.member_kind, m.display_name, ap.agent_kind, ap.status
                           FROM members m
                           LEFT JOIN agent_profiles ap ON ap.member_id = m.id
                          WHERE m.id = :id');
    $st->execute(['id' => $managerId]);
    $row = $st->fetch();
    if ($row === false) {
        return 'That member does not exist.';
    }
    if ($row['member_kind'] === 'human') {
        return null;
    }
    $name = (string) $row['display_name'];
    if ($row['agent_kind'] !== 'orchestrator') {
        return $name . ' is a ' . ($row['agent_kind'] === 'voice' ? 'voice agent' : 'subagent')
            . ', so it manages nobody — a manager is a person or an orchestrator agent.';
    }
    if ($row['status'] === 'offboarded') {
        return $name . ' has been offboarded, so it cannot manage anybody.';
    }
    // An orchestrator managed by the agent it would manage leaves a loop with nobody at the
    // top of it, which is how an approval queue becomes unanswerable.
    if ($agentMemberId !== null && agent_manager_chain_includes($pdo, $managerId, $agentMemberId)) {
        return $name . ' already reports to this agent, directly or further up.';
    }
    return null;
}

/** Does the management chain above $managerId pass through $agentMemberId? */
function agent_manager_chain_includes(PDO $pdo, int $managerId, int $agentMemberId): bool
{
    $st = $pdo->prepare(<<<'SQL'
        WITH RECURSIVE chain AS (
            SELECT member_id, manager_member_id, 0 AS depth
              FROM agent_profiles WHERE member_id = :start
            UNION ALL
            SELECT ap.member_id, ap.manager_member_id, c.depth + 1
              FROM agent_profiles ap JOIN chain c ON ap.member_id = c.manager_member_id
             WHERE c.depth < 20
        )
        SELECT count(*) FROM chain WHERE member_id = :agent AND depth > 0
    SQL);
    $st->execute(['start' => $managerId, 'agent' => $agentMemberId]);
    return (int) $st->fetchColumn() > 0;
}

/** Offices and desks: every active one, with nothing standing between an agent and a home. */
function find_home_location_options(PDO $pdo): array
{
    return $pdo->query("SELECT location_id, name, kind FROM mcp_locations
                          WHERE kind IN ('office', 'desk') AND status = 'active' ORDER BY kind, name")->fetchAll();
}

function find_agent_member_options(PDO $pdo): array
{
    return $pdo->query("SELECT a.agent_member_id AS member_id, a.display_name
                          FROM mcp_agents a
                         WHERE a.status <> 'offboarded' ORDER BY a.display_name")->fetchAll();
}

/** Subagent-kind agents, not offboarded — shared by the hire form's starting roster and the
 *  Roster tab's add picker (db/072: only a subagent may sit on the subagent end). */
function find_subagent_options(PDO $pdo): array
{
    return $pdo->query("SELECT agent_member_id AS member_id, display_name FROM mcp_agents
                          WHERE agent_kind = 'subagent' AND status <> 'offboarded'
                          ORDER BY display_name")->fetchAll();
}

// --------------------------------------------------------------------------
// Roster (agent_subagents, db/072) — one level, enforced by trigger at both ends. Reads go
// through mcp_agent_subagents; writes go to agent_subagents. Live membership only
// (removed_at IS NULL); removal never deletes, so the roster stays auditable.
// --------------------------------------------------------------------------
function find_agent_roster(PDO $pdo, int $orchestratorMemberId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_agent_subagents
                          WHERE orchestrator_member_id = :id AND removed_at IS NULL
                          ORDER BY subagent_name');
    $st->execute(['id' => $orchestratorMemberId]);
    return $st->fetchAll();
}

/** The other side: which orchestrators a subagent currently serves — read-only in the UI,
 *  since membership is managed from the orchestrator's side only. */
function find_agent_orchestrators(PDO $pdo, int $subagentMemberId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_agent_subagents
                          WHERE subagent_member_id = :id AND removed_at IS NULL
                          ORDER BY orchestrator_name');
    $st->execute(['id' => $subagentMemberId]);
    return $st->fetchAll();
}

function find_roster_row(PDO $pdo, int $rosterId): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_agent_subagents WHERE agent_subagent_id = :id');
    $st->execute(['id' => $rosterId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** Refused by the agent_subagents_one_level trigger when either end is the wrong kind, or by
 *  the live-membership unique index when the pair is already on the roster — both are left to
 *  bubble up as PDOException; the endpoint catches and surfaces the trigger's own message. */
function add_agent_subagent(PDO $pdo, int $orchestratorId, int $subagentId, ?string $note, int $by): array
{
    $st = $pdo->prepare('INSERT INTO agent_subagents (orchestrator_member_id, subagent_member_id, note, added_by)
                          VALUES (:o, :s, :note, :by) RETURNING id');
    $st->execute(['o' => $orchestratorId, 's' => $subagentId, 'note' => $note, 'by' => $by]);
    $id = (int) $st->fetchColumn();
    return find_roster_row($pdo, $id) ?? [];
}

/** Sets removed_at; never deletes — the roster's history stays auditable, the same shape
 *  agent_tool_grants uses for revoked_at (db/072's own comment). */
function remove_agent_subagent(PDO $pdo, int $orchestratorId, int $subagentId): bool
{
    $st = $pdo->prepare('UPDATE agent_subagents SET removed_at = now()
                          WHERE orchestrator_member_id = :o AND subagent_member_id = :s AND removed_at IS NULL');
    $st->execute(['o' => $orchestratorId, 's' => $subagentId]);
    return $st->rowCount() > 0;
}

/** Refused by the agent_profiles_kind_change trigger while a live roster depends on the
 *  current kind — left to bubble up as PDOException for the endpoint to surface verbatim. */
function set_agent_kind(PDO $pdo, int $memberId, string $kind): array
{
    $st = $pdo->prepare('UPDATE agent_profiles SET agent_kind = :kind, updated_at = now()
                          WHERE member_id = :id RETURNING member_id');
    $st->execute(['kind' => $kind, 'id' => $memberId]);
    if ($st->fetch() === false) {
        return [];
    }
    return find_agent($pdo, $memberId) ?? [];
}
