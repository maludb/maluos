-- 124: a person's verdict on a run — the cheapest label an evaluation can ever have.
--
-- docs/build-specs/eval-evidence.md, "Open — for the owner", item 1: of everything an evaluation
-- will want, a human judgement of whether a run was any good is the one thing the platform records
-- nowhere. Every other piece of evidence is already kept (prompt_ledger, prompt_payloads,
-- agent_runs, agent_run_events, activity_log). Approved by the owner 2026-09-20.
--
-- It cannot be backfilled. Nobody will remember in March whether Tuesday's morning brief was good,
-- so every day without this table is a day of unlabelled runs — which is exactly the argument that
-- made activity logging mandatory from day one.
--
-- A verdict is deliberately coarse: good or bad, plus an optional note. Anything richer is a rubric,
-- and a rubric belongs to an eval case. One verdict per person per thing, changeable — a second
-- thought replaces the first rather than stacking up.
--
-- It attaches to EITHER an agent run OR one assistant answer (a prompt_ledger row): the command bar
-- is the most-used AI in the product and its answers deserve the same label.
--
-- Additive. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/124_run_verdicts.sql

BEGIN;

CREATE TABLE run_verdicts (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_run_id      bigint REFERENCES agent_runs(id) ON DELETE CASCADE,
    prompt_ledger_id  bigint REFERENCES prompt_ledger(id) ON DELETE CASCADE,
    verdict           text NOT NULL CHECK (verdict IN ('good', 'bad')),
    note              text,
    member_id         bigint NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    -- Exactly one subject. A verdict on nothing, or on two things, is not a verdict.
    CONSTRAINT run_verdicts_one_subject
        CHECK ((agent_run_id IS NOT NULL) <> (prompt_ledger_id IS NOT NULL))
);

-- One verdict per person per subject; changing your mind is an UPDATE, not another row.
CREATE UNIQUE INDEX run_verdicts_run_member_idx ON run_verdicts (agent_run_id, member_id)
    WHERE agent_run_id IS NOT NULL;
CREATE UNIQUE INDEX run_verdicts_ledger_member_idx ON run_verdicts (prompt_ledger_id, member_id)
    WHERE prompt_ledger_id IS NOT NULL;
CREATE INDEX run_verdicts_verdict_idx ON run_verdicts (verdict, created_at DESC);

COMMENT ON TABLE run_verdicts IS
    'A person''s good/bad judgement of one agent run or one assistant answer. Evidence for evaluations; never an automatic score.';

CREATE TRIGGER run_verdicts_touch BEFORE UPDATE ON run_verdicts
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- An agent may never grade: it would be marking its own homework, and the whole value of this
-- table is that a PERSON said it. Enforced here, not only in the handler.
CREATE FUNCTION run_verdicts_human_only() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM members WHERE id = NEW.member_id AND member_kind = 'human') THEN
        RAISE EXCEPTION 'A verdict is a person''s judgement; an agent may not give one.';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER run_verdicts_human_only_trg BEFORE INSERT OR UPDATE ON run_verdicts
    FOR EACH ROW EXECUTE FUNCTION run_verdicts_human_only();

ALTER TABLE run_verdicts ENABLE ROW LEVEL SECURITY;
-- Whoever may see the run (or the call) may see what was said about it; only its author may change
-- their own. app_can_see_agent()/the ledger's rule already decide who may see the subject.
CREATE POLICY run_verdicts_read ON run_verdicts FOR SELECT
    USING (member_id = app_current_member_id()
        OR (agent_run_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM agent_runs r WHERE r.id = run_verdicts.agent_run_id
                  AND app_can_see_run(r.agent_member_id, r.acting_member_id)))
        OR (prompt_ledger_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM prompt_ledger pl WHERE pl.id = run_verdicts.prompt_ledger_id
                  AND (pl.acting_member_id = app_current_member_id()
                    OR (pl.agent_member_id IS NOT NULL AND app_can_see_agent(pl.agent_member_id))
                    OR app_has_module('ledger')))));
CREATE POLICY run_verdicts_write ON run_verdicts FOR ALL
    USING (member_id = app_current_member_id()) WITH CHECK (member_id = app_current_member_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON run_verdicts TO app_rw;
GRANT SELECT ON run_verdicts TO app_records_ro;

CREATE VIEW mcp_run_verdicts WITH (security_barrier = true) AS
SELECT v.id AS run_verdict_id, v.agent_run_id, v.prompt_ledger_id, v.verdict, v.note,
       v.member_id, m.display_name AS member_name, v.created_at, v.updated_at
  FROM run_verdicts v JOIN members m ON m.id = v.member_id;
GRANT SELECT ON mcp_run_verdicts TO app_rw, app_records_ro;

COMMIT;
