<?php
declare(strict_types=1);

/**
 * Proof of K38 — the run facts say who an agent's run acts for (docs/build-specs/kernel-run-facts-requester.md). Read-only: it reads
 * existing agent_runs rows and changes nothing.
 *
 *   php bin/test_run_facts_requester.php
 *
 * Covers: a chat run answers its requester and whether they hold the application (the same holding the sign-on claims use); a duty, an
 * evaluation and a message answer nobody; a run asked of the wrong agent answers nobody; the endpoint carries the three keys.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/applications/sso.php';

$pdo = db();
$fails = 0; $n = 0;
$ok = static function (bool $c, string $label) use (&$fails, &$n): void { $n++; if (!$c) { $fails++; } echo ($c ? '  ok   ' : '  FAIL ') . $label . "\n"; };
$one = static function (string $sql) use ($pdo): ?array { $r = $pdo->query($sql)->fetch(); return $r ?: null; };

$app = $one("SELECT id, name FROM applications ORDER BY id LIMIT 1");
if ($app === null) { echo "  skip: no application registered\n"; exit(0); }
$appId = (int) $app['id'];

$chat = $one("SELECT id, agent_member_id, requested_by FROM agent_runs WHERE trigger = 'chat' AND requested_by IS NOT NULL AND requested_by <> agent_member_id ORDER BY id DESC LIMIT 1");
if ($chat !== null) {
    $f = run_facts_requester($pdo, $appId, (int) $chat['id'], (int) $chat['agent_member_id']);
    $ok($f['requested_by_member_id'] === (int) $chat['requested_by'], 'a chat run answers the person it acts for');
    $holding = sso_member_holding($pdo, $appId, (int) $chat['requested_by']);
    $active = (string) $pdo->query('SELECT status FROM members WHERE id = ' . (int) $chat['requested_by'])->fetchColumn() === 'active';
    $ok($f['requested_by_holds'] === ($active && $holding['capability'] !== null), 'and whether they hold the application — the sign-on claims\' holding');
    $ok(in_array($f['requested_by_kind'], ['human', 'agent'], true), 'and whether the requester is a person or an orchestrating agent');
    $wrong = run_facts_requester($pdo, $appId, (int) $chat['id'], (int) $chat['agent_member_id'] + 100000);
    $ok($wrong['requested_by_member_id'] === null, 'a run asked of another agent answers nobody');
} else {
    echo "  skip: no chat run with a requester on this host\n";
}
foreach (['duty', 'eval', 'message'] as $trigger) {
    $r = $one("SELECT id, agent_member_id FROM agent_runs WHERE trigger = '$trigger' ORDER BY (requested_by IS NULL), id DESC LIMIT 1");
    if ($r === null) { echo "  skip: no $trigger run on this host\n"; continue; }
    $f = run_facts_requester($pdo, $appId, (int) $r['id'], (int) $r['agent_member_id']);
    $ok($f['requested_by_member_id'] === null && $f['requested_by_holds'] === false, "a $trigger run acts as the agent alone — nobody named");
}
$src = (string) file_get_contents(dirname(__DIR__) . '/html/api/v1/runs/facts.php');
$ok(str_contains($src, 'run_facts_requester(') && str_contains($src, "'requested_by_member_id' => null"), 'the endpoint answers the three keys for every caller (null for a person\'s token)');

echo "\n$n checks, $fails failed\n";
exit($fails === 0 ? 0 : 1);
