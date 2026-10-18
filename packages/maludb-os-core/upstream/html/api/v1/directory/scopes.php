<?php
declare(strict_types=1);

/**
 * GET /api/v1/directory/scopes.php — the calling application's live scopes: the sites or departments
 * one installation serves (db/141; docs/build-specs/kernel-scoped-applications.md). What a new
 * installation creates before its first sign-in; afterwards the change feed's `scopes` keeps it current.
 * Schema os.directory-scopes/1.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';

api_require_get();
$application = directory_authenticate();
$pdo = db();
$st = $pdo->prepare('SELECT scope_kind FROM applications WHERE id = :id');
$st->execute(['id' => $application['id']]);
api_json([
    'schema' => 'os.directory-scopes/1',
    'scope_kind' => (string) $st->fetchColumn(),
    'roles' => array_map(static fn (array $r): array => ['key' => $r['role_key'], 'name' => $r['name'],
        'capability' => $r['capability'], 'is_admin' => (bool) $r['is_admin']],
        (static function () use ($pdo, $application): array {
            $q = $pdo->prepare('SELECT role_key, name, capability, is_admin FROM application_roles WHERE application_id = :id ORDER BY sort_order, id');
            $q->execute(['id' => $application['id']]);
            return $q->fetchAll();
        })()),
    'scopes' => directory_scopes($pdo, $application['id']),
]);
