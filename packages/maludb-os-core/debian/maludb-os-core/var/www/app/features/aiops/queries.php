<?php
declare(strict_types=1);

/**
 * AI Ops — queries (docs/build-specs/ai-ops.md). Every read goes through the mcp_* views of
 * db/045, db/046 and db/055, so the views decide: the `ledger` grant, a person's own calls, an
 * agent's calls for whoever may see that agent; payloads for humans only (plus an agent's own);
 * eval cases for humans only. Nothing here widens them.
 */

const AIOPS_PAGE_SIZE = 50;
const AIOPS_CALL_STATUSES = ['ok' => 'OK', 'error' => 'Error', 'timeout' => 'Timed out', 'rate_limited' => 'Rate limited', 'refused' => 'Refused', 'cancelled' => 'Cancelled'];
const AIOPS_PERIODS = ['today' => 'Today', 'this_week' => 'This week', 'this_month' => 'This month', 'last_month' => 'Last month', 'this_quarter' => 'This quarter', 'ytd' => 'This year', 'all' => 'All time'];
const AIOPS_GROUPS = ['agent' => 'Agent', 'model' => 'Model', 'provider' => 'Provider', 'department' => 'Department', 'day' => 'Day'];
const AIOPS_PAYLOAD_CAP = 400000;
const EVAL_GRADERS = ['jev' => 'JEV checks — typed, calibrated; unsure goes to a person', 'rubric_llm' => 'A model grades it against the rubric', 'exact' => 'Exact match with the expected answer', 'programmatic' => 'A programmatic check', 'human' => 'A person grades it'];
const EVAL_SET_STATUSES = ['draft' => 'Draft', 'active' => 'Active', 'retired' => 'Retired'];
const EVAL_SCHEDULE_KINDS = ['scheduled_run' => 'Run the whole set', 'trace_sampling' => 'Grade a sample of real work'];
const EVAL_CADENCES = ['daily' => 'Daily', 'weekly' => 'Weekly', 'monthly' => 'Monthly'];
// The runner exists since 2026-09-20 (docs/build-specs/eval-runner.md). What remains true is what
// the screens must keep saying: a run happens because a person asked, and it advises — it gates
// nothing. Silence still means nobody has looked, which is not the same as passing.
const EVAL_RUNNER_NOTE = 'Evaluations run on demand and advise only: nothing is scheduled, nothing blocks an activation, and no alert is raised. A set with no runs has not been evaluated — which is not the same as passing.';

/** [from, to) as SQL-ready ISO dates in UTC, or null for "all time". */
function aiops_period_bounds(string $period): ?array
{
    $today = new DateTimeImmutable('today', new DateTimeZone('UTC'));
    $month = $today->modify('first day of this month');
    return match ($period) {
        'today' => [$today->format('Y-m-d'), $today->modify('+1 day')->format('Y-m-d')],
        'this_week' => [$today->modify('monday this week')->format('Y-m-d'), $today->modify('monday next week')->format('Y-m-d')],
        'last_month' => [$month->modify('-1 month')->format('Y-m-d'), $month->format('Y-m-d')],
        'this_quarter' => [$month->setDate((int) $month->format('Y'), intdiv((int) $month->format('n') - 1, 3) * 3 + 1, 1)->format('Y-m-d'), $today->modify('+1 day')->format('Y-m-d')],
        'ytd' => [$today->format('Y') . '-01-01', $today->modify('+1 day')->format('Y-m-d')],
        'all' => null,
        default => [$month->format('Y-m-d'), $month->modify('+1 month')->format('Y-m-d')],
    };
}

/** @return array{0: array, 1: int, 2: array} rows, total, totals of the whole filtered set */
function find_ledger_calls(PDO $pdo, array $f, int $page = 1): array
{
    $where = ['1 = 1'];
    $args = [];
    // Click-around step 4 (R6): every way an aggregate row can point here — the agent, the person
    // acting, the model, the provider, the application, the department (the member's primary one,
    // exactly as find_ai_spend() groups), a run, a request, and a calendar month beside the period.
    foreach (['agent' => 'pl.agent_member_id', 'run' => 'pl.agent_run_id', 'acting' => 'pl.acting_member_id', 'model' => 'pl.model_id', 'application' => 'pl.application_id'] as $key => $column) {
        if (($f[$key] ?? null) !== null) { $where[] = "{$column} = :{$key}"; $args[$key] = $f[$key]; }
    }
    if (($f['provider'] ?? '') !== '') { $where[] = 'pl.provider = :provider'; $args['provider'] = $f['provider']; }
    if (($f['department'] ?? null) !== null) {
        $where[] = '(SELECT x.department_id FROM department_members x WHERE x.member_id = coalesce(pl.agent_member_id, pl.acting_member_id) AND x.left_at IS NULL
                      ORDER BY x.is_primary DESC NULLS LAST, x.department_id LIMIT 1) = :department';
        $args['department'] = $f['department'];
    }
    if (($f['status'] ?? '') === 'failed') { $where[] = "pl.status <> 'ok'"; }
    elseif (($f['status'] ?? '') !== '') { $where[] = 'pl.status = :status'; $args['status'] = $f['status']; }
    if (($f['request_id'] ?? '') !== '') { $where[] = 'pl.request_id = :rid'; $args['rid'] = $f['request_id']; }
    if (($f['day'] ?? '') !== '') {   // one UTC day, as the spend page's "by day" rows count it (owner, 2026-09-27)
        $where[] = "(pl.occurred_at AT TIME ZONE 'UTC')::date = :day::date";
        $args['day'] = $f['day'];
    } elseif (($f['month'] ?? '') !== '' && ($m = aiops_month((string) $f['month'])) !== null) {
        $where[] = 'pl.occurred_at >= :lo::date AND pl.occurred_at < (:hi::date + 1)';
        $args += ['lo' => $m[0], 'hi' => $m[1]];
    } elseif (($bounds = aiops_period_bounds((string) ($f['period'] ?? 'this_month'))) !== null) {
        $where[] = 'pl.occurred_at >= :lo::date AND pl.occurred_at < :hi::date';
        $args += ['lo' => $bounds[0], 'hi' => $bounds[1]];
    }
    $sql = ' FROM mcp_prompt_ledger pl WHERE ' . implode(' AND ', $where);
    $totals = $pdo->prepare('SELECT count(*) AS calls, coalesce(sum(pl.cost), 0) AS cost, coalesce(sum(pl.input_tokens + pl.output_tokens), 0) AS tokens,
                                    count(*) FILTER (WHERE pl.status <> \'ok\') AS failed' . $sql);
    $totals->execute($args);
    $t = $totals->fetch();
    $st = $pdo->prepare("SELECT pl.*, (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = pl.agent_member_id) AS agent_name,
                                (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = pl.acting_member_id) AS acting_name,
                                (SELECT mr.display_name FROM mcp_model_registry mr WHERE mr.model_id = pl.model_id) AS model_name
                         {$sql} ORDER BY pl.occurred_at DESC, pl.ledger_id DESC LIMIT " . AIOPS_PAGE_SIZE . ' OFFSET ' . (max(1, $page) - 1) * AIOPS_PAGE_SIZE);
    $st->execute($args);
    return [$st->fetchAll(), (int) $t['calls'], $t];
}

function find_ledger_call(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare("SELECT pl.*, (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = pl.agent_member_id) AS agent_name,
                                (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = pl.acting_member_id) AS acting_name,
                                (SELECT mr.display_name FROM mcp_model_registry mr WHERE mr.model_id = pl.model_id) AS model_name
                           FROM mcp_prompt_ledger pl WHERE pl.ledger_id = :id");
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** The stored prompt and response, or null: not visible to this caller, never stored, or past retention. */
function find_ledger_payload(PDO $pdo, int $ledgerId): ?array
{
    $st = $pdo->prepare('SELECT context, response, byte_size, archived_at FROM mcp_prompt_payloads WHERE ledger_id = :id');
    $st->execute(['id' => $ledgerId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function find_ops_run(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT r.*, (SELECT mr.display_name FROM mcp_model_registry mr WHERE mr.model_id = r.model_id) AS model_name,
                                (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = r.requested_by) AS requested_by_name,
                                (SELECT d.member_kind FROM mcp_team_directory d WHERE d.member_id = r.requested_by) AS requested_by_kind
                           FROM mcp_agent_runs r WHERE r.agent_run_id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function find_ops_child_runs(PDO $pdo, int $runId): array
{
    $st = $pdo->prepare('SELECT agent_run_id, agent_member_id, agent_name, status, cost, currency, started_at FROM mcp_agent_runs WHERE parent_run_id = :id ORDER BY agent_run_id LIMIT 50');
    $st->execute(['id' => $runId]);
    return $st->fetchAll();
}

// ---- one agent's page (agent-view, Performance tab) --------------------------------------------
// The views gate: mcp_agent_runs and mcp_prompt_ledger show the caller what app_can_see_run()
// allows, mcp_eval_sets and mcp_eval_runs what app_can_see_evals() allows — so a reader below
// the line simply sees empty sections, never someone else's spend.

/** An agent's latest runs, newest first (what it is doing outranks what it did). */
function find_agent_runs(PDO $pdo, int $agentMemberId, int $limit = 10): array
{
    $st = $pdo->prepare('SELECT r.*, (SELECT mr.display_name FROM mcp_model_registry mr WHERE mr.model_id = r.model_id) AS model_name,
                                (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = r.requested_by) AS requested_by_name,
                                (SELECT d.member_kind FROM mcp_team_directory d WHERE d.member_id = r.requested_by) AS requested_by_kind,
                                (SELECT du.name FROM mcp_agent_duties du WHERE du.duty_id = r.duty_id) AS duty_name
                           FROM mcp_agent_runs r WHERE r.agent_member_id = :a
                          ORDER BY (r.status IN (\'running\', \'awaiting_approval\')) DESC, r.started_at DESC NULLS LAST, r.agent_run_id DESC
                          LIMIT ' . max(1, $limit));
    $st->execute(['a' => $agentMemberId]);
    return $st->fetchAll();
}

/** How many runs an agent has had, how many are under way, how many failed, and the last start. */
function summarise_agent_runs(PDO $pdo, int $agentMemberId): array
{
    $st = $pdo->prepare("SELECT count(*) AS total, count(*) FILTER (WHERE status IN ('running', 'awaiting_approval')) AS active,
                                count(*) FILTER (WHERE status = 'failed') AS failed, count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                                max(started_at) AS last_started_at
                           FROM mcp_agent_runs WHERE agent_member_id = :a");
    $st->execute(['a' => $agentMemberId]);
    return $st->fetch() ?: ['total' => 0, 'active' => 0, 'failed' => 0, 'succeeded' => 0, 'last_started_at' => null];
}

/**
 * An agent's model calls summed for this month, last month and all time — one row per period,
 * from the same ledger the prompt log and the spend screen read.
 * @return array<string, array> keyed this_month | last_month | all
 */
function summarise_agent_ledger(PDO $pdo, int $agentMemberId): array
{
    $out = [];
    foreach (['this_month', 'last_month', 'all'] as $period) {
        $where = 'agent_member_id = :a';
        $args = ['a' => $agentMemberId];
        if (($bounds = aiops_period_bounds($period)) !== null) {
            $where .= ' AND occurred_at >= :lo::date AND occurred_at < :hi::date';
            $args += ['lo' => $bounds[0], 'hi' => $bounds[1]];
        }
        $st = $pdo->prepare("SELECT count(*) AS calls, count(*) FILTER (WHERE status <> 'ok') AS failed,
                                    coalesce(sum(input_tokens), 0) AS input_tokens, coalesce(sum(output_tokens), 0) AS output_tokens,
                                    coalesce(sum(cache_read_tokens), 0) AS cache_read_tokens, round(avg(latency_ms)) AS avg_latency_ms,
                                    coalesce(sum(cost), 0) AS cost, coalesce(min(currency), 'USD') AS currency, max(occurred_at) AS last_at
                               FROM mcp_prompt_ledger WHERE {$where}");
        $st->execute($args);
        $out[$period] = $st->fetch();
    }
    return $out;
}

/** The eval runs that judged this agent — its own, or those of a set written for it — newest first. */
function find_agent_eval_runs(PDO $pdo, int $agentMemberId, int $limit = 10): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_eval_runs
                          WHERE agent_member_id = :a OR eval_set_id IN (SELECT eval_set_id FROM mcp_eval_sets WHERE agent_member_id = :a2)
                          ORDER BY created_at DESC LIMIT ' . max(1, $limit));
    $st->execute(['a' => $agentMemberId, 'a2' => $agentMemberId]);
    return $st->fetchAll();
}

/** What the run DID, from the activity trail (base table: the run itself was visible, and these are its own rows). */
function find_ops_run_actions(PDO $pdo, int $runId): array
{
    $st = $pdo->prepare("SELECT id, occurred_at, action, entity_type, entity_id FROM activity_log
                          WHERE agent_run_id = :id AND action NOT LIKE 'api.%' AND action <> 'screen.view' ORDER BY id LIMIT 200");
    $st->execute(['id' => $runId]);
    return $st->fetchAll();
}

/** Spend grouped. Department = the agent's primary department (or "No department" for a person's own calls). */
function find_ai_spend(PDO $pdo, string $period, string $groupBy): array
{
    // [key, label, join, kind] — kind is the key's member_kind for the agent grouping (the row links to
    // the agent's page or the person's), NULL for the rest (click-around, docs/build-specs/click-around.md).
    [$key, $label, $join, $kind] = match ($groupBy) {
        'model' => ['pl.model_id', "coalesce(mr.display_name, pl.provider_model_id)", 'LEFT JOIN mcp_model_registry mr ON mr.model_id = pl.model_id', 'NULL::text'],
        'provider' => ['pl.provider', 'pl.provider', '', 'NULL::text'],
        'day' => ["(pl.occurred_at AT TIME ZONE 'UTC')::date", "(pl.occurred_at AT TIME ZONE 'UTC')::date::text", '', 'NULL::text'],
        'department' => ['dm.department_id', "coalesce(dp.name, 'No department')",
            'LEFT JOIN LATERAL (SELECT x.department_id FROM department_members x WHERE x.member_id = coalesce(pl.agent_member_id, pl.acting_member_id) AND x.left_at IS NULL ORDER BY x.is_primary DESC NULLS LAST, x.department_id LIMIT 1) dm ON true
             LEFT JOIN mcp_departments dp ON dp.department_id = dm.department_id', 'NULL::text'],
        default => ['coalesce(pl.agent_member_id, pl.acting_member_id)', "coalesce(td.display_name, 'Someone')", 'LEFT JOIN mcp_team_directory td ON td.member_id = coalesce(pl.agent_member_id, pl.acting_member_id)', 'min(td.member_kind)'],
    };
    $where = '1 = 1';
    $args = [];
    if (($bounds = aiops_period_bounds($period)) !== null) {
        $where = 'pl.occurred_at >= :lo::date AND pl.occurred_at < :hi::date';
        $args = ['lo' => $bounds[0], 'hi' => $bounds[1]];
    }
    $st = $pdo->prepare("
        SELECT {$key} AS group_key, {$label} AS label, {$kind} AS kind, count(*) AS calls, count(*) FILTER (WHERE pl.status <> 'ok') AS failed,
               sum(pl.input_tokens) AS input_tokens, sum(pl.output_tokens) AS output_tokens,
               sum(pl.cache_read_tokens) AS cache_read_tokens, sum(pl.cache_write_tokens) AS cache_write_tokens,
               round(avg(pl.latency_ms)) AS avg_latency_ms, sum(pl.cost) AS cost, min(pl.currency) AS currency,
               -- What the cached tokens would have cost at the input price, less what they did cost to read.
               coalesce(sum(pl.cache_read_tokens * (m2.price_input_per_mtok - m2.price_cache_read_per_mtok) / 1000000.0), 0) AS cache_saving
          FROM mcp_prompt_ledger pl
          LEFT JOIN mcp_model_registry m2 ON m2.model_id = pl.model_id
          {$join}
         WHERE {$where}
         GROUP BY 1, 2 ORDER BY " . ($groupBy === 'day' ? '1' : 'sum(pl.cost) DESC') . ' LIMIT 200');
    $st->execute($args);
    return $st->fetchAll();
}

// ---- usage postings ------------------------------------------------------------------------

/** A month as [first day, last day], or null if $period is not YYYY-MM. */
function aiops_month(string $period): ?array
{
    if (!preg_match('/^(\d{4})-(0[1-9]|1[0-2])$/', $period)) {
        return null;
    }
    $start = new DateTimeImmutable($period . '-01', new DateTimeZone('UTC'));
    return [$start->format('Y-m-d'), $start->modify('last day of this month')->format('Y-m-d')];
}

/**
 * One month of the ledger, summarised the way it would post: per provider x model x currency.
 * Base table on purpose — what a business owes its model providers does not depend on which
 * agents the person pressing the button may see (the gate is on the action, and on the screen).
 */
function summarise_ai_usage(PDO $pdo, string $start, string $end, ?string $provider = null): array
{
    $st = $pdo->prepare("
        SELECT pl.provider, pl.model_id, mr.display_name AS model_name, pl.currency, count(*) AS call_count,
               count(*) FILTER (WHERE pl.cost = 0) AS uncosted_calls,
               sum(pl.input_tokens) AS input_tokens, sum(pl.output_tokens) AS output_tokens,
               sum(pl.cache_read_tokens) AS cache_read_tokens, sum(pl.cache_write_tokens) AS cache_write_tokens,
               sum(pl.cost) AS exact_cost, round(sum(pl.cost), 2) AS amount
          FROM prompt_ledger pl LEFT JOIN model_registry mr ON mr.id = pl.model_id
         WHERE pl.occurred_at >= :s::date AND pl.occurred_at < (:e::date + 1) AND (:p::text IS NULL OR pl.provider = :p2)
         GROUP BY 1, 2, 3, 4 ORDER BY 1, 3");
    $st->execute(['s' => $start, 'e' => $end, 'p' => $provider, 'p2' => $provider]);
    return $st->fetchAll();
}

// ---- evals ---------------------------------------------------------------------------------

function find_eval_sets(PDO $pdo, ?int $agent = null, string $status = ''): array
{
    $where = ['1 = 1'];
    $args = [];
    if ($agent !== null) { $where[] = 's.agent_member_id = :a'; $args['a'] = $agent; }
    if (isset(EVAL_SET_STATUSES[$status])) { $where[] = 's.status = :st'; $args['st'] = $status; }
    $st = $pdo->prepare("SELECT s.*, (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = s.agent_member_id) AS agent_name,
                                (SELECT dp.name FROM mcp_departments dp WHERE dp.department_id = s.department_id) AS department_name,
                                (SELECT count(*) FROM mcp_eval_cases c WHERE c.eval_set_id = s.eval_set_id) AS case_count,
                                (SELECT count(*) FROM mcp_eval_cases c WHERE c.eval_set_id = s.eval_set_id AND c.active) AS active_case_count,
                                (SELECT count(*) FROM mcp_eval_schedules h WHERE h.eval_set_id = s.eval_set_id AND h.active) AS schedule_count
                           FROM mcp_eval_sets s WHERE " . implode(' AND ', $where) . ' ORDER BY s.name LIMIT 300');
    $st->execute($args);
    return $st->fetchAll();
}

function find_eval_set(PDO $pdo, int $id): ?array
{
    foreach (find_eval_sets($pdo) as $s) {
        if ((int) $s['eval_set_id'] === $id) { return $s; }
    }
    return null;
}

function find_eval_cases(PDO $pdo, int $setId): array
{
    $st = $pdo->prepare('SELECT * FROM mcp_eval_cases WHERE eval_set_id = :s ORDER BY active DESC, eval_case_id');
    $st->execute(['s' => $setId]);
    return $st->fetchAll();
}

function find_eval_case(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_eval_cases WHERE eval_case_id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

function find_eval_schedules(PDO $pdo, ?int $setId = null, ?int $agent = null): array
{
    $st = $pdo->prepare('SELECT h.*, (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = h.agent_member_id) AS agent_name
                           FROM mcp_eval_schedules h WHERE (:s::bigint IS NULL OR h.eval_set_id = :s2) AND (:a::bigint IS NULL OR h.agent_member_id = :a2)
                          ORDER BY h.eval_set_name, h.eval_schedule_id');
    $st->execute(['s' => $setId, 's2' => $setId, 'a' => $agent, 'a2' => $agent]);
    return $st->fetchAll();
}

/** The names an eval run row (`r`) is shown with — the agent, the model, who started it (click-around step 2). */
function eval_run_names_sql(): string
{
    return "(SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = r.agent_member_id) AS agent_name,
            (SELECT mr.display_name FROM mcp_model_registry mr WHERE mr.model_id = r.model_id) AS model_name,
            (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = r.started_by) AS started_by_name,
            (SELECT d.member_kind FROM mcp_team_directory d WHERE d.member_id = r.started_by) AS started_by_kind";
}

function find_eval_runs(PDO $pdo, ?int $setId = null): array
{
    $st = $pdo->prepare('SELECT r.*, ' . eval_run_names_sql() . ' FROM mcp_eval_runs r WHERE (:s::bigint IS NULL OR r.eval_set_id = :s2) ORDER BY r.created_at DESC LIMIT 100');
    $st->execute(['s' => $setId, 's2' => $setId]);
    return $st->fetchAll();
}

function find_eval_alerts(PDO $pdo, array $f = []): array
{
    $where = ['1 = 1'];
    $args = [];
    if (($f['agent'] ?? null) !== null) { $where[] = 'agent_member_id = :a'; $args['a'] = $f['agent']; }
    if (($f['eval_set'] ?? null) !== null) { $where[] = 'eval_set_id = :es'; $args['es'] = $f['eval_set']; }
    if (in_array($f['severity'] ?? '', ['info', 'warning', 'critical'], true)) { $where[] = 'severity = :sev'; $args['sev'] = $f['severity']; }
    if (in_array($f['status'] ?? '', ['open', 'acknowledged', 'resolved'], true)) { $where[] = 'status = :st'; $args['st'] = $f['status']; }
    elseif (($f['status'] ?? '') !== 'all') { $where[] = "status <> 'resolved'"; }
    $st = $pdo->prepare('SELECT a.*, (SELECT d.display_name FROM mcp_team_directory d WHERE d.member_id = a.acknowledged_by) AS acknowledged_by_name,
                                (SELECT d.member_kind FROM mcp_team_directory d WHERE d.member_id = a.acknowledged_by) AS acknowledged_by_kind
                           FROM mcp_eval_alerts a WHERE ' . implode(' AND ', $where) . ' ORDER BY a.opened_at DESC LIMIT 200');
    $st->execute($args);
    return $st->fetchAll();
}

/** True if the caller manages (or administers) this agent — the manifest's "agent's manager" half of several eval gates. */
function aiops_can_see_agent(PDO $pdo, ?int $agentMemberId): bool
{
    if ($agentMemberId === null) {
        return false;
    }
    $st = $pdo->prepare('SELECT app_can_see_agent(:a)');
    $st->execute(['a' => $agentMemberId]);
    return (bool) $st->fetchColumn();
}

/* ---- A person's verdict on a run or an assistant answer (db/124) ------------------
 * The cheapest label an evaluation can have, and the one thing the platform recorded
 * nowhere (docs/build-specs/eval-evidence.md). Reads go through mcp_run_verdicts, which
 * shows a verdict to whoever may see the thing it is about; writes are the caller's own
 * row, which the table's RLS enforces regardless of what is asked here.
 */

/** This caller's own verdict on a run (or a call), or null. */
function find_my_verdict(PDO $pdo, ?int $runId, ?int $callId): ?array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT run_verdict_id, verdict, note, updated_at FROM mcp_run_verdicts
         WHERE member_id = :me
           AND agent_run_id IS NOT DISTINCT FROM :run
           AND prompt_ledger_id IS NOT DISTINCT FROM :call
    SQL);
    $st->execute(['me' => current_member_id(), 'run' => $runId, 'call' => $callId]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** Everyone's verdicts on one run (or call), newest first — what a later evaluation reads. */
function find_verdicts(PDO $pdo, ?int $runId, ?int $callId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT verdict, note, member_name, member_id, updated_at FROM mcp_run_verdicts
         WHERE agent_run_id IS NOT DISTINCT FROM :run
           AND prompt_ledger_id IS NOT DISTINCT FROM :call
         ORDER BY updated_at DESC
    SQL);
    $st->execute(['run' => $runId, 'call' => $callId]);
    return $st->fetchAll();
}

/**
 * Record (or change) this caller's verdict. One per person per subject: a second thought
 * replaces the first rather than stacking up, which is what the unique indexes say.
 * Returns [id, 'created'|'changed'].
 */
function set_run_verdict(PDO $pdo, ?int $runId, ?int $callId, string $verdict, ?string $note): array
{
    $existing = find_my_verdict($pdo, $runId, $callId);
    if ($existing !== null) {
        $st = $pdo->prepare('UPDATE run_verdicts SET verdict = :v, note = :n WHERE id = :id RETURNING id');
        $st->execute(['v' => $verdict, 'n' => $note, 'id' => $existing['run_verdict_id']]);
        return [(int) $st->fetchColumn(), 'changed'];
    }
    $st = $pdo->prepare(<<<'SQL'
        INSERT INTO run_verdicts (agent_run_id, prompt_ledger_id, verdict, note, member_id)
        VALUES (:run, :call, :v, :n, :me) RETURNING id
    SQL);
    $st->execute(['run' => $runId, 'call' => $callId, 'v' => $verdict, 'n' => $note, 'me' => current_member_id()]);
    return [(int) $st->fetchColumn(), 'created'];
}

/* ---- The eval runner (docs/build-specs/eval-runner.md) ---------------------------
 * PHP never runs an evaluation any more than it runs an agent: it creates the row and
 * asks the runner, which owns the run's life. Evals advise and never gate, so nothing
 * anywhere waits on the answer.
 */

/**
 * Create the eval_runs row and ask the runner to work it. Returns [run_id, error].
 * The version under test defaults to the agent's active one; naming another is how a
 * change is weighed before it goes live (owner, 2026-09-20).
 */
function start_eval_run(PDO $pdo, array $set, ?int $agentMemberId, ?int $configVersionId, string $trigger): array
{
    require_once dirname(__DIR__) . '/agents/runs.php';

    $agentMemberId ??= $set['agent_member_id'] !== null ? (int) $set['agent_member_id'] : null;
    if ($agentMemberId === null) {
        return [null, 'This set is written for a role rather than one agent, so say which agent to run it against.'];
    }
    // The version decides the model, exactly as it does for an ordinary run.
    $st = $pdo->prepare(<<<'SQL'
        SELECT v.id, v.model_id FROM agent_config_versions v
         WHERE v.agent_member_id = :a
           AND v.id = COALESCE(:v::bigint, (SELECT current_config_version_id FROM agent_profiles WHERE member_id = :a))
    SQL);
    $st->execute(['a' => $agentMemberId, 'v' => $configVersionId]);
    if (($version = $st->fetch()) === false) {
        return [null, $configVersionId !== null
            ? 'That configuration version does not belong to this agent.'
            : 'That agent has no active configuration version to test.'];
    }

    $harness = $pdo->prepare('SELECT harness FROM model_registry WHERE id = :m');
    $harness->execute(['m' => $version['model_id']]);
    $harnessKey = (string) $harness->fetchColumn();

    // The most recent passed run of this set for this agent, so a regression is comparable.
    $base = $pdo->prepare(<<<'SQL'
        SELECT id FROM eval_runs
         WHERE eval_set_id = :s AND agent_member_id = :a AND status = 'passed'
         ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1
    SQL);
    $base->execute(['s' => $set['eval_set_id'], 'a' => $agentMemberId]);
    $baseline = ($b = $base->fetchColumn()) !== false ? (int) $b : null;

    $ins = $pdo->prepare(<<<'SQL'
        INSERT INTO eval_runs (eval_set_id, agent_member_id, config_version_id, model_id, harness,
                               trigger, status, pass_threshold, baseline_run_id, started_by)
        VALUES (:s, :a, :v, :m, :h, :t, 'queued', :th, :b, :by) RETURNING id
    SQL);
    $ins->execute([
        's' => $set['eval_set_id'], 'a' => $agentMemberId, 'v' => (int) $version['id'],
        'm' => (int) $version['model_id'], 'h' => $harnessKey, 't' => $trigger,
        'th' => $set['pass_threshold'], 'b' => $baseline, 'by' => (int) current_member_id(),
    ]);
    $evalRunId = (int) $ins->fetchColumn();

    $r = runner_request('POST', '/eval-runs', ['eval_run_id' => $evalRunId]);
    if ($r['status'] !== 202) {
        // The row stays, marked error: an evaluation that was asked for and did not happen is
        // worth seeing. A queued row that nothing is working would be worse than none at all.
        $pdo->prepare("UPDATE eval_runs SET status = 'error', finished_at = now() WHERE id = :id")
            ->execute(['id' => $evalRunId]);
        return [$evalRunId, $r['status'] === 0
            ? 'The agent runner is not reachable, so nothing was evaluated.'
            : (string) ($r['body']['error'] ?? 'The runner refused the evaluation.')];
    }
    return [$evalRunId, null];
}

/**
 * Recompute a run's score after a person grades one of its human cases. The score counts only
 * what has been graded (owner, 2026-09-20), so grading the last one is what finally makes the
 * number whole — and it must never be restated silently, hence the returned before/after.
 */
function eval_run_rescore(PDO $pdo, int $evalRunId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT r.score AS old_score, r.status AS old_status, r.pass_threshold,
               SUM(c.weight) FILTER (WHERE graded.graded)                       AS graded_weight,
               SUM(c.weight) FILTER (WHERE graded.graded AND res.passed)        AS passed_weight,
               COUNT(*)      FILTER (WHERE graded.graded AND res.passed)        AS passed_count,
               COUNT(*)      FILTER (WHERE NOT graded.graded)                   AS awaiting
          FROM eval_runs r
          JOIN eval_results res ON res.eval_run_id = r.id
          JOIN eval_cases c ON c.id = res.eval_case_id
          CROSS JOIN LATERAL (SELECT ((c.grader <> 'human' AND NOT res.awaiting_person) OR res.graded_by IS NOT NULL) AS graded) graded
         WHERE r.id = :id
         GROUP BY r.score, r.status, r.pass_threshold
    SQL);
    $st->execute(['id' => $evalRunId]);
    if (($row = $st->fetch()) === false) {
        return ['changed' => false];
    }
    $weight = (float) ($row['graded_weight'] ?? 0);
    $score = $weight > 0 ? round(100 * (float) ($row['passed_weight'] ?? 0) / $weight, 2) : null;
    $status = $score === null ? 'error' : ($score >= (float) $row['pass_threshold'] ? 'passed' : 'failed');

    $pdo->prepare('UPDATE eval_runs SET score = :s, status = :st, cases_passed = :p, updated_at = now() WHERE id = :id')
        ->execute(['s' => $score, 'st' => $status, 'p' => (int) $row['passed_count'], 'id' => $evalRunId]);

    return [
        'changed' => (string) $row['old_score'] !== (string) $score || $row['old_status'] !== $status,
        'old_score' => $row['old_score'], 'score' => $score,
        'old_status' => $row['old_status'], 'status' => $status,
        'awaiting' => (int) $row['awaiting'],
    ];
}

/** One run's per-case results, for the run screen. */
function find_eval_results(PDO $pdo, int $evalRunId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT r.eval_result_id, r.eval_case_id, r.agent_run_id, r.passed, r.score, r.grader_notes,
               r.graded_by, c.title, c.grader, c.weight, r.awaiting_person, r.is_graded, r.grader_detail, c.checks
          FROM mcp_eval_results r JOIN mcp_eval_cases c ON c.eval_case_id = r.eval_case_id
         WHERE r.eval_run_id = :id ORDER BY c.eval_case_id
    SQL);
    $st->execute(['id' => $evalRunId]);
    return $st->fetchAll();
}


/**
 * What happened INSIDE a run: which tool ran, whether it failed, how long it took (db/122).
 * Written since 2026-09-20 and read by nothing until now — the run screen showed the runner's
 * in-memory copy instead, which a restart lost. This is the durable one.
 */
function find_run_events(PDO $pdo, int $runId): array
{
    $st = $pdo->prepare(<<<'SQL'
        SELECT seq, occurred_at, event, tool_name, status, duration_ms, error_type, error_message
          FROM mcp_agent_run_events WHERE agent_run_id = :id ORDER BY seq LIMIT 500
    SQL);
    $st->execute(['id' => $runId]);
    return $st->fetchAll();
}


// ---- JEV checks (db/144 — docs/build-specs/eval-jev-grader.md) --------------------------------------

/**
 * [checks, errors] — a JEV case's checks from JSON text, validated to the shape the runner asks JEV:
 * 1–24 checks, ids unique (letters, digits, underscores), type noul | choice | score, the criteria each
 * type takes, and its pass rule. Defaults are TypeSafe's published examples: tune them on our data.
 */
function eval_jev_checks_from_json(string $json): array
{
    $raw = json_decode($json, true);
    if (!is_array($raw) || !array_is_list($raw) || count($raw) < 1 || count($raw) > 24) {
        return [null, ['JEV checks are a list of 1 to 24 checks.']];
    }
    $out = [];
    $errors = [];
    $seen = [];
    foreach ($raw as $i => $c) {
        $n = $i + 1;
        if (!is_array($c)) { $errors[] = "Check {$n} is not an object."; continue; }
        $id = (string) ($c['id'] ?? '');
        if (!preg_match('/^[a-z][a-z0-9_]{0,39}$/', $id) || isset($seen[$id]) || $id === 'grader_injection') {
            $errors[] = "Check {$n} needs its own id: lowercase letters, digits and underscores (not grader_injection).";
        }
        $seen[$id] = true;
        $type = (string) ($c['type'] ?? '');
        $instructions = trim((string) ($c['instructions'] ?? ''));
        if ($instructions === '' || mb_strlen($instructions) > 2000) { $errors[] = "Check {$id}: say what JEV is asked (up to 2000 characters)."; }
        $check = ['id' => $id, 'type' => $type, 'instructions' => $instructions,
                  'required' => !array_key_exists('required', $c) || (bool) $c['required'],
                  'weight' => isset($c['weight']) && is_numeric($c['weight']) && (float) $c['weight'] > 0 ? (float) $c['weight'] : 1.0];
        $criteria = $c['criteria'] ?? null;
        if ($type === 'noul') {
            if ($criteria !== null && (!is_array($criteria) || array_diff(array_keys($criteria), ['true', 'false']) !== [])) {
                $errors[] = "Check {$id}: a noul's criteria, if given, say what true and what false mean.";
            }
            $passAt = $c['pass_at'] ?? 0.8;
            if (!is_numeric($passAt) || $passAt <= 0 || $passAt >= 1) { $errors[] = "Check {$id}: pass_at is between 0 and 1."; }
            $band = $c['uncertain'] ?? [0.3, 0.7];
            if (!is_array($band) || count($band) !== 2 || !is_numeric($band[0]) || !is_numeric($band[1]) || $band[0] >= $band[1]) {
                $errors[] = "Check {$id}: uncertain is a band [low, high].";
            }
            $check += ['criteria' => $criteria, 'pass_at' => (float) $passAt, 'uncertain' => array_map('floatval', (array) $band)];
        } elseif ($type === 'choice') {
            if (!is_array($criteria) || array_is_list($criteria) || count($criteria) < 2 || count($criteria) > 255) {
                $errors[] = "Check {$id}: a choice's criteria are 2–255 options, each with a description.";
            }
            $accept = array_values(array_filter((array) ($c['accept'] ?? []), 'is_string'));
            if ($accept === [] || (is_array($criteria) && array_diff($accept, array_keys($criteria)) !== [])) {
                $errors[] = "Check {$id}: accept names the options that pass.";
            }
            $check += ['criteria' => $criteria, 'accept' => $accept, 'min_confidence' => (float) ($c['min_confidence'] ?? 0.6)];
        } elseif ($type === 'score') {
            if (!is_array($criteria) || !array_is_list($criteria) || count($criteria) < 2 || count($criteria) > 10) {
                $errors[] = "Check {$id}: a score's criteria are 2–10 levels, lowest first, each described as a situation.";
            }
            $min = $c['min_level'] ?? null;
            if (!is_int($min) || $min < 0 || (is_array($criteria) && $min >= count($criteria))) {
                $errors[] = "Check {$id}: min_level is the lowest level that passes (0 is the first).";
            }
            $check += ['criteria' => $criteria, 'min_level' => (int) $min, 'min_confidence' => (float) ($c['min_confidence'] ?? 0.6)];
        } else {
            $errors[] = "Check {$n}: type is noul, choice or score.";
        }
        $out[] = $check;
    }
    return [$errors === [] ? $out : null, array_values(array_unique($errors))];
}

/**
 * A first draft of checks from a rubric: one yes/no (noul) check per line of it — TypeSafe's own advice
 * is one atomic property per question. A person edits the draft; nothing is saved here, and no model
 * is asked (the web tier holds no model key).
 */
function eval_jev_draft_checks(string $rubric): array
{
    $lines = preg_split('/\R/', $rubric) ?: [];
    $checks = [];
    foreach ($lines as $line) {
        $text = trim(preg_replace('/^\s*(?:[-*•]|\d+[.)])\s*/u', '', $line) ?? '');
        if ($text === '' || mb_strlen($text) < 4) { continue; }
        $id = trim(preg_replace('/[^a-z0-9]+/', '_', strtolower(mb_substr($text, 0, 32))) ?? '', '_') ?: 'check';
        $id = preg_match('/^[a-z]/', $id) ? $id : 'c_' . $id;
        $base = substr($id, 0, 36); $id = $base; $k = 2;
        while (isset($checks[$id])) { $id = $base . '_' . $k++; }
        $checks[$id] = ['id' => $id, 'type' => 'noul',
            'instructions' => 'The agent\'s work satisfies this: ' . rtrim($text, '.') . '.',
            'criteria' => ['true' => 'it is satisfied', 'false' => 'it is not, or only partly'],
            'pass_at' => 0.8, 'uncertain' => [0.3, 0.7], 'required' => true, 'weight' => 1];
        if (count($checks) >= 24) { break; }
    }
    return array_values($checks);
}
