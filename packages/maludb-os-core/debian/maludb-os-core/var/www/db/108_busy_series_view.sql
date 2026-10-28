-- 108: busy time for RECURRING appointments, for the read tools (additive;
-- docs/build-specs/calendar.md).
--
-- mcp_busy_blocks answers "is Sam free?" with times only — deliberately including appointments
-- the asker cannot open. But it predates recurrence: a series appears once (its first
-- occurrence), and an exception row has no crew of its own (the crew lives on the series), so a
-- MOVED occurrence is missing from it altogether. This view carries what is needed to expand a
-- series and honour its exceptions — still times only: no title, no customer, no place.
--
--   row_kind = 'series'    : a series × each person / resource on it (with its rule and timezone)
--   row_kind = 'exception' : a child row × the SERIES' crew, with the slot it replaced
--                            (original_start) and its status — 'cancelled' takes the slot out.

BEGIN;

CREATE OR REPLACE VIEW mcp_busy_series WITH (security_barrier = true) AS
 SELECT 'series'::text AS row_kind, a.id AS series_id, who.member_id, who.resource_id,
        a.starts_at, a.ends_at, a.timezone, a.recurrence_rule, NULL::timestamptz AS original_start, a.status
   FROM appointments a
   JOIN LATERAL (
        SELECT aa.member_id, NULL::bigint AS resource_id FROM appointment_assignees aa
         WHERE aa.appointment_id = a.id AND aa.response <> 'declined'
        UNION ALL
        SELECT NULL::bigint, ar.resource_id FROM appointment_resources ar WHERE ar.appointment_id = a.id
   ) who ON true
  WHERE a.recurrence_rule IS NOT NULL AND a.recurrence_parent_id IS NULL AND a.status <> 'cancelled' AND app_is_insider()
 UNION ALL
 SELECT 'exception'::text, c.recurrence_parent_id, who.member_id, who.resource_id,
        c.starts_at, c.ends_at, c.timezone, NULL::text, c.recurrence_original_start, c.status
   FROM appointments c
   JOIN LATERAL (
        SELECT aa.member_id, NULL::bigint AS resource_id FROM appointment_assignees aa
         WHERE aa.appointment_id = c.recurrence_parent_id AND aa.response <> 'declined'
        UNION ALL
        SELECT NULL::bigint, ar.resource_id FROM appointment_resources ar WHERE ar.appointment_id = c.recurrence_parent_id
   ) who ON true
  WHERE c.recurrence_parent_id IS NOT NULL AND app_is_insider();

GRANT SELECT ON mcp_busy_series TO app_rw, app_records_ro;

COMMIT;
