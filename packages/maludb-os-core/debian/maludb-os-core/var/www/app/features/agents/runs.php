<?php
declare(strict_types=1);

/**
 * Agent runs — PHP's side of the agent runner (docs/build-specs/agent-runtime-hermes.md).
 *
 * PHP never runs an agent. It asks the runner (a localhost service under its own unix user) to,
 * and the runner calls back when the run ends so that the log entry is written HERE: the runner
 * holds no PHP write path and no activity_log grant. Both directions carry RUNNER_KEY.
 */

const AGENT_RUN_INSTRUCTIONS_MAX = 8000;

function runner_key(): string
{
    $k = (string) env('RUNNER_KEY', '');
    if (strlen($k) < 32) {
        throw new RuntimeException('RUNNER_KEY is not configured.');
    }
    return $k;
}

/** @return array{status:int, body:array} One JSON round trip to the runner. status 0 = unreachable. */
function runner_request(string $method, string $path, ?array $body = null): array
{
    $ch = curl_init(rtrim((string) env('RUNNER_URL', 'http://127.0.0.1:8815'), '/') . $path);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 3, CURLOPT_TIMEOUT => 30,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'X-Runner-Key: ' . runner_key()],
    ]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body, JSON_THROW_ON_ERROR));
    }
    $raw = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $decoded = is_string($raw) ? json_decode($raw, true) : null;
    return ['status' => $raw === false ? 0 : $status, 'body' => is_array($decoded) ? $decoded : []];
}

/**
 * Ask the runner to start a run. Returns [run|null, error|null]; the runner refuses (409) an
 * agent that is inactive, has no active version, has no built harness, or is already running.
 */
function start_agent_run(int $agentMemberId, string $instructions, string $trigger, ?int $dutyId, int $requestedBy,
                         ?int $parentRunId = null): array
{
    $r = runner_request('POST', '/runs', [
        'agent_member_id' => $agentMemberId, 'trigger' => $trigger, 'instructions' => $instructions,
        'duty_id' => $dutyId, 'requested_by' => $requestedBy, 'parent_run_id' => $parentRunId,
    ]);
    if ($r['status'] === 202 && isset($r['body']['run_id'])) {
        return [$r['body'], null];
    }
    if ($r['status'] === 0) {
        return [null, 'The agent runner is not reachable — nothing was run.'];
    }
    return [null, (string) ($r['body']['error'] ?? 'The agent runner refused the run.')];
}

/**
 * Which `model_registry.harness` values actually have a harness behind them, asked of the runner
 * (its /health reports `registry.built_keys()`). Null when the runner cannot be reached — the
 * caller must then let the action through rather than refuse on an unanswered question.
 *
 * @return list<string>|null
 */
function built_harnesses(): ?array
{
    static $cached = false;
    static $keys = null;
    if ($cached) {
        return $keys;
    }
    $cached = true;
    $r = runner_request('GET', '/health');
    $keys = ($r['status'] === 200 && is_array($r['body']['harnesses'] ?? null))
        ? array_values(array_filter($r['body']['harnesses'], 'is_string'))
        : null;
    return $keys;
}

/**
 * The refusal that stops an agent being hired onto — or activated on — a model nobody can run.
 * `model_registry.harness` admits five names and only some are built; without this the hire
 * succeeds, the roster shows a working agent, and the truth arrives days later as
 * "No harness is built for 'x' yet" at dispatch. Returns null when there is nothing in the way.
 */
function agent_harness_error(?array $model): ?string
{
    $harness = is_array($model) ? (string) ($model['harness'] ?? '') : '';
    if ($harness === '') {
        return null;
    }
    // A model billed to the owner's Claude subscription (db/164) can run only while the runner's switch is on; the runner says
    // so in /health. Asked and unanswered (runner down) lets it through, as the harness check does.
    if (($model['auth_mode'] ?? 'api_key') === 'claude_subscription') {
        $health = runner_request('GET', '/health');
        if ($health['status'] === 200 && empty($health['body']['subscription'])) {
            return sprintf('%s bills to a Claude subscription, and subscription use is switched off on this install '
                . '(ALLOW_CLAUDE_SUBSCRIPTION and the token in the runner\'s environment). Choose another model.',
                (string) ($model['display_name'] ?? $model['model_key'] ?? 'That model'));
        }
    }
    $built = built_harnesses();
    if ($built === null || in_array($harness, $built, true)) {
        return null;
    }
    return sprintf(
        'No harness is built for %s, so %s could never run. Built: %s. Choose a model on one of those.',
        $harness,
        (string) ($model['display_name'] ?? $model['model_key'] ?? 'that model'),
        $built === [] ? 'none' : implode(', ', $built)
    );
}

function cancel_agent_run(int $runId): ?string
{
    $r = runner_request('POST', '/runs/' . $runId . '/cancel');
    return $r['status'] === 202 ? null : (string) ($r['body']['error'] ?? 'The run could not be cancelled.');
}

function find_agent_run(PDO $pdo, int $runId): ?array
{
    $st = $pdo->prepare('SELECT * FROM agent_runs WHERE id = :id');
    $st->execute(['id' => $runId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** A live, active subagent on this orchestrator's roster, named by member id or by display name. */
function find_roster_subagent(PDO $pdo, int $orchestratorId, string $named): ?array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT m.id AS member_id, m.display_name
          FROM agent_subagents s
          JOIN members m         ON m.id = s.subagent_member_id
          JOIN agent_profiles ap ON ap.member_id = m.id
         WHERE s.orchestrator_member_id = :me AND s.removed_at IS NULL
           AND m.status = 'active' AND ap.status = 'active'
           AND (m.id::text = :named OR lower(m.display_name) = lower(:named))
         ORDER BY m.id LIMIT 1
    SQL);
    $st->execute(['me' => $orchestratorId, 'named' => $named]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** @return string[] who this orchestrator may delegate to — said back when it names someone else */
function roster_names(PDO $pdo, int $orchestratorId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT m.display_name FROM agent_subagents s JOIN members m ON m.id = s.subagent_member_id
          JOIN agent_profiles ap ON ap.member_id = m.id
         WHERE s.orchestrator_member_id = :me AND s.removed_at IS NULL AND m.status = 'active' AND ap.status = 'active'
         ORDER BY m.display_name
    SQL);
    $st->execute(['me' => $orchestratorId]);
    return $st->fetchAll(PDO::FETCH_COLUMN);
}
