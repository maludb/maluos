<?php
declare(strict_types=1);

/**
 * Append one row to the activity stream (db/010_activity_log.sql), the source of the
 * MaluDB activity memory. Logging is not optional — every state change and every screen
 * entry writes a row (see the tech-stack "logging is not optional" rule).
 *
 * @param string      $action     e.g. 'attempt.reschedule', 'auth.login', 'screen.view'
 * @param string|null $entityType e.g. 'exam_attempt'
 * @param int|null    $entityId
 * @param array       $opts       before?, after? (arrays → jsonb), screen?, route?,
 *                                source? ('web'|'assistant'|'mcp'|'cron'), actor_member_id?
 */
function log_activity(
    PDO $pdo,
    string $action,
    ?string $entityType = null,
    ?int $entityId = null,
    array $opts = []
): void {
    try {
        $stmt = $pdo->prepare(<<<'SQL'
            INSERT INTO activity_log
                (actor_member_id, source, action, screen, route, entity_type, entity_id,
                 before, after, request_id, session_id, ip_address, agent_run_id)
            VALUES
                (:actor, :source, :action, :screen, :route, :etype, :eid,
                 :before, :after, :rid, :sid, :ip, :run)
            RETURNING id
        SQL);
        $stmt->execute([
            'actor'  => $opts['actor_member_id'] ?? ($_SESSION['member_id'] ?? null),
            'source' => $opts['source'] ?? default_activity_source(),
            'action' => $action,
            'screen' => $opts['screen'] ?? null,
            'route'  => $opts['route'] ?? request_route(),
            'etype'  => $entityType,
            'eid'    => $entityId,
            'before' => isset($opts['before']) ? json_encode($opts['before'], JSON_THROW_ON_ERROR) : null,
            'after'  => isset($opts['after']) ? json_encode($opts['after'], JSON_THROW_ON_ERROR) : null,
            'rid'    => $opts['request_id'] ?? agent_run_request_id($pdo) ?? request_id(),
            'sid'    => session_id() ?: null,
            'run'    => $opts['agent_run_id'] ?? (function_exists('current_agent_run_id') ? current_agent_run_id() : null),
            'ip'     => PHP_SAPI === 'cli' ? null : client_ip(),
        ]);
        // During an approval replay, the first thing the handler logs IS the executed action.
        $replayId = $GLOBALS['__approval_replay_id'] ?? null;
        if ($replayId !== null && empty($GLOBALS['__approval_replay_logged']) && !str_starts_with($action, 'approval_request.')) {
            $GLOBALS['__approval_replay_logged'] = true;
            note_approval_executed_activity($pdo, (int) $replayId, (int) $stmt->fetchColumn());
        }
    } catch (Throwable $e) {
        // Logging must never break the request; record the failure to the error log.
        error_log('activity_log insert failed: ' . $e->getMessage());
    }
}

/**
 * Where this request came from. A request carrying a signed action token is the assistant
 * (or an agent) acting as the member, not the member clicking — and "who did this, a person
 * or their agent?" is a question the activity memory has to be able to answer.
 */
function default_activity_source(): string
{
    if (function_exists('is_action_authed') && is_action_authed()) {
        // A run token is an agent at work under its own identity; the three-part token is the
        // assistant acting for the person at the keyboard.
        return current_agent_run_id() !== null ? 'agent' : 'assistant';
    }
    return PHP_SAPI === 'cli' ? 'cron' : 'web';
}

/** Convenience: record a screen view. */
function log_screen_view(PDO $pdo, string $screen): void
{
    // The Next.js server marks a real page render with X-Screen-View: 1; a prefetch or a
    // background refresh carries no mark and is not a view. Activity memory cannot be
    // un-polluted, so a JSON read counts only when it says it is one.
    if (wants_json() && ($_SERVER['HTTP_X_SCREEN_VIEW'] ?? '') !== '1') {
        return;
    }
    log_activity($pdo, 'screen.view', null, null, ['screen' => $screen]);
}

/**
 * An agent run has ONE request id for its whole life (agent_runs.request_id): every model call in
 * the prompt ledger and every action the run takes carry it, which is what lets "show me the
 * prompt behind this change" work. It is read from the run the verified token names — never from
 * a header the agent could set.
 */
function agent_run_request_id(PDO $pdo): ?string
{
    static $resolved = false, $id = null;
    if (!$resolved) {
        $resolved = true;
        $runId = function_exists('current_agent_run_id') ? current_agent_run_id() : null;
        if ($runId !== null) {
            $stmt = $pdo->prepare('SELECT request_id FROM agent_runs WHERE id = :id');
            $stmt->execute(['id' => $runId]);
            $found = $stmt->fetchColumn();
            $id = $found === false ? null : (string) $found;
        }
    }
    return $id;
}

/** Stable per-request id for tracing (also used to correlate an assistant turn). */
function request_id(): string
{
    static $id = null;
    if ($id === null) {
        $id = $_SERVER['HTTP_X_REQUEST_ID'] ?? bin2hex(random_bytes(8));
    }
    return $id;
}

function request_route(): string
{
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH) ?: '';
    return trim($method . ' ' . $path);
}
