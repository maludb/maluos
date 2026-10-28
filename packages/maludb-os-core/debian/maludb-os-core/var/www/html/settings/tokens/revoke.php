<?php
declare(strict_types=1);
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/queries.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $me = (int) current_member_id();
$id = request_integer('token') ?? request_integer('id'); if ($id === null) { http_response_code(400); exit('Bad request'); }
$revoked = revoke_mcp_token($pdo, $id, $me);
if ($revoked) { log_activity($pdo, 'token.revoke', 'mcp_access_token', $id); }
// Say what happened: a token that was not this member's, or already revoked, changes nothing.
emit_action_status(true, ['did' => $revoked ? 'Token revoked' : 'That token was not active — nothing changed']);
echo settings_section_html($pdo, $me, 'tokens');
