<?php
declare(strict_types=1);

/**
 * Business home presenters. Whitelists, mirrored by web/lib/schemas/home.ts
 * (docs/react-migration-plan.md, "Presenters, never raw rows").
 */

/** The four count tiles (home_counts()) — already integers, named one by one all the same. */
function present_home_counts(array $c): array
{
    $keys = ['locations', 'offices', 'desks', 'departments', 'department_members', 'active_agents',
             'candidate_agents', 'suspended_agents', 'applications', 'builtin_applications',
             'pending_approvals', 'pending_approvals_others'];
    $out = [];
    foreach ($keys as $key) {
        $out[$key] = (int) ($c[$key] ?? 0);
    }
    return $out;
}

/**
 * What an agent is doing right now, as [tone, icon, headline, detail] — the same decision
 * app/views/home/partials/agent-cards.php makes, from the freshest source there is. Times are
 * formatted here, in the viewer's zone, so both front ends read identically. Nothing invents a
 * state: an agent with no run, no trail and no duty is said to have done nothing yet.
 */
function home_agent_activity(array $a, string $viewerTz): array
{
    $triggerLabels = [
        'duty' => 'a scheduled duty', 'location_task' => 'a task from another location',
        'assistant' => 'the assistant', 'chat' => 'a chat', 'eval' => 'an eval', 'manual' => 'a person',
    ];
    $run = (string) ($a['run_status'] ?? '');
    $doing = trim((string) ($a['run_duty_name'] ?? ''))
        ?: ($triggerLabels[(string) ($a['run_trigger'] ?? '')] ?? 'work');

    if ($run === 'running') {
        return ['success', 'feather-activity', 'Working now',
                $doing . ', since ' . format_ts($a['run_started_at'], $viewerTz, 'g:i A')];
    }
    if ($run === 'awaiting_approval') {
        $forMe = (int) ($a['pending_for_me'] ?? 0);
        $pending = (int) ($a['pending_requests'] ?? 0);
        $detail = $forMe > 0 ? ($forMe === 1 ? 'One request waits for your decision' : "{$forMe} requests wait for your decision")
            : ($pending > 0 ? ($pending === 1 ? 'One request waits for its approver' : "{$pending} requests wait for their approver")
            : 'Part-way through ' . $doing);
        return ['warning', 'feather-pause-circle', 'Paused for an approval', $detail . ' — open the agent to release it'];
    }
    if ($run !== '') {
        [$tone, $icon, $word] = match ($run) {
            'failed' => ['danger', 'feather-alert-triangle', 'failed'],
            'cancelled' => ['secondary', 'feather-x-circle', 'was cancelled'],
            default => ['secondary', 'feather-check-circle', 'finished'],
        };
        return [$tone, $icon, 'Last run ' . $word,
                $doing . ' · ' . format_ts($a['run_finished_at'] ?? $a['run_started_at'], $viewerTz, 'M j, g:i A')];
    }
    if (($a['last_action'] ?? null) !== null) {
        return ['info', 'feather-edit-3', (string) $a['last_action'],
                'Last acted ' . format_ts($a['last_action_at'], $viewerTz, 'M j, g:i A')];
    }
    if (($a['next_duty_at'] ?? null) !== null) {
        return ['secondary', 'feather-clock', 'Next: ' . (string) $a['next_duty_name'],
                'Due ' . format_ts($a['next_duty_at'], $viewerTz, 'M j, g:i A')];
    }
    return match ((string) ($a['status'] ?? '')) {
        'candidate' => ['warning', 'feather-user-plus', 'Not hired yet', 'A candidate does no work until it is hired'],
        'suspended' => ['dark', 'feather-slash', 'Suspended',
                        ($a['suspended_at'] ?? null) !== null
                            ? 'Since ' . format_ts($a['suspended_at'], $viewerTz, 'M j, Y') : 'Doing nothing until reinstated'],
        default => ['secondary', 'feather-moon', 'Nothing recorded yet', 'The runner arrives with AI ops (phase 5)'],
    };
}

/** One agent card on the business home (home_agents()). Needs agents/render.php for the initials. */
function present_home_agent(array $a, string $viewerTz): array
{
    [$tone, $icon, $headline, $detail] = home_agent_activity($a, $viewerTz);
    $picture = trim((string) ($a['profile_pic_url'] ?? ''));
    return [
        'id' => (int) $a['agent_member_id'],
        'display_name' => (string) $a['display_name'],
        'initials' => agent_initials((string) ($a['display_name'] ?? '')),
        'picture_url' => $picture !== '' ? $picture : null,
        'job_title' => ($a['job_title'] ?? '') !== '' ? $a['job_title'] : null,
        // The profile description (agent_profiles.description): what the agent is, in the card.
        'description' => trim((string) ($a['description'] ?? '')) !== '' ? trim((string) $a['description']) : null,
        'status' => (string) ($a['status'] ?? ''),
        'department_name' => ($a['department_name'] ?? '') !== '' ? $a['department_name'] : null,
        // Click-around step 2: the department's id and the run the activity line speaks of.
        'department_id' => isset($a['department_id']) ? (int) $a['department_id'] : null,
        'run_id' => isset($a['run_id']) ? (int) $a['run_id'] : null,
        'model_key' => ($a['model_key'] ?? '') !== '' ? $a['model_key'] : null,
        'model_id' => isset($a['model_id']) ? (int) $a['model_id'] : null,
        'activity' => ['tone' => $tone, 'icon' => $icon, 'headline' => $headline, 'detail' => $detail],
    ];
}
