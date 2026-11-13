<?php
declare(strict_types=1);

/**
 * Hire the three watching agents into IT (db/196; MaluOS Phase 14 slice 4c, maluos docs/phase14-watching-agents.md):
 * the database administrator, the Linux administrator and the security officer. Part of an install, after the
 * migrations and the first organizer. Run once; running it again hires only what is missing and says so.
 *
 *   php bin/hire_watch_agents.php [--by you@example.com] [--only postgres,linux,security] [--every 10]
 *
 * --by     the super-admin the hires are recorded under (default: the first active super-admin).
 * --only   hire some of the three.
 * --every  minutes between passes (default 10: the kernel samples a node's numbers every ten minutes).
 *
 * Each is a system_one agent (the harness of the Auditor and the Sysadmin) with one playbook as its duty:
 * watch_postgres, watch_linux, watch_security. They read the estate's node reports and the samples of their numbers,
 * which the kernel already holds; they connect to no other server and ask no model: a check is a number against a
 * threshold in the agent's versioned config (runtime_config.thresholds, .expected_ports). Like every system_one
 * agent they start in SHADOW: every decision is recorded, nothing is sent, until a person sets mode to live.
 * In live mode a finding goes to the agent's approver (in IT: the department's manager) through escalation_raise.
 * Their second tool, estate_node_action (db/197), asks a node for one of its fixed verbs when a check has one
 * bounded answer (end a session idle in a transaction for hours, restart a failed unit of the role's list, apply
 * security updates left for days): every such request pauses for the approver, and the node has the last word.
 */
if (PHP_SAPI !== 'cli') { fwrite(STDERR, "CLI only.\n"); exit(1); }
require_once dirname(__DIR__) . '/app/bootstrap.php';
require_once dirname(__DIR__) . '/app/features/agents/render.php';
agents_require_files();

$opts = getopt('', ['by:', 'only:', 'every:']);
$pdo = db();

$by = null;
if (isset($opts['by'])) {
    $by = find_member_by_email($pdo, normalize_email((string) $opts['by']));
} else {
    $by = $pdo->query("SELECT * FROM members WHERE business_role = 'super_admin' AND member_kind = 'human' AND status = 'active' ORDER BY id LIMIT 1")->fetch() ?: null;
}
if ($by === null || ($by['business_role'] ?? '') !== 'super_admin') {
    fwrite(STDERR, "The hires are recorded under a super-admin: --by <email>.\n");
    exit(1);
}
$byId = (int) $by['id'];
$_SESSION['member_id'] = $byId;
$_SESSION['member_role'] = $by['role'] ?? 'organizer';
db_apply_context($pdo);

$it = $pdo->query("SELECT * FROM departments WHERE system_key = 'it'")->fetch();
if ($it === false) {
    fwrite(STDERR, "No standing IT department: run db/149 first.\n");
    exit(1);
}
if ($pdo->query("SELECT to_regprocedure('watch_nodes()') IS NOT NULL")->fetchColumn() !== true) {
    fwrite(STDERR, "db/196 is not applied (no watch_nodes()).\n");
    exit(1);
}
$model = $pdo->query("SELECT * FROM model_registry WHERE status = 'active' AND harness = 'system_one' ORDER BY id LIMIT 1")->fetch();
if ($model === false) {
    fwrite(STDERR, "No active model on the system_one harness (db/145 registers it).\n");
    exit(1);
}
$every = max(1, min(59, (int) ($opts['every'] ?? 10)));
$domain = $pdo->query("SELECT split_part(email, '@', 2) FROM members WHERE member_kind = 'agent' AND email LIKE '%@agents.%' ORDER BY id LIMIT 1")->fetchColumn();
if ($domain === false || $domain === '') {
    $domain = 'agents.' . substr((string) $by['email'], strpos((string) $by['email'], '@') + 1);
}

// Their two tools, used only in live mode: raising an escalation to their approver, and asking a node for a verb.
$tools = [];
$st = $pdo->query("SELECT e.id FROM application_endpoints e JOIN applications a ON a.id = e.application_id
                    WHERE a.name = 'Business OS' AND e.kind = 'mcp' AND e.name = 'Actions MCP' ORDER BY e.id LIMIT 1");
$actions = $st->fetchColumn();
if ($actions !== false) {
    $tools[] = ['application_endpoint_id' => (int) $actions, 'tool_name' => 'escalation_raise', 'constraints' => []];
    // db/197: asking a node for one of its fixed verbs; every request of an agent's pauses for its approver
    $tools[] = ['application_endpoint_id' => (int) $actions, 'tool_name' => 'estate_node_action', 'constraints' => []];
} else {
    fwrite(STDERR, "note: no 'Actions MCP' endpoint on Business OS: the agents are hired without escalation_raise and estate_node_action (grant them before setting them live).\n");
}

$common = "\n\nHow you work: you run one playbook on a schedule. It reads each node's last report and the samples of its numbers that the kernel keeps; you connect to no other server and you ask no model. A check is a number against a threshold in your config. You record a decision only when a check's state changes. You start in shadow mode: you record what you would have raised and send nothing, until a person sets you live. Live, you raise a finding to your approver with the node, the number and the time. Where a finding has one bounded answer you ask the node for it (end a session, restart a unit of its list, apply updates); every such request waits for your approver, and you never act without that approval.";
$agents = [
    'postgres' => [
        'local' => 'dba', 'name' => 'Database administrator', 'role_key' => 'dba', 'playbook' => 'watch_postgres', 'minute' => 1,
        'description' => 'Watches PostgreSQL on every node that runs a cluster: connections, long transactions and lock waits, dead rows and vacuum age, transaction-id age, replication, the server certificate, the server log\'s error counts, new superusers. Read-only; findings advise.',
        'job' => 'You are the database administrator. You work in IT and report to its manager. You watch PostgreSQL on every node of the estate that runs a cluster for others: the database server, or a single server that holds its own data.' . $common,
    ],
    'linux' => [
        'local' => 'linux-admin', 'name' => 'Linux administrator', 'role_key' => 'linux_admin', 'playbook' => 'watch_linux', 'minute' => 3,
        'description' => 'Watches every server of the estate: whether it still reports, disks and how fast they fill, failed units, a pending reboot, the clock, inodes, memory. Read-only; findings advise.',
        'job' => 'You are the Linux administrator. You work in IT and report to its manager. You watch every server of the estate: the kernel server, the database server and the application servers.' . $common,
    ],
    'security' => [
        'local' => 'security', 'name' => 'Security officer', 'role_key' => 'security_officer', 'playbook' => 'watch_security', 'minute' => 5,
        'description' => 'Watches every server of the estate for failed logins and their sources, logins from addresses not seen before, ports listening outside the server\'s expected set, changes to /etc/maluos and the units, and security updates left pending. Read-only; findings advise.',
        'job' => 'You are the security officer. You work in IT and report to its manager. You watch every server of the estate for signs of misuse and for drift: logins, listening ports, configuration changes, pending security updates. You report; you block nothing.' . $common,
    ],
];
$only = isset($opts['only']) ? array_filter(array_map('trim', explode(',', (string) $opts['only']))) : array_keys($agents);
$unknown = array_diff($only, array_keys($agents));
if ($unknown !== []) {
    fwrite(STDERR, '--only takes postgres, linux, security (not ' . implode(', ', $unknown) . ").\n");
    exit(1);
}

$hired = 0;
foreach ($agents as $key => $a) {
    if (!in_array($key, $only, true)) { continue; }
    $email = $a['local'] . '@' . $domain;
    $existing = find_member_by_email($pdo, $email);
    if ($existing !== null) {
        echo "Already hired: {$a['name']} ({$email}, member {$existing['id']}).\n";
        continue;
    }
    $fields = [
        'email' => $email, 'name' => $a['name'], 'job_title' => $a['name'],
        'description' => $a['description'],
        'department_id' => (int) $it['id'],
        'manager_member_id' => $it['manager_member_id'] !== null ? (int) $it['manager_member_id'] : $byId,
        'model_id' => (int) $model['id'], 'monthly_budget_amount' => '1.00', 'budget_currency' => 'USD',
        'home_location_id' => $it['home_location_id'] !== null ? (int) $it['home_location_id'] : null,
        'role_key' => $a['role_key'], 'agent_kind' => 'subagent', 'phone_number' => null,
        'job_description' => $a['job'], 'parameters' => [], 'tools' => $tools,
        'duties' => [[
            'name' => 'Watch the estate',
            'instructions' => 'playbook: ' . $a['playbook'],
            'schedule_cron' => ($a['minute'] % $every) . '-59/' . $every . ' * * * *',
            'timezone' => 'UTC',
        ]],
    ];
    $agent = hire_agent($pdo, $fields, $byId);
    $memberId = (int) $agent['agent_member_id'];
    log_activity($pdo, 'agent.hire', 'member', $memberId, [
        'source' => 'cron',
        'after' => ['name' => $a['name'], 'department' => $it['name'], 'model' => $model['model_key'], 'playbook' => $a['playbook'], 'mode' => 'shadow', 'by' => 'bin/hire_watch_agents.php'],
    ]);
    echo "Hired: {$a['name']} (member {$memberId}) in {$it['name']}, playbook {$a['playbook']} every {$every} min, shadow mode.\n";
    $hired++;
}
echo $hired === 0 ? "Nothing to hire.\n" : "{$hired} hired. They record decisions and send nothing until a person sets mode to live (Agent HR → the agent → config).\n";
