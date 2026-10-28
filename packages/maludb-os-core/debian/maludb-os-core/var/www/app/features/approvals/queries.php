<?php
declare(strict_types=1);

/**
 * Approval requests — data access (docs/build-specs/approvals-execution.md).
 * Every state change is one guarded UPDATE: the WHERE clause names the state the row must be in,
 * so two people deciding at once cannot both win.
 */

function find_approval_request(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT r.*, rm.display_name AS requested_by_name, rm.member_kind AS requested_by_kind,
               am.display_name AS approver_name, am.member_kind AS approver_kind, p.name AS policy_name,
               ap.manager_member_id AS requester_manager_id
          FROM approval_requests r
          JOIN members rm ON rm.id = r.requested_by_member_id
          JOIN members am ON am.id = r.approver_member_id
          LEFT JOIN approval_policies p ON p.id = r.policy_id
          LEFT JOIN agent_profiles ap ON ap.member_id = r.requested_by_member_id
         WHERE r.id = :id
    SQL);
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** The queue as one member sees it: what waits for them, or what they asked for. */
function approvals_for_member(PDO $pdo, int $memberId, string $role, ?string $status, int $limit = 100): array
{
    $column = $role === 'requester' ? 'r.requested_by_member_id' : 'r.approver_member_id';
    $st = $pdo->prepare(<<<SQL
        SELECT r.*, rm.display_name AS requested_by_name, rm.member_kind AS requested_by_kind,
               am.display_name AS approver_name, am.member_kind AS approver_kind, p.name AS policy_name
          FROM approval_requests r
          JOIN members rm ON rm.id = r.requested_by_member_id
          JOIN members am ON am.id = r.approver_member_id
          LEFT JOIN approval_policies p ON p.id = r.policy_id
         WHERE {$column} = :me AND (:status::text IS NULL OR r.status = :status)
         ORDER BY (r.status = 'pending') DESC, r.created_at DESC
         LIMIT :lim
    SQL);
    $st->bindValue('me', $memberId, PDO::PARAM_INT);
    $st->bindValue('status', $status);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

/** A request nobody decided in time. True when this call is what expired it. */
function expire_approval_if_due(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare("UPDATE approval_requests SET status = 'expired'
                          WHERE id = :id AND status = 'pending' AND expires_at <= now()");
    $st->execute(['id' => $id]);
    return $st->rowCount() === 1;
}

/** pending -> approved | rejected | cancelled. False when the row was no longer pending. */
function decide_approval_request(PDO $pdo, int $id, string $status, int $decidedBy, ?string $note): bool
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE approval_requests
           SET status = :status, decided_by = :by, decided_at = now(), decision_note = :note
         WHERE id = :id AND status = 'pending' AND expires_at > now()
    SQL);
    $st->execute(['status' => $status, 'by' => $decidedBy, 'note' => $note, 'id' => $id]);
    return $st->rowCount() === 1;
}

/** The one-use claim a replay must win before the paused action may run. */
function claim_approval_execution(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare("UPDATE approval_requests SET executed_at = now()
                          WHERE id = :id AND status = 'approved' AND executed_at IS NULL");
    $st->execute(['id' => $id]);
    return $st->rowCount() === 1;
}

function finish_approval_execution(PDO $pdo, int $id, bool $ok, ?string $error): void
{
    $st = $pdo->prepare(<<<'SQL'
        UPDATE approval_requests
           SET status = :status, execution_error = :error, executed_at = COALESCE(executed_at, now())
         WHERE id = :id AND status = 'approved'
    SQL);
    $st->execute(['status' => $ok ? 'executed' : 'execution_failed', 'error' => $error, 'id' => $id]);
}

/** Called by log_activity() for the first row written during a replay. */
function note_approval_executed_activity(PDO $pdo, int $id, int $activityId): void
{
    $st = $pdo->prepare('UPDATE approval_requests SET executed_activity_id = :a
                          WHERE id = :id AND executed_activity_id IS NULL');
    $st->execute(['a' => $activityId, 'id' => $id]);
}

/**
 * The nearest active HUMAN up an agent's management chain — the same walk create_approval_request()
 * makes to choose an approver. An agent's direct manager is often an orchestrator agent, who may
 * neither decide nor withdraw a request.
 */
function nearest_human_manager(PDO $pdo, int $agentMemberId): ?int
{
    $st = $pdo->prepare(<<<'SQL'
        WITH RECURSIVE chain AS (
            SELECT ap.manager_member_id AS id, 1 AS depth FROM agent_profiles ap WHERE ap.member_id = :agent
            UNION ALL
            SELECT ap.manager_member_id, c.depth + 1
              FROM chain c JOIN agent_profiles ap ON ap.member_id = c.id
             WHERE c.depth < 8)
        SELECT c.id FROM chain c JOIN members m ON m.id = c.id
         WHERE m.member_kind = 'human' AND m.status = 'active'
         ORDER BY c.depth LIMIT 1
    SQL);
    $st->execute(['agent' => $agentMemberId]);
    $id = $st->fetchColumn();
    return $id === false ? null : (int) $id;
}

/**
 * A run that stopped for approval is waiting while ANY request it raised is still pending; it is
 * no longer waiting once the last of them is decided, withdrawn or expired. The run did its part;
 * what became of each request is on the request. Until 2026-09-27 only the one request the run
 * was recorded as paused ON released it — a run that asked twice stayed "paused" for good after
 * the other request was decided (Sasha, runs 57/62/77/92).
 */
function settle_paused_run(PDO $pdo, array $request): void
{
    if ($request['agent_run_id'] === null) {
        return;
    }
    settle_paused_runs($pdo, (int) $request['agent_run_id']);
}

/** Release every run (or the one run) paused for approval that has no pending request left. */
function settle_paused_runs(PDO $pdo, ?int $runId = null): int
{
    $st = $pdo->prepare("UPDATE agent_runs r SET status = 'succeeded', updated_at = now()
                          WHERE r.status = 'awaiting_approval' AND (:run::bigint IS NULL OR r.id = :run2)
                            AND NOT EXISTS (SELECT 1 FROM approval_requests q WHERE q.agent_run_id = r.id AND q.status = 'pending')");
    $st->execute(['run' => $runId, 'run2' => $runId]);
    return $st->rowCount();
}

/**
 * Expire every pending request whose time has passed and release the runs that waited on them.
 * Expiry used to happen only when someone opened the request: a request nobody opened stayed
 * "pending" for ever and its run stayed "paused for an approval" on the dashboard. The screens
 * that show that state (home, the agent's page, the queue) sweep first; the cron job sweeps for
 * everyone. Returns the requests this call expired (id, summary, agent_run_id, requested_by_member_id).
 */
function sweep_due_approvals(PDO $pdo, ?int $requestedBy = null): array
{
    $st = $pdo->prepare("UPDATE approval_requests SET status = 'expired', updated_at = now()
                          WHERE status = 'pending' AND expires_at <= now()
                            AND (:who::bigint IS NULL OR requested_by_member_id = :who2)
                      RETURNING id, summary, agent_run_id, requested_by_member_id");
    $st->execute(['who' => $requestedBy, 'who2' => $requestedBy]);
    $expired = $st->fetchAll();
    foreach ($expired as $r) {
        log_activity($pdo, 'approval_request.expire', 'approval_request', (int) $r['id'], [
            'source' => PHP_SAPI === 'cli' ? 'cron' : 'web',
            'after' => ['summary' => $r['summary'], 'agent_run_id' => $r['agent_run_id'] !== null ? (int) $r['agent_run_id'] : null],
        ]);
    }
    settle_paused_runs($pdo);
    return $expired;
}

/**
 * What an agent is waiting on: its runs paused for approval, each with the pending requests it
 * raised, joined the way find_approval_request() joins so present_approval_request() applies.
 * The caller's right to see the agent is the page's; a run with no pending request left is
 * released by the sweep before this is read.
 */
function find_paused_runs_for_agent(PDO $pdo, int $agentMemberId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT r.*, rm.display_name AS requested_by_name, rm.member_kind AS requested_by_kind,
               am.display_name AS approver_name, am.member_kind AS approver_kind, p.name AS policy_name,
               run.started_at AS run_started_at, run.trigger AS run_trigger, du.name AS run_duty_name
          FROM approval_requests r
          JOIN agent_runs run ON run.id = r.agent_run_id AND run.status = 'awaiting_approval'
          LEFT JOIN agent_duties du ON du.id = run.duty_id
          JOIN members rm ON rm.id = r.requested_by_member_id
          JOIN members am ON am.id = r.approver_member_id
          LEFT JOIN approval_policies p ON p.id = r.policy_id
         WHERE r.requested_by_member_id = :agent AND r.status = 'pending'
         ORDER BY run.started_at, r.created_at
    SQL);
    $st->execute(['agent' => $agentMemberId]);
    $runs = [];
    foreach ($st->fetchAll() as $r) {
        $runId = (int) $r['agent_run_id'];
        $runs[$runId] ??= ['id' => $runId, 'started_at' => $r['run_started_at'], 'trigger' => $r['run_trigger'],
                           'duty_name' => $r['run_duty_name'], 'requests' => []];
        $runs[$runId]['requests'][] = $r;
    }
    return array_values($runs);
}
