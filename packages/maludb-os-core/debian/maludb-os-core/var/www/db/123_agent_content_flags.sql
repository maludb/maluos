-- 123: text that reads like instructions, found in what an agent was about to read.
--
-- An agent reads what the business recorded — vendor names, memos, mail, shared memory — and any of
-- it can carry text written to steer the agent ("ignore your instructions…"). The persona tells agents
-- such text is information, not orders, but an instruction is not enforcement (Claude Architect
-- Module 3: screen retrieved content and tool outputs before they reach the model's context; log
-- every hit). mcp/content_screen.py screens tool results and recalled memory deterministically;
-- this table is where every hit is kept, so a person can see what tried to steer which agent.
--
-- The MCP servers run as read-only roles, so they record a hit through one narrow SECURITY DEFINER
-- function and can write nothing else. The excerpt is short and the pattern is named: enough to
-- judge the hit without copying the record.
--
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/123_agent_content_flags.sql

BEGIN;

CREATE TABLE agent_content_flags (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at      timestamptz NOT NULL DEFAULT now(),
    agent_member_id  bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    agent_run_id     bigint REFERENCES agent_runs(id) ON DELETE SET NULL,
    source           text NOT NULL CHECK (source IN ('tool_result', 'recalled_memory', 'core_memory')),
    source_name      text,                       -- the tool, or the memory namespace
    pattern          text NOT NULL,              -- which rule matched (mcp/content_screen.py)
    excerpt          text NOT NULL,              -- a short window around the match
    disposition      text NOT NULL CHECK (disposition IN ('flagged', 'withheld'))
);
CREATE INDEX agent_content_flags_agent_idx ON agent_content_flags (agent_member_id, occurred_at DESC);
CREATE INDEX agent_content_flags_run_idx ON agent_content_flags (agent_run_id) WHERE agent_run_id IS NOT NULL;

COMMENT ON TABLE agent_content_flags IS
    'Instruction-like text found in a tool result or recalled memory on its way to an agent. flagged = delivered with a notice; withheld = not delivered.';

CREATE FUNCTION record_content_flag(p_agent bigint, p_run bigint, p_source text, p_source_name text,
                                    p_pattern text, p_excerpt text, p_disposition text)
RETURNS bigint LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    INSERT INTO agent_content_flags (agent_member_id, agent_run_id, source, source_name, pattern, excerpt, disposition)
    SELECT p_agent, (SELECT id FROM agent_runs WHERE id = p_run AND agent_member_id = p_agent),
           p_source, left(p_source_name, 200), left(p_pattern, 80), left(p_excerpt, 300), p_disposition
     WHERE EXISTS (SELECT 1 FROM members WHERE id = p_agent AND member_kind = 'agent')
    RETURNING id
$$;
REVOKE ALL ON FUNCTION record_content_flag(bigint, bigint, text, text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION record_content_flag(bigint, bigint, text, text, text, text, text)
    TO app_records_ro, app_activity_ro, app_runner, app_rw;

GRANT SELECT ON agent_content_flags TO app_rw;

CREATE VIEW mcp_agent_content_flags AS
SELECT f.id AS content_flag_id, f.occurred_at, f.agent_member_id, m.display_name AS agent_name, f.agent_run_id,
       f.source, f.source_name, f.pattern, f.excerpt, f.disposition
  FROM agent_content_flags f JOIN members m ON m.id = f.agent_member_id
 WHERE app_can_see_agent(f.agent_member_id);
GRANT SELECT ON mcp_agent_content_flags TO app_rw, app_records_ro;

COMMIT;
