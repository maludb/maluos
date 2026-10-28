-- 151: click-around, step 3 (docs/build-specs/click-around.md) — the ids the screens need that only
-- a view could supply, appended LAST to four views so every existing column keeps its place:
--   mcp_agents              + model_id            (the agents list and the dashboard link the model)
--   mcp_agent_escalations   + to_member_name, to_member_kind  (the recipient by name, to their page)
--   mcp_team_directory      + department_ids      (beside `departments`, same order: the team list and
--                                                  the dashboard link each department)
--   mcp_application_access  + scope_location_id, scope_department_id  (a scope's own target, not the
--                                                  application_scopes row: the Access tab links it)
-- Grants are kept by CREATE OR REPLACE; security_barrier is restated where the view had it.
BEGIN;

CREATE OR REPLACE VIEW mcp_agents AS
 SELECT ap.member_id AS agent_member_id,
    m.display_name,
    m.job_title,
    ap.status,
    ap.agent_kind,
    ap.is_office_manager,
    ap.description,
    ap.role_key,
        CASE
            WHEN ap.profile_photo_path IS NOT NULL THEN '/agents/photo.php?agent='::text || ap.member_id::text
            ELSE NULL::text
        END AS profile_pic_url,
    ap.profile_photo_path IS NOT NULL AS has_profile_photo,
    ap.profile_photo_mime,
    ap.profile_photo_size_bytes,
    ap.profile_photo_sha256,
    ap.profile_photo_updated_at,
    ap.manager_member_id,
    mm.display_name AS manager_name,
    ap.home_location_id,
    mr.model_key,
    mr.harness,
        CASE
            WHEN app_can_see_agent(ap.member_id) THEN ap.current_config_version_id
            ELSE NULL::bigint
        END AS current_config_version_id,
        CASE
            WHEN app_can_see_agent(ap.member_id) THEN ap.monthly_budget_amount
            ELSE NULL::numeric
        END AS monthly_budget_amount,
    ap.budget_currency,
    ap.hired_at,
    ap.suspended_at,
    ap.offboarded_at,
    ( SELECT count(*) AS count
           FROM agent_subagents s
          WHERE s.orchestrator_member_id = ap.member_id AND s.removed_at IS NULL) AS subagent_count,
    ( SELECT count(*) AS count
           FROM agent_subagents s
          WHERE s.subagent_member_id = ap.member_id AND s.removed_at IS NULL) AS orchestrator_count,
    ap.phone_number,
    ap.model_id
   FROM agent_profiles ap
     JOIN members m ON m.id = ap.member_id
     JOIN members mm ON mm.id = ap.manager_member_id
     JOIN model_registry mr ON mr.id = ap.model_id
  WHERE app_is_insider();

CREATE OR REPLACE VIEW mcp_agent_escalations WITH (security_barrier = true) AS
 SELECT e.id AS escalation_id,
    e.agent_member_id,
    am.display_name AS agent_name,
    e.to_member_id,
    e.reason_kind,
    e.summary,
    e.entity_type,
    e.entity_id,
    e.approval_request_id,
    e.resolved_at,
    e.resolved_by,
    e.created_at,
    tm.display_name AS to_member_name,
    tm.member_kind AS to_member_kind
   FROM agent_escalations e
     JOIN members am ON am.id = e.agent_member_id
     LEFT JOIN members tm ON tm.id = e.to_member_id
  WHERE e.to_member_id = app_current_member_id() OR app_can_see_agent(e.agent_member_id);

CREATE OR REPLACE VIEW mcp_team_directory WITH (security_barrier = true) AS
 SELECT id AS member_id,
    display_name,
    member_kind,
    business_role,
    job_title,
    timezone,
    status,
    joined_at,
    ( SELECT array_agg(d.name::text ORDER BY dm.is_primary DESC, d.name) AS array_agg
           FROM department_members dm
             JOIN departments d ON d.id = dm.department_id
          WHERE dm.member_id = m.id AND dm.left_at IS NULL) AS departments,
        CASE
            WHEN app_can_admin_member(id) THEN email::text
            ELSE NULL::text
        END AS email,
        CASE
            WHEN app_can_admin_member(id) THEN phone
            ELSE NULL::text
        END AS phone,
        CASE
            WHEN app_is_super_admin() OR id = app_current_member_id() THEN totp_enabled_at IS NOT NULL
            ELSE NULL::boolean
        END AS has_2fa,
        CASE
            WHEN app_is_super_admin() OR id = app_current_member_id() THEN last_login_at
            ELSE NULL::timestamp with time zone
        END AS last_login_at,
    ( SELECT array_agg(d.id ORDER BY dm.is_primary DESC, d.name) AS array_agg
           FROM department_members dm
             JOIN departments d ON d.id = dm.department_id
          WHERE dm.member_id = m.id AND dm.left_at IS NULL) AS department_ids
   FROM members m
  WHERE app_is_insider() AND (status = ANY (ARRAY['active'::text, 'suspended'::text]));

CREATE OR REPLACE VIEW mcp_application_access WITH (security_barrier = true) AS
 SELECT ac.id AS application_access_id,
    ac.application_id,
    a.name AS application_name,
    ac.member_id,
    m.display_name AS member_name,
    m.member_kind,
    ac.department_id,
    d.name::text AS department_name,
    ac.capability,
    ac.granted_by,
    ac.granted_at,
    ac.expires_at,
    ac.note,
    ac.scope_id,
    COALESCE(sl.name, sd.name::text) AS scope_name,
    ac.role_key,
    ar.name AS role_name,
    ac.resident_location_id,
    rl.name AS resident_location_name,
    s.location_id AS scope_location_id,
    s.department_id AS scope_department_id
   FROM application_access ac
     JOIN applications a ON a.id = ac.application_id
     LEFT JOIN members m ON m.id = ac.member_id
     LEFT JOIN departments d ON d.id = ac.department_id
     LEFT JOIN application_scopes s ON s.id = ac.scope_id
     LEFT JOIN locations sl ON sl.id = s.location_id
     LEFT JOIN departments sd ON sd.id = s.department_id
     LEFT JOIN application_roles ar ON ar.application_id = ac.application_id AND ar.role_key = ac.role_key
     LEFT JOIN locations rl ON rl.id = ac.resident_location_id
  WHERE ac.revoked_at IS NULL AND app_is_insider() AND (app_has_module('applications'::text) OR app_is_super_admin() OR ac.member_id = app_current_member_id() OR (ac.department_id = ANY (app_my_department_ids())) OR (ac.resident_location_id IN ( SELECT r.location_id
           FROM location_residents r
          WHERE r.member_id = app_current_member_id() AND r.removed_at IS NULL)));

COMMIT;
