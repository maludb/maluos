-- 020_seed_exams.sql
-- Exam catalog seed (plan §3.3). From third-party summaries of the v1.0 July 2026 exam
-- guides. *** An organizer MUST verify codes, names, and weights against the official
-- guides before launch. *** All four exams: 120 min, pass at 720/1000, Pearson VUE,
-- valid 12 months, free non-proctored renewal if on time. Retake policy and buddy/at-risk
-- windows are seeded in community_settings (002); defaults there match §3.3.
--
-- Idempotent: safe to re-run. Uses codes as the natural key.

BEGIN;

INSERT INTO exams (code, name, audience, guide_version, duration_minutes, question_count,
                   passing_score, validity_months, sort_order, official_guide_url)
VALUES
 ('CCAO-F','Claude Certified Associate – Foundations','Associate','v1.0 July 2026',120,60,720,12,1,NULL),
 ('CCDV-F','Claude Certified Developer – Foundations','Developer','v1.0 July 2026',120,53,720,12,2,NULL),
 ('CCAR-F','Claude Certified Architect – Foundations','Architect','v1.0 July 2026',120,60,720,12,3,NULL),
 ('CCAR-P','Claude Certified Architect – Professional','Architect','v1.0 July 2026',120,63,720,12,4,NULL)
ON CONFLICT (code) DO UPDATE
  SET name = EXCLUDED.name, audience = EXCLUDED.audience,
      guide_version = EXCLUDED.guide_version, question_count = EXCLUDED.question_count,
      sort_order = EXCLUDED.sort_order;

-- Domains per exam (name, weight %). Sort order follows list order.
WITH d(exam_code, name, weight, sort_order) AS (VALUES
  -- CCAO-F
  ('CCAO-F','Output Evaluation and Validation',            21.0, 1),
  ('CCAO-F','Workflow Integration and Solution Design',    16.0, 2),
  ('CCAO-F','Governance, Risk, and Responsible Use',        15.0, 3),
  ('CCAO-F','Prompting and Task Execution',                 14.0, 4),
  ('CCAO-F','Product and Model Selection',                  12.0, 5),
  ('CCAO-F','Configuration and Knowledge Management',       12.0, 6),
  ('CCAO-F','Troubleshooting and Optimization',             10.0, 7),
  -- CCDV-F
  ('CCDV-F','Applications and Integration',                 33.1, 1),
  ('CCDV-F','Model Selection and Optimization',             16.8, 2),
  ('CCDV-F','Agents and Workflows',                         14.7, 3),
  ('CCDV-F','Prompt and Context Engineering',               11.0, 4),
  ('CCDV-F','Tools and MCPs',                               10.6, 5),
  ('CCDV-F','Security and Safety',                           8.1, 6),
  ('CCDV-F','Claude Code',                                   3.1, 7),
  ('CCDV-F','Eval, Testing, and Debugging',                  2.6, 8),
  -- CCAR-F
  ('CCAR-F','Agentic Architecture and Orchestration',       27.0, 1),
  ('CCAR-F','Claude Code Configuration and Workflows',       20.0, 2),
  ('CCAR-F','Prompt Engineering and Structured Output',      20.0, 3),
  ('CCAR-F','Tool Design and MCP Integration',               18.0, 4),
  ('CCAR-F','Context Management and Reliability',            15.0, 5),
  -- CCAR-P
  ('CCAR-P','Integration',                                  19.0, 1),
  ('CCAR-P','Solution Design and Architecture',             17.0, 2),
  ('CCAR-P','Evaluation, Testing and Optimization',         16.0, 3),
  ('CCAR-P','Governance, Safety and Risk Management',        14.0, 4),
  ('CCAR-P','Stakeholder Communication and Lifecycle Management', 14.0, 5),
  ('CCAR-P','Claude Models, Prompting and Context Engineering',   13.0, 6),
  ('CCAR-P','Developer Productivity and Operational Enablement',   7.0, 7)
)
INSERT INTO exam_domains (exam_id, name, weight, sort_order)
SELECT e.id, d.name, d.weight, d.sort_order
FROM d JOIN exams e ON e.code = d.exam_code
ON CONFLICT (exam_id, name) DO UPDATE
  SET weight = EXCLUDED.weight, sort_order = EXCLUDED.sort_order;

COMMIT;
