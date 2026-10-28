-- 103: mcp_pipelines shows a pipeline that has no stages yet.
--
-- Found by the action smoke of 2026-09-19. The view inner-joined pipelines to deal_stages, so a
-- pipeline with no stage was invisible through it — and the actions server resolves a pipeline
-- BY this view: `pipeline_save` succeeded, and `pipeline_stage_save` then answered "No pipeline
-- matching…". A new pipeline could never be given its first stage by an agent or the command
-- bar. The PHP readers were written for a LEFT JOIN all along (find_pipelines() skips a NULL
-- stage_id, find_stages_for_pipeline() filters on it), so only the view was wrong.
--
-- Same columns, same order, same gate; an archived stage still does not appear — that test
-- moves into the join so it cannot turn the LEFT JOIN back into an inner one.
CREATE OR REPLACE VIEW mcp_pipelines AS
 SELECT p.id AS pipeline_id,
        p.name,
        p.is_default,
        s.id AS stage_id,
        s.name AS stage_name,
        s.stage_kind,
        s.probability,
        s.sort_order
   FROM pipelines p
   LEFT JOIN deal_stages s ON s.pipeline_id = p.id AND s.archived_at IS NULL
  WHERE p.archived_at IS NULL
    AND app_has_module('contacts'::text)
    AND NOT app_is_external();
