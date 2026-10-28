-- 109: what the Helpdesk module needs that db/034 did not give it (additive;
-- docs/build-specs/helpdesk.md; owner's decision 8 of 2026-09-19: "a business-hours setting").
--
--  * business_hours — sla_policies.business_hours_only defaults to true, but no business hours
--    were defined anywhere, so an SLA clock had nothing to count. One row per weekday
--    (1 = Monday … 7 = Sunday, ISO), in the business timezone; seeded Mon–Fri 09:00–17:00.
--  * mcp_sla_policies, mcp_ticket_categories — the two lookup tables had no read view, and
--    "every list/detail screen reads an mcp_* view" (db/063).

BEGIN;

CREATE TABLE IF NOT EXISTS business_hours (
    weekday     smallint PRIMARY KEY CHECK (weekday BETWEEN 1 AND 7),
    is_open     boolean NOT NULL DEFAULT true,
    opens       time NOT NULL DEFAULT '09:00',
    closes      time NOT NULL DEFAULT '17:00',
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (closes > opens)
);
INSERT INTO business_hours (weekday, is_open)
SELECT d, d <= 5 FROM generate_series(1, 7) AS d
ON CONFLICT (weekday) DO NOTHING;

GRANT SELECT, INSERT, UPDATE ON business_hours TO app_rw;

CREATE OR REPLACE VIEW mcp_business_hours WITH (security_barrier = true) AS
 SELECT weekday, is_open, opens, closes FROM business_hours WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_sla_policies WITH (security_barrier = true) AS
 SELECT p.id AS sla_policy_id, p.name, p.priority, p.department_id, d.name AS department_name,
        p.first_response_minutes, p.resolution_minutes, p.business_hours_only
   FROM sla_policies p LEFT JOIN departments d ON d.id = p.department_id
  WHERE p.archived_at IS NULL AND app_is_insider();

CREATE OR REPLACE VIEW mcp_ticket_categories WITH (security_barrier = true) AS
 SELECT c.id AS category_id, c.name, c.department_id, d.name AS department_name
   FROM ticket_categories c LEFT JOIN departments d ON d.id = c.department_id
  WHERE c.archived_at IS NULL AND app_is_insider();

GRANT SELECT ON mcp_business_hours, mcp_sla_policies, mcp_ticket_categories TO app_rw, app_records_ro;

COMMIT;
