-- 102_settle_decided_paused_runs.sql
-- One-time data fix. Until stage H3 nothing could decide an approval request, and H3's first
-- decisions were made before settle_paused_run() existed — so a few runs still say
-- awaiting_approval although the request they stopped on has been decided. From here on the
-- decision handlers settle the run themselves. Idempotent.

BEGIN;

UPDATE agent_runs r
   SET status = 'succeeded'
  FROM approval_requests a
 WHERE r.status = 'awaiting_approval'
   AND a.id = r.approval_request_id
   AND a.status <> 'pending';

COMMIT;
