<?php
declare(strict_types=1);

/**
 * Approval policies — which actions need a person's yes, for whom, above what amount
 * (docs/build-specs/approvals.md). Reads go through mcp_approval_policies (insider-open: anyone
 * who works here may know what needs approval); writes are the super-admin's.
 */

const APPROVAL_POLICY_CATEGORIES = [
    'money_out' => 'Money out', 'deletion' => 'Deletion', 'external_send' => 'External send', 'other' => 'Other',
];
const APPROVAL_POLICY_APPLIES_TO = [
    'agents' => 'Every agent', 'agent' => 'One agent', 'department' => 'One department', 'everyone' => 'Everyone',
];

function find_approval_policies(PDO $pdo): array
{
    return $pdo->query(<<<'SQL'
        SELECT p.*, ag.display_name AS agent_name, d.name AS department_name, ap.display_name AS approver_name
          FROM mcp_approval_policies p
          LEFT JOIN mcp_team_directory ag ON ag.member_id = p.agent_member_id
          LEFT JOIN mcp_departments d ON d.department_id = p.department_id
          LEFT JOIN mcp_team_directory ap ON ap.member_id = p.approver_member_id
         ORDER BY p.active DESC, p.category, p.name
    SQL)->fetchAll();
}

function find_approval_policy(PDO $pdo, int $id): ?array
{
    $st = $pdo->prepare('SELECT * FROM mcp_approval_policies WHERE policy_id = :id');
    $st->execute(['id' => $id]);
    return ($r = $st->fetch()) === false ? null : $r;
}

/** @return array{0: array, 1: string[]} the fields and what is wrong with them */
function approval_policy_fields_from_request(PDO $pdo): array
{
    $threshold = trim(request_string('amount_threshold'));
    $f = [
        'name' => trim(request_string('name')),
        'category' => request_string('category'),
        'action_pattern' => trim(request_string('action_pattern')),
        'applies_to' => request_string('applies_to', 'agents'),
        'agent_member_id' => request_integer('agent'),
        'department_id' => request_integer('department'),
        'amount_threshold' => $threshold === '' ? null : $threshold,
        'currency' => strtoupper(trim(request_string('currency'))) ?: null,
        'approver_member_id' => request_integer('approver'),
        'expires_after_hours' => request_integer('expires_after_hours') ?? 72,
    ];
    $e = [];
    if ($f['name'] === '' || mb_strlen($f['name']) > 200) {
        $e[] = 'A policy needs a name (up to 200 characters).';
    }
    if (!isset(APPROVAL_POLICY_CATEGORIES[$f['category']])) {
        $e[] = 'Choose what kind of action this is.';
    }
    // The activity event of a manifest action: 'invoice.send', 'invoice.*' or '*.delete'.
    if (!preg_match('/^(\*|[a-z][a-z0-9_]*)\.(\*|[a-z][a-z0-9_]*)$/', $f['action_pattern']) || $f['action_pattern'] === '*.*') {
        $e[] = 'The action is an event such as invoice.send, invoice.* or *.delete.';
    }
    if (!isset(APPROVAL_POLICY_APPLIES_TO[$f['applies_to']])) {
        $e[] = 'Choose who the policy applies to.';
    }
    if ($f['applies_to'] === 'agent' && $f['agent_member_id'] === null) {
        $e[] = 'Choose the agent this applies to.';
    }
    if ($f['applies_to'] === 'department' && $f['department_id'] === null) {
        $e[] = 'Choose the department this applies to.';
    }
    if ($f['applies_to'] !== 'agent') {
        $f['agent_member_id'] = null;
    }
    if ($f['applies_to'] !== 'department') {
        $f['department_id'] = null;
    }
    if ($f['amount_threshold'] !== null) {
        if (!is_numeric($f['amount_threshold']) || (float) $f['amount_threshold'] < 0) {
            $e[] = 'The amount must be zero or more.';
        }
        $f['currency'] ??= base_currency($pdo);
    } else {
        $f['currency'] = null;
    }
    if ($f['expires_after_hours'] < 1 || $f['expires_after_hours'] > 24 * 90) {
        $e[] = 'A request expires after between 1 hour and 90 days.';
    }
    return [$f, $e];
}

function upsert_approval_policy(PDO $pdo, ?int $id, array $f, int $by): array
{
    $params = [
        'name' => $f['name'], 'category' => $f['category'], 'pattern' => $f['action_pattern'],
        'applies' => $f['applies_to'], 'agent' => $f['agent_member_id'], 'dept' => $f['department_id'],
        'amount' => $f['amount_threshold'], 'currency' => $f['currency'],
        'approver' => $f['approver_member_id'], 'hours' => $f['expires_after_hours'],
    ];
    if ($id === null) {
        $st = $pdo->prepare(<<<'SQL'
            INSERT INTO approval_policies (name, category, action_pattern, applies_to, agent_member_id, department_id,
                                           amount_threshold, currency, approver_member_id, expires_after_hours, created_by)
            VALUES (:name, :category, :pattern, :applies, :agent, :dept, :amount, :currency, :approver, :hours, :by)
            RETURNING *
        SQL);
        $st->execute($params + ['by' => $by]);
    } else {
        $st = $pdo->prepare(<<<'SQL'
            UPDATE approval_policies
               SET name = :name, category = :category, action_pattern = :pattern, applies_to = :applies,
                   agent_member_id = :agent, department_id = :dept, amount_threshold = :amount, currency = :currency,
                   approver_member_id = :approver, expires_after_hours = :hours, updated_at = now()
             WHERE id = :id
            RETURNING *
        SQL);
        $st->execute($params + ['id' => $id]);
    }
    return $st->fetch() ?: [];
}

function set_approval_policy_active(PDO $pdo, int $id, bool $active): bool
{
    $st = $pdo->prepare('UPDATE approval_policies SET active = :a, updated_at = now() WHERE id = :id');
    $st->execute(['a' => $active ? 'true' : 'false', 'id' => $id]);
    return $st->rowCount() === 1;
}

/** Requests a policy caught keep their history: approval_requests.policy_id is SET NULL. */
function delete_approval_policy(PDO $pdo, int $id): bool
{
    $st = $pdo->prepare('DELETE FROM approval_policies WHERE id = :id');
    $st->execute(['id' => $id]);
    return $st->rowCount() === 1;
}

/** Whitelist, mirrored by web/lib/schemas/approvals.ts. */
function present_approval_policy(array $p): array
{
    $int = static fn (string $k): ?int => isset($p[$k]) && $p[$k] !== '' ? (int) $p[$k] : null;
    $currency = $p['currency'] ?? null;
    return [
        'id' => $int('policy_id'),
        'name' => (string) ($p['name'] ?? ''),
        'category' => (string) ($p['category'] ?? 'other'),
        'category_label' => APPROVAL_POLICY_CATEGORIES[$p['category'] ?? ''] ?? (string) ($p['category'] ?? ''),
        'action_pattern' => (string) ($p['action_pattern'] ?? ''),
        'applies_to' => (string) ($p['applies_to'] ?? 'agents'),
        'applies_to_label' => match ($p['applies_to'] ?? 'agents') {
            'agent' => $p['agent_name'] ?? 'One agent',
            'department' => $p['department_name'] ?? 'One department',
            default => APPROVAL_POLICY_APPLIES_TO[$p['applies_to'] ?? 'agents'] ?? '',
        },
        'agent_member_id' => $int('agent_member_id'),
        'department_id' => $int('department_id'),
        'amount_threshold' => isset($p['amount_threshold']) ? (string) $p['amount_threshold'] : null,
        'amount_threshold_display' => isset($p['amount_threshold']) ? money((string) $p['amount_threshold'], $currency) : null,
        'currency' => $currency,
        'approver_member_id' => $int('approver_member_id'),
        'approver_name' => $p['approver_name'] ?? null,
        'expires_after_hours' => (int) ($p['expires_after_hours'] ?? 72),
        'active' => !empty($p['active']),
    ];
}
