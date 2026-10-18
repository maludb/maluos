<?php
declare(strict_types=1);

/**
 * Screen `agent-org` — the orchestrator tree (db/154): each personal assistant and the person it serves,
 * the leads under it, their specialists; and the leads the OS proposes for departments that have none
 * (db/157), each confirmed or declined by a super-admin. Gate: business admin. JSON only (React).
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/assistants/assistants.php';

require_business_admin();
$pdo = db();
log_screen_view($pdo, 'agent-org');
respond_screen([
    'nodes' => array_map(static fn (array $n): array => [
        'id' => (int) $n['id'], 'name' => (string) $n['name'], 'kind' => (string) $n['kind'],
        'principal_id' => $n['principal_id'] !== null ? (int) $n['principal_id'] : null,
        'principal_name' => $n['principal_name'], 'parent_id' => $n['parent_id'] !== null ? (int) $n['parent_id'] : null,
        'departments' => $n['departments'],
    ], org_nodes($pdo)),
    'proposals' => array_map(static fn (array $p): array => [
        'id' => (int) $p['id'], 'name' => (string) $p['name'], 'department_id' => (int) $p['department_id'],
        'department_name' => (string) $p['department_name'], 'job_description' => (string) $p['job_description'],
        'parent_name' => $p['parent_name'], 'model_name' => $p['model_name'],
        'roster' => json_decode((string) $p['roster'], true) ?: [], 'proposed_at' => json_ts($p['proposed_at']),
    ], open_lead_proposals($pdo)),
    'can' => ['decide' => is_super_admin()],
]);
