<?php
declare(strict_types=1);

/**
 * Personal assistants, department leads and the orchestrator tree — the screens' side
 * (docs/build-specs/assistants-and-messaging.md §7 and §9; db/154–157).
 */
require_once dirname(__DIR__) . '/agents/render.php';
agents_require_files();

/** What a department lead is given (tools on the kernel's own endpoints, by name). */
const LEAD_TOOLS = [
    'Actions MCP' => ['agent_delegate', 'message_send', 'message_done', 'escalation_raise'],
    'Records MCP' => ['inbox_read', 'thread_read', 'find_agents'],
];

// ---- the tree -------------------------------------------------------------------------------------------

/**
 * Every agent in a tree, and the people assistants serve: [{id, name, kind, principal_id, principal_name,
 * parent_id, departments, status}], ordered for display (parents before children).
 */
function org_nodes(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT m.id, m.display_name AS name, p.agent_kind AS kind, p.status, p.principal_member_id AS principal_id,
               pm.display_name AS principal_name,
               (SELECT s.orchestrator_member_id FROM agent_subagents s
                 WHERE s.subagent_member_id = m.id AND s.removed_at IS NULL ORDER BY s.id LIMIT 1) AS parent_id,
               (SELECT string_agg(d.name::text, ', ' ORDER BY dm.is_primary DESC, d.name) FROM department_members dm
                  JOIN departments d ON d.id = dm.department_id WHERE dm.member_id = m.id AND dm.left_at IS NULL) AS departments
          FROM agent_profiles p
          JOIN members m ON m.id = p.member_id
          LEFT JOIN members pm ON pm.id = p.principal_member_id
         WHERE p.status <> 'offboarded' AND m.status = 'active'
           AND (p.agent_kind = 'orchestrator' OR p.principal_member_id IS NOT NULL
                OR EXISTS (SELECT 1 FROM agent_subagents s WHERE s.subagent_member_id = m.id AND s.removed_at IS NULL))
         ORDER BY m.display_name
    SQL)->fetchAll();
}

// ---- proposed leads ---------------------------------------------------------------------------------------

/** The model a new lead runs on: the one most live orchestrators use, else the first active model. */
function default_lead_model_id(PDO $pdo): ?int
{
    $id = $pdo->query("SELECT p.model_id FROM agent_profiles p JOIN model_registry r ON r.id = p.model_id AND r.status = 'active'
                        WHERE p.agent_kind = 'orchestrator' AND p.status = 'active'
                        GROUP BY p.model_id ORDER BY count(*) DESC, p.model_id LIMIT 1")->fetchColumn();
    if ($id === false) {
        $id = $pdo->query("SELECT id FROM model_registry WHERE status = 'active' ORDER BY id LIMIT 1")->fetchColumn();
    }
    return $id === false ? null : (int) $id;
}

/** The personal assistant whose person runs this department (a super-admin runs all), or null. */
function assistant_over_department(PDO $pdo, int $departmentId): ?int
{
    $st = $pdo->prepare("SELECT p.member_id FROM agent_profiles p JOIN members m ON m.id = p.member_id
                          WHERE p.principal_member_id IS NOT NULL AND p.status = 'active' AND m.status = 'active'
                            AND :d = ANY (app_agent_reach_department_ids(p.member_id))
                          ORDER BY (SELECT business_role FROM members WHERE id = p.principal_member_id) = 'super_admin', p.member_id
                          LIMIT 1");
    $st->execute(['d' => $departmentId]);
    $id = $st->fetchColumn();
    return $id === false ? null : (int) $id;
}

/**
 * File a proposal for every department that needs a lead and has no open proposal: a standing
 * department, or one with active agents in it, where no orchestrator (other than a personal
 * assistant) works. Answers the proposals filed now.
 */
function propose_missing_leads(PDO $pdo): array
{
    $departments = $pdo->query(<<<'SQL'
        SELECT d.id, d.name::text AS name, d.description, d.handbook_markdown
          FROM departments d
         WHERE d.archived_at IS NULL
           AND (d.is_system OR EXISTS (SELECT 1 FROM department_members dm JOIN agent_profiles p ON p.member_id = dm.member_id
                                        WHERE dm.department_id = d.id AND dm.left_at IS NULL AND p.status = 'active'
                                          AND p.principal_member_id IS NULL))
           AND NOT EXISTS (SELECT 1 FROM department_members dm JOIN agent_profiles p ON p.member_id = dm.member_id
                            WHERE dm.department_id = d.id AND dm.left_at IS NULL AND p.status = 'active'
                              AND p.agent_kind = 'orchestrator' AND p.principal_member_id IS NULL)
           AND NOT EXISTS (SELECT 1 FROM agent_lead_proposals x WHERE x.department_id = d.id AND x.status = 'proposed')
         ORDER BY d.name
    SQL)->fetchAll();
    $model = default_lead_model_id($pdo);
    $filed = [];
    foreach ($departments as $d) {
        $st = $pdo->prepare("SELECT dm.member_id FROM department_members dm JOIN agent_profiles p ON p.member_id = dm.member_id
                              WHERE dm.department_id = :d AND dm.left_at IS NULL AND p.status = 'active'
                                AND p.agent_kind = 'subagent' AND p.principal_member_id IS NULL ORDER BY dm.member_id");
        $st->execute(['d' => (int) $d['id']]);
        $roster = array_map('intval', $st->fetchAll(PDO::FETCH_COLUMN));
        $parent = assistant_over_department($pdo, (int) $d['id']);
        $name = $d['name'] . ' Lead';
        $st = $pdo->prepare('INSERT INTO agent_lead_proposals (department_id, name, job_description, roster_member_ids, parent_member_id, model_id)
                             VALUES (:d, :n, :j, CAST(:r AS bigint[]), :p, :m) RETURNING id');
        $st->execute(['d' => (int) $d['id'], 'n' => $name, 'j' => lead_job_description($pdo, $d, $parent),
                      'r' => '{' . implode(',', $roster) . '}', 'p' => $parent, 'm' => $model]);
        $id = (int) $st->fetchColumn();
        log_activity($pdo, 'agent_lead.propose', 'department', (int) $d['id'], ['after' => ['proposal_id' => $id, 'name' => $name, 'roster' => $roster]]);
        $filed[] = $id;
    }
    return $filed;
}

function lead_job_description(PDO $pdo, array $department, ?int $parentId): string
{
    $parent = $person = null;
    if ($parentId !== null) {
        $st = $pdo->prepare('SELECT m.display_name, pm.display_name AS person FROM agent_profiles p JOIN members m ON m.id = p.member_id
                               LEFT JOIN members pm ON pm.id = p.principal_member_id WHERE p.member_id = :id');
        $st->execute(['id' => $parentId]);
        [$parent, $person] = array_values($st->fetch() ?: [null, null]);
    }
    $dept = (string) $department['name'];
    $above = $parent !== null ? "{$parent}, the personal assistant of {$person}" : 'the business';
    $about = trim((string) ($department['description'] ?? ''));
    return "You are the lead orchestrator of {$dept}" . ($about !== '' ? " — {$about}" : '') . ".\n\n"
        . "Work for {$dept} reaches you from {$above}, and from the people of the department. For each piece:\n"
        . "1. Decide which specialist on your roster should do it, and hand it over with agent_delegate: complete instructions (they start knowing nothing of your conversation), the department, and a one-sentence reason.\n"
        . "2. Follow it through: when the result comes back, check it answers what was asked.\n"
        . "3. Report results, open questions and anything " . ($person ?? 'the owner') . " should know to " . ($parent ?? 'your manager')
        . " with message_send, on the thread the work came on. Keep it short: what was done, what was found, what waits on a decision.\n\n"
        . "When nobody on your roster can do something, say so to " . ($parent ?? 'your manager') . " rather than doing it yourself. "
        . "Your department's handbook, below, says how {$dept} works; follow it.";
}

function find_lead_proposal(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT x.*, d.name::text AS department_name FROM agent_lead_proposals x JOIN departments d ON d.id = x.department_id WHERE x.id = :id');
    $st->execute(['id' => $id]);
    return $st->fetch() ?: null;
}

/** Open proposals, with the names the screen shows. */
function open_lead_proposals(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT x.id, x.name, x.department_id, d.name::text AS department_name, x.job_description, x.proposed_at,
               x.parent_member_id, pm.display_name AS parent_name, r.display_name AS model_name,
               (SELECT coalesce(json_agg(json_build_object('id', m.id, 'name', m.display_name) ORDER BY m.display_name), '[]')
                  FROM members m WHERE m.id = ANY (x.roster_member_ids)) AS roster
          FROM agent_lead_proposals x
          JOIN departments d ON d.id = x.department_id
          LEFT JOIN members pm ON pm.id = x.parent_member_id
          LEFT JOIN model_registry r ON r.id = x.model_id
         WHERE x.status = 'proposed'
         ORDER BY d.name
    SQL)->fetchAll();
}

/**
 * Hire the proposed lead: an orchestrator in the department (its manager the department's, else the
 * hirer), with the lead's tools, the department's specialists on its roster, and placed under the
 * assistant. Answers the new member id. Throws RuntimeException with a sentence when it cannot.
 */
function confirm_lead_proposal(PDO $pdo, array $p, int $by): int
{
    if ($p['status'] !== 'proposed') {
        throw new RuntimeException('That proposal was already ' . $p['status'] . '.');
    }
    if ($p['model_id'] === null) {
        throw new RuntimeException('No model to run a lead on — add one under Settings → Models.');
    }
    $dept = $pdo->prepare('SELECT * FROM departments WHERE id = :id');
    $dept->execute(['id' => (int) $p['department_id']]);
    $d = $dept->fetch();
    $domain = (string) ($pdo->query("SELECT split_part(email, '@', 2) FROM members WHERE member_kind = 'agent' AND email LIKE '%@agents.%' ORDER BY id LIMIT 1")->fetchColumn() ?: 'agents.invalid');
    $slug = trim(preg_replace('/[^a-z0-9]+/', '-', strtolower((string) $p['name'])) ?? 'lead', '-');
    $email = $slug . '@' . $domain;
    for ($n = 2; find_member_by_email($pdo, $email) !== null; $n++) {
        $email = $slug . '-' . $n . '@' . $domain;
    }
    $endpoints = [];
    foreach ($pdo->query("SELECT e.id, e.name FROM application_endpoints e JOIN applications a ON a.id = e.application_id
                           WHERE a.name = 'Business OS' AND e.kind = 'mcp'")->fetchAll() as $e) {
        $endpoints[$e['name']] = (int) $e['id'];
    }
    $tools = [];
    foreach (LEAD_TOOLS as $endpoint => $names) {
        foreach ($names as $name) {
            if (isset($endpoints[$endpoint])) {
                $tools[] = ['application_endpoint_id' => $endpoints[$endpoint], 'tool_name' => $name, 'constraints' => []];
            }
        }
    }
    $agent = hire_agent($pdo, [
        'email' => $email, 'name' => (string) $p['name'], 'job_title' => 'Lead orchestrator, ' . $p['department_name'],
        'description' => 'Leads ' . $p['department_name'] . ': takes its work from the assistant above it, hands each piece to a specialist, reports back.',
        'department_id' => (int) $p['department_id'],
        'manager_member_id' => $d['manager_member_id'] !== null ? (int) $d['manager_member_id'] : $by,
        'model_id' => (int) $p['model_id'], 'monthly_budget_amount' => '10.00', 'budget_currency' => 'USD',
        'home_location_id' => $d['home_location_id'] !== null ? (int) $d['home_location_id'] : null,
        'role_key' => 'department_lead', 'agent_kind' => 'orchestrator', 'phone_number' => null,
        'job_description' => (string) $p['job_description'], 'parameters' => [], 'tools' => $tools, 'duties' => [],
    ], $by);
    $memberId = (int) $agent['agent_member_id'];
    log_activity($pdo, 'agent.hire', 'member', $memberId, ['after' => ['name' => $p['name'], 'department' => $p['department_name'],
        'lead_proposal_id' => (int) $p['id'], 'tools' => count($tools)]]);
    foreach (array_filter(explode(',', trim((string) $p['roster_member_ids'], '{}')), 'strlen') as $sub) {
        try {
            add_agent_subagent($pdo, $memberId, (int) $sub, 'Specialist in ' . $p['department_name'], $by);
            log_activity($pdo, 'agent_subagent.create', 'member', $memberId, ['after' => ['subagent_member_id' => (int) $sub]]);
        } catch (PDOException $ex) {
            error_log('lead roster: ' . $ex->getMessage());                 // the lead stands; a person adds the rest
        }
    }
    if ($p['parent_member_id'] !== null) {
        add_agent_subagent($pdo, (int) $p['parent_member_id'], $memberId, 'Lead of ' . $p['department_name'], $by);
        log_activity($pdo, 'agent_subagent.create', 'member', (int) $p['parent_member_id'], ['after' => ['subagent_member_id' => $memberId]]);
    }
    $pdo->prepare("UPDATE agent_lead_proposals SET status = 'hired', hired_member_id = :m, decided_by = :by, decided_at = now() WHERE id = :id")
        ->execute(['m' => $memberId, 'by' => $by, 'id' => (int) $p['id']]);
    return $memberId;
}

// ---- a person and their assistant -------------------------------------------------------------------------

function my_assistant(PDO $pdo, int $personId): ?array
{
    $st = $pdo->prepare("SELECT m.id, m.display_name AS name, p.agent_kind FROM agent_profiles p JOIN members m ON m.id = p.member_id
                          WHERE p.principal_member_id = :p AND p.status = 'active' AND m.status = 'active' LIMIT 1");
    $st->execute(['p' => $personId]);
    return $st->fetch() ?: null;
}

/** The messages between a person and their assistant, newest last (the latest $limit). */
function assistant_conversation(PDO $pdo, int $personId, int $assistantId, int $limit = 100): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT * FROM (
            SELECT m.id, m.thread_id, t.subject AS thread_subject, m.from_member_id, m.to_member_id, m.kind, m.priority,
                   m.subject, m.body, m.channel, m.delivery_channel, m.delivered_at, m.delivery_error, m.status, m.created_at
              FROM agent_messages m JOIN agent_message_threads t ON t.id = m.thread_id
             WHERE (m.from_member_id = :p AND m.to_member_id = :a) OR (m.from_member_id = :a AND m.to_member_id = :p)
             ORDER BY m.created_at DESC LIMIT :n) x
        ORDER BY created_at
    SQL);
    $st->bindValue('p', $personId, PDO::PARAM_INT);
    $st->bindValue('a', $assistantId, PDO::PARAM_INT);
    $st->bindValue('n', $limit, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

/** What the assistant handed on, newest first: each delegation's agent, department, reason, status and result. */
function assistant_handoffs(PDO $pdo, int $assistantId, int $limit = 30): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT c.id AS run_id, c.agent_member_id, cm.display_name AS agent_name, d.name::text AS department_name,
               c.delegation_reason, c.status, c.started_at, c.finished_at, left(coalesce(c.result, ''), 600) AS result,
               left(c.instructions, 300) AS instructions
          FROM agent_runs c
          JOIN agent_runs p ON p.id = c.parent_run_id AND p.agent_member_id = :a
          JOIN members cm ON cm.id = c.agent_member_id
          LEFT JOIN departments d ON d.id = c.delegated_department_id
         WHERE c.trigger = 'delegation' AND c.agent_member_id <> :a
         ORDER BY c.id DESC LIMIT :n
    SQL);
    $st->bindValue('a', $assistantId, PDO::PARAM_INT);
    $st->bindValue('n', $limit, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}
