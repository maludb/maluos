<?php
declare(strict_types=1);

/** AI Ops — what the handlers share: refusing, and the eval gates. */

function aiops_refuse(array $errors, int $status = 422): never
{
    emit_action_status(false, ['errors' => $errors]);
    if ($status === 422) {
        respond_invalid($errors);
    }
    json_error($status === 404 ? 'not_found' : ($status === 403 ? 'forbidden' : 'refused'), $errors[0] ?? 'That could not be done.', $status);
}

/**
 * Eval authoring and grading are people's work: an agent that could write or read its own cases
 * could learn the test (manifest: "the endpoints refuse agent callers"). $agentToo admits whoever
 * may see the set's agent — its manager, its department's admin — for the actions the manifest
 * words "mod:evals, agent's manager".
 */
function aiops_require_evals(PDO $pdo, ?int $agentMemberId = null, bool $agentToo = false, bool $agentMayRun = false): void
{
    require_login();
    if (is_agent_member()) {
        // Scheduled evals are allowed (owner, 2026-09-27): an agent granted eval_run_start — the Auditor —
        // may START a run; the grant was checked at the Actions MCP before this request was relayed here.
        // Writing, changing or grading cases stays with people.
        if ($agentMayRun && is_action_authed()) {
            return;
        }
        aiops_refuse(['Evals are written and graded by people — an agent may only start a run, and only with that tool granted.'], 403);
    }
    if (has_module_grant('evals') || ($agentToo && aiops_can_see_agent($pdo, $agentMemberId))) {
        return;
    }
    aiops_refuse(['This needs the Evals module' . ($agentToo ? ', or to be the agent\'s manager.' : '.')], 403);
}

/** The set a write names — visible through mcp_eval_sets, else "not found". */
function aiops_eval_set(PDO $pdo, string $param = 'eval_set'): array
{
    $id = request_integer($param);
    $set = $id !== null ? find_eval_set($pdo, $id) : null;
    if ($set === null) {
        aiops_refuse(['Eval set not found.'], 404);
    }
    return $set;
}

/** Free text a person typed for a case's input / expected answer, kept as jsonb {"text": …}; valid JSON is kept as it is. */
function eval_text_to_json(string $text): string
{
    $trim = trim($text);
    if ($trim !== '' && ($trim[0] === '{' || $trim[0] === '[') && json_decode($trim) !== null) {
        return $trim;
    }
    return (string) json_encode(['text' => $text], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
}
