<?php
declare(strict_types=1);

/**
 * JSON whitelist for an approval request. request_body and handler_path are deliberately absent:
 * they are what the platform replays, not what an approver reads — `summary`, `parameters`, the
 * amount and who asked are what a decision is made on.
 */
function present_approval_request(array $r): array
{
    return [
        'approval_request_id' => (int) $r['id'],
        'status' => $r['status'],
        'action_key' => $r['action_key'],
        'summary' => $r['summary'],
        'parameters' => json_decode((string) ($r['parameters'] ?? '{}'), true) ?: new stdClass(),
        'amount' => $r['amount'], 'currency' => $r['currency'],
        'entity_type' => $r['entity_type'], 'entity_id' => $r['entity_id'] !== null ? (int) $r['entity_id'] : null,
        'policy' => $r['policy_name'] ?? null,
        'policy_id' => ($r['policy_id'] ?? null) !== null ? (int) $r['policy_id'] : null,
        'requested_by' => ['member_id' => (int) $r['requested_by_member_id'], 'name' => $r['requested_by_name'],
                           'kind' => $r['requested_by_kind']],
        'agent_run_id' => $r['agent_run_id'] !== null ? (int) $r['agent_run_id'] : null,
        'approver' => ['member_id' => (int) $r['approver_member_id'], 'name' => $r['approver_name'], 'kind' => $r['approver_kind'] ?? null],
        'created_at' => $r['created_at'], 'expires_at' => $r['expires_at'],
        'decided_at' => $r['decided_at'], 'decision_note' => $r['decision_note'],
        'executed_at' => $r['executed_at'], 'execution_error' => $r['execution_error'],
        'executed_activity_id' => $r['executed_activity_id'] !== null ? (int) $r['executed_activity_id'] : null,
    ];
}
