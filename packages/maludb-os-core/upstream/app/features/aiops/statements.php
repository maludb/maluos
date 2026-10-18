<?php
declare(strict_types=1);

/**
 * The ledger's period statement (A5, 2026-09-22 — docs/build-specs/kernel-ledger-statement.md).
 * Each calendar month the prompt ledger rolls up into one statement per provider × model ×
 * department × agent × application × currency. While the month is OPEN the rows are recomputed
 * on demand; a super-admin CLOSES a past month, after which its rows never change and any call
 * that arrives for it later is a late call, folded into the open month with a note. The
 * statement is what leaves the kernel: a file, the ledger feed, the ledger_period tool. Nothing
 * here posts a journal — the accounting system is an application.
 */

const LEDGER_PERIOD_SCHEMA = 'os.ledger-period/1';

/** 'YYYY-MM' → [first day, last day] or null. */
function ai_period_bounds(string $period): ?array
{
    if (!preg_match('/^(\d{4})-(0[1-9]|1[0-2])$/', $period)) {
        return null;
    }
    $start = new DateTimeImmutable($period . '-01', new DateTimeZone('UTC'));
    return [$start->format('Y-m-d'), $start->modify('last day of this month')->format('Y-m-d')];
}

function find_ai_period(PDO $pdo, string $start): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_ai_periods WHERE period_start = :s');
    $st->execute(['s' => $start]);
    return $st->fetch() ?: null;
}

/**
 * Every month the ledger has anything in, newest first, with what the statement says of it: the
 * period's status (open until closed; a month with no row is open), calls and cost from the ledger
 * itself, and the statement's own totals.
 */
function find_ai_period_months(PDO $pdo): array
{
    return $pdo->query("
        WITH months AS (
            SELECT date_trunc('month', occurred_at AT TIME ZONE 'UTC')::date AS period_start FROM prompt_ledger
            UNION SELECT period_start FROM ai_periods
        )
        SELECT to_char(m.period_start, 'YYYY-MM') AS period, m.period_start,
               (m.period_start + interval '1 month' - interval '1 day')::date AS period_end,
               coalesce(p.status, 'open') AS status, p.closed_at, p.closed_by_name, p.rolled_up_at, p.note,
               (SELECT count(*) FROM prompt_ledger pl WHERE pl.occurred_at >= m.period_start AND pl.occurred_at < m.period_start + interval '1 month') AS ledger_calls,
               (SELECT round(coalesce(sum(pl.cost), 0), 4) FROM prompt_ledger pl WHERE pl.occurred_at >= m.period_start AND pl.occurred_at < m.period_start + interval '1 month') AS ledger_cost,
               (SELECT string_agg(DISTINCT pl.currency, ', ') FROM prompt_ledger pl WHERE pl.occurred_at >= m.period_start AND pl.occurred_at < m.period_start + interval '1 month') AS currencies,
               (SELECT count(*) FROM ai_usage_postings s WHERE s.period_start = m.period_start AND s.status <> 'void') AS statement_lines,
               (SELECT round(coalesce(sum(s.amount), 0), 4) FROM ai_usage_postings s WHERE s.period_start = m.period_start AND s.status <> 'void') AS statement_amount,
               (m.period_start + interval '1 month' <= date_trunc('month', now() AT TIME ZONE 'UTC')) AS is_past
          FROM (SELECT DISTINCT period_start FROM months) m
          LEFT JOIN mcp_ai_periods p ON p.period_start = m.period_start
         ORDER BY m.period_start DESC LIMIT 36")->fetchAll();
}

function find_ai_statement_lines(PDO $pdo, string $start): array
{
    $st = $pdo->prepare("SELECT * FROM mcp_ai_usage_postings WHERE period_start = :s AND status <> 'void'
                          ORDER BY provider, model_name, department_name NULLS LAST, agent_name NULLS LAST, application_name NULLS LAST, currency");
    $st->execute(['s' => $start]);
    return $st->fetchAll();
}

/**
 * Recompute an OPEN month's statement from the ledger: its own calls, plus late calls — rows
 * dated in an earlier CLOSED month that arrived after that month closed (id above its high-water
 * mark). Rows are replaced wholesale; nothing references a statement row by id.
 * @return array{lines:int, calls:int, late_calls:int}
 */
function rollup_ai_period(PDO $pdo, string $start, string $end): array
{
    $period = find_ai_period($pdo, $start);
    if ($period !== null && $period['status'] === 'closed') {
        throw new RuntimeException('The period is closed; its statement does not change.');
    }
    $pdo->beginTransaction();
    try {
        $pdo->prepare("INSERT INTO ai_periods (period_start, period_end, status, rolled_up_at) VALUES (:s, :e, 'open', now())
                       ON CONFLICT (period_start) DO UPDATE SET rolled_up_at = now(), updated_at = now()")
            ->execute(['s' => $start, 'e' => $end]);
        $pdo->prepare("DELETE FROM ai_usage_postings WHERE period_start = :s AND status = 'open'")->execute(['s' => $start]);
        $st = $pdo->prepare("
            INSERT INTO ai_usage_postings
                (period_start, period_end, provider, model_id, department_id, agent_member_id, application_id, currency,
                 call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, amount, late_calls, status, note)
            SELECT :s, :e, pl.provider, pl.model_id,
                   (SELECT dm.department_id FROM department_members dm
                     WHERE dm.member_id = pl.agent_member_id AND dm.left_at IS NULL
                     ORDER BY dm.is_primary DESC, dm.joined_at LIMIT 1),
                   pl.agent_member_id, pl.application_id, pl.currency,
                   count(*), sum(pl.input_tokens), sum(pl.output_tokens), sum(pl.cache_read_tokens), sum(pl.cache_write_tokens),
                   round(sum(pl.cost), 4),
                   count(*) FILTER (WHERE pl.occurred_at < :s::date),
                   'open',
                   CASE WHEN count(*) FILTER (WHERE pl.occurred_at < :s::date) > 0
                        THEN 'Includes ' || count(*) FILTER (WHERE pl.occurred_at < :s::date) || ' late call(s) dated in a closed month' END
              FROM prompt_ledger pl
             WHERE (pl.occurred_at >= :s::date AND pl.occurred_at < :e::date + 1)
                OR EXISTS (SELECT 1 FROM ai_periods cp
                            WHERE cp.status = 'closed' AND cp.period_start < :s::date
                              AND pl.occurred_at >= cp.period_start AND pl.occurred_at < cp.period_end + 1
                              AND pl.id > coalesce(cp.ledger_high_water, 0))
             GROUP BY pl.provider, pl.model_id, pl.agent_member_id, pl.application_id, pl.currency
            RETURNING call_count, late_calls");
        $st->execute(['s' => $start, 'e' => $end]);
        $rows = $st->fetchAll();
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
    return ['lines' => count($rows), 'calls' => (int) array_sum(array_column($rows, 'call_count')),
            'late_calls' => (int) array_sum(array_column($rows, 'late_calls'))];
}

/** Close a past month: roll it up one last time, freeze its rows, remember the ledger's high-water mark. */
function close_ai_period(PDO $pdo, string $start, string $end, int $closedBy, ?string $note): array
{
    $summary = rollup_ai_period($pdo, $start, $end);
    $pdo->beginTransaction();
    try {
        $high = (int) $pdo->query('SELECT coalesce(max(id), 0) FROM prompt_ledger')->fetchColumn();
        $pdo->prepare("UPDATE ai_periods SET status = 'closed', closed_at = now(), closed_by = :by, ledger_high_water = :hw,
                              note = :note, updated_at = now() WHERE period_start = :s")
            ->execute(['by' => $closedBy, 'hw' => $high, 'note' => $note, 's' => $start]);
        $pdo->prepare("UPDATE ai_usage_postings SET status = 'closed', closed_at = now(), closed_by = :by, updated_at = now()
                        WHERE period_start = :s AND status = 'open'")->execute(['by' => $closedBy, 's' => $start]);
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
    return $summary + ['ledger_high_water' => $high];
}

// --------------------------------------------------------------------------
// Presenters and the export document (mirrored by web/lib/schemas/aiops.ts).
// --------------------------------------------------------------------------
function present_ai_period_month(array $m): array
{
    return ['period' => (string) $m['period'], 'period_start' => (string) $m['period_start'], 'period_end' => (string) $m['period_end'],
            'status' => (string) $m['status'], 'closed_at' => json_ts($m['closed_at'] ?? null), 'closed_by_name' => $m['closed_by_name'] ?? null,
            'closed_by' => isset($m['closed_by']) ? (int) $m['closed_by'] : null,
            'rolled_up_at' => json_ts($m['rolled_up_at'] ?? null), 'note' => $m['note'] ?? null,
            'ledger_calls' => (int) $m['ledger_calls'], 'ledger_cost' => (string) $m['ledger_cost'], 'currencies' => (string) ($m['currencies'] ?? ''),
            'statement_lines' => (int) $m['statement_lines'], 'statement_amount' => (string) $m['statement_amount'], 'is_past' => !empty($m['is_past'])];
}

function present_ai_statement_line(array $r): array
{
    return ['id' => (int) $r['ai_usage_posting_id'], 'provider' => (string) $r['provider'], 'model_id' => isset($r['model_id']) ? (int) $r['model_id'] : null,
            'model' => $r['model_name'] ?? null, 'department_id' => isset($r['department_id']) ? (int) $r['department_id'] : null, 'department' => $r['department_name'] ?? null,
            'agent_id' => isset($r['agent_member_id']) ? (int) $r['agent_member_id'] : null, 'agent' => $r['agent_name'] ?? null,
            'application_id' => isset($r['application_id']) ? (int) $r['application_id'] : null, 'application' => $r['application_name'] ?? null,
            'calls' => (int) $r['call_count'], 'input_tokens' => (int) $r['input_tokens'], 'output_tokens' => (int) $r['output_tokens'],
            'cache_read_tokens' => (int) $r['cache_read_tokens'], 'cache_write_tokens' => (int) $r['cache_write_tokens'],
            'late_calls' => (int) $r['late_calls'], 'amount' => (string) $r['amount'], 'currency' => (string) $r['currency'],
            'status' => (string) $r['status'], 'note' => $r['note'] ?? null];
}

/** The one document every export carries — screen download, the ledger feed, the ledger_period tool. */
function ai_period_document(PDO $pdo, string $period): ?array
{
    $bounds = ai_period_bounds($period);
    if ($bounds === null) {
        return null;
    }
    [$start, $end] = $bounds;
    $p = find_ai_period($pdo, $start);
    $lines = array_map('present_ai_statement_line', find_ai_statement_lines($pdo, $start));
    $totals = [];
    foreach ($lines as $l) {
        $t = &$totals[$l['currency']];
        $t = ($t ?? ['currency' => $l['currency'], 'calls' => 0, 'late_calls' => 0, 'input_tokens' => 0, 'output_tokens' => 0, 'cache_read_tokens' => 0, 'cache_write_tokens' => 0, 'amount' => '0']);
        foreach (['calls', 'late_calls', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens'] as $k) { $t[$k] += $l[$k]; }
        $t['amount'] = number_format((float) $t['amount'] + (float) $l['amount'], 4, '.', '');
        unset($t);
    }
    return [
        'schema' => LEDGER_PERIOD_SCHEMA,
        'business' => business_name($pdo),
        'period' => $period, 'period_start' => $start, 'period_end' => $end,
        'status' => $p['status'] ?? 'open',
        'closed_at' => json_ts($p['closed_at'] ?? null),
        'rolled_up_at' => json_ts($p['rolled_up_at'] ?? null),
        'currencies' => array_values(array_keys($totals)),
        'exchange' => 'none — each line in the currency the provider billed; nothing is converted',
        'amount_scale' => 4,
        'generated_at' => gmdate('Y-m-d\TH:i:s\Z'),
        'lines' => $lines,
        'totals' => array_values($totals),
    ];
}

/** The same document as CSV: one header, one row per line, one totals row per currency. */
function ai_period_csv(array $doc): string
{
    $out = fopen('php://temp', 'r+');
    fputcsv($out, ['schema', 'business', 'period', 'period_start', 'period_end', 'status', 'closed_at', 'generated_at']);
    fputcsv($out, [$doc['schema'], $doc['business'], $doc['period'], $doc['period_start'], $doc['period_end'], $doc['status'], $doc['closed_at'] ?? '', $doc['generated_at']]);
    fputcsv($out, []);
    $cols = ['provider', 'model', 'department', 'agent', 'application', 'calls', 'late_calls', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'amount', 'currency', 'note'];
    fputcsv($out, $cols);
    foreach ($doc['lines'] as $l) {
        fputcsv($out, array_map(static fn (string $c) => $l[$c] ?? '', $cols));
    }
    foreach ($doc['totals'] as $t) {
        fputcsv($out, ['TOTAL', '', '', '', '', $t['calls'], $t['late_calls'], $t['input_tokens'], $t['output_tokens'], $t['cache_read_tokens'], $t['cache_write_tokens'], $t['amount'], $t['currency'], '']);
    }
    rewind($out);
    return (string) stream_get_contents($out);
}
