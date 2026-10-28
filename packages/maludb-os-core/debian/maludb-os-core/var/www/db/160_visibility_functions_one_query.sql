-- 160: the per-row visibility functions answer in one query each (2026-09-28).
--
-- Why. mcp_prompt_ledger, mcp_agent_runs and thirteen other mcp_* views gate every row with
-- app_can_see_run() / app_can_see_agent(); mcp_team_directory gates every row with
-- app_can_admin_member(). Each of those was a SECURITY DEFINER SQL function calling a chain
-- of other SECURITY DEFINER SQL functions (insider → business role → external flag; module →
-- enabled → super-admin → business role ...), and a SECURITY DEFINER function is never inlined,
-- so every call in the chain was its own plan execution — about twenty per row, 2.3 ms a row.
-- The agent page sums the ledger three times and lists it once on every tab: 164 rows for one
-- agent cost 1.3 s of the page's 1.6 s. Measured on this server, EXPLAIN ANALYZE as app_rw:
-- the ledger sum for agent 43 was 382 ms with the old function; the pieces, inlined, 0.2 ms.
--
-- What changes. NOTHING about who sees what. Each function keeps its name, signature and
-- meaning exactly (the proof that ran before this was applied compared old and new for every
-- member against every agent/acting pair in the ledger and the runs, and every module name);
-- each now reads the caller's member row once and answers from that row, its module grants,
-- its departments and the agent's profile in ONE statement, and each is PL/pgSQL rather than
-- SQL: Postgres 17 parses and plans a SQL-language function's body on EVERY call, while a
-- PL/pgSQL function keeps its plan for the connection — measured here on the ledger sum for
-- agent 43 as app_rw: 382 ms before, 111 ms as one SQL statement, 34 ms as PL/pgSQL.
-- app_module_enabled() goes the same way (it is called from inside the others); the insider
-- rule stays what it was: an active, non-external member. app_current_member_id() is kept as
-- it is (a plain SQL function, inlined).
--
-- One difference in shape only: where the old app_can_see_run() / app_can_see_agent() answered
-- NULL (an anonymous caller, or a NULL acting member with nothing else admitting the row) the
-- new ones answer false. A view's WHERE treats both as "not shown"; nothing reads the NULL.
--
-- The rule this leaves behind for new views: a check that depends only on the CALLER belongs
-- in an uncorrelated scalar subquery — WHERE (SELECT app_is_super_admin()) OR ... — which
-- Postgres runs once per statement (an InitPlan), never once per row.

CREATE OR REPLACE FUNCTION app_module_enabled(p_module text)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $$
BEGIN
    RETURN p_module IS NULL
        OR NOT EXISTS (SELECT 1 FROM nav_items WHERE module = p_module)
        OR EXISTS (SELECT 1 FROM nav_items WHERE module = p_module AND status <> 'disabled');
END $$;

CREATE OR REPLACE FUNCTION app_is_insider()
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $$
BEGIN
    RETURN EXISTS (SELECT 1 FROM members m
                    WHERE m.id = app_current_member_id() AND m.status = 'active' AND NOT m.is_external);
END $$;

CREATE OR REPLACE FUNCTION app_has_module(p_module text)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $$
BEGIN
    RETURN app_module_enabled(p_module)
       AND ((SELECT m.business_role FROM members m
              WHERE m.id = app_current_member_id() AND m.status = 'active') = 'super_admin'
            OR EXISTS (SELECT 1 FROM module_grants g
                        WHERE g.member_id = app_current_member_id() AND g.module = p_module));
END $$;

CREATE OR REPLACE FUNCTION app_can_see_agent(p_agent_member_id bigint)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $$
BEGIN
    -- An insider (active, not external) who is the agent, holds hr, or manages the agent.
    RETURN COALESCE((
        SELECT p_agent_member_id = m.id
            OR (app_module_enabled('hr')
                AND (m.business_role = 'super_admin'
                     OR EXISTS (SELECT 1 FROM module_grants g WHERE g.member_id = m.id AND g.module = 'hr')))
            OR EXISTS (SELECT 1 FROM agent_profiles ap
                        WHERE ap.member_id = p_agent_member_id AND ap.manager_member_id = m.id)
          FROM members m
         WHERE m.id = app_current_member_id() AND m.status = 'active' AND NOT m.is_external
    ), false);
END $$;

CREATE OR REPLACE FUNCTION app_can_see_run(p_agent_member_id bigint, p_acting_member_id bigint)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $$
BEGIN
    -- An insider who acted in the run, holds ledger, or (when an agent ran it) may see that agent.
    RETURN COALESCE((
        SELECT p_acting_member_id = m.id
            OR p_agent_member_id = m.id
            OR (app_module_enabled('ledger')
                AND (m.business_role = 'super_admin'
                     OR EXISTS (SELECT 1 FROM module_grants g WHERE g.member_id = m.id AND g.module = 'ledger')))
            OR (p_agent_member_id IS NOT NULL
                AND ((app_module_enabled('hr')
                      AND (m.business_role = 'super_admin'
                           OR EXISTS (SELECT 1 FROM module_grants g WHERE g.member_id = m.id AND g.module = 'hr')))
                     OR EXISTS (SELECT 1 FROM agent_profiles ap
                                 WHERE ap.member_id = p_agent_member_id AND ap.manager_member_id = m.id)))
          FROM members m
         WHERE m.id = app_current_member_id() AND m.status = 'active' AND NOT m.is_external
    ), false);
END $$;

CREATE OR REPLACE FUNCTION app_can_admin_member(p_member_id bigint)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $$
BEGIN
    -- Oneself; a super-admin; a dept-admin for a member of a department they administer
    -- (flagged admin of it, or its named manager) — the people rule, unchanged.
    RETURN p_member_id = app_current_member_id()
        OR COALESCE((
            SELECT m.business_role = 'super_admin'
                OR (m.business_role = 'dept_admin'
                    AND EXISTS (SELECT 1
                                  FROM department_members dm
                                  JOIN departments d ON d.id = dm.department_id AND d.archived_at IS NULL
                                  LEFT JOIN department_members me
                                         ON me.department_id = d.id AND me.member_id = m.id AND me.left_at IS NULL
                                 WHERE dm.member_id = p_member_id AND dm.left_at IS NULL
                                   AND (d.manager_member_id = m.id OR me.is_admin)))
              FROM members m
             WHERE m.id = app_current_member_id() AND m.status = 'active'
        ), false);
END $$;

-- The two hottest views — the ledger and the runs, summed and listed on every tab of an agent's
-- page — are the exemplar of that rule. Same columns, same security_barrier, same grants (a
-- CREATE OR REPLACE VIEW keeps them), the SAME test as app_can_see_run() written out: the parts
-- that depend only on the caller sit in scalar subqueries and run once; the agents the caller
-- manages are one hashed set; only the comparisons against the row's own columns run per row.

CREATE OR REPLACE VIEW mcp_prompt_ledger WITH (security_barrier = true) AS
SELECT pl.id AS ledger_id, pl.occurred_at, pl.agent_run_id, pl.agent_member_id, pl.acting_member_id, pl.location_id,
       pl.harness, pl.sdk_version, pl.provider, pl.model_id, pl.provider_model_id, pl.request_id, pl.call_kind,
       pl.status, pl.error_code, pl.error_message, pl.input_tokens, pl.output_tokens, pl.cache_read_tokens,
       pl.cache_write_tokens, pl.latency_ms, pl.cost, pl.currency, pl.payload_archived_at, pl.application_id
  FROM prompt_ledger pl
 WHERE (SELECT app_is_insider())
   AND ((SELECT app_has_module('ledger'))
        OR pl.acting_member_id = (SELECT app_current_member_id())
        OR (pl.agent_member_id IS NOT NULL
            AND ((SELECT app_has_module('hr'))
                 OR pl.agent_member_id = (SELECT app_current_member_id())
                 OR pl.agent_member_id IN (SELECT ap.member_id FROM agent_profiles ap
                                            WHERE ap.manager_member_id = app_current_member_id()))));

CREATE OR REPLACE VIEW mcp_agent_runs WITH (security_barrier = true) AS
SELECT r.id AS agent_run_id, r.agent_member_id, am.display_name AS agent_name, r.acting_member_id, r.location_id,
       r.trigger, r.duty_id, r.location_task_id, r.config_version_id, r.model_id, r.harness, r.sdk_version,
       r.request_id, r.status, r.error, r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens,
       r.cost, r.currency, r.started_at, r.finished_at, r.instructions, r.result, r.parent_run_id, r.requested_by,
       r.approval_request_id, r.application_id, r.conversation_key, r.chat_utterance
  FROM agent_runs r
  LEFT JOIN members am ON am.id = r.agent_member_id
 WHERE (SELECT app_is_insider())
   AND ((SELECT app_has_module('ledger'))
        OR r.acting_member_id = (SELECT app_current_member_id())
        OR (r.agent_member_id IS NOT NULL
            AND ((SELECT app_has_module('hr'))
                 OR r.agent_member_id = (SELECT app_current_member_id())
                 OR r.agent_member_id IN (SELECT ap.member_id FROM agent_profiles ap
                                           WHERE ap.manager_member_id = app_current_member_id()))));
