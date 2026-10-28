<?php
declare(strict_types=1);

/** Skills — data access (docs/build-specs/agent-skills.md). State changes are guarded UPDATEs. */

const SKILL_SCOPES = ['org', 'department', 'role', 'agent', 'application'];

function find_skill_assignment(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM skill_assignments WHERE id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function list_skill_assignments(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT a.*, d.name AS department_name, m.display_name AS agent_name, by_m.display_name AS assigned_by_name,
               ap.name AS application_name, coalesce(k.kind, 'skill') AS kind
          FROM skill_assignments a
          LEFT JOIN skill_kinds k ON k.skill_name = a.skill_name
          LEFT JOIN departments d ON d.id = a.department_id
          LEFT JOIN applications ap ON ap.id = a.application_id
          LEFT JOIN members m     ON m.id = a.agent_member_id
          LEFT JOIN members by_m  ON by_m.id = a.assigned_by
         WHERE a.revoked_at IS NULL
         ORDER BY a.skill_name, a.scope_kind, a.id
    SQL)->fetchAll();
}

/** @return array{0:?array,1:?string} [row, error] — the unique index makes a duplicate a sentence, not a 500 */
function create_skill_assignment(PDO $pdo, array $f, int $by): array
{
    try {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO skill_assignments (skill_name, pinned_bundle_hash, scope_kind, department_id, role_key,
                                           agent_member_id, application_id, note, assigned_by)
            VALUES (:name, :pin, :scope, :dept, :role, :agent, :app, :note, :by) RETURNING *
        SQL);
        $st->execute(['name' => $f['skill_name'], 'pin' => $f['pinned_bundle_hash'] ?? null, 'scope' => $f['scope_kind'],
                      'dept' => $f['department_id'] ?? null, 'role' => $f['role_key'] ?? null, 'agent' => $f['agent_member_id'] ?? null,
                      'app' => $f['application_id'] ?? null, 'note' => $f['note'], 'by' => $by]);
        return [$st->fetch(), null];
    } catch (PDOException $ex) {
        if ($ex->getCode() === '23505') {
            return [null, 'That skill is already assigned there.'];
        }
        error_log('skill assignment failed: ' . $ex->getMessage());
        return [null, 'The assignment could not be saved.'];
    }
}

function revoke_skill_assignment(PDO $pdo, int $id, int $by): bool
{
    $st = $pdo->prepare('UPDATE skill_assignments SET revoked_at = now(), revoked_by = :by WHERE id = :id AND revoked_at IS NULL');
    $st->execute(['id' => $id, 'by' => $by]);
    return $st->rowCount() === 1;
}

function find_skill_proposal(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT p.*, m.display_name AS agent_name, dm.display_name AS decided_by_name
          FROM skill_proposals p
          JOIN members m ON m.id = p.agent_member_id
          LEFT JOIN members dm ON dm.id = p.decided_by
         WHERE p.id = :id
    SQL);
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function list_skill_proposals(PDO $pdo, ?string $status): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT p.*, m.display_name AS agent_name, dm.display_name AS decided_by_name
          FROM skill_proposals p
          JOIN members m ON m.id = p.agent_member_id
          LEFT JOIN members dm ON dm.id = p.decided_by
         WHERE (:status::text IS NULL OR p.status = :status)
         ORDER BY (p.status = 'proposed') DESC, p.created_at DESC
         LIMIT 200
    SQL);
    $st->execute(['status' => $status]);
    return $st->fetchAll();
}

function find_skill_proposal_by_hash(PDO $pdo, string $name, string $hash): ?array
{
    $st = $pdo->prepare('SELECT * FROM skill_proposals WHERE skill_name = :n AND bundle_hash = :h');
    $st->execute(['n' => $name, 'h' => $hash]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function create_skill_proposal(PDO $pdo, array $f): int
{
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO skill_proposals (agent_member_id, agent_run_id, skill_name, bundle_hash, parent_bundle_hash,
                                     maludb_skill_id, file_count, has_scripts, scan_findings, skill_markdown, parent_markdown)
        VALUES (:agent, :run, :name, :hash, :parent_hash, :skill_id, :files, false, :findings, :md, :parent_md)
        RETURNING id
    SQL);
    $st->execute(['agent' => $f['agent_member_id'], 'run' => $f['agent_run_id'], 'name' => $f['skill_name'],
                  'hash' => $f['bundle_hash'], 'parent_hash' => $f['parent_bundle_hash'], 'skill_id' => $f['maludb_skill_id'],
                  'files' => $f['file_count'], 'findings' => json_encode($f['scan_findings'], JSON_THROW_ON_ERROR),
                  'md' => $f['skill_markdown'], 'parent_md' => $f['parent_markdown']]);
    return (int) $st->fetchColumn();
}

/** proposed -> approved | rejected. False when someone else decided first. */
function decide_skill_proposal(PDO $pdo, int $id, string $status, int $by, ?string $note): bool
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE skill_proposals SET status = :status, decided_by = :by, decided_at = now(), decision_note = :note
         WHERE id = :id AND status = 'proposed'
    SQL);
    $st->execute(['status' => $status, 'by' => $by, 'note' => $note, 'id' => $id]);
    return $st->rowCount() === 1;
}

/** Who may assign into this scope: HR anywhere; a dept-admin inside the departments they administer. */
function can_assign_skill(PDO $pdo, string $scope, ?int $departmentId, ?int $agentMemberId): bool
{
    if (is_agent_member()) {
        return false;
    }
    if (is_super_admin() || has_module($pdo, 'hr')) {
        return true;
    }
    if ($scope === 'application') {
        // mod:applications, no admin fallback — whoever may change the registry may say what
        // skills an application carries (the same test as can_edit_applications()).
        $st = $pdo->query("SELECT app_has_module('applications')");
        return (bool) $st->fetchColumn();
    }
    if ($scope === 'department') {
        return is_admin_of_department($pdo, $departmentId);
    }
    if ($scope === 'agent' && $agentMemberId !== null) {
        return can_admin_member($pdo, $agentMemberId);
    }
    return false;                                       // org and role reach across departments: HR only
}

/** Who may decide a proposal: HR, or the author's nearest human manager. Never an agent. */
function can_decide_skill_proposal(PDO $pdo, array $proposal): bool
{
    if (is_agent_member()) {
        return false;
    }
    if (is_super_admin() || has_module($pdo, 'hr')) {
        return true;
    }
    require_once dirname(__DIR__) . '/approvals/queries.php';
    return nearest_human_manager($pdo, (int) $proposal['agent_member_id']) === (int) current_member_id();
}

/** What the assign form offers: `{id, name}` lists, already limited to what exists and is live. */
function skill_assign_options(PDO $pdo): array
{
    $departments = $pdo->query("SELECT id, name FROM departments WHERE archived_at IS NULL ORDER BY name")->fetchAll();
    $agents = $pdo->query(<<<'SQL'
        SELECT m.id, m.display_name AS name, ap.role_key FROM members m JOIN agent_profiles ap ON ap.member_id = m.id
         WHERE m.member_kind = 'agent' AND ap.status = 'active' ORDER BY m.display_name
    SQL)->fetchAll();
    $roles = $pdo->query("SELECT DISTINCT role_key FROM agent_profiles WHERE role_key IS NOT NULL AND role_key <> '' ORDER BY 1")->fetchAll(PDO::FETCH_COLUMN);
    return [
        'departments' => array_map(static fn (array $d): array => ['id' => (int) $d['id'], 'name' => $d['name']], $departments),
        'agents' => array_map(static fn (array $a): array => ['id' => (int) $a['id'], 'name' => $a['name']], $agents),
        'roles' => array_values(array_map('strval', $roles)),
    ];
}
