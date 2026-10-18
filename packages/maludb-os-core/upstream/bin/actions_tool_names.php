<?php
declare(strict_types=1);

/**
 * K55 (2026-10-11; docs/build-specs/kernel-action-tool-names.md) — give every application action on the kernel's Actions MCP a
 * name of its own, and move the agents' grants with it.
 *
 *   php bin/actions_tool_names.php [plan]            read-only: what would be renamed and which grants would move
 *   php bin/actions_tool_names.php apply [--by email] writes `tool_name` into mcp/registries/*.json (a copy of each file kept in
 *                                                    mcp/registries/backup-<time>/), moves the grants in one transaction, and
 *                                                    says to restart maludb-os-actions-mcp
 *
 * The rule (app/features/applications/action_tool_names.php): an action keeps its own name when no other application and no
 * kernel action uses it; a shared name becomes "<app_key>_<action>" for every application that has it. A live grant on the
 * Actions MCP whose name is no longer served moves to the tool of the one application the agent works for (the applications
 * whose MCP endpoints it holds grants on) that has that action; a grant that matches none or several is listed and left alone.
 * A grant on a KERNEL action's name held by an agent of an application that has an action of that name (ProcessCore's expert and
 * `mcp_token_create`, from its manifest) was being served the kernel's tool: it moves to the application's, listed apart.
 * Idempotent: a second run changes nothing.
 */

require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/agents/queries.php';
require_once dirname(__DIR__) . '/app/features/applications/action_tool_names.php';

$args = array_slice($GLOBALS['argv'], 1);
$mode = 'plan';
$byEmail = null;
for ($i = 0; $i < count($args); $i++) {
    if ($args[$i] === 'apply' || $args[$i] === 'plan') { $mode = $args[$i]; }
    elseif ($args[$i] === '--by') { $byEmail = $args[++$i] ?? null; }
    else { fwrite(STDERR, "Usage: php bin/actions_tool_names.php [plan|apply] [--by <super-admin email>]\n"); exit(2); }
}
$KERNEL = dirname(__DIR__);
$dir = $KERNEL . '/mcp/registries';
$pdo = db();

// ---- the names ---------------------------------------------------------------------------------------------------------------
$kernelNames = kernel_action_names($KERNEL);
$registries = load_action_registries($dir);
[$named, $clashes] = assign_all_tool_names($registries, $kernelNames);

$served = $kernelNames;                       // every name the server will answer to afterwards
$byApp = [];                                  // app_key => [action => tool]
$renamed = 0;
$total = 0;
foreach ($named as $key => $file) {
    foreach (registry_built_actions($file) as $a) {
        if (!isset($a['tool_name'])) { continue; }
        $served[$a['tool_name']] = true;
        $byApp[$key][(string) $a['action']] = (string) $a['tool_name'];
        $total++;
        if ($a['tool_name'] !== $a['action']) { $renamed++; }
    }
}
$before = 0;                                  // what the server registers today (first registry wins, the rest skipped)
$seen = $kernelNames;
foreach ($registries as $file) {
    foreach (registry_built_actions($file) as $a) {
        $n = action_tool_name($a);
        if (!isset($seen[$n])) { $seen[$n] = true; $before++; }
    }
}
$allBuilt = array_sum(array_map(static fn (array $f): int => count(registry_built_actions($f)), $registries));
echo "Registries: " . count($registries) . ", built actions: {$allBuilt}, kernel actions: " . count($kernelNames) . ".\n";
echo "Served today: {$before} of {$allBuilt}. Served after: {$total} of {$allBuilt}; {$renamed} under '<app_key>_<action>'.\n";
foreach ($named as $key => $file) {
    $changes = [];
    foreach (registry_built_actions($file) as $actionKey => $a) {
        $old = isset($registries[$key]['registry']['actions'][$actionKey]) ? action_tool_name($registries[$key]['registry']['actions'][$actionKey]) : null;
        if (isset($a['tool_name']) && $a['tool_name'] !== $old) { $changes[] = "{$a['action']} → {$a['tool_name']}"; }
    }
    if ($changes !== []) { echo "  {$key}: " . count($changes) . " renamed — " . implode(', ', $changes) . "\n"; }
}
foreach ($clashes as $key => $list) {
    foreach ($list as $action => $why) { echo "  CLASH {$key}: {$action} — {$why} (not served)\n"; }
}

// ---- the grants --------------------------------------------------------------------------------------------------------------
$actionsEndpoint = $pdo->query("SELECT e.id FROM application_endpoints e JOIN applications a ON a.id = e.application_id
                                 WHERE a.name = 'Business OS' AND e.kind = 'mcp' AND e.name = 'Actions MCP'")->fetchColumn();
$moves = [];
$unclear = [];
if ($actionsEndpoint !== false) {
    $st = $pdo->prepare(<<<'SQL'
        SELECT g.id, g.agent_member_id, g.tool_name, g.constraints, m.display_name,
               COALESCE((SELECT array_to_json(array_agg(DISTINCT a2.catalog_key))
                           FROM agent_tool_grants g2 JOIN application_endpoints e2 ON e2.id = g2.application_endpoint_id
                           JOIN applications a2 ON a2.id = e2.application_id
                          WHERE g2.agent_member_id = g.agent_member_id AND g2.revoked_at IS NULL
                            AND e2.id <> :ep AND a2.catalog_key IS NOT NULL), '[]') AS apps
          FROM agent_tool_grants g JOIN members m ON m.id = g.agent_member_id
         WHERE g.application_endpoint_id = :ep AND g.revoked_at IS NULL
         ORDER BY g.agent_member_id, g.tool_name
    SQL);
    $st->execute(['ep' => (int) $actionsEndpoint]);
    foreach ($st->fetchAll() as $g) {
        $tool = (string) $g['tool_name'];
        $apps = json_decode((string) $g['apps'], true) ?: [];
        $hits = [];
        foreach ($apps as $k) { if (isset($byApp[$k][$tool]) && $byApp[$k][$tool] !== $tool) { $hits[$k] = $byApp[$k][$tool]; } }
        $kernelName = isset($kernelNames[$tool]);
        if (isset($served[$tool]) && !($kernelName && count($hits) === 1)) { continue; }   // still served, and meant: leave it
        $owners = array_keys(array_filter($byApp, static fn (array $m): bool => isset($m[$tool])));
        if (count($hits) === 1) {
            $moves[] = ['grant' => (int) $g['id'], 'agent' => (int) $g['agent_member_id'], 'name' => (string) $g['display_name'],
                        'from' => $tool, 'to' => reset($hits), 'app' => array_key_first($hits),
                        'constraints' => json_decode((string) $g['constraints'], true) ?: [], 'kernel_name' => $kernelName];
        } else {
            $unclear[] = "{$g['display_name']} (agent {$g['agent_member_id']}): {$tool} — "
                . ($owners === [] ? 'no application has this action' : (count($hits) === 0
                    ? 'it works for none of ' . implode(', ', $owners) : 'it works for several: ' . implode(', ', array_keys($hits))));
        }
    }
}
echo "Grants on the Actions MCP: " . count($moves) . " to move to the agent's own application's tool, " . count($unclear) . " left for a person.\n";
foreach ($moves as $mv) {
    echo '  move  ' . "{$mv['name']} (agent {$mv['agent']}): {$mv['from']} → {$mv['to']}"
        . ($mv['kernel_name'] ? "  — was being served the KERNEL's {$mv['from']}" : '') . "\n";
}
foreach ($unclear as $u) { echo "  LEFT  {$u}\n"; }

if ($mode === 'plan') {
    echo "\nPlan only — nothing changed. To apply: php bin/actions_tool_names.php apply, then sudo systemctl restart maludb-os-actions-mcp\n";
    exit($clashes === [] ? 0 : 1);
}

// ---- apply -------------------------------------------------------------------------------------------------------------------
if ($clashes !== []) { fwrite(STDERR, "Refused: resolve the clashes above first; nothing was changed.\n"); exit(1); }
$by = $byEmail !== null
    ? find_member_by_email($pdo, normalize_email($byEmail))
    : ($pdo->query("SELECT * FROM members WHERE business_role = 'super_admin' AND member_kind = 'human' AND status = 'active' ORDER BY id LIMIT 1")->fetch() ?: null);
if ($by === null || ($by['business_role'] ?? '') !== 'super_admin') { fwrite(STDERR, "The change is recorded under a super-admin: --by <email>.\n"); exit(1); }
$byId = (int) $by['id'];
$_SESSION['member_id'] = $byId;
$_SESSION['member_role'] = $by['role'] ?? 'organizer';
db_apply_context($pdo);

// The registry files: a copy of each, then the new contents in place (owner, group and mode kept).
$backup = $dir . '/backup-' . date('Ymd-His');
$written = 0;
foreach ($named as $key => $file) {
    $path = $dir . '/' . $key . '.json';
    $json = json_encode($file, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";
    if (is_file($path) && file_get_contents($path) === $json) { continue; }
    if (!is_dir($backup) && !mkdir($backup, 0775)) { fwrite(STDERR, "Could not make {$backup}; nothing was changed.\n"); exit(1); }
    if (!copy($path, $backup . '/' . $key . '.json')) { fwrite(STDERR, "Could not copy {$path}; stopped.\n"); exit(1); }
    if (file_put_contents($path, $json) === false) { fwrite(STDERR, "Could not write {$path}; stopped (the copy is in {$backup}).\n"); exit(1); }
    $written++;
}

// The grants, in one transaction: the old name revoked, the new one granted with the same constraints, each logged.
$pdo->beginTransaction();
try {
    foreach ($moves as $mv) {
        revoke_agent_tool($pdo, $mv['grant']);
        log_activity($pdo, 'agent_tool_grant.revoke', 'member', $mv['agent'], ['source' => 'cron', 'before' => [
            'application_endpoint_id' => (int) $actionsEndpoint, 'tool_name' => $mv['from'], 'by' => 'bin/actions_tool_names.php (K55)']]);
        grant_agent_tool($pdo, $mv['agent'], (int) $actionsEndpoint, $mv['to'], $mv['constraints'], $byId);
        log_activity($pdo, 'agent_tool_grant.create', 'member', $mv['agent'], ['source' => 'cron', 'after' => [
            'application_endpoint_id' => (int) $actionsEndpoint, 'tool_name' => $mv['to'], 'constraints' => $mv['constraints'],
            'application' => $mv['app'], 'replaces' => $mv['from'], 'by' => 'bin/actions_tool_names.php (K55)']]);
    }
    $pdo->commit();
} catch (Throwable $e) {
    $pdo->rollBack();
    fwrite(STDERR, "The grants were NOT moved (rolled back): {$e->getMessage()}\nThe registry files were written; their copies are in {$backup}.\n");
    exit(1);
}
echo "\nApplied: {$written} registry file(s) written" . ($written > 0 ? " (copies in {$backup})" : '') . ", " . count($moves) . " grant(s) moved.\n";
echo "Now: sudo systemctl restart maludb-os-actions-mcp\n";
