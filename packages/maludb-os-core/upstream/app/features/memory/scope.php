<?php
declare(strict_types=1);

/**
 * Who may write where in shared memory (docs/build-specs/agent-memory.md, "Scopes").
 * Everything is resolved from the signed-in member — never from a namespace the caller names.
 */

const MEMORY_TEXT_MAX = 8000;
const MEMORY_SUBJECT_MAX = 200;
const MEMORY_KEY_PATTERN = '/^[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}$/';

/** 'agent:44' | 'member:1' — the same ref the Memory MCP server derives. */
function memory_principal_ref(int $memberId, string $kind): string
{
    return ($kind === 'agent' ? 'agent' : 'member') . ':' . $memberId;
}

/**
 * The namespace a write lands in, or an error sentence.
 * @return array{0:?string,1:?string,2:?int} [namespace, error, department_id]
 */
function memory_write_namespace(PDO $pdo, string $scope, ?int $departmentId): array
{
    $me = (int) current_member_id();
    if ($scope === 'self') {
        return [memory_principal_ref($me, member_kind()), null, null];
    }
    if ($scope === 'department') {
        $mine = my_department_ids($pdo);
        if ($departmentId === null && count($mine) === 1) {
            $departmentId = (int) $mine[0];
        }
        if ($departmentId === null) {
            return [null, 'Say which department — you belong to ' . (count($mine) === 0 ? 'none.' : 'several.'), null];
        }
        if (!in_array($departmentId, array_map('intval', $mine), true)) {
            return [null, 'You can only add to the memory of a department you belong to.', null];
        }
        return ['dept:' . $departmentId, null, $departmentId];
    }
    if ($scope === 'org') {
        // A person needs to administer something to speak for the whole business; an agent may
        // ASK — its request pauses for a person (policy "Agents: writing shared memory").
        if (!is_agent_member() && !is_business_admin()) {
            return [null, 'Only an administrator can add to the whole organisation\'s memory.', null];
        }
        return ['org', null, null];
    }
    return [null, 'Scope must be self, department or org.', null];
}

/** May the signed-in member change $memberId's core memory? Itself, its people-admin, or an agent's human manager. */
function memory_can_set_core(PDO $pdo, int $memberId): bool
{
    if ($memberId === (int) current_member_id()) {
        return true;
    }
    if (is_agent_member()) {
        return false;                       // an agent never edits anyone else's standing memory
    }
    if (can_admin_member($pdo, $memberId)) {
        return true;
    }
    require_once dirname(__DIR__) . '/approvals/queries.php';
    return nearest_human_manager($pdo, $memberId) === (int) current_member_id();
}

function memory_member_kind(PDO $pdo, int $memberId): ?string
{
    $st = $pdo->prepare('SELECT member_kind FROM members WHERE id = :id');
    $st->execute(['id' => $memberId]);
    $kind = $st->fetchColumn();
    return $kind === false ? null : (string) $kind;
}

/**
 * Refuse, with the reason. JSON mode (app/http.php json_mode_finish) takes a refusal's message
 * from the text the handler printed, so the sentences are printed as well as reported. 424, not
 * 502, when MaluDB is the problem: a 5xx is always answered "Something went wrong".
 */
function memory_fail(array $errors, int $status = 422): never
{
    http_response_code($status);
    emit_action_status(false, ['errors' => $errors, 'error' => implode(' ', $errors)]);
    echo e(implode(' ', $errors));
    exit;
}
