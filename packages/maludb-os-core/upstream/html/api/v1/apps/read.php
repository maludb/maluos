<?php
declare(strict_types=1);

/**
 * K7 — one application reads another's shared tool through the kernel (db/161; docs/build-specs/kernel-app-services.md).
 *
 *   POST /api/v1/apps/read.php   {provider, tool, arguments?, location_id?}
 *     → 200 {result, provider, tool}
 *     → 403 not_shared | no_connection | not_at_location, 422 invalid, 502 provider_failed
 *
 * Bearer = the consumer's application token (internal port). Only over a connection a super-admin approved; a
 * per-site tool needs a location both applications serve, and the provider is handed its own scope_id for it. No
 * person's identity crosses; the answer is passed back unchanged and never logged.
 */
require_once dirname(__DIR__, 4) . '/app/api/bootstrap.php';
require_once dirname(__DIR__, 4) . '/app/api/directory.php';
require_once dirname(__DIR__, 4) . '/app/features/applications/services.php';

directory_authenticate();
$pdo = db();
$app = directory_application();
if (directory_method() !== 'POST') {
    header('Allow: POST');
    api_error('method_not_allowed', 'POST.', 405);
}
$body = directory_body();
$provider = (string) ($body['provider'] ?? '');
$tool = (string) ($body['tool'] ?? '');
$arguments = $body['arguments'] ?? [];
if (!preg_match('/^[a-z][a-z0-9_]{1,31}$/', $provider) || !preg_match('/^[a-z][a-z0-9_]{0,63}$/', $tool) || !is_array($arguments)) {
    api_error('invalid', 'provider (an application key), tool and arguments (an object) are required.', 422);
}
$location = isset($body['location_id']) && (int) $body['location_id'] > 0 ? (int) $body['location_id'] : null;
[$status, $payload] = application_read($pdo, $app, $provider, $tool, $arguments, $location);
if ($status >= 400) {
    api_error($payload['code'], $payload['message'], $status);
}
api_json($payload, $status);
