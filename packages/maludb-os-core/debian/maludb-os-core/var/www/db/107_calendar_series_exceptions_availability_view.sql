-- 107: what the Calendar module needs that db/033 did not give it (additive;
-- docs/build-specs/calendar.md, owner's decision 11: full RRULE with exceptions).
--
--  * appointments.recurrence_original_start — db/033 makes an exception to a series "a child row
--    pointing at recurrence_parent_id", but a child had no way to say WHICH occurrence it
--    replaces. This is that occurrence's original start: a moved occurrence is a child with new
--    times, a cancelled one a child with status 'cancelled'; both name the slot they take out of
--    the series (the iCal feed turns them into EXDATE / RECURRENCE-ID). Appended to
--    mcp_appointments.
--  * mcp_availability_blocks — availability_blocks had no read view of its own (it was only
--    inside mcp_busy_blocks, which drops the kind and the note). A person sees their own blocks;
--    someone with the scheduling grant, or an admin, sees everyone's and the resources'.

BEGIN;

ALTER TABLE appointments ADD COLUMN IF NOT EXISTS recurrence_original_start timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS appointments_series_exception_idx
    ON appointments (recurrence_parent_id, recurrence_original_start)
    WHERE recurrence_parent_id IS NOT NULL;

CREATE OR REPLACE VIEW mcp_appointments WITH (security_barrier = true) AS
 SELECT a.id AS appointment_id,
    a.appointment_type_id,
    at.name AS appointment_type,
    a.title,
    a.description,
    a.organization_id,
    o.name AS organization_name,
    a.contact_id,
    a.deal_id,
    a.project_id,
    a.task_id,
    a.location_text,
    a.meeting_url,
    a.starts_at,
    a.ends_at,
    a.all_day,
    a.timezone,
    a.status,
    a.recurrence_rule,
    a.recurrence_parent_id,
    a.completed_at,
    a.cancelled_reason,
    a.owner_member_id,
    a.department_id,
    ( SELECT array_agg(aa.member_id) AS array_agg
           FROM appointment_assignees aa
          WHERE aa.appointment_id = a.id AND aa.response <> 'declined'::text) AS assignee_ids,
    (EXISTS ( SELECT 1
           FROM invoice_lines il
          WHERE il.appointment_id = a.id)) AS is_invoiced,
    a.created_at,
    a.updated_at,
    a.recurrence_original_start
   FROM appointments a
     LEFT JOIN appointment_types at ON at.id = a.appointment_type_id
     LEFT JOIN organizations o ON o.id = a.organization_id
  WHERE app_is_insider() AND ((EXISTS ( SELECT 1
           FROM appointment_assignees aa
          WHERE aa.appointment_id = a.id AND aa.member_id = app_current_member_id())) OR app_can_see('scheduling'::text, a.owner_member_id, a.department_id, 'appointment'::text, a.id, NULL::bigint));

CREATE OR REPLACE VIEW mcp_availability_blocks WITH (security_barrier = true) AS
 SELECT b.id AS availability_block_id, b.member_id, m.display_name AS member_name,
        b.resource_id, r.name AS resource_name, b.kind, b.starts_at, b.ends_at,
        b.recurrence_rule, b.note, b.created_at
   FROM availability_blocks b
   LEFT JOIN members m ON m.id = b.member_id
   LEFT JOIN bookable_resources r ON r.id = b.resource_id
  WHERE app_is_insider()
    AND (b.member_id = app_current_member_id()
         OR app_has_module('scheduling')
         OR app_is_super_admin()
         OR (b.member_id IS NOT NULL AND app_can_admin_member(b.member_id)));

GRANT SELECT ON mcp_availability_blocks TO app_rw, app_records_ro;

COMMIT;

-- The Calendar application row pointed at /calendar/ (the retired cert-study calendar); the
-- module lives at /schedule/, as the nav and the action manifest always said.
UPDATE applications SET url = '/schedule/', updated_at = now() WHERE app_key = 'calendar' AND url = '/calendar/';
