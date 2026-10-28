-- 107: the agent runner may read department handbooks — and nothing else in Documents.
--
-- Requirements, "The HR lifecycle": onboard = job description plus the department handbook in the
-- agent's context. The runner renders that context (docs/build-specs/agent-runtime-hermes.md,
-- "Profile rendering"), and until now app_runner had no way to read a handbook, so the persona went
-- without one.
--
-- app_runner gets no grant on `documents`: a view hands it exactly one thing, the live handbook of a
-- department — title and Markdown body, no files, no other kinds, nothing archived or deleted.
--
-- Which document is a department's handbook:
--   1. the one the department names (departments.handbook_document_id), when it is still live and
--      is something written here (a page of any kind — never an uploaded file);
--   2. otherwise the department's most recently updated live document of kind 'handbook'.
-- (2) exists because nothing sets the pointer yet: a handbook written in Documents for a department
-- should reach that department's agents without a second step.
--
-- Additive only. Run as postgres:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d maludb_os -f db/107_runner_department_handbooks.sql

BEGIN;

CREATE OR REPLACE VIEW runner_department_handbooks AS
SELECT d.id AS department_id, d.name AS department_name,
       h.id AS document_id, h.title, h.body_markdown, h.updated_at
  FROM departments d
  JOIN LATERAL (
        SELECT doc.id, doc.title, doc.body_markdown, doc.updated_at
          FROM documents doc
         WHERE doc.archived_at IS NULL AND doc.deleted_at IS NULL
           AND btrim(COALESCE(doc.body_markdown, '')) <> ''
           AND (doc.id = d.handbook_document_id                                 -- named: any written page
                OR (doc.kind = 'handbook' AND doc.department_id = d.id))
         ORDER BY (doc.id = d.handbook_document_id) DESC, doc.updated_at DESC, doc.id DESC
         LIMIT 1
       ) h ON true;

COMMENT ON VIEW runner_department_handbooks IS
    'The one live handbook per department, for the agent runner''s persona rendering. app_runner reads this and has no grant on documents.';

REVOKE ALL ON runner_department_handbooks FROM PUBLIC;
GRANT SELECT ON runner_department_handbooks TO app_runner;

COMMIT;
