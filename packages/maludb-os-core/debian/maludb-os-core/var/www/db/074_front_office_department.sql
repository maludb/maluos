-- 074_front_office_department.sql
-- The Front Office: a fourth standing department, and the top of the org chart.
--
-- Decided 2026-09-18. Every business has a front of house — the CEO, the COO, the
-- receptionist, whoever fronts the business and runs it — and until now that had nowhere to
-- live: HR, Accounting and Audit are duties, not leadership, and a tenant started with three
-- peer departments and no head. So:
--
--   1. Front Office joins HR, Accounting and Audit as a standing department: seeded in every
--      tenant, renameable, never deletable (the 055 protection trigger already covers any
--      is_system row, so it needs no new guard).
--   2. Every other department reports to it. Existing top-level departments are re-parented
--      here, and a department created later with no parent named is parented to the Front
--      Office by a trigger rather than by whichever screen or MCP tool happened to insert it.
--      The Front Office itself is the root and is held at parent_id IS NULL.
--   3. It works at an onsite location by default — a department may sit anywhere, including a
--      rented offsite office, but the front of the business belongs on a machine we run. The
--      seed takes the first active onsite office, falling back to any active office, and
--      leaves it unassigned if the tenant somehow has neither (nullable, as before).

BEGIN;

-- --------------------------------------------------------------------------
-- 1. The vocabulary
-- --------------------------------------------------------------------------
ALTER TABLE departments DROP CONSTRAINT departments_system_key_check;
ALTER TABLE departments ADD CONSTRAINT departments_system_key_check CHECK (
    system_key IN ('front_office', 'hr', 'accounting', 'audit')
);

COMMENT ON COLUMN departments.system_key IS
    'The standing departments every tenant has: front_office (leadership and front of house, '
    'the root of the org chart), hr (people and agents), accounting (the books and the token '
    'meter), audit (the evals). NULL for an ordinary department.';
COMMENT ON COLUMN departments.parent_id IS
    'Who this department reports to. NULL only for the Front Office, which is the root: the '
    'trigger departments_report_to_front_office fills it in for everyone else.';

-- --------------------------------------------------------------------------
-- 2. The department itself
-- --------------------------------------------------------------------------
INSERT INTO departments (name, description, is_system, system_key, parent_id, home_location_id)
SELECT 'Front Office',
       'The front of the business and the people who run it: the CEO, the COO, reception, and '
       'whoever else meets the world first. Every other department reports here.',
       true, 'front_office', NULL,
       coalesce(
           (SELECT id FROM locations
             WHERE kind = 'office' AND status = 'active' AND siting = 'onsite'
             ORDER BY id LIMIT 1),
           (SELECT id FROM locations
             WHERE kind = 'office' AND status = 'active'
             ORDER BY id LIMIT 1))
WHERE NOT EXISTS (SELECT 1 FROM departments d WHERE d.system_key = 'front_office');

-- --------------------------------------------------------------------------
-- 3. Everyone else reports to it
-- --------------------------------------------------------------------------
UPDATE departments
   SET parent_id = (SELECT id FROM departments WHERE system_key = 'front_office')
 WHERE system_key IS DISTINCT FROM 'front_office'
   AND parent_id IS NULL;

CREATE OR REPLACE FUNCTION department_reports_to_front_office() RETURNS trigger
    LANGUAGE plpgsql AS $$
DECLARE
    front_office_id bigint;
BEGIN
    SELECT id INTO front_office_id FROM departments WHERE system_key = 'front_office';

    -- The Front Office is the root: it reports to nobody, and nothing makes it report to
    -- itself either.
    IF NEW.system_key = 'front_office' THEN
        NEW.parent_id := NULL;
        RETURN NEW;
    END IF;

    IF NEW.parent_id IS NULL THEN
        NEW.parent_id := front_office_id;
    END IF;
    RETURN NEW;
END$$;

COMMENT ON FUNCTION department_reports_to_front_office() IS
    'Keeps the org chart rooted: a department saved without a parent reports to the Front '
    'Office, and the Front Office itself stays at the top.';

DROP TRIGGER IF EXISTS departments_report_to_front_office ON departments;
CREATE TRIGGER departments_report_to_front_office
    BEFORE INSERT OR UPDATE ON departments
    FOR EACH ROW EXECUTE FUNCTION department_reports_to_front_office();

-- --------------------------------------------------------------------------
-- 4. The view carries who a department reports to
-- --------------------------------------------------------------------------
-- parent_id was already exposed; a bare id answers nothing on a screen. The name is
-- appended at the end of the column list, so CREATE OR REPLACE is enough and the view's
-- grants and security_barrier survive untouched (db/069 established the rule).
CREATE OR REPLACE VIEW mcp_departments WITH (security_barrier = true) AS
SELECT d.id AS department_id, d.name::text AS name, d.description, d.parent_id,
       d.manager_member_id, mm.display_name AS manager_name, d.handbook_document_id,
       d.is_system, d.system_key, d.home_location_id, l.name AS home_location_name,
       d.monthly_budget_amount, d.budget_currency,
       (SELECT count(*) FROM department_members dm
         WHERE dm.department_id = d.id AND dm.left_at IS NULL) AS member_count,
       d.archived_at, d.created_at,
       pd.name::text AS parent_name
FROM departments d
LEFT JOIN members mm ON mm.id = d.manager_member_id
LEFT JOIN locations l ON l.id = d.home_location_id
LEFT JOIN departments pd ON pd.id = d.parent_id
WHERE app_is_insider();

COMMIT;
