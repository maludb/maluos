<?php
declare(strict_types=1);

/** Screen `ai-spend` — cost, tokens, latency and cache savings (params: period, group_by). The rows are what mcp_prompt_ledger shows the caller. */
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/queries.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/request.php';
require_once dirname(__DIR__, 3) . '/app/features/aiops/present.php';

require_insider();

$pdo = db();
$period = isset(AIOPS_PERIODS[request_string('period')]) ? request_string('period') : 'this_month';
$group = isset(AIOPS_GROUPS[request_string('group_by')]) ? request_string('group_by') : 'agent';
log_screen_view($pdo, 'ai-spend');
$rows = array_map('present_ai_spend_row', find_ai_spend($pdo, $period, $group));
$named = static fn (array $l): array => array_map(static fn (string $k, string $v): array => ['id' => $k, 'name' => $v], array_keys($l), $l);
respond_screen([
    'period' => $period, 'group_by' => $group, 'rows' => $rows,
    'totals' => ['calls' => array_sum(array_column($rows, 'calls')), 'failed' => array_sum(array_column($rows, 'failed')),
                 'cost' => number_format(array_sum(array_map('floatval', array_column($rows, 'cost'))), 6, '.', ''),
                 'cache_saving' => number_format(array_sum(array_map('floatval', array_column($rows, 'cache_saving'))), 4, '.', ''),
                 'tokens' => array_sum(array_column($rows, 'input_tokens')) + array_sum(array_column($rows, 'output_tokens')),
                 'currency' => $rows[0]['currency'] ?? 'USD'],
    'sees_everything' => has_module_grant('ledger'),
    'options' => ['periods' => $named(AIOPS_PERIODS), 'groups' => $named(AIOPS_GROUPS)],
]);
