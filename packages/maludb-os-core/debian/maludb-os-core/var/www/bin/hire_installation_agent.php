<?php
declare(strict_types=1);

/**
 * Hire the application installation agent into IT — part of an install, after the migrations
 * (db/149 makes IT a standing department) and the first organizer. Run once; running it again
 * is a no-op that says so.
 *
 *   php bin/hire_installation_agent.php --by you@example.com [--model claude-fable-5-1]
 *        [--agent-email installer@agents.example.com] [--plugin-dir ~/maludb-os-integration]
 *
 * --by is the super-admin the hire is recorded under (default: the first active super-admin).
 * --model is a model_registry key on the claude_agent_sdk harness (default: its first active one).
 * The agent's email defaults to installer@agents.<domain>, the domain taken from the agents
 * already hired, else from the super-admin's address.
 *
 * What it gets: a job description (below), tools on the kernel's own MCP endpoints — read the
 * catalog and the applications, register an application, its endpoints and scopes, refresh its
 * roles, propose its expert, check its health, assign the skills it ships, raise an escalation —
 * and the maludb-os-integration plugin's three skills (os-integration, os-adopt, os-install),
 * imported into the skill library and assigned to it. It never holds the application's token
 * (a person mints that on the Overview) and, by the db/149 policies, its registrations pause for
 * its approver. Root on the server is nobody's here: it writes the files and asks.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/agents/render.php';
require_once dirname(__DIR__) . '/app/features/skills/import.php';
agents_require_files();

$opts = getopt('', ['by:', 'model:', 'agent-email:', 'plugin-dir:']);
$pdo = db();

// Who hires.
$by = null;
if (isset($opts['by'])) {
    $by = find_member_by_email($pdo, normalize_email((string) $opts['by']));
} else {
    $st = $pdo->query("SELECT * FROM members WHERE business_role = 'super_admin' AND member_kind = 'human' AND status = 'active' ORDER BY id LIMIT 1");
    $by = $st->fetch() ?: null;
}
if ($by === null || ($by['business_role'] ?? '') !== 'super_admin') {
    fwrite(STDERR, "The hire is recorded under a super-admin: --by <email>.\n");
    exit(1);
}
$byId = (int) $by['id'];
$_SESSION['member_id'] = $byId;
$_SESSION['member_role'] = $by['role'] ?? 'organizer';
db_apply_context($pdo);

// Where: the standing IT department (db/149) at its home office, managed by its manager or the hirer.
$it = $pdo->query("SELECT * FROM departments WHERE system_key = 'it'")->fetch();
if ($it === false) {
    fwrite(STDERR, "No standing IT department — run db/149 first.\n");
    exit(1);
}

// The address.
$agentEmail = isset($opts['agent-email']) ? normalize_email((string) $opts['agent-email']) : null;
if ($agentEmail === null) {
    $domain = $pdo->query("SELECT split_part(email, '@', 2) FROM members WHERE member_kind = 'agent' AND email LIKE '%@agents.%' ORDER BY id LIMIT 1")->fetchColumn();
    if ($domain === false || $domain === '') {
        $domain = 'agents.' . substr((string) $by['email'], strpos((string) $by['email'], '@') + 1);
    }
    $agentEmail = 'installer@' . $domain;
}
$existing = find_member_by_email($pdo, $agentEmail);

// On what: a model on the Claude harness (the skills travel as a plugin — A7, claude_render.py).
$modelKey = (string) ($opts['model'] ?? '');
$st = $pdo->prepare("SELECT * FROM model_registry WHERE status = 'active' AND harness = 'claude_agent_sdk' AND (:k = '' OR model_key = :k2) ORDER BY id LIMIT 1");
$st->execute(['k' => $modelKey, 'k2' => $modelKey]);
$model = $st->fetch();
if ($model === false) {
    fwrite(STDERR, "No active model on the claude_agent_sdk harness" . ($modelKey !== '' ? " with key {$modelKey}" : '') . ".\n");
    exit(1);
}

// The skills it ships with: the integration contract, as the plugin states it.
$pluginDir = rtrim((string) ($opts['plugin-dir'] ?? ''), '/');
foreach ([$pluginDir, getenv('HOME') . '/maludb-os-integration', '/home/maludb/maludb-os-integration', '/opt/maludb-os-integration'] as $candidate) {
    if ($candidate !== '' && is_dir($candidate . '/skills/os-install')) { $pluginDir = $candidate; break; }
}
$skillNames = [];
if ($pluginDir !== '' && is_dir($pluginDir . '/skills')) {
    foreach (['os-integration', 'os-adopt', 'os-install'] as $skill) {
        [$ingested, $error] = import_skill_folder($pdo, $pluginDir . '/skills/' . $skill, $byId);
        if ($error !== null) {
            fwrite(STDERR, "skill {$skill}: {$error}\n");
            continue;
        }
        $skillNames[] = $ingested['name'];
        echo ($ingested['reused'] ? 'Skill unchanged' : 'Skill imported') . ": {$ingested['name']}\n";
    }
} else {
    fwrite(STDERR, "note: the maludb-os-integration plugin was not found (--plugin-dir); the agent is hired without its three skills — assign them later.\n");
}

// Its tools, on the kernel's own endpoints.
$endpoints = [];
$st = $pdo->query("SELECT e.id, e.name FROM application_endpoints e JOIN applications a ON a.id = e.application_id
                    WHERE a.name = 'Business OS' AND e.kind = 'mcp' AND e.name IN ('Records MCP', 'Actions MCP', 'Activity MCP')");
foreach ($st->fetchAll() as $e) { $endpoints[$e['name']] = (int) $e['id']; }
$wanted = [
    'Records MCP' => ['find_applications', 'get_application', 'application_scopes', 'skill_catalog', 'find_departments', 'get_department', 'records_search'],
    'Actions MCP' => ['application_catalog_save', 'application_save', 'application_set_status', 'application_endpoint_save', 'application_endpoint_remove',
                      'application_roles_refresh', 'application_scope_add', 'application_sme_set', 'application_health_check', 'skill_assign', 'escalation_raise'],
    'Activity MCP' => ['record_history', 'system_jobs'],
];
$tools = [];
foreach ($wanted as $endpoint => $names) {
    if (!isset($endpoints[$endpoint])) { fwrite(STDERR, "note: no '{$endpoint}' endpoint on Business OS — its tools are not granted.\n"); continue; }
    foreach ($names as $name) { $tools[] = ['application_endpoint_id' => $endpoints[$endpoint], 'tool_name' => $name, 'constraints' => []]; }
}

$jobDescription = <<<'TXT'
You are the application installation agent. You work in IT and report to its manager. You help the business install and integrate applications with the Business OS kernel: applications from us (a separate Apache/PHP/HTMX application with its own database, memory and MCP servers, declared by maludb-os.json at its repository root), an existing application being adopted, and third-party products reached through an MCP server. You know the integration contract from your skills (os-integration, os-adopt, os-install) and you follow it rather than improvise.

How you work, every time:
1. Understand what is being installed: read its maludb-os.json (or, for a product, what its MCP server offers), its roles and rights, its scope kind, its endpoints and the skills it ships. Ask the person for what the declaration does not say — the DNS name, the port behind the proxy, which departments or sites it serves — and never guess a secret.
2. Plan before you touch anything: say what you will register (the catalog entry, the application record with its sso_path and sso_logout_path, each endpoint, each scope, its roles), what a person must do (mint the application's token on its Overview, create the DNS record, install the vhost, proxy entry and systemd units you write out), and what the application must be able to reach (the directory API, the chat endpoint, the ledger). Put the plan in your reply as numbered steps.
3. Apply through your tools, in order: application_catalog_save → application_save → application_endpoint_save for each endpoint → application_scope_add → application_roles_refresh once the application publishes its roles → application_sme_set to propose its expert → skill_assign for the skills it ships, at application scope → application_health_check. Each registration waits for your approver's approval by policy; that is expected — say what waits, and do not repeat the request.
4. Verify: the health check answers, the launcher shows the application, sign-on lands on its sso_path, and the expert answers a question from the shipped skills. Report what passed and what did not, plainly.

What you never do: hold or ask for a model key or the application's token (a person mints it); run commands as root or edit Apache, DNS or systemd yourself — you write the exact files and the exact commands and ask IT's manager to apply them; send anything about this installation anywhere outside this server; delete an application, an endpoint or a scope without being told to. When something is in the way — a missing endpoint, a refused registration, a contract the application does not meet — raise an escalation naming exactly what is missing rather than working around it.
TXT;

$fields = [
    'email' => $agentEmail, 'name' => 'Installer', 'job_title' => 'Application installation agent',
    'description' => 'Installs and integrates applications with the kernel — from us, adopted, or third-party through MCP — planning first, applying through the kernel, asking a person for root and for secrets.',
    'department_id' => (int) $it['id'],
    'manager_member_id' => $it['manager_member_id'] !== null ? (int) $it['manager_member_id'] : $byId,
    'model_id' => (int) $model['id'], 'monthly_budget_amount' => '20.00', 'budget_currency' => 'USD',
    'home_location_id' => $it['home_location_id'] !== null ? (int) $it['home_location_id'] : null,
    'role_key' => 'installer', 'agent_kind' => 'subagent', 'phone_number' => null,
    'job_description' => $jobDescription, 'parameters' => [], 'tools' => $tools, 'duties' => [],
];
if ($existing !== null) {
    $memberId = (int) $existing['id'];
    echo "Already hired: {$agentEmail} (member {$memberId}) — checking its skills.\n";
} else {
    $agent = hire_agent($pdo, $fields, $byId);
    $memberId = (int) $agent['agent_member_id'];
    log_activity($pdo, 'agent.hire', 'member', $memberId, [
        'source' => 'cron',
        'after' => ['name' => 'Installer', 'department' => $it['name'], 'model' => $model['model_key'], 'tools' => count($tools), 'by' => 'bin/hire_installation_agent.php'],
    ]);
    echo "Hired: Installer (member {$memberId}) in {$it['name']} on {$model['display_name']}, " . count($tools) . " tools.\n";
}

// Its skills — the same rows skill_assign writes, at agent scope; a skill it already holds is left alone.
$assigned = 0;
foreach ($skillNames as $skill) {
    $st = $pdo->prepare("SELECT 1 FROM skill_assignments WHERE skill_name = :s AND scope_kind = 'agent' AND agent_member_id = :m AND revoked_at IS NULL");
    $st->execute(['s' => $skill, 'm' => $memberId]);
    if ($st->fetchColumn() !== false) { continue; }
    $pdo->prepare("INSERT INTO skill_assignments (skill_name, scope_kind, agent_member_id, note, assigned_by)
                   VALUES (:s, 'agent', :m, 'Shipped with the installation agent', :by)")
        ->execute(['s' => $skill, 'm' => $memberId, 'by' => $byId]);
    log_activity($pdo, 'skill.assign', 'member', $memberId, ['source' => 'cron', 'after' => ['skill_name' => $skill, 'scope_kind' => 'agent']]);
    $assigned++;
}
echo "Skills: " . count($skillNames) . " shipped, {$assigned} newly assigned.\n";
