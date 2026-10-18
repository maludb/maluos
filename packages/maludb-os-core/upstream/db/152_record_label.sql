-- 152: click-around (owner, 2026-09-27: "activity rows should record names") — the name of a record
-- by kind and id, for the activity trail and any other "kind #id" that has a name to show. Names only,
-- from the base tables the kernel still has; a kind with no table (the modules cut in db/133, an
-- application's own rows) answers NULL and the screen keeps "kind #id". SECURITY INVOKER, STABLE: the
-- caller (app_rw) reads these tables anyway, and the trail already gates who sees which rows.
BEGIN;

CREATE OR REPLACE FUNCTION app_record_label(p_kind text, p_id bigint) RETURNS text
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = public AS $fn$
    SELECT CASE p_kind
        WHEN 'member'               THEN (SELECT m.display_name FROM members m WHERE m.id = p_id)
        WHEN 'agent'                THEN (SELECT m.display_name FROM members m WHERE m.id = p_id)
        WHEN 'department'           THEN (SELECT d.name::text FROM departments d WHERE d.id = p_id)
        WHEN 'location'             THEN (SELECT l.name FROM locations l WHERE l.id = p_id)
        WHEN 'application'          THEN (SELECT a.name FROM applications a WHERE a.id = p_id)
        WHEN 'application_endpoint' THEN (SELECT e.name FROM application_endpoints e WHERE e.id = p_id)
        WHEN 'approval_request'     THEN (SELECT left(r.summary, 80) FROM approval_requests r WHERE r.id = p_id)
        WHEN 'approval_policy'      THEN (SELECT p.name FROM approval_policies p WHERE p.id = p_id)
        WHEN 'model'                THEN (SELECT mr.display_name FROM model_registry mr WHERE mr.id = p_id)
        WHEN 'system_prompt'        THEN (SELECT sp.name FROM system_prompts sp WHERE sp.id = p_id)
        WHEN 'eval_set'             THEN (SELECT s.name FROM eval_sets s WHERE s.id = p_id)
        WHEN 'eval_case'            THEN (SELECT c.title FROM eval_cases c WHERE c.id = p_id)
        WHEN 'nav_item'             THEN (SELECT n.label FROM nav_items n WHERE n.id = p_id)
        WHEN 'mcp_access_token'     THEN (SELECT t.label FROM mcp_access_tokens t WHERE t.id = p_id)
        WHEN 'skill_proposal'       THEN (SELECT sp.skill_name FROM skill_proposals sp WHERE sp.id = p_id)
        ELSE NULL
    END
$fn$;

COMMENT ON FUNCTION app_record_label(text, bigint) IS 'The name of a kernel record by kind and id, or NULL (click-around, db/152).';

COMMIT;
