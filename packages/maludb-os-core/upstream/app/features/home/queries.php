<?php
declare(strict_types=1);

/**
 * Business home (dashboard) queries — build plan 1.10.
 *
 * The manifest's dashboard is "money this month, pipeline, work due, AI activity", over a
 * chosen period. Every read goes through an mcp_* view, so the dashboard shows exactly what
 * this member — human or agent — is allowed to see, and money is grouped by currency and
 * never summed across currencies.
 *
 * A module whose slice is not built yet has no rows, so its card reports nothing rather than
 * a zero pretending to be a fact: home_module_status() tells the view which is which.
 */

const HOME_PERIODS = ['this_month', 'last_month', 'this_quarter', 'ytd', 'last_12_months'];

/** SQL bounds for a period name. Returns [from, to) as SQL expressions. */
function home_period_bounds(string $period): array
{
    return match ($period) {
        'last_month' => ["date_trunc('month', current_date) - interval '1 month'", "date_trunc('month', current_date)"],
        'this_quarter' => ["date_trunc('quarter', current_date)", "date_trunc('quarter', current_date) + interval '3 months'"],
        'ytd' => ["date_trunc('year', current_date)", "current_date + 1"],
        'last_12_months' => ["current_date - interval '12 months'", "current_date + 1"],
        default => ["date_trunc('month', current_date)", "date_trunc('month', current_date) + interval '1 month'"],
    };
}

function home_period_label(string $period): string
{
    return match ($period) {
        'last_month' => 'last month',
        'this_quarter' => 'this quarter',
        'ytd' => 'this year',
        'last_12_months' => 'the last 12 months',
        default => 'this month',
    };
}

/**
 * Which modules can actually answer yet. A card for an unbuilt module says so instead of
 * showing a confident zero (the registry knows, so the screen does not have to guess).
 */
function home_module_status(): array
{
    static $status = null;
    if ($status !== null) {
        return $status;
    }
    $registry = APP_ROOT . '/mcp/action_registry.json';
    $built = [];
    if (is_readable($registry)) {
        $data = json_decode((string) file_get_contents($registry), true);
        foreach ($data['screens'] ?? [] as $screen) {
            if (!empty($screen['built'])) {
                $built[$screen['section']] = true;
            }
        }
    }
    $status = [
        'contacts' => isset($built['Contacts & CRM']),
        'sales' => isset($built['Sales & invoicing']),
        'expenses' => isset($built['Expenses']),
        'projects' => isset($built['Projects & tasks']),
        'scheduling' => isset($built['Scheduling']),
        'tickets' => isset($built['Tickets']),
        'agents' => isset($built['Agents (HR)']),
    ];
    return $status;
}

// --------------------------------------------------------------------------
// Money this period
// --------------------------------------------------------------------------
/** Invoiced, collected and spent over the period, per currency. */
// --------------------------------------------------------------------------
// Headline counts + recent activity
// --------------------------------------------------------------------------
/**
 * The headline counts: work and decisions waiting, then the shape of the business itself — where it runs (locations),
 * how it is organised (departments), who it employs of the AI workforce (agents) and what
 * it runs on (applications). Every read is through an mcp_* view, so a member sees only
 * what they are allowed to see.
 */
function home_counts(PDO $pdo): array
{
    $locations = $pdo->query("
        SELECT count(*) FILTER (WHERE status = 'active') AS total,
               count(*) FILTER (WHERE status = 'active' AND kind = 'office') AS offices,
               count(*) FILTER (WHERE status = 'active' AND kind = 'desk') AS desks
          FROM mcp_locations")->fetch() ?: [];

    $departments = $pdo->query('
        SELECT count(*) AS total, coalesce(sum(member_count), 0) AS members
          FROM mcp_departments WHERE archived_at IS NULL')->fetch() ?: [];

    $agents = $pdo->query("
        SELECT count(*) FILTER (WHERE status = 'active') AS active,
               count(*) FILTER (WHERE status = 'candidate') AS candidates,
               count(*) FILTER (WHERE status = 'suspended') AS suspended
          FROM mcp_agents")->fetch() ?: [];

    $applications = $pdo->query("
        SELECT count(*) FILTER (WHERE status <> 'retired') AS total,
               count(*) FILTER (WHERE status <> 'retired' AND is_builtin) AS builtin
          FROM mcp_applications")->fetch() ?: [];

    // Decisions waiting: approval requests still pending and not past their expiry. `mine` is what
    // waits for the viewer — exactly what /approvals opens to — and `others` is whatever else
    // mcp_approval_requests lets them see (their own requests, their agents', or the approvals grant).
    $approvals = $pdo->query("
        SELECT count(*) FILTER (WHERE approver_member_id = app_current_member_id()) AS mine,
               count(*) FILTER (WHERE approver_member_id IS DISTINCT FROM app_current_member_id()) AS others
          FROM mcp_approval_requests
         WHERE status = 'pending' AND (expires_at IS NULL OR expires_at > now())")->fetch() ?: [];

    return [
        'pending_approvals' => (int) ($approvals['mine'] ?? 0),
        'pending_approvals_others' => (int) ($approvals['others'] ?? 0),
        'locations' => (int) ($locations['total'] ?? 0),
        'offices' => (int) ($locations['offices'] ?? 0),
        'desks' => (int) ($locations['desks'] ?? 0),
        'departments' => (int) ($departments['total'] ?? 0),
        'department_members' => (int) ($departments['members'] ?? 0),
        'active_agents' => (int) ($agents['active'] ?? 0),
        'candidate_agents' => (int) ($agents['candidates'] ?? 0),
        'suspended_agents' => (int) ($agents['suspended'] ?? 0),
        'applications' => (int) ($applications['total'] ?? 0),
        'builtin_applications' => (int) ($applications['builtin'] ?? 0),
    ];
}

function home_recent_activity(PDO $pdo, int $limit = 8): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT a.action, a.entity_type, a.entity_id, a.created_at, a.source,
               m.display_name AS actor_name, m.member_kind AS actor_kind
          FROM activity_log a
          LEFT JOIN members m ON m.id = a.actor_member_id
         WHERE a.action <> 'screen.view'
         ORDER BY a.id DESC
         LIMIT :lim
    SQL);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}

// --------------------------------------------------------------------------
// The agent workforce
// --------------------------------------------------------------------------
/**
 * One card per agent for the dashboard: who they are, which department they work in, what
 * model they run on and what they are doing right now.
 *
 * "Right now" is answered in the order the truth is freshest, and every source is a lateral so
 * the grid costs one query however many agents there are:
 *   1. a run in flight (`running` / `awaiting_approval`) — the agent is working this second;
 *   2. otherwise its last finished run, which says how the last piece of work ended;
 *   3. otherwise the last thing it did in the activity log (agents act through the same
 *      handlers people do, so they leave the same trail);
 *   4. otherwise the next duty due, which is what it is *about* to do.
 * When all four are empty the card says so in words rather than showing a confident zero —
 * the runner, prompt ledger and agent runs arrive with AI ops (phase 5), so an agent hired
 * today has genuinely done nothing yet, and the card must not imply it is broken.
 *
 * Reads go through the mcp_* views, so a member sees only the agents they are allowed to see;
 * offboarded agents are left out, as they are on the agents list itself.
 */
function home_agents(PDO $pdo, int $limit = 12): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT a.agent_member_id, a.display_name, a.job_title, a.description, a.status, a.agent_kind,
               a.role_key, a.profile_pic_url, a.model_key, a.model_id, a.harness, a.subagent_count,
               a.suspended_at,
               d.department_id,
               d.department_name,
               run.agent_run_id AS run_id,
               run.status       AS run_status,
               run.trigger      AS run_trigger,
               run.started_at   AS run_started_at,
               run.finished_at  AS run_finished_at,
               run.duty_name    AS run_duty_name,
               duty.name        AS next_duty_name,
               duty.next_run_at AS next_duty_at,
               act.action       AS last_action,
               act.created_at   AS last_action_at,
               waits.pending    AS pending_requests,
               waits.for_me     AS pending_for_me,
               count(*) OVER()  AS total_count
          FROM mcp_agents a
          -- What a paused agent waits on, and how much of it waits on the viewer (the base
          -- table: a count, for an agent the viewer may already see).
          LEFT JOIN LATERAL (
              SELECT count(*) AS pending, count(*) FILTER (WHERE q.approver_member_id = :me) AS for_me
                FROM approval_requests q
               WHERE q.requested_by_member_id = a.agent_member_id AND q.status = 'pending'
          ) waits ON true
          -- The department an agent works in is a membership row, not a column: take the
          -- primary one, exactly as the agents list does, so both screens name the same one.
          LEFT JOIN LATERAL (
              SELECT dm.department_id, dm.department_name
                FROM mcp_department_members dm
               WHERE dm.member_id = a.agent_member_id AND dm.left_at IS NULL
               ORDER BY dm.is_primary DESC, dm.department_name
               LIMIT 1
          ) d ON true
          -- An unfinished run outranks a newer finished one: what it is doing beats what it did.
          LEFT JOIN LATERAL (
              SELECT r.agent_run_id, r.status, r.trigger, r.started_at, r.finished_at, du.name AS duty_name
                FROM mcp_agent_runs r
                LEFT JOIN mcp_agent_duties du ON du.duty_id = r.duty_id
               WHERE r.agent_member_id = a.agent_member_id
               ORDER BY (r.status IN ('running', 'awaiting_approval')) DESC, r.started_at DESC
               LIMIT 1
          ) run ON true
          LEFT JOIN LATERAL (
              SELECT du.name, du.next_run_at
                FROM mcp_agent_duties du
               WHERE du.agent_member_id = a.agent_member_id AND du.active
               ORDER BY du.next_run_at NULLS LAST
               LIMIT 1
          ) duty ON true
          LEFT JOIN LATERAL (
              SELECT al.action, al.created_at
                FROM activity_log al
               WHERE al.actor_member_id = a.agent_member_id AND al.action <> 'screen.view'
               ORDER BY al.id DESC
               LIMIT 1
          ) act ON true
         WHERE a.status <> 'offboarded'
         ORDER BY (a.status = 'active') DESC, a.display_name
         LIMIT :lim
    SQL);
    $st->bindValue('lim', $limit, PDO::PARAM_INT);
    $st->bindValue('me', (int) current_member_id(), PDO::PARAM_INT);
    $st->execute();
    return $st->fetchAll();
}
