<?php
declare(strict_types=1);

/**
 * Proof of the model form's "Bills to" rules — docs/build-specs/claude-subscription-auth.md, db/164–166. Nothing is kept:
 * the database part runs in a transaction that is rolled back, and nothing calls a model.
 *
 *   php bin/test_model_auth_mode.php
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/agents/render.php';
agents_require_files();

$pdo = db();
$_SESSION['member_id'] = (int) $pdo->query("SELECT id FROM members WHERE business_role = 'super_admin' AND status = 'active' AND member_kind = 'human' ORDER BY id LIMIT 1")->fetchColumn();
db_apply_context($pdo);
$fails = 0;
$ok = static function (bool $c, string $label) use (&$fails): void { if (!$c) { $fails++; } echo ($c ? '  ok   ' : '  FAIL ') . $label . "\n"; };

$fields = static function (array $post): array {
    $_POST = $post + ['model_key' => 'test-max', 'display_name' => 'Test Max', 'provider' => 'anthropic', 'provider_model_id' => 'claude-sonnet-5',
                      'harness' => 'claude_agent_sdk', 'status' => 'active'];
    return model_fields_from_request();
};

echo "Validation\n";
[$f, $e] = $fields(['auth_mode' => 'claude_subscription']);
$ok($e === [] && $f['auth_mode'] === 'claude_subscription', 'Anthropic on claude_agent_sdk may bill to the Max plan');
[$f, $e] = $fields([]);
$ok($e === [] && $f['auth_mode'] === 'api_key', 'the default is an API key');
[, $e] = $fields(['auth_mode' => 'claude_subscription', 'provider' => 'openai']);
$ok($e !== [] && str_contains($e[0], 'Anthropic'), 'another provider may not');
[, $e] = $fields(['auth_mode' => 'claude_subscription', 'harness' => 'hermes']);
$ok($e !== [] && str_contains($e[0], 'claude_agent_sdk'), 'Hermes may not (it presents itself as Claude Code)');
[, $e] = $fields(['auth_mode' => 'free-money']);
$ok($e !== [], 'an unknown way of billing is refused');

echo "Saving, refusal, rollback\n";
$pdo->beginTransaction();
try {
    [$f] = $fields(['auth_mode' => 'claude_subscription', 'model_key' => 'test-max-' . date('His'), 'price_input_per_mtok' => '3', 'price_output_per_mtok' => '15']);
    $m = upsert_model($pdo, null, $f);
    $ok(($m['auth_mode'] ?? '') === 'claude_subscription', 'a Max-plan model is saved as one');
    $ok(model_in_use($pdo, (int) $m['model_id']) === false, 'a new model is not in use');
    $ok(model_in_use($pdo, 3) === true, 'a model an agent uses is in use (its billing may not change)');
    $err = agent_harness_error($m);
    $health = runner_request('GET', '/health');
    $on = $health['status'] === 200 ? !empty($health['body']['subscription']) : null;
    $ok($on === null || ($on ? $err === null : ($err !== null && str_contains($err, 'switched off'))),
        'hiring onto it is refused exactly while the runner switch is off (' . ($on === null ? 'runner not asked' : ($on ? 'switch on' : 'switch off')) . ')');
    $edit = $f; $edit['auth_mode'] = 'api_key';
    $back = upsert_model($pdo, (int) $m['model_id'], $edit);
    $ok(($back['auth_mode'] ?? '') === 'api_key', 'an unused model can change how it bills');
    $st = $pdo->prepare("SELECT count(*) FROM model_registry WHERE model_key = :k");
    try { $pdo->exec('SAVEPOINT s'); $pdo->exec("INSERT INTO model_registry (model_key, display_name, provider, provider_model_id, harness, auth_mode)
                       VALUES ('bad-max', 'Bad', 'openai', 'x', 'hermes', 'claude_subscription')"); $ok(false, 'the database refuses a Max-plan model off Claude Code');
    } catch (PDOException) { $pdo->exec('ROLLBACK TO SAVEPOINT s'); $ok(true, 'the database itself refuses a Max-plan model off Claude Code'); }
} finally {
    $pdo->rollBack();
}
echo $fails === 0 ? "\nAll passed.\n" : "\n$fails FAILED.\n";
exit($fails === 0 ? 0 : 1);
