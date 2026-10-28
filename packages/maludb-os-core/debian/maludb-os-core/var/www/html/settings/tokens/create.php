<?php
declare(strict_types=1);
require_once dirname(__DIR__, 3) . '/app/bootstrap.php';
require_once dirname(__DIR__, 3) . '/app/features/settings/queries.php';
require_login(); require_post(); verify_csrf();
$pdo = db(); $me = (int) current_member_id();
$label = request_string('label'); if ($label === '') { $label = 'Personal token'; }
$t = create_mcp_token($pdo, $me, $label);
log_activity($pdo, 'token.create', 'mcp_access_token', $t['id'], ['after' => ['label' => $label]]);
emit_action_status(true, ['did' => 'Token created']);
// Shown once, exactly as the HTML below shows it once: the raw token is in this answer's own
// field and nowhere else — not in `did` (which is logged and echoed to action callers), not in
// a header. json_response() sends Cache-Control: no-store. Owner's decision 3, 2026-09-19.
if (wants_json()) {
    respond_saved(['did' => 'Token created', 'token' => $t['raw']]);
}
echo settings_section_html($pdo, $me, 'tokens', ['newToken' => $t['raw']]);
