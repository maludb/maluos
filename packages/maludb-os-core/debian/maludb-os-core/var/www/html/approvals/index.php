<?php
declare(strict_types=1);

/** Approvals — module stub until its slice is built (build plan 1.8). */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';

// The queue as JSON (React, H7). The HTML path stays the module stub: app/views is frozen until
// the React cut-over, and until then the queue is reached through approval_queue + the command bar.
// JSON only since the React cut-over; the queue's rows are the caller's own.
{
    require_login();
    require_once dirname(__DIR__, 2) . '/app/features/approvals/queries.php';
    require_once dirname(__DIR__, 2) . '/app/features/approvals/present.php';
    $role = request_string('role') === 'requester' ? 'requester' : 'approver';
    $status = request_string('status') ?: null;
    if ($status !== null && !in_array($status, ['pending', 'approved', 'rejected', 'expired', 'cancelled', 'executed', 'execution_failed'], true)) {
        $status = null;
    }
    sweep_due_approvals(db());    // an overdue request shows as expired, not as pending for ever
    log_screen_view(db(), 'approvals');
    respond_screen([
        'role' => $role, 'status' => $status,
        'requests' => array_map('present_approval_request', approvals_for_member(db(), (int) current_member_id(), $role, $status)),
    ]);
}

